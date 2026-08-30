import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from realtime_oi_dashboard.application.cvd.poller import CvdPoller
from realtime_oi_dashboard.domain.cvd.model import MINUTE_MS


def exchange_info(count):
    return {
        "symbols": [
            {
                "symbol": f"COIN{index}USDT",
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
                "status": "TRADING",
            }
            for index in range(count)
        ]
    }


class FakeSharedCache:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get_exchange_info(self):
        self.calls += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeHttpClient:
    def __init__(self, klines=None):
        self.klines = klines or []
        self.calls = []
        self.closed = False

    def get_json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.klines

    def close(self):
        self.closed = True


class FakeShard:
    def __init__(self, shard_id):
        self.shard_id = shard_id
        self.symbols = set()
        self.started = False
        self.stopped = False
        self.connected = True
        self.confirmed = True

    def start(self):
        self.started = True

    def stop(self, **_kwargs):
        self.stopped = True

    def update_symbols(self, symbols):
        self.symbols = set(symbols)

    def metrics(self):
        return {
            "shardId": self.shard_id,
            "symbolCount": len(self.symbols),
            "connected": self.connected,
            "confirmedSymbols": len(self.symbols),
            "messagesPerSecond": 0.0,
            "processingLagMs": 0.0,
            "queueDepth": 0,
            "symbolRates": {},
        }

    def confirmed_symbols(self):
        return set(self.symbols) if self.connected and self.confirmed else set()


class CvdPollerTests(unittest.TestCase):
    def create_poller(self, count=1, *, now_ms=None, klines=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        shards = {}

        def shard_factory(shard_id):
            shard = FakeShard(shard_id)
            shards[shard_id] = shard
            return shard

        cache = FakeSharedCache(exchange_info(count))
        client = FakeHttpClient(klines)
        poller = CvdPoller(
            shared_rest_cache=cache,
            http_client=client,
            shard_factory=shard_factory,
            now_ms=now_ms or (lambda: 16 * MINUTE_MS),
            snapshot_path=Path(directory.name) / "cvd.json",
        )
        return poller, cache, client, shards

    def test_discovers_all_symbols_without_ticker_or_top_n_limit(self):
        poller, cache, client, shards = self.create_poller(526)

        change = poller.refresh_universe(force=True)

        self.assertEqual(len(change.symbols), 526)
        self.assertEqual(len(shards), 4)
        self.assertTrue(all(len(shard.symbols) <= 150 for shard in shards.values()))
        self.assertEqual(cache.calls, 1)
        self.assertEqual(client.calls, [])

    def test_new_symbol_is_added_on_next_universe_refresh(self):
        poller, cache, _, shards = self.create_poller(1)
        poller.refresh_universe(force=True)
        cache.payload = exchange_info(2)

        change = poller.refresh_universe(force=True)

        self.assertEqual(change.added, {"COIN1USDT"})
        self.assertEqual(set().union(*(shard.symbols for shard in shards.values())), set(change.symbols))

    def test_scale_out_keeps_old_subscription_until_new_shard_has_data(self):
        poller, cache, _, shards = self.create_poller(150)
        poller.refresh_universe(force=True)
        cache.payload = exchange_info(151)

        poller.refresh_universe(force=True)
        symbol, (old_shard, new_shard) = next(iter(poller._pending_migrations.items()))

        self.assertIn(symbol, shards[old_shard].symbols)
        self.assertIn(symbol, shards[new_shard].symbols)
        poller._handle_kline(new_shard, symbol, {
            "open_time": 16 * MINUTE_MS,
            "quote_volume": 0,
            "taker_buy_quote_volume": 0,
            "closed": False,
            "source": "wss",
            "updated_at": 16 * MINUTE_MS + 1,
        })
        self.assertNotIn(symbol, shards[old_shard].symbols)
        self.assertIn(symbol, shards[new_shard].symbols)

    def test_universe_failure_keeps_existing_assignments(self):
        poller, cache, _, shards = self.create_poller(2)
        poller.refresh_universe(force=True)
        original = {key: set(shard.symbols) for key, shard in shards.items()}
        cache.payload = ConnectionError("exchange unavailable")

        change = poller.refresh_universe(force=True)

        self.assertFalse(change.changed)
        self.assertEqual(
            {key: set(shard.symbols) for key, shard in shards.items()},
            original,
        )

    def test_supervisor_reconciles_each_universe_change_once(self):
        poller, cache, _, _ = self.create_poller(1)
        poller.backfill.start = Mock()
        poller.backfill.stop = Mock()
        poller.snapshots.restore = Mock()
        poller.snapshots.save = Mock()
        poller.snapshots.save_if_due = Mock()
        poller.store.publish = Mock()
        poller._fill_silent_minutes = Mock()
        poller._scale_if_needed = Mock()
        poller._enqueue_backfill_if_missing = Mock(return_value=True)
        original_reconcile = poller._reconcile_shards
        poller._reconcile_shards = Mock(wraps=original_reconcile)
        wait_calls = 0

        def wait(_timeout):
            nonlocal wait_calls
            wait_calls += 1
            if wait_calls == 1:
                cache.payload = exchange_info(2)
                poller.universe._next_refresh_at = 0
                return False
            return True

        poller.stop_event.wait = wait

        poller.run_forever()

        self.assertEqual(poller._reconcile_shards.call_count, 2)
        self.assertEqual(poller.store.active_symbols(), {"COIN0USDT", "COIN1USDT"})

    def test_kline_update_publishes_new_and_legacy_fields(self):
        poller, _, _, _ = self.create_poller(1)
        poller.refresh_universe(force=True)
        poller._handle_shard_health(0, {"COIN0USDT"}, True, None)
        poller._handle_kline(0, "COIN0USDT", {
            "open_time": 16 * MINUTE_MS,
            "quote_volume": 100,
            "taker_buy_quote_volume": 75,
            "closed": False,
            "source": "wss",
            "updated_at": 16 * MINUTE_MS + 1,
        })
        poller.store.publish(now_ms=16 * MINUTE_MS + 1)

        row = poller.get_state()["rows"]["COIN0USDT"]

        self.assertEqual(row["cvd15m"], 50)
        self.assertEqual(row["cvdDirection"], "buying")
        self.assertEqual(row["cvdHealth"], "warming")
        self.assertEqual(row["cvdStatus"], "collecting")

    def test_silent_zero_buckets_wait_for_subscription_confirmation(self):
        poller, _, _, shards = self.create_poller(1)
        poller.refresh_universe(force=True)
        shards[0].confirmed = False

        poller._fill_silent_minutes()
        poller.store.publish(now_ms=16 * MINUTE_MS)

        row = poller.get_state()["rows"]["COIN0USDT"]
        self.assertEqual(row["cvdHealth"], "unavailable")
        self.assertIsNone(row["cvd15m"])

    def test_one_shard_disconnect_does_not_clear_other_rows(self):
        poller, _, _, shards = self.create_poller(151)
        poller.refresh_universe(force=True)
        symbols = sorted(poller.store.active_symbols())
        first = next(iter(shards[0].symbols))
        second = next(iter(shards[1].symbols))
        for shard_id, symbol in ((0, first), (1, second)):
            poller._handle_shard_health(shard_id, {symbol}, True, None)
            poller._handle_kline(shard_id, symbol, {
                "open_time": 16 * MINUTE_MS,
                "quote_volume": 100,
                "taker_buy_quote_volume": 75,
                "closed": False,
                "source": "wss",
                "updated_at": 16 * MINUTE_MS + 1,
            })
        poller._handle_shard_health(0, {first}, False, "disconnected")
        poller.store.publish(now_ms=16 * MINUTE_MS + 1)

        rows = poller.get_state()["rows"]
        self.assertEqual(rows[first]["cvdHealth"], "stale")
        self.assertEqual(rows[second]["cvdHealth"], "warming")
        self.assertEqual(rows[second]["cvd15m"], 50)

    def test_rest_backfill_merges_minute_klines(self):
        klines = [
            [minute * MINUTE_MS, 0, 0, 0, 0, 0, (minute + 1) * MINUTE_MS - 1, "100", 0, 0, "60"]
            for minute in range(1, 17)
        ]
        poller, _, _, _ = self.create_poller(1, klines=klines)
        poller.refresh_universe(force=True)

        poller._apply_backfill("COIN0USDT", klines)
        poller.store.set_connected({"COIN0USDT"}, True)
        poller.store.publish(now_ms=16 * MINUTE_MS)

        row = poller.get_state()["rows"]["COIN0USDT"]
        self.assertEqual(row["cvd15m"], 300)
        self.assertEqual(row["cvdHealth"], "live")

    def test_complete_snapshot_history_does_not_enqueue_rest_backfill(self):
        klines = [
            [minute * MINUTE_MS, 0, 0, 0, 0, 0, (minute + 1) * MINUTE_MS - 1, "100", 0, 0, "60"]
            for minute in range(2, 16)
        ]
        poller, _, _, _ = self.create_poller(1)
        poller.refresh_universe(force=True)
        poller._apply_backfill("COIN0USDT", klines)

        queued = poller._enqueue_backfill_if_missing("COIN0USDT")

        self.assertFalse(queued)
        self.assertEqual(poller.backfill.queue_size, 0)

    def test_close_finishes_cleanup_and_can_retry_after_a_shard_stop_failure(self):
        poller, _, client, _ = self.create_poller(1)

        class FlakyShard(FakeShard):
            def __init__(self, shard_id):
                super().__init__(shard_id)
                self.stop_attempts = 0

            def stop(self, **_kwargs):
                self.stop_attempts += 1
                if self.stop_attempts == 1:
                    raise RuntimeError("shard stop failed")
                super().stop()

        flaky = FlakyShard(0)
        healthy = FakeShard(1)
        poller._shards = {0: flaky, 1: healthy}
        poller.backfill.stop = Mock()
        poller.store.publish = Mock()
        poller.snapshots.save = Mock()

        with self.assertRaisesRegex(RuntimeError, "shard stop failed"):
            poller.close()

        self.assertTrue(healthy.stopped)
        poller.backfill.stop.assert_called_once_with()
        poller.store.publish.assert_called_once_with(now_ms=16 * MINUTE_MS)
        poller.snapshots.save.assert_called_once_with(force=True)
        self.assertFalse(poller._closed)
        self.assertFalse(client.closed)

        poller.close()

        self.assertTrue(flaky.stopped)
        self.assertTrue(poller._closed)
        self.assertEqual(poller.backfill.stop.call_count, 2)


if __name__ == "__main__":
    unittest.main()
