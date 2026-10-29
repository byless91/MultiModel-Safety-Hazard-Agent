"""M4 management analytics contracts."""

from datetime import datetime

from pydantic import BaseModel, Field


class Bucket(BaseModel):
    value: str
    label: str | None = None
    count: int


class MonthCount(BaseModel):
    month: str
    count: int


class MapPoint(BaseModel):
    id: str
    description: str
    district: str | None = None
    facility: str | None = None
    scene: str | None = None
    risk_level: int | None = None
    latitude: float
    longitude: float
    coordinate_system: str | None = None
    map_latitude: float
    map_longitude: float
    event_time: datetime | None = None
    created_at: datetime


class AnalyticsOptionsOut(BaseModel):
    districts: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    facilities: list[str] = Field(default_factory=list)
    scenes: list[str] = Field(default_factory=list)


class AnalyticsOverviewOut(BaseModel):
    time_basis: str
    total: int
    by_district: list[Bucket] = Field(default_factory=list)
    by_category: list[Bucket] = Field(default_factory=list)
    by_risk: list[Bucket] = Field(default_factory=list)
    by_source: list[Bucket] = Field(default_factory=list)
    months: list[MonthCount] = Field(default_factory=list)
    map_points: list[MapPoint] = Field(default_factory=list)
    map_truncated: bool = False
    collected: list[Bucket] = Field(default_factory=list)
    notice: str


class BenchmarkItem(BaseModel):
    id: str
    description: str
    district: str | None = None
    facility: str | None = None
    scene: str | None = None
    hazard_category: str | None = None
    risk_level: int | None = None
    rectification_status: str | None = None
    rectification_note: str | None = None
    rectified_at: datetime | None = None
    event_time: datetime | None = None
    data_source: str | None = None
    match: str
    comparable: str


class BenchmarksOut(BaseModel):
    filters: dict[str, str | None]
    sample_size: int
    returned: int
    truncated: bool
    sources: list[Bucket] = Field(default_factory=list)
    items: list[BenchmarkItem] = Field(default_factory=list)
    notice: str
