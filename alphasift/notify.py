# -*- coding: utf-8 -*-
"""Unified 1-line & per-channel idempotent notifications (12 native channels + optional Apprise)."""

from __future__ import annotations

import base64
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
import hashlib
import hmac
import html as html_lib
import importlib
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import threading
import time
from typing import Any
from urllib.parse import parse_qs, quote, quote_plus, unquote, urlencode, urlsplit, urlunsplit

import requests

from alphasift.config import Config
from alphasift.daily_brief import resolve_strategy_display_names
from alphasift.daily_report import (
    DEFAULT_DASHBOARD_URL,
    IM_CARD_MAX_CHARS,
    _clean_announcement_snippet,
    ensure_im_card_length,
    render_daily_im_card,
)
from alphasift.timeutil import parse_timestamp
from alphasift.jsonutil import atomic_write_strict_json, finite_float, safe_int

SUPPORTED_CHANNELS: tuple[str, ...] = (
    "wecom",
    "feishu",
    "dingtalk",
    "pushplus",
    "serverchan",
    "bark",
    "email",
    "telegram",
    "discord",
    "slack",
    "ntfy",
    "custom",
    "apprise",
)
_PROCESS_LOCK = threading.Lock()
_PENDING_LEASE_SEC = 120.0
_SCTP_PATTERN = re.compile(r"^sctp(\d+)t", re.I)

_SMTP_DEFAULTS: dict[str, tuple[str, int, str]] = {
    "qq.com": ("smtp.qq.com", 465, "ssl"),
    "foxmail.com": ("smtp.qq.com", 465, "ssl"),
    "163.com": ("smtp.163.com", 465, "ssl"),
    "126.com": ("smtp.126.com", 465, "ssl"),
    "yeah.net": ("smtp.yeah.net", 465, "ssl"),
    "gmail.com": ("smtp.gmail.com", 465, "ssl"),
    "googlemail.com": ("smtp.gmail.com", 465, "ssl"),
    "outlook.com": ("smtp.office365.com", 587, "starttls"),
    "hotmail.com": ("smtp.office365.com", 587, "starttls"),
    "live.com": ("smtp.office365.com", 587, "starttls"),
    "icloud.com": ("smtp.mail.me.com", 587, "starttls"),
    "me.com": ("smtp.mail.me.com", 587, "starttls"),
    "aliyun.com": ("smtp.aliyun.com", 465, "ssl"),
    "sina.com": ("smtp.sina.com", 465, "ssl"),
}


def _extract_url_secrets(url: str) -> list[str]:
    text = str(url or "").strip()
    if "://" not in text:
        return []
    parsed = urlsplit(text)
    if parsed.scheme.lower() not in {"http", "https"}:
        return []
    segments: list[str] = []
    for raw_seg in (parsed.path or "").split("/"):
        seg = unquote(raw_seg).strip()
        if len(seg) >= 6 and seg not in {"webhook", "services", "open-apis", "cgi-bin"}:
            segments.append(seg)
    return segments


def _valid_http_target(url: str) -> bool:
    parsed = urlsplit(str(url or "").strip())
    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(parsed.netloc)
        and not any(ch.isspace() for ch in parsed.netloc)
    )


def _strip_fragment_param(raw: str, key: str) -> tuple[str, str]:
    parsed = urlsplit(raw)
    secret = ""
    kept_frag = parsed.fragment
    kept_query = parsed.query
    if parsed.fragment:
        frag_qs = parse_qs(parsed.fragment, keep_blank_values=True)
        if key in frag_qs:
            secret = (frag_qs[key][0] or "").strip()
            kept_pairs = [(k, v) for k, vals in frag_qs.items() if k != key for v in vals]
            kept_frag = urlencode(kept_pairs, doseq=True)
    if not secret and parsed.query:
        qs = parse_qs(parsed.query, keep_blank_values=True)
        if key in qs:
            secret = (qs[key][0] or "").strip()
            kept_q_pairs = [(k, v) for k, vals in qs.items() if k != key for v in vals]
            kept_query = urlencode(kept_q_pairs, doseq=True)
    clean_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, kept_query, kept_frag))
    return clean_url, secret


def _parse_mailto_uri(raw: str) -> dict[str, Any]:
    rest = raw[len("mailto://") :]
    if "?" in rest:
        authority, query = rest.split("?", 1)
    else:
        authority, query = rest, ""
    if "@" not in authority:
        raise ValueError("Invalid mailto:// notification URI: missing '@' before host")
    creds, hostport = authority.rsplit("@", 1)
    if ":" in creds:
        sender_raw, pass_raw = creds.split(":", 1)
    else:
        sender_raw, pass_raw = creds, ""
    sender = unquote(sender_raw).strip()
    password = unquote(pass_raw).strip()
    smtp_host = ""
    smtp_port = 0
    if hostport and hostport.lower() != "auto":
        if ":" in hostport:
            h, p = hostport.rsplit(":", 1)
            smtp_host = h.strip()
            smtp_port = int(p) if p.isdigit() else 0
        else:
            smtp_host = hostport.strip()
        if smtp_host and not smtp_host.startswith("smtp.") and smtp_host.lower() in _SMTP_DEFAULTS:
            smtp_host = _SMTP_DEFAULTS[smtp_host.lower()][0]
    qs = parse_qs(query)
    to_vals = [addr.strip() for item in qs.get("to", []) for addr in item.split(",") if addr.strip()]
    receivers = to_vals or ([sender] if sender else [])
    return {
        "channel": "email",
        "target": sender,
        "secret": password,
        "token": "",
        "extra": {
            "sender": sender,
            "password": password,
            "receivers": receivers,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
        },
        "secrets": [s for s in (raw, password, sender) if s],
    }


def _parse_notify_url(raw: str) -> dict[str, Any] | None:
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned.lower().startswith("mailto://"):
        return _parse_mailto_uri(cleaned)

    parsed = urlsplit(cleaned)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if scheme in {"pushplus"}:
        token = unquote(parsed.netloc or "").strip()
        topic = unquote(path.strip("/")).strip()
        return {
            "channel": "pushplus",
            "target": token,
            "secret": "",
            "token": "",
            "extra": {"topic": topic},
            "secrets": [s for s in (cleaned, token) if s],
        }
    if scheme in {"sct", "serverchan", "ftqq"}:
        sendkey = unquote((parsed.netloc + path).strip("/")).strip()
        return {
            "channel": "serverchan",
            "target": sendkey,
            "secret": "",
            "token": "",
            "extra": {},
            "secrets": [s for s in (cleaned, sendkey) if s],
        }
    if scheme == "bark":
        key_or_host = parsed.netloc.strip()
        clean_path = path.lstrip("/")
        if clean_path:
            target = f"https://{key_or_host}/{clean_path}"
        elif "." in key_or_host:
            target = f"https://{key_or_host}"
        else:
            target = f"https://api.day.app/{key_or_host}"
        if not _valid_http_target(target):
            return None
        return {
            "channel": "bark",
            "target": target,
            "secret": "",
            "token": "",
            "extra": {},
            "secrets": [s for s in (cleaned, target, key_or_host, *_extract_url_secrets(target)) if s],
        }
    if scheme in {"tgram", "tg"}:
        bot_token = unquote(parsed.netloc or "").strip()
        chat_id = unquote(path.strip("/").split("/", 1)[0]).strip()
        return {
            "channel": "telegram",
            "target": bot_token,
            "secret": "",
            "token": "",
            "extra": {"chat_id": chat_id},
            "secrets": [s for s in (cleaned, bot_token, chat_id) if s],
        }
    if scheme == "ntfy":
        if path.strip("/"):
            target = f"https://{parsed.netloc.strip()}/{path.lstrip('/')}"
        else:
            target = f"https://ntfy.sh/{parsed.netloc.strip()}"
        if not _valid_http_target(target):
            return None
        return {
            "channel": "ntfy",
            "target": target,
            "secret": "",
            "token": "",
            "extra": {},
            "secrets": [s for s in (cleaned, target, *_extract_url_secrets(target)) if s],
        }
    if scheme == "wecom":
        raw_rest = cleaned.split("://", 1)[1].strip()
        if not raw_rest:
            return None
        if raw_rest.lower().startswith(("http://", "https://")):
            if not _valid_http_target(raw_rest):
                return None
            target = raw_rest
            token_val = ""
        else:
            token_val = unquote(raw_rest.strip("/")).strip()
            if not token_val:
                return None
            target = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={token_val}"
        return {
            "channel": "wecom",
            "target": target,
            "secret": "",
            "token": "",
            "extra": {},
            "secrets": [s for s in (cleaned, target, token_val, *_extract_url_secrets(target)) if s],
        }
    if scheme in {"feishu", "lark"}:
        raw_rest = cleaned.split("://", 1)[1].strip()
        if not raw_rest:
            return None
        if raw_rest.lower().startswith(("http://", "https://")):
            target, secret = _strip_fragment_param(raw_rest, "secret")
            if not _valid_http_target(target):
                return None
            token_val = ""
        else:
            without_sec, secret = _strip_fragment_param(cleaned, "secret")
            p2 = urlsplit(without_sec)
            token_val = unquote((p2.netloc + p2.path).strip("/")).strip()
            if not token_val:
                return None
            target = f"https://open.feishu.cn/open-apis/bot/v2/hook/{token_val}"
        return {
            "channel": "feishu",
            "target": target,
            "secret": secret,
            "token": "",
            "extra": {},
            "secrets": [s for s in (cleaned, target, token_val, secret, *_extract_url_secrets(target)) if s],
        }
    if scheme == "dingtalk":
        raw_rest = cleaned.split("://", 1)[1].strip()
        if not raw_rest:
            return None
        if raw_rest.lower().startswith(("http://", "https://")):
            target, secret = _strip_fragment_param(raw_rest, "secret")
            if not _valid_http_target(target):
                return None
            token_val = ""
        else:
            without_sec, secret = _strip_fragment_param(cleaned, "secret")
            p2 = urlsplit(without_sec)
            token_val = unquote((p2.netloc + p2.path).strip("/")).strip()
            if not token_val:
                return None
            target = f"https://oapi.dingtalk.com/robot/send?access_token={token_val}"
        return {
            "channel": "dingtalk",
            "target": target,
            "secret": secret,
            "token": "",
            "extra": {},
            "secrets": [s for s in (cleaned, target, token_val, secret, *_extract_url_secrets(target)) if s],
        }
    if scheme == "discord":
        raw_rest = cleaned.split("://", 1)[1].strip()
        if not raw_rest:
            return None
        if raw_rest.lower().startswith(("http://", "https://")):
            if not _valid_http_target(raw_rest):
                return None
            target = raw_rest
            tail = ""
        else:
            tail = unquote(raw_rest.strip("/")).strip()
            if not tail:
                return None
            target = f"https://discord.com/api/webhooks/{tail}"
        return {
            "channel": "discord",
            "target": target,
            "secret": "",
            "token": "",
            "extra": {},
            "secrets": [s for s in (cleaned, target, tail, *tail.split("/"), *_extract_url_secrets(target)) if s],
        }
    if scheme == "slack":
        raw_rest = cleaned.split("://", 1)[1].strip()
        if not raw_rest:
            return None
        if raw_rest.lower().startswith(("http://", "https://")):
            if not _valid_http_target(raw_rest):
                return None
            target = raw_rest
            tail = ""
        else:
            tail = unquote(raw_rest.strip("/")).strip()
            if not tail:
                return None
            target = f"https://hooks.slack.com/services/{tail}"
        return {
            "channel": "slack",
            "target": target,
            "secret": "",
            "token": "",
            "extra": {},
            "secrets": [s for s in (cleaned, target, tail, *_extract_url_secrets(target)) if s],
        }
    if scheme == "custom":
        inner = cleaned[len("custom://") :].strip()
        if not inner:
            return None
        if not inner.lower().startswith(("http://", "https://")):
            inner = f"https://{inner}"
        target, token = _strip_fragment_param(inner, "token")
        if not _valid_http_target(target):
            return None
        return {
            "channel": "custom",
            "target": target,
            "secret": "",
            "token": token,
            "extra": {},
            "secrets": [s for s in (cleaned, target, token, *_extract_url_secrets(target)) if s],
        }

    if scheme in {"http", "https"}:
        if "qyapi.weixin.qq.com" in host:
            return {"channel": "wecom", "target": cleaned, "secret": "", "token": "", "extra": {}, "secrets": [cleaned, *_extract_url_secrets(cleaned)]}
        if "open.feishu.cn" in host or "open.larksuite.com" in host:
            target, secret = _strip_fragment_param(cleaned, "secret")
            return {
                "channel": "feishu",
                "target": target,
                "secret": secret,
                "token": "",
                "extra": {},
                "secrets": [s for s in (cleaned, target, secret, *_extract_url_secrets(target)) if s],
            }
        if "oapi.dingtalk.com" in host:
            target, secret = _strip_fragment_param(cleaned, "secret")
            return {
                "channel": "dingtalk",
                "target": target,
                "secret": secret,
                "token": "",
                "extra": {},
                "secrets": [s for s in (cleaned, target, secret, *_extract_url_secrets(target)) if s],
            }
        if "pushplus.plus" in host:
            qs = parse_qs(parsed.query)
            token = (qs.get("token") or [""])[0].strip() or path.strip("/").split("/")[-1]
            topic = (qs.get("topic") or [""])[0].strip()
            return {
                "channel": "pushplus",
                "target": token,
                "secret": "",
                "token": "",
                "extra": {"topic": topic},
                "secrets": [s for s in (cleaned, token) if s],
            }
        if "sctapi.ftqq.com" in host or "push.ft07.com" in host:
            return {"channel": "serverchan", "target": cleaned, "secret": "", "token": "", "extra": {}, "secrets": [cleaned, *_extract_url_secrets(cleaned)]}
        if "api.day.app" in host:
            return {"channel": "bark", "target": cleaned, "secret": "", "token": "", "extra": {}, "secrets": [cleaned, *_extract_url_secrets(cleaned)]}
        if "discord.com" in host or "discordapp.com" in host:
            return {"channel": "discord", "target": cleaned, "secret": "", "token": "", "extra": {}, "secrets": [cleaned, *_extract_url_secrets(cleaned)]}
        if "hooks.slack.com" in host:
            return {"channel": "slack", "target": cleaned, "secret": "", "token": "", "extra": {}, "secrets": [cleaned, *_extract_url_secrets(cleaned)]}
        if "ntfy.sh" in host:
            return {"channel": "ntfy", "target": cleaned, "secret": "", "token": "", "extra": {}, "secrets": [cleaned, *_extract_url_secrets(cleaned)]}
        target, token = _strip_fragment_param(cleaned, "token")
        return {
            "channel": "custom",
            "target": target,
            "secret": "",
            "token": token,
            "extra": {},
            "secrets": [s for s in (cleaned, target, token, *_extract_url_secrets(target)) if s],
        }

    return {
        "channel": "apprise",
        "target": cleaned,
        "secret": "",
        "token": "",
        "extra": {},
        "secrets": [cleaned],
    }


def resolve_notify_targets(config: Config) -> list[dict[str, Any]]:
    """Resolve unified NOTIFY_URLS + legacy per-channel config entries in deterministic order."""
    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(entry: dict[str, Any] | None) -> None:
        if not entry or not entry.get("target"):
            return
        extra = entry.get("extra") or {}
        receivers_key = ",".join(
            sorted(str(r).strip() for r in (extra.get("receivers") or []) if str(r).strip())
        )
        dedup_key = (
            str(entry["channel"]),
            str(entry["target"]),
            str(extra.get("chat_id") or extra.get("topic") or receivers_key or ""),
        )
        if dedup_key in seen:
            return
        seen.add(dedup_key)
        targets.append(entry)

    # Legacy explicit config fields retain canonical channel ordering first.
    if config.wecom_webhook_url:
        _add({"channel": "wecom", "target": config.wecom_webhook_url, "secret": "", "token": "", "extra": {}, "secrets": [config.wecom_webhook_url, *_extract_url_secrets(config.wecom_webhook_url)]})
    if config.feishu_webhook_url:
        _add({"channel": "feishu", "target": config.feishu_webhook_url, "secret": config.feishu_webhook_secret, "token": "", "extra": {}, "secrets": [config.feishu_webhook_url, config.feishu_webhook_secret, *_extract_url_secrets(config.feishu_webhook_url)]})
    if config.dingtalk_webhook_url:
        _add({"channel": "dingtalk", "target": config.dingtalk_webhook_url, "secret": config.dingtalk_webhook_secret, "token": "", "extra": {}, "secrets": [config.dingtalk_webhook_url, config.dingtalk_webhook_secret, *_extract_url_secrets(config.dingtalk_webhook_url)]})
    if config.pushplus_token:
        _add({"channel": "pushplus", "target": config.pushplus_token, "secret": "", "token": "", "extra": {"topic": config.pushplus_topic}, "secrets": [config.pushplus_token]})
    if config.serverchan_sendkey:
        _add({"channel": "serverchan", "target": config.serverchan_sendkey, "secret": "", "token": "", "extra": {}, "secrets": [config.serverchan_sendkey]})
    if config.bark_url:
        norm_bark = _parse_notify_url(config.bark_url)
        if norm_bark and norm_bark["channel"] == "bark":
            _add(norm_bark)
        else:
            _add({"channel": "bark", "target": config.bark_url, "secret": "", "token": "", "extra": {}, "secrets": [config.bark_url, *_extract_url_secrets(config.bark_url)]})
    if config.email_sender and config.email_password:
        receivers = [r.strip() for r in (config.email_receivers or "").split(",") if r.strip()] or [config.email_sender]
        _add({
            "channel": "email",
            "target": config.email_sender,
            "secret": config.email_password,
            "token": "",
            "extra": {
                "sender": config.email_sender,
                "password": config.email_password,
                "receivers": receivers,
                "smtp_host": config.email_smtp_host,
                "smtp_port": config.email_smtp_port,
            },
            "secrets": [config.email_sender, config.email_password],
        })
    if config.telegram_bot_token and config.telegram_chat_id:
        _add({"channel": "telegram", "target": config.telegram_bot_token, "secret": "", "token": "", "extra": {"chat_id": config.telegram_chat_id}, "secrets": [config.telegram_bot_token, config.telegram_chat_id]})
    if config.discord_webhook_url:
        _add({"channel": "discord", "target": config.discord_webhook_url, "secret": "", "token": "", "extra": {}, "secrets": [config.discord_webhook_url, *_extract_url_secrets(config.discord_webhook_url)]})
    if config.slack_webhook_url:
        _add({"channel": "slack", "target": config.slack_webhook_url, "secret": "", "token": "", "extra": {}, "secrets": [config.slack_webhook_url, *_extract_url_secrets(config.slack_webhook_url)]})
    if config.ntfy_url:
        norm_ntfy = _parse_notify_url(config.ntfy_url)
        if norm_ntfy and norm_ntfy["channel"] == "ntfy":
            _add(norm_ntfy)
        else:
            _add({"channel": "ntfy", "target": config.ntfy_url, "secret": "", "token": "", "extra": {}, "secrets": [config.ntfy_url, *_extract_url_secrets(config.ntfy_url)]})
    if config.custom_webhook_url:
        _add({"channel": "custom", "target": config.custom_webhook_url, "secret": "", "token": config.custom_webhook_token, "extra": {}, "secrets": [config.custom_webhook_url, config.custom_webhook_token, *_extract_url_secrets(config.custom_webhook_url)]})

    for raw in config.notify_urls:
        _add(_parse_notify_url(raw))

    order = {name: i for i, name in enumerate(SUPPORTED_CHANNELS)}
    targets.sort(key=lambda t: order.get(t["channel"], len(SUPPORTED_CHANNELS)))
    return targets


def configured_channels(config: Config) -> list[str]:
    """Return distinct enabled notification channels in deterministic order."""
    seen: list[str] = []
    for t in resolve_notify_targets(config):
        ch = t["channel"]
        if ch not in seen:
            seen.append(ch)
    return seen


def notify_readiness(config: Config) -> dict[str, Any]:
    """Return non-secret notification channel readiness metadata."""
    targets = resolve_notify_targets(config)
    channels = configured_channels(config)
    return {
        "supported_channels": list(SUPPORTED_CHANNELS),
        "configured_channels": channels,
        "notify_urls_count": len(config.notify_urls),
        "target_count": len(targets),
        "any_configured": bool(channels),
        "wecom_configured": "wecom" in channels,
        "feishu_configured": "feishu" in channels,
        "feishu_signed": any(t["channel"] == "feishu" and bool(t.get("secret")) for t in targets),
        "dingtalk_configured": "dingtalk" in channels,
        "dingtalk_signed": any(t["channel"] == "dingtalk" and bool(t.get("secret")) for t in targets),
        "pushplus_configured": "pushplus" in channels,
        "serverchan_configured": "serverchan" in channels,
        "bark_configured": "bark" in channels,
        "email_configured": "email" in channels,
        "telegram_configured": "telegram" in channels,
        "discord_configured": "discord" in channels,
        "slack_configured": "slack" in channels,
        "ntfy_configured": "ntfy" in channels,
        "custom_configured": "custom" in channels,
        "custom_authenticated": any(t["channel"] == "custom" and bool(t.get("token")) for t in targets),
        "apprise_configured": "apprise" in channels,
        "state_path": str(config.notify_state_path),
    }


def _feishu_sign(timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        msg=b"",
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def _dingtalk_sign(timestamp_ms: int, secret: str) -> str:
    string_to_sign = f"{timestamp_ms}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return quote_plus(base64.b64encode(digest))


_CRED_REDACT_RE = re.compile(
    r'(?i)(["\']?(?:access_token|token|key|secret|password|sendkey)["\']?\s*[:=]\s*["\']?)([^\s&,\'"\}\]]+)'
    r'|(bot\d+:)([A-Za-z0-9_-]+)'
    r'|(Bearer\s+)([^\s,\'"\}\]]+)'
)
_TRANSIENT_HTTP_CODES = frozenset({429, 502, 503, 504, 520, 521, 522, 523, 524})
_NTFY_DATE_RE = re.compile(r"\(([^()]+)\)\s*$")


def _safe_json(resp: Any) -> dict[str, Any]:
    try:
        payload = resp.json()
    except ValueError as exc:
        preview = " ".join(str(getattr(resp, "text", "") or "").split())[:800]
        raise RuntimeError(f"non-JSON response body: {preview or type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"unexpected JSON response type: {type(payload).__name__}")
    return payload


def _float_or(value: object, default: float = 0.0) -> float:
    parsed = finite_float(value)
    return parsed if parsed is not None else default


def _non_neg_int(value: object, default: int = 0) -> int:
    return max(safe_int(value, default=default), 0)


def _retry_delay(resp: Any, default: float = 0.5) -> float:
    if getattr(resp, "status_code", None) == 429:
        headers = getattr(resp, "headers", None)
        if hasattr(headers, "get"):
            ra_raw = headers.get("Retry-After") or headers.get("retry-after")
            if ra_raw is not None:
                parsed = finite_float(str(ra_raw).strip())
                if parsed is not None:
                    return max(0.0, min(parsed, 5.0))
    return default


def _post_with_retry(
    post_fn: Any,
    url: str,
    *,
    max_retries: int = 1,
    sleep_fn: Any = None,
    **kwargs: Any,
) -> Any:
    sleep = sleep_fn or time.sleep
    attempts = _non_neg_int(max_retries, default=1) + 1
    for idx in range(attempts):
        resp = post_fn(url, **kwargs)
        code = getattr(resp, "status_code", None)
        if idx < attempts - 1 and isinstance(code, int) and code in _TRANSIENT_HTTP_CODES:
            sleep(_retry_delay(resp))
            continue
        try:
            resp.raise_for_status()
            return resp
        except requests.HTTPError as exc:
            err_resp = getattr(exc, "response", None)
            err_code = getattr(err_resp, "status_code", code)
            if idx < attempts - 1 and isinstance(err_code, int) and err_code in _TRANSIENT_HTTP_CODES:
                sleep(_retry_delay(err_resp))
                continue
            raise
    return resp  # pragma: no cover


def _ntfy_ascii_title(title: str) -> str:
    ascii_clean = " ".join(title.encode("ascii", "ignore").decode("ascii").split())
    raw_clean = " ".join(title.split())
    if ascii_clean and ascii_clean == raw_clean:
        return ascii_clean
    m = _NTFY_DATE_RE.search(raw_clean)
    if m:
        date_part = " ".join(m.group(1).encode("ascii", "ignore").decode("ascii").split())
        if date_part:
            return f"AlphaSift Daily Brief ({date_part})"
    return "AlphaSift Daily Brief"


def _redact_error(exc: Exception, config: Config, extra_secrets: Sequence[str] = ()) -> str:
    text = f"{type(exc).__name__}: {exc}"
    raw_pool: list[str] = [
        config.wecom_webhook_url,
        config.feishu_webhook_url,
        config.feishu_webhook_secret,
        config.dingtalk_webhook_url,
        config.dingtalk_webhook_secret,
        config.pushplus_token,
        config.serverchan_sendkey,
        config.bark_url,
        config.telegram_bot_token,
        config.telegram_chat_id,
        config.discord_webhook_url,
        config.slack_webhook_url,
        config.ntfy_url,
        config.email_sender,
        config.email_password,
        config.custom_webhook_url,
        config.custom_webhook_token,
        *config.notify_urls,
        *(getattr(config, "tavily_api_keys", ()) or ()),
        *(getattr(config, "serpapi_api_keys", ()) or ()),
        *extra_secrets,
    ]
    expanded: set[str] = set()
    for secret in raw_pool:
        if not secret:
            continue
        expanded.add(secret)
        decoded = unquote(secret)
        if decoded:
            expanded.add(decoded)
        encoded = quote(secret, safe="")
        if encoded:
            expanded.add(encoded)
        for seg in _extract_url_secrets(secret):
            expanded.add(seg)
    for secret in sorted(expanded, key=len, reverse=True):
        text = text.replace(secret, "***")
    text = _CRED_REDACT_RE.sub(
        lambda m: f"{m.group(1) or m.group(3) or m.group(5) or ''}***",
        text,
    )
    return text[:240]


def _load_state(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(path: Path, state: dict[str, dict[str, Any]]) -> None:
    atomic_write_strict_json(path, state, indent=2, trailing_newline=True)


@contextmanager
def _ledger_lock(ledger_path: Path) -> Iterator[None]:
    """Serialize push ledger access across threads and OS processes."""
    lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _PROCESS_LOCK:
        with open(lock_path, "a+", encoding="utf-8") as handle:
            if os.name == "posix":
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            else:
                # Non-POSIX (e.g. Windows): no flock; _PROCESS_LOCK still serializes threads.
                yield


def _safe_http_link(raw: object) -> str:
    cleaned = str(raw or "").strip()
    if not cleaned or any(ch in cleaned for ch in '<>"\'\r\n\t\0'):
        return ""
    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        return cleaned
    return ""


def _has_rich_report(report: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(report, dict)
        and isinstance(report.get("market_regime"), dict)
        and report.get("market_regime")
    )


def _resolved_report_url(report: dict[str, Any]) -> str:
    raw = DEFAULT_DASHBOARD_URL if report.get("detail_url") is None else report.get("detail_url")
    return _safe_http_link(raw)


def _has_market_digest(report: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(report, dict)
        and report.get("object") == "MarketDigest"
        and isinstance(report.get("market_sections"), list)
    )


def _strategy_display_name(
    report: dict[str, Any] | None,
    key: object,
) -> str:
    raw = str(key or "").strip()
    if not raw:
        return ""
    overrides = report.get("strategy_display_names") if isinstance(report, dict) else None
    mapping = resolve_strategy_display_names(
        overrides=overrides if isinstance(overrides, dict) else None
    )
    return mapping.get(raw, raw)


def _format_ann_meta(item: dict[str, Any]) -> tuple[str, str, str]:
    """Return (flags_text, recency_date_tag, cleaned_snippet) for announcement risk item."""
    flags = " / ".join(str(x) for x in (item.get("negative_event_flags") or [])[:2])
    ann_date = str(item.get("announcement_date") or "").strip()
    short_d = ann_date[5:] if len(ann_date) >= 10 else ann_date
    recency = str(item.get("recency") or "").strip()
    if short_d and recency == "old":
        d_tag = f"{short_d}·历史进展"
    elif short_d:
        d_tag = short_d
    elif recency == "old":
        d_tag = "历史进展"
    else:
        d_tag = ""
    raw_snip = item.get("matched_announcement") or item.get("announcement_summary")
    snip = _clean_announcement_snippet(raw_snip, max_len=56)
    return flags, d_tag, snip


def _build_report_title(report: dict[str, Any] | None, *, fallback_title: str) -> str:
    if _has_rich_report(report):
        assert report is not None
        tdate = str(report.get("trade_date") or "").strip()
        short_d = tdate[5:10] if len(tdate) >= 10 else (tdate or "-")
        reg = report.get("market_regime") or {}
        stage_lbl = str(reg.get("regime_stage_label") or "-")
        adv = _float_or(reg.get("advance_ratio_pct"))
        flagged_n = _non_neg_int((report.get("announcement_risks") or {}).get("flagged_count"))
        cons_n = len(((report.get("cross_strategy_synthesis") or {}).get("consensus_picks")) or [])
        stale_tag = "[旧包]" if report.get("pack_is_stale") else ""
        return f"AlphaSift A股日报{stale_tag} ({short_d})｜{stage_lbl}·涨{adv:.0f}%·预警{flagged_n}·共识{cons_n}"
    if _has_market_digest(report):
        assert report is not None
        tdate = str(report.get("trade_date") or "").strip()
        short_d = tdate[5:10] if len(tdate) >= 10 else (tdate or "-")
        mkts = "·".join(str(m).upper() for m in (report.get("markets") or [])) or "GLOBAL"
        return f"AlphaSift 全球市场日报 ({short_d})｜{mkts}"
    return fallback_title


def _split_hit_patterns(report: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (primary_patterns, negative_watch_patterns) with non-zero hits."""
    pat_sec = report.get("patterns") or {}
    active = [p for p in (pat_sec.get("active") or []) if _non_neg_int(p.get("hit_count")) > 0]
    exp = [p for p in (pat_sec.get("experimental") or []) if _non_neg_int(p.get("hit_count")) > 0]
    active.sort(key=lambda p: -_non_neg_int(p.get("hit_count")))
    pos_exp = [p for p in exp if p.get("expectancy_tier") != "negative_watch"]
    neg_exp = [p for p in exp if p.get("expectancy_tier") == "negative_watch"]
    pos_exp.sort(
        key=lambda p: (
            0 if p.get("expectancy_tier") == "positive_watch" else 1,
            -_non_neg_int(p.get("hit_count")),
        )
    )
    neg_exp.sort(key=lambda p: -_non_neg_int(p.get("hit_count")))
    return [*active, *pos_exp], neg_exp


def _render_markdown_digest(
    report: dict[str, Any] | None,
    content: str,
    *,
    title: str,
    wecom_colors: bool = False,
) -> str:
    """Rich Markdown digest shared across WeCom (with color tags), DingTalk, PushPlus & ServerChan."""
    if _has_market_digest(report):
        assert report is not None
        lines = [f"### {title}"]
        for sec in (report.get("market_sections") or [])[:6]:
            m_name = sec.get("market_name") or str(sec.get("market") or "").upper()
            lines.append(f"\n**{m_name}**（{_non_neg_int(sec.get('strategy_count'))} 组策略 · {sec.get('trade_date', '-')}）")
            top_picks = sec.get("top_picks") or []
            if top_picks:
                for p in top_picks[:4]:
                    px_val = finite_float(p.get("price"))
                    px = f" ¥{px_val:.2f}" if px_val is not None else ""
                    chg = f" {_fmt_report_pct(p.get('change_pct'))}" if finite_float(p.get("change_pct")) is not None else ""
                    strats = "·".join((p.get("strategy_display_names") or p.get("strategies") or [])[:2])
                    lines.append(
                        f"- **{p.get('name') or p.get('code')}** `{p.get('code')}`{px}{chg} · "
                        f"{_float_or(p.get('avg_final_score')):.1f}分 ({strats})"
                    )
            else:
                lines.append("- 暂无入选标的")
        mnews = ((report.get("market_news") or {}).get("items") or []) if isinstance(report.get("market_news"), dict) else []
        if mnews:
            lines.append("\n**市场热点快讯**")
            for item in mnews[:3]:
                lines.append(f"- {item.get('title', '')}")
        detail_url = _resolved_report_url(report)
        if detail_url:
            lines.append(f"\n🔗 [查看完整看板]({detail_url})")
        lines.append("\n> 注：量化观测与回测基准，非投资建议。")
        out = "\n".join(lines)
        if wecom_colors:
            while len(out.encode("utf-8")) > 3950 and len(lines) > 4:
                lines.pop(-3)
                out = "\n".join(lines)
        return out

    if not _has_rich_report(report):
        return content

    assert report is not None
    reg = report.get("market_regime") or {}
    stage_lbl = str(reg.get("regime_stage_label") or "-")
    adv = _float_or(reg.get("advance_ratio_pct"))
    med_str = _fmt_report_pct(reg.get("median_return_pct"))
    seal = finite_float(reg.get("seal_rate_pct"))
    seal_str = "-" if seal is None else f"{seal:.1f}%"
    amt = finite_float(reg.get("total_amount_yi"))
    amt_str = "-" if amt is None else f"{amt:,.0f} 亿"
    prev_str = _fmt_report_pct(reg.get("prev_limit_up_avg_return_pct"))
    lu = _non_neg_int(reg.get("non_st_limit_up_count"))
    ld = _non_neg_int(reg.get("non_st_limit_down_count"))
    max_streak = _non_neg_int(reg.get("max_consecutive_limit_up"))

    if wecom_colors:
        head_line = f'### {title}\n> 盘面：<font color="info">{stage_lbl}</font>｜上涨 <font color="warning">{adv:.1f}%</font>（中位 {med_str}）｜涨跌停 {lu}/{ld}（封板 {seal_str}）｜最高 {max_streak}板 · 昨涨停 {prev_str} · 成交 {amt_str}'
    else:
        head_line = f"### {title}\n> 盘面 **{stage_lbl}**｜上涨 {adv:.1f}%（中位 {med_str}）｜涨跌停 {lu}/{ld}（封板 {seal_str}）｜最高 {max_streak}板 · 昨涨停 {prev_str} · 成交 {amt_str}"
    lines = [head_line]
    if report.get("pack_is_stale"):
        lines.append(f"> ⚠️ 旧包降级：包日期 {report.get('pack_trade_date', '-')} < {report.get('expected_trade_date', '-')}")

    ann = report.get("announcement_risks") or {}
    flagged = ann.get("flagged_items") or []
    checked = _non_neg_int(ann.get("checked_count"))
    if flagged:
        tag_open, tag_close = ('<font color="warning">', "</font>") if wecom_colors else ("", "")
        lines.append(f"\n**{tag_open}⚠️ 公告排雷预警（{checked}检/{len(flagged)}中）{tag_close}**")
        for item in flagged[:5]:
            flags, d_tag, snip = _format_ann_meta(item)
            meta = f"[{d_tag} · {flags}]" if d_tag else f"[{flags}]"
            lines.append(f"- **{item.get('code', '')} {item.get('name', '')}** {meta}" + (f"：{snip}" if snip else ""))
    elif checked > 0:
        lines.append(f"\n**✅ 公告排雷**：抽检 {checked} 只重点候选无异常")

    brief = report.get("ai_brief") or {}
    if brief.get("headline"):
        lbl = "🤖 AI 盘后综述" if brief.get("mode") == "llm" else "📌 盘后盘面摘要"
        lines.append(f"\n**{lbl}**：{str(brief['headline']).strip()}")
        sub_b = str(brief.get("consensus_and_ai_edge") or brief.get("regime_interpretation") or "").strip()
        if sub_b:
            lines.append(sub_b[:220])

    mnews = ((report.get("market_news") or {}).get("items") or []) if isinstance(report.get("market_news"), dict) else []
    if mnews:
        lines.append("\n**📰 市场热点快讯**")
        for item in mnews[:4]:
            t_str = f" ({item.get('published_at')})" if item.get("published_at") else ""
            lines.append(f"- [{item.get('category') or '要闻'}] {item.get('title', '')}{t_str}")

    syn = report.get("cross_strategy_synthesis") or {}
    consensus = syn.get("consensus_picks") or []
    if consensus:
        lines.append(f"\n**🎯 跨策略共识精选（Top {min(6, len(consensus))}/{len(consensus)}）**")
        for idx, c in enumerate(consensus[:6], start=1):
            strats = "·".join(_strategy_display_name(report, s) for s in (c.get("strategies") or [])[:3])
            px_val = finite_float(c.get("price"))
            pe_val = finite_float(c.get("pe_ratio"))
            px = f" ¥{px_val:.2f}" if px_val is not None else ""
            pe = f" PE {pe_val:.1f}" if pe_val is not None else ""
            chg = f" {_fmt_report_pct(c.get('change_pct'))}" if finite_float(c.get("change_pct")) is not None else ""
            lines.append(
                f"{idx}. **{c.get('name', '')}** `{c.get('code', '')}`{px}{pe}{chg} · "
                f"{_non_neg_int(c.get('strategy_count'))}策略（{strats}）"
            )

    primary_pats, neg_pats = _split_hit_patterns(report)
    if primary_pats or neg_pats:
        lines.append("\n**📡 形态雷达触发**")
        for p in (primary_pats or neg_pats)[:4]:
            tag = "active" if p.get("status") == "active" else "观察期"
            net_val = finite_float(p.get("replay_t5_net_excess_pct"))
            net_s = f" · T+5净{net_val:+.2f}%" if net_val is not None else ""
            sigs = "、".join(
                f"{s.get('name') or s.get('code')}({_fmt_report_pct(s.get('change_pct'))})"
                for s in (p.get("signals") or [])[:3]
            )
            lines.append(f"- **{p.get('display_name') or p.get('pattern')}**（{_non_neg_int(p.get('hit_count'))}只 · {tag}{net_s}）：{sigs}")
        if primary_pats and neg_pats:
            neg_txt = "、".join(f"{p.get('display_name')}({_non_neg_int(p.get('hit_count'))})" for p in neg_pats)
            lines.append(f"- 负期望形态（仅供参考）：{neg_txt}")

    detail_url = _resolved_report_url(report)
    if detail_url:
        lines.append(f"\n🔗 [打开在线交互看板（K线 & T+N实盘验证）]({detail_url})")
    lines.append("\n> 注：量化形态观测与回测基准，非投资建议。")
    out = "\n".join(lines)
    if wecom_colors:
        while len(out.encode("utf-8")) > 3950 and len(lines) > 5:
            lines.pop(-2)
            out = "\n".join(lines)
    return out


def _send_wecom(
    webhook_url: str,
    content: str,
    *,
    title: str = "",
    report: dict[str, Any] | None = None,
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    body_text = _render_markdown_digest(report, content, title=title or "AlphaSift 日报", wecom_colors=True)
    resp = _post_with_retry(
        post_fn,
        webhook_url,
        json={"msgtype": "markdown", "markdown": {"content": body_text}},
        timeout=timeout_sec,
    )
    payload = _safe_json(resp)
    if int(payload.get("errcode", -1)) != 0:
        raise RuntimeError(f"wecom errcode={payload.get('errcode')} errmsg={payload.get('errmsg', '')}")


def _stage_palette(stage: str) -> tuple[str, str, str]:
    """Return (bg, fg, feishu_template) for CN market regime stage."""
    if stage in {"freezing", "ebb"}:
        return "#FEF2F2", "#DC2626", "red"
    if stage in {"startup", "main_up"}:
        return "#ECFDF5", "#059669", "green"
    if stage == "divergence":
        return "#FFFBEB", "#D97706", "orange"
    return "#F1F5F9", "#475569", "blue"


def _fmt_report_pct(val: object) -> str:
    num = finite_float(val)
    if num is None:
        return "–"
    return f"{num:+.2f}%"


def _build_feishu_card(
    report: dict[str, Any] | None,
    content: str,
    *,
    title: str,
) -> dict[str, Any]:
    if _has_market_digest(report):
        assert report is not None
        elements: list[dict[str, Any]] = []
        for sec in (report.get("market_sections") or [])[:6]:
            m_name = sec.get("market_name") or str(sec.get("market") or "").upper()
            lines = [f"**🌍 {m_name}**（{_non_neg_int(sec.get('strategy_count'))} 组策略 · {sec.get('trade_date', '-')}）"]
            top_picks = sec.get("top_picks") or []
            if top_picks:
                for p in top_picks[:4]:
                    px_val = finite_float(p.get("price"))
                    px = f" · ¥{px_val:.2f}" if px_val is not None else ""
                    chg = f" · {_fmt_report_pct(p.get('change_pct'))}" if finite_float(p.get("change_pct")) is not None else ""
                    strats = "·".join((p.get("strategy_display_names") or p.get("strategies") or [])[:2])
                    lines.append(
                        f"- **{p.get('name') or p.get('code')}** `{p.get('code')}`{px}{chg} · "
                        f"{_float_or(p.get('avg_final_score')):.1f}分（{strats}）"
                    )
            else:
                lines.append("- 今日暂无入选标的")
            elements.append({"tag": "markdown", "content": "\n".join(lines)})
        mnews = ((report.get("market_news") or {}).get("items") or []) if isinstance(report.get("market_news"), dict) else []
        if mnews:
            n_lines = ["**📰 市场热点快讯**", *(f"- {n.get('title', '')}" for n in mnews[:3])]
            elements.append({"tag": "markdown", "content": "\n".join(n_lines)})
        detail_url = _resolved_report_url(report)
        if detail_url:
            elements.append({
                "tag": "action",
                "actions": [{
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "打开在线交互看板与历史战绩"},
                    "type": "primary",
                    "url": detail_url,
                }],
            })
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
            "elements": elements,
        }

    if not _has_rich_report(report):
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
            "elements": [{"tag": "markdown", "content": content}],
        }

    assert report is not None
    reg = report.get("market_regime") or {}
    stage = str(reg.get("regime_stage") or "")
    stage_lbl = str(reg.get("regime_stage_label") or "-")
    _, _, tmpl = _stage_palette(stage)
    ann = report.get("announcement_risks") or {}
    flagged = ann.get("flagged_items") or []
    checked = _non_neg_int(ann.get("checked_count"))
    if report.get("pack_is_stale"):
        tmpl = "orange"
    elif flagged:
        tmpl = "red"

    seal = finite_float(reg.get("seal_rate_pct"))
    seal_str = "-" if seal is None else f"{seal:.1f}%"
    prev_ret = finite_float(reg.get("prev_limit_up_avg_return_pct"))
    prev_str = "-" if prev_ret is None else f"{prev_ret:+.2f}%"
    amt = finite_float(reg.get("total_amount_yi"))
    amt_str = "-" if amt is None else f"{amt:,.0f} 亿"
    med = finite_float(reg.get("median_return_pct"))
    med_str = "-" if med is None else f"{med:+.2f}%"
    adv_str = f"{_float_or(reg.get('advance_ratio_pct')):.1f}%"
    lu = _non_neg_int(reg.get("non_st_limit_up_count"))
    ld = _non_neg_int(reg.get("non_st_limit_down_count"))
    max_streak = _non_neg_int(reg.get("max_consecutive_limit_up"))

    elements: list[dict[str, Any]] = []
    if report.get("pack_is_stale"):
        elements.append({
            "tag": "markdown",
            "content": (
                f"⚠️ **旧包降级提示**：当前包日期 `{report.get('pack_trade_date', '-')}` "
                f"落后于目标交易日 `{report.get('expected_trade_date', '-')}`，仅供参考"
            ),
        })

    elements.append({
        "tag": "div",
        "fields": [
            {
                "is_short": True,
                "text": {"tag": "lark_md", "content": f"**盘面温度（{stage_lbl}）**\n上涨 {adv_str} · 中位 {med_str}"},
            },
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**非ST涨跌停 / 封板**\n"
                        f"{lu} 涨停 / {ld} 跌停 · {seal_str}"
                    ),
                },
            },
            {
                "is_short": True,
                "text": {"tag": "lark_md", "content": f"**连板与昨涨停**\n最高 {max_streak} 板 · 昨涨停 {prev_str}"},
            },
            {
                "is_short": True,
                "text": {"tag": "lark_md", "content": f"**两市成交额**\n{amt_str}"},
            },
        ],
    })
    elements.append({"tag": "hr"})

    # Alert-first Announcement risk block with date & recency
    if flagged:
        ann_lines = [f"**⚠️ 公告排雷预警（抽检 {checked} 只，命中 {len(flagged)} 只预警）**"]
        for item in flagged[:5]:
            flags, d_tag, snip = _format_ann_meta(item)
            meta = f"[{d_tag} · {flags}]" if d_tag else f"[{flags}]"
            line = f"- **{item.get('code', '')} {item.get('name', '')}** {meta}"
            if snip:
                line += f"：{snip}"
            ann_lines.append(line)
        if len(flagged) > 5:
            ann_lines.append(f"- 其余 {len(flagged) - 5} 条请查看完整研报或看板")
        elements.append({"tag": "markdown", "content": "\n".join(ann_lines)})
    elif checked > 0 and ann.get("errors"):
        elements.append({"tag": "markdown", "content": f"**⚠️ 公告排雷降级**：抽检 {checked} 只（{str(ann['errors'][0])[:60]}）"})
    elif checked > 0:
        elements.append({"tag": "markdown", "content": f"**✅ 公告排雷通过**：抽检 {checked} 只重点候选，未检出高风险实质性负面公告"})

    # Brief summary
    brief = report.get("ai_brief") or {}
    if brief.get("headline"):
        brief_lbl = f"🤖 AI 盘后综述 ({brief.get('model')})" if brief.get("mode") == "llm" and brief.get("model") else ("🤖 AI 盘后综述" if brief.get("mode") == "llm" else "📌 盘后盘面摘要")
        b_lines = [f"**{brief_lbl}**：{str(brief['headline']).strip()}"]
        if brief.get("consensus_and_ai_edge"):
            b_lines.append(str(brief["consensus_and_ai_edge"]).strip())
        elif brief.get("regime_interpretation"):
            b_lines.append(str(brief["regime_interpretation"]).strip())
        elements.append({"tag": "markdown", "content": "\n".join(b_lines)})

    # Market News highlights
    mnews = ((report.get("market_news") or {}).get("items") or []) if isinstance(report.get("market_news"), dict) else []
    if mnews:
        n_lines = ["**📰 市场热点与政策快讯**"]
        for item in mnews[:4]:
            pub = f"（{item.get('published_at')}）" if item.get("published_at") else ""
            n_lines.append(f"- **[{item.get('category') or '要闻'}]** {item.get('title', '')}{pub}")
        elements.append({"tag": "markdown", "content": "\n".join(n_lines)})

    # Multi-strategy consensus table-like list with Chinese strategy names, valuation & reasons
    syn = report.get("cross_strategy_synthesis") or {}
    consensus = syn.get("consensus_picks") or []
    strategies = report.get("strategies") or []
    if consensus:
        c_lines = [f"**🎯 跨策略高共识精选（共 {len(consensus)} 只，展示 Top 5）**"]
        for idx, c in enumerate(consensus[:5], start=1):
            risk_tag = " ⚠️" if c.get("announcement_risk_flags") else ""
            px_val = finite_float(c.get("price"))
            pe_val = finite_float(c.get("pe_ratio"))
            sc_val = finite_float(c.get("avg_final_score"))
            chg = f" · {_fmt_report_pct(c.get('change_pct'))}" if finite_float(c.get("change_pct")) is not None else ""
            px = f" · ¥{px_val:.2f}" if px_val is not None else ""
            pe = f" · PE {pe_val:.1f}" if pe_val is not None else ""
            sc_txt = f" · 均分 {sc_val:.1f}" if sc_val is not None else ""
            ind = str(c.get("industry") or "-")
            strats_cn = "·".join(_strategy_display_name(report, s) for s in (c.get("strategies") or [])[:3])
            strat_part = f"（{strats_cn}）" if strats_cn else ""
            c_lines.append(
                f"{idx}. **{c.get('name', '')}** `{c.get('code', '')}`{risk_tag} · {ind}{px}{pe}{chg} · "
                f"**{_non_neg_int(c.get('strategy_count'))} 策略**{strat_part}{sc_txt}"
            )
            if c.get("reasons"):
                c_lines.append(f"   理由：{str(c['reasons'][0])[:48]}")
        elements.append({"tag": "markdown", "content": "\n".join(c_lines)})
    elif not strategies:
        elements.append({"tag": "markdown", "content": "**🎯 策略概览**：当日未附带 CN 策略选股运行，下方展示盘后形态扫描结果"})

    # Pattern radar hits tiered by historical expectancy
    primary_pats, neg_pats = _split_hit_patterns(report)
    if primary_pats or neg_pats:
        p_lines = ["**📡 形态雷达触发**"]
        for p in (primary_pats or neg_pats)[:4]:
            tag = "active" if p.get("status") == "active" else "观察期"
            net_val = finite_float(p.get("replay_t5_net_excess_pct"))
            net_s = f" · T+5净{net_val:+.2f}%" if net_val is not None else ""
            sigs = "、".join(
                f"{s.get('name') or s.get('code')}({s.get('code')}, {_fmt_report_pct(s.get('change_pct'))})"
                for s in (p.get("signals") or [])[:3]
            )
            p_lines.append(
                f"- **{p.get('display_name') or p.get('pattern')}**（{_non_neg_int(p.get('hit_count'))} 只 · {tag}{net_s}）"
                + (f"：{sigs}" if sigs else "")
            )
        if primary_pats and neg_pats:
            neg_txt = "、".join(f"{p.get('display_name')}({_non_neg_int(p.get('hit_count'))}只)" for p in neg_pats)
            p_lines.append(f"- 负期望形态仅供参考：{neg_txt}")
        elements.append({"tag": "markdown", "content": "\n".join(p_lines)})

    elements.append({"tag": "hr"})
    detail_url = _resolved_report_url(report)
    if detail_url:
        elements.append({
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "打开在线交互看板（20日K线 & T+N实盘验证）"},
                "type": "primary",
                "url": detail_url,
            }],
        })
    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": "AlphaSift · 开源量化选股与 T+N 验证基准 · 历史统计不含分红，不构成投资建议",
        }],
    })
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": tmpl},
        "elements": elements,
    }


def _render_telegram_html(
    report: dict[str, Any] | None,
    content: str,
    *,
    title: str,
) -> str:
    esc = html_lib.escape
    if _has_market_digest(report):
        assert report is not None
        parts: list[str] = [
            f"🌍 <b>{esc(title)}</b>",
        ]
        for sec in (report.get("market_sections") or [])[:6]:
            m_name = sec.get("market_name") or str(sec.get("market") or "").upper()
            lines = [f"\n<b>{esc(m_name)}</b>（{_non_neg_int(sec.get('strategy_count'))}组策略 · <code>{esc(str(sec.get('trade_date', '-')))}</code>）"]
            for p in (sec.get("top_picks") or [])[:4]:
                px_val = finite_float(p.get("price"))
                px = f" ¥{px_val:.2f}" if px_val is not None else ""
                chg = f" {_fmt_report_pct(p.get('change_pct'))}" if finite_float(p.get("change_pct")) is not None else ""
                strats = "·".join((p.get("strategy_display_names") or p.get("strategies") or [])[:2])
                lines.append(
                    f"• <b>{esc(str(p.get('name') or p.get('code')))}</b> <code>{esc(str(p.get('code')))}</code>"
                    f"{esc(px)}{esc(chg)} · {_float_or(p.get('avg_final_score')):.1f}分（{esc(strats)}）"
                )
            parts.append("\n".join(lines))
        detail_url = _resolved_report_url(report)
        tail = (
            f'\n🔗 <a href="{esc(detail_url, quote=True)}">查看完整看板</a>\n'
            if detail_url
            else "\n"
        ) + "<i>注：仅作量化观测与回测基准，不构成投资建议。</i>"
        out = "\n".join(parts) + tail
        return out[:3990] + ("…" if len(out) > 3990 else "")

    if not _has_rich_report(report):
        lines = [f"<b>{esc(title)}</b>"]
        for raw_line in content.splitlines():
            s = raw_line.strip()
            if not s:
                continue
            s_esc = esc(s)
            s_esc = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s_esc)
            if s_esc.startswith("&gt; "):
                lines.append(f"<blockquote>{s_esc[5:]}</blockquote>")
            else:
                lines.append(s_esc)
        out = "\n".join(lines)
        return out[:3990] + ("…" if len(out) > 3990 else "")

    assert report is not None
    reg = report.get("market_regime") or {}
    seal = finite_float(reg.get("seal_rate_pct"))
    seal_str = "-" if seal is None else f"{seal:.1f}%"
    prev_ret = finite_float(reg.get("prev_limit_up_avg_return_pct"))
    prev_str = "-" if prev_ret is None else f"{prev_ret:+.2f}%"
    amt = finite_float(reg.get("total_amount_yi"))
    amt_str = "-" if amt is None else f"{amt:,.0f} 亿"
    med = finite_float(reg.get("median_return_pct"))
    med_str = "-" if med is None else f"{med:+.2f}%"
    adv = _float_or(reg.get("advance_ratio_pct"))
    lu = _non_neg_int(reg.get("non_st_limit_up_count"))
    ld = _non_neg_int(reg.get("non_st_limit_down_count"))
    max_streak = _non_neg_int(reg.get("max_consecutive_limit_up"))

    parts = [
        f"📊 <b>AlphaSift · A 股盘后观察</b> <code>{esc(str(report.get('trade_date', '-')))}</code>",
    ]
    if report.get("pack_is_stale"):
        parts.append(
            f"⚠️ <b>旧包降级</b>：包日期 <code>{esc(str(report.get('pack_trade_date', '-')))}</code> "
            f"&lt; 目标 <code>{esc(str(report.get('expected_trade_date', '-')))}</code>"
        )
    parts.append(
        "<blockquote>"
        f"<b>盘面 · {esc(str(reg.get('regime_stage_label', '-')))}</b>｜上涨 <b>{adv:.1f}%</b>（中位 {esc(med_str)}）\n"
        f"涨跌停 <b>{lu}/{ld}</b>（封板 {esc(seal_str)}）｜"
        f"最高 {max_streak}板 · 昨涨停 {esc(prev_str)} · 成交 {esc(amt_str)}"
        "</blockquote>"
    )

    ann = report.get("announcement_risks") or {}
    flagged = ann.get("flagged_items") or []
    checked = _non_neg_int(ann.get("checked_count"))
    if flagged:
        ann_lines = [f"\n⚠️ <b>公告排雷预警</b>（{checked}检 / {len(flagged)}中）"]
        for item in flagged[:4]:
            flags, d_tag, snip = _format_ann_meta(item)
            meta = f"[{d_tag} · {flags}]" if d_tag else f"[{flags}]"
            ann_lines.append(
                f"• <code>{esc(str(item.get('code', '')))}</code> <b>{esc(str(item.get('name', '')))}</b> "
                f"{esc(meta)}" + (f"：{esc(snip)}" if snip else "")
            )
        parts.append("\n".join(ann_lines))
    elif checked > 0:
        parts.append(f"\n✅ <b>公告排雷</b>：抽检 {checked} 只重点候选无实质风险")

    brief = report.get("ai_brief") or {}
    if brief.get("headline"):
        lbl = "🤖 AI 盘后综述" if brief.get("mode") == "llm" else "📌 盘后盘面摘要"
        b_txt = f"\n<b>{lbl}</b>\n{esc(str(brief['headline']).strip())}"
        summary_line = str(brief.get("consensus_and_ai_edge") or brief.get("regime_interpretation") or brief.get("market_summary") or "").strip()
        if summary_line:
            b_txt += f"\n{esc(summary_line[:180])}"
        parts.append(b_txt)

    mnews = ((report.get("market_news") or {}).get("items") or []) if isinstance(report.get("market_news"), dict) else []
    if mnews:
        n_lines = ["\n📰 <b>市场热点快讯</b>"]
        for item in mnews[:3]:
            n_lines.append(f"• [{esc(str(item.get('category') or '要闻'))}] {esc(str(item.get('title') or ''))}")
        parts.append("\n".join(n_lines))

    syn = report.get("cross_strategy_synthesis") or {}
    consensus = syn.get("consensus_picks") or []
    if consensus:
        c_lines = [f"\n🎯 <b>跨策略高共识精选（Top {min(5, len(consensus))}/{len(consensus)}）</b>"]
        for idx, c in enumerate(consensus[:5], start=1):
            risk_mark = " ⚠️" if c.get("announcement_risk_flags") else ""
            px_val = finite_float(c.get("price"))
            sc_val = finite_float(c.get("avg_final_score"))
            px = f" ¥{px_val:.2f}" if px_val is not None else ""
            chg = f" · {_fmt_report_pct(c.get('change_pct'))}" if finite_float(c.get("change_pct")) is not None else ""
            sc_txt = f" · {sc_val:.1f}分" if sc_val is not None else ""
            strats_cn = "·".join(_strategy_display_name(report, s) for s in (c.get("strategies") or [])[:2])
            c_lines.append(
                f"{idx}. <b>{esc(str(c.get('name', '')))}</b> <code>{esc(str(c.get('code', '')))}</code>{risk_mark}{esc(px)} · "
                f"{esc(str(c.get('industry') or '-'))} · <b>{_non_neg_int(c.get('strategy_count'))}策略</b>"
                + (f"({esc(strats_cn)})" if strats_cn else "")
                + f"{esc(sc_txt)}{esc(chg)}"
            )
        parts.append("\n".join(c_lines))

    primary_pats, neg_pats = _split_hit_patterns(report)
    if primary_pats or neg_pats:
        p_lines = ["\n📡 <b>形态雷达触发</b>"]
        for p in (primary_pats or neg_pats)[:4]:
            tag = "active" if p.get("status") == "active" else "观察期"
            sigs = "、".join(
                f"{esc(str(s.get('name') or s.get('code')))} {esc(_fmt_report_pct(s.get('change_pct')))}"
                for s in (p.get("signals") or [])[:3]
            )
            p_lines.append(
                f"• <b>{esc(str(p.get('display_name') or p.get('pattern')))}</b>"
                f"（{_non_neg_int(p.get('hit_count'))}只 · {tag}）" + (f"：{sigs}" if sigs else "")
            )
        parts.append("\n".join(p_lines))

    detail_url = _resolved_report_url(report)
    footer_lines: list[str] = []
    if detail_url:
        footer_lines.append(
            f'\n🔗 <a href="{esc(detail_url, quote=True)}">打开在线交互看板（20日K线 &amp; T+N验证）</a>'
        )
    footer_lines.append("<i>注：仅作量化形态观测与回测基准，不构成投资建议。</i>")
    tail = "\n".join(footer_lines)

    body = "\n".join(parts)
    max_body = 4000 - len(tail) - 1
    if len(body) > max_body:
        kept: list[str] = []
        used = 0
        for block in parts:
            add = len(block) + (1 if kept else 0)
            if used + add <= max_body - 16:
                kept.append(block)
                used += add
            else:
                break
        body = "\n".join(kept) if kept else esc(str(report.get("trade_date", "")))
    return f"{body}\n{tail}"


def _render_email_html(
    report: dict[str, Any] | None,
    content: str,
    *,
    title: str,
) -> str:
    esc = html_lib.escape
    font_stack = "-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei','Segoe UI',Roboto,Helvetica,Arial,sans-serif"
    mono_stack = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"

    if _has_market_digest(report):
        assert report is not None
        sections_m: list[str] = []
        for sec in (report.get("market_sections") or [])[:7]:
            m_name = str(sec.get("market_name") or str(sec.get("market") or "").upper())
            bench = str(sec.get("benchmark") or "")
            m_date = str(sec.get("trade_date") or "-")
            top_picks = sec.get("top_picks") or []
            if top_picks:
                rows_html = []
                for idx, p in enumerate(top_picks[:6], start=1):
                    px_val = finite_float(p.get("price"))
                    px_s = f"¥{px_val:.2f}" if (sec.get("market") == "cn" and px_val is not None) else (f"{px_val:.2f}" if px_val is not None else "–")
                    cv = finite_float(p.get("change_pct"))
                    ccol = "#DC2626" if (cv is not None and cv > 0) else ("#059669" if (cv is not None and cv < 0) else "#475569")
                    strats = " · ".join(str(x) for x in (p.get("strategy_display_names") or p.get("strategies") or [])[:3])
                    rows_html.append(
                        f'<tr style="border-bottom:1px solid #F1F5F9;">'
                        f'<td style="padding:7px 8px;font-size:12px;color:#64748B;font-family:{mono_stack};">{idx}</td>'
                        f'<td style="padding:7px 8px;font-size:13px;color:#0F172A;"><strong>{esc(str(p.get("name") or p.get("code")))}</strong> '
                        f'<code style="font-size:11px;color:#64748B;font-family:{mono_stack};">{esc(str(p.get("code", "")))}</code>'
                        f'<div style="font-size:11px;color:#64748B;">{esc(str(p.get("industry") or "-"))} · {esc(strats)}</div></td>'
                        f'<td style="padding:7px 8px;text-align:right;font-size:12px;font-family:{mono_stack};color:#0F172A;">{esc(px_s)}</td>'
                        f'<td style="padding:7px 8px;text-align:right;font-size:12px;font-family:{mono_stack};color:#0F172A;">{_float_or(p.get("avg_final_score")):.1f}</td>'
                        f'<td style="padding:7px 8px;text-align:right;font-size:12px;font-weight:700;font-family:{mono_stack};color:{ccol};">{esc(_fmt_report_pct(cv))}</td></tr>'
                    )
                tbl = (
                    '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">'
                    '<thead><tr style="background:#F8FAFC;"><th style="padding:6px 8px;text-align:left;font-size:11px;color:#64748B;">#</th>'
                    '<th style="padding:6px 8px;text-align:left;font-size:11px;color:#64748B;">标的 / 行业 / 策略</th>'
                    '<th style="padding:6px 8px;text-align:right;font-size:11px;color:#64748B;">现价</th>'
                    '<th style="padding:6px 8px;text-align:right;font-size:11px;color:#64748B;">得分</th>'
                    '<th style="padding:6px 8px;text-align:right;font-size:11px;color:#64748B;">涨跌</th></tr></thead>'
                    f'<tbody>{"".join(rows_html)}</tbody></table>'
                )
            else:
                tbl = '<div style="padding:12px;color:#64748B;font-size:12px;">今日该市场暂无入选候选。</div>'
            sections_m.append(
                f'<div style="border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;margin-bottom:14px;">'
                f'<div style="padding:10px 14px;background:#F8FAFC;border-bottom:1px solid #E2E8F0;font-size:13px;font-weight:700;color:#0F172A;">'
                f'🌍 {esc(m_name)} <span style="font-weight:500;font-size:12px;color:#64748B;">· {esc(bench)} · {esc(m_date)} · {_non_neg_int(sec.get("strategy_count"))} 组策略</span></div>'
                f'{tbl}</div>'
            )
        mnews = ((report.get("market_news") or {}).get("items") or []) if isinstance(report.get("market_news"), dict) else []
        if mnews:
            n_items = "".join(f'<li style="margin:4px 0;font-size:13px;color:#334155;">{esc(str(n.get("title") or ""))}</li>' for n in mnews[:5])
            sections_m.append(
                f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:12px 16px;margin-bottom:14px;">'
                f'<div style="font-size:13px;font-weight:700;color:#0F172A;margin-bottom:6px;">📰 市场热点快讯</div>'
                f'<ul style="margin:0;padding-left:18px;">{n_items}</ul></div>'
            )
        detail_url = _resolved_report_url(report)
        cta = (
            f'<div style="text-align:center;margin:18px 0 6px 0;"><a href="{esc(detail_url, quote=True)}" target="_blank" rel="noopener" '
            f'style="display:inline-block;background:#2563EB;color:#FFFFFF;text-decoration:none;font-size:14px;font-weight:700;padding:10px 22px;border-radius:8px;">打开在线交互看板与历史战绩</a></div>'
            if detail_url
            else ""
        )
        return (
            f'<!doctype html><html><body style="margin:0;padding:24px 12px;background:#F1F5F9;font-family:{font_stack};">'
            f'<div style="max-width:680px;margin:0 auto;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;overflow:hidden;">'
            f'<div style="background:#0F172A;color:#F8FAFC;padding:18px 24px;">'
            f'<div style="font-size:11px;letter-spacing:0.06em;color:#93C5FD;font-weight:700;">ALPHASIFT GLOBAL</div>'
            f'<div style="font-size:19px;font-weight:700;margin-top:4px;">{esc(title)}</div></div>'
            f'<div style="padding:20px 24px;">{"".join(sections_m)}{cta}</div>'
            f'<div style="padding:12px 24px;background:#F8FAFC;border-top:1px solid #E2E8F0;font-size:11px;color:#64748B;">AlphaSift · 开源量化选股与回测基准 · 非投资建议</div>'
            f'</div></body></html>'
        )

    if not _has_rich_report(report):
        body_rows: list[str] = []
        for raw_line in content.splitlines():
            s = raw_line.strip()
            if not s:
                continue
            s_esc = esc(s)
            s_esc = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s_esc)
            if s_esc.startswith("&gt; "):
                body_rows.append(
                    f'<div style="background:#F8FAFC;border-left:3px solid #2563EB;padding:10px 14px;'
                    f'margin:8px 0;border-radius:0 6px 6px 0;color:#334155;font-size:14px;line-height:1.6;">{s_esc[5:]}</div>'
                )
            else:
                body_rows.append(f'<p style="margin:6px 0;color:#1E293B;font-size:14px;line-height:1.65;">{s_esc}</p>')
        inner = "".join(body_rows) or f'<p style="margin:0;color:#334155;">{esc(content)}</p>'
        return (
            f'<!doctype html><html><body style="margin:0;padding:24px 12px;background:#F1F5F9;font-family:{font_stack};">'
            f'<div style="max-width:660px;margin:0 auto;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;overflow:hidden;">'
            f'<div style="background:#0F172A;color:#F8FAFC;padding:18px 24px;">'
            f'<div style="font-size:11px;letter-spacing:0.08em;color:#93C5FD;font-weight:700;text-transform:uppercase;">AlphaSift</div>'
            f'<div style="font-size:19px;font-weight:700;margin-top:4px;">{esc(title)}</div></div>'
            f'<div style="padding:20px 24px;">{inner}</div></div></body></html>'
        )

    assert report is not None
    reg = report.get("market_regime") or {}
    stage = str(reg.get("regime_stage") or "")
    stage_lbl = str(reg.get("regime_stage_label") or "-")
    st_bg, st_fg, _ = _stage_palette(stage)
    adv = _float_or(reg.get("advance_ratio_pct"))
    adv_color = "#DC2626" if adv >= 50.0 else "#059669"
    med = reg.get("median_return_pct")
    med_str = _fmt_report_pct(med)
    seal = finite_float(reg.get("seal_rate_pct"))
    seal_str = "–" if seal is None else f"{seal:.1f}%"
    prev_ret = reg.get("prev_limit_up_avg_return_pct")
    prev_str = _fmt_report_pct(prev_ret)
    amt = finite_float(reg.get("total_amount_yi"))
    amt_str = "–" if amt is None else f"{amt:,.0f} 亿"
    dist = reg.get("return_distribution") or {}
    up_cnt = _non_neg_int(reg.get("up_count") or sum(_non_neg_int(dist.get(k)) for k in ("pos0_3", "pos3_7", "ge_pos7")))
    flat_cnt = _non_neg_int(reg.get("flat_count") or _non_neg_int(dist.get("flat")))
    down_cnt = _non_neg_int(reg.get("down_count") or sum(_non_neg_int(dist.get(k)) for k in ("le_neg7", "neg7_neg3", "neg3_0")))
    lu_cnt = _non_neg_int(reg.get("non_st_limit_up_count"))
    ld_cnt = _non_neg_int(reg.get("non_st_limit_down_count"))
    max_streak = _non_neg_int(reg.get("max_consecutive_limit_up"))

    sections: list[str] = []
    if report.get("pack_is_stale"):
        sections.append(
            f'<div style="background:#FFFBEB;border:1px solid #FDE68A;border-left:4px solid #D97706;'
            f'border-radius:8px;padding:10px 14px;margin-bottom:16px;color:#92400E;font-size:13px;">'
            f'<strong>旧包降级提示：</strong>当前数据包日期 <code>{esc(str(report.get("pack_trade_date", "-")))}</code> '
            f'落后于目标交易日 <code>{esc(str(report.get("expected_trade_date", "-")))}</code>，仅供参考。</div>'
        )

    # 4-card KPI grid
    kpi_cell = 'style="width:25%;padding:12px 10px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;vertical-align:top;"'
    kpi_lbl = 'style="font-size:11px;color:#64748B;margin-bottom:4px;font-weight:600;"'
    kpi_sub = 'style="font-size:11px;color:#64748B;margin-top:4px;"'
    sections.append(
        '<table role="presentation" width="100%" cellspacing="6" cellpadding="0" style="border-collapse:separate;margin:0 -6px 14px -6px;"><tr>'
        f'<td {kpi_cell}><div {kpi_lbl}>上涨家数占比</div>'
        f'<div style="font-size:20px;font-weight:700;color:{adv_color};font-family:{mono_stack};">{adv:.1f}%</div>'
        f'<div {kpi_sub}>中位数 {esc(med_str)}</div></td>'
        f'<td {kpi_cell}><div {kpi_lbl}>非 ST 涨跌停</div>'
        f'<div style="font-size:20px;font-weight:700;color:#0F172A;font-family:{mono_stack};">'
        f'<span style="color:#DC2626;">{lu_cnt}</span> / <span style="color:#059669;">{ld_cnt}</span></div>'
        f'<div {kpi_sub}>封板率 {esc(seal_str)}</div></td>'
        f'<td {kpi_cell}><div {kpi_lbl}>连板高度</div>'
        f'<div style="font-size:20px;font-weight:700;color:#0F172A;font-family:{mono_stack};">{max_streak} 板</div>'
        f'<div {kpi_sub}>昨涨停 {esc(prev_str)}</div></td>'
        f'<td {kpi_cell}><div {kpi_lbl}>两市成交额</div>'
        f'<div style="font-size:19px;font-weight:700;color:#0F172A;font-family:{mono_stack};">{esc(amt_str)}</div>'
        f'<div {kpi_sub}>涨 {up_cnt:,} / 平 {flat_cnt:,} / 跌 {down_cnt:,}</div></td>'
        '</tr></table>'
    )

    # 7-bucket return distribution + compact consecutive board ladder
    buckets = (
        ("le_neg7", "≤-7%", "#059669"),
        ("neg7_neg3", "-7~-3%", "#10B981"),
        ("neg3_0", "-3~0%", "#6EE7B7"),
        ("flat", "平", "#94A3B8"),
        ("pos0_3", "0~3%", "#FCA5A5"),
        ("pos3_7", "3~7%", "#F87171"),
        ("ge_pos7", "≥7%", "#DC2626"),
    )
    counts = [_non_neg_int(dist.get(k)) for k, _, _ in buckets]
    max_b = max(1, *counts)
    b_cells = []
    for idx, (_, blbl, bcol) in enumerate(buckets):
        cnt = counts[idx]
        bh = max(3, int(round((cnt / max_b) * 34))) if cnt > 0 else 2
        b_cells.append(
            f'<td style="width:14.28%;text-align:center;vertical-align:bottom;padding:4px 2px;">'
            f'<div style="font-size:10px;color:#475569;font-family:{mono_stack};margin-bottom:3px;">{cnt}</div>'
            f'<div style="height:{bh}px;background:{bcol};border-radius:3px 3px 0 0;margin:0 6px;"></div>'
            f'<div style="font-size:10px;color:#64748B;border-top:1px solid #CBD5E1;padding-top:3px;">{blbl}</div>'
            f'</td>'
        )
    ladder_map = reg.get("consecutive_board_ladder") or {}
    ladder_items = (
        sorted(
            (
                (board, count)
                for k, v in ladder_map.items()
                if (board := safe_int(k, default=0)) >= 2 and (count := _non_neg_int(v)) > 0
            ),
            reverse=True,
        )
        if isinstance(ladder_map, dict)
        else []
    )
    ladder_html = ""
    if ladder_items:
        chips = " ".join(
            f'<span style="display:inline-block;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:5px;'
            f'padding:2px 7px;margin:2px 4px 2px 0;font-size:11px;color:#334155;font-family:{mono_stack};">'
            f'<strong style="color:#DC2626;">{b}板</strong> {cnt}只</span>'
            for b, cnt in ladder_items[:6]
        )
        ladder_html = f'<div style="margin-top:8px;padding-top:7px;border-top:1px dashed #CBD5E1;font-size:11px;color:#475569;">连板梯队：{chips}</div>'
    sections.append(
        '<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:10px 12px;margin-bottom:16px;">'
        '<div style="font-size:12px;font-weight:700;color:#334155;margin-bottom:6px;">全 A 股涨跌分布（7 档）与连板梯队</div>'
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>{"".join(b_cells)}</tr></table>'
        f'{ladder_html}</div>'
    )

    # Alert-first Announcement Risk section with date & recency
    ann = report.get("announcement_risks") or {}
    flagged = ann.get("flagged_items") or []
    checked = _non_neg_int(ann.get("checked_count"))
    if flagged:
        ann_rows = []
        for item in flagged[:6]:
            flags, d_tag, snip = _format_ann_meta(item)
            date_badge = (
                f'<span style="display:inline-block;background:#FFFFFF;border:1px solid #FCA5A5;color:#7F1D1D;'
                f'font-size:10px;padding:1px 5px;border-radius:4px;margin-left:4px;font-family:{mono_stack};">{esc(d_tag)}</span>'
                if d_tag
                else ""
            )
            ann_rows.append(
                f'<li style="margin:5px 0;font-size:13px;color:#7F1D1D;line-height:1.5;">'
                f'<strong>{esc(str(item.get("name", "")))}</strong> '
                f'<code style="font-family:{mono_stack};color:#991B1B;">{esc(str(item.get("code", "")))}</code>'
                f'{date_badge}'
                f'<span style="display:inline-block;background:#FEE2E2;color:#B91C1C;font-size:11px;font-weight:700;'
                f'padding:1px 6px;border-radius:4px;margin:0 5px;">{esc(flags)}</span>'
                + (f'<span style="color:#450A0A;">{esc(snip)}</span>' if snip else "")
                + '</li>'
            )
        sections.append(
            f'<div style="background:#FEF2F2;border:1px solid #FECACA;border-left:4px solid #DC2626;'
            f'border-radius:8px;padding:12px 16px;margin-bottom:16px;">'
            f'<div style="font-size:13px;font-weight:700;color:#991B1B;margin-bottom:6px;">'
            f'⚠️ 公告排雷预警（抽检 {checked} 只重点标的 · 命中 {len(flagged)} 只预警）</div>'
            f'<ul style="margin:0;padding-left:18px;">{"".join(ann_rows)}</ul></div>'
        )
    elif checked > 0:
        sections.append(
            f'<div style="background:#ECFDF5;border:1px solid #A7F3D0;border-left:4px solid #059669;'
            f'border-radius:8px;padding:10px 14px;margin-bottom:16px;color:#065F46;font-size:13px;">'
            f'<strong>✓ 公告排雷通过：</strong>已抽检 {checked} 只重点候选，未检出减持 / 立案 / 退市等实质性负面公告。</div>'
        )

    # Post-Close Brief
    brief = report.get("ai_brief") or {}
    if brief.get("headline"):
        is_ai = brief.get("mode") == "llm"
        mod_txt = f" · {esc(str(brief.get('model')))}" if is_ai and brief.get("model") else ""
        lbl = f"🤖 AI 盘后综述{mod_txt}" if is_ai else "📌 盘后盘面摘要"
        accent = "#2563EB" if is_ai else "#475569"
        extra_paras = []
        for k in ("market_summary", "consensus_and_ai_edge", "regime_interpretation", "risk_focus"):
            val = str(brief.get(k) or "").strip()
            if val:
                extra_paras.append(f'<p style="margin:5px 0 0 0;font-size:13px;color:#334155;line-height:1.6;">{esc(val)}</p>')
        watch = [str(w).strip() for w in (brief.get("watch_points") or []) if str(w).strip()][:3]
        if watch:
            w_items = "".join(f'<li style="margin:2px 0;">{esc(w)}</li>' for w in watch)
            extra_paras.append(
                f'<ul style="margin:6px 0 0 0;padding-left:18px;font-size:12px;color:#475569;line-height:1.55;">{w_items}</ul>'
            )
        sections.append(
            f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-left:4px solid {accent};'
            f'border-radius:8px;padding:12px 16px;margin-bottom:16px;">'
            f'<div style="font-size:12px;font-weight:700;color:{accent};margin-bottom:4px;">{lbl}</div>'
            f'<div style="font-size:14px;font-weight:700;color:#0F172A;line-height:1.5;">{esc(str(brief["headline"]).strip())}</div>'
            f'{"".join(extra_paras)}</div>'
        )

    # Market News section
    mnews = ((report.get("market_news") or {}).get("items") or []) if isinstance(report.get("market_news"), dict) else []
    if mnews:
        nsrc = " · ".join(str(s) for s in ((report.get("market_news") or {}).get("sources") or []) if s)
        n_rows = []
        for item in mnews[:5]:
            cat = str(item.get("category") or "要闻")
            pub = str(item.get("published_at") or "")
            src = str(item.get("source") or "")
            n_rows.append(
                f'<li style="margin:5px 0;font-size:13px;color:#1E293B;line-height:1.5;">'
                f'<span style="display:inline-block;background:#E0F2FE;color:#0369A1;font-size:10px;font-weight:700;'
                f'padding:1px 6px;border-radius:4px;margin-right:6px;">{esc(cat)}</span>'
                f'{esc(str(item.get("title") or ""))}'
                f'<span style="font-size:11px;color:#64748B;margin-left:6px;">{esc(src)} {esc(pub)}</span></li>'
            )
        sections.append(
            '<div style="border:1px solid #E2E8F0;border-radius:8px;padding:12px 16px;margin-bottom:16px;background:#FFFFFF;">'
            '<div style="font-size:13px;font-weight:700;color:#0F172A;margin-bottom:6px;">'
            '📰 市场热点与政策快讯'
            + (f' <span style="font-size:11px;font-weight:500;color:#64748B;">· {esc(nsrc)}</span>' if nsrc else "")
            + f'</div><ul style="margin:0;padding-left:18px;">{"".join(n_rows)}</ul></div>'
        )

    # Multi-Strategy Consensus Table with Chinese names, valuation, and reasons/news
    syn = report.get("cross_strategy_synthesis") or {}
    consensus = syn.get("consensus_picks") or []
    track_stats = report.get("strategy_track_stats") if isinstance(report.get("strategy_track_stats"), dict) else {}
    if consensus:
        th_css = 'style="padding:8px;text-align:left;font-size:11px;color:#64748B;border-bottom:1px solid #E2E8F0;background:#F8FAFC;"'
        th_r = 'style="padding:8px 6px;text-align:right;font-size:11px;color:#64748B;border-bottom:1px solid #E2E8F0;background:#F8FAFC;white-space:nowrap;"'
        c_rows = []
        for idx, c in enumerate(consensus[:6], start=1):
            chg_v = finite_float(c.get("change_pct"))
            chg_col = "#DC2626" if (chg_v is not None and chg_v > 0) else ("#059669" if (chg_v is not None and chg_v < 0) else "#475569")
            sc_val = finite_float(c.get("avg_final_score"))
            px_val = finite_float(c.get("price"))
            sc_v = "–" if sc_val is None else f"{sc_val:.1f}"
            px_v = "–" if px_val is None else f"¥{px_val:.2f}"
            strats_cn = " · ".join(_strategy_display_name(report, x) for x in (c.get("strategies") or [])[:3])
            val_bits = []
            if (pe_val := finite_float(c.get("pe_ratio"))) is not None:
                val_bits.append(f"PE {pe_val:.1f}")
            if (pb_val := finite_float(c.get("pb_ratio"))) is not None:
                val_bits.append(f"PB {pb_val:.2f}")
            if (mcap_val := finite_float(c.get("market_cap_yi"))) is not None:
                val_bits.append(f"{mcap_val:.0f}亿")
            val_txt = f" · {' · '.join(val_bits)}" if val_bits else ""
            extra_sub = ""
            if c.get("reasons"):
                extra_sub += f'<div style="font-size:11px;color:#475569;margin-top:2px;">理由：{esc(str(c["reasons"][0])[:64])}</div>'
            if c.get("news_headline"):
                extra_sub += f'<div style="font-size:11px;color:#0369A1;margin-top:1px;">动态：{esc(str(c["news_headline"])[:56])}</div>'
            risk_badge = ' <span style="background:#FEE2E2;color:#DC2626;font-size:10px;padding:1px 4px;border-radius:3px;">公告预警</span>' if c.get("announcement_risk_flags") else ""
            c_rows.append(
                f'<tr style="border-bottom:1px solid #F1F5F9;">'
                f'<td style="padding:8px;font-size:12px;color:#64748B;font-family:{mono_stack};vertical-align:top;">{idx}</td>'
                f'<td style="padding:8px;font-size:13px;color:#0F172A;vertical-align:top;"><strong>{esc(str(c.get("name", "")))}</strong> '
                f'<code style="font-size:11px;color:#64748B;font-family:{mono_stack};">{esc(str(c.get("code", "")))}</code>{risk_badge}'
                f'<div style="font-size:11px;color:#64748B;margin-top:2px;">{esc(str(c.get("industry") or "-"))}{esc(val_txt)} · {esc(strats_cn)}</div>{extra_sub}</td>'
                f'<td style="padding:8px 6px;text-align:right;font-size:12px;font-family:{mono_stack};color:#0F172A;vertical-align:top;white-space:nowrap;">{px_v}</td>'
                f'<td style="padding:8px 6px;text-align:right;font-size:12px;vertical-align:top;white-space:nowrap;"><span style="display:inline-block;background:#EFF6FF;color:#1D4ED8;font-weight:700;padding:2px 7px;border-radius:999px;white-space:nowrap;">{_non_neg_int(c.get("strategy_count"))} 策略</span></td>'
                f'<td style="padding:8px 6px;text-align:right;font-size:12px;font-family:{mono_stack};color:#0F172A;vertical-align:top;white-space:nowrap;">{sc_v}</td>'
                f'<td style="padding:8px 6px;text-align:right;font-size:12px;font-weight:700;font-family:{mono_stack};color:{chg_col};vertical-align:top;white-space:nowrap;">{esc(_fmt_report_pct(chg_v))}</td>'
                f'</tr>'
            )
        sections.append(
            f'<div style="border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;margin-bottom:16px;">'
            f'<div style="padding:10px 14px;background:#F8FAFC;border-bottom:1px solid #E2E8F0;font-size:13px;font-weight:700;color:#0F172A;">'
            f'🎯 跨策略高共识精选（共 {len(consensus)} 只，展示 Top {min(6, len(consensus))}）</div>'
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">'
            f'<thead><tr><th {th_css}>#</th><th {th_css}>标的 / 估值 / 命中策略与理由</th><th {th_r}>现价</th><th {th_r}>共振度</th><th {th_r}>均分</th><th {th_r}>今日涨跌</th></tr></thead>'
            f'<tbody>{"".join(c_rows)}</tbody></table></div>'
        )

    # Compact Strategy Picks Grid with Chinese names + historical T+5 track record
    strategies_list = [s for s in (report.get("strategies") or []) if isinstance(s, dict) and (s.get("picks") or [])]
    if strategies_list:
        s_cards: list[str] = []
        for st in strategies_list[:10]:
            skey = str(st.get("strategy") or "")
            sname = _strategy_display_name(report, skey)
            tr_badge = '<span style="background:#EFF6FF;color:#1D4ED8;font-size:10px;padding:1px 5px;border-radius:4px;margin-left:5px;">AI</span>' if (st.get("track") == "ai" or st.get("llm_ranked")) else ""
            ts = track_stats.get(skey) or {}
            ts_excess = finite_float(ts.get("t5_avg_excess_pct"))
            ts_badge = (
                f'<span style="font-size:11px;color:#475569;float:right;font-family:{mono_stack};">T+5 {ts_excess:+.2f}%</span>'
                if ts_excess is not None
                else ""
            )
            top2 = " · ".join(
                f"<strong>{esc(str(pk.get('name') or pk.get('code')))}</strong> "
                f"<span style=\"color:#64748B;font-size:11px;font-family:{mono_stack};\">{esc(str(pk.get('code') or ''))}</span> "
                f"<span style=\"color:#475569;font-size:11px;font-family:{mono_stack};\">{esc(_fmt_report_pct(pk.get('change_pct')))}</span>"
                for pk in (st.get("picks") or [])[:3]
            )
            s_cards.append(
                f'<div style="padding:7px 12px;border-bottom:1px solid #F1F5F9;font-size:12px;">'
                f'<div style="font-weight:700;color:#0F172A;margin-bottom:2px;">{esc(sname)}{tr_badge}{ts_badge}</div>'
                f'<div style="color:#334155;">{top2}</div></div>'
            )
        sections.append(
            f'<div style="border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;margin-bottom:16px;">'
            f'<div style="padding:9px 14px;background:#F8FAFC;border-bottom:1px solid #E2E8F0;font-size:13px;font-weight:700;color:#0F172A;">'
            f'🧭 今日策略精选速览（{len(strategies_list)} 组）</div>'
            f'{"".join(s_cards)}</div>'
        )

    # Pattern Radar Cards tiered by replay expectancy
    primary_pats, neg_pats = _split_hit_patterns(report)
    shown_pats = primary_pats or neg_pats
    if shown_pats:
        pat_blocks = []
        for p in shown_pats[:5]:
            is_act = p.get("status") == "active"
            badge_bg, badge_fg, badge_txt = ("#ECFDF5", "#059669", "active") if is_act else ("#FFFBEB", "#B45309", "观察期")
            net_ex = finite_float(p.get("replay_t5_net_excess_pct"))
            net_txt = f" · T+5净超额 {net_ex:+.2f}%" if net_ex is not None else ""
            sig_rows = []
            for s in (p.get("signals") or [])[:4]:
                cv = finite_float(s.get("change_pct"))
                ccol = "#DC2626" if (cv is not None and cv > 0) else ("#059669" if (cv is not None and cv < 0) else "#475569")
                ov_val = finite_float(s.get("overhead_supply_10pct"))
                ov = "–" if ov_val is None else f"{ov_val:.0f}%"
                sig_rows.append(
                    f'<tr><td style="width:46%;padding:6px 12px;font-size:12px;color:#0F172A;"><strong>{esc(str(s.get("name") or s.get("code")))}</strong> '
                    f'<code style="color:#64748B;font-size:11px;font-family:{mono_stack};">{esc(str(s.get("code", "")))}</code></td>'
                    f'<td style="width:24%;padding:6px 10px;text-align:right;font-size:12px;font-family:{mono_stack};color:{ccol};font-weight:600;">{esc(_fmt_report_pct(cv))}</td>'
                    f'<td style="width:30%;padding:6px 12px;text-align:right;font-size:12px;font-family:{mono_stack};color:#64748B;">上方筹码 {esc(ov)}</td></tr>'
                )
            pat_blocks.append(
                f'<div style="border:1px solid #E2E8F0;border-radius:8px;margin-bottom:10px;overflow:hidden;">'
                f'<div style="padding:8px 12px;background:#F8FAFC;border-bottom:1px solid #E2E8F0;font-size:13px;">'
                f'<strong style="color:#0F172A;">{esc(str(p.get("display_name") or p.get("pattern")))}</strong> '
                f'<span style="display:inline-block;background:{badge_bg};color:{badge_fg};font-size:11px;font-weight:700;padding:1px 7px;border-radius:999px;margin-left:6px;">{badge_txt} · {_non_neg_int(p.get("hit_count"))}只{esc(net_txt)}</span>'
                f'</div>'
                f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">{"".join(sig_rows)}</table></div>'
            )
        neg_note = ""
        if primary_pats and neg_pats:
            neg_parts = []
            for p in neg_pats:
                p_lbl = p.get("display_name") or p.get("pattern")
                p_cnt = _non_neg_int(p.get("hit_count"))
                p_net = finite_float(p.get("replay_t5_net_excess_pct"))
                if p_net is not None:
                    neg_parts.append(f"{p_lbl}({p_cnt}只, {p_net:+.2f}%)")
                else:
                    neg_parts.append(f"{p_lbl}({p_cnt}只)")
            neg_desc = "、".join(neg_parts)
            neg_note = f'<div style="font-size:11px;color:#64748B;margin-top:4px;">历史回放负期望观察期触发（仅作对照）：{esc(neg_desc)}</div>'
        sections.append(
            '<div style="margin-bottom:16px;">'
            '<div style="font-size:13px;font-weight:700;color:#0F172A;margin-bottom:8px;">'
            '📡 A 股无状态形态雷达（按 25bp/NW 实证期望分层）</div>'
            f'{"".join(pat_blocks)}{neg_note}</div>'
        )

    detail_url = _resolved_report_url(report)
    cta_html = (
        f'<div style="text-align:center;margin:20px 0 8px 0;">'
        f'<a href="{esc(detail_url, quote=True)}" target="_blank" rel="noopener" '
        f'style="display:inline-block;background:#2563EB;color:#FFFFFF;text-decoration:none;'
        f'font-size:14px;font-weight:700;padding:11px 24px;border-radius:8px;">'
        f'打开在线交互看板（20日K线 &amp; T+N 实盘验证）</a></div>'
        if detail_url
        else ""
    )

    return (
        f'<!doctype html><html><body style="margin:0;padding:24px 12px;background:#F1F5F9;font-family:{font_stack};">'
        f'<div style="max-width:660px;margin:0 auto;background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;overflow:hidden;">'
        f'<div style="background:#0F172A;color:#F8FAFC;padding:20px 24px;">'
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>'
        f'<td><span style="display:inline-block;background:#1E293B;color:#93C5FD;font-size:11px;font-weight:700;'
        f'letter-spacing:0.06em;padding:3px 9px;border-radius:999px;">ALPHASIFT</span>'
        f'<div style="font-size:20px;font-weight:700;margin-top:8px;">A 股盘后定量观测日报</div>'
        f'<div style="font-size:12px;color:#94A3B8;margin-top:3px;">交易日 {esc(str(report.get("trade_date", "-")))} · 规则筛选 + 公告排雷 + 快讯催化 + 形态雷达</div></td>'
        f'<td style="text-align:right;vertical-align:top;"><span style="display:inline-block;background:{st_bg};color:{st_fg};'
        f'font-size:12px;font-weight:700;padding:5px 12px;border-radius:999px;">盘面 · {esc(stage_lbl)}</span></td>'
        f'</tr></table></div>'
        f'<div style="padding:20px 24px;">{"".join(sections)}{cta_html}</div>'
        f'<div style="padding:12px 24px;background:#F8FAFC;border-top:1px solid #E2E8F0;font-size:11px;color:#64748B;line-height:1.5;">'
        f'<strong>AlphaSift</strong> · 开源量化形态观测与 T+N 回测基准（Apache-2.0）· 历史统计不含分红，不构成投资建议。</div>'
        f'</div></body></html>'
    )


def _send_feishu(
    webhook_url: str,
    content: str,
    *,
    title: str,
    secret: str = "",
    report: dict[str, Any] | None = None,
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    body: dict[str, Any] = {
        "msg_type": "interactive",
        "card": _build_feishu_card(report, content, title=title),
    }
    if secret:
        ts = int(time.time())
        body["timestamp"] = str(ts)
        body["sign"] = _feishu_sign(ts, secret)
    resp = _post_with_retry(post_fn, webhook_url, json=body, timeout=timeout_sec)
    payload = _safe_json(resp)
    code = payload.get("code", payload.get("StatusCode", -1))
    if int(code) != 0:
        raise RuntimeError(f"feishu code={code} msg={payload.get('msg', payload.get('StatusMessage', ''))}")


def _send_dingtalk(
    webhook_url: str,
    content: str,
    *,
    title: str,
    secret: str = "",
    report: dict[str, Any] | None = None,
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    target = webhook_url
    if secret:
        ts_ms = int(time.time() * 1000)
        sep = "&" if "?" in webhook_url else "?"
        target = f"{webhook_url}{sep}timestamp={ts_ms}&sign={_dingtalk_sign(ts_ms, secret)}"
    md_text = _render_markdown_digest(report, content, title=title, wecom_colors=False)
    resp = _post_with_retry(
        post_fn,
        target,
        json={"msgtype": "markdown", "markdown": {"title": title, "text": md_text}},
        timeout=timeout_sec,
    )
    payload = _safe_json(resp)
    if int(payload.get("errcode", -1)) != 0:
        raise RuntimeError(f"dingtalk errcode={payload.get('errcode')} errmsg={payload.get('errmsg', '')}")


def _send_pushplus(
    token: str,
    content: str,
    *,
    title: str,
    topic: str = "",
    report: dict[str, Any] | None = None,
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    md_text = _render_markdown_digest(report, content, title=title, wecom_colors=False)
    body: dict[str, Any] = {
        "token": token,
        "title": title[:100],
        "content": md_text,
        "template": "markdown",
    }
    if topic:
        body["topic"] = topic
    resp = _post_with_retry(post_fn, "https://www.pushplus.plus/send", json=body, timeout=timeout_sec)
    payload = _safe_json(resp)
    if int(payload.get("code", -1)) != 200:
        raise RuntimeError(f"pushplus code={payload.get('code')} msg={payload.get('msg', '')}")


def _send_serverchan(
    sendkey_or_url: str,
    content: str,
    *,
    title: str,
    report: dict[str, Any] | None = None,
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    if sendkey_or_url.startswith(("http://", "https://")):
        url = sendkey_or_url
    else:
        match = _SCTP_PATTERN.match(sendkey_or_url)
        if match:
            url = f"https://{match.group(1)}.push.ft07.com/send/{sendkey_or_url}.send"
        else:
            url = f"https://sctapi.ftqq.com/{sendkey_or_url}.send"
    md_text = _render_markdown_digest(report, content, title=title, wecom_colors=False)
    resp = _post_with_retry(
        post_fn,
        url,
        json={"title": title[:32], "desp": md_text},
        timeout=timeout_sec,
    )
    payload = _safe_json(resp)
    if int(payload.get("code", -1)) != 0:
        raise RuntimeError(f"serverchan code={payload.get('code')} msg={payload.get('message', payload.get('info', ''))}")


def _send_bark(
    bark_url: str,
    content: str,
    *,
    title: str,
    detail_url: str = "",
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    target = bark_url if bark_url.startswith(("http://", "https://")) else f"https://api.day.app/{bark_url.strip('/')}"
    body: dict[str, Any] = {"title": title[:120], "body": content, "group": "AlphaSift"}
    if detail_url:
        body["url"] = detail_url
    resp = _post_with_retry(post_fn, target, json=body, timeout=timeout_sec)
    payload = _safe_json(resp)
    if int(payload.get("code", 200)) != 200:
        raise RuntimeError(f"bark code={payload.get('code')} msg={payload.get('message', '')}")


def _send_telegram(
    bot_token: str,
    chat_id: str,
    content: str,
    *,
    title: str = "",
    report: dict[str, Any] | None = None,
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    html_text = _render_telegram_html(report, content, title=title or "AlphaSift")
    resp = _post_with_retry(
        post_fn,
        url,
        json={
            "chat_id": chat_id,
            "text": html_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=timeout_sec,
    )
    payload = _safe_json(resp)
    if payload.get("ok") is not True:
        desc = str(payload.get("description") or "")
        if "parse" in desc.lower() or "entity" in desc.lower() or "entities" in desc.lower():
            resp2 = _post_with_retry(
                post_fn,
                url,
                json={"chat_id": chat_id, "text": content, "disable_web_page_preview": True},
                timeout=timeout_sec,
            )
            payload2 = _safe_json(resp2)
            if payload2.get("ok") is True:
                return
            raise RuntimeError(f"telegram error={payload2.get('description', 'unknown')}")
        raise RuntimeError(f"telegram error={desc or 'unknown'}")


def _build_discord_embed(
    report: dict[str, Any] | None,
    content: str,
    *,
    title: str,
    detail_url: str = "",
) -> dict[str, Any]:
    if not _has_rich_report(report) and not _has_market_digest(report):
        embed: dict[str, Any] = {"title": title[:256], "description": content[:4096], "color": 3899638}
        if detail_url:
            embed["url"] = detail_url
        return embed

    assert report is not None
    fields: list[dict[str, Any]] = []
    if _has_rich_report(report):
        reg = report.get("market_regime") or {}
        stage = str(reg.get("regime_stage") or "")
        color = 14431557 if stage in {"freezing", "ebb"} else (380259 if stage in {"startup", "main_up"} else 14251526)
        fields.append({
            "name": f"盘面 · {reg.get('regime_stage_label', '-')}",
            "value": (
                f"上涨 {_float_or(reg.get('advance_ratio_pct')):.1f}% · 中位 {_fmt_report_pct(reg.get('median_return_pct'))}\n"
                f"涨跌停 {_non_neg_int(reg.get('non_st_limit_up_count'))}/{_non_neg_int(reg.get('non_st_limit_down_count'))} · 最高 {_non_neg_int(reg.get('max_consecutive_limit_up'))}板"
            ),
            "inline": False,
        })
        flagged = ((report.get("announcement_risks") or {}).get("flagged_items")) or []
        if flagged:
            color = 14431557
            ann_txt = "\n".join(
                f"• `{x.get('code')}` {x.get('name')} [{_format_ann_meta(x)[0]}]"
                for x in flagged[:4]
            )
            fields.append({"name": f"⚠️ 公告排雷 ({len(flagged)})", "value": ann_txt[:1024], "inline": False})
        syn = report.get("cross_strategy_synthesis") or {}
        consensus = syn.get("consensus_picks") or []
        if consensus:
            c_txt = "\n".join(
                f"• **{c.get('name')}** `{c.get('code')}` ({c.get('strategy_count')}策略 · {_fmt_report_pct(c.get('change_pct'))})"
                for c in consensus[:5]
            )
            fields.append({"name": "🎯 跨策略共识", "value": c_txt[:1024], "inline": False})
        desc = str(((report.get("ai_brief") or {}).get("headline")) or content[:300])[:4096]
    else:
        color = 2461419
        desc = f"Global Digest · {report.get('trade_date', '-')}"
        for sec in (report.get("market_sections") or [])[:5]:
            top = ", ".join(f"{p.get('code')}({p.get('avg_final_score'):.0f})" for p in (sec.get("top_picks") or [])[:3])
            fields.append({"name": str(sec.get("market_name") or sec.get("market")), "value": top or "暂无候选", "inline": True})

    embed = {
        "title": title[:256],
        "description": desc,
        "color": color,
        "fields": fields[:6],
        "footer": {"text": "AlphaSift · Quantitative Discovery & Benchmark"},
    }
    if detail_url:
        embed["url"] = detail_url
    return embed


def _send_discord(
    webhook_url: str,
    content: str,
    *,
    title: str,
    detail_url: str = "",
    report: dict[str, Any] | None = None,
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    embed = _build_discord_embed(report, content, title=title, detail_url=detail_url)
    _post_with_retry(post_fn, webhook_url, json={"content": "", "embeds": [embed]}, timeout=timeout_sec)


def _send_slack(
    webhook_url: str,
    content: str,
    *,
    title: str,
    report: dict[str, Any] | None = None,
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    if not _has_rich_report(report) and not _has_market_digest(report):
        _post_with_retry(post_fn, webhook_url, json={"text": f"*{title}*\n{content}"}, timeout=timeout_sec)
        return
    md_text = _render_markdown_digest(report, content, title=title, wecom_colors=False)
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": md_text[:2950]}},
    ]
    assert report is not None
    detail_url = _resolved_report_url(report)
    if detail_url:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "Open Dashboard"},
                "url": detail_url,
            }],
        })
    _post_with_retry(post_fn, webhook_url, json={"text": f"*{title}*\n{content}", "blocks": blocks}, timeout=timeout_sec)


def _send_ntfy(
    ntfy_url: str,
    content: str,
    *,
    title: str,
    detail_url: str = "",
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    headers = {"Title": _ntfy_ascii_title(title)}
    if detail_url:
        headers["Click"] = detail_url
    _post_with_retry(post_fn, ntfy_url, data=content.encode("utf-8"), headers=headers, timeout=timeout_sec)


def _resolve_smtp_settings(sender: str, smtp_host: str = "", smtp_port: int = 0) -> tuple[str, int, str]:
    domain = sender.rsplit("@", 1)[-1].lower().strip() if "@" in sender else ""
    default_host, default_port, default_mode = _SMTP_DEFAULTS.get(
        domain,
        (f"smtp.{domain}" if domain else "", 465, "ssl"),
    )
    host = smtp_host or default_host
    if not host:
        raise ValueError("Email SMTP host could not be inferred; set EMAIL_SMTP_HOST or mailto://user:pass@smtp.example.com")
    port = smtp_port or default_port
    mode = "starttls" if port == 587 else ("ssl" if port == 465 else default_mode)
    return host, port, mode


def _send_email(
    sender: str,
    password: str,
    receivers: Sequence[str],
    content: str,
    *,
    title: str,
    report: dict[str, Any] | None = None,
    smtp_host: str = "",
    smtp_port: int = 0,
    timeout_sec: float = 10.0,
    smtp_factory=None,
) -> None:
    host, port, mode = _resolve_smtp_settings(sender, smtp_host, smtp_port)
    recips = [r.strip() for r in receivers if r.strip()] or [sender]
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = sender if "<" in sender else formataddr(("AlphaSift 量化日报", sender))
    msg["To"] = ", ".join(recips)
    msg.set_content(content, charset="utf-8")
    html_body = _render_email_html(report, content, title=title)
    msg.add_alternative(html_body, subtype="html", charset="utf-8")

    if smtp_factory is not None:
        client = smtp_factory(host, port, mode=mode, timeout=timeout_sec)
        try:
            if hasattr(client, "login"):
                client.login(sender, password)
            client.send_message(msg)
        finally:
            if hasattr(client, "quit"):
                client.quit()
        return

    if mode == "starttls":
        with smtplib.SMTP(host, port, timeout=timeout_sec) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(sender, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, timeout=timeout_sec, context=ssl.create_default_context()) as server:
            server.login(sender, password)
            server.send_message(msg)


def _send_custom_webhook(
    webhook_url: str,
    *,
    report: dict[str, Any],
    content: str,
    title: str,
    token: str = "",
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    syn = report.get("cross_strategy_synthesis") or {}
    ann = report.get("announcement_risks") or {}
    payload: dict[str, Any] = {
        "event": str(report.get("event") or "alphasift.daily_report"),
        "trade_date": report.get("trade_date"),
        "title": title,
        "markdown": content,
        "dashboard_url": str(report.get("detail_url") or ""),
        "pack_is_stale": bool(report.get("pack_is_stale")),
        "summary": {
            "consensus_count": len(syn.get("consensus_picks") or []),
            "flagged_announcements": _non_neg_int(ann.get("flagged_count")),
        },
    }
    kwargs: dict[str, Any] = {"json": payload, "timeout": timeout_sec}
    if token:
        kwargs["headers"] = {"Authorization": f"Bearer {token}"}
    _post_with_retry(post_fn, webhook_url, **kwargs)


def _send_apprise(uri: str, content: str, *, title: str) -> None:
    try:
        apprise_mod = importlib.import_module("apprise")
    except ImportError as exc:
        raise RuntimeError(
            "URI scheme requires optional 'apprise' package (pip install apprise)"
        ) from exc
    app = apprise_mod.Apprise()
    if not app.add(uri):
        raise RuntimeError("apprise rejected notification URI")
    if not app.notify(title=title, body=content):
        raise RuntimeError("apprise notification failed")


def _select_targets(
    cfg: Config,
    channels: Sequence[str] | None,
) -> tuple[list[str], list[dict[str, Any]]]:
    all_targets = resolve_notify_targets(cfg)
    available = configured_channels(cfg)
    if channels is None:
        return available, all_targets
    requested = [c.strip().lower() for c in channels if c.strip()]
    invalid = [c for c in requested if c not in SUPPORTED_CHANNELS]
    if invalid:
        raise ValueError(f"Unsupported notification channels: {', '.join(invalid)}")
    requested_set = set(requested)
    return available, [t for t in all_targets if t["channel"] in requested_set]


def _dispatch_target(
    target_spec: dict[str, Any],
    cfg: Config,
    *,
    report: dict[str, Any],
    content: str,
    title: str,
    post_fn=requests.post,
    smtp_factory=None,
) -> None:
    ch = target_spec["channel"]
    target = str(target_spec["target"])
    secret = str(target_spec.get("secret") or "")
    token = str(target_spec.get("token") or "")
    extra = target_spec.get("extra") or {}
    timeout = cfg.notify_timeout_sec

    if ch == "wecom":
        _send_wecom(target, content, title=title, report=report, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "feishu":
        _send_feishu(
            target,
            content,
            title=title,
            secret=secret,
            report=report,
            timeout_sec=timeout,
            post_fn=post_fn,
        )
    elif ch == "dingtalk":
        _send_dingtalk(target, content, title=title, secret=secret, report=report, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "pushplus":
        _send_pushplus(target, content, title=title, topic=str(extra.get("topic") or ""), report=report, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "serverchan":
        _send_serverchan(target, content, title=title, report=report, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "bark":
        _send_bark(target, content, title=title, detail_url=_resolved_report_url(report), timeout_sec=timeout, post_fn=post_fn)
    elif ch == "email":
        _send_email(
            str(extra.get("sender") or target),
            secret or str(extra.get("password") or ""),
            extra.get("receivers") or [target],
            content,
            title=title,
            report=report,
            smtp_host=str(extra.get("smtp_host") or ""),
            smtp_port=int(extra.get("smtp_port") or 0),
            timeout_sec=timeout,
            smtp_factory=smtp_factory,
        )
    elif ch == "telegram":
        _send_telegram(
            target,
            str(extra.get("chat_id") or ""),
            content,
            title=title,
            report=report,
            timeout_sec=timeout,
            post_fn=post_fn,
        )
    elif ch == "discord":
        _send_discord(target, content, title=title, detail_url=_resolved_report_url(report), report=report, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "slack":
        _send_slack(target, content, title=title, report=report, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "ntfy":
        _send_ntfy(target, content, title=title, detail_url=_resolved_report_url(report), timeout_sec=timeout, post_fn=post_fn)
    elif ch == "custom":
        _send_custom_webhook(target, report=report, content=content, title=title, token=token, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "apprise":
        _send_apprise(target, content, title=title)


def send_test_notification(
    *,
    config: Config | None = None,
    channels: Sequence[str] | None = None,
    dry_run: bool = False,
    post_fn=requests.post,
    smtp_factory=None,
) -> dict[str, Any]:
    """Dispatch a non-persistent connectivity test message to configured targets."""
    cfg = config or Config.from_env()
    available, target_specs = _select_targets(cfg, channels)
    target_channels: list[str] = []
    for spec in target_specs:
        if spec["channel"] not in target_channels:
            target_channels.append(spec["channel"])

    if not target_specs:
        return {
            "status": "skipped_no_channels",
            "configured_channels": available,
            "target_channels": [],
            "sent": [],
            "skipped": [],
            "errors": [],
        }

    title = "AlphaSift Push Connectivity Test"
    content = (
        f"**{title}**\n"
        f"> Channel connectivity verification from AlphaSift CLI (`dry_run={dry_run}`). "
        "This test does not write to the daily idempotency ledger.\n"
        f"🔗 {cfg.dashboard_url}"
    )
    test_report: dict[str, Any] = {
        "event": "alphasift.notify_test",
        "trade_date": "TEST",
        "detail_url": cfg.dashboard_url,
        "pack_is_stale": False,
        "cross_strategy_synthesis": {"consensus_picks": []},
        "announcement_risks": {"flagged_count": 0},
    }

    sent: list[str] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for spec in target_specs:
        ch = spec["channel"]
        if dry_run:
            skipped.append({"channel": ch, "reason": "dry_run"})
            continue
        try:
            _dispatch_target(
                spec,
                cfg,
                report=test_report,
                content=content,
                title=title,
                post_fn=post_fn,
                smtp_factory=smtp_factory,
            )
            sent.append(ch)
        except Exception as exc:  # noqa: BLE001
            errors.append({"channel": ch, "error": _redact_error(exc, cfg, spec.get("secrets") or ())})

    if errors and sent:
        status = "partial"
    elif errors and not sent:
        status = "error"
    elif sent:
        status = "ok"
    else:
        status = "dry_run"

    return {
        "status": status,
        "configured_channels": available,
        "target_channels": target_channels,
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
    }


def push_daily_report(
    report: dict[str, Any],
    *,
    config: Config | None = None,
    channels: Sequence[str] | None = None,
    state_path: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    post_fn=requests.post,
    smtp_factory=None,
) -> dict[str, Any]:
    """Push rendered <1200-char card to configured targets idempotently by (trade_date, target)."""
    cfg = config or Config.from_env()
    trade_date = str(report.get("trade_date") or "").strip()
    if not trade_date:
        raise ValueError("Daily report is missing trade_date")

    card = ensure_im_card_length(
        str(report.get("im_card_markdown") or render_daily_im_card(report)),
        max_chars=IM_CARD_MAX_CHARS,
    )
    _, target_specs = _select_targets(cfg, channels)

    if not target_specs:
        return {
            "status": "skipped_no_channels",
            "trade_date": trade_date,
            "card_chars": len(card),
            "sent": [],
            "skipped": [],
            "errors": [],
        }

    if report.get("pack_is_stale") and not force:
        return {
            "status": "skipped_stale_pack",
            "trade_date": trade_date,
            "pack_trade_date": report.get("pack_trade_date"),
            "stale_reason": report.get("stale_reason"),
            "card_chars": len(card),
            "sent": [],
            "skipped": [{"channel": spec["channel"], "reason": "stale_pack"} for spec in target_specs],
            "errors": [],
        }

    ledger_path = Path(state_path) if state_path is not None else cfg.notify_state_path
    content_hash = hashlib.sha256(card.encode("utf-8")).hexdigest()[:16]
    fallback_title = f"AlphaSift A股量化观测日报 ({trade_date})"
    title = _build_report_title(report, fallback_title=fallback_title)
    market_scope = str(report.get("market") or "cn").strip().lower()
    ledger_prefix = f"{trade_date}:{market_scope}:" if market_scope not in {"", "cn"} else f"{trade_date}:"

    sent: list[str] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    channel_totals: dict[str, int] = {}
    for spec in target_specs:
        ch_name = spec["channel"]
        channel_totals[ch_name] = channel_totals.get(ch_name, 0) + 1

    for spec in target_specs:
        channel = spec["channel"]
        extra = spec.get("extra") or {}
        receivers_fp = ",".join(
            sorted(str(r).strip() for r in (extra.get("receivers") or []) if str(r).strip())
        )
        ident = f"{channel}\0{spec.get('target', '')}\0{extra.get('chat_id') or extra.get('topic') or receivers_fp or ''}"
        fp_full = hashlib.sha256(ident.encode("utf-8")).hexdigest()[:12]
        legacy_key = f"{ledger_prefix}{channel}"
        fp_key = f"{ledger_prefix}{channel}:{fp_full}"
        is_single = channel_totals.get(channel, 0) <= 1
        claim_record: dict[str, Any] | None = None

        with _ledger_lock(ledger_path):
            state = _load_state(ledger_path)
            legacy_rec = state.get(legacy_key)
            fp_rec = state.get(fp_key)
            legacy_matches = isinstance(legacy_rec, dict) and legacy_rec.get("target_fp") in (None, fp_full)

            if is_single:
                if isinstance(fp_rec, dict):
                    key = fp_key
                    existing = fp_rec
                elif legacy_matches:
                    key = legacy_key
                    existing = legacy_rec
                elif isinstance(legacy_rec, dict):
                    key = fp_key
                    existing = fp_rec
                else:
                    key = legacy_key
                    existing = None
            else:
                legacy_exact = isinstance(legacy_rec, dict) and legacy_rec.get("target_fp") == fp_full
                if isinstance(fp_rec, dict):
                    key = fp_key
                    existing = fp_rec
                elif legacy_exact:
                    key = legacy_key
                    existing = legacy_rec
                else:
                    key = fp_key
                    existing = None

            if isinstance(existing, dict) and not force:
                existing_status = existing.get("status")
                if existing_status in (None, "sent"):
                    skipped.append({"channel": channel, "reason": "duplicate_same_trade_date"})
                    continue
                if existing_status == "pending":
                    claimed_dt = parse_timestamp(existing.get("claimed_at"))
                    if (
                        claimed_dt is not None
                        and (datetime.now(timezone.utc) - claimed_dt).total_seconds() < _PENDING_LEASE_SEC
                    ):
                        skipped.append({"channel": channel, "reason": "in_progress_concurrent"})
                        continue

            if dry_run:
                skipped.append({"channel": channel, "reason": "dry_run"})
                continue

            attempts = _non_neg_int(existing.get("attempts"), default=0) + 1 if isinstance(existing, dict) else 1
            claim_record = {
                "status": "pending",
                "trade_date": trade_date,
                "channel": channel,
                "target_fp": fp_full,
                "claimed_at": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "attempts": attempts,
                "content_sha256": content_hash,
            }
            state[key] = claim_record
            _save_state(ledger_path, state)

        send_error: str | None = None
        try:
            _dispatch_target(
                spec,
                cfg,
                report=report,
                content=card,
                title=title,
                post_fn=post_fn,
                smtp_factory=smtp_factory,
            )
        except Exception as exc:  # noqa: BLE001
            send_error = _redact_error(exc, cfg, spec.get("secrets") or ())

        with _ledger_lock(ledger_path):
            latest_state = _load_state(ledger_path)
            if send_error is not None:
                latest_state[key] = {
                    **(claim_record or {}),
                    "status": "failed",
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "last_error": send_error,
                }
                _save_state(ledger_path, latest_state)
                errors.append({"channel": channel, "error": send_error})
            else:
                latest_state[key] = {
                    **(claim_record or {}),
                    "status": "sent",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "chars": len(card),
                }
                _save_state(ledger_path, latest_state)
                sent.append(channel)

    if errors and sent:
        status = "partial"
    elif errors and not sent:
        status = "error"
    elif sent:
        status = "ok"
    elif any(
        s["reason"] in {"duplicate_same_trade_date", "in_progress_concurrent"}
        for s in skipped
    ):
        status = "skipped_duplicate"
    else:
        status = "dry_run"

    return {
        "status": status,
        "trade_date": trade_date,
        "card_chars": len(card),
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
    }
