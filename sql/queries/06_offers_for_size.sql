-- Which tyres of a given size are in stock, from the cheapest offer?
SELECT
    p.ean,
    p.brand,
    p.model,
    p.load_index || COALESCE(p.speed_index, '') AS load_speed,
    p.season,
    s.code AS supplier,
    o.price_eur,
    o.stock,
    o.delivery_days
FROM offers AS o
JOIN products AS p ON p.ean = o.ean
JOIN suppliers AS s ON s.id = o.supplier_id
WHERE p.width = :width
  AND p.aspect_ratio = :aspect_ratio
  AND p.rim_diameter = :rim_diameter
  AND o.stock > 0
ORDER BY o.price_eur, o.delivery_days;
