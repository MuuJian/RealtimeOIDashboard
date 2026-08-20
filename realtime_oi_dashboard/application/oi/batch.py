"""Build per-symbol OI updates with bounded concurrency."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from math import isfinite

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.domain.oi.row import OIRowBuilder


class OIBatchRunner:
    """Fetch one bounded OI batch and isolate per-symbol failures."""

    def __init__(
        self,
        client,
        stop_event,
        record_error,
        *,
        workers: int,
        row_builder=None,
    ) -> None:
        self.client = client
        self.stop_event = stop_event
        self.record_error = record_error
        self.workers = workers
        self.row_builder = row_builder or OIRowBuilder()

    def run(
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

        current_oi = self.client.get_open_interest(symbol)
        measured_wall_time = time.time()
        measured_at = time.monotonic()
        if self.stop_event.is_set():
            return None

        # Preserve the previous failure order: reject invalid OI values before
        # requesting historical OI data.
        if not isfinite(current_oi * price):
            raise ValueError("open-interest value is not finite")

        oi_history = self.client.get_oi_history_changes(
            symbol,
            current_oi,
            price,
            measured_wall_time,
        )
        return self.row_builder.build(
            symbol=symbol,
            ticker=ticker,
            funding=(funding_rates or {}).get(symbol, {}),
            market_cap=(market_caps or {}).get(symbol, {}).get("marketCap"),
            current_oi=current_oi,
            oi_history=oi_history,
            measured_wall_time=measured_wall_time,
            measured_at=measured_at,
        )
