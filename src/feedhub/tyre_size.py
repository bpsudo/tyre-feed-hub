import re
from typing import NamedTuple

# "205/55 R16 91V", "205/55R16", "225/40 ZR18 92Y": the load and speed part is optional.
SIZE_PATTERN = re.compile(
    r"(?<!\d)(\d{3})\s*/\s*(\d{2})\s*Z?R\s*(\d{2})(?:\s+(\d{2,3})\s*([A-Z]))?(?![\dA-Z])",
    re.IGNORECASE,
)
SPEED_INDEXES = "LMNPQRSTUHVWY"


class TyreSize(NamedTuple):
    width: int
    aspect_ratio: int
    rim_diameter: int
    load_index: int | None = None
    speed_index: str | None = None


def is_plausible(width, aspect_ratio, rim_diameter):
    # Tyre widths always end in 5 (195, 205...) and aspect ratios go by steps of 5.
    return (
        125 <= width <= 355 and width % 10 == 5
        and 25 <= aspect_ratio <= 85 and aspect_ratio % 5 == 0
        and 12 <= rim_diameter <= 24
    )


def size_from_match(match):
    width, aspect_ratio, rim_diameter = int(match[1]), int(match[2]), int(match[3])
    if not is_plausible(width, aspect_ratio, rim_diameter):
        return None
    if match[4] is None:
        return TyreSize(width, aspect_ratio, rim_diameter)
    speed_index = match[5].upper()
    if speed_index not in SPEED_INDEXES:
        return None
    return TyreSize(width, aspect_ratio, rim_diameter, int(match[4]), speed_index)


def parse_size(text):
    """Read a text that is only a size, like "205/55 R16 91V". Return None if unreadable."""
    match = SIZE_PATTERN.fullmatch(text.strip())
    return size_from_match(match) if match else None


def find_size(text):
    """Find a size inside a longer text, like a product description."""
    match = SIZE_PATTERN.search(text)
    return size_from_match(match) if match else None


def format_size(width, aspect_ratio, rim_diameter):
    return f"{width}/{aspect_ratio} R{rim_diameter}"
