"""Line-level signals S1-S3 from git churn."""

from __future__ import annotations

from dataclasses import dataclass


def lc_of(record: dict) -> int:
    stat = record.get("git_stat") or {}
    return int(stat.get("lines_added", 0)) + int(stat.get("lines_deleted", 0))


def compute_s0(runs: list[int], lc_by_run: dict[int, int]) -> tuple[int, bool]:
    """First structural stop turn (LC==0), capped at num_turns with censoring flag."""
    num_turns = runs[-1]
    t_stop = next((t for t in runs if lc_by_run[t] == 0), num_turns + 1)
    if t_stop <= num_turns:
        return t_stop, False
    return num_turns, True


def compute_s0_prefix(
    prefix_runs: list[int],
    lc_by_run: dict[int, int],
    end_turn: int,
    num_turns: int,
) -> tuple[int, bool]:
    """Rolling S0 through end_turn: first stop in prefix, else censored at end_turn/horizon."""
    t_stop = next((t for t in prefix_runs if lc_by_run[t] == 0), None)
    if t_stop is not None:
        return t_stop, False
    if end_turn >= num_turns:
        return num_turns, True
    return end_turn, True


@dataclass(frozen=True)
class LineSignalValues:
    s1: float
    s2: float
    s3: float
    t0: int


class LineSignalCalculator:
    """Computes normalized line-churn signals (SRP: S1/S2/S3 only)."""

    def __init__(self, l0_denom: float) -> None:
        self._l0_denom = l0_denom

    def compute(self, runs: list[int], lc_by_run: dict[int, int]) -> LineSignalValues:
        num_turns = runs[-1]
        t0 = next((t for t in runs if lc_by_run[t] == 0), num_turns + 1)

        s1 = sum(lc_by_run[t] for t in runs if t < t0) / self._l0_denom
        s2 = sum(lc_by_run[t] for t in runs if t > t0) / self._l0_denom
        volatility = 0.0
        for i in range(1, len(runs)):
            volatility += abs(lc_by_run[runs[i]] - lc_by_run[runs[i - 1]])
        s3 = volatility / self._l0_denom
        return LineSignalValues(s1=s1, s2=s2, s3=s3, t0=t0)

    def compute_prefix(
        self, prefix_runs: list[int], lc_by_run: dict[int, int], end_turn: int
    ) -> tuple[float, float, float]:
        pt0 = next((r for r in prefix_runs if lc_by_run[r] == 0), end_turn + 1)
        s1 = sum(lc_by_run[r] for r in prefix_runs if r < pt0) / self._l0_denom
        s2 = sum(lc_by_run[r] for r in prefix_runs if r > pt0) / self._l0_denom
        volatility = 0.0
        for i in range(1, len(prefix_runs)):
            volatility += abs(lc_by_run[prefix_runs[i]] - lc_by_run[prefix_runs[i - 1]])
        s3 = volatility / self._l0_denom
        return s1, s2, s3
