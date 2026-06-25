#!/usr/bin/env python3
"""Minimal coding-agent experiment runner (cumulative mode).

Set a fixed prompt in `config/prompt.env` as `AGENT_FIXED_PROMPT=...` (or export AGENT_FIXED_PROMPT).

Optional ``--prompter`` mode uses a Gemini user agent (``GEMINI_API_KEY`` and
``PROMPTER_MODEL`` in ``.env``; ``PROMPTER_SYSTEM_PROMPT`` and ``PROMPTER_NUDGE`` in
``config/prompt.env``; requires ``google-genai``) to generate a vague refactoring request each turn;
the coding agent still runs in one session. Prompter artifacts:
``logs/<stamp>-<user-agent>_<coding-agent>_prompt.txt`` (all turns, sibling of the ``-log.csv``),
``run_NNN/prompter.jsonl``.

The coding CLI is chosen from ``--model``: names starting with ``claude`` use Claude;
all other models use Codex.

Implementation lives in the ``experiment_runner`` package.

Each iteration:
- runs the selected coding agent on the target codebase
- computes total line changes via `git diff --cached --numstat <prev_sha>`
- appends one row to `./result/<target_repo>/logs/<stamp>-<model>-log.csv`
- writes per-step artifacts under `./result/<target_repo>/<stamp>-<model>/run_NNN/`.

Exit codes: 0 ok, 1 partial (some iterations failed; CSV still written), 2 setup error,
3 provider-limit-blocked (a Claude/Codex/Gemini usage limit was detected mid-run; a
`<exp>/.limit_block.json` marker is written so the orchestrator can pause until reset).
"""

from __future__ import annotations

from experiment_runner.config import (
    build_experiment_config,
    parse_args,
    require_tools,
)
from experiment_runner.corruption_log import (
    REASON_AGENT_FAILURE,
    REASON_PROVIDER_LIMIT,
    record_corrupt_branch,
)
from experiment_runner.experiment import ExperimentRunner
from experiment_runner.limit_detect import ProviderLimitError
from experiment_runner.limit_marker import stderr_marker_line, write_limit_marker
from experiment_runner.util import eprint


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not require_tools("git", args.agent):
        return 2

    try:
        config = build_experiment_config(args)
        runner = ExperimentRunner.from_config(config)
        agent_failures = runner.write_log()
    except ProviderLimitError as exc:
        # Provider usage limit hit mid-experiment. Record a marker (with the partial-output
        # paths to discard) and exit 3 so the orchestrator pauses until reset and re-runs.
        # Note: ProviderLimitError is a RuntimeError, so this must precede the clause below.
        exp_dir = config.results_csv.parent.parent
        write_limit_marker(
            exc.hit,
            exp_dir=exp_dir,
            partial_csv=config.results_csv,
            artifacts_dir=config.artifacts_dir,
        )
        # This experiment branch is discarded (the run is re-run fresh after reset); log it
        # for the manual clean_corrupted_branches.py review/cleanup step.
        record_corrupt_branch(
            reason=REASON_PROVIDER_LIMIT,
            detail=exc.hit.raw,
            config=config,
            provider=exc.hit.provider,
        )
        eprint(stderr_marker_line(exc.hit))
        eprint(f"error: provider limit ({exc.hit.provider}/{exc.hit.kind}); pausing for reset.")
        return 3
    except (FileNotFoundError, RuntimeError) as exc:
        eprint(f"error: {exc}")
        return 2

    if agent_failures:
        # A wholesale-dead run (every iteration failed — usually an agent usage/connection
        # problem) leaves a corrupt branch; log it for manual cleanup. Partial runs are kept.
        if agent_failures >= config.iterations:
            record_corrupt_branch(
                reason=REASON_AGENT_FAILURE,
                detail=f"{agent_failures}/{config.iterations} iterations failed "
                       f"({args.agent} agent did not exit successfully)",
                config=config,
                provider=args.agent,
            )
        eprint(
            f"error: {agent_failures} iteration(s) failed: "
            f"{args.agent} did not exit successfully."
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
