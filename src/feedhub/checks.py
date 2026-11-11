from feedhub.mapping import MappingError

REJECT_SEVERITY = "warning"
SIZE_FIELDS = {"size", "width", "aspect_ratio", "rim_diameter", "load_index", "speed_index"}


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
