import unittest

from realtime_oi_dashboard.domain.oi_row import OIRowBuilder


class OIRowBuilderTests(unittest.TestCase):
    def test_build_preserves_dashboard_row_contract(self):
        update = OIRowBuilder().build(
            symbol="BTCUSDT",
            ticker={
                "price": 100.0,
                "volume24h": 5_000.0,
                "priceChangePercent": 3.5,
            },
            funding={
                "fundingRatePercent": 0.01,
                "nextFundingTime": 1_800_000,
            },
            market_cap=20_000.0,
            current_oi=12.0,
            oi_history={
                "oiChange24h": 1.25,
                "oiChange7d": -2.5,
            },
            measured_wall_time=1_000.0,
            measured_at=200.0,
        )

        self.assertEqual(update.symbol, "BTCUSDT")
        self.assertEqual(update.measured_at, 200.0)
        self.assertEqual(
            update.row,
            {
                "symbol": "BTCUSDT",
                "price": 100.0,
                "volume24h": 5_000.0,
                "currentOi": 12.0,
                "currentOiValue": 1_200.0,
                "marketCap": 20_000.0,
                "oiUpdatedAt": 1_000_000,
                "priceChangePercent": 3.5,
                "fundingRatePercent": 0.01,
                "nextFundingTime": 1_800_000,
                "oiChange24h": 1.25,
                "oiChange7d": -2.5,
            },
        )


if __name__ == "__main__":
    unittest.main()
