CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    protocol TEXT NOT NULL,
    format TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    ean TEXT PRIMARY KEY,
    brand TEXT NOT NULL,
    model TEXT,
    width INTEGER NOT NULL,
    aspect_ratio INTEGER NOT NULL,
    rim_diameter INTEGER NOT NULL,
    load_index INTEGER,
    speed_index TEXT,
    season TEXT,
    vehicle_type TEXT,
    noise_db INTEGER,
    fuel_class TEXT,
    wet_grip_class TEXT
);

CREATE TABLE IF NOT EXISTS offers (
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id),
    ean TEXT NOT NULL REFERENCES products (ean),
    price_eur NUMERIC(10, 2) NOT NULL CHECK (price_eur > 0),
    stock INTEGER NOT NULL CHECK (stock >= 0),
    delivery_days INTEGER,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (supplier_id, ean)
);

CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id),
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    -- NULL while the import is still running.
    status TEXT CHECK (status IN ('success', 'partial', 'failed')),
    source_name TEXT,
    rows_read INTEGER NOT NULL DEFAULT 0,
    rows_loaded INTEGER NOT NULL DEFAULT 0,
    rows_rejected INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS offer_snapshots (
    run_id INTEGER NOT NULL REFERENCES import_runs (id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id),
    ean TEXT NOT NULL REFERENCES products (ean),
    price_eur NUMERIC(10, 2) NOT NULL,
    stock INTEGER NOT NULL,
    PRIMARY KEY (run_id, ean)
);

CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY,
    -- NULL for FEED_STALE: a supplier can be late before its first import.
    run_id INTEGER REFERENCES import_runs (id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id),
    -- No foreign key: a rejected line can carry an EAN missing from products.
    ean TEXT,
    rule_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    details TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_products_size ON products (width, aspect_ratio, rim_diameter);
CREATE INDEX IF NOT EXISTS idx_offers_ean ON offers (ean);
CREATE INDEX IF NOT EXISTS idx_import_runs_supplier ON import_runs (supplier_id, started_at);
CREATE INDEX IF NOT EXISTS idx_offer_snapshots_ean ON offer_snapshots (ean);
CREATE INDEX IF NOT EXISTS idx_anomalies_run ON anomalies (run_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_supplier ON anomalies (supplier_id, created_at);
