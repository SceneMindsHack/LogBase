import inspect
import json
import os
import unittest
import uuid
from unittest.mock import patch

from scripts.distinctive_terms import (
    DEFAULT_EXCLUDED_TERMS,
    MAX_WINDOW_HOURS,
    MIN_INTERPRETATION_RECORDS,
    MAX_TOP_N,
    distinctive_terms,
    distinctive_terms_sql,
)

# Shared fixed args for brevity (two adjacent, non-overlapping windows).
FG = ("2020-01-01T00:00:00", "2020-01-01T01:00:00")
BG = ("2020-01-01T01:00:00", "2020-01-01T02:00:00")


def args(**overrides):
    base = dict(dataset="openstack", foreground_start=FG[0], foreground_end=FG[1],
                baseline_start=BG[0], baseline_end=BG[1])
    base.update(overrides)
    return base


class SqlShapeTests(unittest.TestCase):
    def test_uses_native_functions_and_index(self):
        sql, meta = distinctive_terms_sql(**args())
        self.assertIn("ts_dict_agg(content)", sql)
        self.assertIn("ts_dict_count(content)", sql)
        self.assertIn("FROM openstack_logs_fts", sql)
        self.assertEqual(meta["index_relation"], "openstack_logs_fts")

    def test_left_join_keeps_new_terms(self):
        sql, _ = distinctive_terms_sql(**args())
        self.assertIn("LEFT JOIN bg_terms", sql)
        self.assertIn("COALESCE(b.docs, 0)", sql)

    def test_inclusive_start_exclusive_end_and_content_not_null(self):
        sql, _ = distinctive_terms_sql(**args())
        self.assertIn("event_time >= '2020-01-01 00:00:00'", sql)
        self.assertIn("event_time < '2020-01-01 01:00:00'", sql)
        self.assertIn("content IS NOT NULL", sql)

    def test_support_and_ordering_in_sql(self):
        sql, _ = distinctive_terms_sql(**args(min_foreground_docs=5, top_n=7))
        self.assertIn("f.docs >= 5", sql)
        self.assertIn("ORDER BY excess_documents DESC, foreground_docs DESC, term ASC", sql)
        self.assertIn("LIMIT 7", sql)

    def test_qualifying_count_is_computed_before_limit(self):
        sql, _ = distinctive_terms_sql(**args(top_n=7))
        self.assertIn("COUNT(*) OVER () AS total_qualifying_terms", sql)
        self.assertLess(sql.index("COUNT(*) OVER ()"), sql.index("LIMIT 7"))

    def test_positive_excess_filter(self):
        sql, _ = distinctive_terms_sql(**args())
        self.assertIn("foreground_total * baseline_share > 0", sql)

    def test_same_filters_applied_to_both_windows(self):
        sql, _ = distinctive_terms_sql(**args(component="nova", levels=["ERROR"]))
        self.assertEqual(sql.count("component = 'nova'"), 4)  # fg+bg terms, fg+bg totals
        self.assertEqual(sql.count("level IN ('ERROR')"), 4)

    def test_default_exclusions_present_and_quoted(self):
        sql, meta = distinctive_terms_sql(**args())
        self.assertIn("f.term NOT IN (", sql)
        for term in DEFAULT_EXCLUDED_TERMS:
            self.assertIn("'" + term + "'", sql)
        self.assertEqual(meta["excluded_terms"], list(DEFAULT_EXCLUDED_TERMS))

    def test_user_exclusions_are_lowercased_and_added(self):
        _, meta = distinctive_terms_sql(**args(exclude_terms=["TIMEOUT", "Req"]))
        self.assertIn("timeout", meta["excluded_terms"])
        self.assertIn("req", meta["excluded_terms"])

    def test_values_are_quoted_safely(self):
        sql, _ = distinctive_terms_sql(**args(component="x' OR true --"))
        self.assertIn("component = 'x'' OR true --'", sql)


class ValidationTests(unittest.TestCase):
    def test_unknown_dataset(self):
        with self.assertRaises(ValueError):
            distinctive_terms_sql(**args(dataset="nope"))

    def test_reversed_window(self):
        with self.assertRaises(ValueError):
            distinctive_terms_sql(**args(foreground_start=FG[1], foreground_end=FG[0]))

    def test_overlapping_windows_rejected(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            distinctive_terms_sql(dataset="openstack",
                                  foreground_start="2020-01-01T00:00:00",
                                  foreground_end="2020-01-01T02:00:00",
                                  baseline_start="2020-01-01T01:00:00",
                                  baseline_end="2020-01-01T03:00:00")

    def test_adjacent_windows_allowed(self):
        sql, _ = distinctive_terms_sql(**args())  # FG end == BG start
        self.assertIn("ts_dict_agg", sql)

    def test_timezone_rejected(self):
        with self.assertRaises(ValueError):
            distinctive_terms_sql(**args(foreground_start="2020-01-01T00:00:00Z"))

    def test_min_support_must_be_positive(self):
        with self.assertRaises(ValueError):
            distinctive_terms_sql(**args(min_foreground_docs=0))

    def test_top_n_bounds(self):
        with self.assertRaises(ValueError):
            distinctive_terms_sql(**args(top_n=0))
        with self.assertRaises(ValueError):
            distinctive_terms_sql(**args(top_n=MAX_TOP_N + 1))

    def test_empty_levels_list_rejected(self):
        with self.assertRaises(ValueError):
            distinctive_terms_sql(**args(levels=[]))

    def test_maximum_window_boundary_accepted(self):
        _, meta = distinctive_terms_sql(
            dataset="bgl",
            foreground_start="2020-01-01T00:00:00",
            foreground_end="2020-01-02T00:00:00",
            baseline_start="2020-01-02T00:00:00",
            baseline_end="2020-01-03T00:00:00")
        self.assertEqual(meta["foreground"]["duration_seconds"], 24 * 60 * 60)
        self.assertEqual(meta["maximum_window_hours"], MAX_WINDOW_HOURS)

    @patch("scripts.distinctive_terms.records")
    def test_oversized_foreground_rejected_before_sql(self, mocked):
        with self.assertRaisesRegex(ValueError, "at most 24 hours"):
            distinctive_terms(
                dataset="bgl",
                foreground_start="2020-01-01T00:00:00",
                foreground_end="2020-01-02T00:00:01",
                baseline_start="2020-01-03T00:00:00",
                baseline_end="2020-01-04T00:00:00")
        mocked.assert_not_called()

    @patch("scripts.distinctive_terms.records")
    def test_oversized_baseline_rejected_before_sql(self, mocked):
        with self.assertRaisesRegex(ValueError, "at most 24 hours"):
            distinctive_terms(
                dataset="bgl",
                foreground_start="2020-01-01T00:00:00",
                foreground_end="2020-01-02T00:00:00",
                baseline_start="2020-01-02T00:00:00",
                baseline_end="2020-01-03T00:00:01")
        mocked.assert_not_called()


class ExecutionLogicTests(unittest.TestCase):
    """Mocked execution: verifies scoring, flags, types, and status handling."""

    def _rows(self, count=2, total_qualifying=None,
              foreground_total=100, baseline_total=100):
        total_qualifying = count if total_qualifying is None else total_qualifying
        seeds = [
            ("timeout", 60, 10),
            ("newtoken", 50, 0),
            ("connection", 40, 5),
        ]
        rows = []
        for term, foreground_docs, baseline_docs in seeds[:count]:
            foreground_share = foreground_docs / foreground_total
            baseline_share = (baseline_docs / baseline_total
                              if baseline_total else 0)
            rows.append({
                "term": term,
                "foreground_docs": str(foreground_docs),
                "baseline_docs": str(baseline_docs),
                "foreground_total": str(foreground_total),
                "baseline_total": str(baseline_total),
                "foreground_share": str(foreground_share),
                "baseline_share": str(baseline_share),
                "share_change": str(foreground_share - baseline_share),
                "excess_documents": str(
                    foreground_docs - foreground_total * baseline_share),
                "ratio": (str(foreground_share / baseline_share)
                          if baseline_share else None),
                "total_qualifying_terms": str(total_qualifying),
            })
        return rows

    @patch("scripts.distinctive_terms.records")
    def test_scores_flags_and_types(self, mocked):
        mocked.return_value = self._rows()
        result = distinctive_terms(**args(min_foreground_docs=5))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["foreground_total"], 100)
        timeout = result["terms"][0]
        self.assertEqual(timeout["term"], "timeout")
        self.assertEqual(timeout["foreground_docs"], 60)
        self.assertEqual(timeout["share_change_pp"], 50.0)
        self.assertEqual(timeout["excess_documents"], 50.0)
        self.assertEqual(timeout["ratio"], 6.0)
        self.assertFalse(timeout["new_in_baseline_comparison"])

        newtoken = result["terms"][1]
        self.assertIsNone(newtoken["ratio"])
        self.assertTrue(newtoken["new_in_baseline_comparison"])
        json.dumps(result)  # must be serializable

    @patch("scripts.distinctive_terms.records")
    def test_success_executes_only_ranking_and_discloses_it(self, mocked):
        mocked.return_value = self._rows()
        result = distinctive_terms(**args())

        self.assertEqual(mocked.call_count, 1)
        executed = [call.args[0] for call in mocked.call_args_list]
        self.assertEqual(result["sql"], executed)
        self.assertIn("total_qualifying_terms", result["sql"][0])

    @patch("scripts.distinctive_terms.records")
    def test_insufficient_data_status(self, mocked):
        mocked.side_effect = [[], [{"foreground_total": "0", "baseline_total": "100"}]]
        result = distinctive_terms(**args())
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["terms"], [])
        self.assertEqual(result["foreground_total"], 0)
        self.assertEqual(result["returned"], 0)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["total_qualifying_terms"], 0)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(result["sql"],
                         [call.args[0] for call in mocked.call_args_list])

    @patch("scripts.distinctive_terms.records")
    def test_no_distinctive_terms_status(self, mocked):
        mocked.side_effect = [[], [{"foreground_total": "100", "baseline_total": "100"}]]
        result = distinctive_terms(**args())
        self.assertEqual(result["status"], "no_distinctive_terms")
        self.assertIn("no term met", result["note"])
        self.assertEqual(result["returned"], 0)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["total_qualifying_terms"], 0)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(result["sql"],
                         [call.args[0] for call in mocked.call_args_list])

    @patch("scripts.distinctive_terms.records")
    def test_empty_baseline_with_ranking_row_needs_no_fallback(self, mocked):
        mocked.return_value = self._rows(count=1, baseline_total=0)
        result = distinctive_terms(**args())

        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["returned"], 0)
        self.assertEqual(result["terms"], [])
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(result["sql"],
                         [mocked.call_args_list[0].args[0]])

    @patch("scripts.distinctive_terms.records")
    def test_truncation_metadata_for_fewer_than_top_n(self, mocked):
        mocked.return_value = self._rows(count=2, total_qualifying=2)
        result = distinctive_terms(**args(top_n=3))
        self.assertEqual(result["returned"], 2)
        self.assertEqual(result["total_qualifying_terms"], 2)
        self.assertFalse(result["truncated"])

    @patch("scripts.distinctive_terms.records")
    def test_truncation_metadata_for_exactly_top_n(self, mocked):
        mocked.return_value = self._rows(count=3, total_qualifying=3)
        result = distinctive_terms(**args(top_n=3))
        self.assertEqual(result["returned"], 3)
        self.assertEqual(result["total_qualifying_terms"], 3)
        self.assertFalse(result["truncated"])

    @patch("scripts.distinctive_terms.records")
    def test_truncation_metadata_for_more_than_top_n(self, mocked):
        mocked.return_value = self._rows(count=3, total_qualifying=8)
        result = distinctive_terms(**args(top_n=3))
        self.assertEqual(result["returned"], 3)
        self.assertEqual(result["total_qualifying_terms"], 8)
        self.assertTrue(result["truncated"])

    @patch("scripts.distinctive_terms.records")
    def test_small_baseline_warning(self, mocked):
        mocked.return_value = self._rows(baseline_total=MIN_INTERPRETATION_RECORDS - 1)
        result = distinctive_terms(**args())
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("Baseline", result["warnings"][0])
        self.assertIn("ratios and comparisons may be unstable", result["warnings"][0])

    @patch("scripts.distinctive_terms.records")
    def test_small_foreground_warning(self, mocked):
        mocked.return_value = self._rows(
            foreground_total=MIN_INTERPRETATION_RECORDS - 1)
        result = distinctive_terms(**args())
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("Foreground", result["warnings"][0])
        self.assertIn("term rankings may be unstable", result["warnings"][0])

    @patch("scripts.distinctive_terms.records")
    def test_no_warning_for_adequate_windows(self, mocked):
        mocked.return_value = self._rows(
            foreground_total=MIN_INTERPRETATION_RECORDS,
            baseline_total=MIN_INTERPRETATION_RECORDS)
        result = distinctive_terms(**args())
        self.assertEqual(result["warnings"], [])

    @patch("scripts.distinctive_terms.records")
    def test_empty_window_is_not_reported_as_small(self, mocked):
        mocked.side_effect = [[], [{"foreground_total": "100", "baseline_total": "0"}]]
        result = distinctive_terms(**args())
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["warnings"], [])

    @patch("scripts.distinctive_terms.records")
    def test_response_with_warnings_is_json_serializable(self, mocked):
        mocked.return_value = self._rows(
            foreground_total=MIN_INTERPRETATION_RECORDS - 1,
            baseline_total=MIN_INTERPRETATION_RECORDS - 1)
        json.dumps(distinctive_terms(**args()))

    @patch("scripts.distinctive_terms.records")
    def test_method_metadata_names_native_functions(self, mocked):
        mocked.return_value = self._rows()
        result = distinctive_terms(**args())
        self.assertIn("ts_dict_agg(content)", result["method"]["functions"])
        self.assertIn("ts_dict_count(content)", result["method"]["functions"])
        self.assertEqual(result["method"]["maximum_window_hours"], MAX_WINDOW_HOURS)
        self.assertEqual(
            result["method"]["small_window_warning_threshold_records"],
            MIN_INTERPRETATION_RECORDS)


class RegistrationTests(unittest.TestCase):
    def test_registered_with_expected_signature(self):
        from scripts import tools
        self.assertIn("distinctive_terms", tools.mcp._tool_manager._tools)
        signature = inspect.signature(tools.distinctive_terms)
        self.assertEqual(
            list(signature.parameters),
            ["dataset", "foreground_start", "foreground_end",
             "baseline_start", "baseline_end", "component", "levels",
             "min_foreground_docs", "top_n", "exclude_terms"])
        self.assertEqual(
            {name: parameter.default
             for name, parameter in signature.parameters.items()},
            {"dataset": inspect.Parameter.empty,
             "foreground_start": inspect.Parameter.empty,
             "foreground_end": inspect.Parameter.empty,
             "baseline_start": inspect.Parameter.empty,
             "baseline_end": inspect.Parameter.empty,
             "component": None, "levels": None,
             "min_foreground_docs": 5, "top_n": 10,
             "exclude_terms": None})


@unittest.skipUnless(os.environ.get("LOGBASE_LIVE_TESTS") == "1",
                     "Live DB fixture test; set LOGBASE_LIVE_TESTS=1 to run")
class LiveFixtureTests(unittest.TestCase):
    """Proves the native feature works with correct document-frequency semantics
    using an isolated, uniquely named fixture table/index. Cleans up only itself."""

    @classmethod
    def setUpClass(cls):
        from scripts.db import execute
        cls.execute = staticmethod(execute)
        cls.table = "dt_fixture_" + uuid.uuid4().hex[:8]
        cls.index = cls.table + "_fts"
        # 10 foreground + 10 baseline records; see handoff controlled comparison.
        rows = []
        base = "2099-01-01"
        def add(window_hour, i, content):
            ts = f"{base} {window_hour:02d}:00:00"
            rows.append(f"('f',{len(rows)+1},'{ts}','INFO','c','{content}')")
        # foreground hour 00: timeout x6, newtoken x5, rare x1, common x10
        fg_contents = [
            "timeout timeout common", "timeout common newtoken", "timeout common newtoken",
            "timeout common newtoken", "timeout common newtoken", "timeout common newtoken",
            "rare common", "common only", "common filler", "common filler",
        ]
        bg_contents = [
            "timeout common", "common only", "common only", "common only", "common only",
            "common only", "common only", "common only", "common only", "common only",
        ]
        for c in fg_contents:
            add(0, 0, c)
        for c in bg_contents:
            add(1, 0, c)
        cls.execute(
            f"CREATE TABLE {cls.table} (source_file TEXT, line_id BIGINT, "
            f"event_time TIMESTAMP, level TEXT, component TEXT, content TEXT);")
        cls.execute(f"INSERT INTO {cls.table} VALUES " + ", ".join(rows) + ";")
        cls.execute(
            f"CREATE INDEX {cls.index} ON {cls.table} USING inverted "
            f"(source_file, line_id, event_time, level, component, content logbase_words) "
            f"INCLUDE (content);")
        cls.execute(f"VACUUM (REFRESH_TABLE) {cls.table};")

    @classmethod
    def tearDownClass(cls):
        cls.execute(f"DROP TABLE IF EXISTS {cls.table};")

    def _run(self, min_support=5, top_n=10):
        from scripts.db import records
        # Build SQL against the fixture index by patching the relation map.
        import scripts.distinctive_terms as dt
        original = dict(dt.INDEX_RELATIONS)
        dt.INDEX_RELATIONS["bgl"] = self.index
        try:
            return dt.distinctive_terms(
                "bgl",
                "2099-01-01T00:00:00", "2099-01-01T01:00:00",
                "2099-01-01T01:00:00", "2099-01-01T02:00:00",
                min_foreground_docs=min_support, top_n=top_n)
        finally:
            dt.INDEX_RELATIONS.clear()
            dt.INDEX_RELATIONS.update(original)

    def test_document_frequency_and_scores(self):
        result = self._run(min_support=5)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["foreground_total"], 10)
        self.assertEqual(result["baseline_total"], 10)
        by_term = {t["term"]: t for t in result["terms"]}

        # timeout: 6 fg (repeats in line 1 count once), 1 bg -> excess 5, ratio 6
        self.assertIn("timeout", by_term)
        self.assertEqual(by_term["timeout"]["foreground_docs"], 6)
        self.assertEqual(by_term["timeout"]["baseline_docs"], 1)
        self.assertAlmostEqual(by_term["timeout"]["excess_documents"], 5.0, places=4)
        self.assertAlmostEqual(by_term["timeout"]["ratio"], 6.0, places=4)

        # newtoken: 5 fg, 0 bg -> excess 5, null ratio, baseline-absence flag
        self.assertIn("newtoken", by_term)
        self.assertEqual(by_term["newtoken"]["baseline_docs"], 0)
        self.assertIsNone(by_term["newtoken"]["ratio"])
        self.assertTrue(by_term["newtoken"]["new_in_baseline_comparison"])

        # common: present in all records both windows -> zero excess, excluded
        self.assertNotIn("common", by_term)
        # rare: only 1 fg doc -> excluded by min support 5
        self.assertNotIn("rare", by_term)

    def test_rare_included_when_support_lowered(self):
        result = self._run(min_support=1)
        terms = {t["term"] for t in result["terms"]}
        self.assertIn("rare", terms)


if __name__ == "__main__":
    unittest.main()
