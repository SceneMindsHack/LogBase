import json
import unittest
from unittest.mock import patch

from scripts.data_overview import (
    scope_sql, levels_sql, components_sql, teams_sql, overview_one, overview,
)


class DataOverviewSqlShapeTests(unittest.TestCase):
    def test_scope_sql_targets_dataset_table(self):
        sql = scope_sql('bgl')
        self.assertIn('FROM bgl_logs', sql)
        self.assertIn('COUNT(*) AS row_count', sql)
        self.assertIn('MIN(event_time) AS first_event', sql)

    def test_components_and_teams_join_ownership_with_quoted_dataset(self):
        components = components_sql('openstack')
        teams = teams_sql('openstack')
        self.assertIn('LEFT JOIN component_ownership o', components)
        self.assertIn("o.dataset = 'openstack'", components)
        self.assertIn("COALESCE(o.team, 'Unassigned') AS team", teams)

    def test_levels_sql_groups_and_orders(self):
        sql = levels_sql('bgl')
        self.assertIn('GROUP BY level', sql)
        self.assertIn('ORDER BY count DESC, level', sql)


class DataOverviewValidationTests(unittest.TestCase):
    def test_unknown_dataset_rejected(self):
        with self.assertRaises(ValueError):
            overview_one('nope')


class DataOverviewOutputContractTests(unittest.TestCase):
    @patch('scripts.data_overview.records')
    def test_overview_one_builds_json_contract(self, mocked_records):
        mocked_records.side_effect = [
            [{'row_count': '42', 'first_event': '2005-06-03 15:42:50',
              'last_event': '2005-06-04 00:00:00', 'invalid_timestamps': '0',
              'parse_failures': '10', 'source_files': '1',
              'distinct_components': '2'}],                      # scope
            [{'level': 'INFO', 'count': '40'},
             {'level': '', 'count': '2'}],                       # levels
            [{'component': 'kernel', 'team': 'Kernel', 'count': '40'},
             {'component': '', 'team': 'Unassigned', 'count': '2'}],  # components
            [{'team': 'Kernel', 'count': '42'}],                 # teams
        ]

        result = overview_one('bgl')

        self.assertEqual(result['dataset'], 'bgl')
        self.assertEqual(result['row_count'], 42)
        self.assertEqual(result['parse_failures'], 10)
        self.assertTrue(result['has_node_column'])
        # Blank level/component surface as null, not empty string.
        self.assertIsNone(result['levels'][1]['level'])
        self.assertIsNone(result['components'][1]['component'])
        self.assertEqual(len(result['sql']), 4)
        json.dumps(result)

    @patch('scripts.data_overview.records')
    def test_openstack_has_no_node_column(self, mocked_records):
        mocked_records.side_effect = [
            [{'row_count': '0', 'first_event': '', 'last_event': '',
              'invalid_timestamps': '0', 'parse_failures': '0',
              'source_files': '0', 'distinct_components': '0'}],
            [], [], [],
        ]
        result = overview_one('openstack')
        self.assertFalse(result['has_node_column'])
        self.assertIsNone(result['first_event'])

    @patch('scripts.data_overview.records')
    def test_overview_runs_both_datasets(self, mocked_records):
        mocked_records.side_effect = [
            [{'row_count': '1', 'first_event': '', 'last_event': '',
              'invalid_timestamps': '0', 'parse_failures': '0',
              'source_files': '1', 'distinct_components': '0'}],
            [], [], [],
        ] * 2
        result = overview('all')
        self.assertEqual(len(result['datasets']), 2)
        self.assertIn('elapsed_seconds', result)


if __name__ == '__main__':
    unittest.main()
