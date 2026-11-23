"""Truncated completions: detection, one bounded escalation, and loud fallback (#69)."""

import json
import os

import pytest
import requests

from alphasift.llm_client import (
    TRUNCATION_RETRY_MAX_TOKENS,
    TRUNCATION_RETRY_MIN_TOKENS,
    LLMAttempt,
    LLMClientError,
    complete,
    truncation_retry_max_tokens,
)
from alphasift.models import Pick
from alphasift.ranker import _call_llm, _call_llm_with_metadata, rank_candidates_with_metadata

_ATTEMPT = LLMAttempt("https://relay.example.test/v1", "deepseek-v4-flash", "k")
_MESSAGES = [{"role": "user", "content": "rank"}]
_PARTIAL_JSON = '{"ranked": [{"code": "AA'


@pytest.fixture(autouse=True)
def isolated_llm_env(monkeypatch):
    prefixes = ("LLM_", "LITELLM_", "OPENAI_", "GEMINI_", "DEEPSEEK_", "OPENROUTER_")
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
    ],
    ids=["empty", "null", "blank-uppercase", "partial-json", "reasoning-only-stop", "reasoning-only-no-reason"],
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
    ],
    ids=["empty-stop", "null-stop", "blank-reasoning", "non-text-length"],
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


def test_truncated_error_reports_the_budget_actually_sent(monkeypatch):
    # Thinking models get their budget raised to 8192 inside complete(); the error must
    # report that value, or the escalation would retry with a budget already tried.
    attempt = LLMAttempt("https://api.openai.com/v1", "gpt-5-mini", "k")
    monkeypatch.setattr("alphasift.llm_client.requests.post", _Recorder([_response({"content": ""}, "length")]))

    with pytest.raises(LLMClientError) as info:
        complete(attempt, messages=_MESSAGES, temperature=0.2, max_tokens=2048, reasoning_effort="low")

    assert info.value.max_tokens == 8192


def test_truncated_error_without_a_sent_budget(monkeypatch):
    monkeypatch.setattr("alphasift.llm_client.requests.post", _Recorder([_response({"content": ""}, "length")]))

    with pytest.raises(LLMClientError) as info:
        complete(_ATTEMPT, messages=_MESSAGES, temperature=0.2)

    assert info.value.truncated is True
    assert info.value.max_tokens is None
    assert "max_tokens=unset" in str(info.value)


# --- the escalation budget -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("sent", "expected"),
    [
        (None, None),
        (0, None),
        (-1, None),
        (1, TRUNCATION_RETRY_MIN_TOKENS),
        (2048, 8192),
        (4096, 8192),
        (8192, 16384),
        (16384, 32768),
        (20000, TRUNCATION_RETRY_MAX_TOKENS),
        (TRUNCATION_RETRY_MAX_TOKENS, None),
        (40000, None),
    ],
)
def test_truncation_retry_budget_is_floored_doubled_and_capped(sent, expected):
    assert truncation_retry_max_tokens(sent) == expected


# --- _call_llm_with_metadata(): one retry on the same attempt, then fallbacks ---------------


def _call(**kwargs):
    defaults = {"fallback_models": [], "json_mode": False}
    defaults.update(kwargs)
    return _call_llm_with_metadata("prompt", "k", "deepseek/deepseek-chat", "", **defaults)


def test_truncation_is_retried_once_on_the_same_attempt_with_more_room(monkeypatch):
    post = _Recorder([_response({"content": ""}, "length"), _response({"content": "ok"})])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    assert _call(max_tokens=2048) == ("ok", "deepseek-chat")
    assert post.models == ["deepseek-chat", "deepseek-chat"]
    assert post.budgets == [2048, 8192]


def test_retry_keeps_json_mode(monkeypatch):
    post = _Recorder([_response({"content": ""}, "length"), _response({"content": "{}"})])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    _call(max_tokens=2048, json_mode=True)

    assert [payload.get("response_format") for payload in post.payloads] == [{"type": "json_object"}] * 2


def test_second_truncation_moves_on_to_fallback_with_the_original_budget(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    post = _Recorder(
        [
            _response({"content": ""}, "length"),
            _response({"content": ""}, "length"),
            _response({"content": "fallback-ok"}),
        ]
    )
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    assert _call(max_tokens=2048, fallback_models=["deepseek/deepseek-reasoner"]) == (
        "fallback-ok",
        "deepseek-reasoner",
    )
    assert post.models == ["deepseek-chat", "deepseek-chat", "deepseek-reasoner"]
    assert post.budgets == [2048, 8192, 2048]


def test_no_retry_when_the_budget_is_already_at_the_ceiling(monkeypatch):
    post = _Recorder([_response({"content": ""}, "length")])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    with pytest.raises(LLMClientError) as info:
        _call(max_tokens=TRUNCATION_RETRY_MAX_TOKENS)

    assert info.value.truncated is True
    assert post.budgets == [TRUNCATION_RETRY_MAX_TOKENS]


def test_non_truncated_errors_are_not_retried(monkeypatch):
    post = _Recorder([_response({"content": ""}, "stop")])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    with pytest.raises(LLMClientError, match="Empty LLM chat completion content"):
        _call(max_tokens=2048)

    assert len(post.payloads) == 1


def test_retry_timeout_falls_through_to_fallback(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    post = _Recorder(
        [
            _response({"content": ""}, "length"),
            requests.Timeout("read timed out"),
            _response({"content": "fallback-ok"}),
        ]
    )
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    assert _call(max_tokens=2048, fallback_models=["deepseek/deepseek-reasoner"])[0] == "fallback-ok"
    assert post.models == ["deepseek-chat", "deepseek-chat", "deepseek-reasoner"]


def test_validator_sees_the_escalated_answer(monkeypatch):
    post = _Recorder([_response({"content": '{"head'}, "length"), _response({"content": '{"headline": "ok"}'})])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    text, _ = _call(max_tokens=4096, validator=json.loads)

    assert json.loads(text) == {"headline": "ok"}
    assert post.budgets == [4096, 8192]


def test_call_llm_wrapper_inherits_the_retry(monkeypatch):
    post = _Recorder([_response({"content": ""}, "length"), _response({"content": "ok"})])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    assert _call_llm("prompt", "k", "deepseek/deepseek-chat", "", json_mode=False, max_tokens=2048) == "ok"
    assert post.budgets == [2048, 8192]


# --- rank_candidates_with_metadata(): salvage and an explicit degradation note -------------


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
    post = _Recorder([_response({"content": ""}, "length"), _response({"content": ""}, "length")])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)
    degradation: list[str] = []

    result = _rank(degradation, max_tokens=2048)

    assert result.ranked is False
    assert [pick.code for pick in result.picks] == ["AAPL", "MSFT"]
    assert "truncated" in result.errors[0]
    notes = [note for note in degradation if "truncated" in note]
    assert len(notes) == 1
    assert "finish_reason=length" in notes[0]
    assert "max_tokens=8192" in notes[0]
    assert "LLM_MAX_TOKENS" in notes[0]
    assert "partial answer" not in notes[0]


def test_truncation_is_noted_even_when_a_fallback_model_rescues_the_run(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    answer = json.dumps({"ranked": [{"code": "MSFT", "llm_score": 95}, {"code": "AAPL", "llm_score": 60}]})
    post = _Recorder(
        [
            _response({"content": '{"ranked": [{"code": "MS'}, "length"),
            _response({"content": '{"ranked": [{"code": "MS'}, "length"),
            _response({"content": answer}),
        ]
    )
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)
    degradation: list[str] = []

    result = _rank(degradation, max_tokens=2048, fallback_models=["deepseek/deepseek-reasoner"])

    assert result.ranked is True
    assert post.models == ["deepseek-chat", "deepseek-chat", "deepseek-reasoner"]
    notes = [note for note in degradation if "truncated" in note]
    assert len(notes) == 1
    assert "partial answer discarded (24 chars)" in notes[0]


def test_recovered_retry_adds_no_degradation(monkeypatch):
    answer = json.dumps({"ranked": [{"code": "MSFT", "llm_score": 95}, {"code": "AAPL", "llm_score": 60}]})
    post = _Recorder([_response({"content": ""}, "length"), _response({"content": answer})])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)
    degradation: list[str] = []

    result = _rank(degradation, max_tokens=2048)

    assert result.ranked is True
    assert not [note for note in degradation if "truncated" in note]


def test_truncation_without_a_degradation_sink_still_falls_back(monkeypatch):
    post = _Recorder([_response({"content": ""}, "length"), _response({"content": ""}, "length")])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    result = _rank(None, max_tokens=2048)

    assert result.ranked is False
    assert "truncated" in result.errors[0]
