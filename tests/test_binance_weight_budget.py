import threading
import unittest

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.infrastructure.binance.weight_budget import (
    BinanceCooldownError,
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
    def test_cooldown_rejects_requests_until_expiry_but_not_other_providers(self):
        clock = ManualClock()
        budget = BinanceWeightBudget(monotonic=clock,
                                      sleep=lambda _: self.fail("cooldown must not block a worker"))
        budget.defer(BINANCE_REQUEST_URL, 4200, status_code=418)
        with self.assertRaises(BinanceCooldownError) as failure:
            budget.acquire(BINANCE_REQUEST_URL)
        self.assertEqual(failure.exception.status_code, 418)
        self.assertEqual(failure.exception.retry_after, 4200)
        budget.acquire("https://api.coingecko.com/api/v3/coins/markets")
        clock.value = 4200
        self.assertEqual(failure.exception.retry_after, 0)
        budget.acquire(BINANCE_REQUEST_URL)

    def test_observed_ip_weight_is_conservative_for_out_of_order_headers(self):
        clock = ManualClock()
        budget = BinanceWeightBudget(weight_per_minute=10, monotonic=clock,
                                      sleep=lambda delay: setattr(clock, "value", clock.value + delay))
        budget.acquire(BINANCE_REQUEST_URL)
        budget.observe_response(BINANCE_REQUEST_URL, {"X-MBX-USED-WEIGHT-1M": "10"})
        budget.observe_response(BINANCE_REQUEST_URL, {"x-mbx-used-weight-1m": "1"})
        budget.acquire(BINANCE_REQUEST_URL)
        self.assertEqual(clock.value, 60)

    def test_invalid_or_non_binance_usage_headers_do_not_reserve_weight(self):
        clock = ManualClock()
        budget = BinanceWeightBudget(weight_per_minute=1, monotonic=clock,
                                      sleep=lambda _: self.fail("invalid header reserved weight"))
        for value in ("bad", "NaN", "Infinity", "-1", None):
            budget.observe_response(BINANCE_REQUEST_URL, {"X-MBX-USED-WEIGHT-1M": value})
        budget.observe_response("https://example.com", {"X-MBX-USED-WEIGHT-1M": "100"})
        budget.acquire(BINANCE_REQUEST_URL)

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
