"""Parse local BGL/OpenStack files and optionally stream them into SereneDB.

Default mode only validates files. Database writes require --load.
Every physical line becomes a row; unmatched lines retain their original text.
"""
import argparse
import base64
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

COMMON = ('source_file', 'line_id', 'event_time', 'level', 'component',
          'content', 'raw_text', 'parse_ok', 'parse_error', 'event_id', 'event_template', 'raw_text_base64')
EXTRA = {
    'bgl': ('label', 'epoch_seconds', 'node', 'log_type'),
    'openstack': ('log_record', 'pid', 'request_id', 'instance_id', 'correlation_data'),
}
OPENSTACK = re.compile(
    r'^(?P<log_record>\S+)\s+(?P<event_time>\d{4}-\d{2}-\d{2} '
    r'\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+(?P<pid>\d+)\s+'
    r'(?P<level>[A-Z]+)\s+(?P<component>\S+)(?:\s+(?P<content>.*))?$')
REQUEST = re.compile(r'\breq-[0-9a-fA-F-]+\b')
INSTANCE = re.compile(r'\[instance:\s*([^\]\s]+)\]')


def parse_line(dataset, text, source, line_id):
    row = dict.fromkeys(COMMON + EXTRA[dataset])
    row.update(source_file=source, line_id=line_id, raw_text=text,
               content=text, parse_ok=False)
    try:
        if dataset == 'bgl':
            parts = text.split(maxsplit=9)
            # Some records omit the repeated node field; do not shift level.
            if len(parts) > 5 and parts[5] == 'RAS':
                parts = text.split(maxsplit=8)
                parts.insert(5, '-')
            if len(parts) == 9:
                parts.append('')
            if len(parts) != 10:
                raise ValueError('Expected BGL header fields')
            label, epoch, date, node, stamp, repeated_node, log_type, component, level, content = parts
            if log_type not in ('RAS', 'NULL') or level not in (
                    'INFO', 'FATAL', 'WARNING', 'SEVERE', 'ERROR', 'FAILURE',
                    'DEBUG', 'TRACE', 'WARN', 'CRITICAL'):
                raise ValueError('Unrecognized BGL header; possible corrupted field')
            event_time = datetime.strptime(stamp, '%Y-%m-%d-%H.%M.%S.%f')
            row.update(event_time=event_time, label=label,
                       epoch_seconds=int(epoch), node=node, log_type=log_type,
                       component=component, level=level, content=content)
        else:
            match = OPENSTACK.match(text)
            if not match:
                raise ValueError('Unrecognized OpenStack header or continuation line')
            fields = match.groupdict()
            fields['content'] = fields['content'] or ''
            fields['event_time'] = datetime.fromisoformat(fields['event_time'])
            fields['pid'] = int(fields['pid'])
            request = REQUEST.search(fields['content'])
            instance = INSTANCE.search(fields['content'])
            row['correlation_data'] = fields['content'].split(']', 1)[0] + ']' if fields['content'].startswith('[') else None
            row.update(fields, request_id=request.group(0) if request else None,
                       instance_id=instance.group(1) if instance else None)
        row['parse_ok'] = True
    except (ValueError, OverflowError) as error:
        row['parse_error'] = str(error)
    if '\x00' in text:
        # psql's text output truncates at NUL. Keep a reversible original alongside
        # a readable display version rather than silently losing message suffixes.
        row['raw_text_base64'] = base64.b64encode(text.encode('utf-8')).decode('ascii')
        row['raw_text'] = text.replace('\x00', r'\u0000')
        row['content'] = row['content'].replace('\x00', r'\u0000')
    return row


def rows(dataset, path):
    # Strict decoding prevents silent replacement of original characters.
    with path.open('r', encoding='utf-8', newline='') as source:
        for number, line in enumerate(source, 1):
            yield parse_line(dataset, line.rstrip('\r\n'), path.name, number)


def scan(dataset, paths):
    report = {'dataset': dataset, 'total_lines': 0, 'parsed_lines': 0,
              'unparsed_lines': 0, 'files': [], 'level_counts': {},
              'component_counts': {}, 'unparsed_examples': []}
    severities, components = Counter(), Counter()
    earliest = latest = None
    for path in paths:
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        count = 0
        for row in rows(dataset, path):
            count += 1
            report['total_lines'] += 1
            if report['total_lines'] % 500000 == 0:
                print(f'Validating {dataset}: {report["total_lines"]:,} lines', flush=True)
            report['parsed_lines' if row['parse_ok'] else 'unparsed_lines'] += 1
            if row['parse_ok']:
                severities[row['level']] += 1
                components[row['component']] += 1
                stamp = row['event_time']
                earliest = stamp if earliest is None else min(earliest, stamp)
                latest = stamp if latest is None else max(latest, stamp)
            elif len(report['unparsed_examples']) < 10:
                report['unparsed_examples'].append({key: row[key] for key in
                    ('source_file', 'line_id', 'parse_error')})
        report['files'].append({'name': path.name, 'lines': count,
                                'sha256': digest.hexdigest()})
        print(f'Validated {path.name}: {count:,} lines', flush=True)
    report['level_counts'] = dict(severities)
    report['component_counts'] = dict(components)
    report['first_event_time'] = earliest.isoformat() if earliest else None
    report['last_event_time'] = latest.isoformat() if latest else None
    return report


def load(datasets, reports):
    from db import execute, records, copy_rows
    schema = (Path(__file__).resolve().parents[1] / 'sql' / 'schema.sql').read_text(encoding='utf-8')
    execute(schema)
    # Check all selected tables before writing any rows.
    for dataset in datasets:
        table = dataset + '_logs'
        execute('SELECT ' + ','.join(COMMON + EXTRA[dataset]) + ' FROM ' + table + ' LIMIT 0')
        if int(records('SELECT COUNT(*) AS n FROM ' + table)[0]['n']):
            raise RuntimeError(f'{table} already contains data; refusing to append. Use --dataset for an unloaded dataset.')
    for dataset, paths in datasets.items():
        table = dataset + '_logs'
        def stream():
            count = 0
            for path in paths:
                for row in rows(dataset, path):
                    yield row
                    count += 1
                    if count % 250000 == 0:
                        print(f'Sent {dataset}: {count:,} rows', flush=True)
        copy_rows(table, COMMON + EXTRA[dataset], stream())
        result = records('SELECT COUNT(*) AS total, '
                         'SUM(CASE WHEN parse_ok THEN 1 ELSE 0 END) AS parsed, '
                         'MIN(event_time) AS first, MAX(event_time) AS last FROM ' + table)[0]
        expected = reports[dataset]
        if int(result['total']) != expected['total_lines'] or int(result['parsed'] or 0) != expected['parsed_lines']:
            raise RuntimeError(f'{table}: committed row counts differ from input; inspect before proceeding')
        for field, expected_field in [('first', 'first_event_time'), ('last', 'last_event_time')]:
            actual = datetime.fromisoformat(result[field]).isoformat() if result[field] else None
            if actual != expected[expected_field]:
                raise RuntimeError(f'{table}: committed timestamp range differs from input')
        levels = records('SELECT level, COUNT(*) AS n FROM ' + table + ' WHERE parse_ok GROUP BY level')
        if {row['level']: int(row['n']) for row in levels} != expected['level_counts']:
            raise RuntimeError(f'{table}: committed severity totals differ from input')
        duplicate = records('SELECT COUNT(*) AS n FROM (SELECT source_file, line_id FROM ' + table +
                            ' GROUP BY source_file, line_id HAVING COUNT(*) > 1) duplicates')[0]
        if int(duplicate['n']):
            raise RuntimeError(f'{table}: duplicate source identities')
        expected['database_verification'] = result
        print(f'Loaded and verified {dataset}: {result["total"]} rows', flush=True)


def input_files(root, dataset='all'):
    datasets = {
        'bgl': [root / 'BGL' / 'BGL.log'],
        'openstack': [root / 'OpenStack' / name for name in
                      ('openstack_normal1.log', 'openstack_normal2.log', 'openstack_abnormal.log')],
    }
    if dataset != 'all':
        datasets = {dataset: datasets[dataset]}
    for paths in datasets.values():
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(f'Missing input: {path}')
    return datasets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True,
                        help='Folder containing BGL and OpenStack directories')
    parser.add_argument('--dataset', choices=('all', 'bgl', 'openstack'), default='all')
    parser.add_argument('--report', type=Path, default=Path('reports/load-report.json'))
    parser.add_argument('--load', action='store_true', help='Write validated data to SereneDB')
    args = parser.parse_args()
    datasets = input_files(args.data_root, args.dataset)
    reports = {dataset: scan(dataset, paths) for dataset, paths in datasets.items()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(reports, indent=2), encoding='utf-8')
    if args.load:
        try:
            load(datasets, reports)
        finally:
            args.report.write_text(json.dumps(reports, indent=2), encoding='utf-8')
    print(f'Report: {args.report.resolve()}', flush=True)


if __name__ == '__main__':
    main()
