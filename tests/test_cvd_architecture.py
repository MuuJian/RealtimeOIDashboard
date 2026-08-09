import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

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


class SnapshotAndBackfillTests(unittest.TestCase):
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


class BinanceWeightBudgetTests(unittest.TestCase):
    def test_assigns_endpoint_weights_only_to_binance_futures(self):
        self.assertEqual(request_weight("https://fapi.binance.com/fapi/v1/ticker/24hr"), 40)
        self.assertEqual(request_weight("https://fapi.binance.com/fapi/v1/klines"), 1)
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
