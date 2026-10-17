SELECT
    'BGL' AS dataset,
    COUNT(*) AS row_count,
    MIN(event_time) AS first_event,
    MAX(event_time) AS last_event,
    SUM(CASE WHEN event_time IS NULL THEN 1 ELSE 0 END) AS invalid_timestamps,
    COUNT(*) - COUNT(DISTINCT (source_file, line_id)) AS duplicate_line_ids
FROM bgl_logs

UNION ALL

SELECT
    'OpenStack',
    COUNT(*),
    MIN(event_time),
    MAX(event_time),
    SUM(CASE WHEN event_time IS NULL THEN 1 ELSE 0 END),
    COUNT(*) - COUNT(DISTINCT (source_file, line_id))
FROM openstack_logs;