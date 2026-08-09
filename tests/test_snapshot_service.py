import tempfile
import unittest
from pathlib import Path

from realtime_oi_dashboard.infrastructure.storage.oi_snapshot import (
    LoadedSnapshot,
    SnapshotRepository,
    SnapshotService,
)


class StubRepository:
    def __init__(self, loaded=None, load_error=None):
        self.loaded = loaded or LoadedSnapshot()
        self.load_error = load_error
        self.saved = []

    def load(self):
        if self.load_error is not None:
            raise self.load_error
        return self.loaded

    def save(self, **payload):
        self.saved.append(payload)


class SnapshotServiceTests(unittest.TestCase):
    def service(self, repository, clock, logs=None):
        return SnapshotService(
            repository,
            lambda: {"ETHUSDT", "BTCUSDT"},
            lambda: {"BTCUSDT": {"samples": []}},
            save_interval=10,
            iso_now=lambda: "2026-08-06T12:00:00+08:00",
            timestamp=lambda: "2026-08-06 12:00:00",
            log=(logs if logs is not None else []).append,
            monotonic=lambda: clock[0],
        )

    def test_repository_round_trip_preserves_snapshot_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SnapshotRepository(Path(directory) / "latest.json")
            repository.save(
                symbols={"ETHUSDT", "BTCUSDT"},
                saved_at="now",
                oi_history={"BTCUSDT": {"samples": []}},
            )

            loaded = repository.load()

            self.assertEqual(loaded.known_symbols, {"BTCUSDT", "ETHUSDT"})
            self.assertEqual(
                loaded.oi_history,
                {"BTCUSDT": {"samples": []}},
            )

    def test_save_is_throttled_and_force_bypasses_interval(self):
        repository = StubRepository()
        clock = [100.0]
        service = self.service(repository, clock)

        self.assertTrue(service.save())
        clock[0] = 105.0
        self.assertFalse(service.save())
        self.assertTrue(service.save(force=True))

        self.assertEqual(len(repository.saved), 2)
        self.assertEqual(
            repository.saved[0],
            {
                "symbols": {"ETHUSDT", "BTCUSDT"},
                "saved_at": "2026-08-06T12:00:00+08:00",
                "oi_history": {"BTCUSDT": {"samples": []}},
            },
        )

    def test_reset_schedule_allows_the_next_regular_save(self):
        repository = StubRepository()
        clock = [100.0]
        service = self.service(repository, clock)

        self.assertTrue(service.save())
        service.reset_schedule()
        self.assertTrue(service.save())

    def test_load_failure_returns_empty_snapshot_and_logs_error(self):
        logs = []
        service = self.service(
            StubRepository(load_error=ValueError("bad cache")),
            [100.0],
            logs,
        )

        loaded = service.load()

        self.assertEqual(loaded, LoadedSnapshot())
        self.assertEqual(
            logs,
            ["2026-08-06 12:00:00 failed to load previous OI cache: bad cache"],
        )


if __name__ == "__main__":
    unittest.main()
