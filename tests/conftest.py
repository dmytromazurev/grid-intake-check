from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from gridintake import load_rulepack

ROOT = Path(__file__).resolve().parents[1]
VILNIUS = ROOT / "data" / "vilnius-osm.json"

LAT0, LON0 = 54.90, 23.90  # Kaunas area: metre offsets → lon/lat for synthetic fixtures


def ll(dx: float, dy: float) -> list[float]:
    lat = LAT0 + dy / 111_320
    lon = LON0 + dx / (111_320 * math.cos(math.radians(LAT0)))
    return [lon, lat]


def point(fid: str, dx: float, dy: float, **props: Any) -> dict[str, Any]:
    return {"type": "Feature", "id": fid, "properties": {"power": "tower", **props}, "geometry": {"type": "Point", "coordinates": ll(dx, dy)}}


def line(fid: str, pts: list[tuple[float, float]], **props: Any) -> dict[str, Any]:
    return {"type": "Feature", "id": fid, "properties": {"power": "line", **props},
            "geometry": {"type": "LineString", "coordinates": [ll(x, y) for x, y in pts]}}


def fc(*features: dict[str, Any]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(features)}


@pytest.fixture
def rules_no_edge():
    r = load_rulepack("default")
    r.edge_buffer_m = 0
    return r


@pytest.fixture(scope="session")
def vilnius_path() -> Path:
    return VILNIUS
