"""Trend tool: counts of matching log lines bucketed by day or week.

Reliable counts over time, not an anomaly detector. One row is one physical log
line, not an incident, request, or affected user. A zero bucket means no matching
lines were observed, not that a service was healthy or that logging worked.
"""
import argparse
from datetime import datetime, timedelta
import json
import time

try:
    from .db import records, literal
except ImportError:
    from db import records, literal

DATASETS = ('bgl', 'openstack')
# Interval name -> (date_trunc keyword, verified Monday-start for 'week').
INTERVALS = {'day': 'day', 'week': 'week'}
MAX_BUCKETS = 400


def _parse_local(value, label):
    """Parse a source-local ISO timestamp, rejecting timezone offsets."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo:
        raise ValueError(f'{label} must be a source-local timestamp without a timezone offset')
    return parsed


def _bucket_starts(interval, start, end):
    """Expected bucket starts covering [start, end), chronological, inclusive of
    the bucket containing start up to (excluding) end. Weeks start on Monday."""
    if interval == 'day':
        current = start.replace(hour=0, minute=0, second=0, microsecond=0)
        step = lambda d: d + timedelta(days=1)
    else:  # week, Monday-start
        midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
        current = midnight - timedelta(days=midnight.weekday())
        step = lambda d: d + timedelta(days=7)
    buckets = []
    while current < end:
        buckets.append(current)
        current = step(current)
    return buckets


def _expected_bucket_count(interval, start, end):
    return len(_bucket_starts(interval, start, end))


def query_sql(dataset, interval, start, end, level=None, component=None):
    """Build (count_sql, bucket_sql) for the validated inputs. No execution.

    Identifiers (table, bucket keyword) come from fixed allowlists; only data
    values are interpolated, and those go through literal() for safe quoting.
    """
    if dataset not in DATASETS:
        raise ValueError('Unknown dataset; choose bgl or openstack')
    if interval not in INTERVALS:
        raise ValueError('Unknown interval; choose day or week')
    start_dt = _parse_local(start, 'start')
    end_dt = _parse_local(end, 'end')
    if start_dt >= end_dt:
        raise ValueError('start must precede end')

    expected = _expected_bucket_count(interval, start_dt, end_dt)
    if expected > MAX_BUCKETS:
        raise ValueError(
            f'Requested range spans {expected} {interval} buckets; the limit is '
            f'{MAX_BUCKETS}. Narrow the range or widen the interval.')

    keyword = INTERVALS[interval]
    table = dataset + '_logs'
    filters = [
        'event_time >= ' + literal(start_dt),
        'event_time < ' + literal(end_dt),
        'event_time IS NOT NULL',
    ]
    if level is not None:
        filters.append('level = ' + literal(level))
    if component is not None:
        filters.append('component = ' + literal(component))
    where = ' AND '.join(filters)

    bucket_expr = f"date_trunc({literal(keyword)}, event_time)"
    count_sql = f'SELECT COUNT(*) AS matches FROM {table} WHERE {where}'
    bucket_sql = (f'SELECT {bucket_expr} AS bucket, COUNT(*) AS count '
                  f'FROM {table} WHERE {where} GROUP BY bucket ORDER BY bucket')
    return count_sql, bucket_sql


def _zero_fill(interval, start_dt, end_dt, observed):
    """Return chronological buckets with 0 for intervals that had no rows."""
    counts = {}
    for row in observed:
        key = datetime.fromisoformat(row['bucket']).replace(tzinfo=None)
        counts[key] = counts.get(key, 0) + int(row['count'])
    return [{'bucket_start': b.isoformat(), 'count': counts.get(b, 0)}
            for b in _bucket_starts(interval, start_dt, end_dt)]


def trend(dataset, interval, start, end, level=None, component=None):
    """Count matching log lines per day/week over [start, end).

    A database error propagates as an exception; it is never reported as an empty
    trend. No matching rows is a valid, separate outcome (all-zero buckets).
    """
    count_sql, bucket_sql = query_sql(dataset, interval, start, end, level, component)
    start_dt = _parse_local(start, 'start')
    end_dt = _parse_local(end, 'end')
    started = time.perf_counter()

    total = int(records(count_sql)[0]['matches'])
    observed = records(bucket_sql)
    buckets = _zero_fill(interval, start_dt, end_dt, observed)

    bucket_sum = sum(b['count'] for b in buckets)
    if bucket_sum != total:
        raise RuntimeError(
            f'Reconciliation failed: bucket counts sum to {bucket_sum} but a '
            f'separate COUNT(*) returned {total} for the same filters/range.')

    return {
        'dataset': dataset,
        'interval': interval,
        'start_inclusive': start_dt.isoformat(),
        'end_exclusive': end_dt.isoformat(),
        'effective_filters': {'level': level, 'component': component},
        'buckets': buckets,
        'total_timed_matches': total,
        'bucket_count': len(buckets),
        'elapsed_seconds': round(time.perf_counter() - started, 3),
        'sql': [count_sql, bucket_sql],
        'limitations': [
            'Counts are log lines, not incidents, requests, or affected users.',
            'A zero bucket means no matching lines were observed, not that a '
            'service was healthy or that logging was operational.',
            'Rows with a null event_time (including malformed lines) are excluded '
            'from the time aggregation.',
            'First and last buckets may be partial when start or end falls '
            'mid-interval.',
            'BGL and OpenStack cover different years and are never combined.',
        ],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', choices=DATASETS, required=True)
    parser.add_argument('--interval', choices=tuple(INTERVALS), default='day')
    parser.add_argument('--start', required=True, help='Source-local ISO datetime, inclusive')
    parser.add_argument('--end', required=True, help='Source-local ISO datetime, exclusive')
    parser.add_argument('--level', help='Exact match on the level column (e.g. ERROR)')
    parser.add_argument('--component', help='Exact match on the component column')
    args = parser.parse_args()
    print(json.dumps(trend(args.dataset, args.interval, args.start, args.end,
                           args.level, args.component), indent=2))
