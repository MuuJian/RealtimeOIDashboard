import threading
import unittest

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.infrastructure.binance.weight_budget import (
    BinanceWeightBudget,
)


BINANCE_REQUEST_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"


class ManualClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class BinanceWeightBudgetTests(unittest.TestCase):
    def test_wait_can_be_interrupted_by_the_request_owner(self):
        clock = ManualClock()
        stopped = threading.Event()
        waits = []
        budget = BinanceWeightBudget(
            weight_per_minute=1,
            monotonic=clock,
            sleep=lambda _delay: self.fail("default sleep should not run"),
        )
        budget.acquire(BINANCE_REQUEST_URL)

        def check_cancelled():
            if stopped.is_set():
                raise PollingStopped()

        def wait(delay):
            waits.append(delay)
            stopped.set()

        with self.assertRaises(PollingStopped):
            budget.acquire(
                BINANCE_REQUEST_URL,
                check_cancelled=check_cancelled,
                sleep=wait,
            )

        self.assertEqual(waits, [1.0])

    def test_rejects_invalid_capacity(self):
        for capacity in (True, 0, -1, float("nan"), float("inf"), "bad"):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                BinanceWeightBudget(weight_per_minute=capacity)

    def test_rejects_a_request_heavier_than_total_capacity(self):
        budget = BinanceWeightBudget(weight_per_minute=1)

        with self.assertRaisesRegex(ValueError, "exceeds budget capacity"):
            budget.acquire("https://fapi.binance.com/fapi/v1/ticker/24hr")


if __name__ == "__main__":
    unittest.main()
