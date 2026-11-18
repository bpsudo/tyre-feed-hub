-- Which tyres of a given size are in stock, from the cheapest offer?
WITH newest_data AS (
    SELECT supplier_id, MAX(COALESCE(feed_date, DATE(started_at))) AS data_date
    FROM import_runs
    WHERE status IN ('success', 'partial')
    GROUP BY supplier_id
)
SELECT
    p.ean,
    p.brand,
    p.model,
    p.load_index || COALESCE(p.speed_index, '') AS load_speed,
    p.season,
    s.code AS supplier,
    o.price_eur,
    o.stock,
    o.delivery_days,
    n.data_date
FROM offers AS o
JOIN products AS p ON p.ean = o.ean
JOIN suppliers AS s ON s.id = o.supplier_id
LEFT JOIN newest_data AS n ON n.supplier_id = o.supplier_id
WHERE p.width = :width
  AND p.aspect_ratio = :aspect_ratio
  AND p.rim_diameter = :rim_diameter
  AND o.stock > 0
ORDER BY o.price_eur, o.delivery_days;
