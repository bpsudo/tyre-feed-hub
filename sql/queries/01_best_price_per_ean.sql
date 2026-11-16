-- For each tyre, which supplier has the lowest price?
SELECT
    o.ean,
    p.brand,
    p.model,
    s.code AS supplier,
    o.price_eur AS best_price_eur,
    o.stock
FROM offers AS o
JOIN products AS p ON p.ean = o.ean
JOIN suppliers AS s ON s.id = o.supplier_id
WHERE o.price_eur = (
    SELECT MIN(o2.price_eur) FROM offers AS o2 WHERE o2.ean = o.ean
)
ORDER BY p.brand, p.model, o.ean;
