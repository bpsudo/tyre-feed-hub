-- One import, with its supplier.
SELECT
    r.id,
    s.code AS supplier,
    s.name AS supplier_name,
    r.source_name,
    r.feed_date,
    r.status,
    r.started_at,
    r.finished_at,
    r.rows_read,
    r.rows_loaded,
    r.rows_rejected,
    r.error_message
FROM import_runs AS r
JOIN suppliers AS s ON s.id = r.supplier_id
WHERE r.id = :run_id;
