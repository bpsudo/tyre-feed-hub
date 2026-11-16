import json
import re
from datetime import date

from pydantic import ValidationError

from feedhub import checks
from feedhub.checks import REJECT_SEVERITY, readable_text, row_rejection
from feedhub.connectors import local_file, rest_api, sftp
from feedhub.db import now
from feedhub.mapping import MappingError, map_row
from feedhub.models import NormalizedOffer
from feedhub.readers import read_file

CONNECTORS = {"file": local_file, "sftp": sftp, "rest_api": rest_api}
PRODUCT_FIELDS = [
    "ean", "brand", "model", "width", "aspect_ratio", "rim_diameter", "load_index",
    "speed_index", "season", "vehicle_type", "noise_db", "fuel_class", "wet_grip_class",
]

SAVE_SUPPLIER = """
INSERT INTO suppliers (code, name, protocol, format) VALUES (?, ?, ?, ?)
ON CONFLICT (code) DO UPDATE SET
    name = excluded.name, protocol = excluded.protocol, format = excluded.format
"""

# COALESCE keeps a value already known from another supplier when this one leaves it empty.
SAVE_PRODUCT = """
INSERT INTO products (ean, brand, model, width, aspect_ratio, rim_diameter, load_index,
                      speed_index, season, vehicle_type, noise_db, fuel_class, wet_grip_class)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (ean) DO UPDATE SET
    brand = excluded.brand,
    model = COALESCE(excluded.model, products.model),
    width = excluded.width,
    aspect_ratio = excluded.aspect_ratio,
    rim_diameter = excluded.rim_diameter,
    load_index = COALESCE(excluded.load_index, products.load_index),
    speed_index = COALESCE(excluded.speed_index, products.speed_index),
    season = COALESCE(excluded.season, products.season),
    vehicle_type = COALESCE(excluded.vehicle_type, products.vehicle_type),
    noise_db = COALESCE(excluded.noise_db, products.noise_db),
    fuel_class = COALESCE(excluded.fuel_class, products.fuel_class),
    wet_grip_class = COALESCE(excluded.wet_grip_class, products.wet_grip_class)
"""

SAVE_OFFER = """
INSERT INTO offers (supplier_id, ean, price_eur, stock, delivery_days, updated_at)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (supplier_id, ean) DO UPDATE SET
    price_eur = excluded.price_eur,
    stock = excluded.stock,
    delivery_days = excluded.delivery_days,
    updated_at = excluded.updated_at
"""

SAVE_SNAPSHOT = """
INSERT INTO offer_snapshots (run_id, supplier_id, ean, price_eur, stock) VALUES (?, ?, ?, ?, ?)
"""

# An EAN missing from today's file is no longer offered by the supplier.
DELETE_MISSING_OFFERS = """
DELETE FROM offers
WHERE supplier_id = ? AND ean NOT IN (SELECT ean FROM offer_snapshots WHERE run_id = ?)
"""


def connector(mapping):
    return CONNECTORS[mapping["protocol"]]


def describe_source(mapping):
    return connector(mapping).describe(mapping["source"])


def save_supplier(connection, mapping):
    connection.execute(
        SAVE_SUPPLIER, (mapping["code"], mapping["name"], mapping["protocol"], mapping["format"])
    )
    connection.commit()
    row = connection.execute("SELECT id FROM suppliers WHERE code = ?", (mapping["code"],)).fetchone()
    return row["id"]


def imported_files(connection, supplier_id):
    rows = connection.execute(
        "SELECT source_name FROM import_runs WHERE supplier_id = ? AND status IN ('success', 'partial')",
        (supplier_id,),
    )
    return {row["source_name"] for row in rows}


def feed_date(source_name):
    """Date written in a file name such as stock_20260120.csv, or None."""
    match = re.search(r"(\d{4})-?(\d{2})-?(\d{2})", source_name or "")
    if match is None:
        return None
    try:
        return date(*map(int, match.groups())).isoformat()
    except ValueError:
        return None


def start_run(connection, supplier_id, source_name, started_at):
    cursor = connection.execute(
        "INSERT INTO import_runs (supplier_id, started_at, source_name, feed_date) VALUES (?, ?, ?, ?)",
        (supplier_id, started_at, source_name, feed_date(source_name)),
    )
    connection.commit()
    return cursor.lastrowid


def finish_run(connection, run_id, status, rows_read=0, rows_loaded=0, rows_rejected=0, error_message=None):
    connection.execute(
        """
        UPDATE import_runs
        SET finished_at = ?, status = ?, rows_read = ?, rows_loaded = ?, rows_rejected = ?, error_message = ?
        WHERE id = ?
        """,
        (now(), status, rows_read, rows_loaded, rows_rejected, error_message, run_id),
    )


def run_result(connection, run_id):
    return dict(connection.execute("SELECT * FROM import_runs WHERE id = ?", (run_id,)).fetchone())


def validate_rows(raw_rows, mapping):
    """Return the valid offers (last row kept for a repeated EAN), the anomalies and the reject count."""
    offers = {}
    anomalies = []
    rejected = 0
    ean_column = mapping["columns"].get("ean")
    for row_number, raw in enumerate(raw_rows, start=1):
        try:
            offer = NormalizedOffer(**map_row(raw, mapping))
        except (MappingError, ValidationError) as error:
            rule_code, message = row_rejection(error)
            details = f"row {row_number}: {message} | {json.dumps(raw, ensure_ascii=False)}"
            raw_ean = raw.get(ean_column)
            anomalies.append((str(raw_ean) if raw_ean is not None else None, rule_code, REJECT_SEVERITY, details))
            rejected += 1
            continue
        if offer.ean in offers:
            details = f"row {row_number}: EAN already seen in the file, this row is kept"
            anomalies.append((offer.ean, "DUPLICATE_IN_FILE", "warning", details))
        offers[offer.ean] = offer
    return list(offers.values()), anomalies, rejected


def load_offers(connection, run_id, supplier_id, offers, loaded_at, delete_missing=True):
    connection.executemany(
        SAVE_PRODUCT, [[getattr(offer, field) for field in PRODUCT_FIELDS] for offer in offers]
    )
    connection.executemany(
        SAVE_OFFER,
        [(supplier_id, o.ean, o.price_eur, o.stock, o.delivery_days, loaded_at) for o in offers],
    )
    connection.executemany(
        SAVE_SNAPSHOT, [(run_id, supplier_id, o.ean, o.price_eur, o.stock) for o in offers]
    )
    if delete_missing:
        connection.execute(DELETE_MISSING_OFFERS, (supplier_id, run_id))


def save_anomalies(connection, run_id, supplier_id, anomalies):
    connection.executemany(
        """
        INSERT INTO anomalies (run_id, supplier_id, ean, rule_code, severity, details)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(run_id, supplier_id, ean, rule, severity, readable_text(details))
         for ean, rule, severity, details in anomalies],
    )


def import_file(connection, supplier_id, mapping, name, content, thresholds):
    started_at = now()
    run_id = start_run(connection, supplier_id, name, started_at)
    try:
        raw_rows = read_file(content, mapping)
        offers, anomalies, rejected = validate_rows(raw_rows, mapping)
        previous = checks.previous_run(connection, supplier_id, run_id)
        anomalies += checks.check_reject_rate(len(raw_rows), rejected, thresholds)
        row_count_drop = checks.check_row_count(len(raw_rows), previous, thresholds)
        anomalies += row_count_drop
        with connection:
            if offers:
                # A cut file must not delete the offers it is missing.
                load_offers(connection, run_id, supplier_id, offers, started_at,
                            delete_missing=not row_count_drop)
                anomalies += checks.check_loaded_run(connection, run_id, previous, thresholds)
                status = "success" if rejected == 0 else "partial"
                finish_run(connection, run_id, status, len(raw_rows), len(offers), rejected)
            else:
                # Loading nothing would delete every offer of the supplier.
                finish_run(connection, run_id, "failed", len(raw_rows), 0, rejected, "no valid row")
            save_anomalies(connection, run_id, supplier_id, anomalies)
    # One unreadable file must not stop the import of the next ones.
    except Exception as error:
        finish_run(connection, run_id, "failed", error_message=f"{type(error).__name__}: {error}")
        connection.commit()
    return run_result(connection, run_id)


def import_supplier(connection, mapping, thresholds=None):
    """Import every new file of a supplier. Return one result per import run."""
    thresholds = thresholds or checks.load_thresholds()
    supplier_id = save_supplier(connection, mapping)
    skip_names = imported_files(connection, supplier_id)
    try:
        files = connector(mapping).fetch_files(mapping["source"], skip_names)
    # Server down, wrong password, missing folder: recorded as a failed run.
    except Exception as error:
        run_id = start_run(connection, supplier_id, None, now())
        finish_run(connection, run_id, "failed", error_message=f"{type(error).__name__}: {error}")
        connection.commit()
        return [run_result(connection, run_id)]
    return [import_file(connection, supplier_id, mapping, name, content, thresholds)
            for name, content in files]


def check_outliers(connection, results, thresholds=None):
    """Compare the prices of the newest loaded run with the other suppliers. Return the anomaly count."""
    thresholds = thresholds or checks.load_thresholds()
    loaded = [run for run in results if run["status"] in ("success", "partial")]
    if not loaded:
        return 0
    run = loaded[-1]
    anomalies = checks.check_price_outliers(connection, run["id"], thresholds)
    with connection:
        save_anomalies(connection, run["id"], run["supplier_id"], anomalies)
    return len(anomalies)


def import_suppliers(connection, mappings, thresholds=None):
    """Import several suppliers, then run the checks that compare suppliers with each other."""
    thresholds = thresholds or checks.load_thresholds()
    results = {mapping["code"]: import_supplier(connection, mapping, thresholds) for mapping in mappings}
    # Done after every import, so that the first supplier also has other prices to compare with.
    for runs in results.values():
        check_outliers(connection, runs, thresholds)
    return results
