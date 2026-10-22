"""Per-turn usage gate (runner side of the usage guard), for Claude and Codex.

Before each turn, probe the provider's live usage; if the next turn would not fit under a
window's ceiling (``used% + expected turn% >= ceiling``), sleep until that window resets and
continue the *same* run (turns resume one agent session, so a pause between turns loses
nothing but a warm prompt cache). The expected turn % is learned from consecutive pre-turn
probes. Only when the wait would exceed LIMIT_GUARD[_CODEX]_MAX_PAUSE_MINUTES (typically a
weekly reset) does it raise ``ProviderLimitError``, falling back to the existing abort ->
marker -> pipeline re-run path. Probe failures never block: reactive detection still applies.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from agent_usage import (  # noqa: E402
    PROVIDERS,
    SESSION,
    GuardConfig,
    UsageSnapshot,
    blocking_window,
    describe,
    load_guard_config,
    probe_usage,
    window_deltas,
)

from experiment_runner.env import load_prompt_env_entries  # noqa: E402
from experiment_runner.limit_detect import (  # noqa: E402
    SESSION_LIMIT,
    WEEKLY_LIMIT,
    LimitHit,
    ProviderLimitError,
)
from experiment_runner.util import eprint, non_empty_string  # noqa: E402


def load_usage_guard_settings(provider: str = "claude") -> tuple[GuardConfig, int]:
    """(guard config, reset buffer minutes); env vars override config/prompt.env."""
    entries, _ = load_prompt_env_entries()

    def get(key: str) -> str | None:
        return non_empty_string(os.environ.get(key)) or entries.get(key)

    try:
        buffer_min = int(get("LIMIT_BUFFER_MINUTES") or 2)
    except ValueError:
        buffer_min = 2
    return load_guard_config(get, provider), buffer_min


class UsageGate:
    """Blocks before a turn until the next turn fits under every usage ceiling."""

    def __init__(
        self,
        model: str,
        cfg: GuardConfig,
        *,
        provider: str = "claude",
        buffer_min: int = 2,
        poll_s: int = 60,
        keep: int = 5,
        probe: Callable[[], UsageSnapshot | None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.model = model
        self.cfg = cfg
        self.provider = provider
        self.buffer = timedelta(minutes=buffer_min)
        self.poll_s = poll_s
        self.keep = keep
        self.probe = probe or (lambda: probe_usage(provider, timeout_s=cfg.probe_timeout_s))
        self.sleep = sleep
        self.clock = clock or (lambda: datetime.now().astimezone())
        self._last: UsageSnapshot | None = None
        self._turn_obs: dict[str, list[float]] = {}

    def turn_estimates(self) -> tuple[float, float]:
        """(session %, weekly %) one turn is expected to use: max of recent observations,
        else LIMIT_GUARD_TURN_ESTIMATE (session) and a tenth of it (weekly). Capped at half
        the ceiling so a large estimate can never block a freshly reset window forever."""
        session_obs = self._turn_obs.get(SESSION)
        weekly_obs = [v for k, obs in self._turn_obs.items() if k != SESSION for v in obs]
        session = max(session_obs) if session_obs else self.cfg.turn_estimate
        weekly = max(weekly_obs) if weekly_obs else self.cfg.turn_estimate / 10
        return (min(session, self.cfg.session_ceiling / 2),
                min(weekly, self.cfg.weekly_ceiling / 2))

    def _learn(self, snap: UsageSnapshot) -> None:
        for name, delta in window_deltas(self._last, snap).items():
            obs = self._turn_obs.setdefault(name, [])
            obs.append(delta)
            del obs[:-self.keep]
        self._last = snap

    def wait_for_headroom(self) -> None:
        max_pause = timedelta(minutes=self.cfg.max_pause_min)
        started = self.clock()
        while True:
            snap = self.probe()
            if snap is None:
                return
            self._learn(snap)
            session_extra, weekly_extra = self.turn_estimates()
            w = blocking_window(snap, self.model, self.cfg,
                                session_extra=session_extra, weekly_extra=weekly_extra)
            if w is None:
                return
            now = self.clock()
            is_session = w.kind == SESSION
            kind = SESSION_LIMIT if is_session else WEEKLY_LIMIT
            extra = session_extra if is_session else weekly_extra
            ceiling = self.cfg.session_ceiling if is_session else self.cfg.weekly_ceiling
            raw = (f"usage guard: {w.name} {w.percent:g}% + ~{extra:g}% turn would reach "
                   f"{ceiling:g}% ceiling ({describe(snap)})")
            until = (w.resets_at + self.buffer) if w.resets_at else None
            if until is None or until - started > max_pause:
                raise ProviderLimitError(LimitHit(provider=self.provider, reset_dt=w.resets_at,
                                                  raw=raw, kind=kind))
            # A reset already in the past means usage hasn't rolled over yet: re-check soon.
            until = max(until, now + timedelta(seconds=self.poll_s))
            eprint(f"[usage-guard] {self.provider} {w.name} at {w.percent:g}% (next turn "
                   f"~{extra:g}% would reach the {ceiling:g}% ceiling); "
                   f"pausing until {until.isoformat()}")
            while (remaining := (until - self.clock()).total_seconds()) > 0:
                self.sleep(min(self.poll_s, remaining))


def build_usage_gate(agent: str, model: str) -> UsageGate | None:
    """Gate for Claude/Codex runs when that provider's guard is enabled; None otherwise."""
    if agent not in PROVIDERS:
        return None
    cfg, buffer_min = load_usage_guard_settings(agent)
    if not cfg.enabled:
        return None
    return UsageGate(model, cfg, provider=agent, buffer_min=buffer_min)
