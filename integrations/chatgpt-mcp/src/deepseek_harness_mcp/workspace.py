from __future__ import annotations

import re
from pathlib import Path

_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def resolve_workspace(candidate: str | None, root: Path) -> Path:
    """Resolve an existing workspace and reject traversal or symlinks outside root."""
    approved_root = root.expanduser().resolve(strict=True)
    raw = (candidate or "").strip()
    requested = Path(raw).expanduser() if raw else approved_root
    if not requested.is_absolute():
        requested = approved_root / requested
    resolved = requested.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("workspace_path must identify an existing directory")
    try:
        resolved.relative_to(approved_root)
    except ValueError as exc:
        raise ValueError("workspace_path must remain inside DSH_WORKSPACE_ROOT") from exc
    return resolved


def validate_session_id(value: str) -> str:
    candidate = value.strip()
    if not _SESSION_ID.fullmatch(candidate):
        raise ValueError("session_id must be 1-80 letters, digits, dots, underscores, or hyphens")
    return candidate
