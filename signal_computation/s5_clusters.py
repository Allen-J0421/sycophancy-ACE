"""Two-layer S5: lineage-root clusters with optional RefDiff soft presence."""

from __future__ import annotations

from dataclasses import dataclass, field

from signal_computation.lineage import LineageIndex
from signal_computation.presence import present_absent_present_nodes


@dataclass(frozen=True)
class S5RefdiffLink:
    run: int
    deleted_run: int
    deleted_key: str
    added_key: str
    rel_type: str
    before_sha: str
    after_sha: str
    compare_ok: bool = True


class UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def add(self, key: str) -> None:
        if key not in self._parent:
            self._parent[key] = key

    def find(self, key: str) -> str:
        self.add(key)
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != key:
            nxt = self._parent[key]
            self._parent[key] = root
            key = nxt
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            merged = min(ra, rb)
            self._parent[ra] = merged
            self._parent[rb] = merged

    def clusters(self) -> dict[str, set[str]]:
        groups: dict[str, set[str]] = {}
        for key in self._parent:
            root = self.find(key)
            groups.setdefault(root, set()).add(key)
        return groups


@dataclass
class S5Breakdown:
    s5_cont: int
    s5_loops: list[str]
    s5_loops_exact: list[str]
    s5_loops_refdiff: list[str]
    links_by_turn: dict[int, list[S5RefdiffLink]] = field(default_factory=dict)


def _top_level_type(path: list[str] | None) -> str:
    if path:
        return str(path[0])
    return ""


def node_key_parts(key: str) -> tuple[str, str]:
    """Return (kind, top-level type) from canonical key kind|Type/path."""
    if "|" not in key:
        return "", ""
    kind, rest = key.split("|", 1)
    top = rest.split("/", 1)[0] if rest else ""
    return kind, top


def prune_compare_candidates(deleted_key: str, added_key: str) -> bool:
    dk, dt = node_key_parts(deleted_key)
    ak, at = node_key_parts(added_key)
    if dk != ak:
        return False
    if dt and at and dt != at:
        return False
    return True


def build_s5_breakdown(
    version_sets: list[tuple[int, set[str]]],
    lineage: LineageIndex,
    s5_links: list[S5RefdiffLink],
) -> S5Breakdown:
    """Compute unified, exact-only, and refdiff-augmented S5 loop counts."""
    exact_presence = _presence_for_roots(version_sets, {r for _, keys in version_sets for r in keys})
    exact_loops = set(present_absent_present_nodes(exact_presence))

    if not s5_links:
        loops = sorted(exact_loops)
        return S5Breakdown(
            s5_cont=len(loops),
            s5_loops=loops,
            s5_loops_exact=loops,
            s5_loops_refdiff=[],
        )

    uf = UnionFind()
    for root in {r for _, keys in version_sets for r in keys}:
        uf.add(root)
    links_by_turn: dict[int, list[S5RefdiffLink]] = {}
    for link in s5_links:
        uf.union(link.deleted_key, link.added_key)
        links_by_turn.setdefault(link.run, []).append(link)

    cluster_map = uf.clusters()
    cluster_ids = sorted(cluster_map.keys())

    soft_turns_by_cluster: dict[str, set[int]] = {cid: set() for cid in cluster_ids}
    for link in s5_links:
        cid = uf.find(link.deleted_key)
        soft_turns_by_cluster.setdefault(cid, set()).add(link.run)

    unified_presence: dict[str, list[bool]] = {}
    for cid in cluster_ids:
        members = cluster_map[cid]
        soft_turns = soft_turns_by_cluster.get(cid, set())
        seq: list[bool] = []
        for vt, keys in version_sets:
            hard = any(lineage.lineage_root(m) in keys for m in members)
            soft = vt in soft_turns
            seq.append(hard or soft)
        unified_presence[cid] = seq

    unified_loops = set(present_absent_present_nodes(unified_presence))
    refdiff_only = sorted(unified_loops - exact_loops)

    return S5Breakdown(
        s5_cont=len(unified_loops),
        s5_loops=sorted(unified_loops),
        s5_loops_exact=sorted(exact_loops),
        s5_loops_refdiff=refdiff_only,
        links_by_turn=links_by_turn,
    )


def _presence_for_roots(
    version_sets: list[tuple[int, set[str]]],
    roots: set[str],
) -> dict[str, list[bool]]:
    return {root: [root in keys for _, keys in version_sets] for root in roots}


def prefix_s5_breakdown(
    version_sets: list[tuple[int, set[str]]],
    lineage: LineageIndex,
    s5_links: list[S5RefdiffLink],
    end_turn: int,
) -> S5Breakdown:
    prefix_sets = [(vt, keys) for vt, keys in version_sets if vt <= end_turn]
    prefix_links = [link for link in s5_links if link.run <= end_turn]
    return build_s5_breakdown(prefix_sets, lineage, prefix_links)


def link_record_to_dict(link: S5RefdiffLink) -> dict:
    return {
        "run": link.run,
        "deleted_run": link.deleted_run,
        "deleted_key": link.deleted_key,
        "added_key": link.added_key,
        "rel_type": link.rel_type,
        "before_sha": link.before_sha,
        "after_sha": link.after_sha,
        "compare_ok": link.compare_ok,
    }


def link_from_dict(d: dict) -> S5RefdiffLink:
    return S5RefdiffLink(
        run=int(d["run"]),
        deleted_run=int(d["deleted_run"]),
        deleted_key=str(d["deleted_key"]),
        added_key=str(d["added_key"]),
        rel_type=str(d.get("rel_type") or ""),
        before_sha=str(d.get("before_sha") or ""),
        after_sha=str(d.get("after_sha") or ""),
        compare_ok=bool(d.get("compare_ok", True)),
    )
