from __future__ import annotations

from conftest import fc, line, point

import gridintake as gi
from gridintake.reconcile import Detection, Detections


def _register(rules):
    gj = fc(*[point(f"t{i}", i * 200, 0) for i in range(6)], line("L1", [(i * 200, 0) for i in range(6)], voltage="110000"))
    return gi.analyse(gi.load_dataset(gj), rules)


def test_categories(rules_no_edge):
    res = _register(rules_no_edge)
    S = res.dataset.structures
    det = Detections([
        Detection("d0", S[0].x + 0.3, S[0].y),          # matched
        Detection("d1", S[1].x, S[1].y - 0.4),          # matched
        Detection("d2", S[2].x + 5.0, S[2].y),          # mispositioned (3–9 m)
        Detection("d3", S[3].x, S[3].y + 0.2),          # matched
        # t4 has no detection → missing
        Detection("d5", S[5].x - 0.1, S[5].y),          # matched
        Detection("new", 500, -150 + S[0].y),           # unrecorded
        Detection("lamp", S[3].x + 30, S[3].y + 30, "pole_np"),  # non-power
    ])
    rec = gi.reconcile(res, det, tolerance_m=3)
    d = rec.to_dict()
    assert d["counts"] == {"matched": 4, "mispositioned": 1, "missing": 1, "unrecorded": 1, "non_power": 1}
    assert d["missing"][0]["id"] == "t4"


def test_one_to_one(rules_no_edge):
    res = _register(rules_no_edge)
    S = res.dataset.structures
    det = Detections([Detection("only", (S[0].x + S[1].x) / 2, S[0].y)])  # far from both
    rec = gi.reconcile(res, det, tolerance_m=150)
    assert len(rec.pairs) == 1  # one detection can't be claimed twice


def test_simulation_finds_systematic_offset(vilnius_path):
    res = gi.run(vilnius_path)
    det = gi.simulate_detections(res, seed=7)
    assert det.synthetic
    rec = gi.reconcile(res, det, tolerance_m=3)
    assert rec.stats["median"] < 1.0
    assert rec.systematic_offsets, "the shifted line should be reported as one systematic error"
    top = rec.systematic_offsets[0]
    assert top["records"] >= 10 and 3.5 < top["mean_shift_east_m"] < 5.5
    assert len(rec.non_power) > 0 and len(rec.unrecorded) > 0
