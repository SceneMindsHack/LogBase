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

    def test_identity_partition_uses_complete_ordering_key(self):
        anchor = parse_anchor_time('2005-06-03T15:42:50')
        _, before, after = query_sql(
            'bgl', anchor, 5, 10, source_file='BGL.log', anchor_line_id=20)

        self.assertIn('event_time <', before)
        self.assertIn("source_file < 'BGL.log'", before)
        self.assertIn('line_id < 20', before)
        self.assertTrue(before.endswith('LIMIT 4'))
        self.assertIn('event_time >', after)
        self.assertIn("source_file > 'BGL.log'", after)
        self.assertIn('line_id > 20', after)
        self.assertTrue(after.endswith('LIMIT 5'))


class NearbyOutputContractTests(unittest.TestCase):
    @patch('scripts.nearby_events.records')
    def test_missing_identity_fails_clearly(self, mocked_records):
        mocked_records.return_value = []

        with self.assertRaisesRegex(ValueError, 'No log row found for bgl/BGL.log/6'):
            nearby('bgl', 5, 10, source_file='BGL.log', line_id=6)

        self.assertIn('LIMIT 2', mocked_records.call_args.args[0])

    @patch('scripts.nearby_events.records')
    def test_duplicate_identity_fails_clearly(self, mocked_records):
        duplicate = {
            'source_file': 'BGL.log', 'line_id': '6',
            'event_time': '2005-06-03 15:42:50', 'level': 'INFO',
            'component': 'kernel', 'content_preview': 'anchor', 'node': 'R01-M0',
        }
        mocked_records.return_value = [duplicate, duplicate.copy()]

        with self.assertRaisesRegex(RuntimeError, 'Duplicate log identity detected'):
            nearby('bgl', 5, 10, source_file='BGL.log', line_id=6)

    @patch('scripts.nearby_events.records')
    def test_nearby_marks_anchor_and_orders_by_time(self, mocked_records):
        mocked_records.side_effect = [
            # anchor_from_identity: resolve the center line's time/node
            [{'source_file': 'BGL.log', 'line_id': '6',
              'event_time': '2005-06-03 15:42:50', 'level': 'INFO',
              'component': 'kernel', 'content_preview': 'anchor',
              'node': 'R01-M0'}],
            [{'matches': '3'}],                                   # count
            [{'source_file': 'BGL.log', 'line_id': '5',
              'event_time': '2005-06-03 15:42:49', 'level': 'INFO',
              'component': 'kernel', 'content_preview': 'a'}],    # before
            [{'source_file': 'BGL.log', 'line_id': '7',
              'event_time': '2005-06-03 15:42:51', 'level': 'INFO',
              'component': 'kernel', 'content_preview': 'b'}],    # after
        ]
        result = nearby('bgl', 5, 10, source_file='BGL.log', line_id=6)

        self.assertEqual(result['dataset'], 'bgl')
        self.assertEqual(result['total_matches'], 3)
        times = [row['event_time'] for row in result['evidence']]
        self.assertEqual(times, sorted(times))
        anchors = [row for row in result['evidence'] if row['is_anchor']]
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0]['line_id'], '6')
        for sql in result['sql'][1:]:
            self.assertIn("node = 'R01-M0'", sql)
        json.dumps(result)

    @patch('scripts.nearby_events.records')
    def test_equal_timestamp_anchor_is_included_once_in_correct_position(
            self, mocked_records):
        anchor_time = '2005-06-03 15:42:50'
        mocked_records.side_effect = [
            [{'source_file': 'BGL.log', 'line_id': '20',
              'event_time': anchor_time, 'level': 'ERROR',
              'component': 'kernel', 'content_preview': 'anchor',
              'node': 'R01-M0'}],
            [{'matches': '6'}],
            [
                {'source_file': 'BGL.log', 'line_id': '19',
                 'event_time': anchor_time, 'level': 'INFO',
                 'component': 'kernel', 'content_preview': 'same-time before'},
                {'source_file': 'BGL.log', 'line_id': '99',
                 'event_time': '2005-06-03 15:42:49', 'level': 'INFO',
                 'component': 'kernel', 'content_preview': 'earlier'},
            ],
            [
                {'source_file': 'BGL.log', 'line_id': '30',
                 'event_time': '2005-06-03 15:42:51', 'level': 'INFO',
                 'component': 'kernel', 'content_preview': 'later'},
                {'source_file': 'Z.log', 'line_id': '1',
                 'event_time': anchor_time, 'level': 'INFO',
                 'component': 'kernel', 'content_preview': 'other file after'},
                {'source_file': 'BGL.log', 'line_id': '21',
                 'event_time': anchor_time, 'level': 'INFO',
                 'component': 'kernel', 'content_preview': 'same-time after'},
            ],
        ]

        result = nearby(
            'bgl', 5, 6, source_file='BGL.log', line_id=20, all_nodes=True)

        identities = [
            (row['event_time'], row['source_file'], int(row['line_id']))
            for row in result['evidence']
        ]
        self.assertEqual(identities, sorted(identities))
        anchor_key = (anchor_time, 'BGL.log', 20)
        self.assertEqual(identities.count(anchor_key), 1)
        anchor_index = identities.index(anchor_key)
        self.assertTrue(all(key < anchor_key for key in identities[:anchor_index]))
        self.assertTrue(all(key > anchor_key for key in identities[anchor_index + 1:]))
        self.assertEqual(
            [row['is_anchor'] for row in result['evidence']],
            [False, False, True, False, False, False])

    @patch('scripts.nearby_events.records')
    def test_timestamp_anchor_output_order_uses_complete_key(self, mocked_records):
        event_time = '2005-06-03 15:42:50'
        mocked_records.side_effect = [
            [{'matches': '3'}],
            [
                {'source_file': 'B.log', 'line_id': '2', 'event_time': event_time,
                 'level': 'INFO', 'component': 'kernel', 'content_preview': 'b'},
                {'source_file': 'A.log', 'line_id': '10', 'event_time': event_time,
                 'level': 'INFO', 'component': 'kernel', 'content_preview': 'a10'},
                {'source_file': 'A.log', 'line_id': '2', 'event_time': event_time,
                 'level': 'INFO', 'component': 'kernel', 'content_preview': 'a2'},
            ],
            [],
        ]

        result = nearby('bgl', 5, 10, anchor_time='2005-06-03T15:42:50')

        self.assertEqual(
            [(row['source_file'], int(row['line_id'])) for row in result['evidence']],
            [('A.log', 2), ('A.log', 10), ('B.log', 2)])

    @patch('scripts.nearby_events.records')
    def test_openstack_identity_keeps_capture_file_scope(self, mocked_records):
        mocked_records.side_effect = [
            [{'source_file': 'openstack_abnormal.log', 'line_id': '8',
              'event_time': '2017-05-14 19:39:02', 'level': 'ERROR',
              'component': 'nova.api', 'content_preview': 'anchor'}],
            [{'matches': '1'}],
            [], [],
        ]

        result = nearby(
            'openstack', 5, 10,
            source_file='openstack_abnormal.log', line_id=8)

        for sql in result['sql'][1:]:
            self.assertIn("source_file = 'openstack_abnormal.log'", sql)
        self.assertEqual(result['returned'], 1)
        self.assertTrue(result['evidence'][0]['is_anchor'])

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
