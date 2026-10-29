"""M3 location, origin and event-time contract."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

DataSource = Literal["report", "public_case", "simulated"]
CoordinateSystem = Literal["wgs84", "gcj02", "bd09"]


def utc_event_time(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; event time is stored and returned as UTC."""
    if value is None:
        return value
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class LocationData(BaseModel):
    """Fields that describe where/when a record happened and how it was obtained."""

    model_config = ConfigDict(extra="forbid")

    address: str = Field(default="", max_length=512)
    district: str = Field(default="", max_length=128)
    facility: str = Field(default="", max_length=128)
    scene: str = Field(default="", max_length=128)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    coordinate_system: CoordinateSystem | None = None
    data_source: DataSource = "report"
    event_time: AwareDatetime | None = None

    @field_validator("address", "district", "facility", "scene", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("event_time")
    @classmethod
    def normalize_event_time(cls, value: datetime | None) -> datetime | None:
        return utc_event_time(value)

    @model_validator(mode="after")
    def coordinates_are_complete(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("经纬度须同时填写或同时留空")
        if self.latitude is not None and self.coordinate_system is None:
            raise ValueError("填写坐标时须选择坐标系")
        if self.latitude is None and self.coordinate_system is not None:
            raise ValueError("未填写坐标时不能指定坐标系")
        return self


class ImportRow(LocationData):
    source_ref: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=4000)
    data_source: DataSource

    @field_validator("source_ref", "description", mode="before")
    @classmethod
    def strip_required_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class ImportRowsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[object] = Field(min_length=1, max_length=500)


class ImportFailure(BaseModel):
    row: int
    source_ref: str | None = None
    reason: str


class ImportResultOut(BaseModel):
    batch_id: str
    imported: int
    duplicates: list[int] = Field(default_factory=list)
    failures: list[ImportFailure] = Field(default_factory=list)
