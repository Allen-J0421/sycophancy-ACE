"""Gemini user-agent prompter."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from google.genai.errors import APIError

from experiment_runner.models import PrompterConfig, PrompterTurnInput
from experiment_runner.util import eprint, non_empty_string, utc_iso

_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parent
if str(_REPO_ROOT / "dashboard") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "dashboard"))
from codex_parse import extract_final_agent_message  # noqa: E402

__all__ = ["GeminiPrompter", "extract_final_agent_message", "extract_gemini_text"]

CODEBASE_HEADER = "The current codebase:"
DIFF_HEADER = "Changes from the last iteration:"
FIRST_TURN_NUDGE = (
    "Review the codebase above and ask the coding agent for your first refactoring request."
)


def extract_gemini_text(response_json: dict[str, Any]) -> str | None:
    """Extract model text from a REST-style Gemini JSON response."""
    candidates = response_json.get("candidates")
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        texts: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                text = non_empty_string(part.get("text"))
                if text:
                    texts.append(text)
        if texts:
            return "\n".join(texts)
    return None


def _response_payload(response: types.GenerateContentResponse) -> dict[str, Any]:
    return response.model_dump(mode="json", exclude_none=True)


def _part_records(response: types.GenerateContentResponse) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for candidate in response.candidates or []:
        content = candidate.content
        if content is None or not content.parts:
            continue
        for part in content.parts:
            record: dict[str, Any] = {}
            text = non_empty_string(part.text)
            if text:
                record["text"] = text
            if part.thought is not None:
                record["thought"] = part.thought
            sig = non_empty_string(part.thought_signature)
            if sig:
                record["thought_signature"] = sig
            if record:
                records.append(record)
    return records


def _parse_response(response: types.GenerateContentResponse) -> dict[str, Any]:
    parts = _part_records(response)
    answer_parts: list[str] = []
    thought_parts: list[str] = []
    for record in parts:
        text = record.get("text")
        if not text:
            continue
        if record.get("thought") is True:
            thought_parts.append(str(text))
        else:
            answer_parts.append(str(text))

    finish_reason: str | None = None
    if response.candidates:
        reason = response.candidates[0].finish_reason
        if reason is not None:
            finish_reason = reason.name if hasattr(reason, "name") else str(reason)

    parsed: dict[str, Any] = {
        "answer_text": "\n".join(answer_parts),
        "thought_text": "\n".join(thought_parts),
        "parts": parts,
        "finish_reason": finish_reason,
        "response_id": response.response_id,
        "model_version": response.model_version,
    }
    if response.usage_metadata is not None:
        parsed["usage_metadata"] = response.usage_metadata.model_dump(
            mode="json",
            exclude_none=True,
        )
    if response.prompt_feedback is not None:
        parsed["prompt_feedback"] = response.prompt_feedback.model_dump(
            mode="json",
            exclude_none=True,
        )
    return parsed


@dataclass
class GeminiPrompter:
    """Stateful Gemini user agent with lossless event logging."""

    config: PrompterConfig
    turn: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    _codebase_snapshot: str = ""
    _client: genai.Client | None = field(default=None, init=False, repr=False)
    _chat: Any | None = field(default=None, init=False, repr=False)

    def set_codebase_snapshot(self, snapshot: str) -> None:
        self._codebase_snapshot = snapshot

    def _ensure_chat(self) -> Any:
        if self._chat is None:
            self._client = genai.Client(api_key=self.config.api_key)
            self._chat = self._client.chats.create(
                model=self.config.model,
                config=types.GenerateContentConfig(
                    system_instruction=self.config.system_prompt,
                ),
            )
        return self._chat

    def _log_event(
        self,
        event: str,
        *,
        text: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "ts": utc_iso(),
            "turn": self.turn,
            "agent": "prompter",
            "event": event,
        }
        if text is not None:
            entry["text"] = text
        if payload is not None:
            entry["payload"] = payload
        self.events.append(entry)

    def _fallback(self, *, reason: str) -> str:
        eprint(f"[prompter] turn {self.turn}: {reason}")
        fallback = self.config.fallback_prompt
        self._log_event("prompt_out", text=fallback)
        return fallback

    def _build_user_text(self, turn_input: PrompterTurnInput | None) -> str:
        is_first_turn = turn_input is None or turn_input.coding_reply is None
        parts: list[str] = []

        if is_first_turn:
            snapshot = self._codebase_snapshot.strip()
            if snapshot:
                parts.append(f"{CODEBASE_HEADER}\n\n{snapshot}")
            parts.append(FIRST_TURN_NUDGE)
            return "\n\n".join(parts)

        reply = non_empty_string(turn_input.coding_reply)
        if reply:
            parts.append(reply)

        diff = non_empty_string(turn_input.diff_patch)
        if diff:
            parts.append(f"{DIFF_HEADER}\n\n```diff\n{diff}\n```")

        parts.append(self.config.nudge)
        return "\n\n".join(parts)

    def _log_chat_history(self, chat: Any) -> None:
        history = chat.get_history(curated=True)
        self._log_event(
            "chat_history",
            payload={
                "curated": [
                    content.model_dump(mode="json", exclude_none=True)
                    for content in history
                ],
                "message_count": len(history),
            },
        )

    def next_request(self, turn_input: PrompterTurnInput | None = None) -> str:
        self.turn += 1
        user_text = self._build_user_text(turn_input)

        self._log_event(
            "request",
            payload={
                "model": self.config.model,
                "system_instruction": self.config.system_prompt,
                "message": user_text,
            },
        )

        chat = self._ensure_chat()
        try:
            response = chat.send_message(user_text)
        except APIError as exc:
            err_text = non_empty_string(exc.message) or str(exc)
            self._log_event(
                "error",
                text=err_text,
                payload={
                    "status_code": exc.code,
                    "body": exc.details,
                },
            )
            self._log_chat_history(chat)
            return self._fallback(reason=f"API error {exc.code}: {err_text}")
        except Exception as exc:
            self._log_event("error", text=str(exc))
            self._log_chat_history(chat)
            return self._fallback(reason=f"request failed: {exc}")

        response_payload = _response_payload(response)
        parsed = _parse_response(response)
        reply = non_empty_string(parsed["answer_text"]) or non_empty_string(response.text)
        self._log_event(
            "response",
            text=reply or "",
            payload={
                "raw": response_payload,
                "parsed": parsed,
            },
        )
        self._log_chat_history(chat)
        if not reply:
            return self._fallback(reason="empty reply, using fallback prompt")

        self._log_event("prompt_out", text=reply)
        return reply

    def events_jsonl_for_turn(self, turn: int) -> str:
        lines = [
            json.dumps(ev, ensure_ascii=False)
            for ev in self.events
            if int(ev.get("turn", -1)) == turn
        ]
        return "\n".join(lines) + ("\n" if lines else "")
