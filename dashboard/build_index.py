#!/usr/bin/env python3
"""Build the root landing page listing all dashboards under result/."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent

INDEX_TEMPLATE_PATH = _SCRIPT_DIR / "index_template.html"
INDEX_CSS_PATH = _SCRIPT_DIR / "index.css"
INDEX_JS_PATH = _SCRIPT_DIR / "index.js"
OUTPUT_PATH = _REPO_ROOT / "index.html"

DASH_TEMP_MARKER = "-Dash-Temp"


def parse_experiment_name(folder_name: str) -> tuple[str, str | None]:
    """Split ``bubble_sort-Dash-Temp0.0`` → (repo, temperature label)."""
    if DASH_TEMP_MARKER in folder_name:
        repo, temp = folder_name.split(DASH_TEMP_MARKER, 1)
        return repo, f"Temperature {temp}"
    return folder_name, None


def format_updated(mtime: float) -> str:
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def discover_dashboards(result_dir: Path) -> list[dict]:
    """Return built dashboards and pending experiment folders."""
    if not result_dir.is_dir():
        return []

    built: list[dict] = []
    pending: list[dict] = []

    for exp_dir in sorted(result_dir.iterdir()):
        if not exp_dir.is_dir() or exp_dir.name.startswith("."):
            continue
        if exp_dir.name in ("__pycache__",):
            continue

        csv_count = len(list(exp_dir.glob("*-log.csv")))
        if csv_count == 0:
            continue

        repo, temp_label = parse_experiment_name(exp_dir.name)
        subtitle_parts = []
        if temp_label:
            subtitle_parts.append(temp_label)
        subtitle_parts.append(f"{csv_count} model run{'s' if csv_count != 1 else ''}")

        dashboard_path = exp_dir / "dashboard.html"
        if dashboard_path.is_file():
            mtime = dashboard_path.stat().st_mtime
            built.append(
                {
                    "id": exp_dir.name,
                    "href": f"result/{exp_dir.name}/dashboard.html",
                    "title": repo.replace("_", " "),
                    "subtitle": " · ".join(subtitle_parts) + f" · Updated {format_updated(mtime)}",
                    "updated": mtime,
                    "pending": False,
                }
            )
        else:
            pending.append(
                {
                    "id": exp_dir.name,
                    "title": repo.replace("_", " "),
                    "subtitle": " · ".join(subtitle_parts) + " · Dashboard not built",
                    "pending": True,
                }
            )

    built.sort(key=lambda x: x["id"])
    pending.sort(key=lambda x: x["id"])
    return built + pending


def render_landing_page(dashboards: list[dict]) -> str:
    template = INDEX_TEMPLATE_PATH.read_text(encoding="utf-8")
    style_css = INDEX_CSS_PATH.read_text(encoding="utf-8")
    index_js = INDEX_JS_PATH.read_text(encoding="utf-8")

    for item in dashboards:
        item.pop("updated", None)

    data_json = json.dumps(dashboards, ensure_ascii=False)
    data_json = data_json.replace("</", "<\\/")

    html = template.replace("/*__STYLE__*/", style_css)
    html = html.replace("/*__INDEX_JS__*/", index_js)
    html = html.replace("/*__DASHBOARDS__*/", data_json)
    return html


def build_landing_page(
    result_dir: Path | None = None,
    *,
    output_path: Path | None = None,
) -> Path:
    """Scan result/ and write index.html at repo root."""
    result_dir = (result_dir or _REPO_ROOT / "result").resolve()
    output_path = output_path or OUTPUT_PATH

    dashboards = discover_dashboards(result_dir)
    output_path.write_text(render_landing_page(dashboards), encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build root landing page (index.html) listing all dashboards."
    )
    parser.add_argument(
        "--result-dir",
        type=Path,
        default=_REPO_ROOT / "result",
        help="Path to result/ directory (default: repo result/).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="Output path for index.html (default: repo root index.html).",
    )
    args = parser.parse_args(argv)

    dashboards = discover_dashboards(args.result_dir)
    out = build_landing_page(args.result_dir, output_path=args.output)
    count = sum(1 for d in dashboards if not d.get("pending"))
    pending = sum(1 for d in dashboards if d.get("pending"))
    print(f"Wrote: {out} ({count} dashboard(s), {pending} pending)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
