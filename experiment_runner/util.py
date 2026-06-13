"""Small shared utilities."""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from experiment_runner.models import ModelInfo


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def run_text_command(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def script_dir() -> Path:
    """Repository root (parent of the ``experiment_runner`` package)."""
    return Path(__file__).resolve().parent.parent


def sanitize_slug(s: str, *, max_len: int = 64) -> str:
    """Safe fragment for git branch paths and filenames."""
    t = (s or "").strip().replace("\\", "-").replace("/", "-").replace(" ", "_")
    t = re.sub(r"[^a-zA-Z0-9._-]+", "-", t)
    t = re.sub(r"-{2,}", "-", t).strip("-_.")
    if not t:
        t = "default"
    return t[:max_len]


def non_empty_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def resolve_label_slug(label: str | None) -> str | None:
    """Sanitized label slug for branch/result paths, or None if no label was given."""
    text = non_empty_string(label)
    if not text:
        return None
    return sanitize_slug(text)


def resolve_model_info(model: str) -> ModelInfo:
    return ModelInfo(effective=model, slug=sanitize_slug(model))
