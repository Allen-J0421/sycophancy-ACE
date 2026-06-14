"""S5 presence-sequence helpers (present → absent → present)."""

from __future__ import annotations


def present_absent_present_nodes(presence: dict[str, list[bool]]) -> list[str]:
    """Return nodes whose presence sequence shows present -> absent -> present."""
    matched: list[str] = []
    for node, sequence in presence.items():
        seen_present = False
        gap_after_present = False
        for present in sequence:
            if present:
                if gap_after_present:
                    matched.append(node)
                    break
                seen_present = True
            elif seen_present:
                gap_after_present = True
    return sorted(matched)


def count_present_absent_present(presence: dict[str, list[bool]]) -> int:
    """Count nodes whose presence sequence shows present -> absent -> present."""
    return len(present_absent_present_nodes(presence))


def build_presence(
    version_sets: list[tuple[int, set[str]]],
) -> dict[str, list[bool]]:
    universe: set[str] = set()
    for _, keys in version_sets:
        universe |= keys
    return {
        node: [node in keys for _, keys in version_sets] for node in universe
    }
