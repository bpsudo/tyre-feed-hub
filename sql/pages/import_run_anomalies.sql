-- Anomalies of one import: the most severe first, then in file order.
SELECT
    a.rule_code,
    a.severity,
    a.ean,
    a.details
FROM anomalies AS a
WHERE a.run_id = :run_id
ORDER BY
    CASE a.severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
    a.id;
