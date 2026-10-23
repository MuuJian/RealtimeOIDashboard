"""Notify a dedicated channel on large dashboard 24h OI changes."""

from __future__ import annotations

import logging
from math import isfinite

from realtime_oi_dashboard.infrastructure.telegram.notifier import TelegramNotifier
from realtime_oi_dashboard.infrastructure.telegram.settings import load_channel_settings


class Oi24hChannelService:
    """Keep the channel rule independent of optional full-profile OI alerts."""

    def __init__(self, settings=None, *, notifier_factory=TelegramNotifier):
        settings = load_channel_settings() if settings is None else settings
        self._notifier = notifier_factory(
            bot_token=settings.bot_token if settings.enabled else None,
            chat_id=settings.channel_id if settings.enabled else None,
        )
        self._notified_symbols = set()
        self._drop_threshold = settings.drop_threshold_percent
        self._rise_threshold = settings.rise_threshold_percent

    def observe_updates(self, updates):
        if not self._notifier.is_configured:
            return
        for update in updates:
            change = update.row.get("oi24hChangePercent")
            if isinstance(change, bool) or not isinstance(change, (int, float)):
                continue
            if not isfinite(change):
                continue
            # Below -100% is impossible for non-negative open interest.
            if change < -100:
                continue
            direction = (
                "rise" if change > self._rise_threshold else
                "drop" if change < self._drop_threshold else None
            )
            for other in ("rise", "drop"):
                if other != direction:
                    self._notified_symbols.discard((update.symbol, other))
            key = (update.symbol, direction)
            if direction is None or key in self._notified_symbols:
                continue
            row = update.row
            title = (
                f"持仓 24H 涨幅超过 {self._rise_threshold:g}%" if direction == "rise" else
                f"持仓 24H 跌幅超过 {abs(self._drop_threshold):g}%"
            )
            lines = [
                f"{title}：{update.symbol}",
                f"持仓 24H：{change:+.2f}%",
            ]
            oi_value = row.get("currentOiValue")
            if isinstance(oi_value, (int, float)) and isfinite(oi_value):
                lines.append(f"当前持仓：${oi_value:,.0f}")
            lines.append(f"https://www.binance.com/en/futures/{update.symbol}")
            try:
                queued = self._notifier.send_message("\n".join(lines))
            except Exception:
                logging.getLogger(__name__).warning("Telegram channel queue failed")
                continue
            if queued:
                self._notified_symbols.add(key)

    def retain_symbols(self, symbols):
        self._notified_symbols = {
            key for key in self._notified_symbols if key[0] in symbols
        }

    def close(self):
        self._notifier.stop(timeout=5)
