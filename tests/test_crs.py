from __future__ import annotations

import json

import pytest
from conftest import fc, line, point
from pyproj import Transformer

import gridintake as gi
from gridintake.io import choose_working_crs


def test_lks94_matches_reference():
    # Same point the browser engine projects to (582510.4, 6061948.7)
    x, y = Transformer.from_crs(4326, 3346, always_xy=True).transform(25.2797, 54.6872)
    assert abs(x - 582510.4) < 0.5 and abs(y - 6061948.7) < 0.5


def test_working_crs_choice():
    assert choose_working_crs(25.28, 54.69).to_epsg() == 3346
    assert choose_working_crs(13.4, 52.5).to_epsg() == 32633  # Berlin → UTM 33N
    assert choose_working_crs(151.2, -33.9).to_epsg() == 32756  # Sydney → UTM 56S


def test_projected_without_crs_is_rejected():
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"power": "tower"}, "geometry": {"type": "Point", "coordinates": [582510, 6061948]}}]}
    with pytest.raises(gi.IntakeError, match="projected CRS"):
        gi.load_dataset(gj)


def _to_3346(gj):
    tr = Transformer.from_crs(4326, 3346, always_xy=True)
    out = json.loads(json.dumps(gj))
    for f in out["features"]:
        g = f["geometry"]
        if g["type"] == "Point":
            g["coordinates"] = list(tr.transform(*g["coordinates"]))
        else:
            g["coordinates"] = [list(tr.transform(*c)) for c in g["coordinates"]]
    return out


def test_projected_input_gives_same_result(rules_no_edge):
    gj = fc(*[point(f"t{i}", i * 200, 0) for i in range(5)], line("L1", [(i * 200, 0) for i in range(5)], voltage="110000"),
            line("L2", [(0, 500), (300, 500)], voltage="110000"))
    a = gi.analyse(gi.load_dataset(gj), rules_no_edge)
    b = gi.analyse(gi.load_dataset(_to_3346(gj), crs="EPSG:3346"), rules_no_edge)
    assert [(c.id, c.count) for c in a.checks] == [(c.id, c.count) for c in b.checks]
    assert b.dataset.working_crs_code == "EPSG:3346"


def test_legacy_crs_member_is_honoured():
    gj = _to_3346(fc(point("t0", 0, 0), point("t1", 200, 0), line("L1", [(0, 0), (200, 0)], voltage="110000")))
    gj["crs"] = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3346"}}
    ds = gi.load_dataset(gj)
    assert ds.meta["source_crs"] == "EPSG:3346"
    assert abs(ds.structures[0].lat - 54.9) < 1e-6
