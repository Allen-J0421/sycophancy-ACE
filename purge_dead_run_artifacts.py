#!/usr/bin/env python3
"""Quarantine (or delete) dead/duplicate experiment-run artifacts from output/.

A "dead" run = a model run dir whose ``logs/<stamp>-<model>-log.csv`` has >=1 row
and **every** row failed (``exit_code != 0`` or ``timed_out == 1``). These come
from provider spend-caps / session limits / timeouts that the live auto-pause
missed, so all iterations produced 0-line no-ops. Left in place they pollute
every downstream glob (``refusal_analysis``, aggregation) — e.g. a codex
spend-cap run contributes 10 fake ``lines_total==0`` "declines".

SAFETY — this script is built so a later ``clean_corrupted_branches.py --apply``
never misses a branch even though we remove the artifacts here:
  1. For every dead run it FIRST ensures a record exists in
     ``output/corrupted_branches.jsonl`` (append-only, same schema the real tool
     reads) with the run's git branch + repo + baseline. The branch is read from
     the CSV ``git_branch`` column. If a dead run has no recoverable branch it is
     NOT touched (reported instead), so nothing becomes un-cleanable.
  2. Only then are the artifacts moved to a quarantine dir (default) or deleted.

It never writes ``.pipeline_state.json`` and skips anything modified within
``--skip-recent-min`` minutes or any 0-row (live/just-started) CSV, so it is safe
to run while the pipeline is working on other phases.

Usage:
    python purge_dead_run_artifacts.py                 # DRY-RUN: report only
    python purge_dead_run_artifacts.py --apply         # ensure-logged + quarantine
    python purge_dead_run_artifacts.py --apply --delete # hard-delete instead of move
    python purge_dead_run_artifacts.py --suite RealWorld --apply
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_OUTPUT = _SCRIPT_DIR / "output"
_DEFAULT_PLAN = _SCRIPT_DIR / "pipeline_plan.json"
_DEFAULT_LOG = _DEFAULT_OUTPUT / "corrupted_branches.jsonl"
_CATEGORY_DIRS = {"algorithms": "Algorithms", "realworld": "RealWorld"}
_NON_MODEL_SUBS = {"logs", "signals", "plots", "refdiff", "pipeline-logs", "_aggregate"}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# --------------------------------------------------------------------------- #
# Plan map: exp_folder -> {repo_root, baseline}
# --------------------------------------------------------------------------- #

def load_plan_map(plan_path: Path) -> dict[str, dict]:
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    mapping: dict[str, dict] = {}
    for category in ("algorithms", "realworld"):
        for raw in data.get(category, []):
            merged = {**defaults, **raw}
            target = Path(merged["target"])
            if not target.is_absolute():
                target = _SCRIPT_DIR / target
            folder = target.name
            if merged.get("label"):
                folder += f"-{merged['label']}"
            if bool(merged.get("prompter", False)):
                folder += "-Agent"
            mapping[folder] = {
                "repo_root": str(target.resolve()),
                "baseline": str(merged["commit"]),
                "category": _CATEGORY_DIRS[category],
            }
    return mapping


# --------------------------------------------------------------------------- #
# Dead-run detection
# --------------------------------------------------------------------------- #

def _row_failed(r: dict) -> bool:
    return (r.get("exit_code") not in ("0", "", None)) or (r.get("timed_out") == "1")


def find_dead_runs(output_root: Path, suites: list[str], skip_recent_s: float) -> list[dict]:
    """Return dead-run descriptors (one per wholly-dead log CSV)."""
    out: list[dict] = []
    now = time.time()
    for suite in suites:
        for csv_path in sorted(glob.glob(str(output_root / suite / "*" / "logs" / "*-log.csv"))):
            cp = Path(csv_path)
            if "_excluded" in cp.parts:
                continue
            exp = cp.parents[1].name
            stamp_model = cp.name[: -len("-log.csv")]
            model_dir = cp.parents[1] / stamp_model
            rows = list(csv.DictReader(cp.read_text(encoding="utf-8", errors="replace").splitlines()))
            if not rows:
                out.append({"status": "skip_empty", "exp": exp, "suite": suite,
                            "stamp_model": stamp_model, "csv": cp, "model_dir": model_dir})
                continue
            if not all(_row_failed(r) for r in rows):
                continue  # has at least one good iteration -> keep
            # recently modified guard (CSV or dir)
            mtimes = [cp.stat().st_mtime]
            if model_dir.is_dir():
                mtimes.append(model_dir.stat().st_mtime)
            recent = (now - max(mtimes)) < skip_recent_s
            branch = ""
            for r in rows:
                b = (r.get("git_branch") or "").strip()
                if b:
                    branch = b
                    break
            out.append({
                "status": "dead", "exp": exp, "suite": suite, "stamp_model": stamp_model,
                "csv": cp, "model_dir": model_dir, "rows": len(rows), "branch": branch,
                "recent": recent,
                "model": stamp_model.split("-", 1)[1] if "-" in stamp_model else stamp_model,
                "stamp": stamp_model.split("-", 1)[0],
                "exit_codes": sorted({(r.get("exit_code") or "?") for r in rows}),
                "timeouts": sum(1 for r in rows if r.get("timed_out") == "1"),
            })
    return out


# --------------------------------------------------------------------------- #
# Corruption-log: ensure logged (append-only, schema-compatible)
# --------------------------------------------------------------------------- #

def read_log_keys(log_path: Path) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if not log_path.is_file():
        return keys
    for raw in log_path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            keys.add((obj.get("repo_root", ""), obj.get("branch", "")))
    return keys


def build_record(d: dict, plan_map: dict[str, dict]) -> dict | None:
    info = plan_map.get(d["exp"], {})
    repo_root = info.get("repo_root", "")
    if not d["branch"]:
        return None
    detail = (f"all {d['rows']} iterations failed "
              f"(exit={d['exit_codes']}, timeouts={d['timeouts']})")
    return {
        "ts": utc_stamp(),
        "reason": "agent_failure",
        "provider": None,
        "detail": detail,
        "repo_root": repo_root,
        "branch": d["branch"],
        "baseline_commit": info.get("baseline", ""),
        "exp_folder": d["exp"],
        "model": d["model"],
        "stamp": d["stamp"],
        "partial_csv": str(d["csv"]),
        "artifacts_dir": str(d["model_dir"]),
        "cleaned": False,
        "source": "purge_dead_run_artifacts",
    }


def append_records(log_path: Path, records: list[dict]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# Quarantine / delete
# --------------------------------------------------------------------------- #

def move_into(src: Path, dest_dir: Path) -> str:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        dest = dest_dir / f"{src.name}.{utc_stamp()}"
    shutil.move(str(src), str(dest))
    return str(dest)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output-root", type=Path, default=_DEFAULT_OUTPUT)
    ap.add_argument("--plan", type=Path, default=_DEFAULT_PLAN)
    ap.add_argument("--log", type=Path, default=_DEFAULT_LOG)
    ap.add_argument("--suite", choices=["Algorithms", "RealWorld", "both"], default="both")
    ap.add_argument("--quarantine-dir", type=Path, default=_DEFAULT_OUTPUT / "_quarantine_dead_runs")
    ap.add_argument("--skip-recent-min", type=float, default=20.0,
                    help="Skip runs whose CSV/dir was modified within this many minutes (live guard).")
    ap.add_argument("--apply", action="store_true", help="Perform changes (default: dry-run report).")
    ap.add_argument("--delete", action="store_true", help="Hard-delete instead of moving to quarantine.")
    args = ap.parse_args(argv)

    output_root = args.output_root.resolve()
    suites = ["Algorithms", "RealWorld"] if args.suite == "both" else [args.suite]
    plan_map = load_plan_map(args.plan.resolve())
    skip_recent_s = args.skip_recent_min * 60.0

    found = find_dead_runs(output_root, suites, skip_recent_s)
    dead = [d for d in found if d["status"] == "dead"]
    empties = [d for d in found if d["status"] == "skip_empty"]

    actionable = [d for d in dead if d["branch"] and not d["recent"]]
    no_branch = [d for d in dead if not d["branch"]]
    recent = [d for d in dead if d["recent"]]

    print(f"[scan] suites={suites} -> {len(dead)} wholly-dead run(s); "
          f"{len(empties)} empty/live CSV(s) skipped.")
    for d in dead:
        flags = []
        if not d["branch"]:
            flags.append("NO_BRANCH(skip)")
        if d["recent"]:
            flags.append("RECENT(skip)")
        print(f"   DEAD {d['exp']:30} {d['stamp_model']:34} rows={d['rows']:2} "
              f"exits={d['exit_codes']} to={d['timeouts']} {' '.join(flags)}")
    if no_branch:
        print(f"\n[warn] {len(no_branch)} dead run(s) have NO recoverable git branch and will be LEFT "
              f"in place (so clean_corrupted_branches can still find them):")
        for d in no_branch:
            print(f"        {d['exp']} {d['stamp_model']}")
    if recent:
        print(f"\n[info] {len(recent)} dead run(s) modified within {args.skip_recent_min}min -> skipped (live guard).")

    # 1) Ensure logged BEFORE removing anything.
    existing = read_log_keys(args.log)
    to_log: list[dict] = []
    for d in actionable:
        rec = build_record(d, plan_map)
        if rec is None:
            continue
        if (rec["repo_root"], rec["branch"]) not in existing:
            to_log.append(rec)
            existing.add((rec["repo_root"], rec["branch"]))

    print(f"\n[log] {len(to_log)} new corruption-log record(s) needed "
          f"(actionable={len(actionable)}, already-logged={len(actionable)-len(to_log)}).")
    for rec in to_log:
        print(f"       + {rec['exp_folder']:30} {rec['branch']}")

    if not args.apply:
        print(f"\n[dry-run] would quarantine {len(actionable)} run dir(s)+CSV(s) to "
              f"{args.quarantine_dir} (use --apply; --delete to hard-delete). No changes made.")
        return 0

    # Append log records first (append-only; safe vs concurrent appends).
    if to_log:
        append_records(args.log, to_log)
        print(f"[log] appended {len(to_log)} record(s) to {args.log}")

    # Re-verify every actionable run is now logged; refuse to remove any that isn't.
    logged_now = read_log_keys(args.log)
    removed = 0
    for d in actionable:
        info = plan_map.get(d["exp"], {})
        key = (info.get("repo_root", ""), d["branch"])
        if key not in logged_now:
            print(f"   [skip] {d['stamp_model']} not in log after append — leaving in place.")
            continue
        qbase = args.quarantine_dir / d["suite"] / d["exp"]
        for target in (d["model_dir"], d["csv"]):
            if not Path(target).exists():
                continue
            if args.delete:
                if Path(target).is_dir():
                    shutil.rmtree(target)
                else:
                    Path(target).unlink()
                print(f"   [deleted] {target}")
            else:
                sub = qbase / ("logs" if target == d["csv"] else "")
                dest = move_into(Path(target), sub)
                print(f"   [quarantined] {os.path.relpath(str(target), str(output_root))} -> "
                      f"{os.path.relpath(dest, str(output_root))}")
        removed += 1

    print(f"\n[done] processed {removed} dead run(s); "
          f"{'deleted' if args.delete else 'moved to ' + str(args.quarantine_dir)}. "
          f"Branches remain in {args.log} (cleaned=false) for "
          f"`clean_corrupted_branches.py --apply`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
