"""Canonical CST node identity and per-turn change sets."""

from __future__ import annotations

from collections.abc import Iterator


def node_key(node: dict) -> str:
    """Canonical, version-stable identity: kind + qualified-name/signature."""
    kind = str(node.get("kind") or "")
    path = node.get("path") or []
    if path:
        ident = "/".join(str(p) for p in path)
    else:
        ident = str(node.get("localName") or "")
        file = node.get("file")
        if file:
            ident = f"{file}:{ident}"
    return f"{kind}|{ident}"


def version_keys(nodes: list[dict] | None) -> set[str]:
    return {node_key(n) for n in (nodes or [])}


def iter_relationships(record: dict) -> Iterator[dict]:
    """Yield all RefDiff relationships with before/after endpoints."""
    for rel in (record.get("matching_relationships") or []) + (
        record.get("non_matching_relationships") or []
    ):
        if rel.get("before") and rel.get("after"):
            yield rel


def extract_change_sets(record: dict) -> tuple[set[str], set[str], set[str]]:
    """Return (added, deleted, touched) canonical node-key sets for one turn."""
    node_relationships = record.get("node_relationships") or {}
    if node_relationships:
        added: set[str] = set()
        deleted: set[str] = set()
        touched: set[str] = set()
        for key, entry in node_relationships.items():
            node = entry.get("node") or {}
            rels = entry.get("relationships") or []
            non_same = [r for r in rels if str(r.get("type")) != "SAME"]
            if key.startswith("before:"):
                if not rels:
                    deleted.add(node_key(node))
            elif key.startswith("after:"):
                if not rels:
                    added.add(node_key(node))
                elif non_same:
                    touched.add(node_key(node))
        return added, deleted, touched

    relationships = (record.get("matching_relationships") or []) + (
        record.get("non_matching_relationships") or []
    )
    seen_before_ids: set[int] = set()
    seen_after_ids: set[int] = set()
    touched_after_ids: set[int] = set()
    for rel in relationships:
        before = rel.get("before") or {}
        after = rel.get("after") or {}
        if "id" in before:
            seen_before_ids.add(int(before["id"]))
        if "id" in after:
            after_id = int(after["id"])
            seen_after_ids.add(after_id)
            if str(rel.get("type")) != "SAME":
                touched_after_ids.add(after_id)

    added = {
        node_key(n)
        for n in (record.get("nodes_after") or [])
        if int(n.get("id", -1)) not in seen_after_ids
    }
    deleted = {
        node_key(n)
        for n in (record.get("nodes_before") or [])
        if int(n.get("id", -1)) not in seen_before_ids
    }
    touched = {
        node_key(n)
        for n in (record.get("nodes_after") or [])
        if int(n.get("id", -1)) in touched_after_ids
    }
    return added, deleted, touched
