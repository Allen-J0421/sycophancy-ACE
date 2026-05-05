#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True)
class LoadedCsv:
    frame: pd.DataFrame
    path: Path
    key: str


@dataclass(frozen=True)
class PlotArgs:
    source: Path
    output: Path | None


def import_pandas() -> ModuleType:
    import pandas as pd

    return pd


def import_plotting() -> tuple[ModuleType, ModuleType]:
    import matplotlib.pyplot as plt
    import seaborn as sns

    return plt, sns


def parse_args(argv: list[str] | None = None) -> PlotArgs:
    parser = argparse.ArgumentParser(description="Plot line-change totals from experiment CSV logs.")
    parser.add_argument("input", type=Path, help="CSV file or directory containing CSV logs.")
    parser.add_argument("output", nargs="?", type=Path, default=None, help="Optional output image path.")
    namespace = parser.parse_args(argv)
    return PlotArgs(source=namespace.input, output=namespace.output)


def csv_paths(root: Path) -> list[Path]:
    paths = sorted(root.glob("*.csv")) if root.is_dir() else [root]
    if not paths:
        raise SystemExit(f"no .csv in {root}")
    return paths


def zero_filled_column(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return import_pandas().Series(0, index=df.index)
    return df[column].fillna(0)


def ensure_lines_total(df: pd.DataFrame) -> pd.DataFrame:
    if "lines_total" not in df.columns:
        added = zero_filled_column(df, "lines_added")
        deleted = zero_filled_column(df, "lines_deleted")
        df["lines_total"] = added + deleted
    return df


def series_key(df: pd.DataFrame, path: Path) -> str:
    if "model" in df.columns and df["model"].notna().any():
        return str(df["model"].dropna().iloc[0])
    return path.stem


def load_csv(path: Path) -> LoadedCsv:
    pd = import_pandas()
    frame = ensure_lines_total(pd.read_csv(path))
    return LoadedCsv(frame=frame, path=path, key=series_key(frame, path))


def add_series_labels(loaded: list[LoadedCsv]) -> None:
    counts = Counter(item.key for item in loaded)
    for item in loaded:
        item.frame["series"] = (
            f"{item.key} ({item.path.stem})"
            if counts[item.key] > 1
            else item.key
        )


def combine_frames(loaded: list[LoadedCsv]) -> pd.DataFrame:
    return import_pandas().concat([item.frame for item in loaded], ignore_index=True)


def load_frame(paths: list[Path]) -> pd.DataFrame:
    loaded = [load_csv(path) for path in paths]
    add_series_labels(loaded)
    return combine_frames(loaded)


def plot_frame(df: pd.DataFrame, output: Path | None) -> None:
    plt, sns = import_plotting()
    sns.lineplot(data=df, x="run", y="lines_total", hue="series", marker="o")
    plt.xlabel("Iteration")
    plt.ylabel("Lines changed")
    plt.legend(title="model")
    plt.tight_layout()
    if output:
        plt.savefig(output, dpi=200)
    else:
        plt.show()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    plot_frame(load_frame(csv_paths(args.source)), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
