CREATE TABLE IF NOT EXISTS bgl_logs (
    line_id BIGINT,
    event_time TIMESTAMP,
    label VARCHAR,
    node VARCHAR,
    log_type VARCHAR,
    component VARCHAR,
    level VARCHAR,
    content VARCHAR,
    event_id VARCHAR,
    event_template VARCHAR
);

CREATE TABLE IF NOT EXISTS openstack_logs (
    line_id BIGINT,
    event_time TIMESTAMP,
    log_record VARCHAR,
    pid BIGINT,
    component VARCHAR,
    level VARCHAR,
    correlation_data VARCHAR,
    content VARCHAR,
    event_id VARCHAR,
    event_template VARCHAR
);