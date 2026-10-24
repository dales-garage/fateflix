"""Operator compatibility entry point; the secrets capability owns resolution."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "capabilities/secrets"))
from router_credentials import dns_token, dashboard_password  # noqa: F401,E402
