"""Tests for Gemini prompter retry/backoff on transient 5xx errors (before prompt fallback)."""

from __future__ import annotations

from unittest.mock import MagicMock

from google.genai.errors import APIError

from experiment_runner.limit_detect import LimitDetectConfig, detect_gemini_limit
from experiment_runner.models import PrompterConfig
from experiment_runner.prompter import GeminiPrompter


def _config(**kw) -> PrompterConfig:
    return PrompterConfig(api_key="test", model="test-model", system_prompt="system",
                          nudge="nudge", fallback_prompt="refactor", **kw)


def _response(text: str) -> MagicMock:
    response = MagicMock()
    response.candidates = []
    response.text = text
    response.usage_metadata = None
    response.prompt_feedback = None
    response.response_id = "r1"
    response.model_version = "v1"
    response.model_dump.return_value = {}
    return response


def _api_error(code: int) -> APIError:
    return APIError(code, {"error": {"code": code, "message": "high demand", "status": "UNAVAILABLE"}})


def _prompter(chat: MagicMock, **cfg) -> tuple[GeminiPrompter, list[float]]:
    slept: list[float] = []
    prompter = GeminiPrompter(_config(**cfg), _sleep=slept.append)
    chat.get_history.return_value = []
    prompter._chat = chat
    return prompter, slept


def test_transient_503_is_retried_then_succeeds():
    chat = MagicMock()
    chat.send_message.side_effect = [_api_error(503), _api_error(503), _response("Extract a helper.")]
    prompter, slept = _prompter(chat, retry_attempts=4, retry_backoff_s=15)

    assert prompter.next_request() == "Extract a helper."
    assert chat.send_message.call_count == 3
    assert slept == [15, 30]  # exponential backoff
    events = [e["event"] for e in prompter.events]
    assert events.count("retry") == 2 and "error" not in events
    # A recovered 503 must not look like a limit to Gemini limit detection.
    jsonl = prompter.events_jsonl_for_turn(1)
    assert detect_gemini_limit(jsonl, LimitDetectConfig(gemini_surface_503=True)) is None


def test_persistent_503_falls_back_after_retries():
    chat = MagicMock()
    chat.send_message.side_effect = _api_error(503)
    prompter, slept = _prompter(chat, retry_attempts=3, retry_backoff_s=10)

    assert prompter.next_request() == "refactor"
    assert chat.send_message.call_count == 4  # 1 try + 3 retries
    assert slept == [10, 20, 40]
    assert [e["event"] for e in prompter.events].count("error") == 1


def test_backoff_is_capped():
    chat = MagicMock()
    chat.send_message.side_effect = _api_error(503)
    prompter, slept = _prompter(chat, retry_attempts=6, retry_backoff_s=100)
    prompter.next_request()
    assert max(slept) == 300


def test_quota_429_is_not_retried():
    chat = MagicMock()
    chat.send_message.side_effect = _api_error(429)
    prompter, slept = _prompter(chat, retry_attempts=4)

    assert prompter.next_request() == "refactor"
    assert chat.send_message.call_count == 1 and slept == []


def test_zero_attempts_keeps_old_behaviour():
    chat = MagicMock()
    chat.send_message.side_effect = _api_error(503)
    prompter, slept = _prompter(chat, retry_attempts=0)
    assert prompter.next_request() == "refactor"
    assert chat.send_message.call_count == 1 and slept == []


def test_clarification_reply_is_retried_too():
    chat = MagicMock()
    chat.send_message.side_effect = [_api_error(503), _response("Focus on the parser.")]
    prompter, slept = _prompter(chat, retry_attempts=2, retry_backoff_s=5)
    prompter.turn = 1

    assert prompter.respond_to_clarification("Which module?") == "Focus on the parser."
    assert slept == [5]
    retry = next(e for e in prompter.events if e["event"] == "retry")
    assert retry["payload"]["phase"] == "clarification"


def test_load_prompter_config_reads_retry_keys(monkeypatch):
    from experiment_runner import env
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("PROMPTER_MODEL", "m")
    monkeypatch.setenv("PROMPTER_RETRY_ATTEMPTS", "6")
    monkeypatch.setattr(env, "load_prompter_prompts_from_file",
                        lambda **kw: ("sys", "nudge", "clar", "novice"))
    monkeypatch.setattr(env, "load_prompt_env_entries",
                        lambda: ({"PROMPTER_RETRY_ATTEMPTS": "2",
                                  "PROMPTER_RETRY_BACKOFF_SECONDS": "7.5"}, None))
    cfg = env.load_prompter_config(fallback_prompt="refactor")
    assert cfg.retry_attempts == 6       # env var wins over prompt.env
    assert cfg.retry_backoff_s == 7.5


def test_network_errors_are_retried():
    import httpx
    chat = MagicMock()
    chat.send_message.side_effect = [
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
        BrokenPipeError(32, "Broken pipe"),
        _response("Rename the parser."),
    ]
    prompter, slept = _prompter(chat, retry_attempts=4, retry_backoff_s=15)
    assert prompter.next_request() == "Rename the parser."
    assert slept == [15, 30]
    retries = [e for e in prompter.events if e["event"] == "retry"]
    assert [r["payload"]["status_code"] for r in retries] == [None, None]
    assert "error" not in [e["event"] for e in prompter.events]


def test_persistent_network_error_falls_back():
    import httpx
    chat = MagicMock()
    chat.send_message.side_effect = httpx.ConnectError("connection refused")
    prompter, slept = _prompter(chat, retry_attempts=2, retry_backoff_s=1)
    assert prompter.next_request() == "refactor"
    assert chat.send_message.call_count == 3 and slept == [1, 2]


def test_non_network_exception_is_not_retried():
    chat = MagicMock()
    chat.send_message.side_effect = ValueError("bad request shape")
    prompter, slept = _prompter(chat, retry_attempts=4)
    assert prompter.next_request() == "refactor"
    assert chat.send_message.call_count == 1 and slept == []
