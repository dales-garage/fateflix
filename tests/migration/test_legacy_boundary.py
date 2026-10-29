import contextlib
import importlib.util
import io
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "legacy/ubuntu-migration"
spec = importlib.util.spec_from_file_location("legacy_migration", ARCHIVE / "run.py")
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


class LegacyMigrationBoundaryTests(unittest.TestCase):
    def test_manual_app_preserves_historical_python_dependencies(self):
        source = (ARCHIVE / "app.nix").read_text()
        self.assertIn("p.configobj", source)
        self.assertIn("p.pyyaml", source)

    def test_no_command_and_help_do_not_execute_an_operation(self):
        with patch.object(legacy.subprocess, "run") as run, contextlib.redirect_stdout(
            io.StringIO()
        ):
            legacy.main([])
            with self.assertRaises(SystemExit) as result:
                legacy.main(["--help"])
            self.assertEqual(result.exception.code, 0)
            run.assert_not_called()

    def test_missing_acknowledgement_and_unknown_commands_fail_closed(self):
        for arguments in (
            ["snapshot", "/synthetic"],
            ["--confirm-legacy-operation", "../snapshot"],
        ):
            with self.subTest(arguments=arguments), patch.object(
                legacy.subprocess, "run"
            ) as run, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    legacy.main(arguments)
                self.assertEqual(result.exception.code, 2)
                run.assert_not_called()

    def test_explicit_dispatch_only_passes_the_selected_command_and_arguments(self):
        with patch.object(legacy.subprocess, "run") as run:
            legacy.main(
                ["--confirm-legacy-operation", "snapshot", "/synthetic", "--resume"]
            )
        run.assert_called_once_with(
            [sys.executable, str(ARCHIVE / "snapshot.py"), "/synthetic", "--resume"],
            check=True,
        )

    def test_old_aliases_are_removed_and_archive_sources_are_not_normal_scripts(self):
        apps = (ROOT / "scripts/apps.nix").read_text()
        self.assertIn(
            "legacy-ubuntu-migration = import ../legacy/ubuntu-migration/app.nix", apps
        )
        for command in legacy.COMMANDS:
            with self.subTest(command=command):
                self.assertNotRegex(apps, rf"(?m)^\s*{re.escape(command)}\s*=")
                self.assertFalse((ROOT / "scripts" / (command + ".py")).exists())
                self.assertTrue((ARCHIVE / (command + ".py")).is_file())

    def test_runtime_and_workflows_do_not_reference_archived_operations(self):
        forbidden = ["legacy/ubuntu-migration"] + [
            "scripts/" + name + ".py" for name in legacy.COMMANDS
        ]
        for directory in ("capabilities", "hosts", "modules", ".github/workflows"):
            for path in (ROOT / directory).rglob("*"):
                if path.is_file() and path.suffix in {".nix", ".yml", ".yaml"}:
                    with self.subTest(path=str(path.relative_to(ROOT))):
                        source = path.read_text()
                        for entry in forbidden:
                            self.assertNotIn(entry, source)
        self.assertFalse((ROOT / "tests/migration/test_snapshot.py").exists())
        self.assertNotIn(
            'module("reassign-profiles")',
            (ROOT / "tests/migration/test_migration.py").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
