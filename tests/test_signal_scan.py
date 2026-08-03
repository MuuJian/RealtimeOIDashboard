import unittest

from realtime_oi_dashboard.signal_scan import (
    build_scan_universe,
    classify_symbol,
    compute_ema,
    select_signals,
)


def make_klines(closes, highs=None, lows=None):
    highs = highs if highs is not None else closes
    lows = lows if lows is not None else closes
    return [
        [0, 0, highs[i], lows[i], closes[i], 0, 0, 0, 0, 0, 0, 0]
        for i in range(len(closes))
    ]


class ComputeEmaTests(unittest.TestCase):
    def test_matches_known_manual_calculation(self):
        result = compute_ema([1.0, 2.0, 3.0], period=2)

        self.assertAlmostEqual(result, 2.5555555555555554)

    def test_single_value_returns_that_value(self):
        self.assertEqual(compute_ema([5.0], period=20), 5.0)


class ClassifySymbolTests(unittest.TestCase):
    def test_returns_none_when_fewer_than_60_candles(self):
        klines = make_klines([1.0] * 59)

        result = classify_symbol("BTCUSDT", 1.0, klines)

        self.assertIsNone(result)

    def test_flat_price_series_is_neither_bull_nor_bear(self):
        klines = make_klines([100.0] * 120)

        result = classify_symbol("BTCUSDT", 5.0, klines)

        self.assertFalse(result["isBull"])
        self.assertFalse(result["isBear"])
        self.assertAlmostEqual(result["aboveE20"], 0.0)
        self.assertEqual(result["chg24h"], 5.0)

    def test_steadily_rising_price_is_classified_bullish(self):
        closes = [100.0 + i for i in range(120)]
        klines = make_klines(closes)

        result = classify_symbol("ETHUSDT", 10.0, klines)

        self.assertTrue(result["isBull"])
        self.assertFalse(result["isBear"])
        self.assertGreater(result["aboveE20"], 0)

    def test_steadily_falling_price_is_classified_bearish(self):
        closes = [220.0 - i for i in range(120)]
        klines = make_klines(closes)

        result = classify_symbol("SOLUSDT", -10.0, klines)

        self.assertFalse(result["isBull"])
        self.assertTrue(result["isBear"])
        self.assertLess(result["aboveE20"], 0)

    def test_zero_base_amplitude_yields_zero_vol_ratio(self):
        closes = [100.0] * 120
        highs = [100.0] * 117 + [105.0] * 3
        lows = [100.0] * 117 + [95.0] * 3
        klines = make_klines(closes, highs, lows)

        result = classify_symbol("ADAUSDT", 0.0, klines)

        self.assertEqual(result["volRatio"], 0.0)

    def test_recent_spike_yields_high_vol_ratio(self):
        closes = [100.0] * 120
        highs = [100.0] * 87 + [100.5] * 30 + [102.5] * 3
        lows = [100.0] * 87 + [99.5] * 30 + [97.5] * 3
        klines = make_klines(closes, highs, lows)

        result = classify_symbol("XRPUSDT", 0.0, klines)

        self.assertGreater(result["volRatio"], 1.8)


class SelectSignalsTests(unittest.TestCase):
    def entry(self, symbol, above_e20, is_bull, is_bear, vol_ratio):
        return {
            "symbol": symbol,
            "price": 1.0,
            "chg1h": 0.0,
            "chg24h": 0.0,
            "aboveE20": above_e20,
            "isBull": is_bull,
            "isBear": is_bear,
            "volRatio": vol_ratio,
        }

    def test_bulls_sorted_descending_and_limited_to_eight(self):
        entries = [
            self.entry(f"SYM{i}USDT", float(i), True, False, 0.0)
            for i in range(10)
        ]
        trend_pool = {e["symbol"] for e in entries}

        signals = select_signals(entries, trend_pool)

        self.assertEqual(len(signals["bulls"]), 8)
        self.assertEqual(signals["bulls"][0]["symbol"], "SYM9USDT")
        self.assertEqual(signals["bulls"][-1]["symbol"], "SYM2USDT")

    def test_bears_sorted_ascending_and_limited_to_eight(self):
        entries = [
            self.entry(f"SYM{i}USDT", -float(i), False, True, 0.0)
            for i in range(10)
        ]
        trend_pool = {e["symbol"] for e in entries}

        signals = select_signals(entries, trend_pool)

        self.assertEqual(len(signals["bears"]), 8)
        self.assertEqual(signals["bears"][0]["symbol"], "SYM9USDT")

    def test_trend_pool_excludes_symbols_outside_pool(self):
        entries = [
            self.entry("INUSDT", 5.0, True, False, 0.0),
            self.entry("OUTUSDT", 10.0, True, False, 0.0),
        ]

        signals = select_signals(entries, trend_pool_symbols={"INUSDT"})

        self.assertEqual([e["symbol"] for e in signals["bulls"]], ["INUSDT"])

    def test_spikes_use_full_pool_not_trend_pool(self):
        entries = [self.entry("OUTUSDT", 0.0, False, False, 2.5)]

        signals = select_signals(entries, trend_pool_symbols=set())

        self.assertEqual([e["symbol"] for e in signals["spikes"]], ["OUTUSDT"])

    def test_spike_threshold_excludes_low_vol_ratio(self):
        entries = [self.entry("LOWUSDT", 0.0, False, False, 1.2)]

        signals = select_signals(entries, trend_pool_symbols=set())

        self.assertEqual(signals["spikes"], [])


class BuildScanUniverseTests(unittest.TestCase):
    def exchange_info(self, symbols):
        return {
            "symbols": [
                {
                    "symbol": s,
                    "contractType": "PERPETUAL",
                    "underlyingType": "COIN",
                    "status": "TRADING",
                }
                for s in symbols
            ]
        }

    def test_sorts_by_quote_volume_descending_and_caps_pool_sizes(self):
        symbols = [f"SYM{i}USDT" for i in range(35)]
        tickers = [
            {"symbol": s, "quoteVolume": str(i + 1), "priceChangePercent": "0"}
            for i, s in enumerate(symbols)
        ]

        scan_pool, trend_pool_symbols = build_scan_universe(
            tickers, self.exchange_info(symbols)
        )

        self.assertEqual(len(scan_pool), 30)
        self.assertEqual(scan_pool[0]["symbol"], "SYM34USDT")
        self.assertEqual(len(trend_pool_symbols), 20)
        self.assertIn("SYM34USDT", trend_pool_symbols)
        self.assertNotIn("SYM14USDT", trend_pool_symbols)

    def test_excludes_stablecoins_and_non_perpetual_coin_contracts(self):
        tickers = [
            {"symbol": "USDCUSDT", "quoteVolume": "999", "priceChangePercent": "0"},
            {"symbol": "BTCUSDT", "quoteVolume": "999", "priceChangePercent": "0"},
            {"symbol": "DEFIUSDT", "quoteVolume": "500", "priceChangePercent": "0"},
            {"symbol": "ETHUSDT", "quoteVolume": "800", "priceChangePercent": "0"},
        ]
        exchange_info = {
            "symbols": [
                {"symbol": "USDCUSDT", "contractType": "PERPETUAL", "underlyingType": "COIN", "status": "TRADING"},
                {"symbol": "BTCUSDT", "contractType": "PERPETUAL", "underlyingType": "COIN", "status": "TRADING"},
                {"symbol": "DEFIUSDT", "contractType": "PERPETUAL", "underlyingType": "INDEX", "status": "TRADING"},
                {"symbol": "ETHUSDT", "contractType": "PERPETUAL", "underlyingType": "COIN", "status": "TRADING"},
            ]
        }

        scan_pool, _ = build_scan_universe(tickers, exchange_info)

        self.assertEqual([t["symbol"] for t in scan_pool], ["ETHUSDT"])

    def test_excludes_zero_volume_symbols(self):
        tickers = [{"symbol": "ABCUSDT", "quoteVolume": "0", "priceChangePercent": "0"}]
        exchange_info = self.exchange_info(["ABCUSDT"])

        scan_pool, _ = build_scan_universe(tickers, exchange_info)

        self.assertEqual(scan_pool, [])


if __name__ == "__main__":
    unittest.main()
