-- Which 10 tyre sizes have the most tyres in stock?
SELECT
    p.width || '/' || p.aspect_ratio || ' R' || p.rim_diameter AS size,
    COUNT(DISTINCT p.ean) AS reference_count,
    COUNT(DISTINCT o.supplier_id) AS supplier_count,
    SUM(o.stock) AS total_stock
FROM offers AS o
JOIN products AS p ON p.ean = o.ean
WHERE o.stock > 0
GROUP BY p.width, p.aspect_ratio, p.rim_diameter
ORDER BY total_stock DESC
LIMIT 10;
