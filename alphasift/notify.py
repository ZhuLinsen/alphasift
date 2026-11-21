# -*- coding: utf-8 -*-
"""Unified 1-line & per-channel idempotent notifications (12 native channels + optional Apprise)."""

from __future__ import annotations

import base64
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from email.message import EmailMessage
import fcntl
import hashlib
import hmac
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
from alphasift.daily_report import IM_CARD_MAX_CHARS, ensure_im_card_length, render_daily_im_card
from alphasift.timeutil import parse_timestamp

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


def _retry_delay(resp: Any, default: float = 0.5) -> float:
    if getattr(resp, "status_code", None) == 429:
        headers = getattr(resp, "headers", None)
        if hasattr(headers, "get"):
            ra_raw = headers.get("Retry-After") or headers.get("retry-after")
            if ra_raw is not None:
                try:
                    return max(0.0, min(float(str(ra_raw).strip()), 5.0))
                except ValueError:
                    pass
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
    attempts = max(0, int(max_retries)) + 1
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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}.{threading.get_ident()}")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def _ledger_lock(ledger_path: Path) -> Iterator[None]:
    """Serialize push ledger access across threads and OS processes."""
    lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _PROCESS_LOCK:
        with open(lock_path, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _send_wecom(webhook_url: str, content: str, *, timeout_sec: float, post_fn=requests.post) -> None:
    resp = _post_with_retry(
        post_fn,
        webhook_url,
        json={"msgtype": "markdown", "markdown": {"content": content}},
        timeout=timeout_sec,
    )
    payload = _safe_json(resp)
    if int(payload.get("errcode", -1)) != 0:
        raise RuntimeError(f"wecom errcode={payload.get('errcode')} errmsg={payload.get('errmsg', '')}")


def _send_feishu(
    webhook_url: str,
    content: str,
    *,
    title: str,
    secret: str = "",
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    body: dict[str, Any] = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
            "elements": [{"tag": "markdown", "content": content}],
        },
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
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    target = webhook_url
    if secret:
        ts_ms = int(time.time() * 1000)
        sep = "&" if "?" in webhook_url else "?"
        target = f"{webhook_url}{sep}timestamp={ts_ms}&sign={_dingtalk_sign(ts_ms, secret)}"
    resp = _post_with_retry(
        post_fn,
        target,
        json={"msgtype": "markdown", "markdown": {"title": title, "text": content}},
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
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    body: dict[str, Any] = {
        "token": token,
        "title": title[:100],
        "content": content,
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
    resp = _post_with_retry(
        post_fn,
        url,
        json={"title": title[:32], "desp": content},
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


def _send_telegram(bot_token: str, chat_id: str, content: str, *, timeout_sec: float, post_fn=requests.post) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = _post_with_retry(
        post_fn,
        url,
        json={"chat_id": chat_id, "text": content, "disable_web_page_preview": True},
        timeout=timeout_sec,
    )
    payload = _safe_json(resp)
    if payload.get("ok") is not True:
        raise RuntimeError(f"telegram error={payload.get('description', 'unknown')}")


def _send_discord(
    webhook_url: str,
    content: str,
    *,
    title: str,
    detail_url: str = "",
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    embed: dict[str, Any] = {"title": title[:256], "description": content[:4096], "color": 3899638}
    if detail_url:
        embed["url"] = detail_url
    _post_with_retry(post_fn, webhook_url, json={"content": "", "embeds": [embed]}, timeout=timeout_sec)


def _send_slack(webhook_url: str, content: str, *, title: str, timeout_sec: float, post_fn=requests.post) -> None:
    _post_with_retry(post_fn, webhook_url, json={"text": f"*{title}*\n{content}"}, timeout=timeout_sec)


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
    smtp_host: str = "",
    smtp_port: int = 0,
    timeout_sec: float = 10.0,
    smtp_factory=None,
) -> None:
    host, port, mode = _resolve_smtp_settings(sender, smtp_host, smtp_port)
    recips = [r.strip() for r in receivers if r.strip()] or [sender]
    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = sender
    msg["To"] = ", ".join(recips)
    msg.set_content(content, charset="utf-8")

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
            "flagged_announcements": int(ann.get("flagged_count") or 0),
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
        _send_wecom(target, content, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "feishu":
        _send_feishu(target, content, title=title, secret=secret, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "dingtalk":
        _send_dingtalk(target, content, title=title, secret=secret, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "pushplus":
        _send_pushplus(target, content, title=title, topic=str(extra.get("topic") or ""), timeout_sec=timeout, post_fn=post_fn)
    elif ch == "serverchan":
        _send_serverchan(target, content, title=title, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "bark":
        _send_bark(target, content, title=title, detail_url=str(report.get("detail_url") or ""), timeout_sec=timeout, post_fn=post_fn)
    elif ch == "email":
        _send_email(
            str(extra.get("sender") or target),
            secret or str(extra.get("password") or ""),
            extra.get("receivers") or [target],
            content,
            title=title,
            smtp_host=str(extra.get("smtp_host") or ""),
            smtp_port=int(extra.get("smtp_port") or 0),
            timeout_sec=timeout,
            smtp_factory=smtp_factory,
        )
    elif ch == "telegram":
        _send_telegram(target, str(extra.get("chat_id") or ""), content, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "discord":
        _send_discord(target, content, title=title, detail_url=str(report.get("detail_url") or ""), timeout_sec=timeout, post_fn=post_fn)
    elif ch == "slack":
        _send_slack(target, content, title=title, timeout_sec=timeout, post_fn=post_fn)
    elif ch == "ntfy":
        _send_ntfy(target, content, title=title, detail_url=str(report.get("detail_url") or ""), timeout_sec=timeout, post_fn=post_fn)
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
    title = f"AlphaSift A股量化观测日报 ({trade_date})"

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
        legacy_key = f"{trade_date}:{channel}"
        fp_key = f"{trade_date}:{channel}:{fp_full}"
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

            attempts = int(existing.get("attempts", 0) or 0) + 1 if isinstance(existing, dict) else 1
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
