-- How did the total stock of a supplier change from one import to the next?
WITH stock_per_run AS (
    SELECT
        r.id AS run_id,
        r.feed_date,
        r.source_name,
        COUNT(*) AS reference_count,
        SUM(sn.stock) AS total_stock
    FROM import_runs AS r
    JOIN suppliers AS s ON s.id = r.supplier_id
    JOIN offer_snapshots AS sn ON sn.run_id = r.id
    WHERE s.code = :supplier
    GROUP BY r.id, r.feed_date, r.source_name
)
SELECT
    run_id,
    feed_date,
    source_name,
    reference_count,
    total_stock,
    total_stock - LAG(total_stock) OVER (ORDER BY run_id) AS stock_change,
    ROUND(
        100.0 * (total_stock - LAG(total_stock) OVER (ORDER BY run_id))
        / LAG(total_stock) OVER (ORDER BY run_id),
        1
    ) AS change_pct
FROM stock_per_run
ORDER BY run_id;
