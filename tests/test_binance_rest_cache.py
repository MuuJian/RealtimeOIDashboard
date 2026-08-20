import threading
import unittest

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.infrastructure.binance.futures_client import (
    BinanceFuturesClient,
)
from realtime_oi_dashboard.infrastructure.binance.rest_cache import (
    EXCHANGE_INFO_URL,
    TICKER_URL,
    BinanceRestCache,
)


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


def exchange_info_payload():
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
                "underlyingType": "COIN",
                "status": "TRADING",
            }
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
