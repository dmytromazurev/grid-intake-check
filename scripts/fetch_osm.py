"""Re-create data/vilnius-osm.json from the Overpass API (OpenStreetMap, ODbL).

    python scripts/fetch_osm.py --bbox 54.58,25.00,54.82,25.50 --out data/vilnius-osm.json

Fetches power lines, structures (tower, pole, portal, terminal) and substation footprints, then
writes the compact format the package and the web demo read. OSM changes daily, so a fresh
extract will not reproduce the golden numbers in tests/test_vilnius.py exactly.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.parse
import urllib.request

ENDPOINT = "https://overpass-api.de/api/interpreter"
UA = "grid-intake-check/0.1 (+https://github.com/dmytromazurev/grid-intake-check)"
KEEP_NODE = ["design", "material", "line_attachment", "ref", "height", "structure", "operator", "location:transition", "fixme", "name"]
KEEP_WAY = ["voltage", "cables", "circuits", "name", "ref", "operator", "line", "wires", "frequency", "location"]


def overpass(query: str, tries: int = 4) -> dict:
    body = urllib.parse.urlencode({"data": query}).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(ENDPOINT, data=body, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=200) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001 - retry any transport or server error
            if i == tries - 1:
                raise
            print(f"retry {i + 1}: {e}")
            time.sleep(8)
    raise RuntimeError("unreachable")


def area_m2(ring: list[tuple[float, float]]) -> float:
    lat0 = sum(p[0] for p in ring) / len(ring)
    pts = [(math.radians(lo) * 6371000 * math.cos(math.radians(lat0)), math.radians(la) * 6371000) for la, lo in ring]
    return abs(sum(pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1] for i in range(len(pts) - 1))) / 2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", default="54.58,25.00,54.82,25.50", help="south,west,north,east")
    ap.add_argument("--out", default="data/vilnius-osm.json")
    a = ap.parse_args()
    bb = a.bbox
    grid = overpass(f'[out:json][timeout:180];(way["power"~"^(line|minor_line)$"]({bb});node["power"~"^(tower|pole|portal|terminal)$"]({bb}););out geom tags;')
    subs = overpass(f'[out:json][timeout:120];(way["power"~"^(substation|plant)$"]({bb});relation["power"~"^(substation|plant)$"]({bb}););out geom tags;')

    structures, lines, substations = [], [], []
    for e in grid["elements"]:
        t = e.get("tags", {})
        if e["type"] == "node":
            structures.append({"id": e["id"], "lat": round(e["lat"], 7), "lon": round(e["lon"], 7), "power": t.get("power"),
                               "tags": {k: t[k] for k in KEEP_NODE if k in t}})
        else:
            lines.append({"id": e["id"], "power": t.get("power"), "tags": {k: t[k] for k in KEEP_WAY if k in t},
                          "coords": [[round(g["lat"], 7), round(g["lon"], 7)] for g in e["geometry"]]})
    for e in subs["elements"]:
        t = e.get("tags", {})
        rings = [[(g["lat"], g["lon"]) for g in e["geometry"]]] if e["type"] == "way" else [
            [(g["lat"], g["lon"]) for g in m["geometry"]] for m in e.get("members", []) if m.get("role") == "outer" and "geometry" in m]
        for ring in rings:
            if len(ring) < 4:
                continue
            v = t.get("voltage", "")
            # keep real substations; drop small distribution kiosks unless their voltage says otherwise
            if area_m2(ring) > 1500 or any(x in v for x in ("110000", "330000", "35000")):
                substations.append({"id": e["id"], "name": t.get("name", ""), "voltage": v, "kind": t.get("power"),
                                    "ring": [[round(la, 6), round(lo, 6)] for la, lo in ring]})
    out = {"source": "OpenStreetMap contributors (ODbL), Overpass API", "fetched": grid["osm3s"]["timestamp_osm_base"],
           "bbox": [float(x) for x in bb.split(",")], "structures": structures, "lines": lines, "substations": substations}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print(f"{len(structures)} structures, {len(lines)} lines, {len(substations)} substations → {a.out}")


if __name__ == "__main__":
    main()
