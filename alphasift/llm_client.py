"""OpenAI-compatible chat completion and ordered endpoint resolution."""

import logging
import os
import re
from dataclasses import dataclass, field
from http import HTTPStatus

from urllib.parse import quote, urlsplit

import requests

logger = logging.getLogger(__name__)

_DASHSCOPE = ("https://dashscope.aliyuncs.com/compatible-mode/v1", ("DASHSCOPE_API_KEY", "QWEN_API_KEY"))
_GATEWAYS = {
    "openai": ("https://api.openai.com/v1", ("OPENAI_API_KEY",)),
    "deepseek": ("https://api.deepseek.com", ("DEEPSEEK_API_KEY",)),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", ("GEMINI_API_KEY",)),
    "anthropic": ("https://api.anthropic.com/v1", ("ANTHROPIC_API_KEY",)),
    "ollama": ("http://localhost:11434/v1", ()),
    "openrouter": ("https://openrouter.ai/api/v1", ("OPENROUTER_API_KEY",)),
    "dashscope": _DASHSCOPE,
    "qwen": _DASHSCOPE,
    "zhipu": ("https://open.bigmodel.cn/api/paas/v4", ("ZHIPU_API_KEY", "ZAI_API_KEY")),
    "moonshot": ("https://api.moonshot.cn/v1", ("MOONSHOT_API_KEY",)),
    "aihubmix": ("https://aihubmix.com/v1", ("AIHUBMIX_KEY", "AIHUBMIX_API_KEY")),
}
_BASE_URL_ENV = {
    "openai": "OPENAI_BASE_URL",
    "ollama": "OLLAMA_API_BASE",
    "aihubmix": "AIHUBMIX_BASE_URL",
}
_CHANNEL_PROTOCOLS = _GATEWAYS.keys() - {"anthropic"}
_NATIVE_PROVIDER_HOSTS: dict[str, str] = {
    (urlsplit(info[0]).hostname or "").lower(): ("dashscope" if prov == "qwen" else prov)
    for prov, info in _GATEWAYS.items()
    if prov not in {"openai", "openrouter", "aihubmix"} and urlsplit(info[0]).hostname
}


def _is_foreign_gateway_url(url: str, provider: str) -> bool:
    """Return True when ``url`` is a different vendor's native gateway hostname."""
    host = (urlsplit(str(url or "").strip()).hostname or "").lower()
    owner = _NATIVE_PROVIDER_HOSTS.get(host) if host else None
    if not owner:
        return False
    norm_prov = "dashscope" if provider == "qwen" else provider
    return owner != norm_prov
_SECRET_LIKE = re.compile(
    r"(?i)(?:bearer\s+\S+"
    r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r"|[0-9a-f]{12,}\.[A-Za-z0-9_-]{10,}"
    r"|\b(?:sk|pk|rk|key)-[\w-]{8,}"
    r"|\bAIza[\w-]{16,}"
    r"|\b(?:access_token|token|key|secret|password|api_key)\s*[=:]\s*['\"]?[^\s&,'\"\}\]]+['\"]?"
    r"|\b[\w-]{32,}\b)"
)


class LLMClientError(RuntimeError):
    """An LLM failure with a safe message and an HTTP status when available."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        timed_out: bool = False,
        json_mode_rejected: bool = False,
        truncated: bool = False,
        partial_content: str = "",
        max_tokens: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.timed_out = timed_out
        self.json_mode_rejected = json_mode_rejected
        # The completion ran out of output budget: ``partial_content`` holds any
        # text emitted before the cut, ``max_tokens`` the budget actually sent.
        self.truncated = truncated
        self.partial_content = partial_content
        self.max_tokens = max_tokens


# One truncation may raise the budget once: reasoning models spend thousands of
# tokens before answering, so the retry gets a real floor, and the ceiling keeps a
# single bad response from requesting an unbounded budget.
TRUNCATION_RETRY_MIN_TOKENS = 8192
TRUNCATION_RETRY_MAX_TOKENS = 32768


def truncation_retry_max_tokens(sent: int | None) -> int | None:
    """Return the budget for the single retry after a truncation, or None.

    None means a retry cannot add room: no budget was sent (the provider default
    is unknown, so a fixed value could be smaller) or the ceiling is reached.
    """
    if sent is None or sent <= 0:
        return None
    budget = min(max(sent * 2, TRUNCATION_RETRY_MIN_TOKENS), TRUNCATION_RETRY_MAX_TOKENS)
    return budget if budget > sent else None


@dataclass(frozen=True)
class LLMAttempt:
    base_url: str = field(repr=False)
    model: str
    api_key: str = field(repr=False)


def normalize_model(model: str, protocol: str = "openai") -> str:
    model = model.strip()
    if protocol == "openrouter" and not model.startswith("openrouter/"):
        return f"openrouter/{model}"
    if "/" in model:
        return model
    return f"{protocol}/{model}" if protocol in _GATEWAYS else f"openai/{model}"


def split_model(model: str) -> tuple[str, str]:
    prefix, slash, name = model.partition("/")
    if slash and prefix in _GATEWAYS:
        return ("dashscope" if prefix == "qwen" else prefix), name
    return "openai", model


def gateway_api_keys(provider: str) -> list[str]:
    if provider == "gemini":
        value = os.getenv("GEMINI_API_KEYS", "").strip()
        if value.lower() not in {"", "0", "false", "none", "off"}:
            keys = [key.strip() for key in value.split(",") if key.strip()]
            if keys:
                return keys
    for name in _GATEWAYS[provider][1]:
        if key := os.getenv(name, "").strip():
            return [key]
    return []


def gateway_base_url(provider: str, override: str = "") -> str:
    env_name = _BASE_URL_ENV.get(provider)
    configured_url = os.getenv(env_name, "").strip() if env_name else ""
    url = (override.strip() or configured_url or _GATEWAYS[provider][0]).rstrip("/")
    if provider == "ollama" and not url.endswith("/v1"):
        url += "/v1"
    return url


def configuration_error(channels: list[dict[str, object]], config_path: str) -> str:
    if config_path:
        return (
            "LITELLM_CONFIG (Router YAML) is unsupported. Unset LITELLM_CONFIG and migrate each "
            "route to LLM_CHANNELS=primary,backup with LLM_PRIMARY_PROTOCOL=openai, "
            "LLM_PRIMARY_BASE_URL=<OpenAI-compatible base URL>, LLM_PRIMARY_API_KEY=<key> "
            "(or LLM_PRIMARY_API_KEYS=<key1,key2>), and LLM_PRIMARY_MODELS=<model>. "
            "Repeat with LLM_BACKUP_* for the next route."
        )
    if any(str(channel.get("protocol", "openai")) not in _CHANNEL_PROTOCOLS for channel in channels):
        return (
            "Unsupported LLM channel protocol. Set LLM_<NAME>_PROTOCOL=openai and "
            "LLM_<NAME>_BASE_URL to an OpenAI-compatible endpoint. For Claude, use "
            "https://api.anthropic.com/v1."
        )
    return ""


def build_attempts(
    model: str,
    *,
    api_key: str,
    base_url: str,
    channels: list[dict[str, object]],
    fallback_models: list[str],
) -> list[LLMAttempt]:
    """Try the primary model, remaining channel models, then direct fallbacks."""
    primary_provider, primary_name = split_model(model)
    primary_keys = gateway_api_keys(primary_provider)
    if api_key and (
        primary_provider != "gemini" or primary_keys[:1] != [api_key] or os.getenv("LLM_API_KEY", "").strip()
    ):
        primary_keys = [api_key]

    def direct_attempts(candidate: str) -> list[LLMAttempt]:
        provider, name = split_model(candidate)
        same_provider = provider == primary_provider
        url = gateway_base_url(provider, base_url if same_provider else "")
        # Never forward an OpenAI fallback model (e.g. gpt-4o) to OPENAI_BASE_URL when
        # OPENAI_BASE_URL points at a non-OpenAI native gateway (e.g. api.deepseek.com).
        if not same_provider and provider == "openai" and _is_foreign_gateway_url(url, provider):
            return []
        keys = primary_keys if same_provider else gateway_api_keys(provider)
        if not keys and (provider == "ollama" or (same_provider and base_url)):
            keys = [""]
        return [LLMAttempt(url, name, key) for key in keys if name]

    primary_channels: list[LLMAttempt] = []
    remaining_channels: list[LLMAttempt] = []
    for channel in channels:
        protocol = str(channel.get("protocol", "openai"))
        models = channel.get("models")
        channel_keys = channel.get("api_keys")
        channel_url = str(channel.get("base_url") or "")
        for value in models if isinstance(models, list) else []:
            provider, name = split_model(normalize_model(str(value), protocol))
            same_provider = provider == primary_provider
            default_origin = _GATEWAYS.get(provider, ("", ()))[0].rstrip("/")
            url = gateway_base_url(provider, channel_url or (base_url if same_provider else ""))
            explicit_keys = [str(k or "") for k in channel_keys] if isinstance(channel_keys, list) else []
            keys: list[str]
            if explicit_keys:
                keys = explicit_keys
            elif not channel_url or url.rstrip("/") == default_origin or provider == "ollama":
                keys = (primary_keys if same_provider else gateway_api_keys(provider)) or [""]
            else:
                # Custom third-party channel URL without explicit channel keys must NOT
                # receive unrelated provider gateway keys by ambient inheritance.
                keys = [""]
            target = primary_channels if name == primary_name else remaining_channels
            target.extend(LLMAttempt(url, name, key) for key in keys if name)

    attempts = [*primary_channels, *direct_attempts(model), *remaining_channels]
    for fallback in fallback_models:
        attempts.extend(direct_attempts(fallback.strip()))
    return list(dict.fromkeys(attempts))


def _validated_endpoint(base_url: str) -> str:
    cleaned = str(base_url or "").strip()
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise LLMClientError("Invalid LLM endpoint URL")
    if parsed.username or parsed.password:
        raise LLMClientError("Invalid LLM endpoint URL: embedded credentials disallowed")
    if parsed.query or parsed.fragment or "?" in cleaned or "#" in cleaned:
        raise LLMClientError("Invalid LLM endpoint URL: query and fragment disallowed")
    return cleaned.rstrip("/")


def supports_reasoning_effort(attempt: LLMAttempt) -> bool:
    """Return True when endpoint/model expects or supports OpenAI ``reasoning_effort``."""
    url_l = str(attempt.base_url or "").lower()
    model_l = str(attempt.model or "").lower()
    if "generativelanguage.googleapis.com" in url_l and ("gemini-2.5" in model_l or "gemini-3" in model_l):
        return True
    return model_l.startswith(("o1", "o3", "o4", "gpt-5"))


def complete(
    attempt: LLMAttempt,
    *,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int | None = None,
    response_format: dict[str, str] | None = None,
    reasoning_effort: str | None = None,
    timeout: float = 60.0,
    silent: bool = True,
) -> str:
    """Make one request and return the first assistant message's text."""
    endpoint_base = _validated_endpoint(attempt.base_url)
    payload: dict[str, object] = {"model": attempt.model, "messages": messages, "temperature": temperature}
    eff_tokens: int | None = None
    if max_tokens is not None and int(max_tokens) > 0:
        eff_tokens = int(max_tokens)
        if reasoning_effort and supports_reasoning_effort(attempt):
            eff_tokens = max(eff_tokens, 8192)
        payload["max_tokens"] = eff_tokens
    if reasoning_effort and supports_reasoning_effort(attempt):
        payload["reasoning_effort"] = str(reasoning_effort)
    if response_format is not None:
        payload["response_format"] = response_format
    headers = {"Authorization": f"Bearer {attempt.api_key}"} if attempt.api_key else {}
    try:
        response = requests.post(
            f"{endpoint_base}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        # Requests can wrap a body read timeout in ConnectionError or ChunkedEncodingError.
        if isinstance(exc, requests.Timeout) or "timed out" in str(exc).lower():
            raise LLMClientError("LLM request timed out", timed_out=True) from None
        raise LLMClientError("LLM HTTP request failed") from None

    status = response.status_code
    if not silent:
        logger.debug("LLM HTTP status %d", status)
    if not 200 <= status < 300:
        raise _response_error(response, check_json_mode=response_format is not None, api_key=attempt.api_key)

    try:
        choice = response.json()["choices"][0]
        message = choice["message"]
        content = message["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise LLMClientError("Invalid LLM chat completion response", status_code=status) from None
    if content is None or isinstance(content, str):
        text = content or ""
        finish_reason = str(choice.get("finish_reason") or "").strip().lower()
        reasoning = message.get("reasoning_content") if isinstance(message, dict) else None
        # A reasoning model can spend the whole budget before answering (empty
        # content) or be cut off mid-answer; both look like an ordinary bad
        # response unless finish_reason is checked.
        if finish_reason == "length" or (
            not text.strip() and isinstance(reasoning, str) and reasoning.strip()
        ):
            raise LLMClientError(
                f"LLM completion truncated (finish_reason={finish_reason or 'unknown'}, "
                f"max_tokens={eff_tokens if eff_tokens is not None else 'unset'})",
                status_code=status,
                truncated=True,
                partial_content=text if text.strip() else "",
                max_tokens=eff_tokens,
            )
    if not isinstance(content, str):
        raise LLMClientError("Invalid LLM assistant text", status_code=status)
    if not content.strip():
        raise LLMClientError("Empty LLM chat completion content", status_code=status)
    return content


def _provider_reason(response: requests.Response, api_key: str) -> str:
    """Return the provider's short error message with the key redacted, or ''."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, list) and body:
        body = body[0]
    error = body.get("error", body) if isinstance(body, dict) else None
    reason = error.get("message") if isinstance(error, dict) else error
    if not isinstance(reason, str):
        return ""
    reason = " ".join(reason.split())
    if api_key:
        reason = reason.replace(api_key, "***")
        encoded = quote(api_key, safe="")
        if encoded:
            reason = reason.replace(encoded, "***")
    # A relay can echo a credential other than ours, so also mask anything key-shaped.
    return _SECRET_LIKE.sub("***", reason)[:180]


def _response_error(response: requests.Response, *, check_json_mode: bool, api_key: str = "") -> LLMClientError:
    status = response.status_code
    timed_out = status in (408, 504)
    # Error bodies can echo credentials and prompts: classify on the raw text, but only
    # surface the provider's short message field, truncated and with the key redacted.
    detail = response.text.lower() if check_json_mode and status in (400, 415, 422) else ""
    rejected = (
        ("response_format" in detail or "json_object" in detail or "json mode" in detail)
        and any(tok in detail for tok in ("unsupported", "not support", "invalid", "unrecognized", "unknown", "disabled", "disallowed"))
    )
    try:
        message = f"LLM HTTP {status} {HTTPStatus(status).phrase}"
    except ValueError:
        message = f"LLM HTTP {status}"
    if rejected:
        message += " (response_format rejected)"
    elif reason := _provider_reason(response, api_key):
        message += f": {reason}"
    return LLMClientError(message, status_code=status, timed_out=timed_out, json_mode_rejected=rejected)
