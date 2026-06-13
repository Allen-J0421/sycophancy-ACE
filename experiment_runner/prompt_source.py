"""Prompt generation strategies for experiment turns."""

from __future__ import annotations

from typing import Protocol

from experiment_runner.models import PrompterConfig, PrompterTurnInput, PromptTurn
from experiment_runner.prompter import GeminiPrompter


class PromptSource(Protocol):
    def prepare(self, *, codebase_snapshot: str) -> None: ...

    def next_prompt(self, turn_input: PrompterTurnInput | None) -> PromptTurn: ...


class FixedPromptSource:
    """Repeat a single static prompt every turn."""

    def __init__(self, prompt: str) -> None:
        self._prompt = prompt

    def prepare(self, *, codebase_snapshot: str) -> None:
        del codebase_snapshot

    def next_prompt(self, turn_input: PrompterTurnInput | None) -> PromptTurn:
        del turn_input
        return PromptTurn(prompt=self._prompt, prompter_jsonl="")


class GeminiPromptSource:
    """Gemini user agent generates a vague prompt each turn."""

    def __init__(self, prompter: GeminiPrompter) -> None:
        self._prompter = prompter

    @classmethod
    def from_config(cls, config: PrompterConfig) -> GeminiPromptSource:
        return cls(GeminiPrompter(config))

    def prepare(self, *, codebase_snapshot: str) -> None:
        self._prompter.set_codebase_snapshot(codebase_snapshot)

    def next_prompt(self, turn_input: PrompterTurnInput | None) -> PromptTurn:
        prompt = self._prompter.next_request(turn_input)
        events = self._prompter.events_jsonl_for_turn(self._prompter.turn)
        return PromptTurn(prompt=prompt, prompter_jsonl=events)
