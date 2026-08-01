"""Build per-symbol OI updates, sequentially or with a bounded worker pool."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import isfinite

from realtime_oi_dashboard.errors import PollingStopped
from realtime_oi_dashboard.market_data import future_timestamp_ms
from realtime_oi_dashboard.oi_state import OiUpdate


class OiBatchUpdater:
    """Convert market snapshots into timestamped dashboard row updates."""

    def __init__(self, client, stop_event, record_error, *, workers: int) -> None:
        self.client = client
        self.stop_event = stop_event
        self.record_error = record_error
        self.workers = workers

    def update_symbols(
        self,
        batch,
        tickers,
        funding_rates,
        market_caps,
        *,
        executor=None,
        build_update=None,
    ):
        build_update = build_update or self.build_symbol_update
        if self.workers <= 1 or len(batch) <= 1:
            return self._update_sequentially(
                batch,
                tickers,
                funding_rates,
                market_caps,
                build_update,
            )

        if executor is not None:
            return self._update_in_parallel(
                batch,
                tickers,
                funding_rates,
                market_caps,
                executor,
                build_update,
            )

        max_workers = min(self.workers, len(batch))
        with ThreadPoolExecutor(max_workers=max_workers) as temporary_executor:
            return self._update_in_parallel(
                batch,
                tickers,
                funding_rates,
                market_caps,
                temporary_executor,
                build_update,
            )

    def _update_sequentially(
        self,
        batch,
        tickers,
        funding_rates,
        market_caps,
        build_update,
    ):
        results = []
        for symbol in batch:
            if self.stop_event.is_set():
                break
            try:
                results.append(
                    build_update(
                        symbol,
                        tickers,
                        funding_rates,
                        market_caps,
                    )
                )
            except PollingStopped:
                break
            except Exception as exc:
                self.record_error(symbol, exc)
                results.append(None)
        return results

    def _update_in_parallel(
        self,
        batch,
        tickers,
        funding_rates,
        market_caps,
        executor,
        build_update=None,
    ):
        build_update = build_update or self.build_symbol_update
        futures = {}
        try:
            for symbol in batch:
                future = executor.submit(
                    build_update,
                    symbol,
                    tickers,
                    funding_rates,
                    market_caps,
                )
                futures[future] = symbol
        except BaseException:
            for future in futures:
                future.cancel()
            raise

        results_by_symbol = {symbol: None for symbol in batch}
        for future in as_completed(futures):
            if self.stop_event.is_set():
                for pending in futures:
                    pending.cancel()
                break
            symbol = futures[future]
            try:
                results_by_symbol[symbol] = future.result()
            except PollingStopped:
                for pending in futures:
                    pending.cancel()
                break
            except Exception as exc:
                self.record_error(symbol, exc)
        return [results_by_symbol[symbol] for symbol in batch]

    def build_symbol_update(
        self,
        symbol,
        tickers,
        funding_rates,
        market_caps=None,
    ):
        if self.stop_event.is_set():
            return None

        ticker = tickers.get(symbol)
        if not ticker:
            raise ValueError("ticker data unavailable")
        price = ticker["price"]
        volume_24h = ticker["volume24h"]

        current_oi = self.client.get_open_interest(symbol)
        measured_wall_time = time.time()
        measured_at = time.monotonic()
        if self.stop_event.is_set():
            return None

        current_oi_value = current_oi * price
        if not isfinite(current_oi_value):
            raise ValueError("open-interest value is not finite")

        funding = funding_rates.get(symbol, {}) if funding_rates else {}
        funding_rate_percent = funding.get("fundingRatePercent")
        now_ms = int(measured_wall_time * 1000)
        next_funding_time = future_timestamp_ms(
            funding.get("nextFundingTime"),
            now_ms,
        )
        oi_history = self.client.get_oi_history_changes(
            symbol,
            current_oi,
            price,
        )
        market_cap = (market_caps or {}).get(symbol, {}).get("marketCap")

        return OiUpdate(
            symbol=symbol,
            row={
                "symbol": symbol,
                "price": price,
                "volume24h": volume_24h,
                "currentOi": current_oi,
                "currentOiValue": current_oi_value,
                "marketCap": market_cap,
                "oiUpdatedAt": now_ms,
                "priceChangePercent": ticker.get("priceChangePercent"),
                "fundingRatePercent": funding_rate_percent,
                "nextFundingTime": next_funding_time,
                **oi_history,
            },
            measured_at=measured_at,
        )
