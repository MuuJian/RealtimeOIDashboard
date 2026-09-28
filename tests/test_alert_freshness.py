import tempfile
import unittest
from pathlib import Path

from realtime_oi_dashboard.application.oi_alerts.service import OiAlertService
from realtime_oi_dashboard.domain.oi.state import OiUpdate
from realtime_oi_dashboard.infrastructure.storage.oi_alerts import AlertStateRepository
from realtime_oi_dashboard.infrastructure.telegram.notifier import TelegramNotifier


class AlertFreshnessTests(unittest.TestCase):
    def test_expired_rows_remove_current_expansion_but_preserve_event_history(self):
        with tempfile.TemporaryDirectory() as directory:
            service = OiAlertService(
                AlertStateRepository(Path(directory) / "alerts.json"),
                notifier_factory=lambda **kwargs: TelegramNotifier(None, None, **kwargs),
            )
            timestamp = 1_790_553_600_000
            rows = {}
            for offset, quantity, price in ((0, 100, 100), (15 * 60_000, 110, 101)):
                row = {
                    "currentOi": quantity,
                    "currentOiValue": quantity * price,
                    "price": price,
                    "oiUpdatedAt": timestamp + offset,
                }
                rows["BTCUSDT"] = row
                service.observe_updates(
                    [OiUpdate("BTCUSDT", row, 1)], triggered_at="fallback"
                )

            live = service.get_state(rows)
            self.assertEqual(len(live["active"]), 1)
            self.assertEqual(len(live["events"]), 1)

            expired = service.get_state({})
            self.assertEqual(expired["active"], [])
            self.assertEqual(expired["features"], {})
            self.assertEqual(expired["events"], live["events"])
            service.close()
