"""Load RefDiff JSONL records."""

from __future__ import annotations

import json
from pathlib import Path


def load_refdiff_records(jsonl_path: Path) -> list[dict]:
    records: list[dict] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    records.sort(key=lambda r: int(r.get("run", 0)))
    return records
