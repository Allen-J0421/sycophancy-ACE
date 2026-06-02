#!/usr/bin/env python3
"""Run RefDiff on experiment commits (post-hoc, separate from run_experiment.py).

Scans result/ for folders with *-log.csv (like result/plot.py), invokes
refdiff-runner per commit_sha on --repo, and writes refdiff/<stamp>-refdiff.jsonl
plus matcher logs. Skips experiment folders whose commits are not in --repo.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_RUNNER_DIR = _SCRIPT_DIR / "refdiff-runner"
_RESULT_DIR = _SCRIPT_DIR / "result"
_DEFAULT_JAVA_HOME = Path("/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home")


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def java_home() -> str:
    env = os.environ.get("JAVA_HOME", "").strip()
    if env and Path(env).is_dir():
        return env
    if _DEFAULT_JAVA_HOME.is_dir():
        return str(_DEFAULT_JAVA_HOME)
    raise RuntimeError(
        "JAVA_HOME not set and default OpenJDK 21 not found. "
        "Install openjdk@21 or export JAVA_HOME."
    )


def is_java_experiment(exp_name: str, repo: Path) -> bool:
    if "_Java" in exp_name or exp_name.endswith("_Java"):
        return True
    if list(repo.rglob("*.java")):
        return True
    return False


def experiment_dirs_with_logs(result_dir: Path) -> list[Path]:
    """Return result/ subdirs that contain at least one *-log.csv."""
    dirs: list[Path] = []
    if not result_dir.is_dir():
        return dirs
    for exp_dir in sorted(result_dir.iterdir()):
        if not exp_dir.is_dir() or exp_dir.name.startswith("."):
            continue
        if exp_dir.name in ("__pycache__",):
            continue
        if list(exp_dir.glob("*-log.csv")):
            dirs.append(exp_dir)
    return dirs


def repo_contains_commit(repo: Path, commit_sha: str) -> bool:
    if not commit_sha:
        return False
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", commit_sha],
        capture_output=True,
    )
    return proc.returncode == 0


def first_commit_sha(exp_dir: Path) -> str | None:
    csv_files = sorted(exp_dir.glob("*-log.csv"))
    if not csv_files:
        return None
    with csv_files[0].open(newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f), None)
    if not row:
        return None
    sha = row.get("commit_sha", "").strip()
    return sha or None


def stamp_from_csv(csv_path: Path) -> str:
    name = csv_path.name
    if name.endswith("-log.csv"):
        return name[: -len("-log.csv")]
    return csv_path.stem


def git_numstat(repo: Path, commit_sha: str) -> dict[str, int]:
    """Lines changed in commit vs parent (same scope as experiment stats)."""
    spec = f"{commit_sha}^..{commit_sha}"
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", "--numstat", "--format=", spec],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return {"files_changed": 0, "lines_added": 0, "lines_deleted": 0}

    files_changed = 0
    lines_added = 0
    lines_deleted = 0
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted = parts[0], parts[1]
        if added == "-" or deleted == "-":
            continue
        files_changed += 1
        lines_added += int(added)
        lines_deleted += int(deleted)
    return {
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
    }


def run_refdiff_commit(
    *,
    repo: Path,
    commit_sha: str,
    out_json: Path,
    matcher_log: Path | None,
    gradlew: Path,
    env: dict[str, str],
) -> tuple[bool, dict]:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    arg_tokens = [
        "--repo",
        str(repo),
        "--commit",
        commit_sha,
        "--out",
        str(out_json),
        "--include-same",
        "--quiet",
    ]
    if matcher_log:
        arg_tokens.extend(["--matcher-log", str(matcher_log)])
    # Gradle CLI treats tokens after `--args` as Gradle options unless passed as `--args="..."`.
    arg_string = " ".join(shlex.quote(t) for t in arg_tokens)
    args = [str(gradlew), "-q", "run", f"--args={arg_string}"]
    proc = subprocess.run(
        args,
        cwd=_RUNNER_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if not out_json.exists() or out_json.stat().st_size == 0:
        return False, {
            "refdiff_ok": False,
            "error_message": proc.stderr.strip() or proc.stdout.strip() or "no output file",
            "commit_sha": commit_sha,
        }
    try:
        record = json.loads(out_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, {
            "refdiff_ok": False,
            "error_message": f"invalid JSON from refdiff-runner: {exc}",
            "commit_sha": commit_sha,
        }
    return bool(record.get("refdiff_ok")), record


def process_csv(
    *,
    csv_path: Path,
    repo: Path,
    exp_name: str,
    env: dict[str, str],
) -> tuple[int, int]:
    stamp = stamp_from_csv(csv_path)
    refdiff_dir = csv_path.parent / "refdiff"
    jsonl_path = refdiff_dir / f"{stamp}-refdiff.jsonl"
    matcher_dir = refdiff_dir / f"{stamp}-matcher"

    if jsonl_path.exists():
        eprint(f"[skip] {jsonl_path} exists")
        return 0, 0

    refdiff_dir.mkdir(parents=True, exist_ok=True)
    matcher_dir.mkdir(parents=True, exist_ok=True)
    gradlew = _RUNNER_DIR / "gradlew"
    if not gradlew.is_file():
        raise FileNotFoundError(f"Gradle wrapper not found: {gradlew}")

    ok_count = 0
    fail_count = 0
    lines_out: list[str] = []

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            run = int(row["run"])
            commit_sha = row["commit_sha"].strip()
            matcher_log = matcher_dir / f"run_{run:03d}.matcher.log"

            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp_path = Path(tmp.name)

            try:
                success, record = run_refdiff_commit(
                    repo=repo,
                    commit_sha=commit_sha,
                    out_json=tmp_path,
                    matcher_log=matcher_log,
                    gradlew=gradlew,
                    env=env,
                )
            finally:
                pass

            record["run"] = run
            record["commit_sha"] = record.get("commit_sha") or commit_sha
            record["commit_message"] = row.get("commit_message", "")
            record["model"] = row.get("model", "")
            record["git_branch"] = row.get("git_branch", "")
            record["stamp"] = stamp
            record["experiment"] = exp_name
            record["git_stat"] = git_numstat(repo, commit_sha)

            rel_matcher = matcher_log.relative_to(csv_path.parent)
            record["matcher_log"] = str(rel_matcher).replace("\\", "/")
            if matcher_log.exists() and matcher_log.stat().st_size == 0:
                record["matcher_discarded"] = record.get("matcher_discarded") or []

            if success:
                ok_count += 1
            else:
                fail_count += 1
                eprint(f"[warn] run {run} commit {commit_sha[:7]}: {record.get('error_message')}")

            lines_out.append(json.dumps(record, ensure_ascii=False))
            tmp_path.unlink(missing_ok=True)

    jsonl_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    eprint(f"[done] {jsonl_path} ({ok_count} ok, {fail_count} failed)")
    return ok_count, fail_count


def process_experiment_dir(
    *,
    exp_dir: Path,
    repo: Path,
    env: dict[str, str],
) -> tuple[int, int] | None:
    """Process one result/<experiment>/ folder. Returns None if skipped."""
    exp_name = exp_dir.name

    if not is_java_experiment(exp_name, repo):
        eprint(f"[skip] {exp_name}: not a Java experiment")
        return None

    probe_sha = first_commit_sha(exp_dir)
    if probe_sha and not repo_contains_commit(repo, probe_sha):
        eprint(f"[skip] {exp_name}: commits not in {repo}")
        return None

    csv_files = sorted(exp_dir.glob("*-log.csv"))
    if not csv_files:
        return None

    eprint(f"[experiment] {exp_name}")
    ok_count = 0
    fail_count = 0
    for csv_path in csv_files:
        eprint(f"[batch] {csv_path.name}")
        ok, fail = process_csv(
            csv_path=csv_path,
            repo=repo,
            exp_name=exp_name,
            env=env,
        )
        ok_count += ok
        fail_count += fail
    return ok_count, fail_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RefDiff on experiment CSV commits.")
    parser.add_argument("--repo", type=Path, required=True, help="Path to target git repo")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not (repo / ".git").is_dir() and not repo.name.endswith(".git"):
        eprint(f"error: not a git repo: {repo}")
        return 2

    exp_dirs = experiment_dirs_with_logs(_RESULT_DIR)
    if not exp_dirs:
        eprint(f"error: no experiment directories with *-log.csv in {_RESULT_DIR}")
        return 2

    env = os.environ.copy()
    env["JAVA_HOME"] = java_home()

    total_ok = 0
    total_fail = 0
    processed = 0
    for exp_dir in exp_dirs:
        outcome = process_experiment_dir(
            exp_dir=exp_dir,
            repo=repo,
            env=env,
        )
        if outcome is None:
            continue
        processed += 1
        ok, fail = outcome
        total_ok += ok
        total_fail += fail

    if processed == 0:
        eprint(f"[summary] no experiments matched repo {repo}")
        return 0

    eprint(f"[summary] {total_ok} commits ok, {total_fail} failed")
    return 1 if total_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
