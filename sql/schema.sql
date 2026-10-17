CREATE TABLE IF NOT EXISTS bgl_logs (
    source_file TEXT, line_id BIGINT, event_time TIMESTAMP,
    level TEXT, component TEXT, content TEXT, raw_text TEXT,
    parse_ok BOOLEAN, parse_error TEXT, event_id TEXT, event_template TEXT,
    label TEXT, epoch_seconds BIGINT, node TEXT, log_type TEXT, raw_text_base64 TEXT
);

CREATE TABLE IF NOT EXISTS openstack_logs (
    source_file TEXT, line_id BIGINT, event_time TIMESTAMP,
    level TEXT, component TEXT, content TEXT, raw_text TEXT,
    parse_ok BOOLEAN, parse_error TEXT, event_id TEXT, event_template TEXT,
    log_record TEXT, pid BIGINT, request_id TEXT, instance_id TEXT, correlation_data TEXT, raw_text_base64 TEXT
);
