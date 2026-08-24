import threading
import unittest
from unittest.mock import patch

from realtime_oi_dashboard.application.oi.symbol_refresher import SymbolRefresher
from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.domain.oi.history_points import MAX_SAFE_INTEGER
from realtime_oi_dashboard.infrastructure.binance.futures_client import (
    BinanceFuturesClient,
)
from realtime_oi_dashboard.infrastructure.binance.rest_cache import (
    EXCHANGE_INFO_URL,
    TICKER_URL,
    BinanceRestCache,
)


OPEN_INTEREST_URL = "https://fapi.binance.com/fapi/v1/openInterest"


def ticker_payload():
    return [
        {
            "symbol": "BTCUSDT",
            "lastPrice": "100",
            "quoteVolume": "10000",
            "priceChangePercent": "2.5",
        }
    ] + [
        {
            "symbol": f"TEST{index}USDT",
            "lastPrice": "1",
            "quoteVolume": "100",
            "priceChangePercent": "0",
        }
        for index in range(19)
    ]


def exchange_info_payload(count=20):
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT" if index == 0 else f"INFO{index}USDT",
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
                "underlyingType": "COIN",
                "status": "TRADING",
            }
            for index in range(count)
        ]
    }


class ManualClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class FakeHttpClient:
    def __init__(self):
        self.tickers = ticker_payload()
        self.exchange_info = exchange_info_payload()
        self.open_interest = {
            "symbol": "BTCUSDT",
            "openInterest": "123.45",
            "time": 1_700_000_123_456,
        }
        self.calls = []
        self.error = None
        self.request_started = None
        self.release_request = None

    def get_json(self, url, **_kwargs):
        self.calls.append(url)
        if self.request_started is not None:
            self.request_started.set()
            self.release_request.wait(timeout=2)
        if self.error is not None:
            raise self.error
        if url == TICKER_URL:
            return self.tickers
        if url == EXCHANGE_INFO_URL:
            return self.exchange_info
        if url == OPEN_INTEREST_URL:
            return self.open_interest
        raise AssertionError(f"unexpected URL: {url}")


class BinanceRestCacheTests(unittest.TestCase):
    def create_cache(self, *, clock=None, client=None):
        clock = clock or ManualClock()
        client = client or FakeHttpClient()
        cache = BinanceRestCache(
            http_client=client,
            exchange_info_cache_seconds=900,
            ticker_stale_grace_seconds=30,
            exchange_info_stale_grace_seconds=60,
            monotonic=clock,
        )
        return cache, client, clock

    def test_reuses_each_resource_during_its_cache_window(self):
        cache, client, _ = self.create_cache()

        first_tickers = cache.get_tickers()
        second_tickers = cache.get_tickers()
        first_info = cache.get_exchange_info()
        second_info = cache.get_exchange_info()

        self.assertIs(first_tickers, second_tickers)
        self.assertIs(first_info, second_info)
        self.assertEqual(client.calls.count(TICKER_URL), 1)
        self.assertEqual(client.calls.count(EXCHANGE_INFO_URL), 1)

    def test_concurrent_misses_share_one_refresh(self):
        client = FakeHttpClient()
        client.request_started = threading.Event()
        client.release_request = threading.Event()
        cache, _, _ = self.create_cache(client=client)
        results = []
        errors = []

        def load():
            try:
                results.append(cache.get_tickers())
            except BaseException as exc:
                errors.append(exc)

        workers = [threading.Thread(target=load) for _ in range(3)]
        workers[0].start()
        self.assertTrue(client.request_started.wait(timeout=2))
        workers[1].start()
        workers[2].start()
        client.release_request.set()
        for worker in workers:
            worker.join(timeout=2)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 3)
        self.assertTrue(all(result is results[0] for result in results))
        self.assertEqual(client.calls, [TICKER_URL])

    def test_refresh_failure_returns_stale_value_and_throttles_retry(self):
        cache, client, clock = self.create_cache()
        cached = cache.get_tickers()
        clock.value = 10
        client.error = ConnectionError("temporary failure")

        fallback = cache.get_tickers()
        clock.value = 19.999
        throttled = cache.get_tickers()

        self.assertIs(fallback, cached)
        self.assertIs(throttled, cached)
        self.assertEqual(client.calls.count(TICKER_URL), 2)

        clock.value = 40
        with self.assertRaisesRegex(ConnectionError, "temporary failure"):
            cache.get_tickers()

    def test_large_ticker_universe_shrink_keeps_last_good_response(self):
        cache, client, clock = self.create_cache()
        cached = cache.get_tickers()
        client.tickers = ticker_payload()[:10]
        clock.value = 10

        fallback = cache.get_tickers()

        self.assertIs(fallback, cached)
        self.assertEqual(len(fallback), 20)
        self.assertEqual(client.calls.count(TICKER_URL), 2)

    def test_invalid_ticker_prices_do_not_count_toward_response_size(self):
        cache, client, clock = self.create_cache()
        cached = cache.get_tickers()
        client.tickers = ticker_payload()
        for item in client.tickers[:10]:
            item["lastPrice"] = "invalid"
        clock.value = 10

        fallback = cache.get_tickers()

        self.assertIs(fallback, cached)
        self.assertEqual(len(fallback), 20)
        self.assertEqual(client.calls.count(TICKER_URL), 2)

    def test_duplicate_ticker_symbol_keeps_last_good_response(self):
        cache, client, clock = self.create_cache()
        cached = cache.get_tickers()
        client.tickers = ticker_payload() + [{
            "symbol": "BTCUSDT",
            "lastPrice": "999",
        }]
        clock.value = 10

        fallback = cache.get_tickers()

        self.assertIs(fallback, cached)
        self.assertEqual(client.calls.count(TICKER_URL), 2)

    def test_direct_ticker_parser_rejects_duplicate_symbols(self):
        stop_event = threading.Event()
        http_client = FakeHttpClient()
        http_client.tickers.append({
            "symbol": "BTCUSDT",
            "lastPrice": "999",
        })
        oi_client = BinanceFuturesClient(
            stop_event,
            lambda *_args: None,
            funding_cache_seconds=3600,
            http_client=http_client,
        )

        with self.assertRaisesRegex(ValueError, "duplicate ticker symbol"):
            oi_client.get_market_tickers({"BTCUSDT"})

    def test_non_ascii_or_lowercase_symbols_do_not_satisfy_response_size(self):
        cache, client, _ = self.create_cache()
        client.tickers = [
            {
                "symbol": f"币{index}USDT",
                "lastPrice": "1",
            }
            for index in range(20)
        ]
        client.exchange_info = {
            "symbols": [
                {
                    "symbol": f"coin{index}USDT",
                    "quoteAsset": "USDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                }
                for index in range(20)
            ]
        }

        with self.assertRaisesRegex(ValueError, "ticker response"):
            cache.get_tickers()
        with self.assertRaisesRegex(ValueError, "exchange-info response"):
            cache.get_exchange_info()

    def test_undersized_exchange_info_is_retried_instead_of_cached(self):
        cache, client, clock = self.create_cache()
        client.exchange_info = exchange_info_payload(1)

        with self.assertRaisesRegex(ValueError, "exchange-info response"):
            cache.get_exchange_info()
        clock.value = 59.999
        with self.assertRaisesRegex(ValueError, "exchange-info response"):
            cache.get_exchange_info()

        client.exchange_info = exchange_info_payload(20)
        clock.value = 60
        refreshed = cache.get_exchange_info()

        self.assertEqual(len(refreshed["symbols"]), 20)
        self.assertEqual(client.calls.count(EXCHANGE_INFO_URL), 2)

    def test_exchange_info_uses_its_longer_stale_fallback_window(self):
        cache, client, clock = self.create_cache()
        cached = cache.get_exchange_info()
        clock.value = 900
        client.error = ConnectionError("temporary failure")

        fallback = cache.get_exchange_info()
        clock.value = 959.999
        throttled = cache.get_exchange_info()

        self.assertIs(fallback, cached)
        self.assertIs(throttled, cached)
        self.assertEqual(client.calls.count(EXCHANGE_INFO_URL), 2)

    def test_large_symbol_removal_confirmation_forces_a_second_request(self):
        cache, client, clock = self.create_cache()
        client.exchange_info = exchange_info_payload(30)
        stop_event = threading.Event()
        oi_client = BinanceFuturesClient(
            stop_event,
            lambda *_args: None,
            funding_cache_seconds=3600,
            http_client=FakeHttpClient(),
            shared_rest_cache=cache,
        )
        errors = []
        refresher = SymbolRefresher(
            oi_client.get_active_symbols,
            lambda symbol, error: errors.append((symbol, str(error))),
            stop_event,
            threading.RLock(),
            refresh_interval=900,
            monotonic=clock,
        )
        refresher.refresh_if_due(lambda _refresh: None)

        client.exchange_info = exchange_info_payload(20)
        clock.value = 900
        first_confirmation = refresher.refresh_if_due(lambda _refresh: None)
        clock.value = refresher.retry_at
        second_confirmation = refresher.refresh_if_due(lambda _refresh: None)

        self.assertFalse(first_confirmation)
        self.assertTrue(second_confirmation)
        self.assertEqual(len(refresher.symbols), 20)
        self.assertEqual(client.calls.count(EXCHANGE_INFO_URL), 3)
        self.assertEqual(len(errors), 1)

    def test_failed_forced_refresh_does_not_confirm_large_symbol_removal(self):
        cache, client, clock = self.create_cache()
        client.exchange_info = exchange_info_payload(30)
        stop_event = threading.Event()
        oi_client = BinanceFuturesClient(
            stop_event,
            lambda *_args: None,
            funding_cache_seconds=3600,
            http_client=FakeHttpClient(),
            shared_rest_cache=cache,
        )
        errors = []
        refresher = SymbolRefresher(
            oi_client.get_active_symbols,
            lambda symbol, error: errors.append((symbol, str(error))),
            stop_event,
            threading.RLock(),
            refresh_interval=900,
            monotonic=clock,
        )
        refresher.refresh_if_due(lambda _refresh: None)

        client.exchange_info = exchange_info_payload(20)
        clock.value = 900
        first_confirmation = refresher.refresh_if_due(lambda _refresh: None)

        client.error = ConnectionError("confirmation request failed")
        clock.value = refresher.retry_at
        failed_confirmation = refresher.refresh_if_due(lambda _refresh: None)

        self.assertFalse(first_confirmation)
        self.assertFalse(failed_confirmation)
        self.assertEqual(len(refresher.symbols), 30)
        self.assertEqual(client.calls.count(EXCHANGE_INFO_URL), 3)
        self.assertEqual(len(errors), 2)

        client.error = None
        clock.value = refresher.retry_at
        confirmed = refresher.refresh_if_due(lambda _refresh: None)

        self.assertTrue(confirmed)
        self.assertEqual(len(refresher.symbols), 20)
        self.assertEqual(client.calls.count(EXCHANGE_INFO_URL), 4)

    def test_concurrent_failed_misses_share_one_request_error(self):
        client = FakeHttpClient()
        client.error = ConnectionError("temporary failure")
        client.request_started = threading.Event()
        client.release_request = threading.Event()
        cache, _, _ = self.create_cache(client=client)
        errors = []

        def load():
            try:
                cache.get_tickers()
            except BaseException as exc:
                errors.append(exc)

        workers = [threading.Thread(target=load) for _ in range(3)]
        workers[0].start()
        self.assertTrue(client.request_started.wait(timeout=2))
        workers[1].start()
        workers[2].start()
        client.release_request.set()
        for worker in workers:
            worker.join(timeout=2)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(len(errors), 3)
        self.assertTrue(all(error is errors[0] for error in errors))
        self.assertEqual(client.calls, [TICKER_URL])

    def test_oi_client_uses_the_shared_cached_responses(self):
        cache, client, _ = self.create_cache()
        stop_event = threading.Event()
        direct_http = FakeHttpClient()
        direct_http.error = AssertionError("direct shared request was not expected")
        errors = []
        oi_client = BinanceFuturesClient(
            stop_event,
            lambda symbol, error: errors.append((symbol, error)),
            funding_cache_seconds=3600,
            http_client=direct_http,
            shared_rest_cache=cache,
        )
        oi_client.get_market_tickers({"BTCUSDT"})
        oi_client.get_active_symbols()

        self.assertEqual(client.calls.count(TICKER_URL), 1)
        self.assertEqual(client.calls.count(EXCHANGE_INFO_URL), 1)
        self.assertEqual(errors, [])

    def test_current_oi_preserves_binance_transaction_time(self):
        stop_event = threading.Event()
        http_client = FakeHttpClient()
        oi_client = BinanceFuturesClient(
            stop_event,
            lambda *_args: None,
            funding_cache_seconds=3600,
            http_client=http_client,
        )

        with patch(
            "realtime_oi_dashboard.infrastructure.binance.futures_client."
            "time.time",
            return_value=1_700_000_123.456,
        ):
            snapshot = oi_client.get_open_interest("BTCUSDT")

        self.assertEqual(snapshot.value, 123.45)
        self.assertEqual(snapshot.timestamp_ms, 1_700_000_123_456)

    def test_current_oi_rejects_response_without_binance_time(self):
        stop_event = threading.Event()
        http_client = FakeHttpClient()
        http_client.open_interest = {
            "symbol": "BTCUSDT",
            "openInterest": "123.45",
        }
        oi_client = BinanceFuturesClient(
            stop_event,
            lambda *_args: None,
            funding_cache_seconds=3600,
            http_client=http_client,
        )

        with self.assertRaisesRegex(ValueError, "open-interest response"):
            oi_client.get_open_interest("BTCUSDT")

    def test_current_oi_rejects_timestamp_outside_freshness_window(self):
        now_ms = 1_700_000_123_456
        invalid_timestamps = (
            now_ms - 15 * 60 * 1_000 - 1,
            now_ms + 60 * 1_000 + 1,
        )

        for timestamp_ms in invalid_timestamps:
            with self.subTest(timestamp_ms=timestamp_ms):
                stop_event = threading.Event()
                http_client = FakeHttpClient()
                http_client.open_interest["time"] = timestamp_ms
                oi_client = BinanceFuturesClient(
                    stop_event,
                    lambda *_args: None,
                    funding_cache_seconds=3600,
                    http_client=http_client,
                )

                with patch(
                    "realtime_oi_dashboard.infrastructure.binance."
                    "futures_client.time.time",
                    return_value=now_ms / 1_000,
                ), self.assertRaisesRegex(
                    ValueError,
                    "open-interest response",
                ):
                    oi_client.get_open_interest("BTCUSDT")

    def test_current_oi_rejects_response_for_another_symbol(self):
        stop_event = threading.Event()
        http_client = FakeHttpClient()
        http_client.open_interest["symbol"] = "ETHUSDT"
        oi_client = BinanceFuturesClient(
            stop_event,
            lambda *_args: None,
            funding_cache_seconds=3600,
            http_client=http_client,
        )

        with self.assertRaisesRegex(ValueError, "open-interest response"):
            oi_client.get_open_interest("BTCUSDT")

    def test_current_oi_rejects_timestamp_above_javascript_safe_integer(self):
        stop_event = threading.Event()
        http_client = FakeHttpClient()
        http_client.open_interest["time"] = MAX_SAFE_INTEGER + 1
        oi_client = BinanceFuturesClient(
            stop_event,
            lambda *_args: None,
            funding_cache_seconds=3600,
            http_client=http_client,
        )

        with self.assertRaisesRegex(ValueError, "open-interest response"):
            oi_client.get_open_interest("BTCUSDT")

    def test_oi_observes_shared_ticker_refresh_without_a_second_ttl(self):
        cache, client, clock = self.create_cache()
        cache.get_tickers()
        stop_event = threading.Event()
        oi_client = BinanceFuturesClient(
            stop_event,
            lambda *_args: None,
            funding_cache_seconds=3600,
            http_client=FakeHttpClient(),
            shared_rest_cache=cache,
        )

        clock.value = 9
        first = oi_client.get_market_tickers({"BTCUSDT"})
        client.tickers = ticker_payload()
        client.tickers[0]["lastPrice"] = "200"
        clock.value = 10
        refreshed = oi_client.get_market_tickers({"BTCUSDT"})

        self.assertEqual(first["BTCUSDT"]["price"], 100)
        self.assertEqual(refreshed["BTCUSDT"]["price"], 200)
        self.assertEqual(client.calls.count(TICKER_URL), 2)

    def test_stop_prevents_new_shared_requests(self):
        cache, client, _ = self.create_cache()
        cache.stop()

        with self.assertRaises(PollingStopped):
            cache.get_tickers()

        self.assertEqual(client.calls, [])

if __name__ == "__main__":
    unittest.main()
