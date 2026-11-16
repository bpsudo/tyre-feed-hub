-- Which active suppliers have no successful import with data from the last 24 hours?
SELECT
    s.code AS supplier,
    s.name,
    MAX(COALESCE(r.feed_date, DATE(r.started_at))) AS newest_data,
    MAX(r.finished_at) AS last_successful_import
FROM suppliers AS s
LEFT JOIN import_runs AS r
    ON r.supplier_id = s.id
   AND r.status IN ('success', 'partial')
WHERE s.active = 1
GROUP BY s.id, s.code, s.name
HAVING MAX(COALESCE(r.feed_date, DATE(r.started_at))) IS NULL
    OR MAX(COALESCE(r.feed_date, DATE(r.started_at))) < DATE('now', '-1 day')
ORDER BY s.code;
