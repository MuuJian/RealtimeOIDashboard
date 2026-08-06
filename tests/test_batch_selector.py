import unittest

from realtime_oi_dashboard.batch_selector import RoundRobinBatchSelector


class RoundRobinBatchSelectorTests(unittest.TestCase):
    def test_batches_wrap_without_reordering_symbols(self):
        selector = RoundRobinBatchSelector(2)
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

        self.assertEqual(selector.next_batch(symbols), ["BTCUSDT", "ETHUSDT"])
        self.assertEqual(selector.next_batch(symbols), ["SOLUSDT", "BTCUSDT"])
        self.assertEqual(selector.position, 1)

    def test_empty_symbols_leave_position_unchanged(self):
        selector = RoundRobinBatchSelector(2)
        selector.restore(1)

        self.assertEqual(selector.next_batch([]), [])
        self.assertEqual(selector.position, 1)

    def test_reset_and_restore_support_refresh_and_failed_batch_rollback(self):
        selector = RoundRobinBatchSelector(2)
        selector.next_batch(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        selector.restore(1)

        self.assertEqual(selector.next_batch(["BTCUSDT", "ETHUSDT"]), [
            "ETHUSDT",
            "BTCUSDT",
        ])
        selector.reset()
        self.assertEqual(selector.position, 0)


if __name__ == "__main__":
    unittest.main()
