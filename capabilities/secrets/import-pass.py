#!/usr/bin/env python3
"""Historical importer command; JSON on stdin is stored with age-backed Passage."""

import json
import subprocess
import sys

from role import installed_role
from passage_store import import_values

try:
    installed_role(production_only=True)
except (OSError, ValueError):
    sys.exit("Passage import requires an installed production host role.")

try:
    import_values(json.load(sys.stdin))
except (OSError, ValueError, subprocess.SubprocessError):
    sys.exit("Passage import failed; credential output suppressed.")
print("Imported credentials into age-backed Passage; values were not logged.")
