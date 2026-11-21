import os
from unittest.mock import Mock

import pytest
import requests

from alphasift.config import Config
from alphasift.llm_client import LLMAttempt, LLMClientError, build_attempts, complete
from alphasift.models import Pick
from alphasift.ranker import _call_llm, rank_candidates_with_metadata


@pytest.fixture(autouse=True)
def isolated_llm_env(monkeypatch):
    prefixes = (
        "LLM_",
        "LITELLM_",
        "AGENT_LITELLM_",
        "OPENAI_",
        "GEMINI_",
        "DEEPSEEK_",
        "ANTHROPIC_",
        "OLLAMA_",
        "OPENROUTER_",
        "DASHSCOPE_",
        "QWEN_",
        "ZHIPU_",
        "ZAI_",
        "MOONSHOT_",
        "AIHUBMIX_",
    )
    for name in os.environ.copy():
        if name.startswith(prefixes):
            monkeypatch.delenv(name)
    monkeypatch.setattr("alphasift.config._load_env_file", lambda: None)


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"DEEPSEEK_API_KEY": "test-key"}, [("https://api.deepseek.com", "deepseek-chat", "test-key")]),
        (
            {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "custom-gemini"},
            [("https://generativelanguage.googleapis.com/v1beta/openai", "custom-gemini", "test-key")],
        ),
        (
            {"GEMINI_API_KEYS": "key-1, key-2,,key-1", "GEMINI_API_KEY": "unused"},
            [
                ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash", "key-1"),
                ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash", "key-2"),
                ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-4-hydrogen", "key-1"),
                ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-4-hydrogen", "key-2"),
            ],
        ),
        ({"OPENAI_API_KEY": "test-key"}, [("https://api.openai.com/v1", "gpt-4o-mini", "test-key")]),
        (
            {"OPENAI_API_KEY": "test-key", "OPENAI_BASE_URL": "https://example.test/v1/", "OPENAI_MODEL": "other"},
            [("https://example.test/v1", "other", "test-key")],
        ),
        (
            {"OLLAMA_API_BASE": "http://ollama:11434/", "OLLAMA_MODEL": "qwen:8b", "OPENAI_API_KEY": "unused"},
            [("http://ollama:11434/v1", "qwen:8b", "")],
        ),
        (
            {"AGENT_LITELLM_MODEL": "ollama/qwen:8b", "OLLAMA_API_BASE": "http://ollama:11434/v1/"},
            [("http://ollama:11434/v1", "qwen:8b", "")],
        ),
        ({"AGENT_LITELLM_MODEL": "ollama/qwen:8b"}, [("http://localhost:11434/v1", "qwen:8b", "")]),
        (
            {"AIHUBMIX_KEY": "test-key", "OPENAI_API_KEY": "unused"},
            [("https://aihubmix.com/v1", "gpt-4o-mini", "test-key")],
        ),
        (
            {"AIHUBMIX_KEY": "test-key", "AIHUBMIX_BASE_URL": "https://example.test/v1", "OPENAI_API_KEY": "unused"},
            [("https://example.test/v1", "gpt-4o-mini", "test-key")],
        ),
        (
            {
                "LLM_API_KEY": "legacy-key",
                "LLM_MODEL": "vendor/model",
                "LLM_BASE_URL": "https://example.test/v1",
                "AGENT_LITELLM_MODEL": "openai/unused",
                "OPENAI_API_KEY": "unused",
                "OPENAI_BASE_URL": "unused",
            },
            [("https://example.test/v1", "vendor/model", "legacy-key")],
        ),
        (
            {
                "LITELLM_MODEL": "openai/vendor/model",
                "LLM_MODEL": "unused",
                "AGENT_LITELLM_MODEL": "unused",
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://example.test/v1",
            },
            [("https://example.test/v1", "vendor/model", "test-key")],
        ),
        (
            {
                "LITELLM_MODEL": "gemini/custom",
                "LLM_API_KEY": "override",
                "GEMINI_API_KEYS": "override,unused",
                "OPENAI_BASE_URL": "https://example.test/v1",
            },
            [("https://example.test/v1", "custom", "override")],
        ),
        (
            {
                "LLM_CHANNELS": "disabled,local",
                "LLM_DISABLED_ENABLED": "false",
                "LLM_DISABLED_MODELS": "unused",
                "LLM_LOCAL_BASE_URL": "https://example.test/v1",
                "LLM_LOCAL_MODELS": "first,second",
                "LLM_LOCAL_API_KEY": "local-key",
            },
            [
                ("https://example.test/v1", "first", "local-key"),
                ("https://example.test/v1", "second", "local-key"),
            ],
        ),
    ],
)
def test_compatibility_env_resolves_attempts(monkeypatch, env, expected):
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    config = Config.from_env()

    assert config.has_llm_config()
    assert _attempts(config) == [LLMAttempt(*attempt) for attempt in expected]


@pytest.mark.parametrize(
    ("model", "key_name", "base_url", "name"),
    [
        ("anthropic/claude-model", "ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "claude-model"),
        (
            "openrouter/anthropic/claude-model",
            "OPENROUTER_API_KEY",
            "https://openrouter.ai/api/v1",
            "anthropic/claude-model",
        ),
        (
            "dashscope/qwen-plus",
            "DASHSCOPE_API_KEY",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "qwen-plus",
        ),
        ("qwen/qwen-plus", "QWEN_API_KEY", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
        ("zhipu/glm", "ZHIPU_API_KEY", "https://open.bigmodel.cn/api/paas/v4", "glm"),
        ("moonshot/kimi", "MOONSHOT_API_KEY", "https://api.moonshot.cn/v1", "kimi"),
        ("aihubmix/gpt", "AIHUBMIX_KEY", "https://aihubmix.com/v1", "gpt"),
    ],
)
def test_provider_prefix_resolves_gateway(monkeypatch, model, key_name, base_url, name):
    monkeypatch.setenv("AGENT_LITELLM_MODEL", model)
    monkeypatch.setenv(key_name, "test-key")

    config = Config.from_env()

    assert config.has_llm_config()
    assert _attempts(config) == [LLMAttempt(base_url, name, "test-key")]


def _attempts(config: Config) -> list[LLMAttempt]:
    return build_attempts(
        config.llm_model,
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        channels=config.llm_channels,
        fallback_models=config.llm_fallback_models,
    )


def test_channel_keys_and_models_are_tried_before_direct_fallbacks(monkeypatch):
    env = {
        "LITELLM_MODEL": "openai/first",
        "LLM_API_KEY": "direct-key",
        "LLM_BASE_URL": "https://direct.test/v1",
        "LLM_CHANNELS": "disabled,primary,backup",
        "LLM_DISABLED_ENABLED": "false",
        "LLM_DISABLED_PROTOCOL": "anthropic",
        "LLM_PRIMARY_PROTOCOL": "openai",
        "LLM_PRIMARY_BASE_URL": "https://primary.test/v1",
        "LLM_PRIMARY_API_KEYS": "key-1,key-2",
        "LLM_PRIMARY_API_KEY": "unused",
        "LLM_PRIMARY_MODELS": "first,second,second",
        "LLM_BACKUP_PROTOCOL": "openrouter",
        "LLM_BACKUP_API_KEY": "backup-key",
        "LLM_BACKUP_MODELS": "anthropic/claude-model",
        "DEEPSEEK_API_KEY": "deepseek-key",
        "LITELLM_FALLBACK_MODELS": "openai/second,deepseek/third,openai/first,deepseek/third",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    config = Config.from_env()
    expected = [
        LLMAttempt("https://primary.test/v1", "first", "key-1"),
        LLMAttempt("https://primary.test/v1", "first", "key-2"),
        LLMAttempt("https://direct.test/v1", "first", "direct-key"),
        LLMAttempt("https://primary.test/v1", "second", "key-1"),
        LLMAttempt("https://primary.test/v1", "second", "key-2"),
        LLMAttempt("https://openrouter.ai/api/v1", "anthropic/claude-model", "backup-key"),
        LLMAttempt("https://direct.test/v1", "second", "direct-key"),
        LLMAttempt("https://api.deepseek.com", "third", "deepseek-key"),
    ]
    assert _attempts(config) == expected

    unavailable = requests.Response()
    unavailable.status_code = 429
    success = requests.Response()
    success.status_code = 200
    success._content = b'{"choices": [{"message": {"content": "ok"}}]}'
    post = Mock(side_effect=[unavailable] * (len(expected) - 1) + [success])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    assert (
        _call_llm(
            "prompt",
            config.llm_api_key,
            config.llm_model,
            config.llm_base_url,
            channels=config.llm_channels,
            fallback_models=config.llm_fallback_models,
        )
        == "ok"
    )
    assert [
        (call.args[0], call.kwargs["json"]["model"], call.kwargs["headers"]["Authorization"])
        for call in post.call_args_list
    ] == [
        (f"{attempt.base_url}/chat/completions", attempt.model, f"Bearer {attempt.api_key}")
        for attempt in expected
    ]


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"LITELLM_CONFIG": "/private-key-in-path.yaml"}, "Unset LITELLM_CONFIG"),
        ({"LLM_CHANNELS": "primary", "LLM_PRIMARY_PROTOCOL": "anthropic"}, "LLM_<NAME>_PROTOCOL=openai"),
    ],
)
def test_unsupported_config_degrades_with_migration_message(monkeypatch, env, message):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    post = Mock()
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)
    config = Config.from_env()
    picks = [Pick(rank=1, code="000001", name="平安银行", screen_score=80, final_score=80)]

    assert config.has_llm_config()
    result = rank_candidates_with_metadata(
        picks,
        "",
        config.llm_api_key,
        config.llm_model,
        config.llm_base_url,
        channels=config.llm_channels,
        config_path=str(config.llm_config_path or ""),
    )

    assert result.picks == picks
    assert not result.ranked
    assert message in result.errors[0]
    if config.llm_config_path:
        assert "LLM_CHANNELS=primary,backup" in result.errors[0]
        assert "LLM_PRIMARY_MODELS=<model>" in result.errors[0]
        assert str(config.llm_config_path) not in result.errors[0]
    post.assert_not_called()


def test_http_error_carries_status_without_exposing_response_text(monkeypatch):
    response = requests.Response()
    response.status_code = 400
    response._content = b'{"error": {"message": "unsupported response_format with key private-key"}}'
    monkeypatch.setattr("alphasift.llm_client.requests.post", Mock(return_value=response))

    with pytest.raises(LLMClientError, match="LLM HTTP 400") as error:
        complete(
            LLMAttempt("https://example.test/v1", "model", "private-key"),
            messages=[],
            temperature=0.2,
            response_format={"type": "json_object"},
        )

    assert error.value.status_code == 400
    assert error.value.json_mode_rejected
    assert "private-key" not in str(error.value)


def test_http_error_surfaces_redacted_provider_reason(monkeypatch):
    response = requests.Response()
    response.status_code = 404
    response._content = (
        b'{"error": {"message": "model  missing-model not found for key private-key ' + b"x" * 400 + b'"}}'
    )
    monkeypatch.setattr("alphasift.llm_client.requests.post", Mock(return_value=response))

    with pytest.raises(LLMClientError) as error:
        complete(
            LLMAttempt("https://example.test/v1", "missing-model", "private-key"),
            messages=[],
            temperature=0.2,
        )

    message = str(error.value)
    assert message.startswith("LLM HTTP 404 Not Found: model missing-model not found for key ***")
    assert "private-key" not in message
    assert len(message) < 240


def test_keyless_ollama_omits_authorization_and_rejects_malformed_response(monkeypatch):
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"choices": []}'
    post = Mock(return_value=response)
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    with pytest.raises(LLMClientError, match="Invalid LLM chat completion response") as error:
        _call_llm("prompt", "", "ollama/local-model", "", json_mode=False)

    assert error.value.status_code == 200
    assert post.call_args.args[0] == "http://localhost:11434/v1/chat/completions"
    assert "Authorization" not in post.call_args.kwargs["headers"]


def test_default_gemini_timeout_falls_through_to_hydrogen(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gem-key")
    config = Config.from_env()
    success = requests.Response()
    success.status_code = 200
    success._content = b'{"choices": [{"message": {"content": "hydrogen-ok"}}]}'
    post = Mock(side_effect=[requests.Timeout("primary timed out"), success])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)

    result = _call_llm(
        "prompt",
        config.llm_api_key,
        config.llm_model,
        config.llm_base_url,
        channels=config.llm_channels,
        fallback_models=config.llm_fallback_models,
    )

    assert result == "hydrogen-ok"
    assert [call.kwargs["json"]["model"] for call in post.call_args_list] == [
        "gemini-3.8-flash",
        "gemini-4-hydrogen",
    ]


def test_round9_key_origin_isolation_empty_content_fallback_and_userinfo_block(monkeypatch):
    # 1. GEMINI_API_KEY + OPENAI_BASE_URL must NOT forward Gemini key to OpenAI custom proxy
    monkeypatch.setenv("GEMINI_API_KEY", "gem-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://thirdparty-openai-relay.test/v1")
    cfg = Config.from_env()
    attempts = _attempts(cfg)
    assert all(a.base_url == "https://generativelanguage.googleapis.com/v1beta/openai" for a in attempts)

    # 2. Custom channel base_url without explicit channel api_keys does NOT inherit ambient provider keys
    monkeypatch.setenv("LLM_CHANNELS", "custom")
    monkeypatch.setenv("LLM_CUSTOM_PROTOCOL", "gemini")
    monkeypatch.setenv("LLM_CUSTOM_BASE_URL", "https://untrusted-custom.test/v1")
    monkeypatch.setenv("LLM_CUSTOM_MODELS", "gemini-3.8-flash")
    cfg_chan = Config.from_env()
    chan_attempts = _attempts(cfg_chan)
    custom_only = [a for a in chan_attempts if a.base_url == "https://untrusted-custom.test/v1"]
    assert custom_only and all(a.api_key == "" for a in custom_only)

    # 3. URL with embedded userinfo credentials is blocked before sending Authorization header
    with pytest.raises(LLMClientError, match="embedded credentials disallowed"):
        complete(
            LLMAttempt("https://user:pass@example.test/v1", "m", "k"),
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.2,
        )

    # 3b. Query/fragment injection (including bare ? / # delimiters) and Zhipu/JWT redaction
    for bad_url in (
        "https://example.test/v1?api_key=bad",
        "https://example.test/v1?",
        "https://example.test/v1#",
    ):
        with pytest.raises(LLMClientError, match="query and fragment disallowed"):
            complete(
                LLMAttempt(bad_url, "m", "k"),
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.2,
            )

    from alphasift.llm_client import _provider_reason

    err_resp = requests.Response()
    err_resp.status_code = 400
    err_resp._content = (
        b'{"error": {"message": "zhipu=4f8e0123456789abcdef0123456789ab.AbCdEfGh12345678 '
        b'jwt=eyJabcdef1234567890abcdef1234567890.eyJsub12345.sig123456 '
        b'api_key=\\"quoted-secret-value\\""}}'
    )
    sanitized = _provider_reason(err_resp, "")
    assert "AbCdEfGh12345678" not in sanitized
    assert "eyJsub12345" not in sanitized
    assert "quoted-secret-value" not in sanitized

    monkeypatch.setenv("LLM_CHANNELS", "primary")
    monkeypatch.setenv("LLM_PRIMARY_PROTOCOL", "")
    monkeypatch.setenv("LLM_PRIMARY_MODELS", "deepseek-chat")
    monkeypatch.setenv("LLM_PRIMARY_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_PRIMARY_API_KEY", "ds-k")
    monkeypatch.setenv("LITELLM_FALLBACK_MODELS", "")
    monkeypatch.setenv("GEMINI_MODEL", "")
    cfg_empty = Config.from_env()
    assert cfg_empty.llm_channels[0]["protocol"] == "openai"
    assert cfg_empty.has_usable_llm_config() is True

    # 4. Empty/null assistant content raises so _call_llm falls through to fallback model
    empty_resp = requests.Response()
    empty_resp.status_code = 200
    empty_resp._content = b'{"choices": [{"message": {"content": null}}]}'
    ok_resp = requests.Response()
    ok_resp.status_code = 200
    ok_resp._content = b'{"choices": [{"message": {"content": "fallback-good"}}]}'
    post = Mock(side_effect=[empty_resp, ok_resp])
    monkeypatch.setattr("alphasift.llm_client.requests.post", post)
    out = _call_llm(
        "prompt",
        "k",
        "gemini/gemini-3.8-flash",
        "",
        fallback_models=["gemini/gemini-4-hydrogen"],
    )
    assert out == "fallback-good"
    assert [c.kwargs["json"]["model"] for c in post.call_args_list] == [
        "gemini-3.8-flash",
        "gemini-4-hydrogen",
    ]
