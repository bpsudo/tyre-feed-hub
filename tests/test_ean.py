from feedhub.ean import check_digit, is_valid_ean


def test_check_digit():
    assert check_digit("200000000001") == "5"


def test_valid_ean():
    assert is_valid_ean("2000000000015")


def test_wrong_check_digit():
    assert not is_valid_ean("2000000000016")


def test_wrong_length():
    assert not is_valid_ean("200000000015")


def test_letters_are_refused():
    assert not is_valid_ean("20000000000A5")


def test_non_ascii_digit_is_refused():
    assert not is_valid_ean("200000000001²")
