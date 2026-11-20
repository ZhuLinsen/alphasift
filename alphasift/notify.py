# -*- coding: utf-8 -*-
"""Idempotent IM notifications (WeCom, Feishu, Telegram) for CN daily reports."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
from typing import Any

import requests

from alphasift.config import Config
from alphasift.daily_report import IM_CARD_MAX_CHARS, ensure_im_card_length, render_daily_im_card

SUPPORTED_CHANNELS: tuple[str, ...] = ("wecom", "feishu", "telegram")


def configured_channels(config: Config) -> list[str]:
    """Return enabled notification channels in deterministic order."""
    channels: list[str] = []
    if config.wecom_webhook_url:
        channels.append("wecom")
    if config.feishu_webhook_url:
        channels.append("feishu")
    if config.telegram_bot_token and config.telegram_chat_id:
        channels.append("telegram")
    return channels


def notify_readiness(config: Config) -> dict[str, Any]:
    """Return non-secret notification channel readiness metadata."""
    channels = configured_channels(config)
    return {
        "configured_channels": channels,
        "any_configured": bool(channels),
        "wecom_configured": "wecom" in channels,
        "feishu_configured": "feishu" in channels,
        "feishu_signed": bool(config.feishu_webhook_url and config.feishu_webhook_secret),
        "telegram_configured": "telegram" in channels,
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


def _redact_error(exc: Exception, config: Config) -> str:
    text = f"{type(exc).__name__}: {exc}"
    for secret in (
        config.wecom_webhook_url,
        config.feishu_webhook_url,
        config.feishu_webhook_secret,
        config.telegram_bot_token,
        config.telegram_chat_id,
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
    tmp = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


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
    """Push rendered <1200-char card to configured IM webhooks idempotently by (trade_date, channel)."""
    cfg = config or Config.from_env()
    trade_date = str(report.get("trade_date") or "").strip()
    if not trade_date:
        raise ValueError("Daily report is missing trade_date")

    card = ensure_im_card_length(
        str(report.get("im_card_markdown") or render_daily_im_card(report)),
        max_chars=IM_CARD_MAX_CHARS,
    )
    available = configured_channels(cfg)
    if channels is not None:
        requested = [c.strip().lower() for c in channels if c.strip()]
        invalid = [c for c in requested if c not in SUPPORTED_CHANNELS]
        if invalid:
            raise ValueError(f"Unsupported IM channels: {', '.join(invalid)}")
        target_channels = [c for c in requested if c in available]
    else:
        target_channels = available

    if not target_channels:
        return {
            "status": "skipped_no_channels",
            "trade_date": trade_date,
            "card_chars": len(card),
            "sent": [],
            "skipped": [],
            "errors": [],
        }

    ledger_path = Path(state_path) if state_path is not None else cfg.notify_state_path
    state = _load_state(ledger_path)
    content_hash = hashlib.sha256(card.encode("utf-8")).hexdigest()[:16]
    title = f"AlphaSift A股量化观测日报 ({trade_date})"

    sent: list[str] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    state_dirty = False

    for channel in target_channels:
        key = f"{trade_date}:{channel}"
        if not force and key in state:
            skipped.append({"channel": channel, "reason": "duplicate_same_trade_date"})
            continue
        if dry_run:
            skipped.append({"channel": channel, "reason": "dry_run"})
            continue

        try:
            if channel == "wecom":
                _send_wecom(
                    cfg.wecom_webhook_url,
                    card,
                    timeout_sec=cfg.notify_timeout_sec,
                    post_fn=post_fn,
                )
            elif channel == "feishu":
                _send_feishu(
                    cfg.feishu_webhook_url,
                    card,
                    title=title,
                    secret=cfg.feishu_webhook_secret,
                    timeout_sec=cfg.notify_timeout_sec,
                    post_fn=post_fn,
                )
            elif channel == "telegram":
                _send_telegram(
                    cfg.telegram_bot_token,
                    cfg.telegram_chat_id,
                    card,
                    timeout_sec=cfg.notify_timeout_sec,
                    post_fn=post_fn,
                )
        except Exception as exc:  # noqa: BLE001
            errors.append({"channel": channel, "error": _redact_error(exc, cfg)})
            continue

        sent.append(channel)
        state[key] = {
            "trade_date": trade_date,
            "channel": channel,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "content_sha256": content_hash,
            "chars": len(card),
        }
        state_dirty = True

    if state_dirty:
        _save_state(ledger_path, state)

    if errors and sent:
        status = "partial"
    elif errors and not sent:
        status = "error"
    elif sent:
        status = "ok"
    else:
        status = "skipped_duplicate" if any(s["reason"] == "duplicate_same_trade_date" for s in skipped) else "dry_run"

    return {
        "status": status,
        "trade_date": trade_date,
        "card_chars": len(card),
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
    }
