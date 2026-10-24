#!/usr/bin/env python3
"""Operator entry point for the secrets capability's production pass importer."""

from pathlib import Path
import runpy
import sys

source = Path(__file__).resolve().parents[1] / "modules/_modules/secrets"
sys.path.insert(0, str(source))
runpy.run_path(str(source / "import-pass.py"), run_name="__main__")
