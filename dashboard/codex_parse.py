"""Parse Codex ``--json`` JSONL for dashboard display."""

from __future__ import annotations

import json


def _non_empty_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _block_text(block: dict, *types: str) -> str | None:
    if block.get("type") not in types:
        return None
    return _non_empty_str(block.get("text")) or _non_empty_str(block.get("content"))


def _item_text_from_event(obj: dict, *types: str) -> str | None:
    item = obj.get("item")
    if isinstance(item, dict):
        text = _block_text(item, *types)
        if text:
            return text

    payload = obj.get("payload")
    if isinstance(payload, dict):
        text = _block_text(payload, *types)
        if text:
            return text

    return _block_text(obj, *types)


def _iter_jsonl_objects(jsonl_text: str):
    for raw in jsonl_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def extract_final_agent_message(jsonl_text: str) -> str:
    """Last ``agent_message`` (or legacy assistant/message) in file order."""
    last: str | None = None
    for obj in _iter_jsonl_objects(jsonl_text):
        text = _item_text_from_event(obj, "agent_message", "assistant", "message")
        if text:
            last = text
    return last or ""


def extract_reasoning_transcript(jsonl_text: str) -> str:
    """Reasoning blocks plus agent messages (5.2), or all agent messages (5.4/5.5)."""
    reasoning_parts: list[str] = []
    agent_parts: list[str] = []

    for obj in _iter_jsonl_objects(jsonl_text):
        reasoning = _item_text_from_event(obj, "reasoning")
        if reasoning:
            reasoning_parts.append(reasoning)
        agent = _item_text_from_event(obj, "agent_message", "assistant", "message")
        if agent:
            agent_parts.append(agent)

    if reasoning_parts:
        return "\n\n".join(reasoning_parts + agent_parts)
    return "\n\n".join(agent_parts)
