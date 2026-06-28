"""Tests for plot_aggregate --alg filtering."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import plot_aggregate as pa  # noqa: E402


def test_exp_alg_key_algorithms_style() -> None:
    assert pa.exp_alg_key("001_binary_search-high-Agent") == pa.AlgKey(None, 1)


def test_exp_alg_key_realworld_prefixes() -> None:
    assert pa.exp_alg_key("R001_module_java-high-Agent") == pa.AlgKey("R", 1)
    assert pa.exp_alg_key("G001_dbeaver-high-Agent") == pa.AlgKey("G", 1)
    assert pa.exp_alg_key("R001_module_java-high-Agent") != pa.exp_alg_key("G001_dbeaver-high-Agent")


def test_parse_alg_filter_algorithms_range() -> None:
    got = pa.parse_alg_filter("001-003")
    assert got == {pa.AlgKey(None, 1), pa.AlgKey(None, 2), pa.AlgKey(None, 3)}


def test_parse_alg_filter_realworld_r_range() -> None:
    got = pa.parse_alg_filter("R001-R003")
    assert got == {pa.AlgKey("R", 1), pa.AlgKey("R", 2), pa.AlgKey("R", 3)}
    assert pa.AlgKey("G", 1) not in got


def test_parse_alg_filter_realworld_g_single() -> None:
    got = pa.parse_alg_filter("G001,G003")
    assert got == {pa.AlgKey("G", 1), pa.AlgKey("G", 3)}


def test_experiment_dirs_distinguishes_r_and_g(tmp_path: Path) -> None:
    suite = tmp_path / "RealWorld"
    suite.mkdir()
    for name in (
        "R001_module_java-high-Agent",
        "R002_module_java-high-Agent",
        "G001_dbeaver-high-Agent",
        "G002_elasticsearch-high-Agent",
    ):
        (suite / name).mkdir()
    r_only = pa.experiment_dirs(suite, pa.parse_alg_filter("R001"))
    assert [d.name for d in r_only] == ["R001_module_java-high-Agent"]
    g_range = pa.experiment_dirs(suite, pa.parse_alg_filter("G001-G002"))
    assert [d.name for d in g_range] == [
        "G001_dbeaver-high-Agent",
        "G002_elasticsearch-high-Agent",
    ]
    # Bare ``001`` matches only unprefixed ids, not R001/G001.
    (suite / "001_legacy-high-Agent").mkdir()
    bare = pa.experiment_dirs(suite, pa.parse_alg_filter("001"))
    assert [d.name for d in bare] == ["001_legacy-high-Agent"]
