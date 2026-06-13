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

AGENT_JSONL_FILENAMES = {
    "codex": "codex.jsonl",
    "claude": "claude.jsonl",
}


def agent_jsonl_filename(agent: str) -> str:
    return AGENT_JSONL_FILENAMES.get(agent, "codex.jsonl")
