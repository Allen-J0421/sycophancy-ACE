"""Append-only log of corrupted / discarded experiment branches.

Each record points at a dataset-repo experiment branch left behind by a run that was either
discarded (a provider usage/session limit was hit -> the run is re-run fresh) or that failed
wholesale (an agent usage/connection problem killed every iteration). The pipeline only
*logs* here during a run — it never deletes branches. A separate manual script
(``clean_corrupted_branches.py``) reviews this log and deletes the branches after the
experiments finish, so cleanup stays a deliberate, reviewable step.

The log is a JSON-lines file (default ``output/corrupted_branches.jsonl``); the serial
pipeline appends one record per corrupt run.
"""

from __future__ import annotations

import json
from pathlib import Path

from experiment_runner.models import ExperimentConfig
from experiment_runner.result_paths import stamp_from_log_csv
from experiment_runner.util import utc_stamp

LOG_FILENAME = "corrupted_branches.jsonl"

REASON_PROVIDER_LIMIT = "provider_limit"
REASON_AGENT_FAILURE = "agent_failure"


def default_log_path(config: ExperimentConfig) -> Path:
    """Central log beside the output tree (one file across Algorithms + RealWorld).

    ``results_csv`` is ``<output_base>/<exp_folder>/logs/<stamp>-log.csv``; ``parents[2]`` is
    ``<output_base>``, so the log lands next to it (e.g. ``output/corrupted_branches.jsonl``).
    """
    output_base = config.results_csv.parents[2]
    return output_base.parent / LOG_FILENAME


def build_record(
    *,
    reason: str,
    detail: str,
    config: ExperimentConfig,
    provider: str | None = None,
) -> dict:
    return {
        "ts": utc_stamp(),
        "reason": reason,
        "provider": provider,
        "detail": detail,
        "repo_root": str(config.target.root),
        "branch": config.branch,
        "baseline_commit": config.start_commit,
        "exp_folder": config.results_csv.parents[1].name,
        "model": config.effective_model,
        "stamp": stamp_from_log_csv(config.results_csv),
        "partial_csv": str(config.results_csv),
        "artifacts_dir": str(config.artifacts_dir),
        "cleaned": False,
    }


def append_record(log_path: Path, record: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def record_corrupt_branch(
    *,
    reason: str,
    detail: str,
    config: ExperimentConfig,
    provider: str | None = None,
    log_path: Path | None = None,
) -> dict:
    """Append a corrupt-branch record to the log (best-effort; never raises into the run)."""
    record = build_record(reason=reason, detail=detail, config=config, provider=provider)
    path = log_path if log_path is not None else default_log_path(config)
    try:
        append_record(path, record)
    except OSError:
        pass
    return record


def read_log(log_path: Path) -> list[dict]:
    """Read all records from the JSONL log (skips blank/malformed lines)."""
    if not log_path.is_file():
        return []
    records: list[dict] = []
    for raw in log_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def write_log(log_path: Path, records: list[dict]) -> None:
    """Rewrite the whole log (used to flip records to cleaned=true after deletion)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(rec, ensure_ascii=False) for rec in records]
    log_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def record_key(record: dict) -> tuple[str, str]:
    """Identity for dedup: a branch within a repo."""
    return (record.get("repo_root", ""), record.get("branch", ""))
