import json
import unittest
from unittest.mock import patch

from scripts.search_logs import search, query_sql


def evidence_row(source_file, line_id, event_time):
    return {
        'source_file': source_file,
        'line_id': str(line_id),
        'event_time': event_time,
        'level': 'ERROR',
        'component': 'nova.api',
        'content_preview': f'message {line_id}',
    }


class SearchOutputContractTests(unittest.TestCase):
    @patch('scripts.search_logs.records')
    def test_ranks_follow_existing_result_order(self, mocked_records):
        ordered_rows = [
            evidence_row('a.log', 2, '2017-05-14 19:39:02'),
            evidence_row('a.log', 9, '2017-05-14 19:39:02'),
            evidence_row('b.log', 1, '2017-05-14 19:39:03'),
        ]
        mocked_records.side_effect = [[{'matches': '3'}], ordered_rows]

        result = search('openstack', 'failure', 3)

        self.assertEqual([row['rank'] for row in result['evidence']], [1, 2, 3])
        self.assertEqual(
            [(row['source_file'], row['line_id']) for row in result['evidence']],
            [('a.log', '2'), ('a.log', '9'), ('b.log', '1')],
        )
        self.assertEqual(result['total_matches'], 3)
        self.assertEqual(result['returned'], 3)
        self.assertFalse(result['truncated'])

    @patch('scripts.search_logs.records')
    def test_every_result_retains_stable_identity(self, mocked_records):
        mocked_records.side_effect = [
            [{'matches': '2'}],
            [
                evidence_row('normal.log', 7, '2017-05-14 19:39:02'),
                evidence_row('normal.log', 8, '2017-05-14 19:39:03'),
            ],
        ]

        result = search('openstack', 'failure', 2)

        for row in result['evidence']:
            self.assertEqual(row['dataset'], 'openstack')
            self.assertTrue(row['source_file'])
            self.assertTrue(row['line_id'])

    @patch('scripts.search_logs.records')
    def test_empty_results_are_rankless_and_json_serializable(self, mocked_records):
        mocked_records.side_effect = [[{'matches': '0'}], []]

        result = search('bgl', 'not-present', 10)

        self.assertEqual(result['evidence'], [])
        self.assertEqual(result['returned'], 0)
        self.assertEqual(result['total_matches'], 0)
        self.assertFalse(result['truncated'])
        json.dumps(result)

    @patch('scripts.search_logs.records')
    def test_truncated_results_keep_totals_filters_and_sequential_ranks(
            self, mocked_records):
        mocked_records.side_effect = [
            [{'matches': '10'}],
            [
                evidence_row('normal.log', 7, '2017-05-14 19:39:02'),
                evidence_row('normal.log', 8, '2017-05-14 19:39:03'),
            ],
        ]

        result = search(
            'openstack', 'failure', 2,
            since='2017-05-14T00:00:00', until='2017-05-15T00:00:00',
            levels=['ERROR', 'ERROR'],
        )

        self.assertEqual([row['rank'] for row in result['evidence']], [1, 2])
        self.assertEqual(result['total_matches'], 10)
        self.assertEqual(result['returned'], 2)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['since_inclusive'], '2017-05-14T00:00:00')
        self.assertEqual(result['until_exclusive'], '2017-05-15T00:00:00')
        self.assertEqual(result['levels'], ['ERROR'])
        self.assertEqual(result['content_preview_limit'], 500)
        self.assertTrue(result['sql'][1].endswith('LIMIT 2'))
        json.dumps(result)

    def test_query_uses_websearch_parser_for_both_statements(self):
        count_sql, evidence_sql = query_sql('openstack', 'disk info')
        for statement in (count_sql, evidence_sql):
            self.assertIn("websearch_to_tsquery('disk info')", statement)
        # The raw string is parsed by the database, not matched directly.
        self.assertNotIn("content @@ 'disk info'", count_sql)

    def test_query_value_is_safely_quoted(self):
        count_sql, _ = query_sql('openstack', "it's a trap")
        self.assertIn("websearch_to_tsquery('it''s a trap')", count_sql)

    def test_mcp_guidance_preserves_rank_identity_mapping(self):
        from scripts import tools

        self.assertIn('search rank', tools.INSTRUCTIONS)
        self.assertIn('(dataset, source_file, line_id)', tools.INSTRUCTIONS)
        self.assertIn('get_event_details', tools.search.__doc__)
        self.assertIn('nearby_events', tools.search.__doc__)
        self.assertIn('result 2', tools.search.__doc__)


if __name__ == '__main__':
    unittest.main()
