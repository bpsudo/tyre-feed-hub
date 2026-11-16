-- How many anomalies did each supplier have in the last 7 days, by severity?
SELECT
    s.code AS supplier,
    a.severity,
    COUNT(*) AS anomaly_count
FROM anomalies AS a
JOIN suppliers AS s ON s.id = a.supplier_id
WHERE a.created_at >= DATETIME('now', '-7 days')
GROUP BY s.code, a.severity
ORDER BY
    s.code,
    CASE a.severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END;
