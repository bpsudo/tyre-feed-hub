import statistics
import tomllib
from datetime import date, timedelta

from feedhub.db import PROJECT_ROOT
from feedhub.mapping import MappingError

THRESHOLDS_PATH = PROJECT_ROOT / "config" / "thresholds.toml"
REJECT_SEVERITY = "warning"
SIZE_FIELDS = {"size", "width", "aspect_ratio", "rim_diameter", "load_index", "speed_index"}


def load_thresholds(path=THRESHOLDS_PATH):
    with open(path, "rb") as file:
        return tomllib.load(file)


def readable_text(value):
    """Return the value as printable text, unreadable characters replaced by U+FFFD."""
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    # Lone surrogates cannot be stored as UTF-8.
    text = str(value).encode("utf-8", errors="replace").decode("utf-8")
    return "".join(char if char.isprintable() else "�" for char in text)


def percent(share):
    return f"{share * 100:+.0f} %"


# Row checks

def rule_for_field(field, error_type):
    if error_type == "missing":
        return "MISSING_FIELD"
    if field == "ean":
        return "EAN_INVALID"
    # No field means the check on the whole size failed (see NormalizedOffer.check_size).
    if field is None or field in SIZE_FIELDS:
        return "SIZE_UNPARSABLE"
    if field == "price_eur":
        return "PRICE_INVALID"
    if field == "stock" and error_type == "greater_than_equal":
        return "STOCK_NEGATIVE"
    return "VALUE_INVALID"


def row_rejection(error):
    """Return the rule code and a short message for a rejected row."""
    if isinstance(error, MappingError):
        return rule_for_field(error.field, "mapping"), f"{error.field}: {error}"
    first = error.errors()[0]
    field = first["loc"][0] if first["loc"] else None
    message = f"{field}: {first['msg']}" if field else first["msg"]
    return rule_for_field(field, first["type"]), message


# Import checks. Each one returns a list of (ean, rule_code, severity, details).

def previous_run(connection, supplier_id, run_id):
    return connection.execute(
        """
        SELECT id, rows_read FROM import_runs
        WHERE supplier_id = ? AND id < ? AND status IN ('success', 'partial')
        ORDER BY id DESC
        LIMIT 1
        """,
        (supplier_id, run_id),
    ).fetchone()


def check_reject_rate(rows_read, rows_rejected, thresholds):
    if rows_read == 0:
        return []
    rate = rows_rejected / rows_read
    if rate <= thresholds["reject_rate_max"]:
        return []
    details = f"{rows_rejected} rejected rows out of {rows_read} ({rate * 100:.1f} %)"
    return [(None, "REJECT_RATE_HIGH", "critical", details)]


def check_row_count(rows_read, previous, thresholds):
    if previous is None or previous["rows_read"] == 0:
        return []
    drop = (previous["rows_read"] - rows_read) / previous["rows_read"]
    if drop <= thresholds["row_count_drop_max"]:
        return []
    details = (f"{rows_read} rows against {previous['rows_read']} at the previous import"
               f" ({percent(-drop)}), file probably cut; missing offers kept")
    return [(None, "ROW_COUNT_DROP", "critical", details)]


def check_stock_drop(connection, run_id, previous, thresholds):
    if previous is None:
        return []
    total = "SELECT COALESCE(SUM(stock), 0) FROM offer_snapshots WHERE run_id = ?"
    new_stock = connection.execute(total, (run_id,)).fetchone()[0]
    old_stock = connection.execute(total, (previous["id"],)).fetchone()[0]
    if old_stock == 0:
        return []
    drop = (old_stock - new_stock) / old_stock
    if drop <= thresholds["stock_drop_max"]:
        return []
    details = f"total stock {new_stock} against {old_stock} at the previous import ({percent(-drop)})"
    return [(None, "STOCK_DROP", "critical", details)]


PRICE_JUMPS = """
SELECT cur.ean, prev.price_eur AS old_price, cur.price_eur AS new_price
FROM offer_snapshots AS cur
JOIN offer_snapshots AS prev ON prev.ean = cur.ean AND prev.run_id = ?
WHERE cur.run_id = ?
  AND ABS(cur.price_eur - prev.price_eur) > ? * prev.price_eur
ORDER BY cur.ean
"""


def check_price_jumps(connection, run_id, previous, thresholds):
    if previous is None:
        return []
    rows = connection.execute(PRICE_JUMPS, (previous["id"], run_id, thresholds["price_jump_max"]))
    anomalies = []
    for row in rows:
        change = row["new_price"] / row["old_price"] - 1
        details = f"price {row['old_price']:.2f} -> {row['new_price']:.2f} EUR ({percent(change)})"
        anomalies.append((row["ean"], "PRICE_JUMP", "warning", details))
    return anomalies


OTHER_SUPPLIER_PRICES = """
SELECT mine.ean, mine.price_eur AS price, other.price_eur AS other_price
FROM offer_snapshots AS mine
JOIN offers AS other ON other.ean = mine.ean AND other.supplier_id <> mine.supplier_id
WHERE mine.run_id = ?
ORDER BY mine.ean
"""


def check_price_outliers(connection, run_id, thresholds):
    prices = {}
    others = {}
    for row in connection.execute(OTHER_SUPPLIER_PRICES, (run_id,)):
        prices[row["ean"]] = row["price"]
        others.setdefault(row["ean"], []).append(row["other_price"])
    anomalies = []
    for ean, other_prices in others.items():
        all_prices = other_prices + [prices[ean]]
        # With two prices the median is their mean: one wrong price would move it.
        if len(all_prices) < thresholds["price_outlier_min_suppliers"]:
            continue
        median = statistics.median(all_prices)
        gap = prices[ean] / median - 1
        if abs(gap) > thresholds["price_outlier_max"]:
            details = (f"price {prices[ean]:.2f} EUR, median of the {len(all_prices)}"
                       f" suppliers {median:.2f} EUR ({percent(gap)})")
            anomalies.append((ean, "PRICE_OUTLIER", "warning", details))
    return anomalies


def check_loaded_run(connection, run_id, previous, thresholds):
    """Checks that compare the offers just loaded with the previous import of the supplier."""
    return (check_stock_drop(connection, run_id, previous, thresholds)
            + check_price_jumps(connection, run_id, previous, thresholds))


# Supplier checks

LAST_FEED_DATES = """
SELECT s.id, s.code, MAX(COALESCE(r.feed_date, DATE(r.started_at))) AS last_feed
FROM suppliers AS s
LEFT JOIN import_runs AS r ON r.supplier_id = s.id AND r.status IN ('success', 'partial')
WHERE s.active = 1
GROUP BY s.id, s.code
ORDER BY s.code
"""


def check_stale_feeds(connection, thresholds, checked_at):
    """Record FEED_STALE once for each supplier whose newest data is too old. Return the new anomalies."""
    oldest_allowed = (checked_at - timedelta(hours=thresholds["feed_stale_hours"])).date()
    found = []
    for row in connection.execute(LAST_FEED_DATES).fetchall():
        last_feed = date.fromisoformat(row["last_feed"]) if row["last_feed"] else None
        if last_feed is not None and last_feed >= oldest_allowed:
            continue
        details = f"newest data: {last_feed or 'never'}"
        # The same late feed is reported once, not at every import.
        already = connection.execute(
            "SELECT 1 FROM anomalies WHERE supplier_id = ? AND rule_code = 'FEED_STALE' AND details = ?",
            (row["id"], details),
        ).fetchone()
        if already is None:
            connection.execute(
                """
                INSERT INTO anomalies (run_id, supplier_id, ean, rule_code, severity, details)
                VALUES (NULL, ?, NULL, 'FEED_STALE', 'critical', ?)
                """,
                (row["id"], details),
            )
            found.append((row["code"], details))
    connection.commit()
    return found
