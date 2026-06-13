"""Coding-agent protocol shared by Codex and Claude CLI wrappers."""

from __future__ import annotations

from typing import Protocol

from experiment_runner.models import AgentRunResult


class CodingAgent(Protocol):
    def run(
        self,
        prompt: str,
        *,
        is_first: bool,
        session_id: str | None = None,
    ) -> tuple[AgentRunResult, str]: ...
