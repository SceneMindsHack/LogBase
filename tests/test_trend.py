import unittest
from datetime import datetime

from scripts.trend_tool import (query_sql, _bucket_starts, _zero_fill,
                                MAX_BUCKETS)


class TrendSqlTests(unittest.TestCase):
    def test_sql_shape_day(self):
        count_sql, bucket_sql = query_sql(
            'openstack', 'day', '2017-05-14T00:00:00', '2017-05-17T00:00:00')
        self.assertIn('FROM openstack_logs', count_sql)
        self.assertIn('FROM openstack_logs', bucket_sql)
        self.assertIn("event_time >= '2017-05-14 00:00:00'", bucket_sql)
        self.assertIn("event_time < '2017-05-17 00:00:00'", bucket_sql)
        self.assertIn('event_time IS NOT NULL', bucket_sql)
        self.assertIn("date_trunc('day', event_time)", bucket_sql)
        self.assertIn('GROUP BY bucket ORDER BY bucket', bucket_sql)

    def test_sql_shape_week_keyword(self):
        _, bucket_sql = query_sql(
            'bgl', 'week', '2005-06-01T00:00:00', '2005-07-01T00:00:00')
        self.assertIn("date_trunc('week', event_time)", bucket_sql)
        self.assertIn('FROM bgl_logs', bucket_sql)

    def test_sql_shape_hour_keyword(self):
        _, bucket_sql = query_sql(
            'openstack', 'hour', '2017-05-16T09:00:00', '2017-05-16T12:00:00')
        self.assertIn("date_trunc('hour', event_time)", bucket_sql)
        self.assertIn('FROM openstack_logs', bucket_sql)

    def test_filters_are_quoted(self):
        _, bucket_sql = query_sql(
            'bgl', 'day', '2005-06-01T00:00:00', '2005-06-02T00:00:00',
            level="ERROR' OR true --", component='kernel')
        # Single quote in the value is doubled by literal(), not left to break out.
        self.assertIn("level = 'ERROR'' OR true --'", bucket_sql)
        self.assertIn("component = 'kernel'", bucket_sql)

    def test_optional_filters_absent_when_none(self):
        _, bucket_sql = query_sql(
            'bgl', 'day', '2005-06-01T00:00:00', '2005-06-02T00:00:00')
        self.assertNotIn('level =', bucket_sql)
        self.assertNotIn('component =', bucket_sql)


class TrendValidationTests(unittest.TestCase):
    def test_unknown_dataset(self):
        with self.assertRaises(ValueError):
            query_sql('nope', 'day', '2017-05-14T00:00:00', '2017-05-15T00:00:00')

    def test_dataset_cannot_inject(self):
        with self.assertRaises(ValueError):
            query_sql('bgl; DROP TABLE x', 'day',
                      '2017-05-14T00:00:00', '2017-05-15T00:00:00')

    def test_unknown_interval(self):
        with self.assertRaises(ValueError):
            query_sql('bgl', 'month', '2017-05-14T00:00:00', '2017-05-15T00:00:00')

    def test_reversed_range(self):
        with self.assertRaises(ValueError):
            query_sql('bgl', 'day', '2017-05-15T00:00:00', '2017-05-14T00:00:00')

    def test_equal_range(self):
        with self.assertRaises(ValueError):
            query_sql('bgl', 'day', '2017-05-15T00:00:00', '2017-05-15T00:00:00')

    def test_rejects_timezone(self):
        with self.assertRaises(ValueError):
            query_sql('openstack', 'day',
                      '2017-05-14T00:00:00Z', '2017-05-15T00:00:00')

    def test_excessive_bucket_count(self):
        with self.assertRaises(ValueError):
            # Many years of daily buckets exceeds MAX_BUCKETS.
            query_sql('bgl', 'day', '2005-01-01T00:00:00', '2010-01-01T00:00:00')


class BucketStartTests(unittest.TestCase):
    def test_hourly_buckets_inclusive_start_exclusive_end(self):
        starts = _bucket_starts('hour', datetime(2017, 5, 16, 9, 0),
                                datetime(2017, 5, 16, 12, 0))
        self.assertEqual([d.isoformat() for d in starts],
                         ['2017-05-16T09:00:00', '2017-05-16T10:00:00',
                          '2017-05-16T11:00:00'])

    def test_partial_first_hour_included(self):
        # start mid-hour snaps back to the top of that hour.
        starts = _bucket_starts('hour', datetime(2017, 5, 16, 9, 37),
                                datetime(2017, 5, 16, 10, 15))
        self.assertEqual([d.isoformat() for d in starts],
                         ['2017-05-16T09:00:00', '2017-05-16T10:00:00'])

    def test_daily_buckets_inclusive_start_exclusive_end(self):
        starts = _bucket_starts('day', datetime(2017, 5, 14),
                                datetime(2017, 5, 17))
        self.assertEqual([d.isoformat() for d in starts],
                         ['2017-05-14T00:00:00', '2017-05-15T00:00:00',
                          '2017-05-16T00:00:00'])

    def test_partial_first_bucket_included(self):
        starts = _bucket_starts('day', datetime(2017, 5, 14, 13, 30),
                                datetime(2017, 5, 15, 2, 0))
        self.assertEqual([d.isoformat() for d in starts],
                         ['2017-05-14T00:00:00', '2017-05-15T00:00:00'])

    def test_weeks_start_monday(self):
        # 2017-05-17 is a Wednesday; its week starts Monday 2017-05-15. end on
        # 2017-05-23 (Tue) still falls inside the next Monday-week, so that
        # partial last bucket is included.
        starts = _bucket_starts('week', datetime(2017, 5, 17),
                                datetime(2017, 5, 23))
        self.assertEqual([d.isoformat() for d in starts],
                         ['2017-05-15T00:00:00', '2017-05-22T00:00:00'])

    def test_week_contained_in_single_bucket(self):
        # A range entirely within one Monday-week yields exactly that bucket.
        starts = _bucket_starts('week', datetime(2017, 5, 16),
                                datetime(2017, 5, 19))
        self.assertEqual([d.isoformat() for d in starts], ['2017-05-15T00:00:00'])

    def test_week_year_boundary(self):
        # BGL spans into 2006. 2005-12-31 (Sat) -> week of Mon 2005-12-26. end on
        # 2006-01-10 (Tue) pulls in the partial week starting Mon 2006-01-09.
        starts = _bucket_starts('week', datetime(2005, 12, 31),
                                datetime(2006, 1, 10))
        self.assertEqual([d.isoformat() for d in starts],
                         ['2005-12-26T00:00:00', '2006-01-02T00:00:00',
                          '2006-01-09T00:00:00'])

    def test_bucket_count_within_limit(self):
        starts = _bucket_starts('day', datetime(2005, 1, 1), datetime(2005, 2, 1))
        self.assertLessEqual(len(starts), MAX_BUCKETS)


class ZeroFillTests(unittest.TestCase):
    def test_missing_buckets_filled_with_zero(self):
        observed = [{'bucket': '2017-05-14 00:00:00', 'count': '18434'},
                    {'bucket': '2017-05-16 00:00:00', 'count': '123381'}]
        filled = _zero_fill('day', datetime(2017, 5, 14),
                            datetime(2017, 5, 17), observed)
        self.assertEqual(filled, [
            {'bucket_start': '2017-05-14T00:00:00', 'count': 18434},
            {'bucket_start': '2017-05-15T00:00:00', 'count': 0},
            {'bucket_start': '2017-05-16T00:00:00', 'count': 123381},
        ])

    def test_hourly_missing_buckets_filled_with_zero(self):
        observed = [{'bucket': '2017-05-16 09:00:00', 'count': '40'},
                    {'bucket': '2017-05-16 11:00:00', 'count': '7'}]
        filled = _zero_fill('hour', datetime(2017, 5, 16, 9, 0),
                            datetime(2017, 5, 16, 12, 0), observed)
        self.assertEqual(filled, [
            {'bucket_start': '2017-05-16T09:00:00', 'count': 40},
            {'bucket_start': '2017-05-16T10:00:00', 'count': 0},
            {'bucket_start': '2017-05-16T11:00:00', 'count': 7},
        ])

    def test_empty_observed_is_all_zero(self):
        filled = _zero_fill('day', datetime(2017, 5, 14),
                            datetime(2017, 5, 16), [])
        self.assertEqual([b['count'] for b in filled], [0, 0])

    def test_counts_are_integers(self):
        observed = [{'bucket': '2017-05-14 00:00:00', 'count': '5'}]
        filled = _zero_fill('day', datetime(2017, 5, 14),
                            datetime(2017, 5, 15), observed)
        self.assertIsInstance(filled[0]['count'], int)


if __name__ == '__main__':
    unittest.main()
