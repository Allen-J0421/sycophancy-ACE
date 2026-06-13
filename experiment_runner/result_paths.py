"""Canonical paths under result/<experiment>/."""

from __future__ import annotations

from pathlib import Path

LOGS_DIR = "logs"
SIGNALS_DIR = "signals"
PLOTS_DIR = "plots"
REFDIFF_DIR = "refdiff"

LOG_CSV_SUFFIX = "-log.csv"


def logs_dir(exp_dir: Path) -> Path:
    return exp_dir / LOGS_DIR


def signals_dir(exp_dir: Path) -> Path:
    return exp_dir / SIGNALS_DIR


def plots_dir(exp_dir: Path) -> Path:
    return exp_dir / PLOTS_DIR


def refdiff_dir(exp_dir: Path) -> Path:
    return exp_dir / REFDIFF_DIR


def stamp_from_log_csv(csv_path: Path) -> str:
    name = csv_path.name
    if name.endswith(LOG_CSV_SUFFIX):
        return name[: -len(LOG_CSV_SUFFIX)]
    return csv_path.stem


def exp_dir_for_csv(csv_path: Path) -> Path:
    parent = csv_path.parent
    if parent.name == LOGS_DIR:
        return parent.parent
    return parent


def log_csv_path(exp_dir: Path, stamp: str, model_slug: str) -> Path:
    return logs_dir(exp_dir) / f"{stamp}-{model_slug}{LOG_CSV_SUFFIX}"


def artifacts_dir(exp_dir: Path, stamp: str, model_slug: str) -> Path:
    return exp_dir / f"{stamp}-{model_slug}"


def artifacts_dir_for_csv(csv_path: Path) -> Path:
    return exp_dir_for_csv(csv_path) / stamp_from_log_csv(csv_path)


def refdiff_jsonl_path(csv_path: Path) -> Path:
    stamp = stamp_from_log_csv(csv_path)
    return refdiff_dir(exp_dir_for_csv(csv_path)) / f"{stamp}-refdiff.jsonl"


def refdiff_matcher_log_path(csv_path: Path) -> Path:
    stamp = stamp_from_log_csv(csv_path)
    return refdiff_dir(exp_dir_for_csv(csv_path)) / f"{stamp}-matcher.log"


def signals_json_path(csv_path: Path) -> Path:
    stamp = stamp_from_log_csv(csv_path)
    return signals_dir(exp_dir_for_csv(csv_path)) / f"{stamp}-signals.json"


def signals_csv_path(exp_dir: Path) -> Path:
    return signals_dir(exp_dir) / f"{exp_dir.name}_signals.csv"


def iter_log_csvs(exp_dir: Path) -> list[Path]:
    path = logs_dir(exp_dir)
    if not path.is_dir():
        return []
    return sorted(path.glob(f"*{LOG_CSV_SUFFIX}"))


def exp_dir_has_logs(exp_dir: Path) -> bool:
    return bool(iter_log_csvs(exp_dir))
