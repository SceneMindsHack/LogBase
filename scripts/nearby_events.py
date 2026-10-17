"""Show the log lines before and after a chosen line.

Pick the center line either by time, or by (source_file, line_id).
Shows lines within +/- N minutes of it.

If there are more lines than the limit, you get half from before and half
from after, closest first. total_matches still counts every line in the
window, and truncated tells you if some were left out.

For BGL, lines are limited to the same node as the center line.
Use --all-nodes to see all nodes.

Examples:
    python scripts/nearby_events.py --dataset bgl --source-file BGL.log --line-id 500000 --window 5 --limit 10

    python scripts/nearby_events.py --dataset bgl --time 2005-06-03T15:42:50 --window 5
    
    python scripts/nearby_events.py --dataset openstack --source-file openstack_abnormal.log --line-id 1000

Options: --window (minutes each side, default 5), --limit (2 to 100, default 10),
--node (BGL only), --component, --all-nodes.

Output is JSON: total_matches, returned, truncated, the SQL that ran, and the
rows in time order. The center line is marked is_anchor.
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
# node only exists on bgl_logs; see sql/schema.sql and the README data contract.
NODE_DATASETS = ('bgl',)
PREVIEW_LIMIT = 500


def anchor_from_identity(dataset, source_file, line_id):
    columns = (f'source_file, line_id, event_time, level, component, '
               f'LEFT(content, {PREVIEW_LIMIT}) AS content_preview'
               + (', node' if dataset in NODE_DATASETS else ''))
    sql = (f'SELECT {columns} FROM {dataset}_logs '
           f'WHERE source_file = {literal(source_file)} AND line_id = {literal(line_id)} '
           f'ORDER BY source_file, line_id LIMIT 2')
    rows = records(sql)
    if not rows:
        raise ValueError(
            f'No log row found for {dataset}/{source_file}/{line_id}')
    if len(rows) > 1:
        raise RuntimeError(
            'Duplicate log identity detected for '
            f'{dataset}/{source_file}/{line_id}; expected exactly one row')
    row = rows[0]
    node = row.get('node') or None
    evidence = {key: row.get(key) for key in (
        'source_file', 'line_id', 'event_time', 'level', 'component',
        'content_preview')}
    return row['event_time'], node, row['source_file'], evidence, sql


def validate(dataset, window_minutes, limit, node):
    if dataset not in DATASETS:
        raise ValueError('Unknown dataset')
    window_minutes, limit = int(window_minutes), int(limit)
    if not 2 <= limit <= 100:
        raise ValueError('Limit must be between 2 and 100')
    if not 1 <= window_minutes <= 1440:
        raise ValueError('Window must be between 1 and 1440 minutes')
    if node and dataset not in NODE_DATASETS:
        raise ValueError('node filter is only available for the bgl dataset')
    return window_minutes, limit


def parse_anchor_time(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo:
        raise ValueError('Use source-local timestamps without timezone offsets')
    return parsed


def _ordering_bound(side, anchor_literal, anchor_source_file=None,
                    anchor_line_id=None):
    """Partition rows around an anchor using the result ordering key."""
    if anchor_source_file is None or anchor_line_id is None:
        return ('event_time <= ' if side == 'before' else 'event_time > ') + anchor_literal

    comparison = '<' if side == 'before' else '>'
    file_literal = literal(anchor_source_file)
    line_literal = literal(anchor_line_id)
    return (
        f'(event_time {comparison} {anchor_literal} OR '
        f'(event_time = {anchor_literal} AND '
        f'(source_file {comparison} {file_literal} OR '
        f'(source_file = {file_literal} AND line_id {comparison} {line_literal}))))'
    )


def side_sql(dataset, filters, side, half, anchor_literal,
             anchor_source_file=None, anchor_line_id=None):
    """One side of the anchor, ordered closest-first for selection."""
    if side == 'before':
        order = 'event_time DESC, source_file DESC, line_id DESC'
    else:
        order = 'event_time ASC, source_file ASC, line_id ASC'
    bound = _ordering_bound(
        side, anchor_literal, anchor_source_file, anchor_line_id)
    where = ' AND '.join(filters + [bound])
    return (f'SELECT source_file, line_id, event_time, level, component, '
            f'LEFT(content, {PREVIEW_LIMIT}) AS content_preview FROM {dataset}_logs '
            f'WHERE {where} ORDER BY {order} LIMIT {half}')


def query_sql(dataset, anchor_time, window_minutes, limit, node=None, component=None,
              source_file=None, anchor_line_id=None):
    window_minutes, limit = validate(dataset, window_minutes, limit, node)
    window = timedelta(minutes=window_minutes)
    low, high = anchor_time - window, anchor_time + window
    filters = ['event_time >= ' + literal(low), 'event_time <= ' + literal(high)]
    if component:
        filters.append('component = ' + literal(component))
    if node:
        filters.append('node = ' + literal(node))
    # OpenStack capture files hold disjoint time spans; scope the window to the
    # anchor's file when we know it, so a window never mixes capture sessions.
    if source_file and dataset == 'openstack':
        filters.append('source_file = ' + literal(source_file))
    anchor_literal = literal(anchor_time)
    before_half = limit // 2
    after_half = limit - before_half
    identity_anchor = source_file is not None and anchor_line_id is not None
    count_where = ' AND '.join(filters)
    if identity_anchor:
        anchor_identity = (
            f'source_file = {literal(source_file)} AND '
            f'line_id = {literal(anchor_line_id)}')
        # The anchor is always part of identity-based output, even when optional
        # context filters do not match it. Count it once alongside filtered context.
        count_where = (
            f'({anchor_identity}) OR '
            f'(({count_where}) AND NOT ({anchor_identity}))')
        # The old split counted the anchor in the before half. Reserve that slot
        # explicitly so the maximum returned row count and side balance stay stable.
        before_half -= 1
    count = (f'SELECT COUNT(*) AS matches FROM {dataset}_logs '
             f'WHERE {count_where}')
    before = side_sql(dataset, filters, 'before', before_half, anchor_literal,
                      source_file if identity_anchor else None,
                      anchor_line_id if identity_anchor else None)
    after = side_sql(dataset, filters, 'after', after_half, anchor_literal,
                     source_file if identity_anchor else None,
                     anchor_line_id if identity_anchor else None)
    return count, before, after


def nearby(dataset, window_minutes, limit, anchor_time=None, source_file=None,
           line_id=None, node=None, component=None, all_nodes=False):
    if dataset not in DATASETS:
        raise ValueError('Unknown dataset')
    if all_nodes and node:
        raise ValueError('Use either --node or --all-nodes, not both')
    window_minutes, limit = int(window_minutes), int(limit)
    identity_sql = None
    anchor_file = None
    anchor_line = None
    anchor_evidence = None
    if anchor_time is None:
        if source_file is None or line_id is None:
            raise ValueError('Provide --time, or both --source-file and --line-id')
        line_id = int(line_id)
        (anchor_time, found_node, anchor_file, anchor_evidence,
         identity_sql) = anchor_from_identity(dataset, source_file, line_id)
        anchor_line = line_id
        if node is None and not all_nodes:
            node = found_node
    elif source_file is not None or line_id is not None:
        raise ValueError('Use --time or source identity, not both')
    if isinstance(anchor_time, str):
        anchor_time = parse_anchor_time(anchor_time)

    count_sql, before_sql, after_sql = query_sql(
        dataset, anchor_time, window_minutes, limit, node, component,
        source_file=anchor_file, anchor_line_id=anchor_line)
    started = time.perf_counter()
    total = int(records(count_sql)[0]['matches'])
    before_rows = records(before_sql)
    after_rows = records(after_sql)
    # Selection was closest-first per side; present the whole window in time order.
    if anchor_evidence is not None:
        anchor_evidence['is_anchor'] = True
        for row in before_rows + after_rows:
            row['is_anchor'] = False
    evidence = sorted(before_rows + ([anchor_evidence] if anchor_evidence else []) + after_rows,
                      key=lambda r: (r['event_time'], r['source_file'], int(r['line_id'])))
    sql = ([identity_sql] if identity_sql else []) + [count_sql, before_sql, after_sql]
    return {'dataset': dataset, 'anchor_time': anchor_time.isoformat(),
            'window_minutes': window_minutes, 'window_bounds_inclusive': True,
            'anchor_source_file': anchor_file, 'anchor_line_id': anchor_line,
            'node': node, 'component': component, 'total_matches': total,
            'returned': len(evidence), 'truncated': total > len(evidence),
            'content_preview_limit': PREVIEW_LIMIT,
            'elapsed_seconds': round(time.perf_counter() - started, 3),
            'sql': sql, 'evidence': evidence}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', choices=DATASETS, required=True)
    parser.add_argument('--time', help='Source-local ISO datetime anchor (no timezone)')
    parser.add_argument('--source-file', help='Anchor by identity: source_file (with --line-id)')
    parser.add_argument('--line-id', type=int, help='Anchor by identity: line_id (with --source-file)')
    parser.add_argument('--window', type=int, default=5, help='Window in minutes, inclusive both ends')
    parser.add_argument('--node', help='Filter by node (bgl only)')
    parser.add_argument('--all-nodes', action='store_true',
                        help='When anchoring by identity on bgl, do not auto-filter to the '
                             'anchor row\'s node; show every node in the window. Default keeps '
                             'the same-node filter.')
    parser.add_argument('--component', help='Filter by component')
    parser.add_argument('--limit', type=int, default=10, help='Max rows returned; split before/after the anchor')
    args = parser.parse_args()
    if args.time is None and (args.source_file is None or args.line_id is None):
        parser.error('Provide --time, or both --source-file and --line-id')
    print(json.dumps(nearby(args.dataset, args.window, args.limit, anchor_time=args.time,
                             source_file=args.source_file, line_id=args.line_id,
                             node=args.node, component=args.component,
                             all_nodes=args.all_nodes), indent=2))
