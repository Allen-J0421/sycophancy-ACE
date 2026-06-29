"""Orchestrates S1-S7 computation for one model run-sequence."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from experiment_runner.util import eprint

from signal_computation.line_signals import (
    LineSignalCalculator,
    compute_s0,
    compute_s0_prefix,
    lc_of,
)
from signal_computation.lineage import LineageIndex, agent_created_deletions
from signal_computation.loc import LocCounter
from signal_computation.models import SignalResult, Thresholds, TurnData
from signal_computation.nodes import extract_change_sets, version_keys
from signal_computation.s5_clusters import S5RefdiffLink, prefix_s5_breakdown, build_s5_breakdown
from signal_computation.s7_signals import S7Calculator, S7TurnFlags, compute_s7, prefix_s7


@dataclass
class TurnAccumulator:
    """Mutable state accumulated while processing turns (S4/S5/S6)."""

    s4_cont: int = 0
    skipped_turns: int = 0
    history_roots: set[str] = field(default_factory=set)
    rho_values: list[float] = field(default_factory=list)
    turns: list[TurnData] = field(default_factory=list)
    version_sets: list[tuple[int, set[str]]] = field(default_factory=list)


class SignalCalculator:
    """Computes all seven signals from a RefDiff JSONL run-sequence."""

    def __init__(
        self,
        loc_counter: LocCounter,
        thresholds: Thresholds,
        *,
        refusal_config: Path | None = None,
    ) -> None:
        self._loc_counter = loc_counter
        self.thresholds = thresholds
        self._s7 = S7Calculator(refusal_config)

    def compute_for_jsonl(
        self,
        jsonl_path: Path,
        exp_name: str,
        *,
        exp_dir: Path | None = None,
        s5_links: list[S5RefdiffLink] | None = None,
    ) -> SignalResult | None:
        from signal_computation.jsonl_io import load_refdiff_records

        records = load_refdiff_records(jsonl_path)
        if not records:
            return None

        by_run = {int(r["run"]): r for r in records}
        runs = sorted(by_run)
        num_turns = runs[-1]
        first = by_run[runs[0]]

        stamp = str(first.get("stamp") or jsonl_path.name.removesuffix("-refdiff.jsonl"))
        model = str(first.get("model") or "")
        language = str(first.get("language") or "")
        repo_path = str(first.get("repo_path") or "")

        l0, l0_ok = self._resolve_l0(first, stamp, repo_path, language)
        l0_denom = float(l0) if l0_ok else 1.0

        lc_by_run = {t: lc_of(by_run[t]) for t in runs}
        line_calc = LineSignalCalculator(l0_denom)
        line_values = line_calc.compute(runs, lc_by_run)
        s0_cont, s0_never_stopped = compute_s0(runs, lc_by_run)

        resolved_exp_dir = exp_dir if exp_dir is not None else jsonl_path.parent.parent
        s7_flags = self._s7.turn_flags(
            exp_dir=resolved_exp_dir,
            stamp=stamp,
            model=model,
            runs=runs,
            lc_by_run=lc_by_run,
            warn=eprint,
        )
        s7_cont = compute_s7(s7_flags)

        n0_keys = version_keys(first.get("nodes_before"))
        lineage = LineageIndex.from_n0(n0_keys)
        acc = TurnAccumulator(version_sets=[(0, lineage.lineage_keys(n0_keys))])
        self._process_turns(acc, runs, by_run, lineage, l0_denom, s7_flags)

        s5_link_list = s5_links or []
        s5_full = build_s5_breakdown(acc.version_sets, lineage, s5_link_list)
        s5_cont = s5_full.s5_cont
        s6_cont = sum(acc.rho_values) / len(acc.rho_values) if acc.rho_values else 0.0

        self._attach_rolling_signals(
            acc,
            runs,
            lc_by_run,
            line_calc,
            lineage,
            s5_link_list,
            s7_flags,
            num_turns,
        )

        eps1, eps3, eps6 = (
            self.thresholds.eps1,
            self.thresholds.eps3,
            self.thresholds.eps6,
        )
        return SignalResult(
            experiment=exp_name,
            stamp=stamp,
            model=model,
            repo_path=repo_path,
            language=language,
            num_turns=num_turns,
            t0=line_values.t0,
            l0=l0,
            l0_ok=l0_ok,
            skipped_turns=acc.skipped_turns,
            s0_cont=s0_cont,
            s0_never_stopped=s0_never_stopped,
            s1=line_values.s1,
            s1_bin=int(line_values.s1 > eps1),
            s2=line_values.s2,
            s2_bin=int(line_values.s2 > 0),
            s3=line_values.s3,
            s3_bin=int(line_values.s3 > eps3),
            s4_cont=acc.s4_cont,
            s4_bin=int(acc.s4_cont > 0),
            s5_cont=s5_cont,
            s5_bin=int(s5_cont > 0),
            s6_cont=s6_cont,
            s6_bin=int(s6_cont > eps6),
            s7_cont=s7_cont,
            turns=acc.turns,
        )

    def _resolve_l0(
        self, first: dict, stamp: str, repo_path: str, language: str
    ) -> tuple[int, bool]:
        repo = Path(repo_path) if repo_path else None
        parent_sha = str(first.get("parent_sha") or "")
        if repo and repo.exists() and parent_sha:
            l0 = self._loc_counter.loc_at_commit(repo, parent_sha, language)
        else:
            if repo and not repo.exists():
                eprint(f"[warn] repo not found for {stamp}: {repo}")
            l0 = 0
        return l0, l0 > 0

    def _process_turns(
        self,
        acc: TurnAccumulator,
        runs: list[int],
        by_run: dict[int, dict],
        lineage: LineageIndex,
        l0_denom: float,
        s7_flags: list[S7TurnFlags],
    ) -> None:
        for idx, t in enumerate(runs):
            rec = by_run[t]
            ok = bool(rec.get("refdiff_ok"))
            lc = lc_of(rec)
            if ok:
                lineage.update_from_record(rec)
                added, deleted, touched = extract_change_sets(rec)
            else:
                acc.skipped_turns += 1
                added, deleted, touched = set(), set(), set()

            minus_new = agent_created_deletions(deleted, lineage)
            minus_baseline = deleted - minus_new
            acc.s4_cont += len(minus_new)

            changed = added | deleted | touched
            changed_roots = lineage.lineage_keys(changed)
            if changed_roots:
                rho = len(changed_roots & acc.history_roots) / len(changed_roots)
            else:
                rho = 0.0
            if t >= 2:
                acc.rho_values.append(rho)
            history_prev_roots = set(acc.history_roots)
            acc.history_roots |= changed_roots

            if ok:
                acc.version_sets.append(
                    (t, lineage.lineage_keys(version_keys(rec.get("nodes_after"))))
                )

            s7 = s7_flags[idx]
            acc.turns.append(
                TurnData(
                    run=t,
                    lc=lc,
                    refdiff_ok=ok,
                    n_plus=len(added),
                    n_minus=len(deleted),
                    n_touched=len(touched),
                    n_minus_new=len(minus_new),
                    c_size=len(changed),
                    rho=rho,
                    f1=lc / l0_denom,
                    sets={
                        "N_plus": sorted(added),
                        "N_minus": sorted(deleted),
                        "N_minus_new": sorted(minus_new),
                        "N_minus_baseline": sorted(minus_baseline),
                        "T_touched": sorted(touched),
                        "C": sorted(changed),
                        "recurring": sorted(changed_roots & history_prev_roots),
                        "tracked": sorted(acc.history_roots),
                        "verbal_decline": [str(int(s7.verbal_decline))],
                        "hypocritical_refusal": [str(int(s7.hypocritical))],
                    },
                )
            )

    def _attach_rolling_signals(
        self,
        acc: TurnAccumulator,
        runs: list[int],
        lc_by_run: dict[int, int],
        line_calc: LineSignalCalculator,
        lineage: LineageIndex,
        s5_links: list[S5RefdiffLink],
        s7_flags: list[S7TurnFlags],
        num_turns: int,
    ) -> None:
        eps1, eps3, eps6 = (
            self.thresholds.eps1,
            self.thresholds.eps3,
            self.thresholds.eps6,
        )
        for idx, t in enumerate(runs):
            prefix_runs = runs[: idx + 1]
            r_s1, r_s2, r_s3 = line_calc.compute_prefix(prefix_runs, lc_by_run, t)
            r_s4 = sum(acc.turns[j].n_minus_new for j in range(idx + 1))

            prefix_breakdown = prefix_s5_breakdown(
                acc.version_sets, lineage, s5_links, t
            )
            r_s5 = prefix_breakdown.s5_cont
            nt_keys = next((keys for vt, keys in acc.version_sets if vt == t), set())

            prefix_sets = [keys for (vt, keys) in acc.version_sets if vt <= t]
            prefix_universe: set[str] = set()
            for keys in prefix_sets:
                prefix_universe |= keys

            turn_links = prefix_breakdown.links_by_turn.get(t, [])
            acc.turns[idx].sets["universe"] = sorted(prefix_universe)
            acc.turns[idx].sets["Nt"] = sorted(nt_keys)
            acc.turns[idx].sets["s5_loops"] = prefix_breakdown.s5_loops
            acc.turns[idx].sets["s5_loops_exact"] = prefix_breakdown.s5_loops_exact
            acc.turns[idx].sets["s5_loops_refdiff"] = prefix_breakdown.s5_loops_refdiff
            acc.turns[idx].sets["s5_refdiff_links"] = [
                f"{link.deleted_key} -> {link.added_key} ({link.rel_type})"
                for link in turn_links
            ]

            prefix_rhos = [acc.turns[j].rho for j in range(idx + 1) if runs[j] >= 2]
            r_s6 = sum(prefix_rhos) / len(prefix_rhos) if prefix_rhos else 0.0
            r_s7 = prefix_s7(s7_flags, idx)
            r_s0, r_s0_never = compute_s0_prefix(prefix_runs, lc_by_run, t, num_turns)

            acc.turns[idx].rolling = {
                "S0": {"cont": r_s0, "never_stopped": r_s0_never},
                "S1": {"cont": r_s1, "bin": int(r_s1 > eps1)},
                "S2": {"cont": r_s2, "bin": int(r_s2 > 0)},
                "S3": {"cont": r_s3, "bin": int(r_s3 > eps3)},
                "S4": {"cont": r_s4, "bin": int(r_s4 > 0)},
                "S5": {"cont": r_s5, "bin": int(r_s5 > 0)},
                "S6": {"cont": r_s6, "bin": int(r_s6 > eps6)},
                "S7": {"cont": r_s7},
            }
