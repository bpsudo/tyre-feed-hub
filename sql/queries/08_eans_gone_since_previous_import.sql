-- Which EANs were in the previous import of a supplier and are missing from the last one?
WITH loaded_runs AS (
    SELECT
        r.id,
        ROW_NUMBER() OVER (ORDER BY r.id DESC) AS position
    FROM import_runs AS r
    JOIN suppliers AS s ON s.id = r.supplier_id
    WHERE s.code = :supplier
      AND r.status IN ('success', 'partial')
)
SELECT
    prev.ean,
    p.brand,
    p.model,
    prev.price_eur,
    prev.stock
FROM offer_snapshots AS prev
JOIN products AS p ON p.ean = prev.ean
WHERE prev.run_id = (SELECT id FROM loaded_runs WHERE position = 2)
  AND prev.ean NOT IN (
      SELECT ean FROM offer_snapshots
      WHERE run_id = (SELECT id FROM loaded_runs WHERE position = 1)
  )
ORDER BY prev.ean;
