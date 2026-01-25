from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Dict, Iterable, List, Optional, Tuple

from backend.core.logger import get_logger

logger = get_logger("geo_zones")


Coordinate = Tuple[float, float]
Ring = List[Coordinate]
Polygon = List[Ring]


@dataclass(frozen=True)
class GeoZone:
    zone_id: str
    name: str
    polygons: List[Polygon]


_ZONES: Dict[str, GeoZone] = {}
_LOADED = False


def _zones_root() -> Path:
    return Path(__file__).resolve().parents[2] / "geo_extract_prod"


_ZONE_SOURCES = {
    "MKAD": {
        "name": "Территория внутри МКАД",
        "paths": [_zones_root() / "mkad_polygon_simplified.geojson"],
    },
    "MOSCOW_MO": {
        "name": "Москва + Московская область",
        "paths": [
            _zones_root() / "moscow_mo_simplified.geojson",
            _zones_root() / "mkad_polygon_simplified.geojson",
        ],
    },
}


def _extract_geometry(obj: dict) -> List[dict]:
    if not isinstance(obj, dict):
        return []
    obj_type = obj.get("type")
    if obj_type == "FeatureCollection":
        features = obj.get("features") or []
        return [f.get("geometry") for f in features if isinstance(f, dict) and f.get("geometry")]
    if obj_type == "Feature":
        geom = obj.get("geometry")
        if geom and geom.get("type") == "GeometryCollection":
            return geom.get("geometries") or []
        return [geom] if geom else []
    if obj_type in ("Polygon", "MultiPolygon"):
        return [obj]
    if obj_type == "GeometryCollection":
        return obj.get("geometries") or []
    return []


def _convert_polygon(coords: Iterable) -> Polygon:
    rings: Polygon = []
    for ring in coords or []:
        converted: Ring = []
        for pair in ring or []:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            lon, lat = pair[0], pair[1]
            try:
                converted.append((float(lat), float(lon)))
            except Exception:
                continue
        if converted:
            rings.append(converted)
    return rings


def _geometry_to_polygons(geometry: dict) -> List[Polygon]:
    if not geometry:
        return []
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon":
        polygon = _convert_polygon(coords or [])
        return [polygon] if polygon else []
    if gtype == "MultiPolygon":
        polygons: List[Polygon] = []
        for poly in coords or []:
            polygon = _convert_polygon(poly or [])
            if polygon:
                polygons.append(polygon)
        return polygons
    if gtype == "GeometryCollection":
        polygons: List[Polygon] = []
        for geom in geometry.get("geometries") or []:
            polygons.extend(_geometry_to_polygons(geom or {}))
        return polygons
    return []


def _load_zone(zone_id: str, name: str, paths: List[Path]) -> Optional[GeoZone]:
    polygons: List[Polygon] = []
    for path in paths:
        if not path.exists():
            logger.error("GeoJSON файл не найден для зоны %s: %s", zone_id, path)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Ошибка чтения GeoJSON %s: %s", path, exc)
            continue

        geometries = _extract_geometry(data)
        for geom in geometries:
            polygons.extend(_geometry_to_polygons(geom or {}))

    if not polygons:
        logger.error("Не удалось извлечь полигоны для зоны %s", zone_id)
        return None

    return GeoZone(zone_id=zone_id, name=name, polygons=polygons)


def load_zones() -> Dict[str, GeoZone]:
    global _LOADED
    if _LOADED:
        return _ZONES

    for zone_id, meta in _ZONE_SOURCES.items():
        zone = _load_zone(zone_id, meta["name"], meta["paths"])
        if zone:
            _ZONES[zone_id] = zone

    _LOADED = True
    logger.info("✅ Загружено геозон: %s", len(_ZONES))
    return _ZONES


def list_zone_ids() -> List[str]:
    load_zones()
    return sorted(_ZONES.keys())


def normalize_zone_id(zone_id: Optional[str]) -> Optional[str]:
    if zone_id is None:
        return None
    value = str(zone_id).strip().upper()
    if not value:
        return None
    load_zones()
    return value if value in _ZONES else None


def get_zone(zone_id: str) -> Optional[GeoZone]:
    load_zones()
    return _ZONES.get(str(zone_id).strip().upper())


def _point_in_ring(point: Coordinate, ring: Ring) -> bool:
    lat, lon = point
    inside = False
    if not ring:
        return False
    j = len(ring) - 1
    for i in range(len(ring)):
        yi, xi = ring[i]
        yj, xj = ring[j]
        intersects = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _point_in_polygon(point: Coordinate, polygon: Polygon) -> bool:
    if not polygon:
        return False
    outer = polygon[0]
    if not _point_in_ring(point, outer):
        return False
    for hole in polygon[1:]:
        if _point_in_ring(point, hole):
            return False
    return True


def contains_point(zone: GeoZone, lat: float, lon: float) -> bool:
    point = (float(lat), float(lon))
    for polygon in zone.polygons:
        if _point_in_polygon(point, polygon):
            return True
    return False


def point_in_zone(zone_id: str, lat: float, lon: float) -> bool:
    zone = get_zone(zone_id)
    if not zone:
        return False
    return contains_point(zone, lat, lon)
