import xml.etree.ElementTree as ET

import pytest

from feedhub.readers import read_csv, read_file, read_json, read_xml

XML = b"""<?xml version='1.0' encoding='utf-8'?>
<catalogue>
  <product><ean>2000000000015</ean><brand>Kestra</brand><model /></product>
  <product><ean>2000000000022</ean><brand>Norrim</brand></product>
  <info>not a product</info>
</catalogue>"""


def test_read_latin1_csv():
    content = "EAN;Saison\r\n2000000000015;Été\r\n".encode("latin-1")
    assert read_csv(content, "latin-1", ";") == [{"EAN": "2000000000015", "Saison": "Été"}]


def test_cut_line_gives_empty_values():
    content = b"EAN;Prix;Stock\r\n2000000000015;59,90;4\r\n2000000000022;5"
    rows = read_csv(content, "latin-1", ";")
    assert rows[1] == {"EAN": "2000000000022", "Prix": "5", "Stock": None}


def test_wrong_encoding_fails():
    with pytest.raises(UnicodeDecodeError):
        read_csv("Saison\r\nÉté\r\n".encode("cp1252"), "utf-8")


def test_read_xml_records():
    rows = read_xml(XML, "product")
    assert rows == [
        {"ean": "2000000000015", "brand": "Kestra", "model": None},
        {"ean": "2000000000022", "brand": "Norrim"},
    ]


def test_cut_xml_fails():
    with pytest.raises(ET.ParseError):
        read_xml(XML[:120], "product")


def test_read_json_records_path():
    content = '{"data": {"items": [{"EAN": "2000000000015", "Preis": 59.9}]}}'.encode("utf-8")
    assert read_json(content, records="data.items") == [{"EAN": "2000000000015", "Preis": 59.9}]
    assert read_json(b'[{"a": 1}]') == [{"a": 1}]


def test_json_records_must_be_a_list():
    with pytest.raises(ValueError, match="does not point to a list"):
        read_json(b'{"artikel": {"EAN": "1"}}', records="artikel")


def test_read_file_picks_the_format():
    assert len(read_file(XML, {"format": "xml", "file": {"records": "product"}})) == 2
    assert read_file(b'{"artikel": []}', {"format": "json", "file": {"records": "artikel"}}) == []


def test_unsupported_format():
    with pytest.raises(ValueError, match="unsupported format"):
        read_file(b"", {"format": "xlsx"})
