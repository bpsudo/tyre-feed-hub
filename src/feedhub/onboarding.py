"""Reads a sample file from an unknown supplier and proposes a mapping file for it."""
import csv
import json
import re
import statistics
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date
from pathlib import Path

from feedhub import readers
from feedhub.checks import readable_text
from feedhub.db import PROJECT_ROOT
from feedhub.ean import is_valid_ean
from feedhub.generator import BRANDS
from feedhub.mapping import CONFIG_DIR
from feedhub.pipeline import validate_rows
from feedhub.tyre_size import SPEED_INDEXES, find_size, parse_size

DOCS_DIR = PROJECT_ROOT / "docs" / "fournisseurs"
ENCODINGS = ["utf-8", "cp1252", "latin-1"]
SAMPLE_ROWS = 200
MIN_CONFIDENCE = 0.5
VALUE_WEIGHT = 0.8
NAME_BONUS = 0.2
NAME_ONLY_CONFIDENCE = 0.6

FIELD_LABELS = {
    "ean": "EAN",
    "brand": "Marque",
    "model": "Modèle",
    "size": "Dimension complète",
    "width": "Largeur",
    "aspect_ratio": "Série",
    "rim_diameter": "Jante",
    "load_index": "Indice de charge",
    "speed_index": "Indice de vitesse",
    "season": "Saison",
    "vehicle_type": "Type de véhicule",
    "noise_db": "Bruit (dB)",
    "fuel_class": "Classe énergie",
    "wet_grip_class": "Adhérence sol mouillé",
    "price_eur": "Prix d'achat HT",
    "stock": "Stock",
    "delivery_days": "Délai (jours)",
}
FIELDS = list(FIELD_LABELS)
SIZE_PARTS = ["width", "aspect_ratio", "rim_diameter"]

# Column names, written without accents, spaces or case (see normalize).
SYNONYMS = {
    "ean": ["ean", "ean13", "gtin", "codebarre", "codeean", "barcode", "streepjescode"],
    "brand": ["marque", "brand", "hersteller", "marke", "merk", "fabricant", "manufacturer"],
    "model": ["modele", "model", "modell", "profilname"],
    "size": ["dimension", "taille", "size", "groesse", "maat", "afmeting", "designation", "description",
             "bezeichnung", "omschrijving", "libelle"],
    "width": ["largeur", "width", "breite", "breedte"],
    "aspect_ratio": ["serie", "hauteur", "profile", "aspectratio", "querschnitt", "hoogte"],
    "rim_diameter": ["jante", "rim", "felge", "velg", "diametre", "diameter", "zoll"],
    "load_index": ["indicecharge", "loadindex", "lastindex", "belastingindex", "li"],
    "speed_index": ["indicevitesse", "speedindex", "speedrating", "geschwindigkeitsindex", "snelheidsindex", "si"],
    "season": ["saison", "season", "jahreszeit", "seizoen"],
    "vehicle_type": ["categorie", "vehicle", "vehicletype", "fahrzeugtyp", "voertuig"],
    "noise_db": ["bruit", "noise", "rollgeraeusch", "geluid"],
    "fuel_class": ["classeenergie", "fuelclass", "kraftstoffeffizienz", "brandstof"],
    "wet_grip_class": ["adherence", "wetgrip", "nasshaftung", "natgrip"],
    "price_eur": ["prix", "puht", "price", "preis", "prijs", "tarif", "ek"],
    "stock": ["stock", "qte", "quantite", "quantity", "qty", "bestand", "voorraad", "menge"],
    "delivery_days": ["delai", "leadtime", "lieferzeit", "levertijd"],
}

# Known values of the translated fields, written as normalize() returns them.
KNOWN_VALUES = {
    "season": {
        "ete": "summer", "summer": "summer", "sommer": "summer", "zomer": "summer", "s": "summer",
        "hiver": "winter", "winter": "winter", "w": "winter",
        "4saisons": "all_season", "toutessaisons": "all_season", "allseason": "all_season",
        "allseasons": "all_season", "ganzjahr": "all_season", "ganzjahres": "all_season",
        "vierseizoenen": "all_season", "a": "all_season",
    },
    "vehicle_type": {
        "tourisme": "car", "car": "car", "pkw": "car", "pcr": "car", "personenwagen": "car",
        "suv": "suv", "4x4": "suv",
        "utilitaire": "van", "van": "van", "lcv": "van", "transporter": "van", "bestelwagen": "van",
    },
}
VALUE_MAPS = {"season": "season_map", "vehicle_type": "vehicle_map"}


def normalize(text):
    """'Délai (jours)' -> 'delaijours': no accent, no case, letters and digits only."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def name_matches(column, field):
    name = normalize(column)
    # Short synonyms such as "li" must match the whole name, longer ones can be part of it.
    return any(name == word or (len(word) >= 4 and word in name) for word in SYNONYMS[field])


# Detection of the file

def detect_encoding(content):
    if content.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for encoding in ENCODINGS:
        try:
            content.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin-1"


def detect_format(text, file_name):
    start = text.lstrip()[:1]
    if start == "<":
        return "xml"
    if start in ("{", "["):
        return "json"
    extension = Path(file_name).suffix.lower().lstrip(".")
    return extension if extension in ("xml", "json") else "csv"


def detect_delimiter(text):
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        header = text.splitlines()[0] if text else ""
        return max(";,\t|", key=header.count)


def xml_record_paths(element, path=""):
    """(path, count) for each repeated tag whose elements have children."""
    found = []
    counts = Counter(child.tag for child in element if len(child))
    for tag, count in counts.items():
        found.append((f"{path}{tag}", count))
    for tag in {child.tag for child in element if len(child)}:
        first = element.find(tag)
        found += xml_record_paths(first, f"{path}{tag}/")
    return found


def detect_xml_records(content):
    paths = xml_record_paths(ET.fromstring(content))
    if not paths:
        raise ValueError("no repeated element with fields found in the XML file")
    return max(paths, key=lambda item: item[1])[0]


def json_record_paths(data, path=""):
    found = []
    if isinstance(data, list) and data and all(isinstance(item, dict) for item in data):
        found.append((path, len(data)))
    if isinstance(data, dict):
        for key, value in data.items():
            found += json_record_paths(value, f"{path}.{key}" if path else key)
    return found


def detect_json_records(text):
    paths = json_record_paths(json.loads(text))
    if not paths:
        raise ValueError("no list of objects found in the JSON file")
    return max(paths, key=lambda item: item[1])[0]


def file_pattern(file_name):
    """stock_20260115.csv -> stock_*.csv, so that the next days are found too."""
    pattern = re.sub(r"\d{4}-?\d{2}-?\d{2}", "*", file_name)
    if pattern == file_name:
        path = Path(file_name)
        pattern = f"{path.stem}*{path.suffix}"
    return pattern


# Scores of the columns

def as_int(value):
    return int(value) if re.fullmatch(r"\d+", value) else None


def int_between(value, low, high):
    number = as_int(value)
    return number is not None and low <= number <= high


def as_number(value):
    try:
        return float(value.replace(" ", "").replace("€", "").replace(",", "."))
    except ValueError:
        return None


def value_tests(known_brands):
    return {
        "ean": is_valid_ean,
        "brand": lambda v: v.casefold() in known_brands,
        "size": lambda v: find_size(v) is not None,
        "width": lambda v: int_between(v, 125, 355) and v.endswith("5"),
        "aspect_ratio": lambda v: int_between(v, 25, 85) and int(v) % 5 == 0,
        "rim_diameter": lambda v: int_between(v, 12, 24),
        "load_index": lambda v: int_between(v, 50, 130),
        "speed_index": lambda v: len(v) == 1 and v.upper() in SPEED_INDEXES,
        "season": lambda v: normalize(v) in KNOWN_VALUES["season"],
        "vehicle_type": lambda v: normalize(v) in KNOWN_VALUES["vehicle_type"],
        "noise_db": lambda v: int_between(v, 50, 90),
        "fuel_class": lambda v: v.upper() in ("A", "B", "C", "D", "E"),
        "wet_grip_class": lambda v: v.upper() in ("A", "B", "C", "D", "E"),
        "stock": lambda v: int_between(v, 0, 100000),
        "delivery_days": lambda v: int_between(v, 0, 60),
    }


def price_check(values):
    """Share of plausible prices, and the transform the column needs."""
    if all(as_int(v) is not None for v in values) and statistics.median(int(v) for v in values) >= 1000:
        # Whole numbers in the thousands: prices in cents (2848 = 28.48 EUR).
        share = sum(1 <= int(v) / 100 <= 3000 for v in values) / len(values)
        return share, "cents_to_eur"
    numbers = [as_number(v) for v in values]
    share = sum(n is not None and 1 <= n <= 3000 for n in numbers) / len(values)
    # A price usually has decimals; a column of whole numbers is more likely a stock.
    if sum(("." in v or "," in v) for v in values) < len(values) / 2:
        share /= 2
    return share, "decimal_comma" if any("," in v for v in values) else None


def size_transform(values):
    found = [v for v in values if find_size(v) is not None]
    if found and all(parse_size(v) is not None for v in found):
        return "size_combined"
    return "extract_size_from_text"


def column_scores(column, values, tests):
    """Confidence between 0 and 1 for each field. values: the non-empty values of the column."""
    scores = {}
    for field in FIELDS:
        bonus = NAME_BONUS if name_matches(column, field) else 0
        if not values:
            scores[field] = 0
        elif field == "price_eur":
            scores[field] = price_check(values)[0] * VALUE_WEIGHT + bonus
        elif field in tests:
            share = sum(bool(tests[field](v)) for v in values) / len(values)
            scores[field] = share * VALUE_WEIGHT + bonus
        else:
            scores[field] = NAME_ONLY_CONFIDENCE if bonus else 0
    return {field: round(score, 2) for field, score in scores.items()}


def propose_columns(columns, scores):
    """Give each field the column with the best score, each column being used once."""
    pairs = sorted(
        ((scores[c][f], -i, -FIELDS.index(f), c, f) for i, c in enumerate(columns) for f in FIELDS),
        reverse=True,
    )
    proposal = {}
    used = set()
    for score, _, _, column, field in pairs:
        if score < MIN_CONFIDENCE or column in used or field in proposal:
            continue
        # A full size column already gives width, aspect ratio and rim.
        if field in SIZE_PARTS and "size" in proposal:
            continue
        if field == "size" and any(part in proposal for part in SIZE_PARTS):
            continue
        proposal[field] = column
        used.add(column)
    return {field: proposal[field] for field in FIELDS if field in proposal}


def read_sample(content, file_name):
    """Detect how to read the file and return (file settings, format, rows)."""
    encoding = detect_encoding(content)
    text = content.decode(encoding)
    file_format = detect_format(text, file_name)
    settings = {"encoding": encoding}
    if file_format == "csv":
        settings["delimiter"] = detect_delimiter(text)
    elif file_format == "xml":
        settings = {"records": detect_xml_records(content)}
    else:
        settings["records"] = detect_json_records(text)
    rows = readers.read_file(content, {"format": file_format, "file": settings})
    return settings, file_format, rows


def column_values(rows, column):
    values = []
    for row in rows[:SAMPLE_ROWS]:
        value = row.get(column)
        if value is not None and str(value).strip() != "":
            values.append(str(value).strip())
    return values


def analyze(content, file_name, known_brands=()):
    """Detect the format of a sample file and propose a mapping, with a confidence per field."""
    settings, file_format, rows = read_sample(content, file_name)
    columns = list(dict.fromkeys(key for row in rows[:SAMPLE_ROWS] for key in row))
    tests = value_tests({brand.casefold() for brand in [*BRANDS, *known_brands]})
    values = {column: column_values(rows, column) for column in columns}
    scores = {column: column_scores(column, values[column], tests) for column in columns}
    return {
        "file_name": file_name,
        "format": file_format,
        "file": settings,
        "row_count": len(rows),
        "columns": columns,
        "values": values,
        "scores": scores,
        "proposal": propose_columns(columns, scores),
    }


# Mapping file

def default_transforms(analysis, columns):
    transforms = {}
    if "size" in columns:
        transforms["size"] = size_transform(analysis["values"][columns["size"]])
    if "price_eur" in columns and analysis["values"][columns["price_eur"]]:
        transform = price_check(analysis["values"][columns["price_eur"]])[1]
        if transform:
            transforms["price_eur"] = transform
    return transforms


def value_maps(analysis, columns):
    """Translation tables of the season and vehicle columns, and the values not understood."""
    maps = {}
    unknown = []
    for field, table in VALUE_MAPS.items():
        if field not in columns:
            continue
        maps[table] = {}
        for value in dict.fromkeys(analysis["values"][columns[field]]):
            known = KNOWN_VALUES[field].get(normalize(value))
            if known:
                maps[table][value] = known
            else:
                unknown.append((field, value))
    return maps, unknown


def build_mapping(analysis, code, name, columns, transforms=None):
    """The content of config/suppliers/<code>.toml, as a dictionary."""
    columns = {field: columns[field] for field in FIELDS if columns.get(field)}
    if transforms is None:
        transforms = default_transforms(analysis, columns)
    transforms = {field: value for field, value in transforms.items() if value and field in columns}
    maps, _ = value_maps(analysis, columns)
    mapping = {
        "code": code,
        "name": name,
        "protocol": "file",
        "format": analysis["format"],
        "source": {
            "local_dir": f"data/generated/{code.lower()}",
            "file_pattern": file_pattern(analysis["file_name"]),
        },
        "file": dict(analysis["file"]),
        "columns": columns,
    }
    if transforms:
        mapping["transforms"] = transforms
    mapping.update({table: values for table, values in maps.items() if values})
    return mapping


def missing_fields(columns):
    missing = [field for field in ("ean", "brand", "price_eur", "stock") if not columns.get(field)]
    if not columns.get("size") and not all(columns.get(part) for part in SIZE_PARTS):
        missing.append("size")
    return missing


def dry_run(content, mapping, error_count=10):
    """Read and check the file with the mapping, without writing anything to the database."""
    rows = readers.read_file(content, mapping)
    offers, anomalies, rejected = validate_rows(rows, mapping)
    return {
        "rows_read": len(rows),
        "valid": len(offers),
        "rejected": rejected,
        "reject_pct": round(100 * rejected / len(rows), 1) if rows else 0,
        "errors": [(rule, readable_text(details)) for _, rule, _, details in anomalies[:error_count]],
    }


def toml_key(key):
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key, ensure_ascii=False)


def toml_value(value):
    # A JSON string is also a valid TOML string.
    return json.dumps(value, ensure_ascii=False) if isinstance(value, str) else str(value)


def mapping_to_toml(mapping):
    lines = [f"# Written by the new supplier page on {date.today().isoformat()}."]
    tables = []
    for key, value in mapping.items():
        if isinstance(value, dict):
            tables.append((key, value))
        else:
            lines.append(f"{toml_key(key)} = {toml_value(value)}")
    for key, table in tables:
        lines += ["", f"[{key}]"]
        lines += [f"{toml_key(name)} = {toml_value(value)}" for name, value in table.items()]
    return "\n".join(lines) + "\n"


FORMAT_LABELS = {"csv": "CSV", "xml": "XML", "json": "JSON"}
PROTOCOL_LABELS = {
    "file": "fichier déposé dans un dossier",
    "sftp": "SFTP",
    "rest_api": "API REST",
}


def supplier_doc(mapping):
    """The supplier sheet docs/fournisseurs/<code>.md, to complete by hand."""
    settings = mapping.get("file", {})
    source = mapping.get("source", {})
    reading = [f"format {FORMAT_LABELS.get(mapping['format'], mapping['format'])}"]
    if "encoding" in settings:
        reading.append(f"encodage {settings['encoding']}")
    if "delimiter" in settings:
        reading.append(f"séparateur `{settings['delimiter']}`")
    if "records" in settings:
        reading.append(f"enregistrements dans `{settings['records']}`")

    lines = [
        f"# {mapping['name']} ({mapping['code']})",
        "",
        f"Fiche créée le {date.today().isoformat()}. Les lignes « à compléter » sont à remplir à la main.",
        "",
        "## Accès",
        "",
        f"- Protocole : {PROTOCOL_LABELS.get(mapping['protocol'], mapping['protocol'])}",
        f"- Fichiers attendus : `{source.get('file_pattern', '-')}`",
    ]
    if source.get("local_dir"):
        lines.append(f"- Dossier local : `{source['local_dir']}`")
    for key in ("host_env", "url_env", "key_env", "user_env", "password_env"):
        if key in source:
            lines.append(f"- Variable d'environnement : `{source[key]}`")
    lines += [
        "- Contact technique chez le fournisseur : à compléter",
        "- Heure d'envoi habituelle : à compléter",
        "",
        "## Lecture du fichier",
        "",
        "- " + ", ".join(reading),
        f"- Fichier de mapping : `config/suppliers/{mapping['code'].lower()}.toml`",
        "",
        "## Correspondance des colonnes",
        "",
        "| Champ | Colonne du fournisseur | Transformation |",
        "|---|---|---|",
    ]
    transforms = mapping.get("transforms", {})
    for field, column in mapping["columns"].items():
        label = FIELD_LABELS.get(field, field)
        lines.append(f"| {label} | `{column}` | {transforms.get(field, '')} |")
    for field, table in VALUE_MAPS.items():
        if mapping.get(table):
            lines += ["", f"## Valeurs de « {FIELD_LABELS[field]} »", "", "| Fournisseur | Valeur retenue |",
                      "|---|---|"]
            lines += [f"| `{raw}` | {value} |" for raw, value in mapping[table].items()]
    lines += [
        "",
        "## Particularités connues",
        "",
        "- à compléter",
        "",
        "## Historique",
        "",
        f"- {date.today().isoformat()} : intégration du fournisseur.",
        "",
    ]
    return "\n".join(lines)


def save_supplier_files(mapping, config_dir=CONFIG_DIR, docs_dir=DOCS_DIR):
    """Write the mapping file and the supplier sheet. Never overwrites an existing file."""
    code = mapping["code"].lower()
    config_path = Path(config_dir) / f"{code}.toml"
    doc_path = Path(docs_dir) / f"{code}.md"
    for path in (config_path, doc_path):
        if path.exists():
            raise FileExistsError(f"{path} already exists")
    config_path.write_text(mapping_to_toml(mapping), encoding="utf-8", newline="\n")
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(supplier_doc(mapping), encoding="utf-8", newline="\n")
    return config_path, doc_path
