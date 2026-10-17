"""count_by tool: exact per-group counts over the whole dataset.

Groups matching log rows by one dimension (component, team, or severity) with
optional filters and a time range. Counts are physical log rows, not distinct
incidents, requests, or confirmed root causes. Ownership (team) is fictional
demonstration data, not organizational evidence.
"""
import argparse
import json

try:
    from .aggregations import grouped_counts, COUNT_BY_DIMENSIONS
except ImportError:
    from aggregations import grouped_counts, COUNT_BY_DIMENSIONS


CAVEAT = (
    "Counts are physical log rows, not distinct incidents, requests, or affected "
    "users. Frequency does not establish a confirmed problem or root cause. The "
    "team dimension uses fictional ownership mappings."
)


def count_by(dataset, dimension="component", since=None, until=None,
             levels=None, component=None, team=None, text=None, limit=100):
    """Count matching log rows grouped by component, team, or severity.

    Counts over all levels by default (the whole dataset); pass `levels` to
    restrict. A database error propagates as an exception; no matching rows is a
    valid, separate outcome (empty results, zero total).
    """
    counted = grouped_counts(
        dataset=dataset,
        dimension=dimension,
        since=since,
        until=until,
        levels=levels,
        component=component,
        team=team,
        text=text,
        limit=limit,
    )
    return {
        "tool": "count_by",
        "dataset": counted["dataset"],
        "dimension": counted["dimension"],
        "grouped_column": counted["grouped_column"],
        "counted_metric": "log_rows",
        "filters": counted["filters"],
        "total_matching_rows": counted["total_matching_rows"],
        "total_groups": counted["total_groups"],
        "returned": counted["returned"],
        "truncated": counted["truncated"],
        "results": counted["results"],
        "sql": counted["sql"],
        "ownership_is_fictional": True,
        "caveat": CAVEAT,
        "elapsed_seconds": counted["elapsed_seconds"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("bgl", "openstack"), required=True)
    parser.add_argument("--dimension", choices=tuple(COUNT_BY_DIMENSIONS),
                        default="component")
    parser.add_argument("--since", help="Source-local ISO datetime, inclusive")
    parser.add_argument("--until", help="Source-local ISO datetime, exclusive")
    parser.add_argument("--level", action="append", dest="levels",
                        help="Restrict to this level; repeatable")
    parser.add_argument("--component", help="Exact match on the component column")
    parser.add_argument("--team", help="Exact match on the fictional owner team")
    parser.add_argument("--text", help="Full-text match on content")
    parser.add_argument("--limit", type=int, default=100,
                        help="Max groups returned (1-100)")
    args = parser.parse_args()
    print(json.dumps(count_by(args.dataset, args.dimension, args.since, args.until,
                              args.levels, args.component, args.team, args.text,
                              args.limit), indent=2))
