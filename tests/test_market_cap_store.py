import json
import tempfile
import unittest
from pathlib import Path

from realtime_oi_dashboard.infrastructure.market_cap_store import (
    load_market_cap_file,
    write_market_cap_file,
)


class MarketCapStoreTests(unittest.TestCase):
    def test_round_trip_keeps_valid_last_known_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market_caps.json"

            write_market_cap_file(
                path,
                {
                    "BTCUSDT": {
                        "marketCap": 1_000.0,
                        "updatedAt": 123.0,
                        "coingeckoId": "bitcoin",
                        "marketCapRank": 1,
                    }
                },
                saved_at=123.0,
            )

            self.assertEqual(
                load_market_cap_file(path),
                {
                    "BTCUSDT": {
                        "marketCap": 1_000.0,
                        "updatedAt": 123.0,
                        "coingeckoId": "bitcoin",
                        "marketCapRank": 1,
                    }
                },
            )

    def test_loader_skips_invalid_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market_caps.json"
            path.write_text(
                json.dumps(
                    {
                        "market_caps": {
                            "BTCUSDT": {"marketCap": 1_000},
                            "BAD-SYMBOL": {"marketCap": 50},
                            "ETHUSDT": {"marketCap": -1},
                            "SOLUSDT": "not-an-object",
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                load_market_cap_file(path),
                {"BTCUSDT": {"marketCap": 1_000.0}},
            )

    def test_missing_file_is_an_empty_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"

            self.assertEqual(load_market_cap_file(path), {})


if __name__ == "__main__":
    unittest.main()
