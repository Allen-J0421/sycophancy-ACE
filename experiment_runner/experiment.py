"""Experiment orchestration: multi-turn loop, CSV log, artifacts."""

from __future__ import annotations

import csv
from collections.abc import Iterator

from experiment_runner.artifacts import write_step_artifacts
from experiment_runner.coding_agent import CodingAgent
from experiment_runner.config import build_coding_agent, build_prompt_source, eprint_setup
from experiment_runner.constants import CSV_COLUMNS, agent_jsonl_filename
from experiment_runner.git_repo import GitRepository
from experiment_runner.iteration import run_iteration
from experiment_runner.models import ExperimentConfig, IterationResult, PrompterTurnInput, agent_run_ok
from experiment_runner.prompter import extract_final_agent_message
from experiment_runner.prompt_source import PromptSource
from experiment_runner.util import eprint


class ExperimentRunner:
    """Runs a cumulative coding-agent experiment and writes CSV + per-run artifacts."""

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        git: GitRepository,
        agent: CodingAgent,
        prompt_source: PromptSource,
    ) -> None:
        self.config = config
        self.git = git
        self.agent = agent
        self.prompt_source = prompt_source

    @classmethod
    def from_config(cls, config: ExperimentConfig) -> ExperimentRunner:
        git = GitRepository(config.target.root)
        agent = build_coding_agent(config)
        prompt_source = build_prompt_source(config)
        return cls(config, git=git, agent=agent, prompt_source=prompt_source)

    def iter_results(self, initial_sha: str) -> Iterator[IterationResult]:
        prev_sha = initial_sha
        session_id: str | None = None
        last_turn_input: PrompterTurnInput | None = None
        use_prompter = self.config.prompter and self.config.prompter_config is not None

        for i in range(1, self.config.iterations + 1):
            turn = self.prompt_source.next_prompt(last_turn_input)
            result = run_iteration(
                self.git,
                self.agent,
                agent_kind=self.config.agent,
                iteration=i,
                prompt=turn.prompt,
                session_id=session_id,
                previous_sha=prev_sha,
                pathspec=self.config.target.pathspec,
            )
            result = IterationResult(
                number=result.number,
                stats=result.stats,
                agent=result.agent,
                commit_sha=result.commit_sha,
                commit_message=result.commit_message,
                jsonl_text=result.jsonl_text,
                diff_patch=result.diff_patch,
                prompt_text=turn.prompt if use_prompter else "",
                prompter_jsonl=turn.prompter_jsonl if use_prompter else "",
            )
            if i == 1:
                session_id = result.agent.session_id
            if use_prompter and result.jsonl_text:
                reply = extract_final_agent_message(result.jsonl_text) or None
                last_turn_input = PrompterTurnInput(
                    coding_reply=reply,
                    diff_patch=result.diff_patch or None,
                )
            prev_sha = result.commit_sha
            yield result

    def write_log(self) -> int:
        """Returns the number of iterations where the coding agent did not complete successfully."""
        self.config.results_csv.parent.mkdir(parents=True, exist_ok=True)
        eprint_setup(self.config)

        prev_sha = self.git.setup_branch(self.config.start_commit, self.config.branch)
        if self.config.prompter and self.config.prompter_config:
            snapshot = self.git.snapshot_at_commit(prev_sha, self.config.target.pathspec)
            self.prompt_source.prepare(codebase_snapshot=snapshot)
        agent_failures = 0
        jsonl_name = agent_jsonl_filename(self.config.agent)

        with self.config.results_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_COLUMNS)

            for result in self.iter_results(prev_sha):
                writer.writerow(
                    result.as_csv_row(
                        model=self.config.effective_model,
                        branch=self.config.branch,
                    )
                )
                write_step_artifacts(
                    self.config.artifacts_dir,
                    result.number,
                    diff_patch=result.diff_patch,
                    jsonl_text=result.jsonl_text,
                    agent_jsonl_name=jsonl_name,
                    prompt_text=result.prompt_text,
                    prompter_jsonl=result.prompter_jsonl,
                )
                self._eprint_iteration_result(result)
                if not agent_run_ok(result.agent):
                    agent_failures += 1

        eprint(f"[done] Wrote: {self.config.results_csv}")
        eprint(f"[done] Artifacts: {self.config.artifacts_dir}/")
        return agent_failures

    @staticmethod
    def _eprint_iteration_result(result: IterationResult) -> None:
        a = result.agent
        if not agent_run_ok(a):
            eprint(
                f"[run_{result.number:03d}] ERROR: Coding agent did not complete successfully "
                f"(exit={a.exit_code}, timed_out={int(a.timed_out)}). "
                "CSV line-change totals reflect the staged diff at commit time and may be partial."
            )
            return
        eprint(
            f"[run_{result.number:03d}] "
            f"+{result.stats.lines_added} -{result.stats.lines_deleted} "
            f"total={result.stats.lines_total} exit={a.exit_code}"
        )
