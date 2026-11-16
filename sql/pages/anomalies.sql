-- Anomalies, newest first, filtered by supplier, rule, severity and date of the data.
SELECT
    a.id,
    COALESCE(r.feed_date, DATE(a.created_at)) AS data_date,
    s.code AS supplier,
    a.run_id,
    r.source_name,
    a.rule_code,
    a.severity,
    a.ean,
    a.details
FROM anomalies AS a
JOIN suppliers AS s ON s.id = a.supplier_id
LEFT JOIN import_runs AS r ON r.id = a.run_id
WHERE (:supplier IS NULL OR s.code = :supplier)
  AND (:rule_code IS NULL OR a.rule_code = :rule_code)
  AND (:severity IS NULL OR a.severity = :severity)
  AND (:data_date IS NULL OR COALESCE(r.feed_date, DATE(a.created_at)) = :data_date)
ORDER BY a.id DESC
LIMIT 500;
