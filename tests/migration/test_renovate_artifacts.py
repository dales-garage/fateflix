import contextlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "artifacts", ROOT / "scripts/renovate-artifacts.py"
)
artifacts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifacts)


class ArtifactTests(unittest.TestCase):
    def baseline(self):
        return {
            "packages": {
                "Notifiarr/notifiarr": "0.9.7",
                "Maintainerr/Maintainerr": "3.31.0",
                "caddyserver/replace-response": "master@" + "a" * 40,
            },
            "nixpkgs": {"rev": "old"},
            "containers": {"stash": "old"},
        }

    def test_unchanged_inputs_do_not_run_updaters(self):
        self.assertEqual(artifacts.commands(self.baseline(), self.baseline()), [])

    def test_media_group_uses_exact_version_and_refreshes_only_media_artifacts(self):
        old, new = self.baseline(), self.baseline()
        new["packages"]["Maintainerr/Maintainerr"] = "3.32.0"
        self.assertEqual(
            artifacts.commands(old, new),
            [
                ["bash", "pkgs/maintainerr/update.sh", "3.32.0"],
                [
                    "bash",
                    "integrations/nixflix/plugins/jellyfin/update.sh",
                    "--manifest-only",
                ],
            ],
        )

    def test_major_upgrade_does_not_bundle_unrelated_plugin_refresh(self):
        old, new = self.baseline(), self.baseline()
        new["packages"]["Notifiarr/notifiarr"] = "1.0.0"
        self.assertEqual(
            artifacts.commands(old, new, grouped_media=False),
            [
                ["python3", "pkgs/notifiarr/update.py", "1.0.0"],
            ],
        )

    def test_nixpkgs_refresh_regenerates_caddy_hash_even_with_same_plugin_commit(self):
        old, new = self.baseline(), self.baseline()
        new["nixpkgs"]["rev"] = "new"
        self.assertEqual(
            artifacts.commands(old, new),
            [
                [
                    "bash",
                    "integrations/nixflix/compatibility/caddy/update.sh",
                    "a" * 40,
                    "--force",
                ],
                [
                    "bash",
                    "integrations/nixflix/plugins/navidrome/update.sh",
                ],
            ],
        )

    def test_generate_and_publish_on_an_actual_git_branch(self):
        # Exercise data import, file generation, a fast-forward push and dispatch
        # together; substitute only GitHub metadata and the expensive Nix updater.
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], text=True, stderr=subprocess.DEVNULL
                )

            git("init", "--bare", "remote.git")
            git("init", "-b", "main", "checkout")
            with contextlib.chdir("checkout"):
                git("config", "user.name", "Fixture")
                git("config", "user.email", "fixture@example.invalid")
                git("remote", "add", "origin", "../remote.git")
                baseline = self.baseline()
                files = {
                    artifacts.VERSIONS: json.dumps(baseline["packages"]),
                    "flake.lock": json.dumps(
                        {"nodes": {"nixpkgs": {"locked": {"rev": "a" * 40}}}}
                    ),
                    "hosts/nixflix/containers.json": json.dumps(baseline["containers"]),
                    "pkgs/notifiarr/default.nix": 'version = "0.9.7";',
                    "pkgs/maintainerr/default.nix": 'version = "3.31.0";',
                    "integrations/nixflix/compatibility/caddy/default.nix": "replace-response@"
                    + "a" * 12,
                }
                for name, content in files.items():
                    Path(name).parent.mkdir(parents=True, exist_ok=True)
                    Path(name).write_text(content)
                Path(artifacts.STATE).write_text(
                    json.dumps({"inputs": artifacts.fingerprint(artifacts.inputs())})
                )
                git("add", ".")
                git("commit", "-qm", "Base")
                base = git("rev-parse", "HEAD").strip()
                branch = "renovate/media-applications"
                git("checkout", "-b", branch)
                versions = baseline["packages"]
                versions["Maintainerr/Maintainerr"] = "3.32.0"
                Path(artifacts.VERSIONS).write_text(json.dumps(versions))
                git("add", ".")
                git("commit", "-qm", "Requested update")
                head = git("rev-parse", "HEAD").strip()
                git("push", "origin", branch)
                git("checkout", "main")
                pr = {"head": {"sha": head, "ref": branch}, "base": {"sha": base}}
                dispatched = []

                def run(*args, capture=False):
                    if args[:2] == ("nix", "develop"):
                        if "pkgs/maintainerr/update.sh" in args:
                            self.assertEqual(args[-1], "3.32.0")
                            Path("pkgs/maintainerr/default.nix").write_text(
                                'version = "3.32.0";'
                            )
                        return
                    if args[:2] == ("nix", "fmt"):
                        return
                    if args[:2] == ("gh", "workflow"):
                        dispatched.append(args)
                        return
                    return subprocess.check_output(
                        args, text=True, stderr=subprocess.DEVNULL
                    )

                payload = str(Path(directory) / "payload.json")
                with patch.object(artifacts, "pr_info", return_value=pr), patch.object(
                    artifacts, "run", side_effect=run
                ):
                    artifacts.generate(123, payload)
                    generated = json.loads(Path(payload).read_text())["files"]
                    self.assertEqual(
                        set(generated),
                        {artifacts.STATE, "pkgs/maintainerr/default.nix"},
                    )
                    # The write job starts with a clean reviewed base checkout.
                    git("reset", "--hard", base)
                    artifacts.publish(payload)
                self.assertEqual(git("rev-parse", "HEAD^").strip(), head)
                self.assertEqual(
                    git("ls-remote", "origin", branch).split()[0],
                    git("rev-parse", "HEAD").strip(),
                )
                self.assertEqual(len(dispatched), 1)
                artifacts.check()

    def test_lock_refresh_cannot_substitute_a_repository_or_input(self):
        old = {
            "nodes": {
                "nixpkgs": {
                    "locked": {
                        "owner": "NixOS",
                        "repo": "nixpkgs",
                        "type": "github",
                        "rev": "a" * 40,
                        "narHash": "sha256-" + "A" * 43 + "=",
                    }
                }
            }
        }
        new = json.loads(json.dumps(old))
        new["nodes"]["nixpkgs"]["locked"]["rev"] = "b" * 40
        artifacts.validate_lock(old, new)
        new["nodes"]["nixpkgs"]["locked"]["owner"] = "untrusted"
        with self.assertRaisesRegex(ValueError, "identities"):
            artifacts.validate_lock(old, new)

    def test_package_requests_reject_downgrades_and_shell_strings(self):
        old = {
            "Notifiarr/notifiarr": "0.9.7",
            "caddyserver/replace-response": "master@" + "a" * 40,
        }
        for value in ["0.9.6", "1.0.0; echo nope", "1.0.0-beta.1"]:
            with self.assertRaises(ValueError):
                artifacts.validate_versions(old, {**old, "Notifiarr/notifiarr": value})
        artifacts.validate_versions(old, {**old, "Notifiarr/notifiarr": "1.0.0"})

    def test_state_is_order_independent_but_changes_with_inputs(self):
        self.assertEqual(
            artifacts.fingerprint({"a": 1, "b": 2}),
            artifacts.fingerprint({"b": 2, "a": 1}),
        )
        self.assertNotEqual(
            artifacts.fingerprint({"a": 1}), artifacts.fingerprint({"a": 2})
        )

    def test_publisher_rejects_unrelated_files_before_accessing_github(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "payload.json"
            payload.write_text(
                json.dumps({"files": {".github/workflows/ci.yml": "bad"}})
            )
            with patch.object(artifacts, "pr_info") as github:
                with self.assertRaisesRegex(ValueError, "allowlist"):
                    artifacts.publish(payload)
                github.assert_not_called()

    def test_publisher_rejects_a_race_without_touching_the_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "payload.json"
            payload.write_text(
                json.dumps({"pr": 1, "head": "old", "files": {artifacts.STATE: "{}"}})
            )
            with patch.object(
                artifacts, "pr_info", return_value={"head": {"sha": "new"}}
            ), patch.object(artifacts, "run") as run:
                with self.assertRaisesRegex(ValueError, "changed during generation"):
                    artifacts.publish(payload)
                run.assert_not_called()

    def test_required_check_rejects_pending_artifacts(self):
        with patch.object(
            artifacts, "inputs", return_value={"version": "new"}
        ), patch.object(artifacts.Path, "read_text", return_value='{"inputs":"old"}'):
            with self.assertRaisesRegex(ValueError, "pending"):
                artifacts.check()

    def test_publisher_does_not_allow_traversal(self):
        self.assertFalse(
            artifacts.output_allowed(
                "integrations/nixflix/plugins/navidrome/gen/../../../../flake.nix"
            )
        )
        self.assertFalse(artifacts.output_allowed("scripts/renovate-artifacts.py"))
        self.assertTrue(
            artifacts.output_allowed(
                "integrations/nixflix/plugins/navidrome/gen/lyrics-plugin.nix"
            )
        )


if __name__ == "__main__":
    unittest.main()
