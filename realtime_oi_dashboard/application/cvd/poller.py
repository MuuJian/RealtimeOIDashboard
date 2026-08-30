"""Coordinate the dynamically sharded CVD service."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from realtime_oi_dashboard.application.cvd.backfill import CvdBackfillQueue
from realtime_oi_dashboard.application.cvd.shard_allocator import (
    CvdShardAllocator,
    desired_shard_count,
)
from realtime_oi_dashboard.application.cvd.presenter import CvdPresenter
from realtime_oi_dashboard.application.cvd.snapshot_service import (
    CvdSnapshotService,
)
from realtime_oi_dashboard.application.cvd.store import CvdStore
from realtime_oi_dashboard.application.cvd.universe import CvdUniverseManager
from realtime_oi_dashboard.domain.cvd.model import MINUTE_MS
from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.infrastructure.binance.cvd_stream import BinanceCvdShard
from realtime_oi_dashboard.infrastructure.storage.cvd_snapshot import (
    CvdSnapshotRepository,
    PERSIST_MINUTES,
)
from realtime_oi_dashboard.infrastructure.http import JsonHttpClient
from realtime_oi_dashboard.infrastructure.binance.market_data import (
    DirectBinanceMarketData,
    resolve_market_data_source,
)


FAPI_BASE_URL = "https://fapi.binance.com"
EXCHANGE_INFO_URL = f"{FAPI_BASE_URL}/fapi/v1/exchangeInfo"
KLINES_URL = f"{FAPI_BASE_URL}/fapi/v1/klines"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CVD_PERSIST_INTERVAL_SECONDS = 5 * 60
SUPERVISOR_TICK_SECONDS = 1.0


class CvdPoller:
    """Coordinate universe refresh, WSS shards, repair, and publication."""

    def __init__(
        self,
        *,
        market_data=None,
        shared_rest_cache=None,
        http_client=None,
        websocket_factory=None,
        now_ms=None,
        monotonic=None,
        universe_refresh_seconds=15 * 60,
        snapshot_path=None,
        persist_enabled=True,
        persist_minutes=PERSIST_MINUTES,
        persist_interval_seconds=CVD_PERSIST_INTERVAL_SECONDS,
        target_symbols_per_shard=150,
        target_messages_per_second_per_shard=600,
        max_processing_lag_ms=500,
        scale_out_confirm_seconds=30,
        backfill_requests_per_second=4,
        backfill_workers=2,
        connection_rotate_seconds=85_800,
        shard_factory=None,
    ) -> None:
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self._owns_http_client = http_client is None
        self.http_client = http_client or JsonHttpClient(
            sleep=self._wait_for_retry,
            check_cancelled=self._raise_if_stopped,
        )
        self.market_data = resolve_market_data_source(
            market_data=market_data,
            legacy_shared_cache=shared_rest_cache,
            direct_factory=lambda: DirectBinanceMarketData(
                self.http_client.get_json,
            ),
            required_methods=("get_exchange_info",),
        )
        self.websocket_factory = websocket_factory
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.monotonic = monotonic or time.monotonic
        self.target_symbols_per_shard = int(target_symbols_per_shard)
        self.connection_rotate_seconds = float(connection_rotate_seconds)
        self.snapshot_repository = CvdSnapshotRepository(
            Path(snapshot_path) if snapshot_path else DATA_DIR / "cvd_snapshot.json",
            persist_minutes=int(persist_minutes),
        )
        self.store = CvdStore(now_ms=self.now_ms)
        self.universe = CvdUniverseManager(
            self._load_exchange_info,
            refresh_seconds=universe_refresh_seconds,
            monotonic=self.monotonic,
        )
        self.allocator = CvdShardAllocator(
            target_symbols_per_shard=self.target_symbols_per_shard,
            target_messages_per_second=target_messages_per_second_per_shard,
            max_processing_lag_ms=max_processing_lag_ms,
            scale_out_confirm_seconds=scale_out_confirm_seconds,
        )
        self._shard_factory = shard_factory or self._create_shard
        self._shards: dict[int, BinanceCvdShard] = {}
        self._assignments: dict[int, set[str]] = {}
        self._actual_assignments: dict[int, set[str]] = {}
        self._pending_migrations: dict[str, tuple[int, int]] = {}
        self._disconnected_at: dict[int, int] = {}
        self._running = False
        self._closed = False
        self._close_lock = threading.Lock()
        self._top_error = None
        self.backfill = CvdBackfillQueue(
            self._load_backfill,
            self._apply_backfill,
            requests_per_second=backfill_requests_per_second,
            workers=backfill_workers,
        )
        self.presenter = CvdPresenter(
            self.store,
            self.universe,
            self.backfill,
            self._shards_snapshot,
            now_ms=self.now_ms,
            target_symbols_per_shard=self.target_symbols_per_shard,
        )
        self.snapshots = CvdSnapshotService(
            self.snapshot_repository,
            self.store,
            enabled=persist_enabled,
            persist_minutes=persist_minutes,
            interval_seconds=persist_interval_seconds,
            now_ms=self.now_ms,
            monotonic=self.monotonic,
            is_stopped=self.stop_event.is_set,
        )

    def run_forever(self) -> None:
        self._running = True
        try:
            self.snapshots.restore()
            try:
                change = self.refresh_universe(force=True)
                self._top_error = None
            except Exception as exc:
                change = None
                self._top_error = str(exc)
            for shard in self._shards.values():
                shard.start()
            self.backfill.start()
            if change is not None:
                for symbol in change.added:
                    self._enqueue_backfill_if_missing(symbol)

            while not self.stop_event.wait(SUPERVISOR_TICK_SECONDS):
                try:
                    change = self.refresh_universe()
                    if change is not None and change.changed:
                        for symbol in change.added:
                            self._enqueue_backfill_if_missing(symbol)
                    self._fill_silent_minutes()
                    self._scale_if_needed()
                    self.store.publish(now_ms=self.now_ms())
                    self.snapshots.save_if_due()
                    self._top_error = None
                except PollingStopped:
                    break
                except Exception as exc:
                    self._top_error = str(exc)
        except PollingStopped:
            pass
        except Exception as exc:
            self._top_error = str(exc)
        finally:
            self.close()

    def refresh_universe(self, *, force=False):
        change = self.universe.refresh_if_due(force=force)
        if change is None:
            return None
        self.store.set_universe(set(change.symbols))
        if change.changed or not self._assignments:
            self._reconcile_shards()
        return change

    def get_state(self):
        return self.presenter.build(
            top_error=self._top_error,
            snapshot_error=self.snapshots.error,
        )

    def _shards_snapshot(self):
        with self.lock:
            return list(self._shards.values())

    def stop(self) -> None:
        self.stop_event.set()
        with self.lock:
            shards = list(self._shards.values())
        asynchronously_stopped = []
        first_error = None
        for shard in shards:
            try:
                request_stop = getattr(shard, "request_stop", None)
                if callable(request_stop):
                    request_stop()
                    asynchronously_stopped.append(shard)
                else:
                    shard.stop()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        deadline = time.monotonic() + 5.0
        for shard in asynchronously_stopped:
            try:
                shard.wait_stopped(timeout=max(deadline - time.monotonic(), 0.0))
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        try:
            self.backfill.stop()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        if first_error is not None:
            raise first_error

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            first_error = None
            for cleanup in (
                self.stop,
                lambda: self.store.publish(now_ms=self.now_ms()),
                lambda: self.snapshots.save(force=True),
            ):
                try:
                    cleanup()
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
            if self._owns_http_client:
                try:
                    self.http_client.close()
                except BaseException as exc:
                    if first_error is None:
                        first_error = exc
            if first_error is not None:
                raise first_error
            self._closed = True

    def _load_exchange_info(self):
        self._raise_if_stopped()
        result = self.market_data.get_exchange_info()
        self._raise_if_stopped()
        return result

    def _load_backfill(self, symbol: str):
        self._raise_if_stopped()
        return self.http_client.get_json(
            KLINES_URL,
            params={"symbol": symbol, "interval": "1m", "limit": 16},
            timeout=12,
            attempts=1,
        )

    def _apply_backfill(self, symbol: str, rows) -> None:
        if not isinstance(rows, list):
            raise ValueError("invalid CVD backfill response")
        applied = 0
        current_open = self.now_ms() // MINUTE_MS * MINUTE_MS
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) <= 10:
                continue
            try:
                open_time = int(row[0])
                updated_at = int(row[6])
            except (TypeError, ValueError, OverflowError):
                continue
            if self.store.update_bucket(
                symbol,
                open_time=open_time,
                quote_volume=row[7],
                taker_buy_quote_volume=row[10],
                closed=open_time < current_open,
                source="rest",
                updated_at=updated_at,
            ):
                applied += 1
        if applied == 0:
            self.store.mark_partial(symbol, "missing CVD backfill data")
            raise ValueError("CVD backfill contained no usable rows")

    def _reconcile_shards(self) -> None:
        with self.lock:
            if self.stop_event.is_set():
                return
            symbols = self.store.active_symbols()
            base_count = desired_shard_count(
                len(symbols),
                target_symbols_per_shard=self.target_symbols_per_shard,
            )
            target_count = max(base_count, len(self._shards))
            rates = _combined_symbol_rates(self._shards.values())
            assignments = self.allocator.allocate(
                symbols,
                target_count,
                message_rates=rates,
            )
            new_shards = []
            for shard_id in range(target_count):
                if shard_id not in self._shards:
                    shard = self._shard_factory(shard_id)
                    self._shards[shard_id] = shard
                    new_shards.append(shard)
            self._apply_assignments(assignments)
            if self._running:
                for shard in new_shards:
                    shard.start()

    def _scale_if_needed(self) -> None:
        with self.lock:
            if self.stop_event.is_set():
                return
            metrics = [shard.metrics() for shard in self._shards.values()]
            recommended = self.allocator.recommended_count(
                symbol_count=len(self.store.active_symbols()),
                current_count=len(self._shards),
                shard_metrics=metrics,
                now=self.monotonic(),
            )
            if recommended > len(self._shards):
                rates = _combined_symbol_rates(self._shards.values())
                assignments = self.allocator.allocate(
                    self.store.active_symbols(),
                    recommended,
                    message_rates=rates,
                )
                for shard_id in range(len(self._shards), recommended):
                    shard = self._shard_factory(shard_id)
                    self._shards[shard_id] = shard
                self._apply_assignments(assignments)
                for shard_id in range(len(metrics), recommended):
                    self._shards[shard_id].start()

    def _apply_assignments(self, assignments: dict[int, set[str]]) -> None:
        with self.lock:
            previous_by_symbol = {
                symbol: shard_id
                for shard_id, symbols in self._assignments.items()
                for symbol in symbols
            }
            next_by_symbol = {
                symbol: shard_id
                for shard_id, symbols in assignments.items()
                for symbol in symbols
            }
            actual = {
                shard_id: set(symbols) for shard_id, symbols in assignments.items()
            }
            pending = {}
            for symbol, new_shard in next_by_symbol.items():
                old_shard = previous_by_symbol.get(symbol)
                if old_shard is None or old_shard == new_shard:
                    continue
                actual.setdefault(old_shard, set()).add(symbol)
                pending[symbol] = (old_shard, new_shard)
            for symbol, (old_shard, new_shard) in self._pending_migrations.items():
                if next_by_symbol.get(symbol) != new_shard:
                    continue
                actual.setdefault(old_shard, set()).add(symbol)
                pending[symbol] = (old_shard, new_shard)

            # Subscribe target shards before touching source subscriptions.
            for shard_id, symbols in actual.items():
                self._shards[shard_id].update_symbols(symbols)
            self._assignments = {
                shard_id: set(symbols)
                for shard_id, symbols in assignments.items()
            }
            self._actual_assignments = actual
            self._pending_migrations = pending

    def _create_shard(self, shard_id: int):
        return BinanceCvdShard(
            shard_id,
            self._handle_kline,
            self._handle_shard_health,
            websocket_factory=self.websocket_factory,
            monotonic=self.monotonic,
            rotate_seconds=self.connection_rotate_seconds,
        )

    def _handle_kline(self, shard_id: int, symbol: str, values: dict) -> None:
        if self.store.update_bucket(symbol, **values):
            self.store.set_connected({symbol}, True)
        with self.lock:
            migration = self._pending_migrations.get(symbol)
            if migration is not None and migration[1] == shard_id:
                old_shard, _ = migration
                self._pending_migrations.pop(symbol, None)
                old_symbols = self._actual_assignments.get(old_shard, set())
                old_symbols.discard(symbol)
                self._shards[old_shard].update_symbols(old_symbols)

    def _handle_shard_health(
        self,
        shard_id: int,
        symbols: set[str],
        connected: bool,
        reason: str | None,
    ) -> None:
        now_ms = self.now_ms()
        self.store.set_connected(symbols, connected, reason)
        if connected:
            disconnected_at = self._disconnected_at.pop(shard_id, None)
            if (
                disconnected_at is not None
                and disconnected_at // MINUTE_MS < now_ms // MINUTE_MS
            ):
                for symbol in symbols:
                    self._enqueue_backfill_if_missing(symbol)
        else:
            self._disconnected_at.setdefault(shard_id, now_ms)

    def _fill_silent_minutes(self) -> None:
        now_ms = self.now_ms()
        for shard_id, symbols in self._assignments.items():
            shard = self._shards.get(shard_id)
            if shard is None:
                continue
            metrics = shard.metrics()
            if not metrics["connected"]:
                continue
            confirmed_reader = getattr(shard, "confirmed_symbols", None)
            confirmed = (
                confirmed_reader()
                if callable(confirmed_reader)
                else symbols
                if metrics.get("confirmedSymbols") == len(symbols)
                else set()
            )
            self.store.fill_closed_zero_buckets(
                symbols.intersection(confirmed),
                now_ms=now_ms,
            )

    def _enqueue_backfill_if_missing(self, symbol: str) -> bool:
        current_open = self.now_ms() // MINUTE_MS * MINUTE_MS
        missing_history = any(
            open_time < current_open
            for open_time in self.store.missing_recent_buckets(
                symbol,
                now_ms=self.now_ms(),
                minutes=15,
            )
        )
        return missing_history and self.backfill.enqueue(symbol)

    def _raise_if_stopped(self) -> None:
        if self.stop_event.is_set():
            raise PollingStopped

    def _wait_for_retry(self, delay: float) -> None:
        if self.stop_event.wait(delay):
            raise PollingStopped


def _combined_symbol_rates(shards) -> dict[str, float]:
    rates = {}
    for shard in shards:
        for symbol, rate in shard.metrics().get("symbolRates", {}).items():
            rates[symbol] = max(rate, rates.get(symbol, 0.0))
    return rates
