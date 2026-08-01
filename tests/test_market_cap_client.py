import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from realtime_oi_dashboard.errors import PollingStopped
from realtime_oi_dashboard.market_cap_client import CoinGeckoMarketCapClient
from realtime_oi_dashboard.market_cap_store import (
    load_market_cap_file,
    write_market_cap_file,
)


class CoinGeckoMarketCapClientTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "market_caps.json"
        self.errors = []
        self.progress = []
        self.waits = []

    def client(self, responses):
        pending = list(responses)

        def request_json(*_args, **_kwargs):
            response = pending.pop(0)
            if isinstance(response, BaseException):
                raise response
            return response

        return CoinGeckoMarketCapClient(
            request_json,
            self.waits.append,
            lambda key, error: self.errors.append((key, str(error))),
            cache_seconds=3_600,
            store_path=self.path,
            record_progress=self.progress.append,
        )

    def test_get_reads_json_without_network_request(self):
        write_market_cap_file(
            self.path,
            {"BTCUSDT": {"marketCap": 1_000.0, "updatedAt": 10.0}},
            saved_at=10.0,
        )
        client = self.client([])

        self.assertEqual(
            client.get({"BTCUSDT", "ETHUSDT"}),
            {"BTCUSDT": {"marketCap": 1_000.0}},
        )
        self.assertEqual(client.count({"BTCUSDT", "ETHUSDT"}), 1)

    def test_successful_page_merges_without_clearing_old_values(self):
        write_market_cap_file(
            self.path,
            {"BTCUSDT": {"marketCap": 1_000.0, "updatedAt": 10.0}},
            saved_at=10.0,
        )
        client = self.client(
            [[{"symbol": "eth", "market_cap": 500.0}]]
        )

        with patch(
            "realtime_oi_dashboard.market_cap_client.time.time",
            return_value=20.0,
        ):
            updated = client.refresh_page(2, {"BTCUSDT", "ETHUSDT"})

        self.assertEqual(updated, 1)
        self.assertEqual(
            client.get({"BTCUSDT", "ETHUSDT"}),
            {
                "BTCUSDT": {"marketCap": 1_000.0},
                "ETHUSDT": {"marketCap": 500.0},
            },
        )
        self.assertEqual(
            load_market_cap_file(self.path)["ETHUSDT"],
            {"marketCap": 500.0, "updatedAt": 20.0},
        )

    def test_page_uses_fdv_when_market_cap_is_unavailable(self):
        client = self.client(
            [[{
                "id": "abc-token",
                "symbol": "abc",
                "market_cap": None,
                "fully_diluted_valuation": 750.0,
            }]]
        )

        updated = client.refresh_page(8, {"ABCUSDT"})

        self.assertEqual(updated, 1)
        self.assertEqual(
            client.get({"ABCUSDT"}),
            {"ABCUSDT": {"marketCap": 750.0}},
        )
        self.assertEqual(
            load_market_cap_file(self.path)["ABCUSDT"]["coingeckoId"],
            "abc-token",
        )

    def test_rate_limit_retries_same_page_and_preserves_json(self):
        write_market_cap_file(
            self.path,
            {"BTCUSDT": {"marketCap": 1_000.0, "updatedAt": 10.0}},
            saved_at=10.0,
        )
        client = self.client(
            [
                RuntimeError("429 first"),
                RuntimeError("429 second"),
                [{"symbol": "eth", "market_cap": 500.0}],
            ]
        )

        refreshed = client._refresh_page_with_retries(
            5,
            {"BTCUSDT", "ETHUSDT"},
        )

        self.assertEqual(refreshed, 1)
        self.assertEqual(self.waits, [60, 120])
        self.assertEqual(len(self.errors), 2)
        self.assertEqual(
            client.get({"BTCUSDT", "ETHUSDT"}),
            {
                "BTCUSDT": {"marketCap": 1_000.0},
                "ETHUSDT": {"marketCap": 500.0},
            },
        )

    def test_failed_page_does_not_replace_last_known_values(self):
        write_market_cap_file(
            self.path,
            {"BTCUSDT": {"marketCap": 1_000.0, "updatedAt": 10.0}},
            saved_at=10.0,
        )
        client = self.client(
            [RuntimeError("429")] * 3
        )

        refreshed = client._refresh_page_with_retries(5, {"BTCUSDT"})

        self.assertIsNone(refreshed)
        self.assertEqual(
            load_market_cap_file(self.path),
            {"BTCUSDT": {"marketCap": 1_000.0, "updatedAt": 10.0}},
        )

    def test_lower_rank_duplicate_does_not_replace_leading_ticker(self):
        client = self.client(
            [
                [
                    {
                        "id": "leading-abc",
                        "symbol": "abc",
                        "market_cap": 1_000.0,
                        "market_cap_rank": 100,
                    }
                ],
                [
                    {
                        "id": "smaller-abc",
                        "symbol": "abc",
                        "market_cap": 10.0,
                        "market_cap_rank": 1_500,
                    }
                ],
            ]
        )

        client.refresh_page(1, {"ABCUSDT"})
        client.refresh_page(7, {"ABCUSDT"})

        self.assertEqual(
            client.get({"ABCUSDT"}),
            {"ABCUSDT": {"marketCap": 1_000.0}},
        )
        self.assertEqual(
            load_market_cap_file(self.path)["ABCUSDT"]["coingeckoId"],
            "leading-abc",
        )

    def test_unranked_fdv_duplicate_does_not_replace_ranked_market_cap(self):
        client = self.client(
            [
                [
                    {
                        "id": "leading-abc",
                        "symbol": "abc",
                        "market_cap": 1_000.0,
                        "market_cap_rank": 100,
                    }
                ],
                [
                    {
                        "id": "unranked-abc",
                        "symbol": "abc",
                        "market_cap": None,
                        "fully_diluted_valuation": 5_000.0,
                        "market_cap_rank": None,
                    }
                ],
            ]
        )

        client.refresh_page(1, {"ABCUSDT"})
        client.refresh_page(8, {"ABCUSDT"})

        self.assertEqual(
            client.get({"ABCUSDT"}),
            {"ABCUSDT": {"marketCap": 1_000.0}},
        )
        self.assertEqual(
            load_market_cap_file(self.path)["ABCUSDT"]["coingeckoId"],
            "leading-abc",
        )

    def test_retain_symbols_prunes_confirmed_inactive_records(self):
        write_market_cap_file(
            self.path,
            {
                "BTCUSDT": {"marketCap": 1_000.0},
                "OLDUSDT": {"marketCap": 50.0},
            },
            saved_at=10.0,
        )
        client = self.client([])

        client.retain_symbols({"BTCUSDT"})

        self.assertEqual(
            load_market_cap_file(self.path),
            {"BTCUSDT": {"marketCap": 1_000.0}},
        )

    def test_background_round_spaces_pages_and_stops_cleanly(self):
        requested_pages = []
        waits = []

        def request_json(*_args, **kwargs):
            requested_pages.append(kwargs["params"]["page"])
            return []

        def wait(delay):
            waits.append(delay)
            if len(waits) == 2:
                raise PollingStopped()

        client = CoinGeckoMarketCapClient(
            request_json,
            wait,
            lambda *_args: None,
            cache_seconds=3_600,
            store_path=self.path,
            record_progress=self.progress.append,
        )

        with (
            patch(
                "realtime_oi_dashboard.market_cap_client.COINGECKO_PAGE_COUNT",
                2,
            ),
            patch(
                "realtime_oi_dashboard.market_cap_client.time.monotonic",
                side_effect=[100.0, 110.0],
            ),
        ):
            client.run_forever(lambda: {"BTCUSDT"})

        self.assertEqual(requested_pages, [1, 2])
        self.assertEqual(self.waits, [])
        self.assertEqual(waits, [30, 3_590])
        self.assertEqual(
            self.progress,
            [
                "CoinGecko market-cap page 1/2 succeeded; matched 0, "
                "loaded 0/1 active symbols.",
                "CoinGecko market-cap page 2/2 succeeded; matched 0, "
                "loaded 0/1 active symbols.",
                "CoinGecko market-cap refresh complete; loaded 0/1 active "
                "symbols; missing: BTCUSDT (not in top 2000 or ticker did "
                "not match).",
            ],
        )

    def test_background_round_logs_failed_pages_in_partial_summary(self):
        waits = []

        def request_json(*_args, **kwargs):
            if kwargs["params"]["page"] == 1:
                raise RuntimeError("429 rate limited")
            return [{"symbol": "btc", "market_cap": 1_000.0}]

        def wait(delay):
            waits.append(delay)
            if delay > 1_000:
                raise PollingStopped()

        client = CoinGeckoMarketCapClient(
            request_json,
            wait,
            lambda key, error: self.errors.append((key, str(error))),
            cache_seconds=3_600,
            store_path=self.path,
            record_progress=self.progress.append,
        )

        with (
            patch(
                "realtime_oi_dashboard.market_cap_client.COINGECKO_PAGE_COUNT",
                2,
            ),
            patch(
                "realtime_oi_dashboard.market_cap_client.time.monotonic",
                side_effect=[100.0, 110.0],
            ),
        ):
            client.run_forever(lambda: {"BTCUSDT", "ETHUSDT"})

        self.assertEqual(len(self.errors), 3)
        self.assertIn("page 1/2 failed", self.progress[0])
        self.assertIn("failed pages: 1", self.progress[-1])
        self.assertIn("missing: ETHUSDT", self.progress[-1])


if __name__ == "__main__":
    unittest.main()
