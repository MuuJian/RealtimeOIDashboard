import unittest

from realtime_oi_dashboard.domain.symbols import is_valid_binance_symbol


class BinanceSymbolValidationTests(unittest.TestCase):
    def test_accepts_uppercase_ascii_symbols(self):
        for symbol in ("BTCUSDT", "1000PEPEUSDT", "BTCDOMUSDT"):
            with self.subTest(symbol=symbol):
                self.assertTrue(is_valid_binance_symbol(symbol))

    def test_rejects_non_ascii_or_non_uppercase_symbols(self):
        for symbol in (
            "",
            "btcusdt",
            "BtcUSDT",
            "BTC-USDT",
            "BTC_USDT",
            " BTCUSDT",
            "BTCUSDT ",
            "ＢＴＣUSDT",
            "坏USDT",
            None,
            123,
        ):
            with self.subTest(symbol=symbol):
                self.assertFalse(is_valid_binance_symbol(symbol))


if __name__ == "__main__":
    unittest.main()
