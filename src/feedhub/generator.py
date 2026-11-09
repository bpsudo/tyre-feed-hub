import csv
import io
import json
import random
import shutil
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from feedhub.db import PROJECT_ROOT
from feedhub.ean import check_digit

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "generated"
SAMPLES_DIR = PROJECT_ROOT / "data" / "samples"
SAMPLE_DATE = date(2026, 1, 15)
SAMPLE_ROWS = {"NORD": 10, "EURO": 10, "REIF": 10, "SUD": 40}

CATALOGUE_SIZE = 500
SUPPLIERS = ["NORD", "EURO", "REIF", "SUD"]
FILE_NAMES = {
    "NORD": "stock_{:%Y%m%d}.csv",
    "EURO": "catalogue_{:%Y%m%d}.xml",
    "REIF": "offers_{:%Y%m%d}.json",
    "SUD": "export_{:%Y%m%d}.csv",
}

# Each supplier carries part of the catalogue. The overlap gives EANs sold by several suppliers.
ASSORTMENT_SHARE = {"NORD": 0.6, "EURO": 0.55, "REIF": 0.5, "SUD": 0.3}
PRICE_FACTOR = {"NORD": 1.0, "EURO": 0.96, "REIF": 1.04, "SUD": 0.98}
DELIVERY_DAYS = {"NORD": (1, 2), "EURO": (2, 4), "REIF": (3, 5), "SUD": (1, 3)}

# Invented brands, with a price factor (premium brands cost more).
BRANDS = {
    "Valtor": 1.3,
    "Norrim": 1.2,
    "Solvane": 1.1,
    "Kestra": 1.0,
    "Marbeck": 0.95,
    "Brisca": 0.9,
    "Ondura": 0.85,
    "Felvik": 0.8,
}
MODELS = {
    "summer": ["Aero", "Sportline", "Contour", "Velo"],
    "winter": ["Frost", "Nordic", "Alpin"],
    "all_season": ["Quattro", "Allyear", "Meridian"],
}
SIZES = {
    "car": [
        (165, 70, 14), (175, 65, 14), (185, 60, 15), (185, 65, 15), (195, 65, 15),
        (195, 55, 16), (205, 55, 16), (205, 60, 16), (215, 45, 17), (215, 55, 17),
        (225, 45, 17), (225, 50, 17), (225, 55, 17), (225, 40, 18), (235, 40, 18),
        (245, 40, 18), (245, 45, 19), (255, 35, 19),
    ],
    "suv": [
        (215, 65, 16), (215, 60, 17), (225, 65, 17), (235, 65, 17), (235, 55, 18),
        (235, 60, 18), (255, 55, 18), (235, 50, 19), (255, 50, 19), (255, 45, 20),
        (265, 45, 20), (275, 40, 20),
    ],
    "van": [(195, 75, 16), (205, 65, 16), (215, 65, 16), (215, 70, 15), (225, 65, 16), (235, 65, 16)],
}
LOAD_INDEX_RANGES = {"car": (82, 98), "suv": (98, 112), "van": (103, 115)}
SPEED_INDEXES = {"car": "HVWY", "suv": "HVW", "van": "RT"}

NORD_HEADERS = [
    "EAN", "Marque", "Modèle", "Dimension", "Saison", "Catégorie", "Bruit (dB)",
    "Classe énergie", "Adhérence sol mouillé", "Prix HT", "Stock", "Délai (jours)",
]
NORD_SEASONS = {"summer": "Été", "winter": "Hiver", "all_season": "4 saisons"}
NORD_VEHICLES = {"car": "Tourisme", "suv": "SUV", "van": "Utilitaire"}
EURO_SEASONS = {"summer": "S", "winter": "W", "all_season": "A"}
EURO_VEHICLES = {"car": "PCR", "suv": "SUV", "van": "LCV"}
REIF_SEASONS = {"summer": "Sommer", "winter": "Winter", "all_season": "Ganzjahr"}
REIF_VEHICLES = {"car": "PKW", "suv": "SUV", "van": "Transporter"}
SUD_HEADERS = ["CodeBarre", "Fabricant", "Désignation", "PU_HT", "Qté"]

COMMON_ERRORS = ["ean_invalid", "size_typo", "price_zero", "negative_stock", "missing_field", "duplicate"]
SCENARIO_SUPPLIER = {
    "truncated-file": "NORD",
    "price-crash": "EURO",
    "dirty-file": "EURO",
    "api-down": "REIF",
}
SCENARIOS = list(SCENARIO_SUPPLIER)
DIRTY_FILE_ERROR_RATE = 0.12


def make_ean(rng):
    # GS1 prefixes 200-299 are kept for internal use: no real product has them.
    first_12 = "2" + "".join(str(rng.randint(0, 9)) for _ in range(11))
    return first_12 + check_digit(first_12)


def make_product(rng, ean):
    vehicle_type = rng.choices(["car", "suv", "van"], weights=[6, 3, 1])[0]
    season = rng.choices(["summer", "winter", "all_season"], weights=[5, 3, 2])[0]
    width, aspect_ratio, rim_diameter = rng.choice(SIZES[vehicle_type])
    brand = rng.choice(list(BRANDS))

    speeds = SPEED_INDEXES[vehicle_type]
    if season == "winter" and vehicle_type != "van":
        speeds = "THV"
    low, high = LOAD_INDEX_RANGES[vehicle_type]

    price = 30 + (rim_diameter - 14) * 14 + (width - 155) * 0.3
    if vehicle_type != "car":
        price += 15
    price *= BRANDS[brand] * rng.uniform(0.9, 1.1)

    return {
        "ean": ean,
        "brand": brand,
        "model": f"{rng.choice(MODELS[season])} {rng.randint(2, 6)}",
        "width": width,
        "aspect_ratio": aspect_ratio,
        "rim_diameter": rim_diameter,
        "load_index": rng.randint(low, high),
        "speed_index": rng.choice(speeds),
        "season": season,
        "vehicle_type": vehicle_type,
        "noise_db": rng.randint(67, 74),
        "fuel_class": rng.choices("ABCDE", weights=[1, 3, 4, 2, 1])[0],
        "wet_grip_class": rng.choices("ABCDE", weights=[2, 4, 3, 1, 1])[0],
        "base_price": round(price, 2),
    }


def build_catalogue(rng, size=CATALOGUE_SIZE):
    used = set()
    products = []
    while len(products) < size:
        ean = make_ean(rng)
        if ean not in used:
            used.add(ean)
            products.append(make_product(rng, ean))
    return products


def assign_assortments(rng, catalogue):
    assortments = {code: [] for code in SUPPLIERS}
    for product in catalogue:
        for code in SUPPLIERS:
            if rng.random() < ASSORTMENT_SHARE[code]:
                assortments[code].append(product["ean"])
    return assortments


def initial_offers(rng, supplier, products, eans):
    low, high = DELIVERY_DAYS[supplier]
    offers = {}
    for ean in eans:
        price = products[ean]["base_price"] * PRICE_FACTOR[supplier] * rng.uniform(0.95, 1.05)
        stock = 0 if rng.random() < 0.1 else rng.randint(1, 60)
        offers[ean] = {"price": round(price, 2), "stock": stock, "delivery_days": rng.randint(low, high)}
    return offers


def initial_state(seed):
    rng = random.Random(seed)
    catalogue = build_catalogue(rng)
    products = {product["ean"]: product for product in catalogue}
    assortments = assign_assortments(rng, catalogue)
    offers = {code: initial_offers(rng, code, products, assortments[code]) for code in SUPPLIERS}
    listed = {code: set(assortments[code]) for code in SUPPLIERS}
    return rng, products, offers, listed


def next_day(rng, offers, listed):
    for ean, offer in offers.items():
        if rng.random() < 0.1:
            offer["price"] = round(offer["price"] * rng.uniform(0.97, 1.05), 2)
        offer["stock"] -= rng.randint(0, offer["stock"] // 4)
        if rng.random() < 0.15:
            offer["stock"] += rng.randint(10, 40)
        # A few references leave the file and come back later.
        if ean in listed:
            if rng.random() < 0.01:
                listed.remove(ean)
        elif rng.random() < 0.3:
            listed.add(ean)


def build_rows(products, offers, listed):
    return [{**products[ean], **offers[ean]} for ean in sorted(listed)]


def possible_errors(supplier, row):
    errors = list(COMMON_ERRORS)
    # Only the "Été" season has accents that a wrong encoding can break.
    if supplier == "NORD" and row["season"] == "summer":
        errors.append("broken_encoding")
    return errors


def apply_error(rng, row, error):
    if error == "ean_invalid":
        wrong_digit = (int(row["ean"][-1]) + rng.randint(1, 9)) % 10
        row["ean"] = row["ean"][:-1] + str(wrong_digit)
    elif error == "size_typo":
        # Letter O typed instead of a zero, a usual manual entry mistake.
        row["width"] = str(row["width"])[:-1] + "O"
    elif error == "price_zero":
        row["price"] = 0
    elif error == "negative_stock":
        row["stock"] = -rng.randint(1, 5)
    elif error == "missing_field":
        row["brand"] = ""
    elif error == "broken_encoding":
        row["broken_encoding"] = True


def add_errors(rng, supplier, rows, rate, day):
    count = max(1, round(len(rows) * rate))
    log = []
    copies = []
    for row in rng.sample(rows, count):
        error = rng.choice(possible_errors(supplier, row))
        log.append((day, supplier, row["ean"], error))
        if error == "duplicate":
            copy = dict(row)
            copy["stock"] = rng.randint(0, 60)
            copies.append(copy)
        else:
            apply_error(rng, row, error)
    for copy in copies:
        rows.insert(rng.randrange(len(rows) + 1), copy)
    return log


def crash_prices(rng, rows, share=0.25, factor=0.45):
    for row in rng.sample(rows, round(len(rows) * share)):
        row["price"] = round(row["price"] * factor, 2)


def size_text(row):
    return f'{row["width"]}/{row["aspect_ratio"]}R{row["rim_diameter"]} {row["load_index"]}{row["speed_index"]}'


def nord_text(rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(NORD_HEADERS)
    for row in rows:
        season = NORD_SEASONS[row["season"]]
        if row.get("broken_encoding"):
            # A line exported in UTF-8 inside a latin-1 file: "Été" is read as "Ã‰tÃ©".
            season = season.encode("utf-8").decode("latin-1")
        writer.writerow([
            row["ean"],
            row["brand"],
            row["model"],
            size_text(row),
            season,
            NORD_VEHICLES[row["vehicle_type"]],
            row["noise_db"],
            row["fuel_class"],
            row["wet_grip_class"],
            f'{row["price"]:.2f}'.replace(".", ","),
            row["stock"],
            row["delivery_days"],
        ])
    return buffer.getvalue()


def truncate_text(text, keep_share=0.4):
    lines = text.splitlines(keepends=True)
    keep = int(len(lines) * keep_share)
    # The transfer stops in the middle of a line, as with a cut connection.
    return "".join(lines[:keep]) + lines[keep][: len(lines[keep]) // 2]


def euro_xml(rows, day):
    root = ET.Element("catalogue", supplier="EURO", date=day.isoformat())
    for row in rows:
        product = ET.SubElement(root, "product")
        values = {
            "ean": row["ean"],
            "brand": row["brand"],
            "model": row["model"],
            "width": row["width"],
            "profile": row["aspect_ratio"],
            "rim": row["rim_diameter"],
            "loadIndex": row["load_index"],
            "speedRating": row["speed_index"],
            "season": EURO_SEASONS[row["season"]],
            "vehicle": EURO_VEHICLES[row["vehicle_type"]],
            "noise": row["noise_db"],
            "fuelClass": row["fuel_class"],
            "wetGrip": row["wet_grip_class"],
            "priceCents": round(row["price"] * 100),
            "stock": row["stock"],
            "leadTimeDays": row["delivery_days"],
        }
        for tag, value in values.items():
            ET.SubElement(product, tag).text = str(value)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def reif_json(rows, day):
    items = []
    for row in rows:
        items.append({
            "EAN": row["ean"],
            "Hersteller": row["brand"],
            "Modell": row["model"],
            "Breite": row["width"],
            "Querschnitt": row["aspect_ratio"],
            "Felge": row["rim_diameter"],
            "Lastindex": row["load_index"],
            "Geschwindigkeitsindex": row["speed_index"],
            "Saison": REIF_SEASONS[row["season"]],
            "Fahrzeugtyp": REIF_VEHICLES[row["vehicle_type"]],
            "Rollgeraeusch_dB": row["noise_db"],
            "Kraftstoffeffizienz": row["fuel_class"],
            "Nasshaftung": row["wet_grip_class"],
            "Preis": row["price"],
            "Bestand": row["stock"],
            "Lieferzeit_Tage": row["delivery_days"],
        })
    content = {"datum": day.isoformat(), "artikel": items}
    return json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")


def sud_text(rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(SUD_HEADERS)
    for row in rows:
        designation = f'PNEU {row["brand"]} {row["model"]} {size_text(row)}'.upper()
        writer.writerow([row["ean"], row["brand"], designation, f'{row["price"]:.2f}', row["stock"]])
    return buffer.getvalue()


def file_content(supplier, rows, day, truncated=False):
    if supplier == "NORD":
        text = nord_text(rows)
        if truncated:
            text = truncate_text(text)
        return text.encode("latin-1")
    if supplier == "EURO":
        return euro_xml(rows, day)
    if supplier == "REIF":
        return reif_json(rows, day)
    return sud_text(rows).encode("cp1252")


def active_scenarios(supplier, day_index, days, scenarios):
    # api-down lasts two days so that the last good data is more than 24 h old.
    first_index = {"api-down": days - 2}
    return {
        name for name in scenarios
        if SCENARIO_SUPPLIER[name] == supplier and day_index >= first_index.get(name, days - 1)
    }


def clear_output(output_dir):
    for code in SUPPLIERS:
        shutil.rmtree(output_dir / code.lower(), ignore_errors=True)


def write_injections(path, injections):
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["date", "supplier", "ean", "error"])
        for day, supplier, ean, error in injections:
            writer.writerow([day.isoformat(), supplier, ean, error])


def generate(output_dir, days, end_date, inject_errors=False, error_rate=0.02, scenarios=(), seed=42):
    """Write one file per supplier and per day, and return what was written."""
    rng, products, offers, listed = initial_state(seed)
    # Errors use their own generator, so the clean data stays the same with or without them.
    error_rng = random.Random(seed + 1)

    clear_output(output_dir)
    summary = []
    injections = []
    first_day = end_date - timedelta(days=days - 1)
    for day_index in range(days):
        day = first_day + timedelta(days=day_index)
        if day_index > 0:
            for code in SUPPLIERS:
                next_day(rng, offers[code], listed[code])

        for code in SUPPLIERS:
            active = active_scenarios(code, day_index, days, scenarios)
            for name in sorted(active):
                injections.append((day, code, "", name))
            if "api-down" in active:
                summary.append({"supplier": code, "day": day, "file": None, "rows": 0, "note": "api-down"})
                continue

            rows = build_rows(products, offers[code], listed[code])
            if "price-crash" in active:
                crash_prices(error_rng, rows)
            if inject_errors:
                injections += add_errors(error_rng, code, rows, error_rate, day)
            if "dirty-file" in active:
                injections += add_errors(error_rng, code, rows, DIRTY_FILE_ERROR_RATE, day)

            path = output_dir / code.lower() / FILE_NAMES[code].format(day)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(file_content(code, rows, day, truncated="truncated-file" in active))
            note = ", ".join(sorted(active))
            summary.append({"supplier": code, "day": day, "file": path, "rows": len(rows), "note": note})

    write_injections(output_dir / "injections.csv", injections)
    return summary, injections


def write_samples(samples_dir=SAMPLES_DIR, seed=42):
    """Write the small example files kept in the repository."""
    rng, products, offers, listed = initial_state(seed)
    paths = []
    for code in SUPPLIERS:
        rows = build_rows(products, offers[code], listed[code])[: SAMPLE_ROWS[code]]
        path = samples_dir / code.lower() / FILE_NAMES[code].format(SAMPLE_DATE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file_content(code, rows, SAMPLE_DATE))
        paths.append(path)
    return paths
