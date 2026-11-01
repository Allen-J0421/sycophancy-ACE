"""Single experiment iteration: coding agent run + git stage/diff/commit."""

from __future__ import annotations

import json
from collections.abc import Callable

from experiment_runner.clarification import (
    ClarificationPatterns,
    merge_agent_results,
    needs_clarification_followup,
)
from experiment_runner.coding_agent import CodingAgent
from experiment_runner.git_repo import GitRepository
from experiment_runner.models import AgentKind, IterationResult, agent_run_ok
from experiment_runner.prompter import extract_final_agent_message
from experiment_runner.util import eprint

ClarificationResponder = Callable[[str], str]


def count_result_events(jsonl_text: str) -> int:
    """Number of `result` events in a Claude stream-json turn (1 for a normal turn)."""
    count = 0
    for line in jsonl_text.splitlines():
        if '"type":"result"' not in line and '"type": "result"' not in line:
            continue
        try:
            if json.loads(line).get("type") == "result":
                count += 1
        except (json.JSONDecodeError, AttributeError):
            continue
    return count


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
    clarification_patterns: ClarificationPatterns | None = None,
    clarification_responder: ClarificationResponder | None = None,
) -> IterationResult:
    """Run the coding agent for one logged iteration, then stage, diff, and commit."""
    is_first_turn = iteration == 1 and session_id is None

    agent_result, jsonl_text = agent.run(
        prompt,
        is_first=is_first_turn,
        session_id=session_id if not is_first_turn else None,
    )
    resume_session_id = agent_result.session_id or session_id

    stats = git.stage_all_and_diff_stats(previous_sha, pathspec)
    diff_patch = git.capture_step_diff(previous_sha, pathspec)
    final_msg = extract_final_agent_message(jsonl_text)
    clarification_followup = False
    clarification_prompt_text = ""

    if (
        clarification_patterns is not None
        and clarification_responder is not None
        and resume_session_id
        and needs_clarification_followup(
            agent=agent_result,
            diff_patch=diff_patch,
            stats=stats,
            final_message=final_msg,
            patterns=clarification_patterns,
        )
    ):
        clarification_followup = True
        clarification_prompt_text = clarification_responder(final_msg)
        agent_result2, jsonl_text2 = agent.run(
            clarification_prompt_text,
            is_first=False,
            session_id=resume_session_id,
        )
        agent_result = merge_agent_results(agent_result, agent_result2)
        jsonl_text = jsonl_text + ("\n" if jsonl_text and jsonl_text2 else "") + jsonl_text2
        stats = git.stage_all_and_diff_stats(previous_sha, pathspec)
        diff_patch = git.capture_step_diff(previous_sha, pathspec)

    commit_message = f"{agent_kind}-exp: iteration {iteration}"
    if clarification_followup:
        commit_message += " [clarification follow-up]"
    if not agent_run_ok(agent_result):
        commit_message += (
            f" [{agent_kind} failed exit={agent_result.exit_code} "
            f"timed_out={int(agent_result.timed_out)}]"
        )

    folded = git.fold_agent_commits(previous_sha)
    if folded:
        eprint(f"[run_{iteration:03d}] folded {folded} agent commit(s) into the iteration commit")
    results = count_result_events(jsonl_text)
    if results > 1:
        # Background tasks are disabled for Claude; if a session still re-woke itself, the
        # turn holds work the prompter did not ask for. Flag it rather than hide it.
        eprint(f"[run_{iteration:03d}] WARNING: agent emitted {results} result events "
               "(session continued on its own); this turn's diff may include unrequested work")

    commit_sha = git.commit(commit_message)

    return IterationResult(
        number=iteration,
        stats=stats,
        agent=agent_result,
        commit_sha=commit_sha,
        commit_message=commit_message,
        jsonl_text=jsonl_text,
        diff_patch=diff_patch,
        clarification_prompt_text=clarification_prompt_text,
        clarification_followup=clarification_followup,
    )
