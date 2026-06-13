#!/usr/bin/env python3
"""Minimal coding-agent experiment runner (cumulative mode).

Set a fixed prompt in `prompt.env` as `AGENT_FIXED_PROMPT=...` (or export AGENT_FIXED_PROMPT).

Optional ``--prompter`` mode uses a Gemini user agent (``GEMINI_API_KEY`` and
``PROMPTER_MODEL`` in ``.env``; ``PROMPTER_SYSTEM_PROMPT`` and ``PROMPTER_NUDGE`` in
``prompt.env``; requires ``google-genai``) to generate a vague refactoring request each turn;
the coding agent still runs in one session. Prompter artifacts:
``<stamp>-<model>/prompt.txt`` (all turns), ``run_NNN/prompter.jsonl``.

The coding CLI is chosen from ``--model``: names starting with ``claude`` use Claude;
all other models use Codex.

Implementation lives in the ``experiment_runner`` package.

Each iteration:
- runs the selected coding agent on the target codebase
- computes total line changes via `git diff --cached --numstat <prev_sha>`
- appends one row to `./result/<target_repo>/logs/<stamp>-<model>-log.csv`
- writes per-step artifacts under `./result/<target_repo>/<stamp>-<model>/run_NNN/`.
"""

from __future__ import annotations

from experiment_runner.config import (
    build_experiment_config,
    parse_args,
    require_tools,
)
from experiment_runner.experiment import ExperimentRunner
from experiment_runner.util import eprint


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not require_tools("git", args.agent):
        return 2

    try:
        config = build_experiment_config(args)
        runner = ExperimentRunner.from_config(config)
        agent_failures = runner.write_log()
    except (FileNotFoundError, RuntimeError) as exc:
        eprint(f"error: {exc}")
        return 2

    if agent_failures:
        eprint(
            f"error: {agent_failures} iteration(s) failed: "
            f"{args.agent} did not exit successfully."
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
