import unittest

from realtime_oi_dashboard.market_cap import build_market_cap_map, normalize_ticker


class NormalizeTickerTests(unittest.TestCase):
    def test_strips_1000_prefix(self):
        self.assertEqual(normalize_ticker("1000PEPEUSDT"), "PEPE")

    def test_strips_1000000_prefix(self):
        self.assertEqual(normalize_ticker("1000000BOBUSDT"), "BOB")

    def test_strips_1m_prefix(self):
        self.assertEqual(normalize_ticker("1MBABYDOGEUSDT"), "BABYDOGE")

    def test_plain_symbol_unchanged_besides_quote_strip(self):
        self.assertEqual(normalize_ticker("BTCUSDT"), "BTC")

    def test_1inch_is_not_treated_as_multiplier_prefixed(self):
        # 1INCH is a real project ticker, not a "1000x contract" symbol.
        self.assertEqual(normalize_ticker("1INCHUSDT"), "1INCH")


class BuildMarketCapMapTests(unittest.TestCase):
    def test_matches_by_normalized_ticker(self):
        markets = [
            {"symbol": "btc", "market_cap": 900000000000},
            {"symbol": "pepe", "market_cap": 5000000000},
        ]
        active_symbols = {"BTCUSDT", "1000PEPEUSDT", "UNMATCHEDUSDT"}

        result = build_market_cap_map(markets, active_symbols)

        self.assertEqual(result["BTCUSDT"]["marketCap"], 900000000000)
        self.assertEqual(result["1000PEPEUSDT"]["marketCap"], 5000000000)
        self.assertNotIn("UNMATCHEDUSDT", result)

    def test_first_entry_wins_on_ticker_collision(self):
        # CoinGecko is requested with order=market_cap_desc, so the first
        # entry for a given ticker is the higher-market-cap one.
        markets = [
            {"symbol": "abc", "market_cap": 100},
            {"symbol": "abc", "market_cap": 1},
        ]
        active_symbols = {"ABCUSDT"}

        result = build_market_cap_map(markets, active_symbols)

        self.assertEqual(result["ABCUSDT"]["marketCap"], 100)

    def test_skips_malformed_entries_without_raising(self):
        markets = [
            {"symbol": "btc"},  # missing market_cap
            {"market_cap": 500},  # missing symbol
            "not-a-dict",
            {"symbol": "eth", "market_cap": 300000000000},
        ]
        active_symbols = {"BTCUSDT", "ETHUSDT"}

        result = build_market_cap_map(markets, active_symbols)

        self.assertNotIn("BTCUSDT", result)
        self.assertEqual(result["ETHUSDT"]["marketCap"], 300000000000)


if __name__ == "__main__":
    unittest.main()
