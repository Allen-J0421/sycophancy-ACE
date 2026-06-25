"""Sentinel marker for provider-limit blocks (runner side).

When ``run_experiment`` aborts an experiment because of a provider usage limit, it writes a
small JSON marker that the orchestrator (``run_pipeline``) reads to decide how long to pause
and which partial outputs to discard. Kept stdlib-only and import-light; ``run_pipeline``
reads the JSON directly rather than importing this module, so it never pulls in the heavy
``experiment_runner`` chain.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiment_runner.limit_detect import LimitHit
from experiment_runner.util import utc_stamp

MARKER_FILENAME = ".limit_block.json"


def marker_path(exp_dir: Path) -> Path:
    return exp_dir / MARKER_FILENAME


def write_limit_marker(
    hit: LimitHit,
    *,
    exp_dir: Path,
    partial_csv: Path,
    artifacts_dir: Path,
) -> Path:
    """Persist the limit details + exact partial-output paths for precise cleanup."""
    data = {
        "provider": hit.provider,
        "kind": hit.kind,
        "reset_dt_iso": hit.reset_dt.isoformat() if hit.reset_dt else None,
        "raw": hit.raw,
        "ts": utc_stamp(),
        "partial_csv": str(partial_csv),
        "artifacts_dir": str(artifacts_dir),
    }
    path = marker_path(exp_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def stderr_marker_line(hit: LimitHit) -> str:
    """One-line, machine-parseable signal for the orchestrator's captured log."""
    reset = hit.reset_dt.isoformat() if hit.reset_dt else ""
    return f"PROVIDER_LIMIT provider={hit.provider} kind={hit.kind} reset={reset}"
