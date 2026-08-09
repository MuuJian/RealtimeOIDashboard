import unittest

from realtime_oi_dashboard.domain.signal_scan.klines import (
    KLINE_INTERVAL_MILLISECONDS,
    KLINE_MAX_RESPONSE_ROWS,
    merge_kline_history,
    normalize_kline_history,
)


def make_klines(count, *, start=0, close=100):
    return [
        [
            start + index * KLINE_INTERVAL_MILLISECONDS,
            0,
            close,
            close,
            close,
        ]
        for index in range(count)
    ]


class NormalizeKlineHistoryTests(unittest.TestCase):
    def test_returns_a_bounded_copy(self):
        source = make_klines(5)

        result = normalize_kline_history(source, limit=3)

        self.assertEqual(result, source[-3:])
        self.assertIsNot(result[0], source[-3])

    def test_rejects_invalid_limit_without_raising(self):
        history = make_klines(2)

        for limit in (True, False, 0, -1, 1.5, "2", None):
            with self.subTest(limit=limit):
                self.assertIsNone(normalize_kline_history(history, limit=limit))

    def test_rejects_non_contiguous_or_unaligned_open_times(self):
        gapped = make_klines(3)
        gapped[-1][0] += KLINE_INTERVAL_MILLISECONDS
        unaligned = make_klines(3)
        unaligned[-1][0] += 1

        self.assertIsNone(normalize_kline_history(gapped, limit=3))
        self.assertIsNone(normalize_kline_history(unaligned, limit=3))

    def test_rejects_duplicate_or_descending_open_times(self):
        duplicate = make_klines(3)
        duplicate[-1][0] = duplicate[-2][0]
        descending = make_klines(3)
        descending[-1][0] = descending[0][0]

        self.assertIsNone(normalize_kline_history(duplicate, limit=3))
        self.assertIsNone(normalize_kline_history(descending, limit=3))

    def test_rejects_an_oversized_response(self):
        history = make_klines(KLINE_MAX_RESPONSE_ROWS + 1)

        self.assertIsNone(normalize_kline_history(history, limit=120))


class MergeKlineHistoryTests(unittest.TestCase):
    def test_replaces_overlap_and_appends_the_next_candle(self):
        cached = make_klines(4)
        updates = make_klines(
            2,
            start=3 * KLINE_INTERVAL_MILLISECONDS,
            close=110,
        )

        result = merge_kline_history(cached, updates, limit=4)

        self.assertEqual(
            [row[0] for row in result],
            [
                KLINE_INTERVAL_MILLISECONDS,
                2 * KLINE_INTERVAL_MILLISECONDS,
                3 * KLINE_INTERVAL_MILLISECONDS,
                4 * KLINE_INTERVAL_MILLISECONDS,
            ],
        )
        self.assertEqual(result[-2][4], 110)
        self.assertEqual(result[-1][4], 110)
        self.assertEqual(cached[-1][4], 100)

    def test_rejects_stale_updates(self):
        cached = make_klines(4, start=4 * KLINE_INTERVAL_MILLISECONDS)
        updates = make_klines(2)

        self.assertIsNone(merge_kline_history(cached, updates, limit=4))

    def test_rejects_a_gap_after_the_cache(self):
        cached = make_klines(4)
        updates = make_klines(
            2,
            start=5 * KLINE_INTERVAL_MILLISECONDS,
        )

        self.assertIsNone(merge_kline_history(cached, updates, limit=4))

    def test_rejects_duplicate_or_descending_updates(self):
        cached = make_klines(4)
        duplicate = make_klines(
            2,
            start=3 * KLINE_INTERVAL_MILLISECONDS,
        )
        duplicate[-1][0] = duplicate[0][0]
        descending = [row[:] for row in duplicate]
        descending[-1][0] -= KLINE_INTERVAL_MILLISECONDS

        self.assertIsNone(merge_kline_history(cached, duplicate, limit=4))
        self.assertIsNone(merge_kline_history(cached, descending, limit=4))

    def test_rejects_an_oversized_update_response(self):
        cached = make_klines(4)
        updates = make_klines(KLINE_MAX_RESPONSE_ROWS + 1)

        self.assertIsNone(merge_kline_history(cached, updates, limit=4))

    def test_rejects_invalid_limit_without_raising(self):
        history = make_klines(2)

        for limit in (True, False, 0, -1, 1.5, "2", None):
            with self.subTest(limit=limit):
                self.assertIsNone(
                    merge_kline_history(history, history, limit=limit)
                )

    def test_rejects_a_cache_larger_than_its_declared_window(self):
        cached = make_klines(4)
        updates = cached[-2:]

        self.assertIsNone(merge_kline_history(cached, updates, limit=3))


if __name__ == "__main__":
    unittest.main()
