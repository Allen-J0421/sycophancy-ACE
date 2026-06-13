"""Parse Codex ``--json`` and Claude ``stream-json`` JSONL for dashboard display."""

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


def _claude_assistant_text(obj: dict) -> str | None:
    if obj.get("type") != "assistant":
        return None
    message = obj.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") in ("text", "output_text"):
            text = _non_empty_str(block.get("text"))
            if text:
                parts.append(text)
        elif block.get("type") == "thinking":
            text = _non_empty_str(block.get("thinking")) or _non_empty_str(block.get("text"))
            if text:
                parts.append(text)
    if parts:
        return "\n".join(parts)
    return None


def _claude_result_text(obj: dict) -> str | None:
    if obj.get("type") != "result":
        return None
    return _non_empty_str(obj.get("result"))


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
    """Last agent reply in file order (Codex agent_message or Claude assistant/result)."""
    last: str | None = None
    for obj in _iter_jsonl_objects(jsonl_text):
        text = _item_text_from_event(obj, "agent_message", "assistant", "message")
        if text:
            last = text
            continue
        text = _claude_assistant_text(obj)
        if text:
            last = text
            continue
        text = _claude_result_text(obj)
        if text:
            last = text
    return last or ""


def extract_reasoning_transcript(jsonl_text: str) -> str:
    """Reasoning blocks plus agent messages (Codex 5.2+, Claude thinking/assistant)."""
    reasoning_parts: list[str] = []
    agent_parts: list[str] = []

    for obj in _iter_jsonl_objects(jsonl_text):
        reasoning = _item_text_from_event(obj, "reasoning")
        if reasoning:
            reasoning_parts.append(reasoning)
        agent = _item_text_from_event(obj, "agent_message", "assistant", "message")
        if agent:
            agent_parts.append(agent)
            continue
        if obj.get("type") == "assistant":
            message = obj.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "thinking":
                            text = _non_empty_str(block.get("thinking")) or _non_empty_str(
                                block.get("text")
                            )
                            if text:
                                reasoning_parts.append(text)
                        elif block.get("type") in ("text", "output_text"):
                            text = _non_empty_str(block.get("text"))
                            if text:
                                agent_parts.append(text)

    if reasoning_parts:
        return "\n\n".join(reasoning_parts + agent_parts)
    return "\n\n".join(agent_parts)
