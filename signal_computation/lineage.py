"""N0 lineage tracking across RefDiff relationship chains."""

from __future__ import annotations

from dataclasses import dataclass, field

from signal_computation.nodes import iter_relationships, node_key, version_keys


@dataclass
class LineageIndex:
    """Maps syntactic node keys to N0 ancestry via RefDiff relationship chains."""

    n0_keys: frozenset[str]
    ancestors: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def from_n0(cls, n0_keys: set[str]) -> LineageIndex:
        return cls(
            n0_keys=frozenset(n0_keys),
            ancestors={k: {k} for k in n0_keys},
        )

    def _ensure(self, key: str) -> None:
        if key not in self.ancestors:
            self.ancestors[key] = set()

    def update_from_record(self, record: dict) -> None:
        """Merge N0 ancestry across all before→after relationships in one turn."""
        for rel in iter_relationships(record):
            before = rel["before"]
            after = rel["after"]
            bk = node_key(before)
            ak = node_key(after)
            self._ensure(bk)
            self._ensure(ak)
            merged = set(self.ancestors[bk]) | set(self.ancestors[ak])
            if bk in self.n0_keys:
                merged.add(bk)
            if ak in self.n0_keys:
                merged.add(ak)
            self.ancestors[bk] = merged
            self.ancestors[ak] = merged

    def n0_ancestors(self, key: str) -> set[str]:
        return set(self.ancestors.get(key, set())) & set(self.n0_keys)

    def is_agent_created(self, key: str) -> bool:
        return not self.n0_ancestors(key)

    def lineage_root(self, key: str) -> str:
        anc = self.n0_ancestors(key)
        if anc:
            return min(anc)
        return key

    def lineage_keys(self, keys: set[str]) -> set[str]:
        return {self.lineage_root(k) for k in keys}


def agent_created_deletions(deleted: set[str], lineage: LineageIndex) -> set[str]:
    """Deleted keys with no N0 lineage (true agent-created rollbacks for S4)."""
    return {k for k in deleted if lineage.is_agent_created(k)}


def build_lineage_index(
    records: list[dict], n0_keys: set[str] | None = None
) -> LineageIndex:
    """Build N0 lineage index from records in run order."""
    if not records:
        return LineageIndex.from_n0(set())
    ordered = sorted(records, key=lambda r: int(r.get("run", 0)))
    if n0_keys is None:
        n0_keys = version_keys(ordered[0].get("nodes_before"))
    lineage = LineageIndex.from_n0(n0_keys)
    for rec in ordered:
        if rec.get("refdiff_ok"):
            lineage.update_from_record(rec)
    return lineage
