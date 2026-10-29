"""数据分析服务（阶段 2）：热力图、对标分析、趋势预测

核心功能：
1. 热力图数据：按区/街道聚合隐患数量和等级分布
2. 对标分析：某区 vs 全市平均水平
3. 趋势预测：按时间维度统计隐患变化趋势
4. 数据缓存：减少重复聚合查询
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from app.models.entities import Assessment, DistrictStats

logger = logging.getLogger("safety_hazard.analytics")

# 缓存容器（简单实现）
_CACHE: dict[str, Any] = {}
_CACHE_EXPIRE: dict[str, datetime] = {}


def _cache_get(key: str) -> Any | None:
    """获取缓存"""
    if key in _CACHE and key in _CACHE_EXPIRE:
        if datetime.now() < _CACHE_EXPIRE[key]:
            return _CACHE[key]
    return None


def _cache_set(key: str, value: Any, expire_minutes: int = 30):
    """设置缓存"""
    _CACHE[key] = value
    _CACHE_EXPIRE[key] = datetime.now() + timedelta(minutes=expire_minutes)


def get_heatmap_data(
    db: Session,
    district: str | None = None,
    category: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """
    热力图数据：按区/街道聚合

    Args:
        db: 数据库会话
        district: 筛选区（可选）
        category: 筛选类别（可选）
        start_date: 开始日期（YYYY-MM-DD）
        end_date: 结束日期（YYYY-MM-DD）

    Returns:
        [
            {
                "district": "渝北区",
                "street": "龙溪街道",
                "longitude": 106.55,
                "latitude": 29.56,
                "count": 15,
                "level_1": 2,
                "level_2": 8,
                "level_3": 5
            },
            ...
        ]
    """
    # 缓存键
    cache_key = f"heatmap:{district}:{category}:{start_date}:{end_date}"
    cached = _cache_get(cache_key)
    if cached:
        logger.debug("热力图数据命中缓存")
        return cached

    # 构建查询
    query = db.query(
        Assessment.district,
        Assessment.street,
        func.avg(Assessment.longitude).label("longitude"),
        func.avg(Assessment.latitude).label("latitude"),
        func.count(Assessment.id).label("count"),
        func.sum(case((Assessment.risk_level == 1, 1), else_=0)).label("level_1"),
        func.sum(case((Assessment.risk_level == 2, 1), else_=0)).label("level_2"),
        func.sum(case((Assessment.risk_level == 3, 1), else_=0)).label("level_3"),
    ).filter(
        Assessment.longitude.isnot(None),
        Assessment.latitude.isnot(None),
        Assessment.confirmed == True,  # 只统计已确认的记录
    )

    # 筛选条件
    if district:
        query = query.filter(Assessment.district == district)
    if category:
        query = query.filter(Assessment.hazard_category == category)
    if start_date:
        query = query.filter(Assessment.created_at >= start_date)
    if end_date:
        query = query.filter(Assessment.created_at <= end_date)

    # 分组
    query = query.group_by(Assessment.district, Assessment.street)

    # 执行查询
    results = []
    for row in query.all():
        if not row.district or not row.longitude or not row.latitude:
            continue

        results.append({
            "district": row.district,
            "street": row.street or "",
            "longitude": float(row.longitude),
            "latitude": float(row.latitude),
            "count": row.count,
            "level_1": row.level_1,
            "level_2": row.level_2,
            "level_3": row.level_3,
        })

    # 写入缓存
    _cache_set(cache_key, results, expire_minutes=30)

    logger.info("热力图数据查询完成: %d 个点", len(results))
    return results


def get_benchmark_data(db: Session, district: str) -> dict:
    """
    对标分析：某区 vs 全市平均

    Args:
        db: 数据库会话
        district: 区名称

    Returns:
        {
            "district": "渝北区",
            "total": 150,
            "categories": {
                "消防隐患": 80,
                "生产安全": 40,
                "社区治理": 30
            },
            "city_avg": {
                "total": 120,
                "categories": {...}
            },
            "rank": 3,  # 全市排名（隐患数量从高到低）
            "total_districts": 10
        }
    """
    # 缓存键
    cache_key = f"benchmark:{district}"
    cached = _cache_get(cache_key)
    if cached:
        logger.debug("对标数据命中缓存")
        return cached

    # 1. 该区统计
    district_query = db.query(
        Assessment.hazard_category,
        func.count(Assessment.id).label("count"),
    ).filter(
        Assessment.district == district,
        Assessment.confirmed == True,
    ).group_by(Assessment.hazard_category).all()

    district_categories = {}
    district_total = 0
    for row in district_query:
        if row.hazard_category:
            district_categories[row.hazard_category] = row.count
            district_total += row.count

    # 2. 全市统计
    city_query = db.query(
        Assessment.hazard_category,
        func.count(Assessment.id).label("count"),
    ).filter(
        Assessment.confirmed == True,
        Assessment.district.isnot(None),
    ).group_by(Assessment.hazard_category).all()

    city_categories = {}
    city_total = 0
    for row in city_query:
        if row.hazard_category:
            city_categories[row.hazard_category] = row.count
            city_total += row.count

    # 3. 计算全市区域数量
    total_districts = db.query(func.count(func.distinct(Assessment.district))).filter(
        Assessment.confirmed == True,
        Assessment.district.isnot(None),
    ).scalar() or 1

    # 4. 计算排名（按隐患总数降序）
    rank_query = db.query(
        Assessment.district,
        func.count(Assessment.id).label("count"),
    ).filter(
        Assessment.confirmed == True,
        Assessment.district.isnot(None),
    ).group_by(Assessment.district).order_by(func.count(Assessment.id).desc()).all()

    rank = 1
    for idx, row in enumerate(rank_query, start=1):
        if row.district == district:
            rank = idx
            break

    # 计算全市平均
    city_avg_total = city_total // max(total_districts, 1)
    city_avg_categories = {
        cat: count // max(total_districts, 1)
        for cat, count in city_categories.items()
    }

    result = {
        "district": district,
        "total": district_total,
        "categories": district_categories,
        "city_avg": {
            "total": city_avg_total,
            "categories": city_avg_categories,
        },
        "rank": rank,
        "total_districts": total_districts,
    }

    # 写入缓存
    _cache_set(cache_key, result, expire_minutes=60)

    logger.info("对标分析完成: %s (排名 %d/%d)", district, rank, total_districts)
    return result


def get_trends_data(
    db: Session,
    district: str | None = None,
    category: str | None = None,
    months: int = 12,
) -> list[dict]:
    """
    趋势数据：按月统计隐患数量

    Args:
        db: 数据库会话
        district: 筛选区（可选）
        category: 筛选类别（可选）
        months: 统计月数（默认 12 个月）

    Returns:
        [
            {"month": "2024-01", "count": 45, "level_1": 5, "level_2": 20, "level_3": 20},
            {"month": "2024-02", "count": 50, "level_1": 6, "level_2": 22, "level_3": 22},
            ...
        ]
    """
    # 缓存键
    cache_key = f"trends:{district}:{category}:{months}"
    cached = _cache_get(cache_key)
    if cached:
        logger.debug("趋势数据命中缓存")
        return cached

    # 计算起始日期
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)

    # 构建查询（按月分组）
    query = db.query(
        func.strftime("%Y-%m", Assessment.created_at).label("month"),
        func.count(Assessment.id).label("count"),
        func.sum(case((Assessment.risk_level == 1, 1), else_=0)).label("level_1"),
        func.sum(case((Assessment.risk_level == 2, 1), else_=0)).label("level_2"),
        func.sum(case((Assessment.risk_level == 3, 1), else_=0)).label("level_3"),
    ).filter(
        Assessment.confirmed == True,
        Assessment.created_at >= start_date,
    )

    # 筛选条件
    if district:
        query = query.filter(Assessment.district == district)
    if category:
        query = query.filter(Assessment.hazard_category == category)

    # 分组和排序
    query = query.group_by("month").order_by("month")

    # 执行查询
    results = []
    for row in query.all():
        results.append({
            "month": row.month,
            "count": row.count,
            "level_1": row.level_1,
            "level_2": row.level_2,
            "level_3": row.level_3,
        })

    # 写入缓存
    _cache_set(cache_key, results, expire_minutes=60)

    logger.info("趋势数据查询完成: %d 个月", len(results))
    return results


def clear_cache():
    """清空分析缓存（用于测试或强制刷新）"""
    global _CACHE, _CACHE_EXPIRE
    _CACHE.clear()
    _CACHE_EXPIRE.clear()
    logger.info("分析缓存已清空")
