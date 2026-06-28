"""Domain models for signal computation results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TurnData:
    run: int
    lc: int
    refdiff_ok: bool
    n_plus: int
    n_minus: int
    n_touched: int
    n_minus_new: int  # |{k in N-_t : k has no N0 lineage}|
    c_size: int
    rho: float
    f1: float
    rolling: dict[str, dict[str, float]] = field(default_factory=dict)
    sets: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class SignalResult:
    experiment: str
    stamp: str
    model: str
    repo_path: str
    language: str
    num_turns: int
    t0: int
    l0: int
    l0_ok: bool
    skipped_turns: int
    s1: float
    s1_bin: int
    s2: float
    s2_bin: int
    s3: float
    s3_bin: int
    s4_cont: int
    s4_bin: int
    s5_cont: int
    s5_bin: int
    s6_cont: float
    s6_bin: int
    s7_cont: float
    turns: list[TurnData] = field(default_factory=list)


@dataclass(frozen=True)
class Thresholds:
    eps1: float
    eps3: float
    eps6: float
