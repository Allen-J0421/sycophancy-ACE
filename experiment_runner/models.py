"""Domain models for experiment runs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from experiment_runner.limit_detect import LimitDetectConfig

AgentKind = Literal["codex", "claude"]


@dataclass(frozen=True)
class TargetScope:
    root: Path
    rel_path: str
    pathspec: list[str] | None
    work_dir: Path

    @property
    def repo_name(self) -> str:
        return self.root.name or "target"


@dataclass(frozen=True)
class LineStats:
    files_changed: int
    lines_added: int
    lines_deleted: int

    @classmethod
    def empty(cls) -> LineStats:
        return cls(files_changed=0, lines_added=0, lines_deleted=0)

    @property
    def lines_total(self) -> int:
        return self.lines_added + self.lines_deleted

    def plus(self, other: LineStats) -> LineStats:
        return LineStats(
            files_changed=self.files_changed + other.files_changed,
            lines_added=self.lines_added + other.lines_added,
            lines_deleted=self.lines_deleted + other.lines_deleted,
        )


@dataclass(frozen=True)
class AgentRunResult:
    exit_code: int
    duration_s: float
    timed_out: bool
    session_id: str | None = None


def agent_run_ok(agent: AgentRunResult) -> bool:
    """True only if the coding agent exited 0 and did not time out."""
    return agent.exit_code == 0 and not agent.timed_out


@dataclass(frozen=True)
class IterationResult:
    number: int
    stats: LineStats
    agent: AgentRunResult
    commit_sha: str
    commit_message: str
    jsonl_text: str = ""
    diff_patch: str = ""
    prompt_text: str = ""
    prompter_jsonl: str = ""
    clarification_prompt_text: str = ""
    clarification_followup: bool = False

    def as_csv_row(self, *, model: str, branch: str) -> list[object]:
        return [
            self.number,
            self.stats.files_changed,
            self.stats.lines_added,
            self.stats.lines_deleted,
            self.stats.lines_total,
            f"{self.agent.duration_s:.3f}",
            self.agent.exit_code,
            int(self.agent.timed_out),
            self.commit_sha,
            self.commit_message,
            model,
            branch,
        ]


@dataclass(frozen=True)
class ClarificationPatterns:
    refusal_blockers: tuple[re.Pattern[str], ...]
    clarification_signals: tuple[re.Pattern[str], ...]
    require_question_mark: bool = True


@dataclass(frozen=True)
class PrompterConfig:
    api_key: str
    model: str
    system_prompt: str
    nudge: str
    fallback_prompt: str
    clarification_nudge: str = "The coding agent asked for clarification above."


@dataclass(frozen=True)
class ExperimentConfig:
    target: TargetScope
    prompt: str
    requested_model: str
    effective_model: str
    branch: str
    results_csv: Path
    artifacts_dir: Path
    start_commit: str
    iterations: int
    agent: AgentKind = "codex"
    prompter: bool = False
    prompter_config: PrompterConfig | None = None
    clarification_patterns: ClarificationPatterns | None = None
    effort: str | None = None
    limit_detect: LimitDetectConfig | None = None


@dataclass(frozen=True)
class CliArgs:
    target: Path
    iterations: int
    commit: str
    model: str
    label: str | None
    agent: AgentKind
    prompter: bool
    output_base: Path | None = None
    effort: str | None = None


@dataclass(frozen=True)
class ModelInfo:
    effective: str
    slug: str


@dataclass(frozen=True)
class PromptTurn:
    prompt: str
    prompter_jsonl: str


@dataclass(frozen=True)
class PrompterTurnInput:
    """Context passed from the experiment loop into the Gemini prompter each turn."""

    coding_reply: str | None = None
    diff_patch: str | None = None
