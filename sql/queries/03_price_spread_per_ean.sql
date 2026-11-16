-- Which tyres have the largest price gap between suppliers?
SELECT
    o.ean,
    p.brand,
    p.model,
    COUNT(*) AS supplier_count,
    MIN(o.price_eur) AS min_price_eur,
    MAX(o.price_eur) AS max_price_eur,
    ROUND(MAX(o.price_eur) - MIN(o.price_eur), 2) AS spread_eur,
    ROUND(100.0 * (MAX(o.price_eur) - MIN(o.price_eur)) / MIN(o.price_eur), 1) AS spread_pct
FROM offers AS o
JOIN products AS p ON p.ean = o.ean
GROUP BY o.ean, p.brand, p.model
HAVING COUNT(*) >= 2
ORDER BY spread_pct DESC
LIMIT 20;
