import inspect
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from scripts.provenance import record_call, new_call_id, _extract_queries


class ExtractQueriesTests(unittest.TestCase):
    def test_sql_string(self):
        q = _extract_queries({"dataset": "bgl", "sql": "SELECT 1"})
        self.assertEqual(q, [{"sequence": 1, "sql": "SELECT 1", "dataset": "bgl"}])

    def test_sql_list_preserves_order(self):
        q = _extract_queries({"dataset": "openstack",
                              "sql": ["SELECT count", "SELECT bucket"]})
        self.assertEqual([e["sequence"] for e in q], [1, 2])
        self.assertEqual([e["sql"] for e in q], ["SELECT count", "SELECT bucket"])
        self.assertTrue(all(e["dataset"] == "openstack" for e in q))

    def test_data_overview_nested_per_dataset(self):
        result = {"datasets": [
            {"dataset": "bgl", "sql": ["scope_b", "levels_b", "teams_b", "components_b"]},
            {"dataset": "openstack", "sql": ["scope_o", "levels_o"]},
        ]}
        q = _extract_queries(result)
        self.assertEqual([e["sql"] for e in q],
                         ["scope_b", "levels_b", "teams_b", "components_b",
                          "scope_o", "levels_o"])
        self.assertEqual([e["sequence"] for e in q], [1, 2, 3, 4, 5, 6])
        self.assertEqual(q[0]["dataset"], "bgl")
        self.assertEqual(q[4]["dataset"], "openstack")

    def test_conditional_fallback_list_all_captured(self):
        # distinctive_terms-style: a sql list whose length varies by execution.
        q = _extract_queries({"dataset": "bgl", "sql": ["main_sql", "fallback_counts"]})
        self.assertEqual(len(q), 2)
        self.assertEqual(q[1]["sql"], "fallback_counts")

    def test_no_sql_yields_empty(self):
        self.assertEqual(_extract_queries({"found": False}), [])

    def test_blank_sql_ignored(self):
        self.assertEqual(_extract_queries({"sql": ["", "   "]}), [])


class RecordCallTests(unittest.TestCase):
    def test_appends_provenance_without_removing_fields(self):
        result = record_call("trend", {"dataset": "bgl", "interval": "day"},
                             lambda: {"total": 5, "sql": ["a", "b"]})
        self.assertEqual(result["total"], 5)          # existing field preserved
        self.assertEqual(result["sql"], ["a", "b"])   # existing field preserved
        prov = result["provenance"]
        self.assertEqual(prov["tool"], "trend")
        self.assertEqual(prov["arguments"], {"dataset": "bgl", "interval": "day"})
        self.assertEqual([q["sql"] for q in prov["queries"]], ["a", "b"])

    def test_call_ids_are_unique(self):
        ids = {new_call_id() for _ in range(1000)}
        self.assertEqual(len(ids), 1000)

    def test_arguments_capture_defaults(self):
        # The wrapper passes a resolved dict including defaults; verify it's stored.
        result = record_call("count_by", {"dataset": "bgl", "dimension": "component",
                                          "limit": 100},
                             lambda: {"sql": "SELECT 1"})
        self.assertEqual(result["provenance"]["arguments"]["limit"], 100)

    def test_timestamps_are_valid_utc(self):
        result = record_call("x", {}, lambda: {"sql": "SELECT 1"})
        prov = result["provenance"]
        start = datetime.fromisoformat(prov["started_at"])
        end = datetime.fromisoformat(prov["completed_at"])
        self.assertIsNotNone(start.tzinfo)   # timezone-aware
        self.assertIsNotNone(end.tzinfo)
        self.assertLessEqual(start, end)

    def test_error_propagates_without_fabricating_success(self):
        def boom():
            raise RuntimeError("db failure")
        with self.assertRaisesRegex(RuntimeError, "db failure"):
            record_call("trend", {"dataset": "bgl"}, boom)

    def test_json_serializable(self):
        result = record_call("search", {"dataset": "bgl", "query": "x"},
                             lambda: {"total_matches": 3, "sql": ["c", "e"]})
        json.dumps(result)


class ProvenanceMatchesExecutedSqlTests(unittest.TestCase):
    """The provenance SQL must be the statements actually executed, not rebuilt."""

    @patch("scripts.aggregations.records")
    def test_count_by_provenance_matches_executed(self, mocked):
        mocked.return_value = [{"group_value": "KERNEL", "log_count": "3",
                                "total_matching_rows": "3", "total_groups": "1"}]
        from scripts import tools
        result = tools.count_by("bgl", "component")
        executed_sql = mocked.call_args[0][0]
        prov_sql = result["provenance"]["queries"][0]["sql"]
        self.assertEqual(prov_sql, executed_sql)
        self.assertEqual(result["provenance"]["tool"], "count_by")

    @patch("scripts.data_overview.records")
    def test_data_overview_execution_order_matches_provenance(self, mocked):
        # Return shape per query; order of calls is what we assert on.
        def fake(query):
            if "COUNT(*) AS row_count" in query:
                return [{"row_count": "1", "first_event": "2005-06-03 15:42:50",
                         "last_event": "2005-06-03 15:42:50", "invalid_timestamps": "0",
                         "parse_failures": "0", "source_files": "1",
                         "distinct_components": "1"}]
            if "GROUP BY level" in query:
                return [{"level": "INFO", "count": "1"}]
            if "GROUP BY o.team" in query:
                return [{"team": "Platform Operations", "count": "1"}]
            return [{"component": "KERNEL", "team": "Platform Operations", "count": "1"}]
        mocked.side_effect = fake
        from scripts import tools
        result = tools.data_overview("bgl")
        executed = [c.args[0] for c in mocked.call_args_list]
        prov = [q["sql"] for q in result["provenance"]["queries"]]
        self.assertEqual(prov, executed)   # provenance order == execution order

    @patch("scripts.nearby_events.records")
    def test_nearby_identity_lookup_included(self, mocked):
        anchor_row = {"source_file": "BGL.log", "line_id": "5",
                      "event_time": "2005-06-03 15:42:50", "level": "INFO",
                      "component": "KERNEL", "content_preview": "x", "node": "R02"}

        def fake(query):
            if "WHERE source_file =" in query and "line_id =" in query and "COUNT" not in query:
                return [anchor_row]
            if "COUNT(*) AS matches" in query:
                return [{"matches": "2"}]
            return [{"source_file": "BGL.log", "line_id": "4",
                     "event_time": "2005-06-03 15:42:49", "level": "INFO",
                     "component": "KERNEL", "content_preview": "y"}]
        mocked.side_effect = fake
        from scripts import tools
        result = tools.nearby_events("bgl", source_file="BGL.log", line_id=5)
        prov_sql = [q["sql"] for q in result["provenance"]["queries"]]
        # The anchor identity lookup must appear in provenance, not just count/sides.
        self.assertTrue(any("WHERE source_file =" in s and "COUNT" not in s
                            for s in prov_sql))
        # And every executed statement is represented.
        executed = [c.args[0] for c in mocked.call_args_list]
        self.assertEqual(prov_sql, executed)


class RegistrationUnchangedTests(unittest.TestCase):
    def test_all_eight_tools_present_with_signatures(self):
        from scripts import tools
        expected = {"top_problems", "trend", "count_by", "data_overview", "search",
                    "nearby_events", "get_event_details", "distinctive_terms"}
        self.assertTrue(expected.issubset(set(tools.mcp._tool_manager._tools)))

    def test_signatures_have_no_varargs(self):
        from scripts import tools
        for name in ("trend", "count_by", "search", "nearby_events",
                     "get_event_details", "distinctive_terms", "data_overview",
                     "top_problems"):
            sig = inspect.signature(getattr(tools, name))
            kinds = {p.kind for p in sig.parameters.values()}
            self.assertNotIn(inspect.Parameter.VAR_POSITIONAL, kinds, name)
            self.assertNotIn(inspect.Parameter.VAR_KEYWORD, kinds, name)

    def test_instructions_expose_recap_and_keep_existing(self):
        from scripts import tools
        instr = tools.mcp._mcp_server.instructions
        self.assertIn("INVESTIGATION RECAP", instr)
        self.assertIn("ROLE-AWARE ANSWERS", instr)   # role guidance section preserved
        self.assertIn("PRESENTATION", instr)


if __name__ == "__main__":
    unittest.main()
