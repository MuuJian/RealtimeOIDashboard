"""Server-only Telegram channel settings, with environment overrides."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "telegram.json"


@dataclass(frozen=True, slots=True)
class TelegramChannelSettings:
    bot_token: str = field(default="", repr=False)
    channel_id: str = ""
    enabled: bool = True
    drop_threshold_percent: float = -50.0
    rise_threshold_percent: float = 100.0


def load_channel_settings(path=None, *, environ=None) -> TelegramChannelSettings:
    env = os.environ if environ is None else environ
    explicit_path = path or env.get("TELEGRAM_CONFIG_FILE")
    config_path = Path(explicit_path) if explicit_path else DEFAULT_CONFIG_PATH
    payload = {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if explicit_path:
            raise ValueError("Telegram configuration file does not exist") from None
    except (OSError, ValueError):
        raise ValueError("Unable to read Telegram configuration JSON") from None
    if not isinstance(payload, dict):
        raise ValueError("Telegram configuration must be a JSON object")

    enabled = payload.get("enabled", True)
    if "TELEGRAM_CHANNEL_ENABLED" in env:
        raw = env["TELEGRAM_CHANNEL_ENABLED"].strip().lower()
        if raw not in {"true", "false", "1", "0"}:
            raise ValueError("TELEGRAM_CHANNEL_ENABLED must be true, false, 1 or 0")
        enabled = raw in {"true", "1"}
    if not isinstance(enabled, bool):
        raise ValueError("Telegram enabled must be a boolean")

    token = env.get("TELEGRAM_BOT_TOKEN", payload.get("bot_token", ""))
    channel = env.get("TELEGRAM_CHANNEL_ID", payload.get("channel_id", ""))
    if not isinstance(token, str):
        raise ValueError("Telegram bot_token must be a string")
    if isinstance(channel, bool) or not isinstance(channel, (str, int)):
        raise ValueError("Telegram channel_id must be a string or integer")
    drop_threshold = env.get(
        "TELEGRAM_OI_24H_DROP_PERCENT", payload.get("drop_threshold_percent", -50)
    )
    try:
        if isinstance(drop_threshold, bool):
            raise ValueError
        drop_threshold = float(drop_threshold)
        if not isfinite(drop_threshold) or not -100 < drop_threshold < 0:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValueError(
            "Telegram drop_threshold_percent must be between -100 and 0 (exclusive)"
        ) from None
    rise_threshold = env.get(
        "TELEGRAM_OI_24H_RISE_PERCENT", payload.get("rise_threshold_percent", 100)
    )
    try:
        if isinstance(rise_threshold, bool):
            raise ValueError
        rise_threshold = float(rise_threshold)
        if not isfinite(rise_threshold) or rise_threshold <= 0:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValueError(
            "Telegram rise_threshold_percent must be a finite positive number"
        ) from None
    return TelegramChannelSettings(
        bot_token=token.strip(),
        channel_id=str(channel).strip(),
        enabled=enabled,
        drop_threshold_percent=drop_threshold,
        rise_threshold_percent=rise_threshold,
    )
