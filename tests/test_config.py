import os
from pathlib import Path

from alphasift.config import Config, DEFAULT_LLM_MODEL


def test_config_reads_llm_model_and_fallback_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "openai/deepseek-ai/DeepSeek-V3")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.siliconflow.cn/v1")
    monkeypatch.setenv("LLM_FALLBACK_MODELS", "openai/gpt-4o-mini,anthropic/claude-3-5-sonnet")
    monkeypatch.setenv("LLM_TIMEOUT_SEC", "42")
    monkeypatch.setenv("LLM_MAX_TOKENS", "1234")

    config = Config.from_env()

    assert config.llm_model == "openai/deepseek-ai/DeepSeek-V3"
    assert config.llm_api_key == "sk-test"
    assert config.llm_base_url == "https://api.siliconflow.cn/v1"
    assert config.llm_fallback_models == ["openai/gpt-4o-mini", "anthropic/claude-3-5-sonnet"]
    assert config.llm_timeout_sec == 42
    assert config.llm_max_tokens == 1234
    assert config.has_llm_config() is True


def test_config_reads_llm_channels_env(monkeypatch):
    monkeypatch.setenv("LLM_CHANNELS", "deepseek")
    monkeypatch.setenv("LLM_DEEPSEEK_PROTOCOL", "openai")
    monkeypatch.setenv("LLM_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("LLM_DEEPSEEK_API_KEYS", "key1,key2")
    monkeypatch.setenv("LLM_DEEPSEEK_MODELS", "deepseek-chat,deepseek-reasoner")

    config = Config.from_env()

    assert config.llm_model == "openai/deepseek-chat"
    assert config.llm_channels[0]["api_keys"] == ["key1", "key2"]
    assert config.llm_channels[0]["base_url"] == "https://api.deepseek.com/v1"
    assert config.has_llm_config() is True


def test_config_can_disable_default_post_analyzer(monkeypatch):
    monkeypatch.setenv("POST_ANALYZERS", "none")

    config = Config.from_env()

    assert config.post_analyzers == []


def test_config_reads_portfolio_diversity_env(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_DIVERSITY_ENABLED", "true")
    monkeypatch.setenv("PORTFOLIO_MAX_SAME_LLM_SECTOR", "2")
    monkeypatch.setenv("PORTFOLIO_CONCENTRATION_PENALTY", "6.5")

    config = Config.from_env()

    assert config.portfolio_diversity_enabled is True
    assert config.portfolio_max_same_llm_sector == 2
    assert config.portfolio_concentration_penalty == 6.5


def test_config_reads_daily_fetch_retries(monkeypatch):
    monkeypatch.setenv("DAILY_FETCH_RETRIES", "4")

    config = Config.from_env()

    assert config.daily_fetch_retries == 4


def test_config_defaults_daily_source_to_auto(monkeypatch):
    monkeypatch.delenv("DAILY_SOURCE", raising=False)

    config = Config.from_env()

    assert config.daily_source == "auto"


def test_config_reads_daily_fetch_max_workers(monkeypatch):
    monkeypatch.setenv("DAILY_FETCH_MAX_WORKERS", "3")

    config = Config.from_env()

    assert config.daily_fetch_max_workers == 3


def test_config_defaults_daily_history_cache_under_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHASIFT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ALPHASIFT_FALLBACK_SNAPSHOT_PATH", raising=False)
    monkeypatch.delenv("FALLBACK_SNAPSHOT_PATH", raising=False)
    monkeypatch.delenv("ALPHASIFT_DAILY_HISTORY_CACHE_DIR", raising=False)
    monkeypatch.delenv("ALPHASIFT_DAILY_HISTORY_CACHE_TTL_HOURS", raising=False)
    monkeypatch.delenv("DAILY_HISTORY_CACHE_TTL_HOURS", raising=False)
    monkeypatch.delenv("ALPHASIFT_INDUSTRY_PROVIDER_CACHE_DIR", raising=False)
    monkeypatch.delenv("INDUSTRY_PROVIDER_CACHE_DIR", raising=False)
    monkeypatch.delenv("ALPHASIFT_INDUSTRY_PROVIDER_CACHE_TTL_HOURS", raising=False)
    monkeypatch.delenv("INDUSTRY_PROVIDER_CACHE_TTL_HOURS", raising=False)

    config = Config.from_env()

    assert config.daily_history_cache_dir == tmp_path / "daily_history"
    assert config.daily_history_cache_ttl_hours == 24
    assert config.industry_provider_cache_dir == tmp_path / "industry_provider_cache"
    assert config.industry_provider_cache_ttl_hours == 24
    assert config.fallback_snapshot_path == tmp_path / "snapshot.last_good.json"


def test_config_reads_daily_history_cache_env(monkeypatch, tmp_path):
    cache_dir = tmp_path / "custom-daily-cache"
    monkeypatch.setenv("ALPHASIFT_DAILY_HISTORY_CACHE_DIR", str(cache_dir))
    monkeypatch.delenv("ALPHASIFT_DAILY_HISTORY_CACHE_TTL_HOURS", raising=False)
    monkeypatch.setenv("DAILY_HISTORY_CACHE_TTL_HOURS", "6")

    config = Config.from_env()

    assert config.daily_history_cache_dir == cache_dir
    assert config.daily_history_cache_ttl_hours == 6


def test_config_reads_industry_provider_cache_env(monkeypatch, tmp_path):
    cache_dir = tmp_path / "custom-industry-provider-cache"
    monkeypatch.setenv("ALPHASIFT_INDUSTRY_PROVIDER_CACHE_DIR", str(cache_dir))
    monkeypatch.delenv("ALPHASIFT_INDUSTRY_PROVIDER_CACHE_TTL_HOURS", raising=False)
    monkeypatch.setenv("INDUSTRY_PROVIDER_CACHE_TTL_HOURS", "7")

    config = Config.from_env()

    assert config.industry_provider_cache_dir == cache_dir
    assert config.industry_provider_cache_ttl_hours == 7


def test_config_reads_fallback_snapshot_path_env(monkeypatch, tmp_path):
    cache_path = tmp_path / "custom-snapshot.json"
    monkeypatch.setenv("ALPHASIFT_FALLBACK_SNAPSHOT_PATH", str(cache_path))

    config = Config.from_env()

    assert config.fallback_snapshot_path == cache_path


def test_config_reads_snapshot_fallback_max_age_env(monkeypatch):
    monkeypatch.setenv("SNAPSHOT_FALLBACK_MAX_AGE_HOURS", "6.5")

    config = Config.from_env()

    assert config.snapshot_fallback_max_age_hours == 6.5


def test_config_prefers_tushare_when_token_is_configured(monkeypatch):
    monkeypatch.delenv("SNAPSHOT_SOURCE_PRIORITY", raising=False)
    monkeypatch.setenv("TUSHARE_TOKEN", "token")

    config = Config.from_env()

    assert config.snapshot_source_priority == [
        "tushare",
        "em_datacenter",
        "sina",
        "efinance",
        "akshare_em",
    ]


def test_config_omits_tushare_from_default_priority_without_token(monkeypatch):
    monkeypatch.delenv("SNAPSHOT_SOURCE_PRIORITY", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_API_TOKEN", raising=False)

    config = Config.from_env()

    assert config.snapshot_source_priority == [
        "em_datacenter",
        "sina",
        "efinance",
        "akshare_em",
    ]


def test_config_defaults_candidate_context_providers_include_quote(monkeypatch):
    monkeypatch.delenv("LLM_CANDIDATE_CONTEXT_PROVIDERS", raising=False)

    config = Config.from_env()

    assert config.llm_candidate_context_providers == [
        "news",
        "fund_flow",
        "announcement",
        "quote",
    ]


def test_config_respects_explicit_snapshot_priority_with_tushare_token(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    monkeypatch.setenv("SNAPSHOT_SOURCE_PRIORITY", "efinance,em_datacenter")

    config = Config.from_env()

    assert config.snapshot_source_priority == ["efinance", "em_datacenter"]


def test_config_reads_industry_and_candidate_context_env(monkeypatch):
    monkeypatch.setenv("INDUSTRY_MAP_FILES", "/tmp/industry.csv,/tmp/concepts.json")
    monkeypatch.setenv("INDUSTRY_PROVIDER", "akshare")
    monkeypatch.setenv("INDUSTRY_PROVIDER_MAX_BOARDS", "12")
    monkeypatch.setenv("LLM_CANDIDATE_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("LLM_CANDIDATE_CONTEXT_MAX_CANDIDATES", "5")
    monkeypatch.setenv("LLM_CANDIDATE_CONTEXT_PROVIDERS", "news,fund_flow")

    config = Config.from_env()

    assert config.industry_map_files == [Path("/tmp/industry.csv"), Path("/tmp/concepts.json")]
    assert config.industry_provider == "akshare"
    assert config.industry_provider_max_boards == 12
    assert config.llm_candidate_context_enabled is True
    assert config.llm_candidate_context_max_candidates == 5
    assert config.llm_candidate_context_providers == ["news", "fund_flow"]
    assert config.llm_candidate_context_cache_enabled is True


def test_config_reads_evaluation_cost(monkeypatch):
    monkeypatch.setenv("EVALUATION_COST_BPS", "15")
    monkeypatch.setenv("EVALUATION_FOLLOW_THROUGH_PCT", "4")
    monkeypatch.setenv("EVALUATION_FAILED_BREAKOUT_PCT", "-2.5")
    monkeypatch.setenv("EVALUATION_PRICE_PATH_ENABLED", "true")
    monkeypatch.setenv("EVALUATION_PRICE_PATH_LOOKBACK_DAYS", "45")

    config = Config.from_env()

    assert config.evaluation_cost_bps == 15
    assert config.evaluation_follow_through_pct == 4
    assert config.evaluation_failed_breakout_pct == -2.5
    assert config.evaluation_price_path_enabled is True
    assert config.evaluation_price_path_lookback_days == 45


def test_config_loads_extra_env_files(monkeypatch, tmp_path):
    env_file = tmp_path / "external.env"
    env_file.write_text(
        "\n".join([
            "LLM_MODEL=openai/test-model",
            "OPENAI_API_KEY=sk-from-file",
            "OPENAI_BASE_URL=https://example.test/v1",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHASIFT_ENV_FILES", str(env_file))

    config = Config.from_env()

    assert config.llm_model == "openai/test-model"
    assert config.llm_api_key == "sk-from-file"
    assert config.llm_base_url == "https://example.test/v1"


def test_empty_values_in_extra_env_file_do_not_block_later_files(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    first = tmp_path / "first.env"
    second = tmp_path / "second.env"
    first.write_text("GEMINI_API_KEY=\nGEMINI_MODEL=gemini-2.5-flash\n", encoding="utf-8")
    second.write_text("GEMINI_API_KEY=real-key\n", encoding="utf-8")
    monkeypatch.setenv("ALPHASIFT_ENV_FILES", os.pathsep.join([str(first), str(second)]))

    config = Config.from_env()

    assert config.llm_api_key == "real-key"


def test_config_from_env_loads_env_file_once_per_process(monkeypatch, tmp_path):
    for name in (
        "LLM_MODEL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY",
        "GEMINI_API_KEYS",
        "OLLAMA_API_BASE",
        "AIHUBMIX_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / "cached.env"
    env_file.write_text(
        "\n".join([
            "LLM_MODEL=openai/cached-model",
            "OPENAI_API_KEY=sk-cached",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHASIFT_ENV_FILES", str(env_file))
    calls = {"count": 0}
    original_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        if self == env_file:
            calls["count"] += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    first = Config.from_env()
    second = Config.from_env()

    assert calls["count"] == 1
    assert first.llm_model == "openai/cached-model"
    assert second.llm_api_key == "sk-cached"

    monkeypatch.delenv("ALPHASIFT_ENV_FILES", raising=False)
    third = Config.from_env()

    assert os.getenv("LLM_MODEL") is None
    assert os.getenv("OPENAI_API_KEY") is None
    assert third.llm_model == DEFAULT_LLM_MODEL


def test_default_gemini_model_and_hydrogen_fallback(monkeypatch):
    for name in (
        "LLM_MODEL",
        "LLM_FALLBACK_MODELS",
        "GEMINI_MODEL",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "OLLAMA_API_BASE",
        "AIHUBMIX_KEY",
        "LLM_CHANNELS",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-key")
    cfg = Config.from_env()
    assert DEFAULT_LLM_MODEL == "gemini/gemini-3.8-flash"
    assert cfg.llm_model == "gemini/gemini-3.8-flash"
    assert cfg.llm_fallback_models == ["gemini/gemini-4-hydrogen"]

    monkeypatch.setenv("GEMINI_MODEL", "gemini-4-hydrogen")
    cfg_h = Config.from_env()
    assert cfg_h.llm_model == "gemini/gemini-4-hydrogen"
    assert cfg_h.llm_fallback_models == []

    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("LLM_FALLBACK_MODELS", "none")
    cfg_none = Config.from_env()
    assert cfg_none.llm_fallback_models == []

    monkeypatch.setenv("LLM_FALLBACK_MODELS", "")
    cfg_empty = Config.from_env()
    assert cfg_empty.llm_fallback_models == []

    # Keyless non-Ollama channel with models should NOT mark LLM config as usable
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_CHANNELS", "primary")
    monkeypatch.setenv("LLM_PRIMARY_PROTOCOL", "openai")
    monkeypatch.setenv("LLM_PRIMARY_MODELS", "deepseek-chat")
    monkeypatch.setenv("LLM_PRIMARY_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_PRIMARY_API_KEY", "")
    cfg_keyless = Config.from_env()
    assert cfg_keyless.has_usable_llm_config() is False


def test_config_resolves_fork_safe_dashboard_url_and_search_keys(monkeypatch):
    for var in ("ALPHASIFT_DASHBOARD_URL", "GITHUB_REPOSITORY", "ALPHASIFT_ENABLE_PAGES", "TAVILY_API_KEYS", "SERPAPI_API_KEYS"):
        monkeypatch.delenv(var, raising=False)

    # 1. Local default (no explicit URL) omits author's public site
    assert Config.from_env().dashboard_url == ""

    # 2. Upstream ZhuLinsen/alphasift resolves canonical site
    monkeypatch.setenv("GITHUB_REPOSITORY", "ZhuLinsen/alphasift")
    assert Config.from_env().dashboard_url == "https://alphasift.zhulinsen.tech/"

    # 3. Fork without ALPHASIFT_ENABLE_PAGES=true omits author's URL
    monkeypatch.setenv("GITHUB_REPOSITORY", "SomeUser/alphasift")
    assert Config.from_env().dashboard_url == ""

    # 4. Fork with ALPHASIFT_ENABLE_PAGES=true derives fork Pages URL automatically
    monkeypatch.setenv("ALPHASIFT_ENABLE_PAGES", "true")
    assert Config.from_env().dashboard_url == "https://someuser.github.io/alphasift/"

    # 5. Explicit ALPHASIFT_DASHBOARD_URL=none disables URL and reads search keys
    monkeypatch.setenv("ALPHASIFT_DASHBOARD_URL", "none")
    monkeypatch.setenv("TAVILY_API_KEYS", "tvly-a, tvly-b")
    monkeypatch.setenv("SERPAPI_API_KEYS", "serp-1")
    cfg = Config.from_env()
    assert cfg.dashboard_url == ""
    assert cfg.tavily_api_keys == ["tvly-a", "tvly-b"]
    assert cfg.serpapi_api_keys == ["serp-1"]


def test_default_data_dir_uses_writable_user_dir_for_non_checkout_installs(monkeypatch, tmp_path):
    import alphasift.config as config_mod

    fake_pkg_parent = tmp_path / "site_packages"
    fake_pkg_parent.mkdir(parents=True)
    monkeypatch.setattr(config_mod, "_PROJECT_ROOT", fake_pkg_parent)
    monkeypatch.delenv("ALPHASIFT_DATA_DIR", raising=False)

    # 1. Honors XDG_DATA_HOME when not inside a source checkout
    xdg_dir = tmp_path / "xdg_data"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_dir))
    assert config_mod.default_data_dir() == xdg_dir / "alphasift"

    # 2. Falls back to ~/.alphasift/data when XDG_DATA_HOME is unset
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert config_mod.default_data_dir() == Path.home() / ".alphasift" / "data"

    # 3. ALPHASIFT_DATA_DIR overrides everything and Config.from_env() propagates it
    custom = tmp_path / "explicit_data"
    monkeypatch.setenv("ALPHASIFT_DATA_DIR", str(custom))
    cfg = Config.from_env()
    assert cfg.data_dir == custom
    assert cfg.fallback_snapshot_path == custom / "snapshot.last_good.json"
    assert cfg.notify_state_path == custom / "notify_state.json"


def test_config_defaults_llm_max_tokens_to_8192(monkeypatch):
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    assert Config().llm_max_tokens == 8192
    assert Config.from_env().llm_max_tokens == 8192


def test_config_from_env_handles_blank_malformed_and_nonfinite_numeric_envs(monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS", "")
    monkeypatch.setenv("DAILY_LOOKBACK_DAYS", "not-an-int")
    monkeypatch.setenv("ALPHASIFT_EMAIL_SMTP_PORT", "bad")
    monkeypatch.setenv("EMAIL_SMTP_PORT", "465")
    monkeypatch.setenv("LLM_TEMPERATURE", "nan")
    monkeypatch.setenv("LLM_TIMEOUT_SEC", "inf")
    monkeypatch.setenv("DSA_TIMEOUT_SEC", "")
    monkeypatch.setenv("POST_ANALYZER_TIMEOUT_SEC", "-inf")
    monkeypatch.setenv("SNAPSHOT_FALLBACK_MAX_AGE_HOURS", "inf")
    monkeypatch.setenv("ALPHASIFT_NOTIFY_TIMEOUT_SEC", "oops")

    cfg = Config.from_env()
    assert cfg.llm_max_tokens == 8192
    assert cfg.daily_lookback_days == 120
    assert cfg.email_smtp_port == 465
    assert cfg.llm_temperature == 0.2
    assert cfg.llm_timeout_sec == 60.0
    assert cfg.dsa_timeout_sec == 120.0
    assert cfg.post_analyzer_timeout_sec == 120.0
    assert cfg.snapshot_fallback_max_age_hours is None
    assert cfg.notify_timeout_sec == 10.0


