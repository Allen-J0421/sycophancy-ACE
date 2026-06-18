"""Codex CLI agent wrapper."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from experiment_runner.constants import (
    CODEX_AUTO_FLAGS,
    CODEX_REASONING_CONFIG_KEY,
    DEFAULT_TIMEOUT,
)
from experiment_runner.models import AgentRunResult
from experiment_runner.util import run_text_command


def build_codex_command(
    codex_cd: Path,
    prompt: str,
    model: str,
    *,
    is_first: bool,
    session_id: str | None = None,
    effort: str | None = None,
) -> list[str]:
    if is_first:
        cmd = ["codex", "exec", "--json", *CODEX_AUTO_FLAGS, "--cd", str(codex_cd)]
    else:
        if not session_id:
            raise RuntimeError("Missing Codex session id for resume.")
        # `codex exec resume` does not accept `--cd` in some Codex CLI versions.
        # We enforce the working directory via `subprocess.run(..., cwd=...)` instead.
        cmd = ["codex", "exec", "resume", session_id, "--json", *CODEX_AUTO_FLAGS]

    if effort:
        cmd = [*cmd, "-c", f"{CODEX_REASONING_CONFIG_KEY}={effort}"]
    cmd = [*cmd, "--model", model, prompt]
    return cmd


def parse_codex_session_id(jsonl_text: str) -> str | None:
    """
    Extract the Codex resume id from `codex exec --json` output (session fields only).

    We look for an event like:
      {"type":"session_meta","payload":{"id":"..."}}

    Some Codex versions emit:
      {"type":"thread.started","thread_id":"..."}
    """
    for raw in jsonl_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "thread.started":
            tid = obj.get("thread_id")
            if isinstance(tid, str) and tid.strip():
                return tid.strip()

        if obj.get("type") != "session_meta":
            continue

        payload = obj.get("payload")
        if isinstance(payload, dict):
            sid = payload.get("id")
            if isinstance(sid, str) and sid.strip():
                return sid.strip()
    return None


class CodexAgent:
    """Runs ``codex exec`` / ``codex exec resume`` for one working directory."""

    def __init__(
        self,
        codex_cd: Path,
        model: str,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        effort: str | None = None,
    ) -> None:
        self.codex_cd = codex_cd
        self.model = model
        self.timeout = timeout
        self.effort = effort

    def run(
        self,
        prompt: str,
        *,
        is_first: bool,
        session_id: str | None = None,
    ) -> tuple[AgentRunResult, str]:
        cmd = build_codex_command(
            self.codex_cd,
            prompt,
            self.model,
            is_first=is_first,
            session_id=session_id,
            effort=self.effort,
        )
        t0 = time.monotonic()
        try:
            proc = run_text_command(cmd, cwd=self.codex_cd, timeout=self.timeout)
            out = proc.stdout or ""
            err = proc.stderr or ""
            jsonl = "\n".join([out, err])
            sid: str | None = None
            if is_first:
                # Different Codex versions may emit JSONL to stdout, stderr, or both.
                sid = parse_codex_session_id(jsonl)
                if not sid:
                    preview: list[str] = []
                    if out.strip():
                        preview.append(
                            "stdout (first 10 lines):\n" + "\n".join(out.splitlines()[:10])
                        )
                    if err.strip():
                        preview.append(
                            "stderr (first 10 lines):\n" + "\n".join(err.splitlines()[:10])
                        )
                    detail = ("\n\n" + "\n\n".join(preview)) if preview else ""
                    raise RuntimeError(
                        "Could not parse Codex session id from `codex exec --json` output. "
                        "Try running with a longer timeout, or run `codex exec --json ...` "
                        f"manually to inspect output.{detail}"
                    )
            return (
                AgentRunResult(
                    exit_code=proc.returncode,
                    duration_s=time.monotonic() - t0,
                    timed_out=False,
                    session_id=sid,
                ),
                jsonl,
            )
        except subprocess.TimeoutExpired:
            return (
                AgentRunResult(
                    exit_code=124,
                    duration_s=time.monotonic() - t0,
                    timed_out=True,
                ),
                "",
            )
