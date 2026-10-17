"""Small real-server COPY round-trip test; creates and removes its own probe table."""
from pathlib import Path
from uuid import uuid4
import base64
from db import execute, records, copy_rows
from load_logs import COMMON, EXTRA, parse_line

if __name__ == '__main__':
    table = 'loader_probe_' + uuid4().hex
    schema = (Path(__file__).resolve().parents[1] / 'sql/schema.sql').read_text()
    statement = schema.split(';')[1].replace('openstack_logs', table)
    execute(statement)
    try:
        text = 'nova.log 2017-05-14 19:39:02.007 2931 ERROR nova.driver [req-abcd-1234 x] [instance: vm-123] tab\there \\N and \\path'
        text += '\x00\x0f\x10'
        row = parse_line('openstack', text, 'probe.log', 1)
        bad = parse_line('openstack', 'unparsed continuation', 'probe.log', 2)
        copy_rows(table, COMMON + EXTRA['openstack'], [row, bad])
        actual = records('SELECT raw_text, raw_text_base64, request_id, parse_ok FROM ' + table + ' ORDER BY line_id')
        assert len(actual) == 2, actual
        assert actual[0]['raw_text'] == text.replace('\x00', r'\u0000'), actual
        assert base64.b64decode(actual[0]['raw_text_base64']).decode('utf-8') == text
        assert actual[0]['request_id'] == 'req-abcd-1234', actual
        assert actual[1]['parse_ok'] in ('f', 'false'), actual
        print('Real-server COPY round-trip passed, including escaped text and unparsed rows')
    finally:
        execute('DROP TABLE ' + table)
