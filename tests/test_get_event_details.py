import inspect
import json
import unittest
from unittest.mock import patch

from scripts.get_event_details import (
    COMMON_FIELDS,
    DATASET_FIELDS,
    event_details_sql,
    get_event_details,
)


def common_row(**overrides):
    row = {
        "source_file": "sample.log",
        "line_id": "7",
        "event_time": "2017-05-16 03:19:45.356",
        "level": "ERROR",
        "component": "sample.component",
        "content": "complete message",
        "raw_text": "complete raw line",
        "parse_ok": "t",
        "parse_error": "",
        "event_id": "",
        "event_template": "",
        "raw_text_base64": "Y29tcGxldGUgcmF3IGxpbmU=",
        "owning_team": "Example Team",
    }
    row.update(overrides)
    return row


class GetEventDetailsTests(unittest.TestCase):
    @patch("scripts.get_event_details.records")
    def test_bgl_event_contains_common_and_specific_fields(self, mocked_records):
        mocked_records.return_value = [common_row(
            source_file="BGL.log",
            event_time="2005-06-03 15:42:50.363779",
            component="KERNEL",
            label="-",
            epoch_seconds="1117838570",
            node="R02-M1-N0-C:J12-U11",
            log_type="RAS",
            owning_team="Compute Reliability",
        )]

        result = get_event_details("bgl", "BGL.log", 7)

        self.assertTrue(result["found"])
        self.assertEqual(result["requested_identity"], {
            "dataset": "bgl", "source_file": "BGL.log", "line_id": 7,
        })
        self.assertTrue(set(COMMON_FIELDS).issubset(result["event"]))
        self.assertTrue(set(DATASET_FIELDS["bgl"]).issubset(result["event"]))
        self.assertNotIn("pid", result["event"])
        self.assertEqual(result["event"]["line_id"], 7)
        self.assertEqual(result["event"]["epoch_seconds"], 1117838570)
        self.assertEqual(result["event"]["owning_team"], "Compute Reliability")
        self.assertTrue(result["event"]["parse_ok"])
        json.dumps(result)

    @patch("scripts.get_event_details.records")
    def test_openstack_event_contains_specific_fields(self, mocked_records):
        mocked_records.return_value = [common_row(
            source_file="openstack_normal1.log",
            log_record="nova.log",
            pid="2931",
            request_id="req-abcd",
            instance_id="instance-123",
            correlation_data="[req-abcd]",
            owning_team="Cloud Compute",
        )]

        result = get_event_details("openstack", "openstack_normal1.log", 7)

        self.assertEqual(result["event"]["pid"], 2931)
        self.assertEqual(result["event"]["request_id"], "req-abcd")
        self.assertEqual(result["event"]["raw_text"], "complete raw line")
        self.assertEqual(
            result["event"]["raw_text_base64"],
            "Y29tcGxldGUgcmF3IGxpbmU=",
        )
        self.assertNotIn("epoch_seconds", result["event"])

    @patch("scripts.get_event_details.records")
    def test_unparsed_row_is_preserved(self, mocked_records):
        mocked_records.return_value = [common_row(
            event_time="",
            level="",
            component="",
            content="unparsed continuation",
            raw_text="unparsed continuation",
            parse_ok="f",
            parse_error="Unrecognized OpenStack header or continuation line",
            raw_text_base64="",
            log_record="",
            pid="",
            request_id="",
            instance_id="",
            correlation_data="",
            owning_team="Unassigned",
        )]

        result = get_event_details("openstack", "sample.log", 7)

        self.assertFalse(result["event"]["parse_ok"])
        self.assertIsNone(result["event"]["event_time"])
        self.assertIsNone(result["event"]["component"])
        self.assertEqual(result["event"]["raw_text"], "unparsed continuation")
        self.assertEqual(result["event"]["owning_team"], "Unassigned")
        self.assertTrue(result["ownership_is_fictional"])
        self.assertIn("physical log line", result["caveat"])
        self.assertIn("root cause", result["caveat"])

    @patch("scripts.get_event_details.records", return_value=[])
    def test_missing_event_returns_found_false(self, _mocked_records):
        result = get_event_details("bgl", "missing.log", 99)

        self.assertFalse(result["found"])
        self.assertIsNone(result["event"])
        self.assertEqual(result["requested_identity"]["line_id"], 99)
        self.assertIn("LIMIT 2", result["sql"])

    def test_invalid_identity_inputs(self):
        cases = (
            (("other", "a.log", 1), "dataset"),
            (("bgl", "   ", 1), "source_file"),
            (("bgl", "a.log", 0), "line_id"),
            (("bgl", "a.log", -1), "line_id"),
            (("bgl", "a.log", True), "line_id"),
            (("bgl", "a.log", "1"), "line_id"),
        )
        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ValueError, message):
                    event_details_sql(*arguments)

    def test_sql_uses_allowlisted_table_and_quotes_values(self):
        sql = event_details_sql("openstack", "a' OR true --", 7)

        self.assertIn("FROM openstack_logs AS l", sql)
        self.assertIn("l.source_file = 'a'' OR true --'", sql)
        self.assertIn("l.line_id = 7", sql)
        self.assertIn("o.dataset = 'openstack'", sql)
        self.assertIn("COALESCE(o.team, 'Unassigned')", sql)

    @patch("scripts.get_event_details.records")
    def test_duplicate_identity_raises_clear_error(self, mocked_records):
        mocked_records.return_value = [common_row(), common_row()]

        with self.assertRaisesRegex(RuntimeError, "Duplicate log identity"):
            get_event_details("openstack", "sample.log", 7)

    def test_fastmcp_registration_and_contract(self):
        from scripts import tools

        self.assertIn("get_event_details", tools.mcp._tool_manager._tools)
        signature = inspect.signature(tools.get_event_details)
        self.assertEqual(
            list(signature.parameters),
            ["dataset", "source_file", "line_id"],
        )
        self.assertIs(signature.parameters["dataset"].annotation, str)
        self.assertIs(signature.parameters["source_file"].annotation, str)
        self.assertIs(signature.parameters["line_id"].annotation, int)


if __name__ == "__main__":
    unittest.main()
