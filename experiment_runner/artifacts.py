"""Per-run artifact writers."""

from __future__ import annotations

from pathlib import Path


def write_step_artifacts(
    artifacts_dir: Path,
    run_number: int,
    *,
    diff_patch: str,
    jsonl_text: str,
    agent_jsonl_name: str = "codex.jsonl",
    prompt_text: str = "",
    prompter_jsonl: str = "",
) -> None:
    run_dir = artifacts_dir / f"run_{run_number:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "diff.patch").write_text(diff_patch, encoding="utf-8")
    (run_dir / agent_jsonl_name).write_text(jsonl_text, encoding="utf-8")
    if prompt_text:
        (run_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    if prompter_jsonl:
        (run_dir / "prompter.jsonl").write_text(prompter_jsonl, encoding="utf-8")
