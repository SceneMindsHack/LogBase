"""Data overview: what data exists, how much of it, and which filter values are valid.

PURPOSE
    Call this first, before searching or counting. It tells an agent (or a person)
    what is in the database, so later tools are called with real values instead
    of guesses such as a component name that does not exist.

WHAT IT RETURNS (per dataset: bgl, openstack)
    row_count            Total log lines. One row is one physical log line,
                         not one incident.
    first_event,         The time range covered, in source-local time (no
    last_event           timezone is assumed).
    invalid_timestamps   Rows whose timestamp could not be read.
    parse_failures       Rows whose header could not be parsed. They are kept
                         in the data, not dropped.
    source_files         How many log files the dataset was loaded from.
    distinct_components  Number of named components (blank ones not counted).
    has_node_column      True for bgl, False for openstack. Tells the agent
                         whether it can filter by node.
    levels               Row count per level (severity), for example INFO,
                         ERROR, FATAL. Use these exact values as filters.
    teams                Row count per owning team, from the ownership table.
    components           Every component with its owning team and row count.
    sql                  The exact queries that produced these numbers, so
                         every figure can be checked.

THINGS TO KNOW
    - Unmatched components appear under the team 'Unassigned' (see the README
      data contract).
    - Blank level or blank component values are shown as null.
    - Component lists are returned in full, since both datasets have few
      components. BGL has 10 named components plus one null entry for the 10 malformed rows. OpenStack has 12.
    - BGL (2005-2006) and OpenStack (2017) cover different periods, so their
      timestamps should not be compared with each other.
    - This tool only reads data. It never changes anything.

EXAMPLE USE
    python scripts/data_overview.py                      # both datasets
    python scripts/data_overview.py --dataset bgl        # only bgl

    Example question it answers: "What levels exist in OpenStack, and how many
    ERROR lines are there?"
    -> levels shows INFO 204,506, WARNING 3,118, ERROR 194 and CRITICAL 2, so
       a follow-up search can filter on level ERROR, and count_by can group
       those 194 lines by component.
"""
import argparse
import json
import time

try:
    from .db import records, literal
except ImportError:
    from db import records, literal

DATASETS = ('bgl', 'openstack')


def scope_sql(dataset):
    return (f"SELECT COUNT(*) AS row_count, MIN(event_time) AS first_event, "
            f"MAX(event_time) AS last_event, "
            f"SUM(CASE WHEN event_time IS NULL THEN 1 ELSE 0 END) AS invalid_timestamps, "
            f"SUM(CASE WHEN parse_ok THEN 0 ELSE 1 END) AS parse_failures, "
            f"COUNT(DISTINCT source_file) AS source_files, "
            f"COUNT(DISTINCT component) AS distinct_components FROM {dataset}_logs")


def levels_sql(dataset):
    # Empty/NULL level is reported as null rather than hidden; blank marks malformed headers.
    return (f"SELECT level, COUNT(*) AS count FROM {dataset}_logs "
            f"GROUP BY level ORDER BY count DESC, level")


def components_sql(dataset):
    return (f"SELECT l.component, COALESCE(o.team, 'Unassigned') AS team, "
            f"COUNT(*) AS count FROM {dataset}_logs l "
            f"LEFT JOIN component_ownership o "
            f"ON o.dataset = {literal(dataset)} AND o.component = l.component "
            f"GROUP BY l.component, o.team ORDER BY count DESC, l.component")


def teams_sql(dataset):
    return (f"SELECT COALESCE(o.team, 'Unassigned') AS team, COUNT(*) AS count "
            f"FROM {dataset}_logs l "
            f"LEFT JOIN component_ownership o "
            f"ON o.dataset = {literal(dataset)} AND o.component = l.component "
            f"GROUP BY o.team ORDER BY count DESC, team")


def overview_one(dataset):
    if dataset not in DATASETS:
        raise ValueError('Unknown dataset')
    scope_q = scope_sql(dataset)
    levels_q = levels_sql(dataset)
    components_q = components_sql(dataset)
    teams_q = teams_sql(dataset)
    scope = records(scope_q)[0]
    levels = records(levels_q)
    components = records(components_q)
    teams = records(teams_q)
    return {
        'dataset': dataset,
        'row_count': int(scope['row_count']),
        'first_event': scope['first_event'] or None,
        'last_event': scope['last_event'] or None,
        'invalid_timestamps': int(scope['invalid_timestamps']),
        'parse_failures': int(scope['parse_failures']),
        'source_files': int(scope['source_files']),
        'distinct_components': int(scope['distinct_components']),
        'has_node_column': dataset == 'bgl',
        'notes': ('Each row is one physical log line, not an incident. BGL and '
                  'OpenStack cover different periods, so do not compare their '
                  'timestamps directly.'),
        'levels': [{'level': r['level'] or None, 'count': int(r['count'])} for r in levels],
        'teams': [{'team': r['team'], 'count': int(r['count'])} for r in teams],
        'components': [{'component': r['component'] or None, 'team': r['team'],
                        'count': int(r['count'])} for r in components],
        'sql': [scope_q, levels_q, teams_q, components_q],
    }


def overview(dataset='all'):
    datasets = DATASETS if dataset == 'all' else (dataset,)
    started = time.perf_counter()
    results = [overview_one(name) for name in datasets]
    return {'datasets': results,
            'elapsed_seconds': round(time.perf_counter() - started, 3)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dataset', choices=('all',) + DATASETS, default='all')
    args = parser.parse_args()
    print(json.dumps(overview(args.dataset), indent=2))
