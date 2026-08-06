import unittest

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.application.market_snapshot import MarketSnapshotProvider


class StubBinance:
    def __init__(self, calls):
        self.calls = calls

    def get_market_tickers(self, symbols):
        self.calls.append(("tickers", symbols))
        return {"BTCUSDT": {"price": 100.0}}

    def get_funding_rates(self, symbols):
        self.calls.append(("funding", symbols))
        return {"BTCUSDT": {"fundingRatePercent": 0.01}}


class StubMarketCaps:
    def __init__(self, calls):
        self.calls = calls

    def get(self, symbols):
        self.calls.append(("market_caps", symbols))
        return {"BTCUSDT": {"marketCap": 20_000.0}}


class MarketSnapshotProviderTests(unittest.TestCase):
    def test_collects_each_shared_source_once_in_existing_order(self):
        calls = []
        checks = []
        symbols = {"BTCUSDT"}
        provider = MarketSnapshotProvider(
            StubBinance(calls),
            StubMarketCaps(calls),
            lambda: checks.append("running"),
        )

        snapshot = provider.get(symbols)

        self.assertEqual(
            calls,
            [
                ("tickers", symbols),
                ("funding", symbols),
                ("market_caps", symbols),
            ],
        )
        self.assertEqual(checks, ["running", "running", "running"])
        self.assertEqual(snapshot.tickers["BTCUSDT"]["price"], 100.0)
        self.assertEqual(snapshot.funding_rates["BTCUSDT"]["fundingRatePercent"], 0.01)
        self.assertEqual(snapshot.market_caps["BTCUSDT"]["marketCap"], 20_000.0)

    def test_cancellation_stops_before_next_shared_request(self):
        calls = []

        def stop_after_tickers():
            raise PollingStopped()

        provider = MarketSnapshotProvider(
            StubBinance(calls),
            StubMarketCaps(calls),
            stop_after_tickers,
        )

        with self.assertRaises(PollingStopped):
            provider.get({"BTCUSDT"})

        self.assertEqual(calls, [("tickers", {"BTCUSDT"})])


if __name__ == "__main__":
    unittest.main()
