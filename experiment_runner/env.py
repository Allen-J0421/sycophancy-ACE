"""Environment and prompt.env loading."""

from __future__ import annotations

import os
import re
from pathlib import Path

from experiment_runner.constants import (
    DEFAULT_PROMPTER_PROFILE,
    PROMPTER_PROFILES,
)
from experiment_runner.limit_detect import LimitDetectConfig
from experiment_runner.models import ClarificationPatterns, PrompterConfig
from experiment_runner.util import non_empty_string, script_dir

AGENT_FIXED_PROMPT_KEY = "AGENT_FIXED_PROMPT"


def prompt_file_candidates() -> list[Path]:
    # config/ is the canonical home; the two root paths are kept for back-compat.
    # *_FILE keys in prompt.env resolve relative to wherever prompt.env is found,
    # so the pattern .txt files travel with it into config/ with no edits.
    return [
        Path.cwd() / "prompt.env",
        script_dir() / "config" / "prompt.env",
        script_dir() / "prompt.env",
    ]


def dotenv_file_candidates() -> list[Path]:
    return [
        Path.cwd() / ".env",
        script_dir() / "config" / ".env",
        script_dir() / ".env",
    ]


def parse_env_line(raw: str) -> tuple[str, str] | None:
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None
    return key, value.strip().strip('"').strip("'").strip()


def load_dotenv_file() -> None:
    """Load KEY=VALUE pairs from ``.env`` without overriding existing env vars."""
    for path in dotenv_file_candidates():
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            parsed = parse_env_line(raw)
            if not parsed:
                continue
            key, value = parsed
            if key not in os.environ:
                os.environ[key] = value


def load_prompt_env_values() -> dict[str, str]:
    """Load AGENT_FIXED_PROMPT from prompt.env (env var takes precedence over file)."""
    values: dict[str, str] = {}
    env_val = non_empty_string(os.environ.get(AGENT_FIXED_PROMPT_KEY))
    if env_val:
        values[AGENT_FIXED_PROMPT_KEY] = env_val

    for path in prompt_file_candidates():
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            parsed = parse_env_line(raw)
            if not parsed:
                continue
            key, value = parsed
            if key == AGENT_FIXED_PROMPT_KEY and key not in values and value:
                values[key] = value
    return values


def load_prompt_env_entries() -> tuple[dict[str, str], Path | None]:
    """Load all single-line KEY=VALUE pairs from the first found prompt.env."""
    for path in prompt_file_candidates():
        if not path.is_file():
            continue
        found: dict[str, str] = {}
        for raw in path.read_text(encoding="utf-8").splitlines():
            parsed = parse_env_line(raw)
            if not parsed:
                continue
            key, value = parsed
            if value:
                found[key] = value
        return found, path
    return {}, None


def resolve_prompt_path(raw_path: str, *, prompt_env: Path | None) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_file():
        return path.resolve()
    if prompt_env is not None:
        candidate = (prompt_env.parent / path).resolve()
        if candidate.is_file():
            return candidate
    candidate = (Path.cwd() / path).resolve()
    if candidate.is_file():
        return candidate
    raise SystemExit(f"Prompt file not found: {raw_path}")


def load_prompt_text(*, inline: str | None, file_key: str, entries: dict[str, str], prompt_env: Path | None) -> str:
    file_path = entries.get(file_key)
    if file_path:
        path = resolve_prompt_path(file_path, prompt_env=prompt_env)
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
        raise SystemExit(f"{file_key} points to an empty file: {path}")

    if inline:
        return inline

    raise SystemExit(f"Missing inline value or {file_key} in prompt.env (required when using --prompter).")


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def load_regex_patterns_file(path: Path) -> tuple[re.Pattern[str], ...]:
    patterns: list[re.Pattern[str]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            patterns.append(re.compile(line, re.I | re.M))
        except re.error as exc:
            raise SystemExit(f"Invalid regex in {path} line {lineno}: {exc}") from exc
    if not patterns:
        raise SystemExit(f"Pattern file is empty: {path}")
    return tuple(patterns)


def load_clarification_patterns() -> ClarificationPatterns:
    entries, prompt_env = load_prompt_env_entries()
    refusal_path = resolve_prompt_path(
        entries.get("CLARIFICATION_REFUSAL_PATTERNS_FILE", "clarification_refusal_patterns.txt"),
        prompt_env=prompt_env,
    )
    signal_path = resolve_prompt_path(
        entries.get("CLARIFICATION_SIGNAL_PATTERNS_FILE", "clarification_signal_patterns.txt"),
        prompt_env=prompt_env,
    )
    return ClarificationPatterns(
        refusal_blockers=load_regex_patterns_file(refusal_path),
        clarification_signals=load_regex_patterns_file(signal_path),
        require_question_mark=_parse_bool(
            entries.get("CLARIFICATION_REQUIRE_QUESTION_MARK"),
            default=True,
        ),
    )


def load_limit_detect_config() -> LimitDetectConfig:
    """Load provider-limit detection knobs from prompt.env (all optional, sensible defaults)."""
    entries, prompt_env = load_prompt_env_entries()

    def _patterns(file_key: str) -> tuple:
        raw_path = entries.get(file_key)
        if not raw_path:
            return ()
        return load_regex_patterns_file(resolve_prompt_path(raw_path, prompt_env=prompt_env))

    return LimitDetectConfig(
        enabled=_parse_bool(entries.get("LIMIT_DETECT_ENABLED"), default=True),
        claude_patterns=_patterns("LIMIT_CLAUDE_PATTERNS_FILE"),
        codex_patterns=_patterns("LIMIT_CODEX_PATTERNS_FILE"),
        gemini_surface=_parse_bool(entries.get("LIMIT_GEMINI_SURFACE"), default=False),
        gemini_surface_503=_parse_bool(entries.get("LIMIT_GEMINI_SURFACE_503"), default=False),
    )


def load_clarification_nudge(entries: dict[str, str], *, prompt_env: Path | None) -> str:
    inline = entries.get("PROMPTER_CLARIFICATION_NUDGE")
    if inline:
        return inline
    file_key = "PROMPTER_CLARIFICATION_NUDGE_FILE"
    file_path = entries.get(file_key)
    if file_path:
        path = resolve_prompt_path(file_path, prompt_env=prompt_env)
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
        raise SystemExit(f"{file_key} points to an empty file: {path}")
    return "The coding agent asked for clarification above."


def resolve_prompter_profile(profile: str | None) -> str:
    """Normalize and validate a prompter profile name."""
    name = (profile or DEFAULT_PROMPTER_PROFILE).strip().lower()
    if name not in PROMPTER_PROFILES:
        valid = ", ".join(sorted(PROMPTER_PROFILES))
        raise SystemExit(f"Unknown prompter profile {profile!r}; choose one of: {valid}")
    return name


def resolve_prompter_system_prompt_file(
    entries: dict[str, str],
    *,
    profile: str | None = None,
) -> str | None:
    """Return PROMPTER_SYSTEM_PROMPT_FILE path, or map PROMPTER_PROFILE to a built-in file."""
    explicit = entries.get("PROMPTER_SYSTEM_PROMPT_FILE")
    if explicit:
        return explicit
    profile_name = resolve_prompter_profile(profile or entries.get("PROMPTER_PROFILE"))
    return PROMPTER_PROFILES[profile_name]


def load_prompter_prompts_from_file(
    *,
    profile: str | None = None,
    system_prompt_file: str | None = None,
) -> tuple[str, str, str, str]:
    """Load prompter prompts from prompt.env. Returns (system_prompt, nudge, clarification_nudge, profile).

    An explicit ``system_prompt_file`` (e.g. an ablation cell) overrides both
    ``--prompter-profile`` and the profile resolved from prompt.env; the returned
    profile label is then ``"custom"``.
    """
    entries, prompt_env = load_prompt_env_entries()

    if system_prompt_file:
        profile_name = "custom"
        resolved_file = system_prompt_file
    else:
        profile_name = resolve_prompter_profile(profile or entries.get("PROMPTER_PROFILE"))
        resolved_file = resolve_prompter_system_prompt_file(entries, profile=profile_name)
    entries_with_file = dict(entries)
    if resolved_file:
        entries_with_file["PROMPTER_SYSTEM_PROMPT_FILE"] = resolved_file

    system_prompt = load_prompt_text(
        inline=None if system_prompt_file else entries.get("PROMPTER_SYSTEM_PROMPT"),
        file_key="PROMPTER_SYSTEM_PROMPT_FILE",
        entries=entries_with_file,
        prompt_env=prompt_env,
    )
    nudge = load_prompt_text(
        inline=entries.get("PROMPTER_NUDGE"),
        file_key="PROMPTER_NUDGE_FILE",
        entries=entries,
        prompt_env=prompt_env,
    )
    clarification_nudge = load_clarification_nudge(entries, prompt_env=prompt_env)
    return system_prompt, nudge, clarification_nudge, profile_name


def prompt_from_env_line(raw: str) -> str | None:
    parsed = parse_env_line(raw)
    if not parsed or parsed[0] != AGENT_FIXED_PROMPT_KEY:
        return None
    return parsed[1] or None


def load_prompt_file(path: Path) -> str | None:
    if not path.exists():
        return None

    for raw in path.read_text(encoding="utf-8").splitlines():
        prompt = prompt_from_env_line(raw)
        if prompt:
            return prompt
    return None


def load_prompt() -> str:
    prompt = non_empty_string(os.environ.get(AGENT_FIXED_PROMPT_KEY))
    if prompt:
        return prompt

    values = load_prompt_env_values()
    prompt = values.get(AGENT_FIXED_PROMPT_KEY)
    if prompt:
        return prompt

    raise SystemExit(
        f"Missing {AGENT_FIXED_PROMPT_KEY} "
        f"(set it in prompt.env or export {AGENT_FIXED_PROMPT_KEY})."
    )


def require_env_var(name: str) -> str:
    value = non_empty_string(os.environ.get(name))
    if not value:
        raise SystemExit(
            f"Missing {name} (set it in .env or export {name}) when using --prompter."
        )
    return value


def load_prompter_config(
    *,
    fallback_prompt: str,
    profile: str | None = None,
    system_prompt_file: str | None = None,
) -> PrompterConfig:
    load_dotenv_file()
    system_prompt, nudge, clarification_nudge, profile_name = load_prompter_prompts_from_file(
        profile=profile,
        system_prompt_file=system_prompt_file,
    )

    api_key = require_env_var("GEMINI_API_KEY")
    model = require_env_var("PROMPTER_MODEL")
    return PrompterConfig(
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        nudge=nudge,
        fallback_prompt=fallback_prompt,
        clarification_nudge=clarification_nudge,
        profile=profile_name,
    )
