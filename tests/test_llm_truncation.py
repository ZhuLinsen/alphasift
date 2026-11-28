"""Truncated completions: detection, strict ceiling (no auto-escalation), and loud fallback (#69)."""

import json
import os

import pytest
import requests

from alphasift.llm_client import (
    DEFAULT_LLM_MAX_TOKENS,
    LLMAttempt,
    LLMClientError,
    complete,
)
from alphasift.models import Pick
from alphasift.ranker import _call_llm, _call_llm_with_metadata, rank_candidates_with_metadata

_ATTEMPT = LLMAttempt("https://relay.example.test/v1", "deepseek-v4-flash", "k")
_MESSAGES = [{"role": "user", "content": "rank"}]
_PARTIAL_JSON = '{"ranked": [{"code": "AA'


@pytest.fixture(autouse=True)
def isolated_llm_env(monkeypatch):
    prefixes = ("LLM_", "OPENAI_", "GEMINI_", "DEEPSEEK_", "OPENROUTER_")
    for name in os.environ.copy():
        if name.startswith(prefixes):
            monkeypatch.delenv(name)
    monkeypatch.setattr("alphasift.config._load_env_file", lambda: None)


def _response(message: dict, finish_reason: str | None = "stop", status: int = 200) -> requests.Response:
    choice: dict = {"message": message}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps({"choices": [choice]}).encode()
    return response


class _Recorder:
    """Stand-in for requests.post that replays responses and records payloads."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.payloads: list[dict] = []

    def __call__(self, url, *, headers, json, timeout, allow_redirects):  # noqa: A002
        self.payloads.append(json)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def budgets(self) -> list:
        return [payload.get("max_tokens") for payload in self.payloads]

    @property
    def models(self) -> list:
        return [payload["model"] for payload in self.payloads]


# --- complete(): which 2xx shapes count as truncated -------------------------------------


@pytest.mark.parametrize(
    ("message", "finish_reason", "partial"),
    [
        ({"content": ""}, "length", ""),
        ({"content": None}, "length", ""),
        ({"content": "   "}, "LENGTH", ""),
        ({"content": _PARTIAL_JSON}, "length", _PARTIAL_JSON),
        ({"content": "", "reasoning_content": "thinking..."}, "stop", ""),
        ({"content": None, "reasoning_content": "thinking..."}, None, ""),
        ({"reasoning_content": "thinking..."}, "length", ""),
        ({"reasoning_content": "thinking..."}, "stop", ""),
    ],
    ids=[
        "empty",
        "null",
        "blank-uppercase",
        "partial-json",
        "reasoning-only-stop",
        "reasoning-only-no-reason",
        "omitted-content-length",
        "omitted-content-reasoning-stop",
    ],
)
def test_truncated_shapes_raise_tagged_error(monkeypatch, message, finish_reason, partial):
    monkeypatch.setattr("alphasift.llm_client.requests.post", _Recorder([_response(message, finish_reason)]))

    with pytest.raises(LLMClientError) as info:
        complete(_ATTEMPT, messages=_MESSAGES, temperature=0.2, max_tokens=2048)

    assert info.value.truncated is True
    assert info.value.partial_content == partial
    assert info.value.max_tokens == 2048
    assert "truncated" in str(info.value)


@pytest.mark.parametrize(
    ("message", "finish_reason", "expected_error"),
    [
        ({"content": ""}, "stop", "Empty LLM chat completion content"),
        ({"content": None}, "stop", "Invalid LLM assistant text"),
        ({"content": "", "reasoning_content": "  "}, "stop", "Empty LLM chat completion content"),
        ({"content": ["not", "text"]}, "length", "Invalid LLM assistant text"),
        ({}, "stop", "Invalid LLM chat completion response"),
    ],
    ids=["empty-stop", "null-stop", "blank-reasoning", "non-text-length", "empty-message"],
)
def test_non_truncated_failures_keep_their_existing_errors(monkeypatch, message, finish_reason, expected_error):
    monkeypatch.setattr("alphasift.llm_client.requests.post", _Recorder([_response(message, finish_reason)]))

    with pytest.raises(LLMClientError, match=expected_error) as info:
        complete(_ATTEMPT, messages=_MESSAGES, temperature=0.2, max_tokens=2048)

    assert info.value.truncated is False


@pytest.mark.parametrize("finish_reason", ["stop", None, "content_filter"])
def test_complete_answers_are_returned_unchanged(monkeypatch, finish_reason):
    message = {"content": "ok", "reasoning_content": "thinking..."}
    monkeypatch.setattr("alphasift.llm_client.requests.post", _Recorder([_response(message, finish_reason)]))

    assert complete(_ATTEMPT, messages=_MESSAGES, temperature=0.2, max_tokens=2048) == "ok"


def test_complete_respects_configured_ceiling_even_for_thinking_models(monkeypatch):
    attempt = LLMAttempt("https://api.openai.com/v1", "gpt-5-mini", "k")
    post = _Recorder([_response({"content": ""}, "length")])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    with pytest.raises(LLMClientError) as info:
        complete(attempt, messages=_MESSAGES, temperature=0.2, max_tokens=2048, reasoning_effort="low")

    assert post.budgets == [2048]
    assert info.value.max_tokens == 2048


def test_truncated_error_without_a_sent_budget(monkeypatch):
    monkeypatch.setattr("alphasift.llm_client.requests.post", _Recorder([_response({"content": ""}, "length")]))

    with pytest.raises(LLMClientError) as info:
        complete(_ATTEMPT, messages=_MESSAGES, temperature=0.2)

    assert info.value.truncated is True
    assert info.value.max_tokens is None
    assert "max_tokens=unset" in str(info.value)


# --- _call_llm_with_metadata(): no auto-escalation; fallbacks keep strict ceiling ----------


def _call(**kwargs):
    defaults = {"fallback_models": [], "json_mode": False}
    defaults.update(kwargs)
    return _call_llm_with_metadata("prompt", "k", "deepseek/deepseek-chat", "", **defaults)


def test_truncation_does_not_auto_escalate_on_the_same_attempt(monkeypatch):
    post = _Recorder([_response({"content": ""}, "length")])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    with pytest.raises(LLMClientError) as info:
        _call(max_tokens=2048)

    assert info.value.truncated is True
    assert post.models == ["deepseek-chat"]
    assert post.budgets == [2048]


def test_truncation_moves_to_fallback_keeping_the_exact_budget(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    post = _Recorder([_response({"content": ""}, "length"), _response({"content": "fallback-ok"})])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    assert _call(max_tokens=2048, fallback_models=["deepseek/deepseek-reasoner"]) == (
        "fallback-ok",
        "deepseek-reasoner",
    )
    assert post.models == ["deepseek-chat", "deepseek-reasoner"]
    assert post.budgets == [2048, 2048]


def test_call_defaults_to_8192_max_tokens(monkeypatch):
    post = _Recorder([_response({"content": "ok"})])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    assert DEFAULT_LLM_MAX_TOKENS == 8192
    assert _call() == ("ok", "deepseek-chat")
    assert post.budgets == [8192]


def test_non_truncated_errors_are_not_retried(monkeypatch):
    post = _Recorder([_response({"content": ""}, "stop")])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    with pytest.raises(LLMClientError, match="Empty LLM chat completion content"):
        _call(max_tokens=2048)

    assert len(post.payloads) == 1


def test_call_llm_wrapper_respects_ceiling_without_escalation(monkeypatch):
    post = _Recorder([_response({"content": ""}, "length")])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    with pytest.raises(LLMClientError) as info:
        _call_llm("prompt", "k", "deepseek/deepseek-chat", "", json_mode=False, max_tokens=2048)

    assert info.value.truncated is True
    assert post.budgets == [2048]


# --- rank_candidates_with_metadata(): loud degradation note without silent escalation -----


def _picks() -> list[Pick]:
    return [
        Pick(rank=1, code="AAPL", name="Apple", screen_score=80, final_score=80),
        Pick(rank=2, code="MSFT", name="Microsoft", screen_score=70, final_score=70),
    ]


def _rank(degradation: list[str] | None, **kwargs):
    return rank_candidates_with_metadata(
        _picks(),
        "",
        "k",
        "deepseek/deepseek-chat",
        "",
        json_mode=False,
        max_retries=0,
        degradation=degradation,
        **kwargs,
    )


def test_exhausted_budget_falls_back_with_an_explicit_degradation_note(monkeypatch):
    post = _Recorder([_response({"content": ""}, "length")])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)
    degradation: list[str] = []

    result = _rank(degradation, max_tokens=2048)

    assert result.ranked is False
    assert [pick.code for pick in result.picks] == ["AAPL", "MSFT"]
    assert post.budgets == [2048]
    assert "truncated" in result.errors[0]
    notes = [note for note in degradation if "truncated" in note]
    assert len(notes) == 1
    assert "finish_reason=length" in notes[0]
    assert "max_tokens=2048" in notes[0]
    assert "LLM_MAX_TOKENS" in notes[0]
    assert "partial answer" not in notes[0]


def test_truncation_is_noted_even_when_a_fallback_model_rescues_the_run(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    answer = json.dumps({"ranked": [{"code": "MSFT", "llm_score": 95}, {"code": "AAPL", "llm_score": 60}]})
    post = _Recorder(
        [
            _response({"content": '{"ranked": [{"code": "MS'}, "length"),
            _response({"content": answer}),
        ]
    )
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)
    degradation: list[str] = []

    result = _rank(degradation, max_tokens=2048, fallback_models=["deepseek/deepseek-reasoner"])

    assert result.ranked is True
    assert post.models == ["deepseek-chat", "deepseek-reasoner"]
    assert post.budgets == [2048, 2048]
    notes = [note for note in degradation if "truncated" in note]
    assert len(notes) == 1
    assert "partial answer discarded (24 chars)" in notes[0]


def test_rank_defaults_to_8192_and_truncation_without_sink_still_falls_back(monkeypatch):
    post = _Recorder([_response({"content": ""}, "length")])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    result = _rank(None)

    assert result.ranked is False
    assert post.budgets == [8192]
    assert "truncated" in result.errors[0]
