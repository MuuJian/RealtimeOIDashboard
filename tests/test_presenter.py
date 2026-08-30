import unittest

from realtime_oi_dashboard.domain.oi.state import OiStateStore, OiUpdate
from realtime_oi_dashboard.application.oi.presenter import DashboardPresenter


class StubClock:
    def __init__(self, stale=False):
        self.stale = stale
        self.checked_at = None

    def rows_are_stale(self, now):
        self.checked_at = now
        return self.stale


class DashboardPresenterTests(unittest.TestCase):
    def presenter(self, store, clock, cvd_state_provider=None):
        return DashboardPresenter(
            store,
            clock,
            lambda: [{"symbol": "ETHUSDT", "error": "temporary"}],
            lambda symbols: len(symbols & {"BTCUSDT"}),
            schema_version=7,
            stale_rows_error="stale",
            cvd_state_provider=cvd_state_provider,
            dominance_history_provider=lambda: [{"timestamp": 1, "btc": 100}],
            monotonic=lambda: 100.0,
            wall_time=lambda: 1_000.0,
        )

    def test_build_preserves_public_api_fields(self):
        store = OiStateStore(max_age_seconds=900)
        store.apply_updates([
            OiUpdate(
                symbol="BTCUSDT",
                row={"symbol": "BTCUSDT", "price": 100.0},
                measured_at=90.0,
            ),
        ])
        clock = StubClock()

        payload = self.presenter(store, clock).build(
            {"saved_at": "now", "error": None},
            ["BTCUSDT", "ETHUSDT"],
        )

        self.assertEqual(
            set(payload),
            {
                "saved_at",
                "error",
                "schema_version",
                "active_symbols",
                "total_symbols",
                "market_cap_loaded_symbols",
                "oi_dominance_history",
                "rows",
                "recent_errors",
                "cvd_meta",
            },
        )
        self.assertEqual(payload["schema_version"], 7)
        self.assertEqual(payload["active_symbols"], ["BTCUSDT", "ETHUSDT"])
        self.assertEqual(payload["total_symbols"], 2)
        self.assertEqual(payload["market_cap_loaded_symbols"], 1)
        self.assertEqual(
            payload["oi_dominance_history"],
            [{"timestamp": 1, "btc": 100}],
        )
        self.assertEqual(payload["rows"][0]["symbol"], "BTCUSDT")
        self.assertEqual(payload["rows"][0]["price"], 100.0)
        self.assertEqual(payload["rows"][0]["cvdStatus"], "unavailable")
        self.assertEqual(payload["rows"][0]["cvdHealth"], "unavailable")
        self.assertEqual(payload["cvd_meta"]["serviceHealth"], "unavailable")
        self.assertEqual(clock.checked_at, 1_000.0)

    def test_stale_rows_are_hidden_without_mutating_stored_rows(self):
        store = OiStateStore(max_age_seconds=900)
        store.apply_updates([
            OiUpdate(
                symbol="BTCUSDT",
                row={"symbol": "BTCUSDT"},
                measured_at=90.0,
            ),
        ])

        payload = self.presenter(store, StubClock(stale=True)).build(
            {"saved_at": "old", "error": None},
            ["BTCUSDT"],
        )

        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["error"], "stale")
        self.assertEqual(store.copy_rows(), [{"symbol": "BTCUSDT"}])

    def test_build_merges_matching_cvd_snapshot_without_mutating_stored_row(self):
        store = OiStateStore(max_age_seconds=900)
        store.apply_updates([
            OiUpdate(
                symbol="BTCUSDT",
                row={"symbol": "BTCUSDT", "price": 100.0},
                measured_at=90.0,
            ),
        ])

        payload = self.presenter(
            store,
            StubClock(),
            cvd_state_provider=FakeCvdProvider({
                "BTCUSDT": cvd_row(
                    cvd15m=120.0,
                    cvd15mRatio=0.12,
                    cvdStatus="buying",
                    cvdUpdatedAt=999,
                ),
            }),
        ).build({"saved_at": "now", "error": None}, ["BTCUSDT"])

        self.assertEqual(payload["rows"][0]["cvdStatus"], "buying")
        self.assertEqual(payload["rows"][0]["cvd15m"], 120.0)
        self.assertNotIn("cvdStatus", store.copy_rows()[0])

    def test_build_marks_untracked_rows_when_cvd_provider_has_no_match(self):
        store = OiStateStore(max_age_seconds=900)
        store.apply_updates([
            OiUpdate(
                symbol="BTCUSDT", row={"symbol": "BTCUSDT"}, measured_at=90.0
            ),
        ])

        payload = self.presenter(
            store, StubClock(), cvd_state_provider=FakeCvdProvider({})
        ).build({"saved_at": "now", "error": None}, ["BTCUSDT"])

        self.assertEqual(payload["rows"][0]["cvdStatus"], "untracked")

    def test_top_level_cvd_error_does_not_hide_healthy_symbol_snapshot(self):
        store = OiStateStore(max_age_seconds=900)
        store.apply_updates([
            OiUpdate(
                symbol="BTCUSDT",
                row={"symbol": "BTCUSDT"},
                measured_at=90.0,
            ),
        ])
        provider = FakeCvdProvider({
            "BTCUSDT": cvd_row(
                cvd15m=50.0,
                cvd15mRatio=0.2,
                cvdStatus="buying",
                cvdHealth="live",
            ),
        })
        provider.error = "one shard failed"

        payload = self.presenter(
            store,
            StubClock(),
            cvd_state_provider=provider,
        ).build({"saved_at": "now", "error": None}, ["BTCUSDT"])

        self.assertEqual(payload["rows"][0]["cvd15m"], 50.0)
        self.assertEqual(payload["rows"][0]["cvdHealth"], "live")

    def test_malformed_cvd_rows_do_not_hide_healthy_oi_rows(self):
        store = oi_store()
        provider = FakeCvdProvider([])

        payload = self.presenter(
            store,
            StubClock(),
            cvd_state_provider=provider,
        ).build({"saved_at": "now", "error": None}, ["BTCUSDT"])

        self.assertEqual(payload["rows"][0]["symbol"], "BTCUSDT")
        self.assertEqual(payload["rows"][0]["price"], 100.0)
        self.assertEqual(payload["rows"][0]["cvdStatus"], "unavailable")

    def test_cvd_snapshot_cannot_overwrite_oi_fields(self):
        store = oi_store()
        provider = FakeCvdProvider({
            "BTCUSDT": {
                **cvd_row(),
                "symbol": "ETHUSDT",
                "price": 1.0,
                "currentOi": 0,
            },
        })

        payload = self.presenter(
            store,
            StubClock(),
            cvd_state_provider=provider,
        ).build({"saved_at": "now", "error": None}, ["BTCUSDT"])

        row = payload["rows"][0]
        self.assertEqual(row["symbol"], "BTCUSDT")
        self.assertEqual(row["price"], 100.0)
        self.assertEqual(row["currentOi"], 10.0)
        self.assertEqual(row["cvdStatus"], "buying")

    def test_invalid_symbol_snapshot_degrades_only_cvd_fields(self):
        store = oi_store()
        provider = FakeCvdProvider({"BTCUSDT": ["invalid"]})

        payload = self.presenter(
            store,
            StubClock(),
            cvd_state_provider=provider,
        ).build({"saved_at": "now", "error": None}, ["BTCUSDT"])

        row = payload["rows"][0]
        self.assertEqual(row["price"], 100.0)
        self.assertEqual(row["cvdStatus"], "unavailable")

    def test_invalid_cvd_meta_degrades_without_breaking_oi_payload(self):
        store = oi_store()
        provider = FakeCvdProvider({"BTCUSDT": cvd_row()})
        provider.meta = cvd_meta(processingLagMs=float("inf"))

        payload = self.presenter(
            store,
            StubClock(),
            cvd_state_provider=provider,
        ).build({"saved_at": "now", "error": None}, ["BTCUSDT"])

        self.assertEqual(payload["rows"][0]["cvdStatus"], "buying")
        self.assertEqual(payload["cvd_meta"]["serviceHealth"], "unavailable")
        self.assertEqual(payload["cvd_meta"]["processingLagMs"], 0.0)


class FakeCvdProvider:
    def __init__(self, rows):
        self.rows = rows
        self.error = None
        self.meta = None

    def get_state(self):
        return {
            "rows": self.rows,
            "error": self.error,
            "cvd_meta": self.meta,
        }


def oi_store():
    store = OiStateStore(max_age_seconds=900)
    store.apply_updates([
        OiUpdate(
            symbol="BTCUSDT",
            row={
                "symbol": "BTCUSDT",
                "price": 100.0,
                "currentOi": 10.0,
            },
            measured_at=90.0,
        ),
    ])
    return store


def cvd_row(**overrides):
    return {
        "cvd15m": 120.0,
        "cvd15mRatio": 0.12,
        "cvdDirection": "buying",
        "cvdHealth": "live",
        "cvdAsOf": 999,
        "cvdCoverageSeconds": 900,
        "cvdReason": None,
        "cvdStatus": "buying",
        "cvdUpdatedAt": 999,
        **overrides,
    }


def cvd_meta(**overrides):
    return {
        "serviceHealth": "live",
        "universeSymbols": 1,
        "desiredShards": 1,
        "activeShards": 1,
        "connectedShards": 1,
        "incomingMessagesPerSecond": 2.5,
        "processingLagMs": 10.0,
        "backfillQueueSize": 0,
        "healthCounts": {
            "warming": 0,
            "live": 1,
            "stale": 0,
            "partial": 0,
            "unavailable": 0,
        },
        **overrides,
    }


if __name__ == "__main__":
    unittest.main()
