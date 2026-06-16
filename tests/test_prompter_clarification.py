"""Tests for Gemini prompter session continuity during clarification."""

from __future__ import annotations

from unittest.mock import MagicMock

from experiment_runner.models import PrompterConfig
from experiment_runner.prompter import GeminiPrompter


def test_respond_to_clarification_keeps_turn_and_chat():
    config = PrompterConfig(
        api_key="test",
        model="test-model",
        system_prompt="system",
        nudge="nudge",
        fallback_prompt="fallback",
        clarification_nudge="The coding agent asked for clarification above.",
    )
    prompter = GeminiPrompter(config)
    chat = MagicMock()
    chat.get_history.return_value = []
    response = MagicMock()
    response.candidates = []
    response.text = "Please refactor."
    response.usage_metadata = None
    response.prompt_feedback = None
    response.response_id = "r1"
    response.model_version = "v1"
    chat.send_message.return_value = response
    prompter._chat = chat

    prompter.turn = 1
    reply = prompter.respond_to_clarification("Which area should I refactor?")

    assert reply == "Please refactor."
    assert prompter.turn == 1
    assert prompter._chat is chat
    assert chat.send_message.call_count == 1
    sent = chat.send_message.call_args[0][0]
    assert "Which area should I refactor?" in sent
    assert sent.endswith("The coding agent asked for clarification above.")
