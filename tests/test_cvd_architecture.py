import io
import json
import tempfile
import threading
import time
import unittest
import websocket
from pathlib import Path
from unittest.mock import patch

from realtime_oi_dashboard.application.cvd.backfill import CvdBackfillQueue
from realtime_oi_dashboard.application.cvd.shard_allocator import (
    CvdShardAllocator,
    desired_shard_count,
)
from realtime_oi_dashboard.application.cvd.universe import (
    CvdUniverseManager,
    select_cvd_symbols,
)
from realtime_oi_dashboard.infrastructure.binance.cvd_stream import (
    BinanceCvdShard,
)
from realtime_oi_dashboard.infrastructure.binance.weight_budget import (
    BinanceCooldownError,
    BinanceWeightBudget,
    request_weight,
)
from realtime_oi_dashboard.infrastructure.storage.cvd_snapshot import (
    CvdSnapshotRepository,
)


def exchange_info(symbols):
    return {
        "symbols": [
            {
                "symbol": symbol,
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
                "status": "TRADING",
            }
            for symbol in symbols
        ]
    }


class ManualClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value


class UniverseAndAllocatorTests(unittest.TestCase):
    def test_universe_filters_only_trading_usdt_perpetuals(self):
        payload = exchange_info(["BTCUSDT"])
        payload["symbols"].extend([
            {
                "symbol": "ETHUSDT",
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
                "status": "BREAK",
            },
            {
                "symbol": "BTCUSD_PERP",
                "quoteAsset": "USD",
                "contractType": "PERPETUAL",
                "status": "TRADING",
            },
        ])

        self.assertEqual(select_cvd_symbols(payload), {"BTCUSDT"})

    def test_universe_refresh_failure_keeps_last_success(self):
        values = [exchange_info(["BTCUSDT"]), ConnectionError("failed")]

        def load():
            value = values.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        manager = CvdUniverseManager(load)
        first = manager.refresh_if_due(force=True)
        second = manager.refresh_if_due(force=True)

        self.assertEqual(first.added, {"BTCUSDT"})
        self.assertEqual(second.symbols, {"BTCUSDT"})
        self.assertFalse(second.changed)

    def test_shard_count_scales_without_a_total_symbol_limit(self):
        self.assertEqual(desired_shard_count(30), 1)
        self.assertEqual(desired_shard_count(300), 2)
        self.assertEqual(desired_shard_count(526), 4)
        self.assertEqual(desired_shard_count(1000), 7)

    def test_scale_out_rebalances_existing_assignments(self):
        allocator = CvdShardAllocator()
        symbols = {f"COIN{index}USDT" for index in range(300)}
        allocator.allocate(symbols, 1)

        assignments = allocator.allocate(symbols, 2)

        self.assertEqual([len(assignments[index]) for index in range(2)], [150, 150])
        self.assertEqual(set().union(*assignments.values()), symbols)

    def test_load_overage_must_persist_before_extra_scale_out(self):
        allocator = CvdShardAllocator()
        metrics = [{
            "symbolCount": 10,
            "messagesPerSecond": 700,
            "processingLagMs": 10,
            "queueDepth": 0,
        }]

        self.assertEqual(allocator.recommended_count(
            symbol_count=10, current_count=1, shard_metrics=metrics, now=0
        ), 1)
        self.assertEqual(allocator.recommended_count(
            symbol_count=10, current_count=1, shard_metrics=metrics, now=29.9
        ), 1)
        self.assertEqual(allocator.recommended_count(
            symbol_count=10, current_count=1, shard_metrics=metrics, now=30
        ), 2)

    def test_upstream_delay_does_not_expand_and_load_expansion_is_bounded(self):
        allocator = CvdShardAllocator()
        count = 1
        for now in range(0, 3600, 30):
            count = allocator.recommended_count(symbol_count=1, current_count=count,
                shard_metrics=[{"symbolCount": 1, "processingLagMs": 600}], now=now)
        self.assertEqual(count, 1)
        for now in range(3600, 10800, 30):
            count = allocator.recommended_count(symbol_count=1, current_count=count,
                shard_metrics=[{"symbolCount": 1, "messagesPerSecond": 700}], now=now)
        self.assertEqual(count, 1)
        count = 1
        for now in range(10800, 25200, 30):
            count = allocator.recommended_count(symbol_count=526, current_count=count,
                shard_metrics=[{"messagesPerSecond": 700}], now=now)
        self.assertEqual(count, 64)


class FakeConnection:
    def __init__(self, received=None):
        self.sent = []
        self.received = list(received or [])
        self.closed = False

    def send(self, message):
        self.sent.append(json.loads(message))

    def close(self):
        self.closed = True

    def recv(self):
        value = self.received.pop(0)
        return value(self) if callable(value) else value


class CvdStreamTests(unittest.TestCase):
    def test_open_but_silent_socket_expires_and_is_closed(self):
        clock = ManualClock()
        health = []
        connection = FakeConnection()
        def recv():
            clock.value += 1
            raise websocket.WebSocketTimeoutException()
        connection.recv = recv
        shard = BinanceCvdShard(0, lambda *_args: None,
            lambda *args: health.append(args), monotonic=clock,
            websocket_factory=lambda *_args, **_kwargs: connection)
        shard.update_symbols({"BTCUSDT"})
        shard._connect()
        with self.assertRaisesRegex(ConnectionError, "timed out"):
            shard._consume()
        shard._close_connection()
        self.assertTrue(connection.closed)
        self.assertFalse(health[-1][2])

    def test_subscriptions_are_batched_and_kline_fields_are_forwarded(self):
        connection = FakeConnection()
        updates = []
        health = []
        shard = BinanceCvdShard(
            0,
            lambda shard_id, symbol, values: updates.append(
                (shard_id, symbol, values)
            ),
            lambda *args: health.append(args),
            websocket_factory=lambda *_args, **_kwargs: connection,
            wall_time=lambda: 1.0,
        )
        symbols = {f"COIN{index}USDT" for index in range(205)}
        shard.update_symbols(symbols)

        shard._connect()
        self.assertEqual(health, [])
        for item in connection.sent:
            shard._handle_message(json.dumps({"result": None, "id": item["id"]}))
        shard._handle_message(json.dumps({
            "stream": "coin0usdt@kline_1m",
            "data": {
                "E": 900_001,
                "k": {
                    "s": "COIN0USDT",
                    "t": 900_000,
                    "q": "150",
                    "Q": "90",
                    "x": False,
                },
            },
        }))

        self.assertEqual([len(item["params"]) for item in connection.sent], [100, 100, 5])
        self.assertTrue(all(item["method"] == "SUBSCRIBE" for item in connection.sent))
        self.assertEqual(updates[0][0:2], (0, "COIN0USDT"))
        self.assertEqual(updates[0][2]["quote_volume"], "150")
        self.assertTrue(health[0][2])
        self.assertEqual(health[0][1], symbols)

    def test_dynamic_removal_sends_unsubscribe_without_reconnecting(self):
        connection = FakeConnection()
        shard = BinanceCvdShard(
            0,
            lambda *_args: None,
            lambda *_args: None,
            websocket_factory=lambda *_args, **_kwargs: connection,
        )
        shard.update_symbols({"BTCUSDT", "ETHUSDT"})
        shard._connect()
        shard.update_symbols({"BTCUSDT"})

        shard._sync_subscriptions()

        self.assertEqual(connection.sent[-1]["method"], "UNSUBSCRIBE")
        self.assertEqual(connection.sent[-1]["params"], ["ethusdt@kline_1m"])

    def test_subscription_rejection_forces_independent_reconnect(self):
        connection = FakeConnection()
        shard = BinanceCvdShard(
            0,
            lambda *_args: None,
            lambda *_args: None,
            websocket_factory=lambda *_args, **_kwargs: connection,
        )
        shard.update_symbols({"BTCUSDT"})
        shard._connect()

        with self.assertRaises(ConnectionError):
            shard._handle_message(json.dumps({
                "id": connection.sent[0]["id"],
                "code": 2,
                "msg": "Invalid request",
            }))

    def test_control_message_without_result_does_not_confirm_subscriptions(self):
        shard, connection = self.rotation_shard(FakeConnection(), {"BTCUSDT"})
        request_id = connection.sent[0]["id"]

        shard._handle_message(json.dumps({"id": request_id}))

        self.assertEqual(shard.confirmed_symbols(), set())
        self.assertIn(request_id, shard._pending_controls)

    def test_smooth_rotation_waits_for_ack_and_live_data(self):
        old_connection = FakeConnection()
        replacement = FakeConnection(received=[
            lambda connection: json.dumps({
                "result": None,
                "id": connection.sent[0]["id"],
            }),
            json.dumps({
                "stream": "btcusdt@kline_1m",
                "data": {
                    "E": 900_001,
                    "k": {
                        "s": "BTCUSDT",
                        "t": 900_000,
                        "q": "150",
                        "Q": "90",
                        "x": False,
                    },
                },
            }),
        ])
        connections = iter([old_connection, replacement])
        updates = []
        shard = BinanceCvdShard(
            0,
            lambda *args: updates.append(args),
            lambda *_args: None,
            websocket_factory=lambda *_args, **_kwargs: next(connections),
            wall_time=lambda: 1.0,
        )
        shard.update_symbols({"BTCUSDT"})
        shard._connect()

        shard._rotate_connection()

        self.assertTrue(old_connection.closed)
        self.assertFalse(replacement.closed)
        self.assertEqual(len(updates), 1)
        self.assertIs(shard._connection, replacement)

    def test_rotation_rejection_preserves_the_working_connection(self):
        replacement = FakeConnection(received=[
            lambda connection: json.dumps({
                "result": None,
                "id": connection.sent[0]["id"],
            }),
            lambda connection: json.dumps({
                "code": 2,
                "msg": "Invalid request",
                "id": connection.sent[1]["id"],
            }),
            json.dumps({"k": {
                "s": "BTCUSDT", "t": 900_000,
                "q": "150", "Q": "90", "x": False,
            }}),
        ])
        symbols = {"BTCUSDT"} | {f"COIN{index}USDT" for index in range(100)}
        shard, old_connection = self.rotation_shard(replacement, symbols)

        with self.assertRaisesRegex(ConnectionError, "subscription rejected"):
            shard._rotate_connection()

        self.assertFalse(old_connection.closed)
        self.assertTrue(replacement.closed)
        self.assertIs(shard._connection, old_connection)

    def test_rotation_requires_usable_data_from_a_subscribed_symbol(self):
        for kline in ({}, {
            "s": "ETHUSDT", "t": 900_000,
            "q": "150", "Q": "90", "x": False,
        }):
            with self.subTest(kline=kline):
                replacement = FakeConnection(received=[
                    lambda connection: json.dumps({
                        "result": None,
                        "id": connection.sent[0]["id"],
                    }),
                    json.dumps({"k": kline}),
                    None,
                ])
                shard, old_connection = self.rotation_shard(replacement, {"BTCUSDT"})

                with self.assertRaisesRegex(ConnectionError, "was not confirmed"):
                    shard._rotate_connection()

                self.assertFalse(old_connection.closed)
                self.assertTrue(replacement.closed)
                self.assertIs(shard._connection, old_connection)

    def test_rotation_requires_an_explicit_success_result(self):
        replacement = FakeConnection(received=[
            lambda connection: json.dumps({"id": connection.sent[0]["id"]}),
            json.dumps({"k": {
                "s": "BTCUSDT", "t": 900_000,
                "q": "150", "Q": "90", "x": False,
            }}),
            None,
        ])
        shard, old_connection = self.rotation_shard(replacement, {"BTCUSDT"})

        with self.assertRaisesRegex(ConnectionError, "was not confirmed"):
            shard._rotate_connection()

        self.assertFalse(old_connection.closed)
        self.assertTrue(replacement.closed)
        self.assertIs(shard._connection, old_connection)

    def test_stop_during_rotation_closes_the_replacement_without_waiting_for_data(self):
        replacement = FakeConnection()
        shard, old_connection = self.rotation_shard(replacement, {"BTCUSDT"})

        def stop_and_ack(connection):
            shard.request_stop()
            return json.dumps({"result": None, "id": connection.sent[0]["id"]})

        replacement.received.append(stop_and_ack)

        # Another recv would exhaust the fixture, reproducing the old loop
        # that kept waiting for live data after shutdown had been requested.
        shard._rotate_connection()

        self.assertTrue(old_connection.closed)
        self.assertTrue(replacement.closed)
        self.assertIsNone(shard._connection)

    def rotation_shard(self, replacement, symbols):
        old_connection = FakeConnection()
        connections = iter([old_connection, replacement])
        shard = BinanceCvdShard(
            0, lambda *_args: None, lambda *_args: None,
            websocket_factory=lambda *_args, **_kwargs: next(connections),
        )
        shard.update_symbols(symbols)
        shard._connect()
        self.addCleanup(shard.stop)
        return shard, old_connection


class SnapshotAndBackfillTests(unittest.TestCase):
    def test_oversized_snapshot_read_is_bounded_before_decoding(self):
        class RecordedStream(io.BytesIO):
            def __init__(self, data):
                super().__init__(data)
                self.read_sizes = []

            def read(self, size=-1):
                self.read_sizes.append(size)
                return super().read(size)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cvd.json"
            path.touch()
            repository = CvdSnapshotRepository(path)
            snapshot_file = RecordedStream(b"x" * 1024)
            with patch.object(Path, "open", return_value=snapshot_file), patch(
                "realtime_oi_dashboard.infrastructure.storage.cvd_snapshot.MAX_SNAPSHOT_BYTES",
                64,
            ):
                with self.assertRaisesRegex(ValueError, "too large"):
                    repository.load(now_ms=1_800_000)
            self.assertEqual(snapshot_file.read_sizes, [65])

    def test_snapshot_round_trip_prunes_expired_buckets(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = CvdSnapshotRepository(Path(directory) / "cvd.json")
            repository.save(saved_at=1_800_000, symbols={
                "BTCUSDT": [
                    {
                        "openTime": 0,
                        "quoteVolume": 10,
                        "takerBuyQuoteVolume": 5,
                        "closed": True,
                    },
                    {
                        "openTime": 1_740_000,
                        "quoteVolume": 100,
                        "takerBuyQuoteVolume": 60,
                        "closed": True,
                    },
                ]
            })

            records, saved_at = repository.load(now_ms=1_800_000)

            self.assertEqual(saved_at, 1_800_000)
            self.assertEqual([row["openTime"] for row in records["BTCUSDT"]], [1_740_000])

    def test_corrupt_snapshot_is_rejected_without_overwriting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cvd.json"
            path.write_text("not json", encoding="utf-8")
            repository = CvdSnapshotRepository(path)

            with self.assertRaises(json.JSONDecodeError):
                repository.load(now_ms=1_200_000)
            self.assertEqual(path.read_text(encoding="utf-8"), "not json")

    def test_snapshot_rejects_non_finite_volumes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cvd.json"
            path.write_text(json.dumps({
                "version": 1,
                "savedAt": 1_800_000,
                "symbols": {
                    "BTCUSDT": [{
                        "openTime": 1_740_000,
                        "quoteVolume": float("inf"),
                        "takerBuyQuoteVolume": 1,
                        "closed": True,
                    }],
                },
            }), encoding="utf-8")

            records, _ = CvdSnapshotRepository(path).load(now_ms=1_800_000)

            self.assertEqual(records, {})

    def test_backfill_queue_deduplicates_one_symbol(self):
        started = threading.Event()
        release = threading.Event()
        calls = []
        applied = []

        def load(symbol):
            calls.append(symbol)
            started.set()
            release.wait(timeout=2)
            return [[1]]

        queue = CvdBackfillQueue(
            load,
            lambda symbol, rows: applied.append((symbol, rows)),
            requests_per_second=1000,
            workers=2,
        )
        queue.enqueue("BTCUSDT")
        queue.start()
        self.assertTrue(started.wait(timeout=2))
        self.assertFalse(queue.enqueue("BTCUSDT"))
        release.set()
        for _ in range(20):
            if applied:
                break
            time.sleep(0.01)
        queue.stop()

        self.assertEqual(calls, ["BTCUSDT"])
        self.assertEqual(len(applied), 1)

    def test_http_418_blocks_remaining_backfill_requests(self):
        class Response:
            status_code = 418
            headers = {}

        class BannedError(Exception):
            response = Response()

        calls = []

        def load(symbol):
            calls.append(symbol)
            raise BannedError("IP banned")

        queue = CvdBackfillQueue(
            load,
            lambda *_args: None,
            requests_per_second=1000,
            workers=1,
        )
        queue.enqueue("BTCUSDT")
        queue.enqueue("ETHUSDT")
        queue.start()
        for _ in range(100):
            if queue.last_error:
                break
            time.sleep(0.01)
        queue.stop()

        self.assertEqual(calls, ["BTCUSDT"])

    def test_backfill_resumes_after_ban_without_losing_pending_symbols(self):
        class Response:
            status_code = 418
            headers = {"Retry-After": "180"}

        class BannedError(Exception):
            response = Response()

        clock = [0.0]
        calls, applied = [], []

        def load(symbol):
            calls.append(symbol)
            if len(calls) == 1:
                raise BannedError("IP banned")
            return [[1]]

        queue = CvdBackfillQueue(
            load, lambda symbol, rows: applied.append(symbol),
            workers=1, requests_per_second=1000, monotonic=lambda: clock[0],
        )
        queue.enqueue("BTCUSDT")
        queue.enqueue("ETHUSDT")
        queue.start()
        try:
            for _ in range(100):
                if queue.last_error:
                    break
                time.sleep(0.01)
            self.assertTrue(queue.enqueue("SOLUSDT"))
            self.assertEqual(queue._blocked_until, 180)
            self.assertEqual(calls, ["BTCUSDT"])
            clock[0] = 181
            with queue._condition:
                queue._condition.notify_all()
            for _ in range(100):
                if len(applied) == 3:
                    break
                time.sleep(0.01)
            self.assertCountEqual(applied, ["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        finally:
            queue.stop()

    def test_preflight_cooldown_keeps_queue_and_symbol_retry_budget(self):
        clock = ManualClock()
        calls, applied = [], []

        def load(symbol):
            calls.append(symbol)
            if len(calls) == 1:
                raise BinanceCooldownError(45, status_code=429, monotonic=clock)
            return [[1]]

        queue = CvdBackfillQueue(
            load, lambda symbol, _rows: applied.append(symbol),
            workers=1, requests_per_second=1000, monotonic=clock,
        )
        queue.enqueue("BTCUSDT")
        queue.enqueue("ETHUSDT")
        queue.start()
        try:
            for _ in range(100):
                with queue._condition:
                    pending = list(queue._pending)
                    blocked_until = queue._blocked_until
                if blocked_until == 45 and ("BTCUSDT", 0) in pending:
                    break
                time.sleep(0.01)
            self.assertEqual(calls, ["BTCUSDT"])
            self.assertIn(("BTCUSDT", 0), pending)
            self.assertEqual(queue._blocked_until, 45)
            clock.value = 46
            with queue._condition:
                queue._condition.notify_all()
            for _ in range(100):
                if len(applied) == 2:
                    break
                time.sleep(0.01)
            self.assertCountEqual(applied, ["BTCUSDT", "ETHUSDT"])
        finally:
            queue.stop()


class BinanceWeightBudgetTests(unittest.TestCase):
    def test_assigns_endpoint_weights_only_to_binance_futures(self):
        self.assertEqual(request_weight("https://fapi.binance.com/fapi/v1/ticker/24hr"), 40)
        self.assertEqual(request_weight("https://fapi.binance.com/fapi/v1/klines"), 5)
        self.assertEqual(request_weight("https://api.coingecko.com/api/v3/coins"), 0)

    def test_budget_waits_until_tokens_refill(self):
        clock = ManualClock()

        def sleep(seconds):
            clock.value += seconds

        budget = BinanceWeightBudget(
            weight_per_minute=40,
            monotonic=clock,
            sleep=sleep,
        )
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        budget.acquire(url)
        budget.acquire(url)

        self.assertAlmostEqual(clock.value, 60)


if __name__ == "__main__":
    unittest.main()
