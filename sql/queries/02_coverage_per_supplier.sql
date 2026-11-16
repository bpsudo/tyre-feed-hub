-- How many references does each supplier offer, and how many does no other supplier have?
WITH suppliers_per_ean AS (
    SELECT ean, COUNT(*) AS supplier_count
    FROM offers
    GROUP BY ean
)
SELECT
    s.code AS supplier,
    COUNT(*) AS reference_count,
    SUM(CASE WHEN c.supplier_count = 1 THEN 1 ELSE 0 END) AS exclusive_count
FROM offers AS o
JOIN suppliers AS s ON s.id = o.supplier_id
JOIN suppliers_per_ean AS c ON c.ean = o.ean
GROUP BY s.code
ORDER BY s.code;
