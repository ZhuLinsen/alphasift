# -*- coding: utf-8 -*-
"""Idempotent notifications (WeCom, Feishu, DingTalk, Telegram, Discord, custom webhook)."""

from __future__ import annotations

import base64
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import threading
import time
from typing import Any
from urllib.parse import quote_plus

import requests

from alphasift.config import Config
from alphasift.daily_report import IM_CARD_MAX_CHARS, ensure_im_card_length, render_daily_im_card
from alphasift.timeutil import parse_timestamp

SUPPORTED_CHANNELS: tuple[str, ...] = (
    "wecom",
    "feishu",
    "dingtalk",
    "telegram",
    "discord",
    "custom",
)
_PROCESS_LOCK = threading.Lock()
_PENDING_LEASE_SEC = 120.0


def configured_channels(config: Config) -> list[str]:
    """Return enabled notification channels in deterministic order."""
    channels: list[str] = []
    if config.wecom_webhook_url:
        channels.append("wecom")
    if config.feishu_webhook_url:
        channels.append("feishu")
    if config.dingtalk_webhook_url:
        channels.append("dingtalk")
    if config.telegram_bot_token and config.telegram_chat_id:
        channels.append("telegram")
    if config.discord_webhook_url:
        channels.append("discord")
    if config.custom_webhook_url:
        channels.append("custom")
    return channels


def notify_readiness(config: Config) -> dict[str, Any]:
    """Return non-secret notification channel readiness metadata."""
    channels = configured_channels(config)
    return {
        "supported_channels": list(SUPPORTED_CHANNELS),
        "configured_channels": channels,
        "any_configured": bool(channels),
        "wecom_configured": "wecom" in channels,
        "feishu_configured": "feishu" in channels,
        "feishu_signed": bool(config.feishu_webhook_url and config.feishu_webhook_secret),
        "dingtalk_configured": "dingtalk" in channels,
        "dingtalk_signed": bool(config.dingtalk_webhook_url and config.dingtalk_webhook_secret),
        "telegram_configured": "telegram" in channels,
        "discord_configured": "discord" in channels,
        "custom_configured": "custom" in channels,
        "custom_authenticated": bool(config.custom_webhook_url and config.custom_webhook_token),
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


def _redact_error(exc: Exception, config: Config) -> str:
    text = f"{type(exc).__name__}: {exc}"
    for secret in (
        config.wecom_webhook_url,
        config.feishu_webhook_url,
        config.feishu_webhook_secret,
        config.dingtalk_webhook_url,
        config.dingtalk_webhook_secret,
        config.telegram_bot_token,
        config.telegram_chat_id,
        config.discord_webhook_url,
        config.custom_webhook_url,
        config.custom_webhook_token,
    ):
        if secret:
            text = text.replace(secret, "***")
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


def _send_wecom(
    webhook_url: str,
    content: str,
    *,
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    resp = post_fn(
        webhook_url,
        json={"msgtype": "markdown", "markdown": {"content": content}},
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    payload = resp.json()
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
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [{"tag": "markdown", "content": content}],
        },
    }
    if secret:
        ts = int(time.time())
        body["timestamp"] = str(ts)
        body["sign"] = _feishu_sign(ts, secret)
    resp = post_fn(webhook_url, json=body, timeout=timeout_sec)
    resp.raise_for_status()
    payload = resp.json()
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
    resp = post_fn(
        target,
        json={"msgtype": "markdown", "markdown": {"title": title, "text": content}},
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    payload = resp.json()
    if int(payload.get("errcode", -1)) != 0:
        raise RuntimeError(f"dingtalk errcode={payload.get('errcode')} errmsg={payload.get('errmsg', '')}")


def _send_telegram(
    bot_token: str,
    chat_id: str,
    content: str,
    *,
    timeout_sec: float,
    post_fn=requests.post,
) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = post_fn(
        url,
        json={"chat_id": chat_id, "text": content, "disable_web_page_preview": True},
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    payload = resp.json()
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
    embed: dict[str, Any] = {
        "title": title[:256],
        "description": content[:4096],
        "color": 3899638,
    }
    if detail_url:
        embed["url"] = detail_url
    resp = post_fn(
        webhook_url,
        json={"content": "", "embeds": [embed]},
        timeout=timeout_sec,
    )
    resp.raise_for_status()


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
    resp = post_fn(webhook_url, **kwargs)
    resp.raise_for_status()


def _resolve_target_channels(
    cfg: Config,
    channels: Sequence[str] | None,
) -> tuple[list[str], list[str]]:
    available = configured_channels(cfg)
    if channels is None:
        return available, available
    requested = [c.strip().lower() for c in channels if c.strip()]
    invalid = [c for c in requested if c not in SUPPORTED_CHANNELS]
    if invalid:
        raise ValueError(f"Unsupported IM channels: {', '.join(invalid)}")
    return available, [c for c in requested if c in available]


def _dispatch_channel(
    channel: str,
    cfg: Config,
    *,
    report: dict[str, Any],
    content: str,
    title: str,
    post_fn=requests.post,
) -> None:
    if channel == "wecom":
        _send_wecom(
            cfg.wecom_webhook_url,
            content,
            timeout_sec=cfg.notify_timeout_sec,
            post_fn=post_fn,
        )
    elif channel == "feishu":
        _send_feishu(
            cfg.feishu_webhook_url,
            content,
            title=title,
            secret=cfg.feishu_webhook_secret,
            timeout_sec=cfg.notify_timeout_sec,
            post_fn=post_fn,
        )
    elif channel == "dingtalk":
        _send_dingtalk(
            cfg.dingtalk_webhook_url,
            content,
            title=title,
            secret=cfg.dingtalk_webhook_secret,
            timeout_sec=cfg.notify_timeout_sec,
            post_fn=post_fn,
        )
    elif channel == "telegram":
        _send_telegram(
            cfg.telegram_bot_token,
            cfg.telegram_chat_id,
            content,
            timeout_sec=cfg.notify_timeout_sec,
            post_fn=post_fn,
        )
    elif channel == "discord":
        _send_discord(
            cfg.discord_webhook_url,
            content,
            title=title,
            detail_url=str(report.get("detail_url") or ""),
            timeout_sec=cfg.notify_timeout_sec,
            post_fn=post_fn,
        )
    elif channel == "custom":
        _send_custom_webhook(
            cfg.custom_webhook_url,
            report=report,
            content=content,
            title=title,
            token=cfg.custom_webhook_token,
            timeout_sec=cfg.notify_timeout_sec,
            post_fn=post_fn,
        )


def send_test_notification(
    *,
    config: Config | None = None,
    channels: Sequence[str] | None = None,
    dry_run: bool = False,
    post_fn=requests.post,
) -> dict[str, Any]:
    """Dispatch a non-persistent connectivity test message to configured channels."""
    cfg = config or Config.from_env()
    available, target_channels = _resolve_target_channels(cfg, channels)
    if not target_channels:
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
    for channel in target_channels:
        if dry_run:
            skipped.append({"channel": channel, "reason": "dry_run"})
            continue
        try:
            _dispatch_channel(
                channel,
                cfg,
                report=test_report,
                content=content,
                title=title,
                post_fn=post_fn,
            )
            sent.append(channel)
        except Exception as exc:  # noqa: BLE001
            errors.append({"channel": channel, "error": _redact_error(exc, cfg)})

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
) -> dict[str, Any]:
    """Push rendered <1200-char card to configured webhooks idempotently by (trade_date, channel)."""
    cfg = config or Config.from_env()
    trade_date = str(report.get("trade_date") or "").strip()
    if not trade_date:
        raise ValueError("Daily report is missing trade_date")

    card = ensure_im_card_length(
        str(report.get("im_card_markdown") or render_daily_im_card(report)),
        max_chars=IM_CARD_MAX_CHARS,
    )
    _, target_channels = _resolve_target_channels(cfg, channels)

    if not target_channels:
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
            "skipped": [{"channel": channel, "reason": "stale_pack"} for channel in target_channels],
            "errors": [],
        }

    ledger_path = Path(state_path) if state_path is not None else cfg.notify_state_path
    content_hash = hashlib.sha256(card.encode("utf-8")).hexdigest()[:16]
    title = f"AlphaSift A股量化观测日报 ({trade_date})"

    sent: list[str] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for channel in target_channels:
        key = f"{trade_date}:{channel}"
        claim_record: dict[str, Any] | None = None

        with _ledger_lock(ledger_path):
            state = _load_state(ledger_path)
            existing = state.get(key)
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
                # status == "failed" or expired pending lease falls through to automatic retry.

            if dry_run:
                skipped.append({"channel": channel, "reason": "dry_run"})
                continue

            attempts = int(existing.get("attempts", 0) or 0) + 1 if isinstance(existing, dict) else 1
            claim_record = {
                "status": "pending",
                "trade_date": trade_date,
                "channel": channel,
                "claimed_at": datetime.now(timezone.utc).isoformat(),
                "pid": os.getpid(),
                "attempts": attempts,
                "content_sha256": content_hash,
            }
            state[key] = claim_record
            _save_state(ledger_path, state)

        send_error: str | None = None
        try:
            _dispatch_channel(
                channel,
                cfg,
                report=report,
                content=card,
                title=title,
                post_fn=post_fn,
            )
        except Exception as exc:  # noqa: BLE001
            send_error = _redact_error(exc, cfg)

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
