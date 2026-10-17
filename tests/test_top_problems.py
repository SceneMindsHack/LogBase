import json
import unittest
from unittest.mock import patch

from scripts.aggregations import DEFAULT_PROBLEM_LEVELS, ranked_count_sql
from scripts.top_problems import top_problems


class TopProblemsTests(unittest.TestCase):
    @patch("scripts.aggregations.records")
    def test_component_grouping_and_output_contract(self, mocked_records):
        mocked_records.return_value = [
            {
                "group_value": "nova.compute.manager",
                "owning_team": "Cloud Compute",
                "log_count": "8",
                "total_matching_rows": "10",
                "total_groups": "2",
            },
            {
                "group_value": "unknown.component",
                "owning_team": "Unassigned",
                "log_count": "2",
                "total_matching_rows": "10",
                "total_groups": "2",
            },
        ]

        result = top_problems("openstack", levels=["ERROR"], top_n=5)

        self.assertEqual(result["tool"], "top_problems")
        self.assertEqual(result["counted_metric"], "log_rows")
        self.assertEqual(result["total_matching_rows"], 10)
        self.assertEqual(result["returned"], 2)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["results"][0], {
            "rank": 1,
            "component": "nova.compute.manager",
            "count": 8,
            "percentage": 80.0,
            "owning_team": "Cloud Compute",
        })
        self.assertEqual(result["results"][1]["owning_team"], "Unassigned")
        self.assertEqual(result["filters"]["levels"], ["ERROR"])

    @patch("scripts.aggregations.records")
    def test_team_grouping_and_truncation(self, mocked_records):
        mocked_records.return_value = [
            {
                "group_value": "Cloud Compute",
                "log_count": "7",
                "total_matching_rows": "10",
                "total_groups": "3",
            },
            {
                "group_value": "Unassigned",
                "log_count": "2",
                "total_matching_rows": "10",
                "total_groups": "3",
            },
        ]

        result = top_problems("openstack", group_by="team", top_n=2)

        self.assertTrue(result["truncated"])
        self.assertEqual(result["results"][1], {
            "rank": 2,
            "team": "Unassigned",
            "count": 2,
            "percentage": 20.0,
        })

    def test_dataset_and_group_allow_lists(self):
        with self.assertRaisesRegex(ValueError, "dataset"):
            ranked_count_sql("openstack; DROP TABLE openstack_logs")
        with self.assertRaisesRegex(ValueError, "group_by"):
            ranked_count_sql("openstack", group_by="level; DROP TABLE x")

    def test_top_n_bounds(self):
        for invalid in (0, 51, True, 1.5):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "top_n"):
                    ranked_count_sql("bgl", top_n=invalid)
        ranked_count_sql("bgl", top_n=1)
        ranked_count_sql("bgl", top_n=50)

    def test_empty_levels_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            ranked_count_sql("bgl", levels=[])

    def test_blank_component_and_team_filters_are_rejected(self):
        for name in ("component", "team"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, f"{name} must not be blank"):
                    ranked_count_sql("openstack", **{name: "   \t"})

    @patch("scripts.aggregations.records", return_value=[])
    def test_default_problem_levels_are_applied_and_reported(self, _mocked_records):
        result = top_problems("openstack")

        self.assertEqual(result["filters"]["levels"], list(DEFAULT_PROBLEM_LEVELS))
        self.assertNotIn("INFO", result["filters"]["levels"])
        for level in DEFAULT_PROBLEM_LEVELS:
            self.assertIn(f"'{level}'", result["sql"])

    def test_explicit_levels_override_the_default(self):
        sql, filters = ranked_count_sql("bgl", levels=["INFO"])
        self.assertEqual(filters["levels"], ["INFO"])
        self.assertIn("l.level IN ('INFO')", sql)
        self.assertNotIn("'ERROR'", sql)

    def test_invalid_time_range(self):
        with self.assertRaisesRegex(ValueError, "since must precede until"):
            ranked_count_sql(
                "openstack", since="2017-05-17", until="2017-05-16"
            )

    def test_time_boundaries_are_inclusive_then_exclusive(self):
        sql, filters = ranked_count_sql(
            "openstack", since="2017-05-16", until="2017-05-17"
        )
        self.assertIn("l.event_time >= '2017-05-16 00:00:00'", sql)
        self.assertIn("l.event_time < '2017-05-17 00:00:00'", sql)
        self.assertEqual(filters["since_inclusive"], "2017-05-16T00:00:00")
        self.assertEqual(filters["until_exclusive"], "2017-05-17T00:00:00")

    def test_values_are_safely_quoted_and_text_reuses_full_text_relation(self):
        attack = "nova.driver' OR true --"
        sql, _ = ranked_count_sql(
            "openstack",
            levels=["ERROR' OR true --"],
            component=attack,
            team="Team' OR true --",
            text="disk' OR true --",
        )
        self.assertIn("FROM openstack_logs_fts AS l", sql)
        self.assertIn("nova.driver'' OR true --", sql)
        self.assertIn("ERROR'' OR true --", sql)
        self.assertIn("Team'' OR true --", sql)
        self.assertIn("disk'' OR true --", sql)

    @patch("scripts.aggregations.records", return_value=[])
    def test_empty_results_are_bounded_and_json_serializable(self, _mocked_records):
        result = top_problems("bgl")
        self.assertEqual(result["total_matching_rows"], 0)
        self.assertEqual(result["returned"], 0)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["results"], [])
        json.dumps(result)

    def test_sql_has_deterministic_ordering_and_unassigned_ownership(self):
        component_sql, _ = ranked_count_sql("bgl")
        team_sql, _ = ranked_count_sql("bgl", group_by="team")
        self.assertIn(
            "ORDER BY log_count DESC, group_value ASC, owning_team ASC",
            component_sql,
        )
        self.assertIn("ORDER BY log_count DESC, group_value ASC", team_sql)
        self.assertIn("COALESCE(o.team, 'Unassigned')", team_sql)
        self.assertIn("o.dataset = 'bgl' AND o.component = l.component", team_sql)

    @patch("scripts.aggregations.records")
    def test_caveats_and_fictional_ownership_are_explicit(self, mocked_records):
        mocked_records.return_value = []
        result = top_problems("openstack")
        self.assertTrue(result["ownership_is_fictional"])
        self.assertIn("physical log rows", result["caveat"])
        self.assertIn("do not establish distinct problems", result["caveat"])
        self.assertIn("root causes", result["caveat"])


if __name__ == "__main__":
    unittest.main()
