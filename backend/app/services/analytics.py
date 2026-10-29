"""M4 confirmed-record analytics: distributions, trend, map points and rectification benchmarks."""

import math
from collections import Counter
from datetime import UTC, date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Assessment
from app.schemas.location import utc_event_time

UNFILLED = "未填写"
TIME_BASIS = "event_time_else_created_at"
MAP_POINT_LIMIT = 500
RISK_LABELS = {"1": "一级（高）", "2": "二级（中）", "3": "三级（较低）", "ungraded": "未分级"}
DATA_SOURCE_LABELS = {"report": "现场上报", "public_case": "公开案例", "simulated": "模拟数据", "unknown": "未标注"}
COMPARABLE_LABELS = {"both": "设施与场景一致", "facility": "仅设施一致", "scene": "仅场景一致"}

_GCJ_A = 6378245.0
_GCJ_EE = 0.00669342162296594323
_X_PI = math.pi * 3000.0 / 180.0


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def record_time(item: Assessment) -> datetime:
    return _as_utc(item.event_time or item.created_at)


def month_key(value: datetime) -> str:
    return _as_utc(value).strftime("%Y-%m")


def parse_month(value: str) -> date:
    try:
        year, month = int(value[:4]), int(value[5:])
    except (TypeError, ValueError) as exc:
        raise ValueError("月份须为 YYYY-MM") from exc
    if not 1 <= month <= 12:
        raise ValueError("月份须为 YYYY-MM")
    return date(year, month, 1)


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)


def _month_keys(first: date, last: date) -> list[str]:
    keys = []
    current = first
    while current <= last:
        keys.append(f"{current.year:04d}-{current.month:02d}")
        current = _next_month(current)
    return keys


def _out_of_china(lat: float, lng: float) -> bool:
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(lng: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320.0 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 * math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lng: float) -> tuple[float, float]:
    if _out_of_china(lat, lng):
        return lat, lng
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = 1 - _GCJ_EE * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_GCJ_A * (1 - _GCJ_EE)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (_GCJ_A / sqrtmagic * math.cos(radlat) * math.pi)
    return lat + dlat, lng + dlng


def gcj02_to_wgs84(lat: float, lng: float) -> tuple[float, float]:
    if _out_of_china(lat, lng):
        return lat, lng
    wlat, wlng = lat, lng
    for _ in range(5):
        glat, glng = wgs84_to_gcj02(wlat, wlng)
        wlat -= glat - lat
        wlng -= glng - lng
    return wlat, wlng


def bd09_to_wgs84(lat: float, lng: float) -> tuple[float, float]:
    x, y = lng - 0.0065, lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * _X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * _X_PI)
    return gcj02_to_wgs84(z * math.sin(theta), z * math.cos(theta))


def to_wgs84(lat: float, lng: float, system: str | None) -> tuple[float, float]:
    if system == "gcj02":
        return gcj02_to_wgs84(lat, lng)
    if system == "bd09":
        return bd09_to_wgs84(lat, lng)
    return lat, lng


def _buckets(counts: Counter, labels: dict[str, str] | None = None) -> list[dict]:
    labels = labels or {}
    return [
        {"value": value, "label": labels.get(value, value), "count": count}
        for value, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]


def _confirmed_query(district: str | None, category: str | None, facility: str | None,
                     scene: str | None, start: date | None, end: date | None):
    query = select(Assessment).where(Assessment.confirmed.is_(True))
    if district:
        query = query.where(Assessment.district == district)
    if category:
        query = query.where(Assessment.hazard_category == category)
    if facility:
        query = query.where(Assessment.facility == facility)
    if scene:
        query = query.where(Assessment.scene == scene)
    time_expr = func.coalesce(Assessment.event_time, Assessment.created_at)
    if start:
        query = query.where(time_expr >= datetime(start.year, start.month, 1, tzinfo=UTC))
    if end:
        following = _next_month(end)
        query = query.where(time_expr < datetime(following.year, following.month, 1, tzinfo=UTC))
    return query


def analytics_options(db: Session) -> dict:
    rows = db.scalars(select(Assessment).where(Assessment.confirmed.is_(True))).all()

    def distinct(values) -> list[str]:
        return sorted({value for value in values if value})

    return {
        "districts": distinct(item.district for item in rows),
        "categories": distinct(item.hazard_category for item in rows),
        "facilities": distinct(item.facility for item in rows),
        "scenes": distinct(item.scene for item in rows),
    }


def analytics_overview(db: Session, *, district: str | None = None, category: str | None = None,
                       facility: str | None = None, scene: str | None = None,
                       start: str | None = None, end: str | None = None) -> dict:
    start_date = parse_month(start) if start else None
    end_date = parse_month(end) if end else None
    if start_date and end_date and start_date > end_date:
        raise ValueError("开始月份不能晚于结束月份")
    rows = db.scalars(_confirmed_query(
        district, category, facility, scene, start_date, end_date,
    )).all()

    districts = Counter(item.district or UNFILLED for item in rows)
    categories = Counter(item.hazard_category or UNFILLED for item in rows)
    sources = Counter(item.data_source or "unknown" for item in rows)
    risk = {"1": 0, "2": 0, "3": 0, "ungraded": 0}
    for item in rows:
        risk[str(item.risk_level) if item.risk_level in (1, 2, 3) else "ungraded"] += 1

    month_counts = Counter(month_key(record_time(item)) for item in rows)
    if start_date:
        first = start_date
    elif month_counts:
        first = parse_month(min(month_counts))
    else:
        first = end_date
    if end_date:
        last = end_date
    elif month_counts:
        last = parse_month(max(month_counts))
    else:
        last = first
    months = [{"month": key, "count": month_counts.get(key, 0)}
              for key in _month_keys(first, last)] if first and last else []

    points = []
    for item in rows:
        if item.latitude is None or item.longitude is None:
            continue
        map_lat, map_lng = to_wgs84(item.latitude, item.longitude, item.coordinate_system)
        points.append({
            "id": item.id, "description": item.description, "district": item.district,
            "facility": item.facility, "scene": item.scene, "risk_level": item.risk_level,
            "latitude": item.latitude, "longitude": item.longitude,
            "coordinate_system": item.coordinate_system,
            "map_latitude": map_lat, "map_longitude": map_lng,
            "event_time": utc_event_time(item.event_time), "created_at": utc_event_time(item.created_at),
        })

    collected_rows = db.execute(
        select(Assessment.data_source, func.count()).where(Assessment.status == "imported")
        .group_by(Assessment.data_source)
    ).all()
    collected = [
        {"value": source or "unknown", "label": DATA_SOURCE_LABELS.get(source or "", "未标注"), "count": count}
        for source, count in sorted(collected_rows, key=lambda pair: -pair[1])
    ]

    return {
        "time_basis": TIME_BASIS,
        "total": len(rows),
        "by_district": _buckets(districts),
        "by_category": _buckets(categories),
        "by_risk": [
            {"value": value, "label": label, "count": risk[value]}
            for value, label in RISK_LABELS.items()
        ],
        "by_source": _buckets(sources, DATA_SOURCE_LABELS),
        "months": months,
        "map_points": points[:MAP_POINT_LIMIT],
        "map_truncated": len(points) > MAP_POINT_LIMIT,
        "collected": collected,
        "notice": "统计仅含人工已确认记录；时间按事件时间，未填写时使用录入时间；数量不代表风险排名。",
    }


def analytics_benchmarks(db: Session, *, facility: str | None = None, scene: str | None = None,
                         category: str | None = None, limit: int = 20) -> dict:
    if not facility and not scene:
        raise ValueError("请至少选择设施或场景")
    matches = []
    if facility:
        matches.append(Assessment.facility == facility)
    if scene:
        matches.append(Assessment.scene == scene)
    has_note = func.length(func.trim(func.coalesce(Assessment.rectification_note, ""))) > 0
    query = select(Assessment).where(
        Assessment.confirmed.is_(True),
        or_(*matches),
        or_(Assessment.rectification_status.is_not(None), has_note),
    )
    if category:
        query = query.where(Assessment.hazard_category == category)
    rows = db.scalars(query).all()

    def match_of(item: Assessment) -> str:
        both = bool(facility and scene and item.facility == facility and item.scene == scene)
        if both:
            return "both"
        return "facility" if facility and item.facility == facility else "scene"

    def sort_key(item: Assessment):
        return match_of(item) != "both", -_as_utc(
            item.rectified_at or item.updated_at or item.created_at
        ).timestamp()

    rows.sort(key=sort_key)
    sources = Counter(item.data_source or "unknown" for item in rows)
    items = [{
        "id": item.id, "description": item.description, "district": item.district,
        "facility": item.facility, "scene": item.scene, "hazard_category": item.hazard_category,
        "risk_level": item.risk_level, "rectification_status": item.rectification_status,
        "rectification_note": item.rectification_note,
        "rectified_at": utc_event_time(item.rectified_at), "event_time": utc_event_time(item.event_time),
        "data_source": item.data_source, "match": match_of(item),
        "comparable": COMPARABLE_LABELS[match_of(item)],
    } for item in rows[:limit]]
    return {
        "filters": {"facility": facility, "scene": scene, "category": category},
        "sample_size": len(rows),
        "returned": len(items),
        "truncated": len(rows) > len(items),
        "sources": _buckets(sources, DATA_SOURCE_LABELS),
        "items": items,
        "notice": "对标仅汇总已确认且填写了整改状态或说明的记录；样本量不足或条件不同时，不能据此直接作出处置决定。",
    }
