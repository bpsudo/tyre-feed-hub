-- Last import of each active supplier, with the date of its newest data.
WITH last_run AS (
    SELECT supplier_id, MAX(id) AS run_id
    FROM import_runs
    GROUP BY supplier_id
),
newest_data AS (
    SELECT supplier_id, MAX(COALESCE(feed_date, DATE(started_at))) AS newest_data
    FROM import_runs
    WHERE status IN ('success', 'partial')
    GROUP BY supplier_id
)
SELECT
    s.code,
    s.name,
    s.protocol,
    s.format,
    r.id AS run_id,
    r.status,
    r.started_at,
    r.source_name,
    r.rows_read,
    r.rows_rejected,
    r.error_message,
    n.newest_data,
    n.newest_data < :oldest_allowed_date AS is_stale,
    (SELECT COUNT(*) FROM anomalies AS a
     WHERE a.run_id = r.id AND a.severity = 'critical') AS critical_count,
    (SELECT COUNT(*) FROM offers AS o WHERE o.supplier_id = s.id) AS offer_count
FROM suppliers AS s
LEFT JOIN last_run AS lr ON lr.supplier_id = s.id
LEFT JOIN import_runs AS r ON r.id = lr.run_id
LEFT JOIN newest_data AS n ON n.supplier_id = s.id
WHERE s.active = 1
ORDER BY s.code;
