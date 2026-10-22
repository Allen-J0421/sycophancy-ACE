"""Tests for the proactive usage guard (Claude + Codex): usage parsing + policy (agent_usage),
the per-turn pause gate (experiment_runner.usage_gate), and the orchestrator's pre-run check."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import agent_usage  # noqa: E402
import run_pipeline  # noqa: E402
from agent_usage import (  # noqa: E402
    CODEX_DEFAULTS,
    GuardConfig,
    RunEstimator,
    UsageSnapshot,
    UsageWindow,
    blocking_window,
    load_guard_config,
    parse_reset,
    parse_codex_rate_limits,
    parse_usage_text,
    probe_claude_usage,
    probe_codex_usage,
    start_decision,
    window_deltas,
)
from experiment_runner.limit_detect import (  # noqa: E402
    SESSION_LIMIT,
    WEEKLY_LIMIT,
    ProviderLimitError,
)
from experiment_runner.usage_gate import UsageGate  # noqa: E402

LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 10, 22, 10, 0, tzinfo=LA)

# Verbatim `claude -p /usage` output (Claude Code 2.1.195), trimmed after the limits block.
USAGE_TEXT = """You are currently using your subscription to power your Claude Code usage

Current session: 4% used · resets Oct 22 at 2pm (America/Los_Angeles)
Current week (all models): 7% used · resets Oct 28 at 8am (America/Los_Angeles)
Current week (Fable): 0% used · resets Oct 28 at 8am (America/Los_Angeles)

What's contributing to your limits usage?
Last 24h · 81 requests · 2 sessions
"""


def _snap(session=10.0, week=10.0, *, s_reset=None, w_reset=None, extra=()):
    return UsageSnapshot(
        session=UsageWindow("session", "", session, s_reset),
        weekly=(UsageWindow("week", "all models", week, w_reset), *extra),
    )


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #

def test_parse_real_usage_output():
    snap = parse_usage_text(USAGE_TEXT, now=NOW)
    assert snap.session.percent == 4.0
    assert snap.session.resets_at == datetime(2026, 10, 22, 14, 0, tzinfo=LA)
    labels = [(w.label, w.percent) for w in snap.weekly]
    assert labels == [("all models", 7.0), ("Fable", 0.0)]
    assert snap.weekly[0].resets_at == datetime(2026, 10, 28, 8, 0, tzinfo=LA)


@pytest.mark.parametrize("text,expected", [
    ("Oct 22 at 2:30pm (America/Los_Angeles)", datetime(2026, 10, 22, 14, 30, tzinfo=LA)),
    ("Oct 23, 2026 at 12am (America/Los_Angeles)", datetime(2026, 10, 23, 0, 0, tzinfo=LA)),
    ("11am (America/Los_Angeles)", datetime(2026, 10, 22, 11, 0, tzinfo=LA)),
    ("9am (America/Los_Angeles)", datetime(2026, 10, 23, 9, 0, tzinfo=LA)),  # passed -> tomorrow
])
def test_parse_reset_variants(text, expected):
    assert parse_reset(text, now=NOW) == expected


def test_parse_reset_rolls_year_forward():
    dec = datetime(2026, 12, 30, 12, 0, tzinfo=LA)
    assert parse_reset("Jan 2 at 8am (America/Los_Angeles)", now=dec) == \
        datetime(2027, 1, 2, 8, 0, tzinfo=LA)


@pytest.mark.parametrize("text", ["", "soon", "Foo 3 at 2pm", "13pm", "Feb 30 at 1pm"])
def test_parse_reset_garbage_returns_none(text):
    assert parse_reset(text, now=NOW) is None


def test_parse_usage_without_limit_lines_returns_none():
    assert parse_usage_text("API key auth: usage-based billing, no plan limits") is None


def test_weekly_for_matches_per_model_window():
    opus = UsageWindow("week", "Opus", 50.0, None)
    snap = _snap(extra=(opus,))
    assert opus in snap.weekly_for("claude-opus-4-8")
    assert opus not in snap.weekly_for("claude-sonnet-4-6")
    assert [w.label for w in snap.weekly_for("claude-sonnet-4-6")] == ["all models"]


# --------------------------------------------------------------------------- #
# probe
# --------------------------------------------------------------------------- #

class _Proc:
    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def test_probe_parses_cli_json():
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return _Proc(stdout=json.dumps({"result": USAGE_TEXT, "total_cost_usd": 0}))

    snap = probe_claude_usage(run=run, now=NOW)
    assert snap.session.percent == 4.0
    assert "/usage" in seen["cmd"] and "--no-session-persistence" in seen["cmd"]


@pytest.mark.parametrize("run", [
    lambda cmd, **kw: _Proc(returncode=1),
    lambda cmd, **kw: _Proc(stdout="not json"),
    lambda cmd, **kw: _Proc(stdout=json.dumps({"result": "no limits here"})),
])
def test_probe_failures_return_none(run):
    assert probe_claude_usage(run=run) is None


def test_probe_missing_cli_or_timeout_returns_none():
    def missing(cmd, **kw):
        raise FileNotFoundError("claude")

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    assert probe_claude_usage(run=missing) is None
    assert probe_claude_usage(run=slow) is None


# --------------------------------------------------------------------------- #
# policy
# --------------------------------------------------------------------------- #

CFG = GuardConfig(session_ceiling=85, weekly_ceiling=95)
FALLBACK = NOW + timedelta(hours=1)


def test_blocking_window_weekly_takes_precedence():
    snap = _snap(session=90, week=96)
    assert blocking_window(snap, "claude-sonnet-4-6", CFG).kind == "week"
    assert blocking_window(_snap(session=90), "m", CFG).kind == "session"
    assert blocking_window(_snap(session=84.9), "m", CFG) is None


def test_start_over_ceiling_waits_for_reset():
    reset = NOW + timedelta(hours=2)
    d = start_decision(_snap(session=86, s_reset=reset), "m", CFG,
                       estimate=40, other_work=False, fallback_until=FALLBACK)
    assert not d.ok and d.until == reset


def test_start_without_reset_uses_fallback():
    d = start_decision(_snap(week=99), "m", CFG, estimate=40, other_work=True,
                       fallback_until=FALLBACK)
    assert not d.ok and d.until == FALLBACK


def test_start_defers_only_when_other_work_can_fill_gap():
    reset = NOW + timedelta(hours=3)
    snap = _snap(session=60, s_reset=reset)  # 60 + 40 crosses 85
    deferred = start_decision(snap, "m", CFG, estimate=40, other_work=True, fallback_until=FALLBACK)
    assert not deferred.ok and deferred.until == reset
    started = start_decision(snap, "m", CFG, estimate=40, other_work=False, fallback_until=FALLBACK)
    assert started.ok


def test_start_ok_when_probe_unavailable_or_disabled():
    assert start_decision(None, "m", CFG, estimate=40, other_work=True, fallback_until=FALLBACK).ok
    off = GuardConfig(enabled=False)
    assert start_decision(_snap(session=100), "m", off, estimate=40, other_work=True,
                          fallback_until=FALLBACK).ok


def test_run_estimator_learns_conservatively():
    est = RunEstimator(40, keep=3)
    assert est.estimate("m") == 40
    reset = NOW + timedelta(hours=4)
    for before, after in ((10, 30), (30, 55), (55, 60), (60, 72)):
        est.observe("m", _snap(session=before, s_reset=reset), _snap(session=after, s_reset=reset))
    assert est.estimate("m") == 25  # max of last 3 deltas (25, 5, 12); oldest (20) dropped
    est.observe("m", _snap(session=0, s_reset=reset), _snap(session=3, s_reset=reset))
    est.observe("m", _snap(session=3, s_reset=reset), _snap(session=6, s_reset=reset))
    assert est.estimate("m") == 12  # 25 aged out: (12, 3, 3)
    est2 = RunEstimator(40)
    est2.observe("m", _snap(session=10, s_reset=reset), _snap(session=30, s_reset=reset))
    assert est2.estimate("m") == 20
    assert est2.estimate("other") == 40


def test_run_estimator_ignores_runs_spanning_a_reset():
    est = RunEstimator(40)
    used = est.observe("m", _snap(session=80, s_reset=NOW), _snap(session=20, s_reset=NOW + timedelta(hours=5)))
    assert used is None and est.estimate("m") == 40


def test_load_guard_config_from_lookup():
    env = {"LIMIT_GUARD_SESSION_CEILING": "70", "LIMIT_GUARD_WEEKLY_CEILING": "90.5",
           "LIMIT_GUARD_RUN_ESTIMATE": "bad", "LIMIT_GUARD_MAX_PAUSE_MINUTES": "30"}
    cfg = load_guard_config(env.get)
    assert (cfg.enabled, cfg.session_ceiling, cfg.weekly_ceiling) == (True, 70, 90.5)
    assert cfg.run_estimate == 40 and cfg.max_pause_min == 30
    assert load_guard_config({"LIMIT_GUARD_ENABLED": "false"}.get).enabled is False


def test_runner_settings_env_var_overrides_prompt_env(monkeypatch):
    from experiment_runner import usage_gate
    monkeypatch.setattr(usage_gate, "load_prompt_env_entries",
                        lambda: ({"LIMIT_GUARD_SESSION_CEILING": "85",
                                  "LIMIT_BUFFER_MINUTES": "5"}, None))
    monkeypatch.setenv("LIMIT_GUARD_SESSION_CEILING", "60")
    cfg, buffer_min = usage_gate.load_usage_guard_settings()
    assert cfg.session_ceiling == 60 and buffer_min == 5


# --------------------------------------------------------------------------- #
# per-turn gate (runner)
# --------------------------------------------------------------------------- #

class _Clock:
    def __init__(self, now):
        self.now = now
        self.slept = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept += seconds
        self.now += timedelta(seconds=seconds)


def test_gate_passes_when_under_ceiling():
    clock = _Clock(NOW)
    gate = UsageGate("m", CFG, probe=lambda: _snap(session=50), sleep=clock.sleep, clock=clock)
    gate.wait_for_headroom()
    assert clock.slept == 0


def test_gate_passes_when_probe_unavailable():
    clock = _Clock(NOW)
    UsageGate("m", CFG, probe=lambda: None, sleep=clock.sleep, clock=clock).wait_for_headroom()
    assert clock.slept == 0


def test_gate_pauses_until_reset_then_continues():
    clock = _Clock(NOW)
    reset = NOW + timedelta(hours=2)
    snaps = iter([_snap(session=90, s_reset=reset), _snap(session=1, s_reset=reset + timedelta(hours=5))])
    gate = UsageGate("m", CFG, buffer_min=2, probe=lambda: next(snaps), sleep=clock.sleep, clock=clock)
    gate.wait_for_headroom()
    assert clock.now == reset + timedelta(minutes=2)


def test_gate_aborts_when_wait_exceeds_max_pause():
    clock = _Clock(NOW)
    weekly_reset = NOW + timedelta(days=3)
    gate = UsageGate("m", GuardConfig(max_pause_min=480),
                     probe=lambda: _snap(week=97, w_reset=weekly_reset),
                     sleep=clock.sleep, clock=clock)
    with pytest.raises(ProviderLimitError) as exc:
        gate.wait_for_headroom()
    assert exc.value.hit.kind == WEEKLY_LIMIT
    assert exc.value.hit.reset_dt == weekly_reset
    assert clock.slept == 0


def test_gate_aborts_when_reset_unknown():
    clock = _Clock(NOW)
    gate = UsageGate("m", CFG, probe=lambda: _snap(session=99), sleep=clock.sleep, clock=clock)
    with pytest.raises(ProviderLimitError) as exc:
        gate.wait_for_headroom()
    assert exc.value.hit.kind == SESSION_LIMIT


def test_gate_stale_reset_rechecks_after_one_poll():
    clock = _Clock(NOW)
    stale = NOW - timedelta(minutes=10)  # /usage not rolled over yet
    snaps = iter([_snap(session=90, s_reset=stale), _snap(session=0)])
    gate = UsageGate("m", CFG, buffer_min=2, poll_s=60, probe=lambda: next(snaps),
                     sleep=clock.sleep, clock=clock)
    gate.wait_for_headroom()
    assert clock.slept == 60


def test_experiment_runner_checks_gate_before_every_turn(tmp_path):
    from experiment_runner.experiment import ExperimentRunner
    from experiment_runner.limit_detect import LimitDetectConfig
    from experiment_runner.models import (
        AgentRunResult,
        ExperimentConfig,
        LineStats,
        PromptTurn,
        TargetScope,
    )

    ok_jsonl = json.dumps({"type": "result", "is_error": False, "result": "done",
                           "session_id": "sid-1"})

    class _Agent:
        def run(self, prompt, *, is_first, session_id=None):
            return (AgentRunResult(exit_code=0, duration_s=0.0, timed_out=False,
                                   session_id="sid-1"), ok_jsonl)

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

    class _Gate:
        calls = 0

        def wait_for_headroom(self):
            _Gate.calls += 1

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
                              limit_cfg=config.limit_detect, usage_gate=_Gate())
    runner.write_log()
    assert _Gate.calls == 3
    assert (config.artifacts_dir / "run_003").exists()


def test_build_usage_gate_for_claude_and_codex(monkeypatch):
    from experiment_runner import usage_gate
    monkeypatch.setattr(usage_gate, "load_usage_guard_settings",
                        lambda provider="claude": (GuardConfig(), 2))
    claude_gate = usage_gate.build_usage_gate("claude", "claude-opus-4-8")
    codex_gate = usage_gate.build_usage_gate("codex", "gpt-5.5")
    assert isinstance(claude_gate, UsageGate) and claude_gate.provider == "claude"
    assert isinstance(codex_gate, UsageGate) and codex_gate.provider == "codex"
    assert usage_gate.build_usage_gate("gemini", "x") is None
    monkeypatch.setattr(usage_gate, "load_usage_guard_settings",
                        lambda provider="claude": (GuardConfig(enabled=False), 2))
    assert usage_gate.build_usage_gate("codex", "gpt-5.5") is None


# --------------------------------------------------------------------------- #
# orchestrator pre-run check
# --------------------------------------------------------------------------- #

def _make_task(tmp_path, model):
    return run_pipeline.Task(
        category="realworld", output_base=tmp_path, target=tmp_path / "repo", commit="abc123",
        models=[model], iterations=1, phases=["run_exp"], prompter=False, label="high",
        exp_folder="repo-high-Agent",
    )


def test_pause_config_guard_off_by_default():
    cfg = run_pipeline.PauseConfig()
    step = run_pipeline.Step("k", _make_task(Path("/tmp"), "claude-opus-4-8"), "run_exp",
                             "claude-opus-4-8")
    assert cfg.guards == {} and cfg.guard_for(step) is None


def test_schedule_holds_claude_at_ceiling_and_runs_codex_meanwhile(tmp_path, monkeypatch):
    clock = {"now": datetime(2026, 10, 22, 17, 0, tzinfo=timezone.utc)}

    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    reset = clock["now"] + timedelta(hours=2)
    probes = iter([
        _snap(session=90, s_reset=reset),                           # pre-run: at ceiling
        _snap(session=5, s_reset=reset + timedelta(hours=5)),       # after reset: room
        _snap(session=25, s_reset=reset + timedelta(hours=5)),      # after the run
    ])
    monkeypatch.setattr(run_pipeline, "datetime", _FakeDT)
    monkeypatch.setattr(run_pipeline.agent_usage, "probe_usage",
                        lambda provider, **kw: next(probes))
    slept_to = []

    def fake_sleep_until(target, *, poll_s):
        slept_to.append(target)
        clock["now"] = target

    monkeypatch.setattr(run_pipeline, "_sleep_until", fake_sleep_until)
    calls: list[str] = []
    monkeypatch.setattr(run_pipeline, "run_step",
                        lambda step, *, dry_run: (calls.append(step.model), ("done", "exit=0"))[1])

    state = run_pipeline.State(tmp_path / "state.json")
    claude = run_pipeline.Step("c::run_exp::claude-sonnet-4-6",
                               _make_task(tmp_path, "claude-sonnet-4-6"), "run_exp",
                               "claude-sonnet-4-6")
    codex = run_pipeline.Step("x::run_exp::gpt-5.5", _make_task(tmp_path, "gpt-5.5"),
                              "run_exp", "gpt-5.5")
    args = argparse.Namespace(retry_failed=False, force=False, dry_run=False, no_dep_check=False)
    counts = {"done": 0, "failed": 0, "skipped": 0, "blocked": 0}
    cfg = run_pipeline.PauseConfig(buffer_min=2, guards={"claude": GuardConfig(session_ceiling=85)})

    run_pipeline.schedule_run_exp([claude, codex], state, args, counts, cfg)

    assert calls == ["gpt-5.5", "claude-sonnet-4-6"]
    assert slept_to == [reset + timedelta(minutes=2)]
    assert counts["done"] == 2 and counts["blocked"] == 0


# --------------------------------------------------------------------------- #
# Codex: app-server rate limits
# --------------------------------------------------------------------------- #

# Shape of a live `account/rateLimits/read` result (codex-cli 0.140.0, edu plan).
CODEX_RESULT = {
    "rateLimits": {
        "limitId": "codex",
        "primary": {"usedPercent": 37, "windowDurationMins": 300, "resetsAt": 1792713715},
        "secondary": {"usedPercent": 12, "windowDurationMins": 10080, "resetsAt": 1793300515},
        "credits": {"hasCredits": True, "unlimited": False, "balance": None},
        "planType": "edu",
        "rateLimitReachedType": None,
    },
}


def test_parse_codex_rate_limits():
    snap = parse_codex_rate_limits(CODEX_RESULT)
    assert snap.session.percent == 37 and snap.session.kind == "session"
    assert snap.session.resets_at == datetime.fromtimestamp(1792713715, tz=timezone.utc)
    assert [(w.label, w.percent) for w in snap.weekly] == [("all models", 12)]
    assert snap.weekly_for("gpt-5.5") == list(snap.weekly)
    assert snap.has_credits is True and snap.limit_reached is None


@pytest.mark.parametrize("result", [None, {}, {"rateLimits": None},
                                    {"rateLimits": {"primary": {"usedPercent": "n/a"}}}])
def test_parse_codex_rate_limits_bad_shapes(result):
    assert parse_codex_rate_limits(result) is None


def test_probe_codex_usage_uses_rpc_result():
    assert probe_codex_usage(rpc=lambda **kw: CODEX_RESULT).session.percent == 37
    assert probe_codex_usage(rpc=lambda **kw: None) is None


def test_codex_rpc_against_fake_app_server(tmp_path, monkeypatch):
    """Exercise the real JSON-RPC stdio exchange against a stand-in `codex` executable."""
    fake = tmp_path / "codex"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"RESULT = {json.dumps(CODEX_RESULT)!r}\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if msg.get('method') == 'initialize':\n"
        "        print(json.dumps({'id': msg['id'], 'result': {}}), flush=True)\n"
        "        print(json.dumps({'method': 'remoteControl/status/changed'}), flush=True)\n"
        "    elif msg.get('method') == 'account/rateLimits/read':\n"
        "        print(json.dumps({'id': msg['id'], 'result': json.loads(RESULT)}), flush=True)\n"
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    snap = agent_usage.probe_usage("codex", timeout_s=20)
    assert snap is not None and snap.session.percent == 37


def test_codex_rpc_missing_cli_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert agent_usage.codex_rate_limits_rpc(timeout_s=5) is None


def test_codex_full_window_pauses_unless_using_credits():
    full = parse_codex_rate_limits({"rateLimits": {
        **CODEX_RESULT["rateLimits"], "primary": {"usedPercent": 100, "resetsAt": 1792713715}}})
    assert blocking_window(full, "gpt-5.5", CODEX_DEFAULTS).kind == "session"
    with_credits = GuardConfig(session_ceiling=100, weekly_ceiling=100, use_credits=True)
    assert blocking_window(full, "gpt-5.5", with_credits) is None


def test_codex_limit_reached_flag_blocks_even_below_ceiling():
    snap = UsageSnapshot(session=UsageWindow("session", "", 40, None),
                         weekly=(UsageWindow("week", "all models", 99, None),),
                         limit_reached="rate_limit")
    assert blocking_window(snap, "gpt-5.5", CODEX_DEFAULTS).kind == "week"


def test_load_guard_config_codex_prefix_and_defaults():
    cfg = load_guard_config({}.get, "codex")
    assert (cfg.session_ceiling, cfg.weekly_ceiling, cfg.use_credits) == (100, 100, False)
    env = {"LIMIT_GUARD_CODEX_USE_CREDITS": "true", "LIMIT_GUARD_CODEX_SESSION_CEILING": "95",
           "LIMIT_GUARD_SESSION_CEILING": "10"}
    cfg = load_guard_config(env.get, "codex")
    assert cfg.use_credits is True and cfg.session_ceiling == 95
    assert load_guard_config(env.get, "claude").session_ceiling == 10
    assert load_guard_config({"LIMIT_GUARD_USE_CREDITS": "true"}.get, "claude").use_credits is False


# --------------------------------------------------------------------------- #
# per-turn learning
# --------------------------------------------------------------------------- #

def test_window_deltas_same_reset_only():
    r1, r2 = NOW + timedelta(hours=1), NOW + timedelta(days=3)
    before = _snap(session=10, week=20, s_reset=r1, w_reset=r2)
    after = _snap(session=18, week=21, s_reset=r1, w_reset=r2)
    assert window_deltas(before, after) == {"session": 8, "week (all models)": 1}
    rolled = _snap(session=2, week=21, s_reset=r1 + timedelta(hours=5), w_reset=r2)
    assert window_deltas(before, rolled) == {"week (all models)": 1}


def test_gate_pauses_when_next_turn_would_cross_ceiling():
    """No headroom cap (Codex 100%): 80% + a learned 15%-per-turn fits, 92% does not."""
    clock = _Clock(NOW)
    reset = NOW + timedelta(hours=1)
    snaps = iter([
        _snap(session=65, s_reset=reset),                     # turn 1: 65 + default 5 -> go
        _snap(session=80, s_reset=reset),                     # turn 2: learned 15 -> 95 -> go
        _snap(session=92, s_reset=reset),                     # turn 3: 92 + 15 >= 100 -> pause
        _snap(session=0, s_reset=reset + timedelta(hours=5)), # after reset -> go
    ])
    gate = UsageGate("gpt-5.5", CODEX_DEFAULTS, provider="codex", buffer_min=2,
                     probe=lambda: next(snaps), sleep=clock.sleep, clock=clock)
    gate.wait_for_headroom()
    gate.wait_for_headroom()
    assert clock.slept == 0
    gate.wait_for_headroom()
    assert clock.now == reset + timedelta(minutes=2)


def test_gate_turn_estimate_capped_at_half_ceiling():
    gate = UsageGate("m", GuardConfig(session_ceiling=80, turn_estimate=70),
                     probe=lambda: None)
    assert gate.turn_estimates()[0] == 40


def test_gate_codex_abort_names_provider():
    clock = _Clock(NOW)
    gate = UsageGate("gpt-5.5", CODEX_DEFAULTS, provider="codex",
                     probe=lambda: _snap(session=100), sleep=clock.sleep, clock=clock)
    with pytest.raises(ProviderLimitError) as exc:
        gate.wait_for_headroom()
    assert exc.value.hit.provider == "codex"


def test_schedule_holds_codex_at_full_window_and_runs_claude(tmp_path, monkeypatch):
    clock = {"now": datetime(2026, 10, 22, 17, 0, tzinfo=timezone.utc)}

    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    reset = clock["now"] + timedelta(hours=1)
    codex_probes = iter([_snap(session=100, s_reset=reset),
                         _snap(session=0, s_reset=reset + timedelta(hours=5)),
                         _snap(session=30, s_reset=reset + timedelta(hours=5))])
    monkeypatch.setattr(run_pipeline, "datetime", _FakeDT)
    monkeypatch.setattr(run_pipeline.agent_usage, "probe_usage",
                        lambda provider, **kw: next(codex_probes) if provider == "codex"
                        else _snap(session=1))
    monkeypatch.setattr(run_pipeline, "_sleep_until",
                        lambda target, *, poll_s: clock.__setitem__("now", target))
    calls: list[str] = []
    monkeypatch.setattr(run_pipeline, "run_step",
                        lambda step, *, dry_run: (calls.append(step.model), ("done", "exit=0"))[1])

    codex = run_pipeline.Step("x::run_exp::gpt-5.5", _make_task(tmp_path, "gpt-5.5"),
                              "run_exp", "gpt-5.5")
    claude = run_pipeline.Step("c::run_exp::claude-sonnet-4-6",
                               _make_task(tmp_path, "claude-sonnet-4-6"), "run_exp",
                               "claude-sonnet-4-6")
    args = argparse.Namespace(retry_failed=False, force=False, dry_run=False, no_dep_check=False)
    counts = {"done": 0, "failed": 0, "skipped": 0, "blocked": 0}
    cfg = run_pipeline.PauseConfig(buffer_min=2, guards={"codex": CODEX_DEFAULTS,
                                                         "claude": GuardConfig()})

    run_pipeline.schedule_run_exp([codex, claude], run_pipeline.State(tmp_path / "s.json"),
                                  args, counts, cfg)

    assert calls == ["claude-sonnet-4-6", "gpt-5.5"]
    assert counts["done"] == 2


def test_unstarted_codex_window_reset_drift_still_measured():
    """At 0% Codex reports resetsAt = now + 5h, which drifts between probes."""
    est = RunEstimator(40)
    before = _snap(session=0, s_reset=NOW + timedelta(hours=5))
    after = _snap(session=22, s_reset=NOW + timedelta(hours=5, minutes=1))
    assert est.observe("codex::gpt-5.5", before, after) == 22
    rolled = _snap(session=3, s_reset=NOW + timedelta(hours=10))
    assert est.observe("codex::gpt-5.5", after, rolled) is None
