"""Mock map provider for store location display."""

import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# Predefined coordinates for known cities
CITY_COORDINATES = {
    "广州": {"lat": 23.1291, "lng": 113.2644},
    "深圳": {"lat": 22.5431, "lng": 114.0579},
    "北京": {"lat": 39.9042, "lng": 116.4074},
    "佛山": {"lat": 23.0218, "lng": 113.1218},
    "东莞": {"lat": 23.0208, "lng": 113.7518},
}


class MockMapProvider:
    """Mock map provider using static coordinates."""

    def get_city_coordinates(self, city_name: str) -> dict[str, float] | None:
        if settings.MOCK_SCENARIO == "error":
            logger.warning("MapProvider mock error scenario")
            return None
        return CITY_COORDINATES.get(city_name)

    def get_store_marker(
        self, store_name: str, lat: float, lng: float, address: str
    ) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {"name": store_name, "address": address},
        }

    def calculate_distance(
        self, lat1: float, lng1: float, lat2: float, lng2: float
    ) -> float:
        """Simple Euclidean distance approximation for mock purposes."""
        import math

        R = 6371  # Earth radius in km
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlng / 2) ** 2
        )
        return R * 2 * math.asin(math.sqrt(a))


class AmapProvider:
    """高德地图 Provider，地理编码调用高德 API。

    get_store_marker / calculate_distance 与 Mock 实现一致（不依赖外部 API）。
    未配置 AMAP_KEY 时回退到本地城市查表逻辑。
    """

    def get_city_coordinates(self, city_name: str) -> dict[str, float] | None:
        key = settings.AMAP_KEY
        if not key:
            logger.warning("AmapProvider 未配置 AMAP_KEY，回退到本地城市查表")
            return CITY_COORDINATES.get(city_name)

        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    "https://restapi.amap.com/v3/geocode/geo",
                    params={"key": key, "address": city_name},
                )
                resp.raise_for_status()
                data = resp.json()
            # 高德返回 geocodes[0].location 格式为 "lng,lat"
            geocodes = data.get("geocodes") or []
            if not geocodes:
                logger.warning("AmapProvider 未找到 %s 的坐标", city_name)
                return None
            location = geocodes[0].get("location", "")
            parts = location.split(",")
            if len(parts) != 2:
                logger.warning("AmapProvider 坐标格式异常: %s", location)
                return None
            return {"lng": float(parts[0]), "lat": float(parts[1])}
        except Exception as exc:
            logger.error("AmapProvider.get_city_coordinates 失败: %s", exc)
            return CITY_COORDINATES.get(city_name)

    def get_store_marker(
        self, store_name: str, lat: float, lng: float, address: str
    ) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {"name": store_name, "address": address},
        }

    def calculate_distance(
        self, lat1: float, lng1: float, lat2: float, lng2: float
    ) -> float:
        """Haversine 公式计算球面距离，与 Mock 实现一致。"""
        import math

        R = 6371  # Earth radius in km
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlng / 2) ** 2
        )
        return R * 2 * math.asin(math.sqrt(a))


class TencentMapProvider:
    """腾讯地图 Provider，地理编码调用腾讯地图 API。

    get_store_marker / calculate_distance 与 Mock 实现一致（不依赖外部 API）。
    未配置 TENCENT_MAP_KEY 时回退到本地城市查表逻辑。
    """

    def get_city_coordinates(self, city_name: str) -> dict[str, float] | None:
        key = settings.TENCENT_MAP_KEY
        if not key:
            logger.warning(
                "TencentMapProvider 未配置 TENCENT_MAP_KEY，回退到本地城市查表"
            )
            return CITY_COORDINATES.get(city_name)

        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    "https://apis.map.qq.com/ws/geocoder/v1/",
                    params={"key": key, "address": city_name},
                )
                resp.raise_for_status()
                data = resp.json()
            # 腾讯返回 result.location 含 lat/lng
            location = (data.get("result") or {}).get("location")
            if not location:
                logger.warning("TencentMapProvider 未找到 %s 的坐标", city_name)
                return None
            return {"lng": float(location["lng"]), "lat": float(location["lat"])}
        except Exception as exc:
            logger.error("TencentMapProvider.get_city_coordinates 失败: %s", exc)
            return CITY_COORDINATES.get(city_name)

    def get_store_marker(
        self, store_name: str, lat: float, lng: float, address: str
    ) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {"name": store_name, "address": address},
        }

    def calculate_distance(
        self, lat1: float, lng1: float, lat2: float, lng2: float
    ) -> float:
        """Haversine 公式计算球面距离，与 Mock 实现一致。"""
        import math

        R = 6371  # Earth radius in km
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlng / 2) ** 2
        )
        return R * 2 * math.asin(math.sqrt(a))


def get_map_provider() -> MockMapProvider | AmapProvider | TencentMapProvider:
    if settings.MAP_PROVIDER == "mock":
        return MockMapProvider()
    if settings.MAP_PROVIDER == "amap":
        return AmapProvider()
    if settings.MAP_PROVIDER == "tencent":
        return TencentMapProvider()
    raise NotImplementedError(
        f"Map provider '{settings.MAP_PROVIDER}' not implemented."
    )
