from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from feedhub.ean import is_valid_ean
from feedhub.tyre_size import is_plausible

LabelClass = Literal["A", "B", "C", "D", "E"]


class NormalizedOffer(BaseModel):
    """One supplier row after mapping, ready to be loaded."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    ean: str
    brand: str = Field(min_length=1)
    model: str | None = None
    width: int
    aspect_ratio: int
    rim_diameter: int
    load_index: int | None = Field(None, ge=50, le=130)
    speed_index: str | None = Field(None, pattern=r"^[LMNPQRSTUHVWY]$")
    season: Literal["summer", "winter", "all_season"] | None = None
    vehicle_type: Literal["car", "suv", "van"] | None = None
    noise_db: int | None = Field(None, ge=50, le=90)
    fuel_class: LabelClass | None = None
    wet_grip_class: LabelClass | None = None
    # Without allow_inf_nan=False, the text "inf" would be a valid price.
    price_eur: float = Field(allow_inf_nan=False)
    stock: int = Field(ge=0)
    delivery_days: int | None = Field(None, ge=0)

    @field_validator("ean")
    @classmethod
    def check_ean(cls, value):
        if not is_valid_ean(value):
            raise ValueError("invalid EAN-13")
        return value

    @field_validator("price_eur")
    @classmethod
    def check_price(cls, value):
        value = round(value, 2)
        # Checked after rounding, otherwise 0.004 would be loaded as 0.00.
        if value <= 0:
            raise ValueError("price must be greater than 0")
        return value

    @model_validator(mode="after")
    def check_size(self):
        if not is_plausible(self.width, self.aspect_ratio, self.rim_diameter):
            raise ValueError("implausible tyre size")
        return self
