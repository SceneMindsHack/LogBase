import unittest

from scripts.aggregations import count_by_sql, MAX_GROUPS


class CountBySqlShapeTests(unittest.TestCase):
    def test_component_dimension(self):
        sql, filters = count_by_sql('bgl', 'component')
        self.assertIn("COALESCE(NULLIF(l.component, ''), 'Unknown') AS group_value", sql)
        self.assertIn('FROM bgl_logs AS l', sql)
        self.assertIn('ORDER BY log_count DESC, group_value ASC', sql)
        self.assertIn('LIMIT 100', sql)
        self.assertEqual(filters['limit'], 100)

    def test_team_dimension_uses_ownership(self):
        sql, _ = count_by_sql('openstack', 'team')
        self.assertIn("COALESCE(o.team, 'Unassigned') AS group_value", sql)
        self.assertIn('LEFT JOIN ownership AS o', sql)

    def test_severity_maps_to_level_column(self):
        sql, _ = count_by_sql('bgl', 'severity')
        self.assertIn("COALESCE(NULLIF(l.level, ''), 'Unknown') AS group_value", sql)

    def test_counts_all_levels_by_default(self):
        # Unlike top_problems, no implicit problem-level filter is applied.
        sql, filters = count_by_sql('bgl', 'component')
        self.assertNotIn('l.level IN', sql)
        self.assertIsNone(filters['levels'])

    def test_explicit_levels_filter(self):
        sql, filters = count_by_sql('bgl', 'component', levels=['ERROR', 'FATAL'])
        self.assertIn("l.level IN ('ERROR', 'FATAL')", sql)
        self.assertEqual(filters['levels'], ['ERROR', 'FATAL'])

    def test_time_bounds_inclusive_start_exclusive_end(self):
        sql, _ = count_by_sql('openstack', 'component',
                              since='2017-05-14T00:00:00', until='2017-05-16T00:00:00')
        self.assertIn("l.event_time >= '2017-05-14 00:00:00'", sql)
        self.assertIn("l.event_time < '2017-05-16 00:00:00'", sql)

    def test_text_uses_full_text_table(self):
        sql, _ = count_by_sql('openstack', 'component', text='error')
        self.assertIn('FROM openstack_logs_fts AS l', sql)
        self.assertIn("l.content @@ 'error'", sql)

    def test_filter_values_are_quoted(self):
        sql, _ = count_by_sql('bgl', 'component', component="kernel' OR true --")
        self.assertIn("l.component = 'kernel'' OR true --'", sql)


class CountByValidationTests(unittest.TestCase):
    def test_unknown_dataset(self):
        with self.assertRaises(ValueError):
            count_by_sql('nope', 'component')

    def test_unknown_dimension(self):
        with self.assertRaises(ValueError):
            count_by_sql('bgl', 'request_id')

    def test_reversed_time_range(self):
        with self.assertRaises(ValueError):
            count_by_sql('bgl', 'component',
                         since='2017-05-16T00:00:00', until='2017-05-14T00:00:00')

    def test_rejects_timezone(self):
        with self.assertRaises(ValueError):
            count_by_sql('openstack', 'component', since='2017-05-14T00:00:00Z')

    def test_limit_bounds(self):
        with self.assertRaises(ValueError):
            count_by_sql('bgl', 'component', limit=0)
        with self.assertRaises(ValueError):
            count_by_sql('bgl', 'component', limit=MAX_GROUPS + 1)

    def test_empty_levels_list_rejected(self):
        with self.assertRaises(ValueError):
            count_by_sql('bgl', 'component', levels=[])

    def test_blank_component_rejected(self):
        with self.assertRaises(ValueError):
            count_by_sql('bgl', 'component', component='   ')


if __name__ == '__main__':
    unittest.main()
