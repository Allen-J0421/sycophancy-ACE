"""Cross-turn S5 layer-2 links via RefDiff matching relationships."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from experiment_runner.util import eprint

from signal_computation.lineage import LineageIndex, agent_created_deletions
from signal_computation.nodes import extract_change_sets, node_key, version_keys
from signal_computation.refdiff_runner import run_refdiff_compare
from signal_computation.s5_clusters import (
    S5RefdiffLink,
    link_from_dict,
    link_record_to_dict,
    prune_compare_candidates,
)


@dataclass
class DeletionArchiveEntry:
    key: str
    deleted_run: int
    last_present_sha: str
    relinked: bool = False


@dataclass
class S5LinkBuilder:
    compare_cache: dict[tuple[str, str, str, str], dict] = field(default_factory=dict)

    def build(
        self,
        records: list[dict],
        *,
        repo_path: str,
        language: str,
        enabled: bool = True,
    ) -> list[S5RefdiffLink]:
        if not enabled or not records:
            return []

        repo = Path(repo_path) if repo_path else None
        if repo is None or not repo.exists():
            eprint("[warn] S5 layer-2 skipped: repo not found")
            return []

        by_run = {int(r["run"]): r for r in records}
        runs = sorted(by_run)
        first = by_run[runs[0]]
        n0_keys = version_keys(first.get("nodes_before"))
        lineage = LineageIndex.from_n0(n0_keys)

        commit_after: dict[int, str] = {}
        for t in runs:
            sha = str(by_run[t].get("commit_sha") or "").strip()
            if sha:
                commit_after[t] = sha

        def last_present_sha(deleted_run: int) -> str:
            if deleted_run <= 1:
                return str(first.get("parent_sha") or first.get("commit_sha") or "")
            prev = deleted_run - 1
            return commit_after.get(prev, "")

        archive: list[DeletionArchiveEntry] = []
        links: list[S5RefdiffLink] = []

        for t in runs:
            rec = by_run[t]
            ok = bool(rec.get("refdiff_ok"))
            if ok:
                lineage.update_from_record(rec)
                added, deleted, _ = extract_change_sets(rec)
            else:
                added, deleted = set(), set()

            agent_deleted = agent_created_deletions(deleted, lineage)
            for key in agent_deleted:
                sha = last_present_sha(t)
                if sha:
                    archive.append(
                        DeletionArchiveEntry(
                            key=key,
                            deleted_run=t,
                            last_present_sha=sha,
                        )
                    )

            if not ok:
                continue

            after_sha = commit_after.get(t, "")
            if not after_sha:
                continue

            agent_added = {k for k in added if lineage.is_agent_created(k)}
            if not agent_added:
                continue

            active = [e for e in archive if not e.relinked]
            if not active:
                continue

            sha_groups: dict[str, list[DeletionArchiveEntry]] = {}
            for entry in active:
                candidates = [
                    k
                    for k in agent_added
                    if prune_compare_candidates(entry.key, k)
                ]
                if not candidates:
                    continue
                sha_groups.setdefault(entry.last_present_sha, []).append(entry)

            for before_sha, entries in sha_groups.items():
                if not before_sha or before_sha == after_sha:
                    continue
                compare = run_refdiff_compare(
                    repo=repo,
                    before_sha=before_sha,
                    after_sha=after_sha,
                    lang=language,
                    compare_cache=self.compare_cache,
                )
                if not compare.get("refdiff_ok"):
                    continue

                matched_added: set[str] = set()
                for rel in compare.get("matching_relationships") or []:
                    if not rel.get("is_matching", True):
                        continue
                    before = rel.get("before") or {}
                    after = rel.get("after") or {}
                    if not before or not after:
                        continue
                    bk = node_key(before)
                    ak = node_key(after)
                    if ak not in agent_added or ak in matched_added:
                        continue
                    entry = next(
                        (e for e in entries if e.key == bk and not e.relinked),
                        None,
                    )
                    if entry is None:
                        continue
                    links.append(
                        S5RefdiffLink(
                            run=t,
                            deleted_run=entry.deleted_run,
                            deleted_key=entry.key,
                            added_key=ak,
                            rel_type=str(rel.get("type") or ""),
                            before_sha=before_sha,
                            after_sha=after_sha,
                            compare_ok=True,
                        )
                    )
                    entry.relinked = True
                    matched_added.add(ak)

        return links


def write_s5_links_cache(links: list[S5RefdiffLink], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(link_record_to_dict(link), ensure_ascii=False) for link in links]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def load_s5_links_cache(path: Path) -> list[S5RefdiffLink]:
    if not path.is_file():
        return []
    links: list[S5RefdiffLink] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        links.append(link_from_dict(json.loads(line)))
    return links


def s5_links_cache_path(jsonl_path: Path) -> Path:
    stamp = jsonl_path.name.removesuffix("-refdiff.jsonl")
    return jsonl_path.with_name(f"{stamp}-s5-links.jsonl")
