import contextlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "extra", ROOT / "scripts/extra_dependencies.py"
)
extra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extra)


def catalog(version="1.0", digest="A"):
    return {
        "Plugin": {
            "guid": "one",
            "versions": [
                {
                    "version": version,
                    "targetAbi": "12.0",
                    "sourceUrl": "https://example.invalid/plugin.zip",
                    "hash": "sha256-" + digest * 43 + "=",
                }
            ],
        }
    }


class CatalogTests(unittest.TestCase):
    def test_disappearing_sources_and_old_versions_are_retained(self):
        before = {
            **catalog(),
            "Offline": {"guid": "two", "versions": catalog()["Plugin"]["versions"]},
        }
        result = extra.merge_catalog(before, catalog("2.0"))
        self.assertIn("Offline", result)
        self.assertEqual(
            [v["version"] for v in result["Plugin"]["versions"]], ["2.0", "1.0"]
        )
        self.assertEqual(extra.merge_catalog(result, catalog("2.0")), result)

    def test_empty_unhashed_republished_or_renamed_plugins_fail(self):
        invalid = [
            {},
            catalog(digest="bad"),
            catalog(digest="B"),
            {"Plugin": {**catalog()["Plugin"], "guid": "changed"}},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                extra.merge_catalog(catalog(), value)


class ImageTests(unittest.TestCase):
    def test_discovery_does_not_pass_github_write_credentials(self):
        with patch.dict(
            "os.environ", {"GH_TOKEN": "canary", "GITHUB_TOKEN": "canary"}
        ), patch.object(extra.subprocess, "run") as run:
            extra.run("skopeo", "inspect", "docker://example.invalid/image")
        self.assertNotIn("GH_TOKEN", run.call_args.kwargs["env"])
        self.assertNotIn("GITHUB_TOKEN", run.call_args.kwargs["env"])

    def test_platform_and_digest_must_be_valid(self):
        policy = json.loads((ROOT / extra.POLICY).read_text())
        image = policy["supplementalImages"][0]
        source = (ROOT / image["path"]).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / image["path"]
            path.parent.mkdir(parents=True)
            path.write_text(source)
            good = {
                "Digest": "sha256:" + "a" * 64,
                "Architecture": "amd64",
                "Os": "linux",
            }
            for invalid in [
                {**good, "Architecture": "arm64"},
                {**good, "Digest": "oops"},
                {**good, "Os": "windows"},
            ]:
                with patch.object(
                    extra, "run", return_value=json.dumps(invalid)
                ), self.assertRaises(ValueError):
                    extra.refresh_images(root, policy)
                self.assertEqual(path.read_text(), source)
            with patch.object(extra, "run", return_value=json.dumps(good)) as run:
                extra.refresh_images(root, policy)
            self.assertIn("@sha256:" + "a" * 64, path.read_text())
            self.assertIn("--override-arch", run.call_args.args)
            self.assertIn(
                "docker://docker.io/caronc/apprise:latest", run.call_args.args
            )


class CoverageTests(unittest.TestCase):
    def test_current_checkout_has_complete_pin_ownership(self):
        result = extra.audit(ROOT)
        self.assertEqual(result["unclassified"], [])
        self.assertTrue(
            any(e["owner"] == "supplemental" for e in result["dependencies"])
        )
        self.assertTrue(
            any(
                e["name"] == "trash-guides" and e["owner"] == "manual-policy"
                for e in result["dependencies"]
                if "name" in e
            )
        )

    def test_ci_validator_and_python_pins_are_owned_not_unversioned(self):
        result = extra.audit(ROOT)
        pins = {
            entry.get("name"): entry
            for entry in result["dependencies"]
            if entry.get("name") in {"renovate", "PyYAML"}
        }
        self.assertEqual(set(pins), {"renovate", "PyYAML"})
        for entry in pins.values():
            self.assertEqual(entry["owner"], "renovate")
            self.assertRegex(entry["pin"], r"^\d+\.\d+\.\d+$")
        self.assertFalse(
            any(
                entry["owner"] == "unversioned-tooling"
                for entry in result["dependencies"]
            )
        )

    def test_new_image_and_container_and_package_require_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in [
                extra.POLICY,
                "renovate.json",
                "hosts/nixflix/containers.json",
                "flake.lock",
                ".github/package-versions.json",
                ".github/workflows/ci.yml",
                ".github/requirements-ci.txt",
            ]:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_bytes((ROOT / name).read_bytes())
            new = root / "new.nix"
            new.write_text('{image = "example.invalid/new@sha256:' + "a" * 64 + '";}')
            containers = json.loads(
                (root / "hosts/nixflix/containers.json").read_text()
            )
            containers["new"] = "example.invalid/new@sha256:" + "a" * 64
            (root / "hosts/nixflix/containers.json").write_text(json.dumps(containers))
            (root / ".github/package-versions.json").write_text(
                '{"Unmanaged/App":"1.0.0"}'
            )
            with patch.object(extra, "tracked", return_value=["new.nix"]):
                unknown = extra.audit(root)["unclassified"]
            self.assertEqual(len(unknown), 3)


class TransactionTests(unittest.TestCase):
    def test_write_failure_restores_already_published_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root, scratch = Path(directory) / "original", Path(directory) / "prepared"
            root.mkdir()
            scratch.mkdir()
            originals = {"one": b"old one", "two": b"old two"}
            for name, contents in originals.items():
                (root / name).write_bytes(contents)
                (scratch / name).write_bytes(b"new")
            replace = extra.os.replace

            def fail_second(source, target):
                if Path(target).name == "two":
                    raise OSError("write failed")
                replace(source, target)

            with patch.object(
                extra.os, "replace", side_effect=fail_second
            ), self.assertRaises(OSError):
                extra.publish_files(root, scratch, originals, list(originals))
            self.assertEqual(
                originals, {p.name: p.read_bytes() for p in root.iterdir()}
            )

    @contextlib.contextmanager
    def repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            for name in extra.OUTPUTS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / name).read_bytes())
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "commit",
                    "-qm",
                    "Fixture",
                ],
                check=True,
            )
            with patch.object(
                extra,
                "audit",
                return_value={
                    "unclassified": [],
                    "policy": json.loads((ROOT / extra.POLICY).read_text()),
                },
            ):
                yield root

    def change(self, root, policy):
        path = root / extra.OUTPUTS[0]
        pattern, match = extra.image_match(
            path.read_text(), policy["supplementalImages"][0]["repository"]
        )
        path.write_text(
            pattern.sub(
                lambda m: m[1] + match[2].split("@")[0] + "@sha256:" + "a" * 64 + m[3],
                path.read_text(),
            )
        )

    def test_failure_does_not_touch_original_and_removes_worktree(self):
        with self.repository() as root:
            before = {p: (root / p).read_bytes() for p in extra.OUTPUTS}

            def fail(scratch, policy):
                self.change(scratch, policy)
                raise RuntimeError("manifest unavailable")

            with patch.object(
                extra, "refresh_checkout", side_effect=fail
            ), self.assertRaises(RuntimeError):
                extra.refresh(root)
            self.assertEqual(
                before, {p: (root / p).read_bytes() for p in extra.OUTPUTS}
            )
            self.assertEqual(
                extra.run(
                    "git", "worktree", "list", "--porcelain", cwd=root, capture=True
                ).count("worktree "),
                1,
            )

    def test_success_and_dry_run_use_real_worktrees(self):
        with self.repository() as root:
            before = (root / extra.OUTPUTS[0]).read_bytes()
            with patch.object(extra, "refresh_checkout", side_effect=self.change):
                preview = extra.refresh(root, dry_run=True)
                self.assertEqual((root / extra.OUTPUTS[0]).read_bytes(), before)
                applied = extra.refresh(root)
            self.assertEqual(preview["changed"], [extra.OUTPUTS[0]])
            self.assertEqual(applied["changed"], preview["changed"])
            self.assertNotEqual((root / extra.OUTPUTS[0]).read_bytes(), before)

    def test_dirty_checkout_and_unrelated_edits_are_rejected(self):
        with self.repository() as root:
            (root / "untracked").write_text("keep")
            with self.assertRaisesRegex(ValueError, "clean checkout"):
                extra.refresh(root)
            (root / "untracked").unlink()

            def unrelated(scratch, policy):
                self.change(scratch, policy)
                path = scratch / extra.OUTPUTS[0]
                path.write_text(path.read_text() + "\n# unrelated change\n")

            with patch.object(
                extra, "refresh_checkout", side_effect=unrelated
            ), self.assertRaisesRegex(ValueError, "outside the image pin"):
                extra.refresh(root)

    def test_concurrent_edit_prevents_publication(self):
        with self.repository() as root:
            before = (root / extra.OUTPUTS[0]).read_bytes()

            def concurrent(scratch, policy):
                self.change(scratch, policy)
                (root / "concurrent").write_text("keep")

            with patch.object(
                extra, "refresh_checkout", side_effect=concurrent
            ), self.assertRaisesRegex(ValueError, "Checkout changed"):
                extra.refresh(root)
            self.assertEqual((root / extra.OUTPUTS[0]).read_bytes(), before)

    def test_untracked_discovery_output_is_rejected(self):
        with self.repository() as root:
            before = (root / extra.OUTPUTS[0]).read_bytes()

            def unrelated(scratch, policy):
                self.change(scratch, policy)
                (scratch / "unexpected.nix").write_text("{}")

            with patch.object(
                extra, "refresh_checkout", side_effect=unrelated
            ), self.assertRaisesRegex(ValueError, "outside the supplemental allowlist"):
                extra.refresh(root)
            self.assertEqual((root / extra.OUTPUTS[0]).read_bytes(), before)


class HookTests(unittest.TestCase):
    def test_post_merge_hook_uses_trusted_main_and_explicit_dispatch(self):
        # BaseLoader preserves GitHub's `on` key rather than treating it as YAML 1.1's boolean.
        workflow = yaml.load(
            (ROOT / ".github/workflows/update-packages.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        self.assertIn("closed", workflow["on"]["pull_request_target"]["types"])
        job = workflow["jobs"]["extra-dependencies"]
        self.assertIn("merged == true", job["if"])
        self.assertIn("renovate[bot]", job["if"])
        self.assertIn("head.repo.full_name == github.repository", job["if"])
        checkout = next(
            s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout")
        )
        self.assertEqual(checkout["with"]["ref"], "main")
        self.assertIn("action != 'closed'", workflow["jobs"]["generate"]["if"])


if __name__ == "__main__":
    unittest.main()
