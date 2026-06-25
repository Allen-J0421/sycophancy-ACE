"""Tests for provider usage/session-limit detection, marker round-trip, and the
orchestrator's auto-pause scheduling helpers."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import run_pipeline  # noqa: E402
from experiment_runner.limit_detect import (  # noqa: E402
    OVERLOAD,
    QUOTA,
    SESSION_LIMIT,
    SPEND_CAP,
    LimitDetectConfig,
    LimitHit,
    detect_codex_limit,
    detect_gemini_limit,
    detect_limit,
    parse_claude_reset,
)
from experiment_runner.limit_marker import (  # noqa: E402
    stderr_marker_line,
    write_limit_marker,
)

LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 6, 25, 8, 0, tzinfo=LA)  # 8:00 AM Pacific
DEFAULT = LimitDetectConfig()


def _claude_result_line(**fields) -> str:
    base = {"type": "result", "subtype": "success", "session_id": "abc"}
    base.update(fields)
    return json.dumps(base)


# --------------------------------------------------------------------------- #
# parse_claude_reset
# --------------------------------------------------------------------------- #

def test_reset_same_day_with_tz():
    dt = parse_claude_reset("resets 9:50am (America/Los_Angeles)", now=NOW)
    assert dt == datetime(2026, 6, 25, 9, 50, tzinfo=LA)


def test_reset_rolls_to_next_day_no_tz():
    # 3:30am is before 8:00am now -> tomorrow, in now's tz when no tz given.
    dt = parse_claude_reset("resets 3:30am", now=NOW)
    assert dt == datetime(2026, 6, 26, 3, 30, tzinfo=LA)


def test_reset_noon_and_midnight():
    assert parse_claude_reset("resets 12:00pm", now=NOW) == datetime(2026, 6, 25, 12, 0, tzinfo=LA)
    # 12:00am == 00:00, before 08:00 -> tomorrow.
    assert parse_claude_reset("resets 12:00am", now=NOW) == datetime(2026, 6, 26, 0, 0, tzinfo=LA)


def test_reset_unknown_tz_falls_back_to_now_tz():
    dt = parse_claude_reset("resets 10:00am (Mars/Phobos)", now=NOW)
    assert dt == datetime(2026, 6, 25, 10, 0, tzinfo=LA)


@pytest.mark.parametrize("text", ["no reset here", "resets 13:00pm", "resets 99am"])
def test_reset_garbage_returns_none(text):
    assert parse_claude_reset(text, now=NOW) is None


# --------------------------------------------------------------------------- #
# detect_claude_limit (via dispatcher)
# --------------------------------------------------------------------------- #

def test_claude_429_session_limit_positive():
    jsonl = _claude_result_line(
        is_error=True,
        api_error_status=429,
        result="You've hit your session limit · resets 9:50am (America/Los_Angeles)",
    )
    hit = detect_limit(provider="claude", jsonl_text=jsonl, cfg=DEFAULT, now=NOW)
    assert hit is not None
    assert hit.provider == "claude" and hit.kind == SESSION_LIMIT
    assert hit.reset_dt == datetime(2026, 6, 25, 9, 50, tzinfo=LA)


def test_claude_normal_result_negative():
    jsonl = _claude_result_line(is_error=False, result="No. I won't make that change.")
    assert detect_limit(provider="claude", jsonl_text=jsonl, cfg=DEFAULT, now=NOW) is None


def test_claude_text_match_without_429():
    # Limit text present but api_error_status absent -> still a hit (no parseable reset).
    jsonl = _claude_result_line(is_error=True, api_error_status=None,
                                result="You've hit your usage limit")
    hit = detect_limit(provider="claude", jsonl_text=jsonl, cfg=DEFAULT, now=NOW)
    assert hit is not None and hit.reset_dt is None


def test_claude_skips_malformed_lines():
    jsonl = "not json {{{\n" + _claude_result_line(
        is_error=True, api_error_status=429,
        result="You've hit your session limit · resets 3:30am (America/Los_Angeles)",
    )
    hit = detect_limit(provider="claude", jsonl_text=jsonl, cfg=DEFAULT, now=NOW)
    assert hit is not None and hit.reset_dt == datetime(2026, 6, 26, 3, 30, tzinfo=LA)


# --------------------------------------------------------------------------- #
# detect_codex_limit
# --------------------------------------------------------------------------- #

def test_codex_spend_cap_positive():
    jsonl = json.dumps({"type": "item", "text": "turn.failed: spend cap reached"})
    hit = detect_codex_limit(jsonl, DEFAULT)
    assert hit is not None and hit.provider == "codex" and hit.kind == SPEND_CAP
    assert hit.reset_dt is None


def test_codex_ordinary_output_negative():
    jsonl = json.dumps({"type": "item", "text": "Refactored the queue class."})
    assert detect_codex_limit(jsonl, DEFAULT) is None


def test_codex_custom_pattern_override():
    cfg = LimitDetectConfig(codex_patterns=(re.compile(r"quota exceeded", re.I),))
    hit = detect_codex_limit("error: monthly quota exceeded", cfg)
    assert hit is not None and hit.kind == SPEND_CAP


# --------------------------------------------------------------------------- #
# detect_gemini_limit (default: silent)
# --------------------------------------------------------------------------- #

def _gemini_error(status: int) -> str:
    return json.dumps({"event": "error", "text": "boom", "payload": {"status_code": status}})


def test_gemini_default_config_silent():
    assert detect_gemini_limit(_gemini_error(429), DEFAULT) is None
    assert detect_gemini_limit(_gemini_error(503), DEFAULT) is None


def test_gemini_429_surfaced_when_enabled():
    cfg = LimitDetectConfig(gemini_surface=True)
    hit = detect_gemini_limit(_gemini_error(429), cfg)
    assert hit is not None and hit.kind == QUOTA and hit.provider == "gemini"
    # 503 still silent unless explicitly enabled.
    assert detect_gemini_limit(_gemini_error(503), cfg) is None


def test_gemini_503_surfaced_only_with_flag():
    cfg = LimitDetectConfig(gemini_surface_503=True)
    hit = detect_gemini_limit(_gemini_error(503), cfg)
    assert hit is not None and hit.kind == OVERLOAD


# --------------------------------------------------------------------------- #
# dispatcher gating
# --------------------------------------------------------------------------- #

def test_dispatcher_disabled_returns_none():
    cfg = LimitDetectConfig(enabled=False)
    jsonl = _claude_result_line(is_error=True, api_error_status=429,
                                result="You've hit your session limit · resets 9:50am (UTC)")
    assert detect_limit(provider="claude", jsonl_text=jsonl, cfg=cfg, now=NOW) is None


def test_dispatcher_gemini_provider_not_handled_here():
    assert detect_limit(provider="gemini", jsonl_text="", cfg=DEFAULT) is None


# --------------------------------------------------------------------------- #
# limit_marker round-trip
# --------------------------------------------------------------------------- #

def test_marker_round_trip(tmp_path):
    hit = LimitHit(provider="claude", reset_dt=datetime(2026, 6, 25, 9, 50, tzinfo=LA),
                   raw="You've hit your session limit", kind=SESSION_LIMIT)
    path = write_limit_marker(hit, exp_dir=tmp_path,
                              partial_csv=tmp_path / "logs" / "x-log.csv",
                              artifacts_dir=tmp_path / "x")
    data = json.loads(path.read_text())
    assert data["provider"] == "claude"
    assert data["reset_dt_iso"] == "2026-06-25T09:50:00-07:00"
    assert data["partial_csv"].endswith("x-log.csv")
    assert "PROVIDER_LIMIT provider=claude kind=session_limit" in stderr_marker_line(hit)


def test_marker_null_reset():
    hit = LimitHit(provider="codex", reset_dt=None, raw="spend cap", kind=SPEND_CAP)
    assert stderr_marker_line(hit) == "PROVIDER_LIMIT provider=codex kind=spend_cap reset="


# --------------------------------------------------------------------------- #
# orchestrator helpers
# --------------------------------------------------------------------------- #

def _make_task(tmp_path, *, model="claude-sonnet-4-6", prompter=True):
    return run_pipeline.Task(
        category="realworld",
        output_base=tmp_path,
        target=tmp_path / "repo",
        commit="abc123",
        models=[model],
        iterations=1,
        phases=["run_exp"],
        prompter=prompter,
        label="high",
        exp_folder="repo-high-Agent",  # explicit -> skips git in __post_init__
    )


def test_step_providers():
    t = _make_task(Path("/tmp"), model="claude-opus-4-8", prompter=True)
    step = run_pipeline.Step("k", t, "run_exp", "claude-opus-4-8")
    assert run_pipeline.step_providers(step) == {"claude", "gemini"}

    t2 = _make_task(Path("/tmp"), model="gpt-5.5", prompter=False)
    step2 = run_pipeline.Step("k", t2, "run_exp", "gpt-5.5")
    assert run_pipeline.step_providers(step2) == {"codex"}


def test_block_until_uses_reset_plus_buffer():
    cfg = run_pipeline.PauseConfig(buffer_min=2)
    marker = {"reset_dt_iso": "2026-06-25T09:50:00-07:00"}
    out = run_pipeline._block_until(marker, cfg)
    assert out == datetime(2026, 6, 25, 9, 52, tzinfo=LA)


def test_block_until_fixed_fallback_on_null_or_bad():
    cfg = run_pipeline.PauseConfig(fixed_wait_min=60)
    before = datetime.now(timezone.utc)
    out_null = run_pipeline._block_until({"reset_dt_iso": None}, cfg)
    out_bad = run_pipeline._block_until({"reset_dt_iso": "not-a-date"}, cfg)
    for out in (out_null, out_bad):
        delta_min = (out - before).total_seconds() / 60
        assert 59 <= delta_min <= 61


def test_clean_dead_run_removes_paths(tmp_path):
    csv = tmp_path / "logs" / "x-log.csv"
    csv.parent.mkdir(parents=True)
    csv.write_text("header\n")
    art = tmp_path / "x"
    (art / "run_001").mkdir(parents=True)
    marker = {"partial_csv": str(csv), "artifacts_dir": str(art)}
    run_pipeline.clean_dead_run(marker, cleanup=True)
    assert not csv.exists() and not art.exists()


def test_clean_dead_run_respects_disable(tmp_path):
    csv = tmp_path / "x-log.csv"
    csv.write_text("header\n")
    run_pipeline.clean_dead_run({"partial_csv": str(csv)}, cleanup=False)
    assert csv.exists()


def test_run_step_maps_exit_3_to_blocked(tmp_path, monkeypatch):
    task = _make_task(tmp_path, model="claude-sonnet-4-6")
    step = run_pipeline.Step("repo-high-Agent::run_exp::claude-sonnet-4-6", task, "run_exp",
                             "claude-sonnet-4-6")

    class _Proc:
        returncode = 3

    monkeypatch.setattr(run_pipeline.subprocess, "run", lambda *a, **k: _Proc())
    status, detail = run_pipeline.run_step(step, dry_run=False)
    assert status == "blocked"
    assert "exit=3" in detail


def test_schedule_skips_ahead_and_retries(tmp_path, monkeypatch):
    """A blocked claude step is cleaned up + requeued; the codex step runs in the meantime;
    the claude step then succeeds on retry. No real sleeping."""
    state = run_pipeline.State(tmp_path / "state.json")
    claude_task = _make_task(tmp_path, model="claude-sonnet-4-6")
    codex_task = _make_task(tmp_path, model="gpt-5.5")
    claude_step = run_pipeline.Step("c::run_exp::claude-sonnet-4-6", claude_task, "run_exp",
                                    "claude-sonnet-4-6")
    codex_step = run_pipeline.Step("x::run_exp::gpt-5.5", codex_task, "run_exp", "gpt-5.5")

    calls: list[str] = []
    claude_attempts = {"n": 0}

    def fake_run_step(step, *, dry_run):
        calls.append(step.model)
        if step.model.startswith("claude"):
            claude_attempts["n"] += 1
            if claude_attempts["n"] == 1:
                return ("blocked", "exit=3")
            return ("done", "exit=0")
        return ("done", "exit=0")

    monkeypatch.setattr(run_pipeline, "run_step", fake_run_step)
    monkeypatch.setattr(run_pipeline, "read_limit_marker",
                        lambda task: {"provider": "claude", "reset_dt_iso": None})
    # Block clears immediately so we never sleep in the test.
    monkeypatch.setattr(run_pipeline, "_block_until",
                        lambda marker, cfg: datetime.now(timezone.utc))
    monkeypatch.setattr(run_pipeline, "clean_dead_run", lambda marker, cleanup: None)
    monkeypatch.setattr(run_pipeline, "clear_limit_marker", lambda task: None)

    args = argparse.Namespace(retry_failed=False, force=False, dry_run=False, no_dep_check=False)
    counts = {"done": 0, "failed": 0, "skipped": 0, "blocked": 0}
    cfg = run_pipeline.PauseConfig()

    run_pipeline.schedule_run_exp([claude_step, codex_step], state, args, counts, cfg)

    assert counts["done"] == 2
    assert claude_attempts["n"] == 2  # blocked once, then succeeded
    assert "gpt-5.5" in calls
    assert state.is_done(claude_step.key) and state.is_done(codex_step.key)


# --------------------------------------------------------------------------- #
# End-to-end: the experiment loop aborts before persisting a dead turn
# --------------------------------------------------------------------------- #

def test_experiment_runner_aborts_on_session_limit(tmp_path):
    from experiment_runner.experiment import ExperimentRunner
    from experiment_runner.limit_detect import ProviderLimitError
    from experiment_runner.models import (
        AgentRunResult,
        ExperimentConfig,
        LineStats,
        PromptTurn,
        TargetScope,
    )

    session_limit_jsonl = _claude_result_line(
        is_error=True, api_error_status=429,
        result="You've hit your session limit · resets 9:50am (America/Los_Angeles)",
    )

    class _Agent:
        def run(self, prompt, *, is_first, session_id=None):
            return (AgentRunResult(exit_code=0, duration_s=0.0, timed_out=False,
                                   session_id="sid-1"), session_limit_jsonl)

    class _Git:
        def setup_branch(self, start_commit, branch):
            return "init-sha"

        def stage_all_and_diff_stats(self, prev, pathspec):
            return LineStats.empty()

        def capture_step_diff(self, prev, pathspec):
            return ""

        def commit(self, message):
            return "commit-sha"

    class _Prompts:
        def next_prompt(self, last_turn_input=None):
            return PromptTurn(prompt="refactor", prompter_jsonl="")

        def respond_to_clarification(self, coding_reply):
            return PromptTurn(prompt="clarify", prompter_jsonl="")

    exp_dir = tmp_path / "repo-high-Agent"
    config = ExperimentConfig(
        target=TargetScope(root=tmp_path, rel_path="", pathspec=None, work_dir=tmp_path),
        prompt="refactor",
        requested_model="claude-sonnet-4-6",
        effective_model="claude-sonnet-4-6",
        branch="claude-exp/x",
        results_csv=exp_dir / "logs" / "stamp-claude-sonnet-4-6-log.csv",
        artifacts_dir=exp_dir / "stamp-claude-sonnet-4-6",
        start_commit="abc",
        iterations=3,
        agent="claude",
        prompter=False,
        limit_detect=LimitDetectConfig(),
    )
    runner = ExperimentRunner(config, git=_Git(), agent=_Agent(), prompt_source=_Prompts(),
                              limit_cfg=config.limit_detect)

    with pytest.raises(ProviderLimitError) as exc:
        runner.write_log()
    hit = exc.value.hit
    assert hit.provider == "claude"
    # reset_dt resolves against real wall-clock now, so assert time-of-day, not the date.
    assert hit.reset_dt is not None
    assert (hit.reset_dt.hour, hit.reset_dt.minute) == (9, 50)
    assert hit.reset_dt.tzinfo == LA
    # The dead turn's artifacts must never be written.
    assert not (config.artifacts_dir / "run_001").exists()
