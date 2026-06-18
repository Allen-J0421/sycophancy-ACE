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
DEFAULT_TIMEOUT = 600
PROMPTER_SUFFIX = "-Agent"

# Thinking / reasoning effort levels accepted by each agent CLI.
#   Claude:  `claude -p --effort <level>`
#   Codex:   `codex exec -c model_reasoning_effort="<level>"`
CLAUDE_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
CODEX_EFFORT_LEVELS = ("minimal", "low", "medium", "high")
CODEX_REASONING_CONFIG_KEY = "model_reasoning_effort"


def effort_levels_for_agent(agent: str) -> tuple[str, ...]:
    """Valid `--effort` values for the given agent CLI."""
    return CLAUDE_EFFORT_LEVELS if agent == "claude" else CODEX_EFFORT_LEVELS

AGENT_JSONL_FILENAMES = {
    "codex": "codex.jsonl",
    "claude": "claude.jsonl",
}


def agent_jsonl_filename(agent: str) -> str:
    return AGENT_JSONL_FILENAMES.get(agent, "codex.jsonl")
