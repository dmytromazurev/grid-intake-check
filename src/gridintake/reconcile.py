"""Register vs survey reconciliation.

Matches structures in the customer register to structures detected in a survey (LiDAR
classification output) one-to-one within a tolerance, in both directions, and sorts the
leftovers by likely cause so each goes to the right fix.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from statistics import median
from typing import Any

import shapely
from pyproj import Transformer
from shapely import STRtree

from .analyse import AnalysisResult
from .io import Structure, read_json


@dataclass
class Detection:
    id: str
    x: float
    y: float
    cls: str = "structure"  # structure | tower | pole_np (non-power pole, e.g. street light)


@dataclass
class Detections:
    points: list[Detection]
    synthetic: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class Reconciliation:
    tolerance_m: float
    pairs: list[tuple[Structure, Detection, float]]
    mispositioned: list[tuple[Structure, Detection, float]]
    missing: list[Structure]
    unrecorded: list[Detection]
    non_power: list[Detection]
    stats: dict[str, float]
    systematic_offsets: list[dict[str, Any]]
    synthetic: bool

    def to_dict(self, limit: int = 200) -> dict[str, Any]:
        def s(st: Structure) -> dict[str, Any]:
            return {"id": st.id, "lon": st.lon, "lat": st.lat, "x": st.x, "y": st.y}

        def d(dt: Detection) -> dict[str, Any]:
            return {"id": dt.id, "x": dt.x, "y": dt.y, "class": dt.cls}

        return {
            "tolerance_m": self.tolerance_m,
            "synthetic_detections": self.synthetic,
            "counts": {"matched": len(self.pairs), "mispositioned": len(self.mispositioned), "missing": len(self.missing),
                       "unrecorded": len(self.unrecorded), "non_power": len(self.non_power)},
            "offset_stats_m": {k: round(v, 3) for k, v in self.stats.items()},
            "systematic_offsets": self.systematic_offsets,
            "mispositioned": [{"register": s(a), "detection": d(b), "distance_m": round(dd, 2)} for a, b, dd in self.mispositioned[:limit]],
            "missing": [s(x) for x in self.missing[:limit]],
            "unrecorded": [d(x) for x in self.unrecorded[:limit]],
            "non_power": [d(x) for x in self.non_power[:limit]],
        }


def load_detections(source: Any, res: AnalysisResult, crs: str | None = None) -> Detections:
    """GeoJSON points; ``properties.class`` = ``pole_np`` marks non-power poles."""
    gj = read_json(source)
    src = crs or "EPSG:4326"
    tr = Transformer.from_crs(src, res.dataset.working_crs, always_xy=True)
    pts = []
    for i, f in enumerate(gj.get("features", []), 1):
        g = (f or {}).get("geometry") or {}
        if g.get("type") != "Point":
            continue
        x, y = tr.transform(*g["coordinates"][:2])
        props = f.get("properties") or {}
        pts.append(Detection(str(f.get("id", props.get("id", f"D{i}"))), x, y, str(props.get("class", props.get("cls", "structure")))))
    if not pts:
        raise ValueError("No Point features found in the detections file.")
    return Detections(pts)


def simulate_detections(res: AnalysisResult, seed: int = 7) -> Detections:
    """Synthetic detections for demos: 0.5 m noise, ~3.5% missed, one 110 kV line offset ≈5 m,
    unrecorded structures on long spans, and street-light false positives."""
    rnd = random.Random(seed)
    S = res.dataset.structures
    lines110 = sorted((ln for ln in res.dataset.lines if res.line_info[ln.id]["voltage_class"] == "110 kV"), key=lambda ln: -len(ln.xy))
    offset_line = lines110[3] if len(lines110) > 3 else (lines110[0] if lines110 else None)
    offset_ids: set[str] = set()
    if offset_line:
        tree = STRtree(shapely.points([s.x for s in S], [s.y for s in S]))
        for x, y in offset_line.xy:
            idx = tree.query_nearest(shapely.Point(x, y), max_distance=1.0, all_matches=False)
            if len(idx):
                offset_ids.add(S[int(idx[0])].id)
    det: list[Detection] = []
    k = 0
    for s in S:
        if rnd.random() < 0.035:
            continue
        dx, dy = rnd.gauss(0, 0.5), rnd.gauss(0, 0.5)
        if s.id in offset_ids:
            dx -= 4.2
            dy += 2.6
        k += 1
        det.append(Detection(f"D{k}", s.x - dx, s.y - dy, "structure" if s.power == "pole" else "tower"))
    long_spans = [sp for sp in res.spans if sp.length > 1.6 * res.span_stats[sp.voltage_class]["median"]][:12]
    for sp in long_spans:
        k += 1
        det.append(Detection(f"D{k}", (sp.a.x + sp.b.x) / 2 + rnd.gauss(0, 1), (sp.a.y + sp.b.y) / 2 + rnd.gauss(0, 1), "tower"))
    lines = res.dataset.lines
    for _ in range(round(len(S) * 0.015)):
        ln = lines[int(rnd.random() * len(lines))]
        x, y = ln.xy[int(rnd.random() * len(ln.xy))]
        k += 1
        det.append(Detection(f"D{k}", x + 6 + rnd.random() * 20, y + 6 + rnd.random() * 20, "pole_np"))
    note = f"Synthetic detections (seed {seed}); line {offset_line.id} shifted ≈5 m." if offset_line else f"Synthetic detections (seed {seed})."
    return Detections(det, synthetic=True, notes=[note])


def reconcile(res: AnalysisResult, det: Detections, tolerance_m: float = 3.0) -> Reconciliation:
    S, D = res.dataset.structures, det.points
    d_tree = STRtree(shapely.points([d.x for d in D], [d.y for d in D]))
    s_pts = shapely.points([s.x for s in S], [s.y for s in S])
    si, di = d_tree.query(s_pts, predicate="dwithin", distance=tolerance_m)
    cand = sorted(((math.dist((S[a].x, S[a].y), (D[b].x, D[b].y)), a, b) for a, b in zip(si.tolist(), di.tolist(), strict=True)))
    used_s, used_d, pairs = set(), set(), []
    for dd, a, b in cand:  # greedy one-to-one: two records can’t claim one detection
        if a in used_s or b in used_d:
            continue
        used_s.add(a)
        used_d.add(b)
        pairs.append((S[a], D[b], dd))
    reg_only = [i for i in range(len(S)) if i not in used_s]
    det_only = [j for j in range(len(D)) if j not in used_d]

    mispositioned: list[tuple[Structure, Detection, float]] = []
    taken: set[int] = set()
    if det_only:
        left = STRtree(shapely.points([D[j].x for j in det_only], [D[j].y for j in det_only]))
        for i in reg_only:
            hits = left.query(shapely.Point(S[i].x, S[i].y), predicate="dwithin", distance=tolerance_m * 3).tolist()
            hits = [h for h in hits if det_only[h] not in taken]
            if hits:
                h = min(hits, key=lambda h: math.dist((S[i].x, S[i].y), (D[det_only[h]].x, D[det_only[h]].y)))
                j = det_only[h]
                taken.add(j)
                mispositioned.append((S[i], D[j], math.dist((S[i].x, S[i].y), (D[j].x, D[j].y))))
    mis_ids = {m[0].id for m in mispositioned}
    missing = [S[i] for i in reg_only if S[i].id not in mis_ids]
    unrecorded = [D[j] for j in det_only if j not in taken and D[j].cls != "pole_np"]
    non_power = [D[j] for j in det_only if j not in taken and D[j].cls == "pole_np"]

    dists = [p[2] for p in pairs]
    stats = {"median": median(dists) if dists else 0.0,
             "p95": sorted(dists)[min(len(dists) - 1, int(0.95 * (len(dists) - 1)))] if dists else 0.0,
             "max": max(dists) if dists else 0.0}

    # group mispositioned records by line: a shared shift vector means one systematic error
    by_line: dict[str, list[tuple[Structure, Detection, float]]] = {}
    for m in mispositioned:
        for ln in res.dataset.lines:
            if any(math.dist(p, (m[0].x, m[0].y)) < 1 for p in ln.xy):
                by_line.setdefault(ln.id, []).append(m)
                break
    systematic = []
    for lid, ms in sorted(by_line.items(), key=lambda kv: -len(kv[1])):
        if len(ms) < 5:
            continue
        dx = sum(d.x - s.x for s, d, _ in ms) / len(ms)
        dy = sum(d.y - s.y for s, d, _ in ms) / len(ms)
        ln = next(x for x in res.dataset.lines if x.id == lid)
        systematic.append({"line_id": lid, "line_name": ln.tags.get("name", ""), "records": len(ms),
                           "mean_shift_east_m": round(dx, 2), "mean_shift_north_m": round(dy, 2),
                           "advice": "One systematic error (e.g. an old digitising source): fix the source transform once and re-run."})
    return Reconciliation(tolerance_m, pairs, mispositioned, missing, unrecorded, non_power, stats, systematic, det.synthetic)
