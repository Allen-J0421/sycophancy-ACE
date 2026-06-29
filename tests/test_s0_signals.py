"""Tests for S0 (first structural stop turn) computation."""

import json
from pathlib import Path

from signal_computation.line_signals import compute_s0, compute_s0_prefix


def _lc_map(runs: list[int], values: list[int]) -> dict[int, int]:
    return dict(zip(runs, values))


def test_stop_at_turn_3():
    runs = list(range(1, 11))
    lc = _lc_map(runs, [10, 5, 0, 3, 2, 1, 4, 6, 7, 8])
    assert compute_s0(runs, lc) == (3, False)


def test_never_stop():
    runs = list(range(1, 11))
    lc = _lc_map(runs, [1] * 10)
    assert compute_s0(runs, lc) == (10, True)


def test_stop_at_turn_10():
    runs = list(range(1, 11))
    lc = _lc_map(runs, [1] * 9 + [0])
    assert compute_s0(runs, lc) == (10, False)


def test_prefix_stop_visible_early():
    runs = list(range(1, 11))
    lc = _lc_map(runs, [10, 5, 0, 3, 2, 1, 4, 6, 7, 8])
    prefix = runs[:5]
    assert compute_s0_prefix(prefix, lc, end_turn=5, num_turns=10) == (3, False)


def test_prefix_censored_mid_run():
    runs = list(range(1, 11))
    lc = _lc_map(runs, [1] * 10)
    prefix = runs[:5]
    assert compute_s0_prefix(prefix, lc, end_turn=5, num_turns=10) == (5, True)


def test_prefix_censored_at_horizon():
    runs = list(range(1, 11))
    lc = _lc_map(runs, [1] * 10)
    assert compute_s0_prefix(runs, lc, end_turn=10, num_turns=10) == (10, True)


def test_s0_patch_preserves_existing_signals(tmp_path: Path):
    from signal_computation.s0_patch import patch_s0_for_experiment

    exp_dir = tmp_path / "exp"
    refdiff_dir = exp_dir / "refdiff"
    signals_out = exp_dir / "signals"
    refdiff_dir.mkdir(parents=True)
    signals_out.mkdir(parents=True)

    stamp = "20260101T000000Z-gpt-5.5"
    records = [
        {"run": t, "stamp": stamp, "model": "gpt-5.5", "git_stat": {"lines_added": 1, "lines_deleted": 0}}
        for t in range(1, 4)
    ]
    records.append(
        {"run": 4, "stamp": stamp, "model": "gpt-5.5", "git_stat": {"lines_added": 0, "lines_deleted": 0}}
    )
    (refdiff_dir / f"{stamp}-refdiff.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )

    existing = {
        "stamp": stamp,
        "model": "gpt-5.5",
        "signals": {
            "S1": {"cont": 0.42, "bin": 1},
            "S6": {"cont": 0.1, "bin": 0},
        },
        "turns": [
            {"run": t, "LC": 1, "rolling": {"S1": {"cont": 0.42, "bin": 1}}, "sets": {}}
            for t in range(1, 5)
        ],
    }
    signals_path = signals_out / f"{stamp}-signals.json"
    signals_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    csv_path = signals_out / "exp_signals.csv"
    csv_path.write_text(
        "experiment,stamp,model,S1,S1_bin,S6_cont,S6_bin\n"
        f"exp,{stamp},gpt-5.5,0.420000,1,0.100000,0\n",
        encoding="utf-8",
    )

    patched = patch_s0_for_experiment(exp_dir)
    assert patched == 1

    data = json.loads(signals_path.read_text(encoding="utf-8"))
    assert data["signals"]["S1"] == {"cont": 0.42, "bin": 1}
    assert data["signals"]["S0"] == {"cont": 4, "never_stopped": False}
    assert data["turns"][3]["rolling"]["S0"] == {"cont": 4, "never_stopped": False}
    assert data["turns"][0]["rolling"]["S0"] == {"cont": 1, "never_stopped": True}

    csv_text = csv_path.read_text(encoding="utf-8")
    assert "S0" in csv_text
    assert "S0_never_stopped" in csv_text
    assert ",4,0" in csv_text or ",4,0\n" in csv_text

