import tomllib

from feedhub.db import PROJECT_ROOT
from feedhub.tyre_size import find_size, parse_size

CONFIG_DIR = PROJECT_ROOT / "config" / "suppliers"
VALUE_MAPS = {"season": "season_map", "vehicle_type": "vehicle_map"}


class MappingError(ValueError):
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def supplier_codes(config_dir=CONFIG_DIR):
    return sorted(path.stem.upper() for path in config_dir.glob("*.toml"))


def load_mapping(code, config_dir=CONFIG_DIR):
    with open(config_dir / f"{code.lower()}.toml", "rb") as file:
        return tomllib.load(file)


def set_size(row, field, size):
    if size is None:
        raise MappingError(field, f"unreadable size {row[field]!r}")
    del row[field]
    row.update({key: value for key, value in size._asdict().items() if value is not None})


def apply_transform(row, field, transform):
    value = row[field]
    if transform == "decimal_comma":
        row[field] = value.replace(" ", "").replace(",", ".")
    elif transform == "cents_to_eur":
        if not str(value).isdigit():
            raise MappingError(field, f"not a number of cents: {value!r}")
        row[field] = int(value) / 100
    elif transform == "size_combined":
        set_size(row, field, parse_size(value))
    elif transform == "extract_size_from_text":
        set_size(row, field, find_size(value))
    else:
        raise ValueError(f"unknown transform: {transform}")


def map_row(raw, mapping):
    """Turn a raw supplier row into the fields of NormalizedOffer."""
    row = {}
    for field, column in mapping["columns"].items():
        value = raw.get(column)
        if isinstance(value, str):
            value = value.strip()
        # An empty cell counts as a missing value.
        if value is None or value == "":
            continue
        row[field] = value

    for field, transform in mapping.get("transforms", {}).items():
        if field in row:
            apply_transform(row, field, transform)

    for field, table in VALUE_MAPS.items():
        if field in row and table in mapping:
            if row[field] not in mapping[table]:
                raise MappingError(field, f"unknown value {row[field]!r}")
            row[field] = mapping[table][row[field]]
    return row
