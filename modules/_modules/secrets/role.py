"""Installed host role is the sole authority for credential namespaces."""

from pathlib import Path


def installed_role(path=Path("/etc/nixflix/mode"), production_only=False):
    role = path.read_text().strip()
    if role not in {"production", "staging"}:
        raise ValueError("Unknown installed host role")
    if production_only and role != "production":
        raise ValueError("This credential operation requires production")
    return role
