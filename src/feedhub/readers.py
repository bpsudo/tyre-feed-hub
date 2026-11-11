import csv
import io
import json
import xml.etree.ElementTree as ET


def read_csv(content, encoding="utf-8", delimiter=","):
    """Return the rows of a CSV file as dictionaries keyed by column name."""
    text = content.decode(encoding)
    return list(csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter))


def read_xml(content, records):
    """Return one dictionary {tag: text} per element matching the records path."""
    # The parser reads the encoding from the XML declaration.
    root = ET.fromstring(content)
    return [{child.tag: child.text for child in record} for record in root.iterfind(records)]


def read_json(content, encoding="utf-8", records=None):
    """Return the list found at the records path, for example "artikel" or "data.items"."""
    data = json.loads(content.decode(encoding))
    for key in records.split(".") if records else []:
        data = data[key]
    if not isinstance(data, list):
        raise ValueError(f"records path {records!r} does not point to a list")
    return data


def read_file(content, mapping):
    settings = mapping.get("file", {})
    file_format = mapping["format"]
    encoding = settings.get("encoding", "utf-8")
    if file_format == "csv":
        return read_csv(content, encoding, settings.get("delimiter", ","))
    if file_format == "xml":
        return read_xml(content, settings["records"])
    if file_format == "json":
        return read_json(content, encoding, settings.get("records"))
    raise ValueError(f"unsupported format: {file_format}")
