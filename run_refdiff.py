#!/usr/bin/env python3
"""Run RefDiff on experiment commits (post-hoc, separate from run_experiment.py).

Scans result/ for folders with *-log.csv (like result/plot.py), invokes
refdiff-runner per commit_sha on --repo, and writes refdiff/<stamp>-refdiff.jsonl
plus matcher logs. Skips experiment folders whose commits are not in --repo.

Near-miss thresholds are read from `.env` (see REFDIFF_NEAR_MISS_* below).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_RUNNER_DIR = _SCRIPT_DIR / "refdiff-runner"
_RESULT_DIR = _SCRIPT_DIR / "result"
_DEFAULT_JAVA_HOME = Path("/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home")
_MAX_GRADLE_JAVA = 23  # Gradle 8.10.2 max supported runtime

# RefDiff-js bundles an ancient @babel/parser (7.0.0-beta.51) that cannot parse
# `??` / `?.` without plugins it never enables. It extracts that parser into
# `${java.io.tmpdir}/refdiff_node_modules/@babel/parser` only when absent, and
# reuses whatever is already there. build.gradle pins java.io.tmpdir to
# _REFDIFF_NODE_TMP; we pre-seed a modern vendored parser there so modern JS
# syntax parses correctly. See vendor/babel-parser.
_VENDOR_BABEL = _RUNNER_DIR / "vendor" / "babel-parser"
_REFDIFF_NODE_TMP = _RUNNER_DIR / ".refdiff-node-tmp"
_BABEL_FILES = ("package.json", "lib/index.js", "bin/babel-parser.js")

# Near-miss score band defaults; overridden by .env (cwd first, then repo root).
NEAR_MISS_MIN_SCORE = 0.3
NEAR_MISS_MAX_SCORE = 0.5


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def jdk_major_version(home: Path) -> int | None:
    """Return JDK major version from <home>/release or `java -version`."""
    release = home / "release"
    if release.is_file():
        text = release.read_text(encoding="utf-8", errors="replace")
        match = re.search(r'^JAVA_VERSION="([^"]+)"', text, re.MULTILINE)
        if match:
            version = match.group(1)
            if version.startswith("1."):
                parts = version.split(".")
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1])
            head = version.split(".", 1)[0]
            if head.isdigit():
                return int(head)

    java_bin = home / "bin" / "java"
    if not java_bin.is_file():
        return None
    proc = subprocess.run(
        [str(java_bin), "-version"],
        capture_output=True,
        text=True,
    )
    output = (proc.stderr or "") + (proc.stdout or "")
    match = re.search(r'version "(\d+)(?:\.(\d+))?', output)
    if not match:
        return None
    major = int(match.group(1))
    if major == 1 and match.group(2):
        return int(match.group(2))
    return major


def java_home() -> str:
    env_home = os.environ.get("JAVA_HOME", "").strip()
    candidates: list[Path] = []
    if env_home:
        candidates.append(Path(env_home))
    if _DEFAULT_JAVA_HOME not in candidates:
        candidates.append(_DEFAULT_JAVA_HOME)

    for home in candidates:
        if not home.is_dir():
            continue
        major = jdk_major_version(home)
        if major is None:
            eprint(f"[warn] cannot detect Java version for {home}, skipping")
            continue
        if major > _MAX_GRADLE_JAVA:
            eprint(
                f"[warn] {home} is Java {major} (Gradle 8.10.2 supports up to "
                f"{_MAX_GRADLE_JAVA}), skipping"
            )
            continue
        if env_home and str(home.resolve()) != Path(env_home).resolve():
            eprint(f"[warn] using {home} (Java {major}) instead of JAVA_HOME={env_home}")
        return str(home)

    raise RuntimeError(
        f"No JDK <= {_MAX_GRADLE_JAVA} found for Gradle 8.10.2. "
        "Install openjdk@21 (brew install openjdk@21) or set JAVA_HOME to a "
        f"compatible JDK (e.g. {_DEFAULT_JAVA_HOME})."
    )


def _parse_env_float(key: str, value: str) -> float | None:
    raw = value.strip().strip('"').strip("'")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        eprint(f"[warn] invalid {key}={value!r} in .env; ignoring")
        return None


def load_dotenv() -> None:
    """Load REFDIFF_NEAR_MISS_* from `.env` (cwd, then sandbox root)."""
    global NEAR_MISS_MIN_SCORE, NEAR_MISS_MAX_SCORE
    candidates = [Path.cwd() / ".env", _SCRIPT_DIR / ".env"]
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if key == "REFDIFF_NEAR_MISS_MIN_SCORE":
                parsed = _parse_env_float(key, value)
                if parsed is not None:
                    NEAR_MISS_MIN_SCORE = parsed
            elif key == "REFDIFF_NEAR_MISS_MAX_SCORE":
                parsed = _parse_env_float(key, value)
                if parsed is not None:
                    NEAR_MISS_MAX_SCORE = parsed

    if NEAR_MISS_MIN_SCORE >= NEAR_MISS_MAX_SCORE:
        eprint(
            "[warn] .env: REFDIFF_NEAR_MISS_MIN_SCORE must be < REFDIFF_NEAR_MISS_MAX_SCORE; "
            "using 0.3 / 0.5"
        )
        NEAR_MISS_MIN_SCORE = 0.3
        NEAR_MISS_MAX_SCORE = 0.5


def seed_babel_parser() -> bool:
    """Pre-seed RefDiff's reuse location with the vendored modern @babel/parser.

    Force-copies the vendored parser into
    ``_REFDIFF_NODE_TMP/refdiff_node_modules/@babel/parser`` so RefDiff-js reuses
    it (it only extracts its bundled beta.51 when the files are absent). Keeps the
    copy fresh on every invocation in case the OS temp reaper cleared it.
    """
    if not (_VENDOR_BABEL / "lib" / "index.js").is_file():
        eprint(
            f"[warn] vendored @babel/parser missing at {_VENDOR_BABEL}; "
            "JS files using ??/?. may fail to parse"
        )
        return False
    dst_root = _REFDIFF_NODE_TMP / "refdiff_node_modules" / "@babel" / "parser"
    for rel in _BABEL_FILES:
        src = _VENDOR_BABEL / rel
        if not src.is_file():
            continue
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return True


def detect_repo_language(repo: Path) -> str | None:
    has_java = bool(list(repo.rglob("*.java")))
    has_js = bool(list(repo.rglob("*.js"))) or bool(list(repo.rglob("*.jsx")))
    if has_java and has_js:
        return None
    if has_java:
        return "java"
    if has_js:
        return "js"
    return None


def is_java_experiment(exp_name: str, repo: Path) -> bool:
    if "_Java" in exp_name or exp_name.endswith("_Java"):
        return True
    if list(repo.rglob("*.java")):
        return True
    return False


def experiment_matches_language(exp_name: str, repo: Path, lang: str) -> bool:
    if lang == "java":
        return is_java_experiment(exp_name, repo)
    if lang == "js":
        return "_Java" not in exp_name and not exp_name.endswith("_Java")
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
    lang: str,
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
        "--lang",
        lang,
        "--out",
        str(out_json),
        "--include-same",
        "--quiet",
    ]
    if matcher_log:
        arg_tokens.extend(["--matcher-log", str(matcher_log)])
    # Gradle CLI treats tokens after `--args` as Gradle options unless passed as `--args="..."`.
    arg_string = " ".join(shlex.quote(t) for t in arg_tokens)
    # -P (per-invocation project property) keeps the JVM's java.io.tmpdir aligned
    # with the directory we pre-seeded with a modern @babel/parser.
    args = [
        str(gradlew),
        "-q",
        f"-PrefdiffTmpdir={_REFDIFF_NODE_TMP}",
        f"-PrefdiffNearMissMin={NEAR_MISS_MIN_SCORE}",
        f"-PrefdiffNearMissMax={NEAR_MISS_MAX_SCORE}",
        "run",
        f"--args={arg_string}",
    ]
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
    lang: str,
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
                    lang=lang,
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
    lang: str,
    env: dict[str, str],
) -> tuple[int, int] | None:
    """Process one result/<experiment>/ folder. Returns None if skipped."""
    exp_name = exp_dir.name

    if not experiment_matches_language(exp_name, repo, lang):
        eprint(f"[skip] {exp_name}: not a {lang} experiment")
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
            lang=lang,
            env=env,
        )
        ok_count += ok
        fail_count += fail
    return ok_count, fail_count


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run RefDiff on experiment CSV commits.")
    parser.add_argument("--repo", type=Path, required=True, help="Path to target git repo")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not (repo / ".git").is_dir() and not repo.name.endswith(".git"):
        eprint(f"error: not a git repo: {repo}")
        return 2

    lang = detect_repo_language(repo)
    if lang is None:
        has_java = bool(list(repo.rglob("*.java")))
        has_js = bool(list(repo.rglob("*.js"))) or bool(list(repo.rglob("*.jsx")))
        if has_java and has_js:
            eprint(
                "error: repo contains both .java and .js/.jsx files; "
                "RefDiff auto-detect requires a single language"
            )
        else:
            eprint("error: repo contains no .java, .js, or .jsx source files")
        return 2
    eprint(f"[info] repo language: {lang}")
    eprint(
        f"[info] near-miss score band (from .env): "
        f"{NEAR_MISS_MIN_SCORE} <= score < {NEAR_MISS_MAX_SCORE}"
    )

    exp_dirs = experiment_dirs_with_logs(_RESULT_DIR)
    if not exp_dirs:
        eprint(f"error: no experiment directories with *-log.csv in {_RESULT_DIR}")
        return 2

    env = os.environ.copy()
    env["JAVA_HOME"] = java_home()

    if lang == "js":
        if seed_babel_parser():
            eprint(f"[info] seeded modern @babel/parser into {_REFDIFF_NODE_TMP}")

    total_ok = 0
    total_fail = 0
    processed = 0
    for exp_dir in exp_dirs:
        outcome = process_experiment_dir(
            exp_dir=exp_dir,
            repo=repo,
            lang=lang,
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
