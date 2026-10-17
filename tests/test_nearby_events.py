import json
import unittest
from unittest.mock import patch

from scripts.nearby_events import (
    validate, parse_anchor_time, query_sql, nearby,
)


class NearbyValidationTests(unittest.TestCase):
    def test_unknown_dataset_rejected(self):
        with self.assertRaises(ValueError):
            validate('nope', 5, 10, None)

    def test_limit_bounds(self):
        with self.assertRaises(ValueError):
            validate('bgl', 5, 1, None)
        with self.assertRaises(ValueError):
            validate('bgl', 5, 101, None)

    def test_window_bounds(self):
        with self.assertRaises(ValueError):
            validate('bgl', 0, 10, None)
        with self.assertRaises(ValueError):
            validate('bgl', 1441, 10, None)

    def test_node_filter_only_for_bgl(self):
        with self.assertRaises(ValueError):
            validate('openstack', 5, 10, 'R01-M0')
        self.assertEqual(validate('bgl', 5, 10, 'R01-M0'), (5, 10))

    def test_timezone_anchor_rejected(self):
        with self.assertRaises(ValueError):
            parse_anchor_time('2005-06-03T15:42:50+02:00')
        self.assertIsNotNone(parse_anchor_time('2005-06-03T15:42:50'))


class NearbySqlShapeTests(unittest.TestCase):
    def test_query_sql_splits_before_and_after(self):
        anchor = parse_anchor_time('2005-06-03T15:42:50')
        count, before, after = query_sql('bgl', anchor, 5, 10)
        self.assertIn('COUNT(*) AS matches', count)
        self.assertIn('event_time <=', before)
        self.assertTrue(before.endswith('LIMIT 5'))
        self.assertIn('event_time >', after)
        self.assertTrue(after.endswith('LIMIT 5'))

    def test_filter_values_are_quoted(self):
        anchor = parse_anchor_time('2005-06-03T15:42:50')
        _, before, _ = query_sql('bgl', anchor, 5, 10,
                                 component="kernel' OR true --")
        self.assertIn("component = 'kernel'' OR true --'", before)

    def test_openstack_scopes_window_to_source_file(self):
        anchor = parse_anchor_time('2017-05-14T19:39:02')
        _, before, _ = query_sql('openstack', anchor, 5, 10,
                                 source_file='openstack_abnormal.log')
        self.assertIn("source_file = 'openstack_abnormal.log'", before)


class NearbyOutputContractTests(unittest.TestCase):
    @patch('scripts.nearby_events.records')
    def test_nearby_marks_anchor_and_orders_by_time(self, mocked_records):
        mocked_records.side_effect = [
            # anchor_from_identity: resolve the center line's time/node
            [{'source_file': 'BGL.log', 'event_time': '2005-06-03 15:42:50',
              'node': 'R01-M0'}],
            [{'matches': '3'}],                                   # count
            [{'source_file': 'BGL.log', 'line_id': '5',
              'event_time': '2005-06-03 15:42:49', 'level': 'INFO',
              'component': 'kernel', 'content_preview': 'a'}],    # before
            [{'source_file': 'BGL.log', 'line_id': '6',
              'event_time': '2005-06-03 15:42:51', 'level': 'INFO',
              'component': 'kernel', 'content_preview': 'b'}],    # after
        ]
        result = nearby('bgl', 5, 10, source_file='BGL.log', line_id=6)

        self.assertEqual(result['dataset'], 'bgl')
        self.assertEqual(result['total_matches'], 3)
        times = [row['event_time'] for row in result['evidence']]
        self.assertEqual(times, sorted(times))
        json.dumps(result)

    @patch('scripts.nearby_events.records')
    def test_truncated_when_window_exceeds_returned(self, mocked_records):
        mocked_records.side_effect = [
            [{'matches': '50'}],
            [], [],
        ]
        result = nearby('bgl', 5, 10, anchor_time='2005-06-03T15:42:50')
        self.assertTrue(result['truncated'])
        self.assertEqual(result['returned'], 0)


if __name__ == '__main__':
    unittest.main()
