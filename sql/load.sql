-- Optional structured samples ONLY. These never replace full-corpus tables.
CREATE OR REPLACE TABLE sample_bgl_logs AS
SELECT
    "LineId" AS line_id,
    try_strptime("Time", '%Y-%m-%d-%H.%M.%S.%f') AS event_time,
    "Label" AS label,
    "Node" AS node,
    "Type" AS log_type,
    "Component" AS component,
    "Level" AS level,
    "Content" AS content,
    "EventId" AS event_id,
    "EventTemplate" AS event_template
FROM read_csv('/data/BGL_2k.log_structured.csv');

CREATE OR REPLACE TABLE sample_openstack_logs AS
SELECT
    "LineId" AS line_id,
    "Date" + "Time" AS event_time,
    "Logrecord" AS log_record,
    "Pid" AS pid,
    "Component" AS component,
    "Level" AS level,
    "ADDR" AS correlation_data,
    "Content" AS content,
    "EventId" AS event_id,
    "EventTemplate" AS event_template
FROM read_csv('/data/OpenStack_2k.log_structured.csv');