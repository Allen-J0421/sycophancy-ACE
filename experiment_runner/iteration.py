"""Single experiment iteration: coding agent run + git stage/diff/commit."""

from __future__ import annotations

from experiment_runner.coding_agent import CodingAgent
from experiment_runner.git_repo import GitRepository
from experiment_runner.models import AgentKind, IterationResult, agent_run_ok


def run_iteration(
    git: GitRepository,
    agent: CodingAgent,
    *,
    agent_kind: AgentKind,
    iteration: int,
    prompt: str,
    session_id: str | None,
    previous_sha: str,
    pathspec: list[str] | None,
) -> IterationResult:
    """Run the coding agent once for one logged iteration, then stage, diff, and commit."""
    is_first_turn = iteration == 1 and session_id is None

    agent_result, jsonl_text = agent.run(
        prompt,
        is_first=is_first_turn,
        session_id=session_id if not is_first_turn else None,
    )

    stats = git.stage_all_and_diff_stats(previous_sha, pathspec)
    diff_patch = git.capture_step_diff(previous_sha, pathspec)

    commit_message = f"{agent_kind}-exp: iteration {iteration}"
    if not agent_run_ok(agent_result):
        commit_message += (
            f" [{agent_kind} failed exit={agent_result.exit_code} "
            f"timed_out={int(agent_result.timed_out)}]"
        )

    commit_sha = git.commit(commit_message)

    return IterationResult(
        number=iteration,
        stats=stats,
        agent=agent_result,
        commit_sha=commit_sha,
        commit_message=commit_message,
        jsonl_text=jsonl_text,
        diff_patch=diff_patch,
    )
