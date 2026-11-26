# -*- coding: utf-8 -*-
"""Configuration."""

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from alphasift.llm_client import (
    DEFAULT_LLM_MAX_TOKENS,
    gateway_api_keys,
    gateway_base_url,
    normalize_model,
    split_model,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_POST_ANALYZERS = ["scorecard"]
DEFAULT_LLM_MODEL = "gemini/gemini-3.8-flash"
DEFAULT_GEMINI_FALLBACK_MODELS = ["gemini/gemini-4-hydrogen"]
DEFAULT_SNAPSHOT_SOURCE_PRIORITY = ["em_datacenter", "sina", "efinance", "akshare_em"]
TUSHARE_FIRST_SOURCE_PRIORITY = ["tushare", "em_datacenter", "sina", "efinance", "akshare_em"]
_ENV_FILE_CACHE: dict[Path, tuple[tuple[int, int], dict[str, str]]] = {}
_APPLIED_ENV_FILE_VALUES: dict[str, str] = {}


def _load_env_file() -> None:
    """Load .env from cwd or project root if present."""
    candidates = [
        *_env_file_candidates_from_env(),
        Path.cwd() / ".env",
        _PROJECT_ROOT / ".env",
    ]
    seen: set[Path] = set()
    file_values: dict[str, str] = {}
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        for key, value in _read_env_file_values(path).items():
            file_values.setdefault(key, value)
    _apply_env_file_values(file_values)


def _read_env_file_values(path: Path) -> dict[str, str]:
    resolved = path.resolve()
    stat = path.stat()
    signature = (stat.st_mtime_ns, stat.st_size)
    cached = _ENV_FILE_CACHE.get(resolved)
    if cached is not None and cached[0] == signature:
        return dict(cached[1])

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cleaned = value.strip().strip("'\"")
        if cleaned == "":
            continue
        values.setdefault(key.strip(), cleaned)
    _ENV_FILE_CACHE[resolved] = (signature, dict(values))
    return values


def _apply_env_file_values(file_values: dict[str, str]) -> None:
    for key, old_value in list(_APPLIED_ENV_FILE_VALUES.items()):
        if os.environ.get(key) == old_value and file_values.get(key) != old_value:
            os.environ.pop(key, None)
        if os.environ.get(key) != old_value:
            _APPLIED_ENV_FILE_VALUES.pop(key, None)

    for key, value in file_values.items():
        if key not in os.environ:
            os.environ[key] = value
            _APPLIED_ENV_FILE_VALUES[key] = value


def _env_file_candidates_from_env() -> list[Path]:
    raw_values = [
        os.getenv("ALPHASIFT_ENV_FILE", ""),
        os.getenv("ALPHASIFT_ENV_FILES", ""),
    ]
    paths: list[Path] = []
    for raw in raw_values:
        for item in raw.replace(os.pathsep, ",").split(","):
            value = item.strip()
            if value:
                paths.append(Path(value))
    return paths


def _parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv_env(name: str, default: list[str] | None = None) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return list(default or [])
    if value.strip().lower() in {"", "0", "false", "none", "off"}:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_optional_path_env(name: str) -> Path | None:
    value = os.getenv(name, "").strip()
    return Path(value) if value else None


def _has_tushare_token() -> bool:
    return bool(
        os.getenv("TUSHARE_TOKEN", "").strip()
        or os.getenv("TUSHARE_API_TOKEN", "").strip()
    )


def _resolve_snapshot_source_priority() -> list[str]:
    explicit = os.getenv("SNAPSHOT_SOURCE_PRIORITY")
    if explicit is not None:
        return [s.strip() for s in explicit.split(",") if s.strip()]
    if _has_tushare_token():
        return list(TUSHARE_FIRST_SOURCE_PRIORITY)
    return list(DEFAULT_SNAPSHOT_SOURCE_PRIORITY)


def _resolve_fallback_snapshot_path(data_dir: Path) -> Path | None:
    for name in ("ALPHASIFT_FALLBACK_SNAPSHOT_PATH", "FALLBACK_SNAPSHOT_PATH"):
        raw = os.getenv(name)
        if raw is None:
            continue
        value = raw.strip()
        if value.lower() in {"", "0", "false", "none", "off"}:
            return None
        return Path(value)
    return data_dir / "snapshot.last_good.json"


def _resolve_source_health_path(data_dir: Path) -> Path | None:
    raw = os.getenv("ALPHASIFT_SOURCE_HEALTH_PATH")
    if raw is None:
        return data_dir / "source_health.json"
    value = raw.strip()
    if value.lower() in {"", "0", "false", "none", "off"}:
        return None
    return Path(value)


def _is_source_checkout(root: Path | None = None) -> bool:
    base = root or _PROJECT_ROOT
    return (base / "pyproject.toml").is_file() and (base / "alphasift").is_dir()


def default_data_dir() -> Path:
    """Return repo-local ``data/`` in editable checkouts, else a writable user data dir."""
    env_val = os.getenv("ALPHASIFT_DATA_DIR", "").strip()
    if env_val:
        return Path(env_val)
    if _is_source_checkout():
        return _PROJECT_ROOT / "data"
    xdg = os.getenv("XDG_DATA_HOME", "").strip()
    if xdg:
        return Path(xdg) / "alphasift"
    return Path.home() / ".alphasift" / "data"


def _default_strategies_dir() -> Path:
    """Find strategies directory: env var > project root > package bundled."""
    env_dir = os.getenv("STRATEGIES_DIR")
    if env_dir:
        return Path(env_dir)
    # Dev mode: project root
    project_dir = _PROJECT_ROOT / "strategies"
    if project_dir.is_dir():
        return project_dir
    # Installed: inside package
    return _PACKAGE_DIR / "strategies"


@dataclass
class Config:
    """Runtime configuration, loaded from env vars."""

    # LLM
    llm_api_key: str = ""
    llm_model: str = DEFAULT_LLM_MODEL
    llm_base_url: str = ""
    llm_config_path: Path | None = None
    llm_fallback_models: list[str] = field(default_factory=list)
    llm_channels: list[dict[str, object]] = field(default_factory=list)
    llm_context: str = ""
    llm_candidate_context_enabled: bool = False
    llm_candidate_context_max_candidates: int = 8
    llm_candidate_context_providers: list[str] = field(default_factory=lambda: ["news", "fund_flow", "announcement", "quote"])
    llm_candidate_context_news_limit: int = 3
    llm_candidate_context_announcement_limit: int = 3
    llm_candidate_context_cache_enabled: bool = True
    llm_candidate_context_cache_ttl_hours: int = 24
    llm_candidate_context_cache_dir: Path | None = None
    llm_temperature: float = 0.2
    llm_json_mode: bool = True
    llm_silent: bool = True
    llm_rank_weight: float = 0.40
    llm_candidate_multiplier: int = 6
    llm_max_candidates: int = 30
    llm_max_retries: int = 1
    llm_min_coverage: float = 0.60
    llm_context_max_chars: int = 4000
    llm_timeout_sec: float = 60.0
    llm_max_tokens: int = DEFAULT_LLM_MAX_TOKENS

    # Snapshot data source priority
    snapshot_source_priority: list[str] = field(
        default_factory=lambda: list(DEFAULT_SNAPSHOT_SOURCE_PRIORITY)
    )
    fallback_snapshot_path: Path | None = field(
        default_factory=lambda: default_data_dir() / "snapshot.last_good.json"
    )
    # Cross-run snapshot source health; None disables persisted reordering.
    source_health_path: Path | None = None

    # Strategy directory
    strategies_dir: Path = field(default_factory=_default_strategies_dir)

    # Optional deterministic industry/concept enrichment.
    industry_map_files: list[Path] = field(default_factory=list)
    industry_provider: str = "none"
    # Backfill A-share industry labels when the snapshot source has none, so
    # portfolio diversity control is not silently disabled.
    industry_auto_backfill: bool = True
    industry_provider_max_boards: int = 80
    industry_provider_cache_dir: Path | None = field(
        default_factory=lambda: default_data_dir() / "industry_provider_cache"
    )
    industry_provider_cache_ttl_hours: int = 24

    # Optional: DSA API for L3 deep analysis
    dsa_api_url: str = ""
    dsa_report_type: str = "detailed"
    dsa_max_picks: int = 3
    dsa_timeout_sec: float = 120.0
    dsa_force_refresh: bool = False
    dsa_notify: bool = False

    # L3/post-ranking analyzers. scorecard is the default local scorer; DSA is
    # one optional backend, not the pipeline's default or only final stage.
    post_analyzers: list[str] = field(default_factory=lambda: list(DEFAULT_POST_ANALYZERS))
    post_analysis_max_picks: int = 3
    post_analyzer_url: str = ""
    post_analyzer_timeout_sec: float = 120.0

    # Optional daily K-line enrichment after snapshot hard filters.
    daily_enrich_enabled: bool = False
    daily_enrich_max_candidates: int = 100
    daily_lookback_days: int = 120
    daily_source: str = "auto"
    daily_fetch_retries: int = 2
    daily_fetch_max_workers: int = 1
    daily_history_cache_dir: Path | None = None
    daily_history_cache_ttl_hours: int = 24
    daily_pack_enabled: bool = True
    daily_pack_dir: Path | None = None

    # Independent risk layer.
    risk_enabled: bool = True
    risk_max_penalty: float = 12.0
    risk_veto_high: bool = False

    # Portfolio diversity layer driven by LLM sector/theme risk buckets.
    portfolio_diversity_enabled: bool = True
    portfolio_max_same_llm_sector: int = 1
    portfolio_concentration_penalty: float = 4.0

    # Evaluation overlay.
    evaluation_cost_bps: float = 0.0
    evaluation_follow_through_pct: float = 3.0
    evaluation_failed_breakout_pct: float = -3.0
    evaluation_price_path_enabled: bool = False
    evaluation_price_path_lookback_days: int = 90

    # Data directory
    data_dir: Path = field(default_factory=default_data_dir)

    # Optional notification webhooks / 1-line NOTIFY_URLS (idle unless explicitly configured).
    notify_urls: list[str] = field(default_factory=list)
    wecom_webhook_url: str = ""
    feishu_webhook_url: str = ""
    feishu_webhook_secret: str = ""
    dingtalk_webhook_url: str = ""
    dingtalk_webhook_secret: str = ""
    pushplus_token: str = ""
    pushplus_topic: str = ""
    serverchan_sendkey: str = ""
    bark_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""
    slack_webhook_url: str = ""
    ntfy_url: str = ""
    email_sender: str = ""
    email_password: str = ""
    email_receivers: str = ""
    email_smtp_host: str = ""
    email_smtp_port: int = 0
    custom_webhook_url: str = ""
    custom_webhook_token: str = ""
    # Notification safety caps & UX URL
    notify_state_path: Path = field(default_factory=lambda: default_data_dir() / "notify_state.json")
    notify_timeout_sec: float = 10.0
    dashboard_url: str = ""
    tavily_api_keys: list[str] = field(default_factory=list)
    serpapi_api_keys: list[str] = field(default_factory=list)

    # Optional guardrail for last-good snapshot fallback freshness.
    snapshot_fallback_max_age_hours: float | None = None

    def has_llm_config(self) -> bool:
        """Return whether LLM ranking is configured, including legacy YAML to diagnose."""
        return any([
            bool(self.llm_api_key),
            bool(self.llm_base_url and self.llm_model.startswith("ollama/")),
            bool(self.llm_config_path),
            bool(self.llm_channels),
            self.llm_model.startswith("ollama/"),
        ])

    def has_usable_llm_config(self) -> bool:
        """Return whether a supported non-legacy LLM route is usable."""
        from alphasift.llm_client import configuration_error

        if configuration_error(self.llm_channels, str(self.llm_config_path or "")):
            return False
        has_channels_with_models = any(
            bool(ch.get("models"))
            and (
                str(ch.get("protocol", "")).lower() == "ollama"
                or bool(ch.get("api_keys"))
                or bool(self.llm_api_key)
                or bool(gateway_api_keys(str(ch.get("protocol", "")).lower()))
            )
            for ch in self.llm_channels
        )
        return any([
            bool(self.llm_api_key),
            has_channels_with_models,
            self.llm_model.startswith("ollama/"),
        ])

    @classmethod
    def from_env(cls) -> "Config":
        _load_env_file()
        channels = _parse_llm_channels_env()
        llm_model = _resolve_llm_model(channels)
        data_dir = default_data_dir()
        fallback_snapshot_path = _resolve_fallback_snapshot_path(data_dir)
        daily_history_cache_dir = (
            _parse_optional_path_env("ALPHASIFT_DAILY_HISTORY_CACHE_DIR")
            or _parse_optional_path_env("DAILY_HISTORY_CACHE_DIR")
            or data_dir / "daily_history"
        )
        industry_provider_cache_dir = (
            _parse_optional_path_env("ALPHASIFT_INDUSTRY_PROVIDER_CACHE_DIR")
            or _parse_optional_path_env("INDUSTRY_PROVIDER_CACHE_DIR")
            or data_dir / "industry_provider_cache"
        )
        return cls(
            llm_api_key=_resolve_llm_api_key(llm_model),
            llm_model=llm_model,
            llm_base_url=_resolve_llm_base_url(llm_model),
            llm_config_path=_parse_optional_path_env("LITELLM_CONFIG"),
            llm_fallback_models=_resolve_llm_fallback_models(llm_model),
            llm_channels=channels,
            llm_context=os.getenv("LLM_CONTEXT", ""),
            llm_candidate_context_enabled=_parse_bool_env("LLM_CANDIDATE_CONTEXT_ENABLED", False),
            llm_candidate_context_max_candidates=max(
                1,
                _parse_int_env("LLM_CANDIDATE_CONTEXT_MAX_CANDIDATES", 8),
            ),
            llm_candidate_context_providers=_parse_csv_env(
                "LLM_CANDIDATE_CONTEXT_PROVIDERS",
                ["news", "fund_flow", "announcement", "quote"],
            ),
            llm_candidate_context_news_limit=max(1, _parse_int_env("LLM_CANDIDATE_CONTEXT_NEWS_LIMIT", 3)),
            llm_candidate_context_announcement_limit=max(
                1,
                _parse_int_env("LLM_CANDIDATE_CONTEXT_ANNOUNCEMENT_LIMIT", 3),
            ),
            llm_candidate_context_cache_enabled=_parse_bool_env("LLM_CANDIDATE_CONTEXT_CACHE_ENABLED", True),
            llm_candidate_context_cache_ttl_hours=max(
                0,
                _parse_int_env("LLM_CANDIDATE_CONTEXT_CACHE_TTL_HOURS", 24),
            ),
            llm_candidate_context_cache_dir=(
                _parse_optional_path_env("ALPHASIFT_CANDIDATE_CONTEXT_CACHE_DIR")
                or _parse_optional_path_env("LLM_CANDIDATE_CONTEXT_CACHE_DIR")
            ),
            llm_temperature=_parse_float_env("LLM_TEMPERATURE", 0.2),
            llm_json_mode=_parse_bool_env("LLM_JSON_MODE", True),
            llm_silent=_parse_bool_env("LLM_SILENT", True),
            llm_rank_weight=_parse_float_env("LLM_RANK_WEIGHT", 0.40),
            llm_candidate_multiplier=max(1, _parse_int_env("LLM_CANDIDATE_MULTIPLIER", 6)),
            llm_max_candidates=max(1, _parse_int_env("LLM_MAX_CANDIDATES", 30)),
            llm_max_retries=max(0, _parse_int_env("LLM_MAX_RETRIES", 1)),
            llm_min_coverage=_parse_float_env("LLM_MIN_COVERAGE", 0.60),
            llm_context_max_chars=max(500, _parse_int_env("LLM_CONTEXT_MAX_CHARS", 4000)),
            llm_timeout_sec=max(1.0, _parse_float_env("LLM_TIMEOUT_SEC", 60.0)),
            llm_max_tokens=max(1, _parse_int_env("LLM_MAX_TOKENS", DEFAULT_LLM_MAX_TOKENS)),
            snapshot_source_priority=_resolve_snapshot_source_priority(),
            fallback_snapshot_path=fallback_snapshot_path,
            source_health_path=_resolve_source_health_path(data_dir),
            snapshot_fallback_max_age_hours=_parse_optional_float_env(
                "SNAPSHOT_FALLBACK_MAX_AGE_HOURS"
            ),
            strategies_dir=_default_strategies_dir(),
            industry_map_files=[
                Path(item)
                for item in _parse_csv_env("INDUSTRY_MAP_FILES", [])
            ],
            industry_provider=os.getenv("INDUSTRY_PROVIDER", "none"),
            industry_auto_backfill=_parse_bool_env("INDUSTRY_AUTO_BACKFILL", True),
            industry_provider_max_boards=max(1, _parse_int_env("INDUSTRY_PROVIDER_MAX_BOARDS", 80)),
            industry_provider_cache_dir=industry_provider_cache_dir,
            industry_provider_cache_ttl_hours=max(
                0,
                _parse_int_env(
                    "ALPHASIFT_INDUSTRY_PROVIDER_CACHE_TTL_HOURS",
                    24,
                    fallback_names=("INDUSTRY_PROVIDER_CACHE_TTL_HOURS",),
                ),
            ),
            dsa_api_url=os.getenv("DSA_API_URL", ""),
            dsa_report_type=os.getenv("DSA_REPORT_TYPE", "detailed"),
            dsa_max_picks=max(1, _parse_int_env("DSA_MAX_PICKS", 3)),
            dsa_timeout_sec=max(1.0, _parse_float_env("DSA_TIMEOUT_SEC", 120.0)),
            dsa_force_refresh=_parse_bool_env("DSA_FORCE_REFRESH", False),
            dsa_notify=_parse_bool_env("DSA_NOTIFY", False),
            post_analyzers=_parse_csv_env("POST_ANALYZERS", DEFAULT_POST_ANALYZERS),
            post_analysis_max_picks=max(
                1,
                _parse_int_env(
                    "POST_ANALYSIS_MAX_PICKS",
                    3,
                    fallback_names=("DSA_MAX_PICKS",),
                ),
            ),
            post_analyzer_url=os.getenv("POST_ANALYZER_URL", ""),
            post_analyzer_timeout_sec=max(1.0, _parse_float_env("POST_ANALYZER_TIMEOUT_SEC", 120.0)),
            daily_enrich_enabled=_parse_bool_env("DAILY_ENRICH_ENABLED", False),
            daily_enrich_max_candidates=max(1, _parse_int_env("DAILY_ENRICH_MAX_CANDIDATES", 100)),
            daily_lookback_days=max(30, _parse_int_env("DAILY_LOOKBACK_DAYS", 120)),
            daily_source=os.getenv("DAILY_SOURCE", "auto"),
            daily_fetch_retries=max(0, _parse_int_env("DAILY_FETCH_RETRIES", 2)),
            daily_fetch_max_workers=max(1, _parse_int_env("DAILY_FETCH_MAX_WORKERS", 1)),
            daily_history_cache_dir=daily_history_cache_dir,
            daily_history_cache_ttl_hours=max(
                0,
                _parse_int_env(
                    "ALPHASIFT_DAILY_HISTORY_CACHE_TTL_HOURS",
                    24,
                    fallback_names=("DAILY_HISTORY_CACHE_TTL_HOURS",),
                ),
            ),
            daily_pack_enabled=_parse_bool_env("ALPHASIFT_DAILY_PACK_ENABLED", True),
            daily_pack_dir=_parse_optional_path_env("ALPHASIFT_PACK_DIR"),
            risk_enabled=_parse_bool_env("RISK_ENABLED", True),
            risk_max_penalty=_parse_float_env("RISK_MAX_PENALTY", 12.0),
            risk_veto_high=_parse_bool_env("RISK_VETO_HIGH", False),
            portfolio_diversity_enabled=_parse_bool_env("PORTFOLIO_DIVERSITY_ENABLED", True),
            portfolio_max_same_llm_sector=max(
                1,
                _parse_int_env("PORTFOLIO_MAX_SAME_LLM_SECTOR", 1),
            ),
            portfolio_concentration_penalty=_parse_float_env("PORTFOLIO_CONCENTRATION_PENALTY", 4.0),
            evaluation_cost_bps=_parse_float_env("EVALUATION_COST_BPS", 0.0),
            evaluation_follow_through_pct=_parse_float_env("EVALUATION_FOLLOW_THROUGH_PCT", 3.0),
            evaluation_failed_breakout_pct=_parse_float_env("EVALUATION_FAILED_BREAKOUT_PCT", -3.0),
            evaluation_price_path_enabled=_parse_bool_env("EVALUATION_PRICE_PATH_ENABLED", False),
            evaluation_price_path_lookback_days=max(
                30,
                _parse_int_env("EVALUATION_PRICE_PATH_LOOKBACK_DAYS", 90),
            ),
            data_dir=data_dir,
            notify_urls=_parse_notify_urls_env(),
            wecom_webhook_url=(
                os.getenv("ALPHASIFT_WECOM_WEBHOOK_URL") or os.getenv("WECOM_WEBHOOK_URL", "")
            ).strip(),
            feishu_webhook_url=(
                os.getenv("ALPHASIFT_FEISHU_WEBHOOK_URL") or os.getenv("FEISHU_WEBHOOK_URL", "")
            ).strip(),
            feishu_webhook_secret=(
                os.getenv("ALPHASIFT_FEISHU_WEBHOOK_SECRET") or os.getenv("FEISHU_WEBHOOK_SECRET", "")
            ).strip(),
            dingtalk_webhook_url=(
                os.getenv("ALPHASIFT_DINGTALK_WEBHOOK_URL") or os.getenv("DINGTALK_WEBHOOK_URL", "")
            ).strip(),
            dingtalk_webhook_secret=(
                os.getenv("ALPHASIFT_DINGTALK_WEBHOOK_SECRET") or os.getenv("DINGTALK_WEBHOOK_SECRET", "")
            ).strip(),
            pushplus_token=(
                os.getenv("ALPHASIFT_PUSHPLUS_TOKEN") or os.getenv("PUSHPLUS_TOKEN", "")
            ).strip(),
            pushplus_topic=(
                os.getenv("ALPHASIFT_PUSHPLUS_TOPIC") or os.getenv("PUSHPLUS_TOPIC", "")
            ).strip(),
            serverchan_sendkey=(
                os.getenv("ALPHASIFT_SERVERCHAN_SENDKEY")
                or os.getenv("SERVERCHAN_SENDKEY")
                or os.getenv("SERVERCHAN3_SENDKEY", "")
            ).strip(),
            bark_url=(
                os.getenv("ALPHASIFT_BARK_URL") or os.getenv("BARK_URL", "")
            ).strip(),
            telegram_bot_token=(
                os.getenv("ALPHASIFT_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
            ).strip(),
            telegram_chat_id=(
                os.getenv("ALPHASIFT_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID", "")
            ).strip(),
            discord_webhook_url=(
                os.getenv("ALPHASIFT_DISCORD_WEBHOOK_URL") or os.getenv("DISCORD_WEBHOOK_URL", "")
            ).strip(),
            slack_webhook_url=(
                os.getenv("ALPHASIFT_SLACK_WEBHOOK_URL") or os.getenv("SLACK_WEBHOOK_URL", "")
            ).strip(),
            ntfy_url=(
                os.getenv("ALPHASIFT_NTFY_URL") or os.getenv("NTFY_URL", "")
            ).strip(),
            email_sender=(
                os.getenv("ALPHASIFT_EMAIL_SENDER") or os.getenv("EMAIL_SENDER", "")
            ).strip(),
            email_password=(
                os.getenv("ALPHASIFT_EMAIL_PASSWORD") or os.getenv("EMAIL_PASSWORD", "")
            ).strip(),
            email_receivers=(
                os.getenv("ALPHASIFT_EMAIL_RECEIVERS") or os.getenv("EMAIL_RECEIVERS", "")
            ).strip(),
            email_smtp_host=(
                os.getenv("ALPHASIFT_EMAIL_SMTP_HOST") or os.getenv("EMAIL_SMTP_HOST", "")
            ).strip(),
            email_smtp_port=max(
                0,
                _parse_int_env(
                    "ALPHASIFT_EMAIL_SMTP_PORT",
                    0,
                    fallback_names=("EMAIL_SMTP_PORT",),
                ),
            ),
            custom_webhook_url=(
                os.getenv("ALPHASIFT_CUSTOM_WEBHOOK_URL") or os.getenv("CUSTOM_WEBHOOK_URL", "")
            ).strip(),
            custom_webhook_token=(
                os.getenv("ALPHASIFT_CUSTOM_WEBHOOK_TOKEN") or os.getenv("CUSTOM_WEBHOOK_TOKEN", "")
            ).strip(),
            notify_state_path=(
                _parse_optional_path_env("ALPHASIFT_NOTIFY_STATE_PATH")
                or (data_dir / "notify_state.json")
            ),
            notify_timeout_sec=max(1.0, _parse_float_env("ALPHASIFT_NOTIFY_TIMEOUT_SEC", 10.0)),
            dashboard_url=_resolve_dashboard_url(),
            tavily_api_keys=_parse_csv_env("TAVILY_API_KEYS", []) or _parse_csv_env("TAVILY_API_KEY", []),
            serpapi_api_keys=_parse_csv_env("SERPAPI_API_KEYS", []) or _parse_csv_env("SERPAPI_API_KEY", []),
        )


def _resolve_dashboard_url() -> str:
    """Resolve user/Fork-safe dashboard URL without leaking upstream URL to third-party pushes."""
    explicit = os.getenv("ALPHASIFT_DASHBOARD_URL")
    if explicit is not None:
        cleaned = explicit.strip()
        if cleaned.lower() in {"", "none", "off", "false"}:
            return ""
        return cleaned
    gh_repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    if gh_repo:
        if gh_repo == "ZhuLinsen/alphasift":
            return "https://alphasift.zhulinsen.tech/"
        if _parse_bool_env("ALPHASIFT_ENABLE_PAGES", False) and "/" in gh_repo:
            owner, repo = gh_repo.split("/", 1)
            return f"https://{owner.lower()}.github.io/{repo}/"
        return ""
    return ""


def _parse_int_env(name: str, default: int, *, fallback_names: tuple[str, ...] = ()) -> int:
    for key in (name, *fallback_names):
        raw = os.getenv(key)
        if raw is None:
            continue
        cleaned = raw.strip()
        if not cleaned:
            continue
        try:
            return int(cleaned)
        except ValueError:
            continue
    return default


def _parse_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    try:
        parsed = float(cleaned)
    except ValueError:
        return default
    return parsed if math.isfinite(parsed) else default


def _parse_notify_urls_env() -> list[str]:
    raw = (os.getenv("ALPHASIFT_NOTIFY_URLS") or os.getenv("NOTIFY_URLS") or "").strip()
    if not raw:
        return []
    urls: list[str] = []
    # Split on newlines/semicolons, or commas before another scheme:// (preserves mailto://...?to=a,b).
    for block in re.split(r"[\r\n;]+", raw):
        for chunk in re.split(r"(?:\s*,\s*)+(?=[A-Za-z][A-Za-z0-9+.-]*://)", block):
            cleaned = chunk.strip().strip(",").strip()
            if cleaned and cleaned not in urls:
                urls.append(cleaned)
    return urls


def _parse_optional_float_env(name: str) -> float | None:
    value = os.getenv(name)
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned.lower() in {"", "none", "off", "false"}:
        return None
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _parse_llm_channels_env() -> list[dict[str, object]]:
    channels = []
    for raw_name in _parse_csv_env("LLM_CHANNELS", []):
        name = raw_name.strip()
        if not name:
            continue
        key = name.upper()
        enabled = _parse_bool_env(f"LLM_{key}_ENABLED", True)
        api_keys = (
            _parse_csv_env(f"LLM_{key}_API_KEYS", [])
            or _parse_csv_env(f"LLM_{key}_API_KEY", [])
        )
        channels.append({
            "name": name.lower(),
            "protocol": (os.getenv(f"LLM_{key}_PROTOCOL") or "").strip().lower() or "openai",
            "base_url": os.getenv(f"LLM_{key}_BASE_URL", "").strip(),
            "api_keys": api_keys,
            "models": _parse_csv_env(f"LLM_{key}_MODELS", []),
            "enabled": enabled,
        })
    return [channel for channel in channels if channel["enabled"]]


def _resolve_llm_model(channels: list[dict[str, object]]) -> str:
    explicit = (
        os.getenv("LITELLM_MODEL")
        or os.getenv("LLM_MODEL")
        or os.getenv("AGENT_LITELLM_MODEL")
        or ""
    ).strip()
    if explicit:
        return normalize_model(explicit)

    for channel in channels:
        models = channel.get("models", [])
        if isinstance(models, list) and models:
            return normalize_model(str(models[0]), str(channel.get("protocol", "openai")))

    if os.getenv("OLLAMA_API_BASE"):
        ollama_model = os.getenv("OLLAMA_MODEL", "").strip()
        return f"ollama/{ollama_model}" if ollama_model else DEFAULT_LLM_MODEL
    if os.getenv("DEEPSEEK_API_KEY"):
        return "deepseek/deepseek-chat"
    if os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS"):
        gemini_model = (os.getenv("GEMINI_MODEL") or "").strip() or DEFAULT_LLM_MODEL
        return normalize_model(gemini_model, "gemini")
    if os.getenv("OPENAI_API_KEY") or os.getenv("AIHUBMIX_KEY"):
        openai_model = (os.getenv("OPENAI_MODEL") or "").strip() or "gpt-4o-mini"
        return normalize_model(openai_model)
    return DEFAULT_LLM_MODEL


def _resolve_llm_fallback_models(llm_model: str) -> list[str]:
    raw_fb = os.getenv("LITELLM_FALLBACK_MODELS")
    if raw_fb is not None:
        cleaned = raw_fb.strip()
        if not cleaned or cleaned.lower() in {"none", "off", "false", "0"}:
            return []
        return _parse_csv_env("LITELLM_FALLBACK_MODELS", [])
    if llm_model == DEFAULT_LLM_MODEL:
        return list(DEFAULT_GEMINI_FALLBACK_MODELS)
    return []


def _resolve_llm_api_key(model: str) -> str:
    explicit = os.getenv("LLM_API_KEY", "").strip()
    if explicit:
        return explicit
    provider, _ = split_model(model)
    if provider == "openai" and os.getenv("AIHUBMIX_KEY"):
        return os.getenv("AIHUBMIX_KEY", "")
    keys = gateway_api_keys(provider)
    return keys[0] if keys else ""


def _resolve_llm_base_url(model: str) -> str:
    explicit = os.getenv("LLM_BASE_URL", "").strip()
    if explicit:
        return explicit
    provider, _ = split_model(model)
    if provider == "ollama":
        return os.getenv("OLLAMA_API_BASE", "")
    if provider == "openai":
        if os.getenv("AIHUBMIX_KEY"):
            return gateway_base_url("aihubmix")
        return os.getenv("OPENAI_BASE_URL", "")
    # Never route non-OpenAI provider keys (e.g. GEMINI_API_KEY / DEEPSEEK_API_KEY)
    # to OPENAI_BASE_URL unless LLM_API_KEY explicitly overrides credentials too.
    if provider in {"gemini", "deepseek", "anthropic"} and os.getenv("LLM_API_KEY", "").strip():
        return os.getenv("OPENAI_BASE_URL", "")
    return ""
