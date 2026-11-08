from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    """Validated process configuration. Secrets are read from the environment only."""

    dsh_home: Path
    workspace_root: Path
    bearer_token: str
    model: str = "deepseek-v4-flash"
    reasoning_effort: str | None = None
    max_tokens: int = 32768
    port: int = 8765
    max_active_tasks: int = 1
    approval_timeout_seconds: int = 600
    question_timeout_seconds: int = 600

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        token = os.environ.get("MCP_BEARER_TOKEN", "").strip()
        if len(token) < 32:
            raise ValueError("MCP_BEARER_TOKEN must contain at least 32 characters")

        root_value = os.environ.get("DSH_WORKSPACE_ROOT", "").strip()
        if not root_value:
            raise ValueError("DSH_WORKSPACE_ROOT must point to an existing workspace directory")
        root = Path(root_value).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("DSH_WORKSPACE_ROOT must be a directory")

        home_value = os.environ.get("DSH_HOME", "").strip()
        if not home_value:
            raise ValueError("DSH_HOME must be a non-empty, dedicated Harness home")
        home = Path(home_value).expanduser().resolve()
        try:
            home.relative_to(root)
        except ValueError:
            pass
        else:
            raise ValueError("DSH_HOME must be outside DSH_WORKSPACE_ROOT so the agent cannot read bridge credentials or runtime state")
        home.mkdir(parents=True, exist_ok=True)

        port = _bounded_int("MCP_PORT", 8765, 1024, 65535)
        max_tokens = _bounded_int("DSH_MAX_TOKENS", 32768, 1024, 131072)
        return cls(
            dsh_home=home,
            workspace_root=root,
            bearer_token=token,
            model=os.environ.get("DSH_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash",
            reasoning_effort=os.environ.get("DSH_REASONING_EFFORT", "").strip() or None,
            max_tokens=max_tokens,
            port=port,
            max_active_tasks=_bounded_int("MCP_MAX_ACTIVE_TASKS", 1, 1, 1),
            approval_timeout_seconds=_bounded_int("MCP_APPROVAL_TIMEOUT_SECONDS", 600, 30, 3600),
            question_timeout_seconds=_bounded_int("MCP_QUESTION_TIMEOUT_SECONDS", 600, 30, 3600),
        )


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value
