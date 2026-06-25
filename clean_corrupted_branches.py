#!/usr/bin/env python3
"""Review and clean up corrupted / discarded experiment branches in the dataset repo.

The pipeline LOGS corrupt branches to ``output/corrupted_branches.jsonl`` during runs:
  * provider usage/session limits that trigger a fresh re-run (the old branch is discarded), and
  * wholesale-dead runs where every iteration failed (an agent usage/connection problem).

This script is the deliberate, manual cleanup step — run it AFTER the experiments finish:
  1. review the logged branches (default: no changes),
  2. optionally ``--scan`` the output tree to discover corrupt runs not already logged
     (useful for backfilling branches from before this logging existed), then
  3. ``--apply`` to delete those branches from the dataset repo and mark them cleaned.

Safety: only deletes branches matching the experiment-branch pattern (``<agent>-exp/...``);
never touches the per-codebase baseline branches. Records are flagged ``cleaned`` (not removed)
so the log stays an audit trail.

Usage:
    python clean_corrupted_branches.py                  # review only
    python clean_corrupted_branches.py --scan           # discover from output/ + append to log
    python clean_corrupted_branches.py --apply           # delete logged branches, mark cleaned
    python clean_corrupted_branches.py --scan --apply    # discover, then delete
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from experiment_runner.corruption_log import (  # noqa: E402
    REASON_AGENT_FAILURE,
    REASON_PROVIDER_LIMIT,
    read_log,
    record_key,
    write_log,
)
from experiment_runner.limit_detect import (  # noqa: E402
    LimitDetectConfig,
    detect_claude_limit,
    detect_codex_limit,
)

_DEFAULT_LOG = _SCRIPT_DIR / "output" / "corrupted_branches.jsonl"
_DEFAULT_PLAN = _SCRIPT_DIR / "pipeline_plan.json"
_DEFAULT_OUTPUT = _SCRIPT_DIR / "output"
_EXP_BRANCH_RE = re.compile(r"^(claude|codex)-exp/")
_CATEGORY_DIRS = {"algorithms": "Algorithms", "realworld": "RealWorld"}


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Git helpers
# --------------------------------------------------------------------------- #

def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False,
    )


def branch_exists(repo: Path, branch: str) -> bool:
    return _git(repo, ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"]).returncode == 0


def current_branch(repo: Path) -> str | None:
    proc = _git(repo, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def is_exp_branch(branch: str) -> bool:
    return bool(_EXP_BRANCH_RE.match(branch or ""))


def delete_branch(repo: Path, branch: str, baseline: str) -> tuple[bool, str]:
    """Delete an experiment branch, detaching the worktree to baseline first if it's checked out."""
    if not is_exp_branch(branch):
        return (False, "skipped (not an experiment branch)")
    if not repo.is_dir():
        return (False, f"skipped (repo missing: {repo})")
    if not branch_exists(repo, branch):
        return (True, "already absent")
    if current_branch(repo) == branch:
        co = _git(repo, ["checkout", "-f", baseline])
        if co.returncode != 0:
            return (False, f"could not detach worktree to {baseline[:10]}: {co.stderr.strip()}")
    res = _git(repo, ["branch", "-D", branch])
    if res.returncode != 0:
        return (False, f"branch -D failed: {res.stderr.strip()}")
    return (True, "deleted")


# --------------------------------------------------------------------------- #
# Scan: discover corrupt runs from the output tree (not yet in the log)
# --------------------------------------------------------------------------- #

def _load_plan_map(plan_path: Path) -> dict[str, dict]:
    """Map exp_folder -> {repo_root, baseline} using the planner (for branch deletion targets)."""
    if not plan_path.is_file():
        return {}
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    mapping: dict[str, dict] = {}
    for category in ("algorithms", "realworld"):
        for raw in data.get(category, []):
            merged = {**defaults, **raw}
            target = Path(merged["target"])
            if not target.is_absolute():
                target = (_SCRIPT_DIR / target)
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


def _csv_for_model_dir(model_dir: Path) -> Path:
    return model_dir.parent / "logs" / f"{model_dir.name}-log.csv"


def _classify_model_dir(model_dir: Path) -> tuple[str, str] | None:
    """Classify one experiment run dir (= one branch). Returns (reason, detail) or None."""
    runs = sorted(model_dir.glob("run_*"))
    if not runs:
        return None
    cfg = LimitDetectConfig()
    # 1) Provider-limit signature in any turn's agent JSONL.
    for run in runs:
        for name, detector in (("claude.jsonl", detect_claude_limit), ("codex.jsonl", detect_codex_limit)):
            jpath = run / name
            if not jpath.is_file():
                continue
            text = jpath.read_text(encoding="utf-8", errors="ignore")
            hit = detector(text, cfg)
            if hit is not None:
                return (REASON_PROVIDER_LIMIT, f"{hit.provider} {hit.kind}: {hit.raw[:80]}")
    # 2) Wholesale-dead run: every CSV row failed (nonzero exit or timed out).
    csv_path = _csv_for_model_dir(model_dir)
    if csv_path.is_file():
        rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8").splitlines()))
        if rows and all(
            (r.get("exit_code") not in ("0", "", None)) or (r.get("timed_out") == "1")
            for r in rows
        ):
            return (REASON_AGENT_FAILURE, f"all {len(rows)} iterations failed (exit/timeout)")
    return None


def _branch_from_csv(model_dir: Path) -> str | None:
    csv_path = _csv_for_model_dir(model_dir)
    if not csv_path.is_file():
        return None
    rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8").splitlines()))
    for r in rows:
        b = (r.get("git_branch") or "").strip()
        if b:
            return b
    return None


def _branch_from_repo(repo_root: str, stamp: str) -> str | None:
    """Fallback when no CSV exists: resolve the experiment branch from the dataset repo by its
    (unique) run stamp. Handy for backfilling runs whose CSV was already cleaned away."""
    if not repo_root or not stamp:
        return None
    repo = Path(repo_root)
    if not repo.is_dir():
        return None
    proc = _git(repo, ["for-each-ref", "--format=%(refname:short)", "refs/heads/"])
    if proc.returncode != 0:
        return None
    matches = [b for b in proc.stdout.splitlines() if stamp in b and is_exp_branch(b)]
    return matches[0] if matches else None


def scan_output(output_root: Path, plan_map: dict[str, dict], known: set[tuple[str, str]]) -> list[dict]:
    """Find corrupt runs under output/ and build records not already in the log."""
    from experiment_runner.util import utc_stamp  # local import: keeps top stdlib-light

    found: list[dict] = []
    for category in _CATEGORY_DIRS.values():
        croot = output_root / category
        if not croot.is_dir():
            continue
        for exp_dir in sorted(p for p in croot.iterdir() if p.is_dir()):
            info = plan_map.get(exp_dir.name)
            for model_dir in sorted(p for p in exp_dir.iterdir() if p.is_dir()):
                if model_dir.name in ("logs", "signals", "plots", "refdiff", "pipeline-logs"):
                    continue
                verdict = _classify_model_dir(model_dir)
                if verdict is None:
                    continue
                repo_root = info["repo_root"] if info else ""
                stamp = model_dir.name.split("-", 1)[0]
                branch = _branch_from_csv(model_dir) or _branch_from_repo(repo_root, stamp)
                if not branch:
                    eprint(f"  [scan] corrupt run with no recoverable branch: {model_dir} "
                           f"({verdict[0]}) — skipped")
                    continue
                if (repo_root, branch) in known:
                    continue
                reason, detail = verdict
                model = model_dir.name.split("-", 1)[1] if "-" in model_dir.name else ""
                found.append({
                    "ts": utc_stamp(),
                    "reason": reason,
                    "provider": None,
                    "detail": detail,
                    "repo_root": repo_root,
                    "branch": branch,
                    "baseline_commit": info["baseline"] if info else "",
                    "exp_folder": exp_dir.name,
                    "model": model,
                    "stamp": stamp,
                    "partial_csv": str(_csv_for_model_dir(model_dir)),
                    "artifacts_dir": str(model_dir),
                    "cleaned": False,
                    "source": "scan",
                })
                known.add((repo_root, branch))
    return found


# --------------------------------------------------------------------------- #
# Review + apply
# --------------------------------------------------------------------------- #

def review(records: list[dict]) -> None:
    if not records:
        eprint("[review] no corrupt branches logged.")
        return
    by_repo: dict[str, list[dict]] = {}
    for rec in records:
        by_repo.setdefault(rec.get("repo_root", "(unknown repo)"), []).append(rec)
    total_open = 0
    for repo, recs in sorted(by_repo.items()):
        print(f"\n{repo}")
        for rec in recs:
            branch = rec.get("branch", "?")
            status = "cleaned" if rec.get("cleaned") else _live_status(Path(repo), branch)
            if not rec.get("cleaned"):
                total_open += 1
            print(f"  [{rec.get('reason','?'):14}] {rec.get('model','?'):20} {branch}")
            print(f"      status={status}  detail={rec.get('detail','')[:80]}")
    print(f"\n[review] {len(records)} record(s); {total_open} not yet cleaned. "
          f"Re-run with --apply to delete them.")


def _live_status(repo: Path, branch: str) -> str:
    if not repo.is_dir():
        return "repo-missing"
    if not branch_exists(repo, branch):
        return "branch-absent"
    return "checked-out" if current_branch(repo) == branch else "present"


def apply(records: list[dict]) -> int:
    deleted = 0
    for rec in records:
        if rec.get("cleaned"):
            continue
        repo = Path(rec.get("repo_root", ""))
        branch = rec.get("branch", "")
        baseline = rec.get("baseline_commit", "")
        ok, msg = delete_branch(repo, branch, baseline)
        eprint(f"  {'[ok]' if ok else '[skip]'} {branch} — {msg}")
        if ok:
            rec["cleaned"] = True
            rec["clean_status"] = msg
            deleted += 1
    return deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log", type=Path, default=_DEFAULT_LOG, help="Corruption log (JSONL).")
    parser.add_argument("--plan", type=Path, default=_DEFAULT_PLAN, help="Planner (maps exp -> repo/baseline for --scan).")
    parser.add_argument("--output-root", type=Path, default=_DEFAULT_OUTPUT, help="Output tree to --scan.")
    parser.add_argument("--scan", action="store_true", help="Discover corrupt runs from output/ and append to the log.")
    parser.add_argument("--apply", action="store_true", help="Delete logged branches and flag them cleaned.")
    args = parser.parse_args(argv)

    records = read_log(args.log)

    if args.scan:
        plan_map = _load_plan_map(args.plan)
        known = {record_key(r) for r in records}
        discovered = scan_output(args.output_root.resolve(), plan_map, known)
        records.extend(discovered)
        write_log(args.log, records)
        eprint(f"[scan] discovered {len(discovered)} new corrupt run(s); log now has {len(records)}.")

    if args.apply:
        eprint(f"[apply] deleting corrupt branches from {len(records)} logged record(s) …")
        n = apply(records)
        write_log(args.log, records)
        eprint(f"[apply] deleted {n} branch(es); log updated: {args.log}")
    else:
        review(records)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
