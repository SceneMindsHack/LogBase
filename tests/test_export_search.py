import base64
import csv
import tempfile
import unittest
from pathlib import Path
from scripts.export_csv import export
from scripts.search_logs import query_sql


class ExportSearchTests(unittest.TestCase):
    def test_csv_preserves_evidence_and_flagged_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'openstack_abnormal.log'
            original = 'nova.log 2017-05-14 19:39:02.007 2931 ERROR nova.driver [req-abcd] comma, quote" before\x00after'
            source.write_text(original + '\ninvalid header\n', encoding='utf-8')
            target = root / 'export.csv'
            self.assertEqual(export('openstack', [source], target), (2, 1))
            with target.open(encoding='utf-8', newline='') as stream:
                records = list(csv.DictReader(stream))
            self.assertEqual(base64.b64decode(records[0]['raw_text_base64']).decode(), original)
            self.assertEqual(records[0]['source_file'], source.name)
            self.assertEqual(records[1]['line_id'], '2')
            self.assertEqual(records[1]['parse_ok'], 'False')
            with self.assertRaises(FileExistsError):
                export('openstack', [source], target)

    def test_search_quotes_input_and_limits_evidence(self):
        count, evidence = query_sql('bgl', "error' OR true --", 7)
        self.assertIn("'error'' OR true --'", count)
        self.assertTrue(evidence.endswith('LIMIT 7'))
        self.assertIn('source_file, line_id', evidence)

    def test_search_rejects_invalid_scope(self):
        with self.assertRaises(ValueError):
            query_sql('bgl', 'error', 1000)
        with self.assertRaises(ValueError):
            query_sql('bgl; DROP TABLE x', 'error')
        with self.assertRaises(ValueError):
            query_sql('bgl', 'error', since='2020-01-02', until='2020-01-01')
        with self.assertRaises(ValueError):
            query_sql('openstack', 'error', since='2017-01-01T00:00:00Z')


if __name__ == '__main__':
    unittest.main()
