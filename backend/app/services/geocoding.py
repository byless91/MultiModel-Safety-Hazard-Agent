"""地理编码服务（阶段 2）：地址 → 经纬度 + 行政区划

功能：
1. 调用高德地图 API 将地址转换为经纬度
2. 解析行政区划（区、街道）
3. 批量地理编码（限速处理）
4. 缓存机制（避免重复调用 API）
"""

import asyncio
import hashlib
import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger("safety_hazard.geocoding")

# 内存缓存（简单实现，生产环境建议用 Redis）
_GEOCODE_CACHE: dict[str, dict] = {}


def _cache_key(address: str, city: str) -> str:
    """生成缓存键"""
    return hashlib.md5(f"{city}:{address}".encode()).hexdigest()


async def geocode_address(
    address: str,
    city: str | None = None,
) -> dict | None:
    """
    地理编码：地址 → 经纬度 + 行政区划

    Args:
        address: 详细地址
        city: 城市名称（可选，默认从配置读取）

    Returns:
        {
            "longitude": 106.550464,
            "latitude": 29.563761,
            "district": "渝北区",
            "street": "龙溪街道",
            "formatted_address": "重庆市渝北区龙溪街道...",
            "adcode": "500112"  # 行政区划代码
        }
        失败返回 None
    """
    settings = get_settings()

    # 默认城市
    if not city:
        city = settings.default_city or "重庆"

    # 检查缓存
    cache_key = _cache_key(address, city)
    if cache_key in _GEOCODE_CACHE:
        logger.debug("地理编码命中缓存: %s", address)
        return _GEOCODE_CACHE[cache_key]

    # 检查 API Key
    if not settings.amap_api_key:
        logger.warning("未配置高德地图 API Key，地理编码功能不可用")
        return None

    try:
        # 调用高德地图 API
        url = "https://restapi.amap.com/v3/geocode/geo"
        params = {
            "key": settings.amap_api_key,
            "address": address,
            "city": city,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            data = response.json()

            # 检查响应
            if data.get("status") != "1":
                logger.warning("高德地图 API 返回失败: %s", data.get("info"))
                return None

            geocodes = data.get("geocodes", [])
            if not geocodes:
                logger.warning("地址无法地理编码: %s", address)
                return None

            # 解析第一个结果
            geocode = geocodes[0]
            location = geocode.get("location", "")
            if not location or "," not in location:
                logger.warning("地理编码返回坐标格式错误: %s", location)
                return None

            lon, lat = location.split(",")

            result = {
                "longitude": float(lon),
                "latitude": float(lat),
                "district": geocode.get("district", ""),
                "street": geocode.get("street", "") or geocode.get("township", ""),
                "formatted_address": geocode.get("formatted_address", address),
                "adcode": geocode.get("adcode", ""),
            }

            # 写入缓存
            _GEOCODE_CACHE[cache_key] = result

            logger.info("地理编码成功: %s → (%s, %s)", address, lon, lat)
            return result

    except httpx.TimeoutException:
        logger.error("地理编码超时: %s", address)
        return None
    except Exception as exc:
        logger.error("地理编码异常: %s - %s", address, exc, exc_info=True)
        return None


async def batch_geocode(
    addresses: list[dict[str, str]],
    delay_seconds: float = 0.2,
) -> list[dict]:
    """
    批量地理编码（带限速）

    Args:
        addresses: [{"id": "xxx", "address": "...", "city": "..."}, ...]
        delay_seconds: 每次请求间隔（高德免费版 QPS 限制）

    Returns:
        [
            {
                "id": "xxx",
                "address": "...",
                "longitude": 106.55,
                "latitude": 29.56,
                "district": "渝北区",
                "street": "龙溪街道",
                "success": True,
                "error": None
            },
            ...
        ]
    """
    results = []

    for item in addresses:
        addr_id = item.get("id", "")
        address = item.get("address", "")
        city = item.get("city")

        if not address:
            results.append({
                "id": addr_id,
                "address": address,
                "success": False,
                "error": "地址为空",
            })
            continue

        # 地理编码
        geo = await geocode_address(address, city)

        if geo:
            results.append({
                "id": addr_id,
                "address": address,
                "longitude": geo["longitude"],
                "latitude": geo["latitude"],
                "district": geo["district"],
                "street": geo["street"],
                "formatted_address": geo["formatted_address"],
                "success": True,
                "error": None,
            })
        else:
            results.append({
                "id": addr_id,
                "address": address,
                "success": False,
                "error": "地理编码失败",
            })

        # 限速（避免超过 QPS 限制）
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

    return results


def reverse_geocode(longitude: float, latitude: float) -> dict | None:
    """
    逆地理编码：经纬度 → 地址（同步版本，用于非关键路径）

    Args:
        longitude: 经度
        latitude: 纬度

    Returns:
        {
            "address": "重庆市渝北区龙溪街道...",
            "district": "渝北区",
            "street": "龙溪街道"
        }
    """
    # TODO: 如果需要逆地理编码功能，可以实现
    # 暂时返回 None
    logger.debug("逆地理编码功能未实现: (%s, %s)", longitude, latitude)
    return None


def clear_cache():
    """清空地理编码缓存（用于测试或强制刷新）"""
    global _GEOCODE_CACHE
    _GEOCODE_CACHE.clear()
    logger.info("地理编码缓存已清空")
