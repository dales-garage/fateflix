import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
CADDY = Path("integrations/nixflix/compatibility/caddy")
NAVIDROME = Path("integrations/nixflix/plugins/navidrome")
SHA = "80962887e4c680abfd1b11ce1403fa8cc0fdd3d6"
VERSION = "v0.0.0-20250618171559-80962887e4c6"
HASH = "sha256-" + "B" * 43 + "="


class PluginUpdaters(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(
            os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"]
        )
        self.log = self.root / "calls.jsonl"
        self.env["TEST_CALLS"] = str(self.log)
        for directory in [CADDY, NAVIDROME]:
            (self.repo / directory).mkdir(parents=True)
            shutil.copyfile(
                ROOT / directory / "update.sh", self.repo / directory / "update.sh"
            )
        shutil.copyfile(ROOT / CADDY / "default.nix", self.repo / CADDY / "default.nix")
        self.stub(
            "nix",
            """
import json, os, sys
with open(os.environ['TEST_CALLS'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1] == 'build':
    if os.environ.get('TEST_CADDY'):
        print('got: ' + os.environ['TEST_HASH'], file=sys.stderr)
        sys.exit(1)
    if 'bad' in sys.argv[2]:
        sys.exit(1)
    print(os.environ['TEST_OUTPUT'])
elif '--json' in sys.argv:
    print(os.environ['TEST_PLUGINS'])
elif os.environ.get('TEST_FAIL_CODEGEN'):
    sys.exit(1)
else:
    print('# generated fixture')
""",
        )

    def stub(self, name, source):
        path = self.bin / name
        path.write_text("#!" + sys.executable + "\n" + source)
        path.chmod(0o755)

    def run_updater(self, directory, *args):
        return subprocess.run(
            ["bash", str(self.repo / directory / "update.sh"), *args],
            cwd=self.repo,
            env=self.env,
            text=True,
            capture_output=True,
        )

    def caddy_metadata(self, *, sha=SHA, version=VERSION):
        self.env.update(
            TEST_CADDY="1",
            TEST_HASH=HASH,
            TEST_METADATA=json.dumps(
                {
                    "Version": version,
                    "Origin": {
                        "Hash": sha,
                        "VCS": "git",
                        "URL": "https://github.com/caddyserver/replace-response",
                    },
                }
            ),
        )
        self.stub(
            "curl",
            """
import os, sys
assert sys.argv[-1].startswith('https://proxy.golang.org/')
assert sys.argv[-1].endswith('.info')
print(os.environ['TEST_METADATA'])
""",
        )

    def test_caddy_force_refresh_uses_commit_metadata_without_github_api(self):
        self.caddy_metadata()
        result = self.run_updater(CADDY, SHA, "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(HASH, (self.repo / CADDY / "default.nix").read_text())
        self.assertIn(VERSION, (self.repo / CADDY / "default.nix").read_text())
        self.assertTrue(self.log.exists())

    def test_caddy_unchanged_commit_skips_build_without_force(self):
        self.caddy_metadata()
        result = self.run_updater(CADDY, SHA)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log.exists())

    def test_caddy_rejects_mismatched_commit_before_modifying_package(self):
        self.caddy_metadata(sha="a" * 40)
        path = self.repo / CADDY / "default.nix"
        before = path.read_bytes()
        result = self.run_updater(CADDY, SHA, "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.log.exists())

    def test_caddy_rejects_invalid_module_version_before_modifying_package(self):
        self.caddy_metadata(version='bad"; malicious')
        path = self.repo / CADDY / "default.nix"
        before = path.read_bytes()
        result = self.run_updater(CADDY, SHA, "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(path.read_bytes(), before)

    def navidrome_package(self, layout):
        output = self.root / "package with spaces"
        directory = output / layout
        directory.mkdir(parents=True)
        bundle = directory / "bundle.ndp"
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr(
                "manifest.json",
                json.dumps({"name": "Fixture", "config": {"schema": {}}}),
            )
        self.env["TEST_OUTPUT"] = str(output)
        self.env["TEST_PLUGINS"] = json.dumps(
            {
                "fixture": {
                    "drvPath": "/nix/store/good.drv",
                    "apiId": "bundle",
                    "realBundleName": "bundle",
                }
            }
        )
        generated = self.repo / NAVIDROME / "gen"
        generated.mkdir()
        (generated / "dropped-plugin.nix").write_text("previous generation\n")
        return bundle, generated

    def check_layout(self, layout):
        _, generated = self.navidrome_package(layout)
        result = self.run_updater(NAVIDROME)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (generated / "fixture-plugin.nix").read_text(), "# generated fixture\n"
        )
        self.assertFalse((generated / "dropped-plugin.nix").exists())

    def test_navidrome_reads_legacy_bundle_layout(self):
        self.check_layout("share")

    def test_navidrome_reads_new_bundle_layout(self):
        self.check_layout("share/plugins")

    def test_navidrome_rejects_ambiguous_bundles_and_preserves_generation(self):
        bundle, generated = self.navidrome_package("share/plugins")
        shutil.copyfile(bundle, bundle.with_name("extra.ndp"))
        result = self.run_updater(NAVIDROME)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("found 2", result.stderr)
        self.assertEqual(list(generated.iterdir()), [generated / "dropped-plugin.nix"])

    def test_navidrome_failed_build_keeps_previous_generation(self):
        _, generated = self.navidrome_package("share/plugins")
        plugins = json.loads(self.env["TEST_PLUGINS"])
        plugins["z-failure"] = dict(plugins["fixture"], drvPath="/nix/store/bad.drv")
        self.env["TEST_PLUGINS"] = json.dumps(plugins)
        result = self.run_updater(NAVIDROME)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Build failed for z-failure", result.stderr)
        self.assertEqual(list(generated.iterdir()), [generated / "dropped-plugin.nix"])
        self.assertEqual(
            (generated / "dropped-plugin.nix").read_text(), "previous generation\n"
        )

    def test_navidrome_failed_codegen_keeps_previous_generation(self):
        _, generated = self.navidrome_package("share/plugins")
        self.env["TEST_FAIL_CODEGEN"] = "1"
        result = self.run_updater(NAVIDROME)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Codegen failed", result.stderr)
        self.assertEqual(list(generated.iterdir()), [generated / "dropped-plugin.nix"])


if __name__ == "__main__":
    unittest.main()
