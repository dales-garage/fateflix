import contextlib
import importlib.util
import io
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "capabilities/secrets"
sys.path.insert(0, str(DIRECTORY))


def module(name):
    spec = importlib.util.spec_from_file_location(name, DIRECTORY / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


provision = module("provision")
role = module("role")
installer = module("provision-secrets")


class SecretOwnership(unittest.TestCase):
    def test_independent_staging_manifest_and_preserved_namespaces(self):
        production = tomllib.loads((DIRECTORY / "secretspec.toml").read_text())
        staging = tomllib.loads((DIRECTORY / "secretspec-staging.toml").read_text())
        self.assertEqual(production["project"]["name"], "nixflix")
        self.assertEqual(staging["project"]["name"], "nixflix-staging")
        self.assertEqual(set(staging["profiles"]), {"default"})
        self.assertEqual(
            staging["profiles"]["default"], production["profiles"]["default"]
        )
        for filename, profiles in [
            ("secretspec-notifiarr.toml", {"notifiarr"}),
            ("secretspec-router.toml", {"router_web", "public_tls"}),
        ]:
            manifest = tomllib.loads((DIRECTORY / filename).read_text())
            self.assertEqual(manifest["project"]["name"], "nixflix")
            self.assertEqual(set(manifest["profiles"]), profiles)

    def test_installed_role_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mode"
            with self.assertRaises(OSError):
                role.installed_role(path)
            for value in ["", "unknown", "production\nstaging"]:
                path.write_text(value)
                with self.assertRaises(ValueError):
                    role.installed_role(path)
            path.write_text("staging\n")
            self.assertEqual(role.installed_role(path), "staging")
            with self.assertRaises(ValueError):
                role.installed_role(path, production_only=True)

    def test_production_only_commands_reject_staging_before_provider(self):
        for operation in ["provision-notifications", "provision-notifiarr"]:
            with patch.object(sys, "argv", ["provision.py", operation]), patch.object(
                provision, "installed_role", side_effect=ValueError
            ), patch.object(provision.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    provision.main()
                run.assert_not_called()
            with self.assertRaises(ValueError):
                provision.command(operation, "staging", "pass")
        with self.assertRaises(ValueError):
            provision.command("provision", "unknown", "pass")

    def test_provider_selection_and_no_install_on_resolution_failure(self):
        for provider, expected in [
            (None, "pass"),
            ("", "pass"),
            ("keyring", "keyring"),
        ]:
            environment = {} if provider is None else {"SECRETSPEC_PROVIDER": provider}
            canary = secrets.token_hex(32)
            failed = subprocess.CompletedProcess(
                [], 1, canary.encode(), canary.encode()
            )
            output = io.StringIO()
            with patch.dict(os.environ, environment, clear=True), patch.object(
                sys, "argv", ["provision.py", "provision"]
            ), patch.object(
                provision, "installed_role", return_value="staging"
            ), patch.object(
                provision.subprocess, "run", return_value=failed
            ) as run, contextlib.redirect_stdout(
                output
            ), contextlib.redirect_stderr(
                output
            ):
                with self.assertRaises(ValueError) as error:
                    provision.main()
                self.assertEqual(run.call_count, 1)
                cmd = run.call_args.args[0]
                self.assertEqual(cmd[cmd.index("--provider") + 1], expected)
                self.assertTrue(cmd[2].endswith("secretspec-staging.toml"))
                self.assertNotIn(canary, str(error.exception) + output.getvalue())

    def test_runtime_generation_and_interrupted_publication(self):
        canary = secrets.token_hex(32)
        values = {key: canary for key in installer.KEYS}
        values["SMB_CREDENTIALS"] = "username=test\npassword=" + canary + "\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "credentials"
            installer.install(values, root)
            previous = os.readlink(root / "current")
            # Interrupted prior generation and stale publication link are repaired.
            (root / "generation-interrupted").mkdir(mode=0o700)
            (root / ".next").symlink_to("generation-interrupted")
            with patch.object(installer.os, "replace", side_effect=OSError("failure")):
                with self.assertRaises(OSError):
                    installer.install(dict(values, SONARR_API_KEY="changed"), root)
            self.assertEqual(os.readlink(root / "current"), previous)
            self.assertEqual((root / "current/sonarr").read_text(), canary)
            installer.install(dict(values, SONARR_API_KEY="changed"), root)
            self.assertFalse((root / ".next").exists())
            self.assertTrue(
                installer.valid_generation(
                    root / "current", root, dict(values, SONARR_API_KEY="changed")
                )
            )


if __name__ == "__main__":
    unittest.main()
