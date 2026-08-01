import unittest

from realtime_oi_dashboard.oi_history_points import (
    HISTORY_BASELINE_TOLERANCE_MS,
    calculate_change_percent,
    history_open_interest_point,
    history_point_price,
    history_point_value,
    parse_oi_history_points,
)


class ParseOiHistoryPointsTests(unittest.TestCase):
    def test_filters_invalid_items_and_sorts_by_timestamp(self):
        response = [
            {"timestamp": "300", "sumOpenInterest": "3"},
            "invalid",
            {"timestamp": 0, "sumOpenInterest": "0"},
            {"timestamp": "100", "sumOpenInterest": "1"},
            {"timestamp": "not-a-number", "sumOpenInterest": "2"},
        ]

        points = parse_oi_history_points(response)

        self.assertEqual([timestamp for timestamp, _ in points], [100, 300])

    def test_rejects_non_list_response(self):
        with self.assertRaisesRegex(ValueError, "unexpected OI history response"):
            parse_oi_history_points({"timestamp": 1})


class HistoryOpenInterestPointTests(unittest.TestCase):
    def test_selects_latest_point_at_or_before_target(self):
        target = 10_000
        points = [
            (
                8_000,
                {
                    "sumOpenInterest": "4",
                    "sumOpenInterestValue": "20",
                },
            ),
            (9_000, {"sumOpenInterest": "6", "sumOpenInterestValue": "42"}),
            (11_000, {"sumOpenInterest": "99"}),
        ]

        point = history_open_interest_point(points, target, "24h")

        self.assertEqual(point, (9_000, 6.0, 7.0))

    def test_skips_invalid_nearer_value_when_older_point_is_valid(self):
        target = 10_000
        points = [
            (8_000, {"sumOpenInterest": "5"}),
            (9_000, {"sumOpenInterest": "invalid"}),
        ]

        point = history_open_interest_point(points, target, "7d")

        self.assertEqual(point, (8_000, 5.0, None))

    def test_raises_when_only_in_range_value_is_invalid(self):
        points = [(9_000, {"sumOpenInterest": "invalid"})]

        with self.assertRaisesRegex(ValueError, "invalid 24h OI history"):
            history_open_interest_point(points, 10_000, "24h")

    def test_returns_none_when_point_is_outside_tolerance(self):
        target = 20_000_000
        too_old = target - HISTORY_BASELINE_TOLERANCE_MS - 1

        self.assertIsNone(
            history_open_interest_point(
                [(too_old, {"sumOpenInterest": "5"})],
                target,
                "7d",
            )
        )


class CachedHistoryPointTests(unittest.TestCase):
    def test_value_and_price_expire_together(self):
        point = (1_000, 5.0, 2.5)
        valid_target = 1_000 + HISTORY_BASELINE_TOLERANCE_MS
        expired_target = valid_target + 1

        self.assertEqual(history_point_value(point, valid_target), 5.0)
        self.assertEqual(history_point_price(point, valid_target), 2.5)
        self.assertIsNone(history_point_value(point, expired_target))
        self.assertIsNone(history_point_price(point, expired_target))

    def test_change_percent_requires_positive_baseline(self):
        self.assertEqual(calculate_change_percent(125, 100), 25)
        self.assertIsNone(calculate_change_percent(125, 0))
        self.assertIsNone(calculate_change_percent(125, None))


if __name__ == "__main__":
    unittest.main()
