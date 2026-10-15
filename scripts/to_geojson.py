"""Convert the compact demo JSON to a standard GeoJSON FeatureCollection (EPSG:4326).

    python scripts/to_geojson.py data/vilnius-osm.json examples/vilnius-grid.geojson
"""

from __future__ import annotations

import json
import sys


def main(src: str, dst: str) -> None:
    d = json.load(open(src, encoding="utf-8"))
    feats = []
    for s in d["structures"]:
        feats.append({"type": "Feature", "id": str(s["id"]), "properties": {"power": s["power"], **s.get("tags", {})},
                      "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]}})
    for w in d["lines"]:
        feats.append({"type": "Feature", "id": str(w["id"]), "properties": {"power": w["power"], **w.get("tags", {})},
                      "geometry": {"type": "LineString", "coordinates": [[c[1], c[0]] for c in w["coords"]]}})
    for sb in d.get("substations", []):
        feats.append({"type": "Feature", "id": str(sb["id"]), "properties": {"power": "substation", "name": sb.get("name", ""), "voltage": sb.get("voltage", "")},
                      "geometry": {"type": "Polygon", "coordinates": [[[c[1], c[0]] for c in sb["ring"]]]}})
    out = {"type": "FeatureCollection", "name": "vilnius-grid", "attribution": d.get("source", ""), "fetched": d.get("fetched", ""),
           "coverage": d.get("coverage"),  # [west, south, east, north]: the analysis area; the rest is context
           "features": feats}
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(feats)} features → {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
