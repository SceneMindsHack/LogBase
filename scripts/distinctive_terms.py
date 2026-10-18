"""distinctive_terms: terms over-represented in a foreground window vs a baseline.

Native SereneDB analytics. All term enumeration and document-frequency counting
happens in the database via ts_dict_agg(content) and ts_dict_count(content) over
the inverted full-text index. Python only validates input, builds safe SQL,
converts scalar types, and formats output; it never fetches or counts the corpus.

Document frequency, not occurrence frequency: a record containing a term many
times contributes one document to that term's count. Counts are proportions of
log records, not request failure rates, incidents, or business impact. Terms are
investigative leads, not causes.
"""
import time
from datetime import datetime, timedelta

try:
    from .db import records, literal
except ImportError:
    from db import records, literal

# Fixed allowlist: dataset -> inverted full-text index relation.
INDEX_RELATIONS = {
    'bgl': 'bgl_logs_fts',
    'openstack': 'openstack_logs_fts',
}
# Small, documented noise list of structural tokens that dominate many lines.
# Lowercased to match the logbase_words analyzer. Error codes/acronyms are kept.
DEFAULT_EXCLUDED_TERMS = (
    'the', 'a', 'an', 'and', 'or', 'of', 'to', 'in', 'on', 'at', 'for', 'is',
    'as', 'by', 'with', 'from',
)
MAX_TOP_N = 50
MAX_EXCLUSIONS = 100
MAX_WINDOW_HOURS = 24
MIN_INTERPRETATION_RECORDS = 100
# Shares are expressed as proportions in [0, 1]; share_change_pp is percentage points.


def _parse_local(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be an ISO date/time string')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f'{label} must be a valid ISO date/time') from error
    if parsed.tzinfo is not None:
        raise ValueError('Use source-local timestamps without timezone offsets')
    return parsed


def _validate_window(start, end, label):
    start_dt = _parse_local(start, f'{label}_start')
    end_dt = _parse_local(end, f'{label}_end')
    if start_dt >= end_dt:
        raise ValueError(f'{label}_start must precede {label}_end')
    if end_dt - start_dt > timedelta(hours=MAX_WINDOW_HOURS):
        raise ValueError(
            f'{label} window may span at most {MAX_WINDOW_HOURS} hours')
    return start_dt, end_dt


def _overlaps(fg, bg):
    """True if the two [start, end) windows overlap. Adjacent windows do not."""
    return fg[0] < bg[1] and bg[0] < fg[1]


def _normalize_exclusions(exclude_terms):
    terms = list(DEFAULT_EXCLUDED_TERMS)
    if exclude_terms is not None:
        if not isinstance(exclude_terms, list):
            raise ValueError('exclude_terms must be a list of strings')
        if len(exclude_terms) > MAX_EXCLUSIONS:
            raise ValueError(f'exclude_terms may contain at most {MAX_EXCLUSIONS} entries')
        for term in exclude_terms:
            if not isinstance(term, str) or not term.strip():
                raise ValueError('exclude_terms must contain non-empty strings')
            # Match the analyzer's lowercasing so exclusions actually bite.
            lowered = term.strip().lower()
            if lowered not in terms:
                terms.append(lowered)
    return terms


def _normalize_levels(levels):
    if levels is None:
        return None
    if not isinstance(levels, list) or not levels:
        raise ValueError('levels must be a non-empty list when provided')
    normalized = []
    for level in levels:
        if not isinstance(level, str) or not level.strip():
            raise ValueError('levels must contain non-empty strings')
        if level not in normalized:
            normalized.append(level)
    return normalized


def _window_filters(index, start_dt, end_dt, component, levels):
    """Shared WHERE clause for one window: filtered, timed, non-null content."""
    parts = [
        'event_time >= ' + literal(start_dt),
        'event_time < ' + literal(end_dt),
        'event_time IS NOT NULL',
        'content IS NOT NULL',
    ]
    if component is not None:
        parts.append('component = ' + literal(component))
    if levels is not None:
        quoted = ', '.join(literal(level) for level in levels)
        parts.append(f'level IN ({quoted})')
    return ' AND '.join(parts)


def distinctive_terms_sql(dataset, foreground_start, foreground_end,
                          baseline_start, baseline_end, component=None,
                          levels=None, min_foreground_docs=5, top_n=10,
                          exclude_terms=None):
    """Validate inputs and build one native significant-terms query.

    Returns (sql, metadata). All identifiers come from fixed allowlists; only
    data values are interpolated, via literal().
    """
    if dataset not in INDEX_RELATIONS:
        raise ValueError("dataset must be 'bgl' or 'openstack'")
    if isinstance(min_foreground_docs, bool) or not isinstance(min_foreground_docs, int) \
            or min_foreground_docs < 1:
        raise ValueError('min_foreground_docs must be a positive integer')
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= MAX_TOP_N:
        raise ValueError(f'top_n must be an integer between 1 and {MAX_TOP_N}')
    if component is not None and (not isinstance(component, str) or not component.strip()):
        raise ValueError('component must be a non-empty string when provided')

    fg = _validate_window(foreground_start, foreground_end, 'foreground')
    bg = _validate_window(baseline_start, baseline_end, 'baseline')
    if _overlaps(fg, bg):
        raise ValueError('foreground and baseline windows must not overlap (adjacent is allowed)')

    normalized_levels = _normalize_levels(levels)
    exclusions = _normalize_exclusions(exclude_terms)

    index = INDEX_RELATIONS[dataset]
    fg_where = _window_filters(index, fg[0], fg[1], component, normalized_levels)
    bg_where = _window_filters(index, bg[0], bg[1], component, normalized_levels)
    excl_quoted = ', '.join(literal(term) for term in exclusions)

    # One statement. Term aggregates and eligible denominators come from the same
    # filtered snapshot of the inverted index. LEFT JOIN keeps terms absent from
    # the baseline; COALESCE their baseline docs to 0. All ranking/limit in SQL.
    sql = (
        "WITH fg_terms AS (\n"
        "    SELECT unnest(ts_dict_agg(content)) AS term,\n"
        "           unnest(ts_dict_count(content)) AS docs\n"
        f"    FROM {index} WHERE {fg_where}\n"
        "), bg_terms AS (\n"
        "    SELECT unnest(ts_dict_agg(content)) AS term,\n"
        "           unnest(ts_dict_count(content)) AS docs\n"
        f"    FROM {index} WHERE {bg_where}\n"
        "), fg_total AS (\n"
        f"    SELECT COUNT(*) AS n FROM {index} WHERE {fg_where}\n"
        "), bg_total AS (\n"
        f"    SELECT COUNT(*) AS n FROM {index} WHERE {bg_where}\n"
        "), joined AS (\n"
        "    SELECT f.term AS term,\n"
        "           f.docs AS foreground_docs,\n"
        "           COALESCE(b.docs, 0) AS baseline_docs,\n"
        "           (SELECT n FROM fg_total) AS foreground_total,\n"
        "           (SELECT n FROM bg_total) AS baseline_total\n"
        "    FROM fg_terms f\n"
        "    LEFT JOIN bg_terms b ON b.term = f.term\n"
        f"    WHERE f.docs >= {min_foreground_docs}\n"
        f"      AND f.term NOT IN ({excl_quoted})\n"
        "), scored AS (\n"
        "    SELECT term, foreground_docs, baseline_docs,\n"
        "           foreground_total, baseline_total,\n"
        "           foreground_docs::double precision / foreground_total AS foreground_share,\n"
        "           CASE WHEN baseline_total > 0\n"
        "                THEN baseline_docs::double precision / baseline_total\n"
        "                ELSE 0 END AS baseline_share\n"
        "    FROM joined\n"
        "    WHERE foreground_total > 0\n"
        "), qualifying AS (\n"
        "    SELECT term, foreground_docs, baseline_docs,\n"
        "           foreground_total, baseline_total,\n"
        "           foreground_share, baseline_share,\n"
        "           foreground_share - baseline_share AS share_change,\n"
        "           foreground_docs - foreground_total * baseline_share AS excess_documents,\n"
        "           CASE WHEN baseline_share > 0\n"
        "                THEN foreground_share / baseline_share ELSE NULL END AS ratio\n"
        "    FROM scored\n"
        "    WHERE foreground_docs - foreground_total * baseline_share > 0\n"
        ")\n"
        "SELECT term, foreground_docs, baseline_docs,\n"
        "       foreground_total, baseline_total,\n"
        "       foreground_share, baseline_share,\n"
        "       share_change, excess_documents, ratio,\n"
        "       COUNT(*) OVER () AS total_qualifying_terms\n"
        "FROM qualifying\n"
        "ORDER BY excess_documents DESC, foreground_docs DESC, term ASC\n"
        f"LIMIT {top_n}"
    )

    metadata = {
        'dataset': dataset,
        'index_relation': index,
        'foreground': {
            'start_inclusive': fg[0].isoformat(), 'end_exclusive': fg[1].isoformat(),
            'duration_seconds': (fg[1] - fg[0]).total_seconds(),
        },
        'baseline': {
            'start_inclusive': bg[0].isoformat(), 'end_exclusive': bg[1].isoformat(),
            'duration_seconds': (bg[1] - bg[0]).total_seconds(),
        },
        'effective_filters': {'component': component, 'levels': normalized_levels},
        'min_foreground_docs': min_foreground_docs,
        'top_n': top_n,
        'excluded_terms': exclusions,
        'maximum_window_hours': MAX_WINDOW_HOURS,
    }
    return sql, metadata


def _eligible_counts_sql(dataset, fg, bg, component, levels):
    """Separate denominator query, used when term aggregation returns no rows so
    we can still report whether a window simply had no eligible records."""
    index = INDEX_RELATIONS[dataset]
    fg_where = _window_filters(index, fg[0], fg[1], component, levels)
    bg_where = _window_filters(index, bg[0], bg[1], component, levels)
    return (f"SELECT (SELECT COUNT(*) FROM {index} WHERE {fg_where}) AS foreground_total,\n"
            f"       (SELECT COUNT(*) FROM {index} WHERE {bg_where}) AS baseline_total")


def _interpretation_warnings(foreground_total, baseline_total):
    """Warnings for non-empty samples too small for stable interpretation.

    The threshold is a practical guardrail, not a statistical guarantee.
    """
    warnings = []
    if 0 < foreground_total < MIN_INTERPRETATION_RECORDS:
        warnings.append(
            f'Foreground has fewer than {MIN_INTERPRETATION_RECORDS} eligible '
            'records; document shares and term rankings may be unstable. '
            'This threshold is a practical interpretation warning, not a '
            'statistical guarantee.')
    if 0 < baseline_total < MIN_INTERPRETATION_RECORDS:
        warnings.append(
            f'Baseline has fewer than {MIN_INTERPRETATION_RECORDS} eligible '
            'records; ratios and comparisons may be unstable. This threshold '
            'is a practical interpretation warning, not a statistical guarantee.')
    return warnings


def distinctive_terms(dataset, foreground_start, foreground_end, baseline_start,
                      baseline_end, component=None, levels=None,
                      min_foreground_docs=5, top_n=10, exclude_terms=None):
    """Rank terms disproportionately common in the foreground vs the baseline.

    A database error propagates as an exception. Insufficient data (an empty
    window) is a distinct, documented success-shaped status, never a crash.
    """
    sql, metadata = distinctive_terms_sql(
        dataset, foreground_start, foreground_end, baseline_start, baseline_end,
        component, levels, min_foreground_docs, top_n, exclude_terms)

    started = time.perf_counter()
    rows = records(sql)
    executed_sql = [sql]
    if rows:
        foreground_total = int(rows[0]['foreground_total'])
        baseline_total = int(rows[0]['baseline_total'])
    else:
        fg = (_parse_local(foreground_start, 'foreground_start'),
              _parse_local(foreground_end, 'foreground_end'))
        bg = (_parse_local(baseline_start, 'baseline_start'),
              _parse_local(baseline_end, 'baseline_end'))
        counts_sql = _eligible_counts_sql(
            dataset, fg, bg, component, metadata['effective_filters']['levels'])
        counts = records(counts_sql)[0]
        executed_sql.append(counts_sql)
        foreground_total = int(counts['foreground_total'])
        baseline_total = int(counts['baseline_total'])
    elapsed = round(time.perf_counter() - started, 3)
    warnings = _interpretation_warnings(foreground_total, baseline_total)

    method = {
        'engine': 'SereneDB native inverted-index term dictionary',
        'functions': ['ts_dict_agg(content)', 'ts_dict_count(content)'],
        'metric': 'document frequency (records containing the term; repeats within '
                  'one record count once)',
        'score': 'excess_documents = foreground_docs - foreground_total * baseline_share',
        'score_is_not': 'not a p-value, confidence, or statistical-significance score',
        'shares_scale': '0-1 proportions of eligible records; share_change_pp is percentage points',
        'min_foreground_docs': min_foreground_docs,
        'excluded_terms': metadata['excluded_terms'],
        'top_n': top_n,
        'result_kind': 'top_n (bounded ranking, not the exhaustive vocabulary)',
        'maximum_window_hours': MAX_WINDOW_HOURS,
        'small_window_warning_threshold_records': MIN_INTERPRETATION_RECORDS,
        'freshness': 'reflects the inverted index as last refreshed; not guaranteed '
                     'real-time if records were ingested after the last refresh',
    }
    base = {
        'tool': 'distinctive_terms',
        'dataset': dataset,
        'index_relation': metadata['index_relation'],
        'foreground': metadata['foreground'],
        'baseline': metadata['baseline'],
        'effective_filters': metadata['effective_filters'],
        'foreground_total': foreground_total,
        'baseline_total': baseline_total,
        'method': method,
        'sql': executed_sql,
        'warnings': warnings,
        'elapsed_seconds': elapsed,
        'caveat': ('Shares are proportions of log records, not request failure rates '
                   'or business impact. Repeated messages can dominate term counts. '
                   'Terms are investigative leads, not causes; this is a transparent '
                   'heuristic, not statistical significance.'),
    }

    if foreground_total == 0 or baseline_total == 0:
        base.update({'status': 'insufficient_data', 'returned': 0,
                     'truncated': False, 'total_qualifying_terms': 0, 'terms': [],
                     'note': 'One or both windows had no eligible records '
                             '(timed, non-null content, matching filters).'})
        return base

    terms = []
    for row in rows:
        baseline_docs = int(row['baseline_docs'])
        ratio = None if row['ratio'] in (None, '') else round(float(row['ratio']), 4)
        fg_share = float(row['foreground_share'])
        bl_share = float(row['baseline_share'])
        terms.append({
            'term': row['term'],
            'foreground_docs': int(row['foreground_docs']),
            'baseline_docs': baseline_docs,
            'foreground_share': round(fg_share, 6),
            'baseline_share': round(bl_share, 6),
            'share_change_pp': round(100 * (fg_share - bl_share), 4),
            'excess_documents': round(float(row['excess_documents']), 4),
            'ratio': ratio,
            'new_in_baseline_comparison': baseline_docs == 0,
        })

    total_qualifying_terms = (
        int(rows[0]['total_qualifying_terms']) if rows else 0)
    base.update({
        'status': 'ok' if terms else 'no_distinctive_terms',
        'returned': len(terms),
        'truncated': total_qualifying_terms > len(terms),
        'total_qualifying_terms': total_qualifying_terms,
        'terms': terms,
    })
    if not terms:
        base['note'] = ('Both windows had eligible records, but no term met the '
                        'support, positive-excess, and exclusion filters.')
    return base
