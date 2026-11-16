-- What share of the rows was rejected at each import?
SELECT
    r.id AS run_id,
    s.code AS supplier,
    r.source_name,
    r.status,
    r.rows_read,
    r.rows_rejected,
    ROUND(100.0 * r.rows_rejected / NULLIF(r.rows_read, 0), 1) AS reject_pct
FROM import_runs AS r
JOIN suppliers AS s ON s.id = r.supplier_id
WHERE :supplier IS NULL OR s.code = :supplier
ORDER BY r.id DESC;
