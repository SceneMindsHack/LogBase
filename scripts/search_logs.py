"""Full-text index setup and bounded search, adapted from Hazal's fts_demo.py."""
import argparse
from datetime import datetime
import json
import time

try:
    from .db import execute, records, literal
except ImportError:
    from db import execute, records, literal

DICTIONARY = 'logbase_words'
DATASETS = ('bgl', 'openstack')


def setup(dataset):
    if not records("SELECT dictname FROM pg_ts_dict WHERE dictname = 'logbase_words'"):
        execute("CREATE TEXT SEARCH DICTIONARY logbase_words AS "
                "split_text(case := 'lower') | normalize_tokens('en_US.UTF-8', accent := false) "
                "WITH (frequency, position, offset)")
    table, index = dataset + '_logs', dataset + '_logs_fts'
    if not records('SELECT indexname FROM pg_indexes WHERE indexname = ' + literal(index)):
        execute(f'CREATE INDEX {index} ON {table} USING inverted '
                '(source_file, line_id, event_time, level, component, content logbase_words) INCLUDE (content)')
    started = time.perf_counter()
    execute(f'VACUUM (REFRESH_TABLE) {table}')
    print(f'{index}: ready; refresh took {time.perf_counter() - started:.2f}s', flush=True)


def query_sql(dataset, query, limit=10, since=None, until=None):
    if dataset not in DATASETS:
        raise ValueError('Unknown dataset')
    if not 1 <= limit <= 100:
        raise ValueError('Limit must be between 1 and 100')
    if not query.strip() or len(query) > 1000:
        raise ValueError('Query must contain 1 to 1000 characters')
    filters = ['content @@ ' + literal(query)]
    for value, operator in ((since, '>='), (until, '<')):
        if value:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo:
                raise ValueError('Use source-local timestamps without timezone offsets')
            filters.append('event_time ' + operator + ' ' + literal(parsed))
    if since and until and datetime.fromisoformat(since) >= datetime.fromisoformat(until):
        raise ValueError('--since must precede --until')
    where = ' AND '.join(filters)
    count = f'SELECT COUNT(*) AS matches FROM {dataset}_logs_fts WHERE {where}'
    evidence = (f'SELECT source_file, line_id, event_time, level, component, '
                f'LEFT(content, 500) AS content_preview FROM {dataset}_logs_fts WHERE {where} '
                f'ORDER BY event_time, source_file, line_id LIMIT {limit}')
    return count, evidence


def search(dataset, query, limit, since=None, until=None):
    count_sql, evidence_sql = query_sql(dataset, query, limit, since, until)
    started = time.perf_counter()
    count = int(records(count_sql)[0]['matches'])
    evidence = records(evidence_sql)
    return {'dataset': dataset, 'query': query, 'since_inclusive': since,
            'until_exclusive': until, 'total_matches': count, 'returned': len(evidence),
            'truncated': count > len(evidence), 'content_preview_limit': 500,
            'elapsed_seconds': round(time.perf_counter() - started, 3),
            'sql': [count_sql, evidence_sql], 'evidence': evidence}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', choices=('all',) + DATASETS, default='all')
    parser.add_argument('--setup', action='store_true', help='Create missing indexes and refresh; never drop tables/indexes')
    parser.add_argument('--query')
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--since', help='Source-local ISO datetime, inclusive')
    parser.add_argument('--until', help='Source-local ISO datetime, exclusive')
    args = parser.parse_args()
    if not args.setup and args.query is None:
        parser.error('Choose --setup, --query, or both')
    datasets = DATASETS if args.dataset == 'all' else (args.dataset,)
    if args.query is not None:
        for dataset in datasets:
            query_sql(dataset, args.query, args.limit, args.since, args.until)
    for dataset in datasets:
        if args.setup:
            setup(dataset)
        if args.query is not None:
            print(json.dumps(search(dataset, args.query, args.limit, args.since, args.until), indent=2))
