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
sys.path.insert(0, str(_REPO_ROOT))

from codex_parse import extract_final_agent_message, extract_reasoning_transcript  # noqa: E402
from experiment_runner.artifacts import load_prompts_by_turn  # noqa: E402
from experiment_runner.result_paths import (  # noqa: E402
    artifacts_dir_for_csv,
    exp_dir_has_logs,
    iter_log_csvs,
    logs_dir,
    refdiff_jsonl_path,
    signals_json_path,
    stamp_from_log_csv,
)
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
    return stamp_from_log_csv(csv_path)


def load_signals_for_csv(csv_path: Path) -> dict | None:
    """Load compute_signals.py output for this batch, if present."""
    path = signals_json_path(csv_path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"warning: invalid signals JSON {path}: {exc}", file=sys.stderr)
        return None


def build_refdiff_hover(record: dict) -> str:
    if not record.get("refdiff_ok", False):
        msg = (record.get("error_message") or "failed").strip()
        return f"error: {msg[:100]}" if msg else "error"
    type_counts: dict[str, int] = {}
    for rel in (record.get("non_matching_relationships") or []) + (
        record.get("matching_relationships") or []
    ):
        if rel.get("type") == "SAME":
            continue
        t = rel.get("type", "UNKNOWN")
        type_counts[t] = type_counts.get(t, 0) + 1
    if not type_counts:
        return "(none)"
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


def _summarize_chat_history(curated: object, *, preview_chars: int = 200) -> str:
    if not isinstance(curated, list):
        return ""
    lines: list[str] = []
    for entry in curated:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "unknown")
        texts: list[str] = []
        parts = entry.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict):
                    text = str(part.get("text") or "").strip()
                    if text:
                        texts.append(text)
        body = " ".join(texts).replace("\n", " ").strip()
        if len(body) > preview_chars:
            body = body[: preview_chars - 3] + "..."
        lines.append(f"{role}: {body or '(empty)'}")
    return "\n".join(lines)


def build_prompter_transcript(events: list[dict]) -> str:
    """Readable intermediate messages from normalized prompter envelopes."""
    parts: list[str] = []
    for ev in events:
        event = str(ev.get("event") or "")
        text = str(ev.get("text") or "").strip()
        if event == "request":
            payload = ev.get("payload")
            message = ""
            if isinstance(payload, dict):
                message = str(payload.get("message") or "").strip()
            if message:
                parts.append(f"[Prompter input]\n{message}")
            continue
        if event == "chat_history":
            payload = ev.get("payload")
            if isinstance(payload, dict):
                summary = _summarize_chat_history(payload.get("curated"))
                if summary:
                    parts.append(f"[Gemini curated history]\n{summary}")
            continue
        if event == "response":
            payload = ev.get("payload")
            if isinstance(payload, dict):
                parsed = payload.get("parsed")
                if isinstance(parsed, dict):
                    thought = str(parsed.get("thought_text") or "").strip()
                    if thought:
                        parts.append(f"[Prompter thought]\n{thought}")
            if text:
                parts.append(f"[Prompter request]\n{text}")
            continue
        if not text:
            continue
        if event == "prompt_out":
            parts.append(f"[Sent to coding agent]\n{text}")
        elif event == "error":
            parts.append(f"[Prompter error]\n{text}")
    return "\n\n".join(parts)


def load_prompter_artifacts(
    run_dir: Path,
    *,
    prompt_text: str | None = None,
) -> dict | None:
    path = run_dir / "prompter.jsonl"
    if not path.is_file():
        if prompt_text:
            return {
                "prompter_prompt": prompt_text,
                "prompter_transcript": "",
                "prompter_jsonl": "",
            }
        prompt_path = run_dir / "prompt.txt"
        if prompt_path.is_file():
            file_prompt = prompt_path.read_text(encoding="utf-8", errors="replace").strip()
            if file_prompt:
                return {
                    "prompter_prompt": file_prompt,
                    "prompter_transcript": "",
                    "prompter_jsonl": "",
                }
        return None

    raw = path.read_text(encoding="utf-8", errors="replace")
    events: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)

    prompt_out = prompt_text or ""
    if not prompt_out:
        for ev in events:
            if ev.get("event") == "prompt_out":
                text = str(ev.get("text") or "").strip()
                if text:
                    prompt_out = text

    if not prompt_out:
        prompt_path = run_dir / "prompt.txt"
        if prompt_path.is_file():
            file_prompt = prompt_path.read_text(encoding="utf-8", errors="replace").strip()
            if file_prompt:
                prompt_out = file_prompt

    return {
        "prompter_prompt": prompt_out,
        "prompter_transcript": build_prompter_transcript(events),
        "prompter_jsonl": truncate_text(raw),
    }


def load_steps_from_csv(csv_path: Path) -> list[dict]:
    artifacts_dir = artifacts_dir_for_csv(csv_path)
    prompts_by_turn = load_prompts_by_turn(artifacts_dir)
    refdiff_by_run = load_refdiff_for_csv(csv_path)
    signals_data = load_signals_for_csv(csv_path)
    signal_by_run: dict[int, dict] = {}
    if signals_data:
        for turn in signals_data.get("turns") or []:
            signal_by_run[int(turn["run"])] = turn
    steps: list[dict] = []

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            run = int(row["run"])
            run_dir = artifacts_dir / f"run_{run:03d}"
            diff_path = run_dir / "diff.patch"
            claude_path = run_dir / "claude.jsonl"
            codex_path = run_dir / "codex.jsonl"
            if claude_path.exists():
                agent_path = claude_path
                agent_kind = "claude"
            else:
                agent_path = codex_path
                agent_kind = "codex"
            has_artifacts = diff_path.exists() or agent_path.exists()
            diff = truncate_text(read_artifact_file(diff_path)) if diff_path.exists() else ""
            agent_raw = read_artifact_file(agent_path) if agent_path.exists() else ""
            agent_jsonl = truncate_text(agent_raw) if agent_raw else ""
            response = extract_final_agent_message(agent_raw) if agent_raw else ""
            reasoning = extract_reasoning_transcript(agent_raw) if agent_raw else ""

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
                "agent_jsonl": agent_jsonl,
                "agent_kind": agent_kind,
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

            turn_signal = signal_by_run.get(run)
            if turn_signal is not None:
                step["signal"] = turn_signal

            prompter_data = load_prompter_artifacts(
                run_dir,
                prompt_text=prompts_by_turn.get(run),
            )
            if prompter_data is not None:
                step.update(prompter_data)

            steps.append(step)

    return steps


def build_experiment_data(exp_dir: Path) -> dict:
    csv_files = iter_log_csvs(exp_dir)
    if not csv_files:
        raise FileNotFoundError(f"No *-log.csv files in {logs_dir(exp_dir)}")

    models: list[dict] = []
    for csv_path in csv_files:
        with csv_path.open(newline="", encoding="utf-8") as f:
            first_row = next(csv.DictReader(f))
        model_id = first_row["model"]
        stamp = csv_path.name.replace("-log.csv", "")

        signals_data = load_signals_for_csv(csv_path)
        signals_summary = None
        if signals_data:
            signals_summary = {
                "values": signals_data.get("signals") or {},
                "t0": signals_data.get("t0"),
                "L0": signals_data.get("L0"),
                "L0_ok": signals_data.get("L0_ok"),
                "num_turns": signals_data.get("num_turns"),
                "skipped_turns": signals_data.get("skipped_turns"),
                "thresholds": signals_data.get("thresholds") or {},
            }

        steps = load_steps_from_csv(csv_path)
        has_prompter = any(step.get("prompter_prompt") for step in steps)

        models.append(
            {
                "id": f"{stamp}:{model_id}",
                "model": model_id,
                "label": LABELS.get(model_id, model_id),
                "stamp": stamp,
                "csv": csv_path.name,
                "color": COLORS.get(model_id, "#888888"),
                "signals": signals_summary,
                "has_prompter": has_prompter,
                "steps": steps,
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
        if exp_dir_has_logs(exp_dir):
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
