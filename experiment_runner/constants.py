"""Shared constants for the experiment runner."""

CSV_COLUMNS = (
    "run",
    "files_changed",
    "lines_added",
    "lines_deleted",
    "lines_total",
    "duration_s",
    "exit_code",
    "timed_out",
    "commit_sha",
    "commit_message",
    "model",
    "git_branch",
)
CODEX_AUTO_FLAGS = ("--full-auto", "--skip-git-repo-check")
CLAUDE_AUTO_FLAGS = ("--verbose", "--permission-mode", "bypassPermissions")
DEFAULT_TIMEOUT = 18000  # 5 hours
PROMPTER_SUFFIX = "-Agent"

# Built-in Gemini user-agent system prompts (config/prompter_system_prompt*.txt).
PROMPTER_PROFILES: dict[str, str] = {
    "novice": "prompter_system_prompt.txt",
    "expert": "prompter_system_prompt_expert.txt",
}
DEFAULT_PROMPTER_PROFILE = "novice"

# Thinking / reasoning effort levels accepted by each agent CLI.
#   Claude:  `claude -p --effort <level>`
#   Codex:   `codex exec -c model_reasoning_effort="<level>"`
# gpt-5.5 API supports none|low|medium|high|xhigh (not minimal).
CLAUDE_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
CODEX_EFFORT_LEVELS = ("none", "low", "medium", "high", "xhigh")
CODEX_REASONING_CONFIG_KEY = "model_reasoning_effort"


def codex_exec_flags(effort: str | None = None) -> tuple[str, ...]:
    """CLI flags for ``codex exec`` / ``codex exec resume``."""
    del effort
    return CODEX_AUTO_FLAGS


def effort_levels_for_agent(agent: str) -> tuple[str, ...]:
    """Valid `--effort` values for the given agent CLI."""
    return CLAUDE_EFFORT_LEVELS if agent == "claude" else CODEX_EFFORT_LEVELS

AGENT_JSONL_FILENAMES = {
    "codex": "codex.jsonl",
    "claude": "claude.jsonl",
}


def agent_jsonl_filename(agent: str) -> str:
    return AGENT_JSONL_FILENAMES.get(agent, "codex.jsonl")
