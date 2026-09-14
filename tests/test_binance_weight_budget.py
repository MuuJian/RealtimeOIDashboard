import threading
import unittest

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.infrastructure.binance.weight_budget import (
    BinanceWeightBudget,
    request_weight,
)


BINANCE_REQUEST_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"


class ManualClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class BinanceWeightBudgetTests(unittest.TestCase):
    def test_kline_weight_uses_actual_limit(self):
        url = "https://fapi.binance.com/fapi/v1/klines"
        for limit, expected in ((16, 1), (99, 1), (100, 2), (120, 2),
                                (499, 2), (500, 5), (1000, 5), (1500, 10)):
            self.assertEqual(request_weight(url, params={"limit": limit}), expected)
        self.assertEqual(request_weight(url + "?limit=120"), 2)

    def test_history_request_window_is_independent_of_weight(self):
        clock = ManualClock()
        def sleep(delay):
            clock.value += delay
        budget = BinanceWeightBudget(monotonic=clock, sleep=sleep)
        url = "https://fapi.binance.com/futures/data/openInterestHist"
        for _ in range(1000):
            budget.acquire(url)
        self.assertEqual(clock.value, 0)
        budget.acquire(url)
        self.assertEqual(clock.value, 300)

    def test_minute_budget_does_not_refill_inside_an_already_full_window(self):
        clock = ManualClock()
        def sleep(delay):
            clock.value += delay
        budget = BinanceWeightBudget(weight_per_minute=2, monotonic=clock, sleep=sleep)
        budget.acquire(BINANCE_REQUEST_URL)
        budget.acquire(BINANCE_REQUEST_URL)
        clock.value = 30
        budget.acquire(BINANCE_REQUEST_URL)
        self.assertEqual(clock.value, 60)

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
