#!/usr/bin/env python3
"""Build a static interactive dashboard HTML for one experiment folder."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Allow importing style_config from result/
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_REPO_ROOT / "result"))

from codex_parse import extract_final_agent_message, extract_reasoning_transcript  # noqa: E402
from style_config import COLORS, LABELS  # noqa: E402

MAX_FIELD_BYTES = 200_000
MISSING_ARTIFACT_MSG = (
    "No artifacts for this step (re-run experiment after dashboard support)."
)

TEMPLATE_PATH = _SCRIPT_DIR / "template.html"
APP_JS_PATH = _SCRIPT_DIR / "app.js"
STYLE_CSS_PATH = _SCRIPT_DIR / "style.css"


def truncate_text(text: str, *, max_bytes: int = MAX_FIELD_BYTES) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated + "\n\n(truncated)"


def read_artifact_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def stamp_from_csv(csv_path: Path) -> str:
    name = csv_path.name
    if name.endswith("-log.csv"):
        return name[: -len("-log.csv")]
    return csv_path.stem


def refdiff_jsonl_path(csv_path: Path) -> Path:
    stamp = stamp_from_csv(csv_path)
    return csv_path.parent / "refdiff" / f"{stamp}-refdiff.jsonl"


def build_refdiff_hover(record: dict) -> str:
    if not record.get("refdiff_ok", False):
        msg = (record.get("error_message") or "failed").strip()
        return f"error: {msg[:100]}" if msg else "error"
    n = int(record.get("n_refactorings", 0))
    if n == 0:
        return "(none)"
    type_counts: dict[str, int] = {}
    for rel in record.get("refactorings") or []:
        t = rel.get("type", "UNKNOWN")
        type_counts[t] = type_counts.get(t, 0) + 1
    return ", ".join(f"{t} ({c})" for t, c in sorted(type_counts.items()))


def load_refdiff_for_csv(csv_path: Path) -> dict[int, dict]:
    jsonl_path = refdiff_jsonl_path(csv_path)
    if not jsonl_path.is_file():
        return {}

    by_run: dict[int, dict] = {}
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        by_run[int(record["run"])] = record
    return by_run


def artifacts_dir_for_csv(csv_path: Path) -> Path:
    """Map ``<stamp>-<model>-log.csv`` → ``<stamp>-<model>/``."""
    name = csv_path.name
    if name.endswith("-log.csv"):
        folder_name = name[: -len("-log.csv")]
    else:
        folder_name = csv_path.stem
    return csv_path.parent / folder_name


def load_steps_from_csv(csv_path: Path) -> list[dict]:
    artifacts_dir = artifacts_dir_for_csv(csv_path)
    refdiff_by_run = load_refdiff_for_csv(csv_path)
    steps: list[dict] = []

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            run = int(row["run"])
            run_dir = artifacts_dir / f"run_{run:03d}"
            diff_path = run_dir / "diff.patch"
            codex_path = run_dir / "codex.jsonl"
            has_artifacts = diff_path.exists() or codex_path.exists()
            diff = truncate_text(read_artifact_file(diff_path)) if diff_path.exists() else ""
            codex_raw = read_artifact_file(codex_path) if codex_path.exists() else ""
            codex_jsonl = truncate_text(codex_raw) if codex_raw else ""
            response = extract_final_agent_message(codex_raw) if codex_raw else ""
            reasoning = extract_reasoning_transcript(codex_raw) if codex_raw else ""

            step: dict = {
                "run": run,
                "lines_total": int(row["lines_total"]),
                "lines_added": int(row["lines_added"]),
                "lines_deleted": int(row["lines_deleted"]),
                "files_changed": int(row["files_changed"]),
                "duration_s": float(row["duration_s"]),
                "exit_code": int(row["exit_code"]),
                "timed_out": int(row["timed_out"]),
                "commit_sha": row["commit_sha"],
                "diff": diff,
                "response": response,
                "reasoning": reasoning,
                "codex_jsonl": codex_jsonl,
                "has_artifacts": has_artifacts,
            }

            refdiff_record = refdiff_by_run.get(run)
            if refdiff_record is not None:
                csv_sha = row["commit_sha"].strip()
                rec_sha = str(refdiff_record.get("commit_sha", "")).strip()
                if rec_sha and csv_sha and not rec_sha.startswith(csv_sha[:7]) and not csv_sha.startswith(rec_sha[:7]):
                    print(
                        f"warning: refdiff commit mismatch run {run}: "
                        f"csv={csv_sha[:12]} jsonl={rec_sha[:12]}",
                        file=sys.stderr,
                    )
                step["refdiff"] = refdiff_record
                step["refdiff_hover"] = build_refdiff_hover(refdiff_record)
                step["refdiff_ok"] = bool(refdiff_record.get("refdiff_ok", False))
                err = refdiff_record.get("error_message") or ""
                if err:
                    step["refdiff_error"] = err

            steps.append(step)

    return steps


def build_experiment_data(exp_dir: Path) -> dict:
    csv_files = sorted(exp_dir.glob("*-log.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No *-log.csv files in {exp_dir}")

    models: list[dict] = []
    for csv_path in csv_files:
        with csv_path.open(newline="", encoding="utf-8") as f:
            first_row = next(csv.DictReader(f))
        model_id = first_row["model"]
        stamp = csv_path.name.replace("-log.csv", "")

        models.append(
            {
                "id": f"{stamp}:{model_id}",
                "model": model_id,
                "label": LABELS.get(model_id, model_id),
                "stamp": stamp,
                "csv": csv_path.name,
                "color": COLORS.get(model_id, "#888888"),
                "steps": load_steps_from_csv(csv_path),
            }
        )

    return {
        "experiment": exp_dir.name,
        "missing_artifact_msg": MISSING_ARTIFACT_MSG,
        "models": models,
    }


def render_dashboard(data: dict) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    app_js = APP_JS_PATH.read_text(encoding="utf-8")
    style_css = STYLE_CSS_PATH.read_text(encoding="utf-8")

    data_json = json.dumps(data, ensure_ascii=False)
    data_json = data_json.replace("</", "<\\/")

    html = template.replace("/*__STYLE__*/", style_css)
    html = html.replace("/*__APP_JS__*/", app_js)
    html = html.replace("/*__DATA__*/", data_json)
    return html


def experiment_dirs_with_logs(result_dir: Path) -> list[Path]:
    """Return experiment subdirs under result/ that contain at least one *-log.csv."""
    dirs: list[Path] = []
    if not result_dir.is_dir():
        return dirs
    for exp_dir in sorted(result_dir.iterdir()):
        if not exp_dir.is_dir() or exp_dir.name.startswith("."):
            continue
        if exp_dir.name == "__pycache__":
            continue
        if list(exp_dir.glob("*-log.csv")):
            dirs.append(exp_dir)
    return dirs


def build_one_experiment(exp_dir: Path) -> int:
    try:
        data = build_experiment_data(exp_dir)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out_path = exp_dir / "dashboard.html"
    out_path.write_text(render_dashboard(data), encoding="utf-8")
    print(f"Wrote: {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build static dashboard HTML for an experiment.")
    parser.add_argument(
        "--exp",
        help="Experiment folder name under result/ (e.g. target, bubble_sort).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Build dashboards for every result/ subdir that has *-log.csv.",
    )
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=_REPO_ROOT / "result",
        help="Path to result/ directory (default: repo result/).",
    )
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="Do not regenerate the root landing page (index.html).",
    )
    args = parser.parse_args(argv)

    if not args.all and not args.exp:
        parser.error("one of --exp or --all is required")

    result_dir = args.result_dir.resolve()

    if args.all:
        exp_dirs = experiment_dirs_with_logs(result_dir)
        if not exp_dirs:
            print(f"error: no experiment directories with *-log.csv in {result_dir}", file=sys.stderr)
            return 2
        for exp_dir in exp_dirs:
            rc = build_one_experiment(exp_dir)
            if rc != 0:
                return rc
    else:
        exp_dir = (result_dir / args.exp).resolve()
        if not exp_dir.is_dir():
            print(f"error: experiment directory not found: {exp_dir}", file=sys.stderr)
            return 2
        rc = build_one_experiment(exp_dir)
        if rc != 0:
            return rc

    if not args.no_index:
        if str(_SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPT_DIR))
        from build_index import build_landing_page

        index_path = build_landing_page(result_dir)
        print(f"Wrote: {index_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
