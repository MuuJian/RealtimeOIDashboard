import unittest

from realtime_oi_dashboard.domain.cvd import RollingCvdWindow


class RollingCvdWindowTests(unittest.TestCase):
    def setUp(self):
        self.window = RollingCvdWindow(now_ms=0)
        self.window.set_tracked_symbols({"BTCUSDT"}, now_ms=0)

    def test_taker_buys_and_sells_are_signed_as_usdt_notional(self):
        self.window.add_trade(
            "BTCUSDT", 1, price=100, quantity=2, buyer_is_maker=False
        )
        self.window.add_trade(
            "BTCUSDT", 2, price=100, quantity=0.5, buyer_is_maker=True
        )

        snapshot = self.window.snapshot("BTCUSDT", now_ms=900_001)

        self.assertEqual(snapshot["cvd15m"], 150)
        self.assertEqual(snapshot["cvd15mRatio"], 0.6)
        self.assertEqual(snapshot["cvdStatus"], "buying")
        self.assertEqual(snapshot["cvdUpdatedAt"], 2)

    def test_snapshot_is_collecting_until_the_full_window_has_elapsed(self):
        self.window.add_trade(
            "BTCUSDT", 1, price=100, quantity=1, buyer_is_maker=False
        )

        snapshot = self.window.snapshot("BTCUSDT", now_ms=899_999)

        self.assertEqual(snapshot["cvdStatus"], "collecting")

    def test_snapshot_prunes_events_older_than_the_rolling_window(self):
        self.window.add_trade(
            "BTCUSDT", 1, price=100, quantity=1, buyer_is_maker=False
        )
        self.window.add_trade(
            "BTCUSDT", 900_002, price=100, quantity=2, buyer_is_maker=True
        )

        snapshot = self.window.snapshot("BTCUSDT", now_ms=900_002)

        self.assertEqual(snapshot["cvd15m"], -200)
        self.assertEqual(snapshot["cvd15mRatio"], -1)
        self.assertEqual(snapshot["cvdStatus"], "selling")

    def test_snapshot_is_untracked_for_symbols_outside_the_universe(self):
        self.assertEqual(
            self.window.snapshot("ETHUSDT", now_ms=900_000),
            {"cvdStatus": "untracked"},
        )

    def test_small_imbalance_is_neutral_after_collection(self):
        self.window.add_trade(
            "BTCUSDT", 1, price=100, quantity=1.05, buyer_is_maker=False
        )
        self.window.add_trade(
            "BTCUSDT", 2, price=100, quantity=1, buyer_is_maker=True
        )

        snapshot = self.window.snapshot("BTCUSDT", now_ms=900_001)

        self.assertEqual(snapshot["cvdStatus"], "neutral")


if __name__ == "__main__":
    unittest.main()
