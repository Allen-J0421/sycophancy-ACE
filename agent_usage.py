"""Coding-agent subscription usage probes + headroom guard policy (stdlib only).

Why this exists: provider limits are otherwise only *detected* after they hit
(``limit_detect``), and the run in flight is discarded and re-run fresh (~13% of Claude usage
in the G-series; Codex spend-cap hits corrupted 15 R-series runs). The guard reads live usage
*before* starting a run (``run_pipeline``) and before every turn
(``experiment_runner.usage_gate``) so a run pauses at a turn boundary instead of dying mid-turn.

Probes (neither makes a model call):
  - Claude: ``claude -p /usage --output-format json --no-session-persistence`` (~1.5 s). Plain
    text in Claude Code 2.1.x, parsed line by line.
  - Codex:  ``codex app-server`` JSON-RPC ``account/rateLimits/read`` (~5-7 s): a 5-hour
    ``primary`` and weekly ``secondary`` window, plus whether the plan has credits.

Every probe/parse failure degrades to ``None`` and callers fall back to reactive detection.

Settings: env vars, falling back to ``config/prompt.env``. Claude keys are ``LIMIT_GUARD_*``;
Codex keys are ``LIMIT_GUARD_CODEX_*`` with the same suffixes (see ``load_guard_config``).
Ceilings are percentages (0-100); a turn/run is held when ``used% + expected% >= ceiling``.
Claude defaults to 80/80 (headroom for interactive use); Codex to 100/100 (use the whole
window, but never start a turn that would not fit).

CLI: ``python agent_usage.py [claude|codex] [--json]`` prints the parsed windows.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CLAUDE_PROBE_CMD = (
    "claude", "-p", "/usage", "--output-format", "json", "--no-session-persistence",
)
CODEX_PROBE_CMD = ("codex", "app-server")

# "Current session: 4% used · resets Oct 22 at 2pm (America/Los_Angeles)"
# "Current week (all models): 7% used · resets Oct 28 at 8am (America/Los_Angeles)"
_LINE_RE = re.compile(
    r"^\s*Current (session|week(?:\s*\(([^)]+)\))?)\s*:\s*(\d+(?:\.\d+)?)%\s*used"
    r"(?:.*?\bresets\s+(.+?))?\s*$",
    re.I | re.M,
)
# "Oct 22 at 2pm (tz)", "Oct 22, 2026 at 2:30pm", "2pm (tz)", "9:50am".
_RESET_RE = re.compile(
    r"^(?:([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,?\s+(\d{4}))?\s+at\s+)?"
    r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)\b(?:\s*\(([^)]+)\))?",
    re.I,
)
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}

SESSION = "session"
WEEK = "week"
ALL_MODELS = "all models"
PROVIDERS = ("claude", "codex")


@dataclass(frozen=True)
class UsageWindow:
    """One limit window: ``kind`` is "session" (5-hour) or "week"; ``label`` is the weekly
    scope ("all models", "Opus", ...) and empty for the session window."""

    kind: str
    label: str
    percent: float
    resets_at: datetime | None

    @property
    def name(self) -> str:
        return SESSION if self.kind == SESSION else f"week ({self.label})"


@dataclass(frozen=True)
class UsageSnapshot:
    session: UsageWindow | None
    weekly: tuple[UsageWindow, ...]
    raw: str = ""
    has_credits: bool = False           # Codex: usage past a full window spills onto credits
    limit_reached: str | None = None    # Codex: provider says a limit is already reached

    def weekly_for(self, model: str | None) -> list[UsageWindow]:
        """Weekly windows that constrain ``model``: "all models" plus any per-model window
        whose label (e.g. "Opus") appears in the model id (e.g. "claude-opus-4-8")."""
        m = (model or "").lower()
        return [
            w for w in self.weekly
            if w.label.lower() == ALL_MODELS or (m and w.label.lower() in m)
        ]

    def windows_for(self, model: str | None) -> list[UsageWindow]:
        return ([self.session] if self.session else []) + self.weekly_for(model)

    def all_windows(self) -> list[UsageWindow]:
        return ([self.session] if self.session else []) + list(self.weekly)


@dataclass(frozen=True)
class GuardConfig:
    enabled: bool = True
    session_ceiling: float = 80.0
    weekly_ceiling: float = 80.0
    run_estimate: float = 40.0      # session % one full run is assumed to use (until measured)
    turn_estimate: float = 5.0      # session % one turn is assumed to use (until measured)
    max_pause_min: int = 480
    probe_timeout_s: int = 60
    use_credits: bool = False       # Codex: keep running on credits once a window is full


CLAUDE_DEFAULTS = GuardConfig()
CODEX_DEFAULTS = GuardConfig(session_ceiling=100.0, weekly_ceiling=100.0)
_ENV_PREFIX = {"claude": "LIMIT_GUARD_", "codex": "LIMIT_GUARD_CODEX_"}
_DEFAULTS = {"claude": CLAUDE_DEFAULTS, "codex": CODEX_DEFAULTS}


@dataclass(frozen=True)
class StartDecision:
    """Whether a run may start now; when not, ``until`` is when to re-check."""

    ok: bool
    until: datetime | None = None
    reason: str = ""


# ---------------------------------------------------------------------------
# Claude: parse `/usage` text
# ---------------------------------------------------------------------------

def _now_aware(now: datetime | None) -> datetime:
    if now is not None:
        return now if now.tzinfo is not None else now.astimezone()
    return datetime.now().astimezone()


def parse_reset(text: str, *, now: datetime | None = None) -> datetime | None:
    """Parse a ``/usage`` reset clause into a tz-aware datetime (None when unrecognised).

    With a month/day the year is inferred (rolled forward if that date is > 1 day past);
    without one the time resolves to its next occurrence. Unknown/absent tz -> local.
    """
    match = _RESET_RE.match(text.strip())
    if not match:
        return None
    mon, day, year, hour, minute, ampm, tz_name = match.groups()
    hour, minute = int(hour), int(minute or 0)
    if not (1 <= hour <= 12) or minute > 59:
        return None
    hour = (0 if hour == 12 else hour) if ampm.lower() == "am" else (12 if hour == 12 else hour + 12)

    tz = None
    if tz_name:
        try:
            tz = ZoneInfo(tz_name.strip())
        except (ZoneInfoNotFoundError, ValueError):
            tz = None
    base = _now_aware(now)
    if tz is not None:
        base = base.astimezone(tz)

    if mon:
        month = _MONTHS.get(mon[:3].lower())
        if month is None:
            return None
        try:
            candidate = base.replace(year=int(year) if year else base.year, month=month,
                                     day=int(day), hour=hour, minute=minute,
                                     second=0, microsecond=0)
        except ValueError:
            return None
        if not year and candidate < base - timedelta(days=1):
            candidate = candidate.replace(year=candidate.year + 1)
        return candidate

    candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= base:
        candidate += timedelta(days=1)
    return candidate


def parse_usage_text(text: str, *, now: datetime | None = None) -> UsageSnapshot | None:
    """Parse Claude ``/usage`` text into a snapshot; None if no session/weekly line is found."""
    session: UsageWindow | None = None
    weekly: list[UsageWindow] = []
    for match in _LINE_RE.finditer(text or ""):
        head, label, pct, reset = match.groups()
        resets_at = parse_reset(reset, now=now) if reset else None
        if head.lower() == SESSION:
            session = UsageWindow(SESSION, "", float(pct), resets_at)
        else:
            weekly.append(UsageWindow(WEEK, (label or ALL_MODELS).strip(), float(pct), resets_at))
    if session is None and not weekly:
        return None
    return UsageSnapshot(session=session, weekly=tuple(weekly), raw=text)


def probe_claude_usage(
    *,
    timeout_s: int = 60,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    now: datetime | None = None,
) -> UsageSnapshot | None:
    """Run the Claude ``/usage`` probe; None on any failure (CLI missing, timeout, API-key
    auth with no plan windows, unparseable text)."""
    try:
        proc = run(list(CLAUDE_PROBE_CMD), capture_output=True, text=True,
                   timeout=timeout_s, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout or "")
    except json.JSONDecodeError:
        return None
    text = payload.get("result") if isinstance(payload, dict) else None
    return parse_usage_text(text, now=now) if isinstance(text, str) else None


# ---------------------------------------------------------------------------
# Codex: app-server `account/rateLimits/read`
# ---------------------------------------------------------------------------

def _codex_window(kind: str, raw: object) -> UsageWindow | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("usedPercent"), (int, float)):
        return None
    reset = raw.get("resetsAt")
    resets_at = (datetime.fromtimestamp(reset).astimezone()
                 if isinstance(reset, (int, float)) and reset > 0 else None)
    return UsageWindow(kind, "" if kind == SESSION else ALL_MODELS,
                       float(raw["usedPercent"]), resets_at)


def parse_codex_rate_limits(result: object) -> UsageSnapshot | None:
    """Map an ``account/rateLimits/read`` result to a snapshot: ``primary`` (5-hour) ->
    session, ``secondary`` (weekly) -> week (all models)."""
    rl = result.get("rateLimits") if isinstance(result, dict) else None
    if not isinstance(rl, dict):
        return None
    session = _codex_window(SESSION, rl.get("primary"))
    week = _codex_window(WEEK, rl.get("secondary"))
    if session is None and week is None:
        return None
    credits = rl.get("credits") if isinstance(rl.get("credits"), dict) else {}
    return UsageSnapshot(
        session=session,
        weekly=(week,) if week else (),
        raw=json.dumps(rl),
        has_credits=bool(credits.get("hasCredits") or credits.get("unlimited")),
        limit_reached=rl.get("rateLimitReachedType") or None,
    )


def codex_rate_limits_rpc(*, timeout_s: int = 60) -> dict | None:
    """Ask a short-lived ``codex app-server`` for the account's rate limits (JSON-RPC over
    stdio). Returns the ``result`` object, or None on any error/timeout."""
    try:
        proc = subprocess.Popen(list(CODEX_PROBE_CMD), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, bufsize=1)
    except OSError:
        return None
    deadline = time.monotonic() + timeout_s

    def send(obj: dict) -> None:
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def response(msg_id: int) -> dict | None:
        while (left := deadline - time.monotonic()) > 0:
            ready, _, _ = select.select([proc.stdout], [], [], min(left, 1.0))
            if not ready:
                continue
            line = proc.stdout.readline()
            if not line:
                return None
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("id") == msg_id:
                return msg
        return None

    try:
        send({"method": "initialize", "id": 0,
              "params": {"clientInfo": {"name": "usage-guard", "version": "1"}}})
        if response(0) is None:
            return None
        send({"method": "initialized"})
        send({"method": "account/rateLimits/read", "id": 1})
        msg = response(1)
        return msg.get("result") if msg and isinstance(msg.get("result"), dict) else None
    except (OSError, ValueError):
        return None
    finally:
        proc.kill()
        proc.wait()


def probe_codex_usage(
    *,
    timeout_s: int = 60,
    rpc: Callable[..., dict | None] = codex_rate_limits_rpc,
) -> UsageSnapshot | None:
    return parse_codex_rate_limits(rpc(timeout_s=timeout_s))


def probe_usage(provider: str, *, timeout_s: int = 60) -> UsageSnapshot | None:
    if provider == "claude":
        return probe_claude_usage(timeout_s=timeout_s)
    if provider == "codex":
        return probe_codex_usage(timeout_s=timeout_s)
    return None


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def blocking_window(
    snapshot: UsageSnapshot,
    model: str | None,
    cfg: GuardConfig,
    *,
    session_extra: float = 0.0,
    weekly_extra: float = 0.0,
) -> UsageWindow | None:
    """The window that is (or, with the expected extra usage, would be) at/over its ceiling;
    weekly first since it blocks longest. None when the turn/run fits.

    With ``use_credits`` on a plan that has credits, full windows don't stop the provider, so
    nothing blocks (the unobservable spend cap is left to reactive detection)."""
    if cfg.use_credits and snapshot.has_credits:
        return None
    if snapshot.limit_reached:
        windows = snapshot.windows_for(model)
        if windows:
            return max(windows, key=lambda w: w.percent)
    for w in snapshot.weekly_for(model):
        if w.percent + weekly_extra >= cfg.weekly_ceiling:
            return w
    s = snapshot.session
    if s is not None and s.percent + session_extra >= cfg.session_ceiling:
        return s
    return None


def start_decision(
    snapshot: UsageSnapshot | None,
    model: str | None,
    cfg: GuardConfig,
    *,
    estimate: float,
    other_work: bool,
    fallback_until: datetime,
) -> StartDecision:
    """Decide whether a run may start (orchestrator side).

    - Over a ceiling now -> wait for that window's reset.
    - Under the ceiling but the run is expected to cross it -> defer *only* if other-provider
      work can fill the gap; otherwise start anyway and let the in-run gate pause between
      turns (that uses the window's remaining headroom instead of idling it).
    """
    if snapshot is None or not cfg.enabled:
        return StartDecision(True)
    w = blocking_window(snapshot, model, cfg)
    if w is not None:
        return StartDecision(False, w.resets_at or fallback_until,
                             f"{w.name} {w.percent:g}% >= ceiling")
    if other_work:
        w = blocking_window(snapshot, model, cfg, session_extra=estimate)
        if w is not None:
            return StartDecision(False, w.resets_at or fallback_until,
                                 f"{w.name} {w.percent:g}% + ~{estimate:g}% run would cross ceiling")
    return StartDecision(True)


def same_window(a: UsageWindow, b: UsageWindow, *, slack_min: int = 15) -> bool:
    """True if two readings belong to the same window instance. Slack absorbs an unstarted
    window whose reset floats at now+duration (Codex at 0%); a real reset moves it by hours."""
    if a.resets_at is None or b.resets_at is None:
        return a.resets_at is b.resets_at
    return abs((a.resets_at - b.resets_at).total_seconds()) <= slack_min * 60


def session_delta(before: UsageSnapshot | None, after: UsageSnapshot | None) -> float | None:
    """Session % used between two probes; None if either is missing or a reset intervened."""
    if not (before and after and before.session and after.session):
        return None
    if not same_window(before.session, after.session):
        return None
    delta = after.session.percent - before.session.percent
    return delta if delta > 0 else None


def window_deltas(before: UsageSnapshot | None, after: UsageSnapshot | None) -> dict[str, float]:
    """Per-window % used between two probes (same reset only), keyed by window name."""
    if not (before and after):
        return {}
    prev = {w.name: w for w in before.all_windows()}
    out: dict[str, float] = {}
    for w in after.all_windows():
        p = prev.get(w.name)
        if p is not None and same_window(p, w) and w.percent > p.percent:
            out[w.name] = w.percent - p.percent
    return out


class RunEstimator:
    """Session % a run uses, learned per (provider, model) from before/after probes.

    Uses the max of the last few observations (conservative); before any observation,
    ``default``. Observations spanning a session reset are dropped.
    """

    def __init__(self, default: float | Callable[[str], float], *, keep: int = 3) -> None:
        self.default = default if callable(default) else (lambda _key: default)
        self.keep = keep
        self._obs: dict[str, list[float]] = {}

    def estimate(self, key: str) -> float:
        obs = self._obs.get(key)
        return max(obs) if obs else self.default(key)

    def observe(self, key: str, before: UsageSnapshot | None, after: UsageSnapshot | None) -> float | None:
        delta = session_delta(before, after)
        if delta is None:
            return None
        obs = self._obs.setdefault(key, [])
        obs.append(delta)
        del obs[:-self.keep]
        return delta


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_guard_config(get: Callable[[str], str | None], provider: str = "claude") -> GuardConfig:
    """Build a provider's GuardConfig from a key lookup (callers pass env-var-then-prompt.env).

    Claude reads ``LIMIT_GUARD_<KEY>``; Codex reads ``LIMIT_GUARD_CODEX_<KEY>``. Keys:
    ENABLED, SESSION_CEILING, WEEKLY_CEILING, RUN_ESTIMATE, TURN_ESTIMATE,
    MAX_PAUSE_MINUTES, PROBE_TIMEOUT_SECONDS, and (Codex) USE_CREDITS.
    """
    d = _DEFAULTS[provider]
    prefix = _ENV_PREFIX[provider]

    def _float(key: str, default: float) -> float:
        raw = get(prefix + key)
        try:
            return float(raw) if raw not in (None, "") else default
        except ValueError:
            return default

    def _bool(key: str, default: bool) -> bool:
        raw = (get(prefix + key) or "").strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        return default

    return replace(
        d,
        enabled=_bool("ENABLED", d.enabled),
        session_ceiling=_float("SESSION_CEILING", d.session_ceiling),
        weekly_ceiling=_float("WEEKLY_CEILING", d.weekly_ceiling),
        run_estimate=_float("RUN_ESTIMATE", d.run_estimate),
        turn_estimate=_float("TURN_ESTIMATE", d.turn_estimate),
        max_pause_min=int(_float("MAX_PAUSE_MINUTES", d.max_pause_min)),
        probe_timeout_s=int(_float("PROBE_TIMEOUT_SECONDS", d.probe_timeout_s)),
        use_credits=_bool("USE_CREDITS", d.use_credits) if provider == "codex" else False,
    )


def describe(snapshot: UsageSnapshot | None) -> str:
    """One-line summary for logs, e.g. ``session 42% (resets 14:00) · week (all models) 7%``."""
    if snapshot is None:
        return "usage unavailable"
    parts = []
    for w in snapshot.all_windows():
        reset = f" (resets {w.resets_at:%m-%d %H:%M %Z})" if w.resets_at else ""
        parts.append(f"{w.name} {w.percent:g}%{reset}")
    if snapshot.has_credits:
        parts.append("credits available")
    if snapshot.limit_reached:
        parts.append(f"limit reached: {snapshot.limit_reached}")
    return " · ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print coding-agent subscription usage.")
    parser.add_argument("provider", nargs="?", choices=PROVIDERS, default="claude")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)
    snap = probe_usage(args.provider, timeout_s=int(os.environ.get("LIMIT_GUARD_PROBE_TIMEOUT_SECONDS", "60")))
    if snap is None:
        print(f"{args.provider} usage unavailable (CLI missing, not logged in to a plan, "
              "or output format changed)", file=sys.stderr)
        return 1
    if args.json:
        def _w(w: UsageWindow) -> dict:
            d = asdict(w)
            d["resets_at"] = w.resets_at.isoformat() if w.resets_at else None
            return d
        print(json.dumps({
            "session": _w(snap.session) if snap.session else None,
            "weekly": [_w(w) for w in snap.weekly],
            "has_credits": snap.has_credits,
            "limit_reached": snap.limit_reached,
        }, indent=2))
    else:
        print(describe(snap))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
