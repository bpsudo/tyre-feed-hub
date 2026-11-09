def check_digit(first_12):
    """Return the EAN-13 check digit of a string of 12 digits."""
    total = 0
    for position, char in enumerate(first_12):
        weight = 3 if position % 2 == 1 else 1
        total += int(char) * weight
    return str((10 - total % 10) % 10)


def is_valid_ean(value):
    # isdigit() alone accepts characters like "²", so isascii() is needed too.
    if len(value) != 13 or not value.isascii() or not value.isdigit():
        return False
    return value[-1] == check_digit(value[:12])
