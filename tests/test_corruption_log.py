"""Tests for the corruption log and the manual clean_corrupted_branches.py script."""

from __future__ import annotations

import csv
import io
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import clean_corrupted_branches as ccb  # noqa: E402
from experiment_runner import corruption_log as clog  # noqa: E402
from experiment_runner.models import ExperimentConfig, TargetScope  # noqa: E402

CSV_HEADER = [
    "run", "files_changed", "lines_added", "lines_deleted", "lines_total", "duration_s",
    "exit_code", "timed_out", "commit_sha", "commit_message", "model", "git_branch",
]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


def _init_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "tester")
    (path / "a.txt").write_text("hello")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "baseline")
    return _git(path, "rev-parse", "HEAD").stdout.strip()


def _make_config(tmp_path: Path) -> ExperimentConfig:
    results_csv = tmp_path / "output" / "RealWorld" / "R002-high-Agent" / "logs" / "20260625T120000Z-claude-sonnet-4-6-log.csv"
    return ExperimentConfig(
        target=TargetScope(root=tmp_path / "wt", rel_path="", pathspec=None, work_dir=tmp_path / "wt"),
        prompt="refactor",
        requested_model="claude-sonnet-4-6",
        effective_model="claude-sonnet-4-6",
        branch="claude-exp/20260625T120000Z-claude-sonnet-4-6-high-Agent",
        results_csv=results_csv,
        artifacts_dir=results_csv.parents[1] / "20260625T120000Z-claude-sonnet-4-6",
        start_commit="abc123",
        iterations=10,
    )


# --------------------------------------------------------------------------- #
# corruption_log
# --------------------------------------------------------------------------- #

def test_record_and_read_round_trip(tmp_path):
    config = _make_config(tmp_path)
    log_path = tmp_path / "corrupted_branches.jsonl"
    rec = clog.record_corrupt_branch(
        reason=clog.REASON_PROVIDER_LIMIT, detail="session limit", config=config,
        provider="claude", log_path=log_path,
    )
    assert rec["branch"].startswith("claude-exp/")
    assert rec["repo_root"].endswith("wt")
    assert rec["baseline_commit"] == "abc123"
    assert rec["exp_folder"] == "R002-high-Agent"
    assert rec["cleaned"] is False

    loaded = clog.read_log(log_path)
    assert len(loaded) == 1 and loaded[0]["branch"] == rec["branch"]


def test_default_log_path_is_central(tmp_path):
    config = _make_config(tmp_path)
    # results_csv = .../output/RealWorld/<exp>/logs/<csv> -> log beside output/
    assert clog.default_log_path(config) == tmp_path / "output" / "corrupted_branches.jsonl"


def test_append_multiple_and_keys(tmp_path):
    config = _make_config(tmp_path)
    log_path = tmp_path / "log.jsonl"
    clog.record_corrupt_branch(reason=clog.REASON_PROVIDER_LIMIT, detail="x", config=config, log_path=log_path)
    clog.record_corrupt_branch(reason=clog.REASON_AGENT_FAILURE, detail="y", config=config, log_path=log_path)
    records = clog.read_log(log_path)
    assert len(records) == 2
    assert clog.record_key(records[0]) == (str(config.target.root), config.branch)


# --------------------------------------------------------------------------- #
# clean script: git helpers
# --------------------------------------------------------------------------- #

def test_delete_exp_branch_when_checked_out(tmp_path):
    repo = tmp_path / "repo"
    baseline = _init_repo(repo)
    _git(repo, "checkout", "-qb", "claude-exp/run1")
    (repo / "b.txt").write_text("change")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "exp work")
    assert ccb.branch_exists(repo, "claude-exp/run1")
    assert ccb.current_branch(repo) == "claude-exp/run1"

    ok, msg = ccb.delete_branch(repo, "claude-exp/run1", baseline)
    assert ok and msg == "deleted"
    assert not ccb.branch_exists(repo, "claude-exp/run1")


def test_delete_refuses_non_exp_branch(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    main = ccb.current_branch(repo)  # default branch (main/master)
    ok, msg = ccb.delete_branch(repo, main, "HEAD")
    assert not ok and "not an experiment branch" in msg
    assert ccb.branch_exists(repo, main)


def test_delete_absent_branch_is_ok(tmp_path):
    repo = tmp_path / "repo"
    baseline = _init_repo(repo)
    ok, msg = ccb.delete_branch(repo, "claude-exp/missing", baseline)
    assert ok and msg == "already absent"


def test_apply_marks_records_cleaned(tmp_path):
    repo = tmp_path / "repo"
    baseline = _init_repo(repo)
    _git(repo, "branch", "claude-exp/run2")  # exists, not checked out
    records = [{
        "reason": "provider_limit", "branch": "claude-exp/run2",
        "repo_root": str(repo), "baseline_commit": baseline, "model": "m", "cleaned": False,
    }]
    deleted = ccb.apply(records)
    assert deleted == 1
    assert records[0]["cleaned"] is True
    assert not ccb.branch_exists(repo, "claude-exp/run2")


# --------------------------------------------------------------------------- #
# clean script: scan
# --------------------------------------------------------------------------- #

def _write_csv(path: Path, branch: str, *, exit_code: str = "0") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEADER)
    w.writerow(["1", "1", "5", "0", "5", "1.0", exit_code, "0", "sha", "msg", "claude-sonnet-4-6", branch])
    path.write_text(buf.getvalue())


def test_scan_discovers_provider_limit_run(tmp_path):
    output_root = tmp_path / "output"
    exp = output_root / "RealWorld" / "repo-high-Agent"
    model_dir = exp / "20260625T120000Z-claude-sonnet-4-6"
    (model_dir / "run_001").mkdir(parents=True)
    # Session-limit result line in the agent JSONL.
    (model_dir / "run_001" / "claude.jsonl").write_text(
        '{"type":"result","is_error":true,"api_error_status":429,'
        '"result":"You\'ve hit your session limit · resets 9:50am (UTC)","session_id":"s"}'
    )
    _write_csv(_csv := exp / "logs" / "20260625T120000Z-claude-sonnet-4-6-log.csv",
               "claude-exp/20260625T120000Z-claude-sonnet-4-6-high-Agent")

    plan_map = {"repo-high-Agent": {"repo_root": "/data/wt/repo", "baseline": "base123", "category": "RealWorld"}}
    found = ccb.scan_output(output_root, plan_map, known=set())
    assert len(found) == 1
    rec = found[0]
    assert rec["reason"] == clog.REASON_PROVIDER_LIMIT
    assert rec["branch"] == "claude-exp/20260625T120000Z-claude-sonnet-4-6-high-Agent"
    assert rec["repo_root"] == "/data/wt/repo" and rec["baseline_commit"] == "base123"


def test_branch_from_repo_resolves_by_stamp(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "branch", "claude-exp/20260625T120000Z-claude-sonnet-4-6-high-Agent")
    _git(repo, "branch", "codex-exp/20260101T000000Z-gpt-5.5-high-Agent")
    found = ccb._branch_from_repo(str(repo), "20260625T120000Z")
    assert found == "claude-exp/20260625T120000Z-claude-sonnet-4-6-high-Agent"
    assert ccb._branch_from_repo(str(repo), "19990101T000000Z") is None


def test_scan_recovers_branch_from_repo_when_no_csv(tmp_path):
    # A corrupt run whose CSV was already cleaned away: branch is recovered from the repo by stamp.
    repo = tmp_path / "wt"
    _init_repo(repo)
    stamp = "20260625T130000Z"
    branch = f"claude-exp/{stamp}-claude-haiku-4-5-high-Agent"
    _git(repo, "branch", branch)

    output_root = tmp_path / "output"
    model_dir = output_root / "Algorithms" / "011_x-high-Agent" / f"{stamp}-claude-haiku-4-5"
    (model_dir / "run_001").mkdir(parents=True)
    (model_dir / "run_001" / "claude.jsonl").write_text(
        '{"type":"result","is_error":true,"api_error_status":429,'
        '"result":"You\'ve hit your session limit · resets 9:50am (UTC)"}'
    )  # note: no logs/*.csv written

    plan_map = {"011_x-high-Agent": {"repo_root": str(repo), "baseline": "b", "category": "Algorithms"}}
    found = ccb.scan_output(output_root, plan_map, known=set())
    assert len(found) == 1 and found[0]["branch"] == branch


def test_scan_skips_known_and_healthy(tmp_path):
    output_root = tmp_path / "output"
    exp = output_root / "Algorithms" / "001_x-high-Agent"
    model_dir = exp / "20260625T120000Z-gpt-5.5"
    (model_dir / "run_001").mkdir(parents=True)
    (model_dir / "run_001" / "codex.jsonl").write_text('{"type":"item","text":"refactored fine"}')
    _write_csv(exp / "logs" / "20260625T120000Z-gpt-5.5-log.csv", "codex-exp/healthy", exit_code="0")
    # Healthy run (exit 0, no limit) -> nothing discovered.
    found = ccb.scan_output(output_root, {}, known=set())
    assert found == []
