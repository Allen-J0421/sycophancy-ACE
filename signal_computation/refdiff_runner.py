"""Invoke refdiff-runner (Gradle) for per-commit or cross-turn compares."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from experiment_runner.util import eprint, script_dir

_RUNNER_DIR = script_dir() / "refdiff-runner"
_DEFAULT_JAVA_HOME = Path("/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home")
_MAX_GRADLE_JAVA = 23
_REFDIFF_NODE_TMP = _RUNNER_DIR / ".refdiff-node-tmp"
_VENDOR_BABEL = _RUNNER_DIR / "vendor" / "babel-parser"
_BABEL_FILES = ("package.json", "lib/index.js", "bin/babel-parser.js")


def jdk_major_version(home: Path) -> int | None:
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
    proc = subprocess.run([str(java_bin), "-version"], capture_output=True, text=True)
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
        if major is None or major > _MAX_GRADLE_JAVA:
            continue
        return str(home)
    raise RuntimeError(
        f"No JDK <= {_MAX_GRADLE_JAVA} found. Install openjdk@21 or set JAVA_HOME."
    )


def seed_babel_parser() -> None:
    if not (_VENDOR_BABEL / "lib" / "index.js").is_file():
        return
    dst_root = _REFDIFF_NODE_TMP / "refdiff_node_modules" / "@babel" / "parser"
    for rel in _BABEL_FILES:
        src = _VENDOR_BABEL / rel
        if not src.is_file():
            continue
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def refdiff_env() -> dict[str, str]:
    env = os.environ.copy()
    env["JAVA_HOME"] = java_home()
    if "js" in env.get("PATH", ""):
        pass
    seed_babel_parser()
    return env


def git_dir_for(repo: Path) -> str:
    """Resolve the shared common git dir (`<main>/.git`).

    The dataset targets are git worktrees whose `.git` is a file, which the
    vendored Java/JGit refdiff-runner rejects. Hand it the real `.git`
    directory instead; commits resolve by SHA from the shared object store.
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
    )
    out = proc.stdout.strip()
    return out or str(repo)


def run_refdiff_compare(
    *,
    repo: Path,
    before_sha: str,
    after_sha: str,
    lang: str,
    compare_cache: dict[tuple[str, str, str, str], dict] | None = None,
) -> dict:
    """Run RefDiff between two arbitrary commits; return JSON record."""
    cache_key = (str(repo.resolve()), lang, before_sha, after_sha)
    if compare_cache is not None and cache_key in compare_cache:
        return compare_cache[cache_key]

    gradlew = _RUNNER_DIR / "gradlew"
    if not gradlew.is_file():
        raise FileNotFoundError(f"Gradle wrapper not found: {gradlew}")

    repo_arg = git_dir_for(repo)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        out_path = Path(tmp.name)

    arg_tokens = [
        "--repo",
        repo_arg,
        "--before-commit",
        before_sha,
        "--after-commit",
        after_sha,
        "--lang",
        lang,
        "--out",
        str(out_path),
        "--include-same",
        "--quiet",
    ]
    arg_string = " ".join(shlex.quote(t) for t in arg_tokens)
    args = [
        str(gradlew),
        "-q",
        f"-PrefdiffTmpdir={_REFDIFF_NODE_TMP}",
        "run",
        f"--args={arg_string}",
    ]
    proc = subprocess.run(
        args,
        cwd=_RUNNER_DIR,
        env=refdiff_env(),
        capture_output=True,
        text=True,
    )
    try:
        if not out_path.exists() or out_path.stat().st_size == 0:
            record = {
                "refdiff_ok": False,
                "error_message": proc.stderr.strip() or proc.stdout.strip() or "no output",
            }
        else:
            record = json.loads(out_path.read_text(encoding="utf-8"))
    finally:
        out_path.unlink(missing_ok=True)

    if compare_cache is not None:
        compare_cache[cache_key] = record
    if not record.get("refdiff_ok"):
        eprint(
            f"[warn] cross-turn RefDiff failed {before_sha[:7]}..{after_sha[:7]}: "
            f"{record.get('error_message')}"
        )
    return record
