import unittest
import base64
from scripts.load_logs import parse_line
from scripts.db import copy_value


class ParserTests(unittest.TestCase):
    def test_nul_original_is_recoverable(self):
        text = 'nova.log 2017-05-14 19:39:02.007 2931 ERROR nova.driver before\x00after'
        row = parse_line('openstack', text, 'a.log', 1)
        self.assertTrue(row['parse_ok'])
        self.assertEqual(base64.b64decode(row['raw_text_base64']).decode('utf-8'), text)
        self.assertEqual(row['content'], r'before\u0000after')

    def test_copy_null_and_literal_backslash_are_distinct(self):
        self.assertEqual(copy_value(None), r'\N')
        self.assertEqual(copy_value(r'\N'), r'\\N')
        self.assertEqual(copy_value('a\tb\n'), r'a\011b\012')

    def test_bgl_content_and_microseconds(self):
        line = '- 1117838570 2005.06.03 NODE 2005-06-03-15.42.50.363779 NODE RAS KERNEL INFO parity error corrected'
        row = parse_line('bgl', line, 'BGL.log', 7)
        self.assertTrue(row['parse_ok'])
        self.assertEqual(row['event_time'].microsecond, 363779)
        self.assertEqual(row['content'], 'parity error corrected')
        self.assertEqual(row['raw_text'], line)
        self.assertEqual(row['line_id'], 7)

    def test_openstack_context(self):
        row = parse_line('openstack', 'nova.log 2017-05-14 19:39:02.007 2931 INFO nova.driver [req-abcd-1234 x] [instance: vm-123] Creating image', 'a.log', 1)
        self.assertTrue(row['parse_ok'])
        self.assertEqual(row['request_id'], 'req-abcd-1234')
        self.assertEqual(row['instance_id'], 'vm-123')
        self.assertEqual(row['pid'], 2931)

    def test_continuation_preserved(self):
        text = '  Traceback continuation without header'
        row = parse_line('openstack', text, 'a.log', 2)
        self.assertFalse(row['parse_ok'])
        self.assertEqual(row['raw_text'], text)
        self.assertIsNone(row['event_time'])

    def test_invalid_date_is_reported(self):
        row = parse_line('openstack', 'nova.log 2017-99-14 19:39:02.007 2931 ERROR nova.driver bad', 'a.log', 3)
        self.assertFalse(row['parse_ok'])

    def test_empty_contents(self):
        bgl = parse_line('bgl', '- 1117838570 2005.06.03 NODE 2005-06-03-15.42.50.363779 NODE RAS KERNEL FATAL', 'a', 1)
        cloud = parse_line('openstack', 'nova.log 2017-05-14 19:39:02.007 2931 ERROR nova.driver', 'b', 1)
        self.assertTrue(bgl['parse_ok'])
        self.assertTrue(cloud['parse_ok'])
        self.assertEqual(bgl['content'], '')
        self.assertEqual(cloud['content'], '')

    def test_missing_repeated_node(self):
        row = parse_line('bgl', '- 1119415930 2005.06.21 - 2005-06-21-21.52.10.214285 RAS KERNEL FATAL Kill job timed out.', 'a', 1)
        self.assertTrue(row['parse_ok'])
        self.assertEqual(row['level'], 'FATAL')
        self.assertEqual(row['content'], 'Kill job timed out.')

    def test_corrupt_header_not_misclassified(self):
        row = parse_line('bgl', '- 1133447861 2005.12.01 - 2005-12-01-06.37.41.417709 time for a single instance RAS KERNEL INFO text', 'a', 1)
        self.assertFalse(row['parse_ok'])


if __name__ == '__main__':
    unittest.main()
