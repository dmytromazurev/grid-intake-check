"""Loading utility network data and putting it into one metric working CRS.

Accepted inputs:

* GeoJSON FeatureCollection: Point = structure, (Multi)LineString = power line,
  Polygon/MultiPolygon with ``power=substation|plant`` = substation footprint.
  RFC 7946 says GeoJSON is EPSG:4326; a legacy ``crs`` member or an explicit ``crs`` argument is honoured.
* Overpass API JSON (``out geom``), e.g. an OpenStreetMap extract.
* The compact JSON used by the bundled demo data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pyproj import CRS, Transformer

STRUCTURE_POWER = {"tower", "pole", "portal", "terminal"}
LINE_POWER = {"line", "minor_line", "cable"}
SUBSTATION_POWER = {"substation", "plant"}

LITHUANIA_BBOX = (20.9, 53.8, 26.9, 56.5)  # lon_min, lat_min, lon_max, lat_max


class IntakeError(ValueError):
    """The file can’t be analysed as delivered; the message says what to ask the customer for."""


@dataclass
class Structure:
    id: str
    x: float
    y: float
    lon: float
    lat: float
    power: str
    tags: dict[str, str]


@dataclass
class Line:
    id: str
    power: str
    tags: dict[str, str]
    xy: list[tuple[float, float]]
    lonlat: list[tuple[float, float]]


@dataclass
class Substation:
    id: str
    name: str
    voltage: str
    ring_xy: list[tuple[float, float]]


@dataclass
class Dataset:
    structures: list[Structure]
    lines: list[Line]
    substations: list[Substation]
    source_crs: CRS
    working_crs: CRS
    meta: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def working_crs_code(self) -> str:
        auth = self.working_crs.to_authority()
        return f"{auth[0]}:{auth[1]}" if auth else self.working_crs.name


# --------------------------------------------------------------------------- raw parsing

_Raw = dict[str, list[dict[str, Any]]]


def _str_tags(props: dict[str, Any] | None) -> dict[str, str]:
    return {str(k): str(v) for k, v in (props or {}).items() if v is not None and not isinstance(v, dict | list)}


def _from_compact(d: dict[str, Any]) -> _Raw:
    return {
        "structures": [{"id": str(n["id"]), "x": n["lon"], "y": n["lat"], "power": n.get("power") or "structure", "tags": _str_tags(n.get("tags"))} for n in d["structures"]],
        "lines": [{"id": str(w["id"]), "power": w.get("power") or "line", "tags": _str_tags(w.get("tags")), "coords": [(c[1], c[0]) for c in w["coords"]]} for w in d["lines"]],
        "substations": [{"id": str(s["id"]), "name": s.get("name", ""), "voltage": s.get("voltage", ""), "ring": [(c[1], c[0]) for c in s["ring"]]} for s in d.get("substations", [])],
    }


def _from_overpass(d: dict[str, Any]) -> _Raw:
    out: _Raw = {"structures": [], "lines": [], "substations": []}
    for e in d.get("elements", []):
        t = _str_tags(e.get("tags"))
        power = t.get("power", "")
        if e.get("type") == "node" and power in STRUCTURE_POWER:
            out["structures"].append({"id": str(e["id"]), "x": e["lon"], "y": e["lat"], "power": power, "tags": t})
        elif e.get("type") == "way" and e.get("geometry"):
            coords = [(g["lon"], g["lat"]) for g in e["geometry"]]
            if power in LINE_POWER:
                out["lines"].append({"id": str(e["id"]), "power": power, "tags": t, "coords": coords})
            elif power in SUBSTATION_POWER and len(coords) >= 4:
                out["substations"].append({"id": str(e["id"]), "name": t.get("name", ""), "voltage": t.get("voltage", ""), "ring": coords})
    return out


def _from_geojson(d: dict[str, Any]) -> _Raw:
    out: _Raw = {"structures": [], "lines": [], "substations": []}
    feats = d.get("features", []) if d.get("type") == "FeatureCollection" else [d] if d.get("type") == "Feature" else []
    for n, f in enumerate(feats, 1):
        g = (f or {}).get("geometry")
        if not g:
            continue
        props = f.get("properties") or {}
        t = _str_tags(props)
        fid = str(f.get("id", props.get("id", props.get("ref", f"f{n}"))))
        typ, c = g.get("type"), g.get("coordinates")
        if typ == "Point":
            out["structures"].append({"id": fid, "x": c[0], "y": c[1], "power": t.get("power", "structure"), "tags": t})
        elif typ == "LineString":
            out["lines"].append({"id": fid, "power": t.get("power", "line"), "tags": t, "coords": [tuple(p[:2]) for p in c]})
        elif typ == "MultiLineString":
            for i, part in enumerate(c):
                out["lines"].append({"id": f"{fid}/{i}", "power": t.get("power", "line"), "tags": t, "coords": [tuple(p[:2]) for p in part]})
        elif typ in {"Polygon", "MultiPolygon"} and t.get("power") in SUBSTATION_POWER:
            rings = [c[0]] if typ == "Polygon" else [poly[0] for poly in c]
            for i, ring in enumerate(rings):
                out["substations"].append({"id": fid if i == 0 else f"{fid}/{i}", "name": t.get("name", ""), "voltage": t.get("voltage", ""), "ring": [tuple(p[:2]) for p in ring]})
    return out


def _legacy_geojson_crs(d: dict[str, Any]) -> str | None:
    name = ((d.get("crs") or {}).get("properties") or {}).get("name")
    if not name:
        return None
    m = re.search(r"EPSG:+(\d+)", name)
    if m:
        return f"EPSG:{m.group(1)}"
    return "EPSG:4326" if "CRS84" in name else name


# --------------------------------------------------------------------------- CRS handling

def choose_working_crs(lon: float, lat: float) -> CRS:
    """LKS-94 inside Lithuania, otherwise the local UTM zone. Always metres."""
    x0, y0, x1, y1 = LITHUANIA_BBOX
    if x0 < lon < x1 and y0 < lat < y1:
        return CRS.from_epsg(3346)
    zone = int((lon + 180) // 6) + 1
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def _check_geographic_ranges(raw: _Raw) -> None:
    xs = [s["x"] for s in raw["structures"]] + [p[0] for ln in raw["lines"] for p in ln["coords"]]
    ys = [s["y"] for s in raw["structures"]] + [p[1] for ln in raw["lines"] for p in ln["coords"]]
    if not xs:
        raise IntakeError("The file contains no points or lines that look like structures or power lines.")
    bad = sum(1 for v in xs if abs(v) > 180) + sum(1 for v in ys if abs(v) > 90)
    if bad:
        raise IntakeError(
            f"{bad} coordinate values are outside the longitude/latitude range, so the file is probably in a projected CRS. "
            "Pass the source CRS (e.g. --crs EPSG:3346) or ask the customer for it and re-export to EPSG:4326 "
            "(ogr2ogr -t_srs EPSG:4326 out.geojson in.shp)."
        )


def _apply_aliases(tags: dict[str, str], aliases: dict[str, list[str]]) -> dict[str, str]:
    if not aliases:
        return tags
    lower = {k.lower(): v for k, v in tags.items()}
    out = dict(tags)
    for key, names in aliases.items():
        if out.get(key):
            continue
        for name in names:
            v = tags.get(name) or lower.get(name.lower())
            if v:
                out[key] = v
                break
    return out


# --------------------------------------------------------------------------- public API

def read_json(source: str | Path | dict[str, Any] | bytes) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    if isinstance(source, bytes):
        return json.loads(source.decode("utf-8"))
    p = Path(source)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    if isinstance(source, str) and source.lstrip().startswith(("{", "[")):
        return json.loads(source)
    raise IntakeError(f"File not found: {source}")


def load_dataset(source: str | Path | dict[str, Any] | bytes, crs: str | None = None,
                 field_aliases: dict[str, list[str]] | None = None) -> Dataset:
    d = read_json(source)
    if isinstance(d, dict) and isinstance(d.get("structures"), list) and isinstance(d.get("lines"), list):
        raw, fmt, declared = _from_compact(d), "compact", "EPSG:4326"
    elif isinstance(d, dict) and isinstance(d.get("elements"), list):
        raw, fmt, declared = _from_overpass(d), "overpass", "EPSG:4326"
    elif isinstance(d, dict) and d.get("type") in {"FeatureCollection", "Feature"}:
        raw, fmt, declared = _from_geojson(d), "geojson", _legacy_geojson_crs(d) or "EPSG:4326"
    else:
        raise IntakeError("Not GeoJSON, Overpass JSON or the compact demo format.")

    src = CRS.from_user_input(crs or declared)
    notes: list[str] = []
    if src.is_geographic:
        _check_geographic_ranges(raw)
        to_ll = None
    else:
        to_ll = Transformer.from_crs(src, 4326, always_xy=True)

    def lonlat(x: float, y: float) -> tuple[float, float]:
        return (x, y) if to_ll is None else to_ll.transform(x, y)

    pts = [lonlat(s["x"], s["y"]) for s in raw["structures"]] + [lonlat(*ln["coords"][0]) for ln in raw["lines"] if ln["coords"]]
    if not pts:
        raise IntakeError("The file contains no points or lines that look like structures or power lines.")
    c_lon = sum(p[0] for p in pts) / len(pts)
    c_lat = sum(p[1] for p in pts) / len(pts)

    if src.is_projected and all(ax.unit_name in {"metre", "meter"} for ax in src.axis_info[:2]):
        work = src
        notes.append(f"Source CRS {src.to_string()} is already metric; used as working CRS.")
    else:
        work = choose_working_crs(c_lon, c_lat)
    to_w = Transformer.from_crs(src, work, always_xy=True)

    aliases = field_aliases or {}
    structures = []
    for s in raw["structures"]:
        x, y = to_w.transform(s["x"], s["y"])
        lo, la = lonlat(s["x"], s["y"])
        structures.append(Structure(s["id"], x, y, lo, la, s["power"], _apply_aliases(s["tags"], aliases)))
    lines = []
    for ln in raw["lines"]:
        if len(ln["coords"]) < 2:
            notes.append(f"Line {ln['id']} has fewer than two vertices and was skipped.")
            continue
        xs, ys = to_w.transform([p[0] for p in ln["coords"]], [p[1] for p in ln["coords"]])
        lines.append(Line(ln["id"], ln["power"], _apply_aliases(ln["tags"], aliases), list(zip(xs, ys, strict=True)), [lonlat(*p) for p in ln["coords"]]))
    subs = []
    for sb in raw["substations"]:
        xs, ys = to_w.transform([p[0] for p in sb["ring"]], [p[1] for p in sb["ring"]])
        subs.append(Substation(sb["id"], sb["name"], sb["voltage"], list(zip(xs, ys, strict=True))))

    meta = {"format": fmt, "source_crs": src.to_string()}
    for k in ("source", "fetched"):
        if isinstance(d, dict) and k in d:
            meta[k] = d[k]
    return Dataset(structures, lines, subs, src, work, meta, notes)
