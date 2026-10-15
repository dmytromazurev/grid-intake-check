"""Intake checks and the readiness score.

All distances are in metres in the dataset's working CRS. The logic mirrors ``web/engine.js``
(the browser demo); ``tests/test_parity.py`` keeps the two in step.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Any

import numpy as np
import shapely
from shapely import STRtree

from .io import Dataset, Line, Structure
from .rules import RulePack, load_rulepack


@dataclass
class Issue:
    check: str
    severity: str  # high | medium | low
    feature: str  # line | structure
    feature_id: str
    x: float
    y: float
    lon: float
    lat: float
    detail: str


@dataclass
class Check:
    id: str
    title: str
    group: str
    help: str
    count: int = 0
    severity: str = "pass"


CHECKS: list[tuple[str, str, str, str]] = [
    ("line-voltage-missing", "Lines without voltage", "Attributes",
     "Without voltage the line gets no clearance rule and no standard. Ask the utility, or infer from connected substations and structure type and mark as assumed."),
    ("line-voltage-invalid", "Unparseable voltage values", "Attributes",
     "Normalise units (V vs kV) and separators at ingest; never guess silently."),
    ("line-voltage-multi", "Several voltages on one line", "Attributes",
     "Shared-structure lines carry several circuits. Model them as separate circuits on the same structures."),
    ("cables-circuits", "Cables don’t match circuits", "Attributes",
     "For 3-phase AC, cables = 3 × circuits. A mismatch points to a wrong attribute or an earth wire counted as a cable."),
    ("joint-voltage", "Voltage changes at a line joint", "Topology",
     "Two line pieces meeting end to end with different voltages usually means one of them is wrong."),
    ("dangling-end", "Dangling line ends", "Topology",
     "A conductor can’t end in the air. Either a structure or substation is missing from the file, or the line is digitised short."),
    ("bend-no-structure", "Line vertices without a structure", "Topology",
     "In a utility export a line bends only at a structure. Bends without one are missing poles or digitising noise; both change span lengths and sag."),
    ("orphan-structure", "Structures not on any line", "Topology",
     "A structure carrying no line: decommissioned, a stub, or a line missing from the export."),
    ("duplicate-structure", "Duplicate structures", "Geometry",
     "Two records for one physical structure inflate counts and break GIS ↔ LiDAR matching."),
    ("span-long", "Unusually long spans", "Geometry",
     "Compared with the median span of the same voltage class. Very long spans usually skip structures that exist in the field."),
    ("span-short", "Very short spans", "Geometry",
     "Very short spans are often duplicates or gantries inside substations."),
    ("fixme", "Notes left in the source data", "Source",
     "Notes left by whoever produced the data. Read them before trusting the area."),
]
TOPOLOGY_BAD = {"dangling-end", "orphan-structure", "duplicate-structure", "joint-voltage"}
GEOMETRY_BAD = {"span-long", "bend-no-structure"}


@dataclass
class Span:
    line_id: str
    voltage_class: str
    a: Structure
    b: Structure
    length: float


@dataclass
class Voltage:
    ok: bool
    kind: str = ""  # missing | unparseable
    raw: str = ""
    values: list[float] = field(default_factory=list)

    @property
    def max(self) -> float | None:
        return max(self.values) if self.values else None


@dataclass
class AnalysisResult:
    dataset: Dataset
    rules: RulePack
    issues: list[Issue]
    checks: list[Check]
    completeness: dict[str, list[dict[str, Any]]]
    endpoints: dict[str, int]
    spans: list[Span]
    span_stats: dict[str, dict[str, float]]
    line_info: dict[str, dict[str, Any]]
    score: int
    parts: dict[str, int]
    bounds: tuple[float, float, float, float]
    notes: list[str]
    scope_structures: list[Structure] = field(default_factory=list)
    scope_lines: list[Line] = field(default_factory=list)

    def check(self, check_id: str) -> Check:
        return next(c for c in self.checks if c.id == check_id)

    def headline(self) -> list[str]:
        comp = {f["key"]: f for f in self.completeness["structures"] + self.completeness["lines"]}
        out = []
        ref, att, vol = comp.get("ref"), comp.get("line_attachment"), comp.get("voltage")
        if ref and ref["have"] < ref["total"]:
            out.append(f"{ref['total'] - ref['have']:,} of {ref['total']:,} structures ({100 - _pct(ref['have'], ref['total'])}%) have no structure number, "
                       "so the model can’t be matched to the asset register or work orders yet.")
        if att and att["have"] < att["total"]:
            out.append(f"Suspension vs tension is known for only {_pct(att['have'], att['total'])}% of structures; tension sections would have to be inferred from geometry.")
        if vol and vol["have"] < vol["total"]:
            out.append(f"{vol['total'] - vol['have']:,} lines have no voltage, so clearance rules can’t be assigned to them.")
        if n := self.check("dangling-end").count:
            out.append(f"{n} line ends stop in the open (not at a structure, substation or another line).")
        if n := self.check("span-long").count:
            out.append(f"{n} spans are far longer than their voltage class allows for, which usually means missing structures.")
        return out

    def summary(self) -> dict[str, Any]:
        ds = self.dataset
        km: dict[str, float] = {}
        for info in self.line_info.values():
            if info["in_scope"]:
                km[info["voltage_class"]] = km.get(info["voltage_class"], 0) + info["length_in_coverage_m"] / 1000
        types: dict[str, int] = {}
        for s in self.scope_structures:
            types[s.power] = types.get(s.power, 0) + 1
        return {
            "score": self.score,
            "parts": self.parts,
            "working_crs": ds.working_crs_code,
            "source_crs": ds.meta.get("source_crs"),
            "counts": {"structures": len(self.scope_structures), "structure_types": types, "lines": len(self.scope_lines),
                       "line_km": round(sum(km.values()), 1), "line_km_by_class": {k: round(v, 1) for k, v in km.items()},
                       "substations": len(ds.substations), "issues": len(self.issues),
                       "context_structures": len(ds.structures) - len(self.scope_structures),
                       "context_lines": len(ds.lines) - len(self.scope_lines)},
            "coverage": "declared" if ds.coverage_xy else "data extent",
            "headline": self.headline(),
            "endpoints": self.endpoints,
            "span_stats": {k: {kk: round(vv, 1) for kk, vv in v.items()} for k, v in self.span_stats.items()},
            "rulepack": self.rules.name,
            "notes": self.notes,
        }

    def to_dict(self, issue_limit: int | None = None) -> dict[str, Any]:
        issues = self.issues if issue_limit is None else self.issues[:issue_limit]
        return {
            "summary": self.summary(),
            "checks": [asdict(c) for c in self.checks],
            "completeness": self.completeness,
            "issues": [asdict(i) for i in issues],
            "issues_total": len(self.issues),
            "meta": self.dataset.meta,
        }


def _pct(a: int, b: int) -> int:
    return _round(100 * a / b) if b else 0


def _round(x: float) -> int:
    """Round half up, like JavaScript’s Math.round (Python’s round() is banker’s rounding)."""
    return int(math.floor(x + 0.5))


def _p(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(math.floor(q * (len(s) - 1))))] if s else 0.0


def parse_voltage(raw: str | None) -> Voltage:
    if raw is None or str(raw).strip() == "":
        return Voltage(False, "missing")
    parts = [p.strip() for p in str(raw).replace(",", ";").split(";") if p.strip()]
    vals = []
    for p in parts:
        try:
            v = float(p.replace(" ", ""))
        except ValueError:
            return Voltage(False, "unparseable", str(raw))
        if not math.isfinite(v) or v <= 0:
            return Voltage(False, "unparseable", str(raw))
        vals.append(v)
    return Voltage(True, raw=str(raw), values=vals)


def analyse(ds: Dataset, rules: RulePack | None = None) -> AnalysisResult:
    r = rules or load_rulepack("default")
    S, L = ds.structures, ds.lines
    notes = list(ds.notes)
    issues: list[Issue] = []

    def add(check: str, sev: str, feature: str, fid: str, x: float, y: float, lon: float, lat: float, detail: str) -> None:
        issues.append(Issue(check, sev, feature, fid, x, y, lon, lat, detail))

    # Coverage = the area the data is meant to describe (survey footprint, extract box). Without one,
    # the data extent is used. Checks near its edge are skipped: a cut line is not a real gap.
    xs = [s.x for s in S] + [p[0] for ln in L for p in ln.xy]
    ys = [s.y for s in S] + [p[1] for ln in L for p in ln.xy]
    minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
    eb = r.edge_buffer_m
    cov = shapely.Polygon(ds.coverage_xy) if ds.coverage_xy else None
    zone = None
    if cov is not None:
        zone = cov.buffer(-eb) if eb > 0 else cov
        shapely.prepare(cov)
        shapely.prepare(zone)

    def inner(x: float, y: float) -> bool:
        if zone is not None:
            return bool(zone.covers(shapely.Point(x, y)))
        return eb <= 0 or (minx + eb < x < maxx - eb and miny + eb < y < maxy - eb)

    def in_cov(x: float, y: float) -> bool:
        return cov is None or bool(cov.covers(shapely.Point(x, y)))

    line_geom = {ln.id: shapely.LineString(ln.xy) for ln in L}
    scope_s = [s for s in S if in_cov(s.x, s.y)]
    scope_l = [ln for ln in L if cov is None or line_geom[ln.id].intersects(cov)]
    scope_s_ids = {s.id for s in scope_s}
    scope_l_ids = {ln.id for ln in scope_l}
    if cov is not None:
        notes.append(f"Checks limited to the coverage area: {len(scope_s):,} of {len(S):,} structures and "
                     f"{len(scope_l):,} of {len(L):,} lines; the rest is context.")

    # voltage
    volts: dict[str, Voltage] = {ln.id: parse_voltage(ln.tags.get("voltage")) for ln in L}
    parsed_max = [v.max for v in volts.values() if v.ok and v.max is not None]
    kv = r.voltage_unit.lower() == "kv" or (r.voltage_unit.lower() == "auto" and parsed_max and max(parsed_max) <= 1000)
    if kv:
        for v in volts.values():
            v.values = [x * 1000 for x in v.values]
        notes.append("Voltage values interpreted as kV (all values ≤ 1000)." if r.voltage_unit.lower() == "auto" else "Voltage values interpreted as kV.")
    vclass = {lid: r.voltage_class(v.max if v.ok else None) for lid, v in volts.items()}

    # completeness
    def comp(items: list[Any], rules_: list[Any]) -> list[dict[str, Any]]:
        out = []
        for f in rules_:
            have = sum(1 for it in items if str(it.tags.get(f.key, "")).strip() != "")
            out.append({"key": f.key, "label": f.label, "why": f.why, "critical": f.critical, "have": have, "total": len(items)})
        return out

    completeness = {"structures": comp(scope_s, r.structure_fields), "lines": comp(scope_l, r.line_fields)}

    def mid(ln: Line) -> tuple[float, float, float, float]:
        i = len(ln.xy) >> 1
        return (*ln.xy[i], *ln.lonlat[i])

    for ln in scope_l:
        v = volts[ln.id]
        if not v.ok and v.kind == "missing":
            add("line-voltage-missing", "high", "line", ln.id, *mid(ln), "Line has no voltage" + (f" ({ln.tags['name']})" if ln.tags.get("name") else ""))
        elif not v.ok:
            add("line-voltage-invalid", "high", "line", ln.id, *mid(ln), f"Voltage value “{v.raw}” can’t be parsed")
        elif len(v.values) > 1:
            add("line-voltage-multi", "medium", "line", ln.id, *mid(ln), f"Several voltages on one line ({ln.tags.get('voltage')}): split into circuits or confirm a shared-structure line")
        c, k = ln.tags.get("cables"), ln.tags.get("circuits")
        if c and k:
            try:
                cn, kn = float(c), float(k)
                if math.isfinite(cn) and math.isfinite(kn) and cn != 3 * kn:
                    add("cables-circuits", "medium", "line", ln.id, *mid(ln), f"cables={c} but circuits={k} (expected cables = 3 × circuits for 3-phase AC)")
            except ValueError:
                pass

    # spatial indexes
    s_pts = shapely.points([s.x for s in S], [s.y for s in S]) if S else np.array([])
    s_tree = STRtree(s_pts) if S else None
    sub_polys = [shapely.Polygon(sb.ring_xy) for sb in ds.substations if len(sb.ring_xy) >= 4]
    sub_tree = STRtree(sub_polys) if sub_polys else None
    v_owner: list[str] = [ln.id for ln in L for _ in ln.xy]
    v_pts = shapely.points([p[0] for ln in L for p in ln.xy], [p[1] for ln in L for p in ln.xy])
    v_tree = STRtree(v_pts)

    def on_structure(x: float, y: float) -> Structure | None:
        if s_tree is None:
            return None
        idx = s_tree.query_nearest(shapely.Point(x, y), max_distance=r.snap_tolerance_m, all_matches=False)
        return S[int(idx[0])] if len(idx) else None

    used: set[str] = set()
    endpoints = {"total": 0, "on_structure": 0, "at_substation": 0, "joint": 0, "dangling": 0, "edge": 0}
    spans: list[Span] = []
    line_info: dict[str, dict[str, Any]] = {}

    for ln in L:
        prev: Structure | None = None
        along = since = 0.0
        interior = 0
        n = len(ln.xy)
        for i, (x, y) in enumerate(ln.xy):
            if i:
                d = math.dist(ln.xy[i - 1], (x, y))
                along += d
                since += d
            st = on_structure(x, y)
            if st:
                used.add(st.id)
            if i in (0, n - 1):
                endpoints["total"] += 1
                if not inner(x, y):
                    endpoints["edge"] += 1
                elif st:
                    endpoints["on_structure"] += 1
                elif sub_tree is not None and len(sub_tree.query(shapely.Point(x, y), predicate="dwithin", distance=r.substation_tolerance_m)):
                    endpoints["at_substation"] += 1
                elif any(v_owner[j] != ln.id for j in v_tree.query(shapely.Point(x, y), predicate="dwithin", distance=r.snap_tolerance_m)):
                    endpoints["joint"] += 1
                else:
                    endpoints["dangling"] += 1
                    detail = "Line end is not on a structure, a substation or another line"
                    near = [j for j in v_tree.query(shapely.Point(x, y), predicate="dwithin", distance=50.0).tolist() if v_owner[j] != ln.id]
                    if near:
                        j = min(near, key=lambda j: shapely.distance(v_pts[j], shapely.Point(x, y)))
                        detail += f"; line {v_owner[j]} passes {shapely.distance(v_pts[j], shapely.Point(x, y)):.0f} m away, so a structure or connection is probably missing between them"
                    add("dangling-end", "high", "line", ln.id, x, y, *ln.lonlat[i], detail)
            elif not st and inner(x, y):
                interior += 1
            if st:
                if prev and prev.id != st.id and inner(prev.x, prev.y) and inner(st.x, st.y):
                    spans.append(Span(ln.id, vclass[ln.id], prev, st, since))
                prev, since = st, 0.0
        in_scope = ln.id in scope_l_ids
        inside_len = along if cov is None else (line_geom[ln.id].intersection(cov).length if in_scope else 0.0)
        line_info[ln.id] = {"length_m": along, "length_in_coverage_m": inside_len, "voltage_class": vclass[ln.id], "in_scope": in_scope}
        if interior:
            j = max(1, n >> 1)
            add("bend-no-structure", "medium" if interior > 2 else "low", "line", ln.id, *ln.xy[j], *ln.lonlat[j],
                f"{interior} line vertex(es) with no structure: missing pole/tower or digitising noise")

    for s in S:
        if s.id not in used and inner(s.x, s.y):
            add("orphan-structure", "medium", "structure", s.id, s.x, s.y, s.lon, s.lat, f"Structure ({s.power}) is not on any line")

    if s_tree is not None:
        a_idx, b_idx = s_tree.query(s_pts, predicate="dwithin", distance=r.duplicate_tolerance_m)
        for a, b in zip(a_idx.tolist(), b_idx.tolist(), strict=True):
            if a < b and S[a].id in scope_s_ids and S[b].id in scope_s_ids:
                sa, sb = S[a], S[b]
                add("duplicate-structure", "high", "structure", sa.id, sa.x, sa.y, sa.lon, sa.lat,
                    f"Within {math.dist((sa.x, sa.y), (sb.x, sb.y)):.2f} m of structure {sb.id}: likely duplicate record")

    groups: dict[str, list[float]] = {}
    for sp in spans:
        groups.setdefault(sp.voltage_class, []).append(sp.length)
    span_stats = {k: {"n": len(v), "median": median(v), "p95": _p(v, 0.95), "max": max(v)} for k, v in groups.items()}
    for sp in spans:
        m = span_stats[sp.voltage_class]["median"]
        x, y = (sp.a.x + sp.b.x) / 2, (sp.a.y + sp.b.y) / 2
        lo, la = (sp.a.lon + sp.b.lon) / 2, (sp.a.lat + sp.b.lat) / 2
        if sp.length > r.span_long_factor * m:
            add("span-long", "medium", "line", sp.line_id, x, y, lo, la,
                f"Span {_round(sp.length)} m is {sp.length / m:.1f}× the {sp.voltage_class} median ({_round(m)} m): missing structure or skipped pole")
        elif sp.length < r.span_min_length_m:
            add("span-short", "low", "line", sp.line_id, x, y, lo, la, f"Span only {sp.length:.1f} m: possible duplicate structure or gantry")

    # voltage mismatch where two line ends meet
    ends = [(ln, i) for ln in L for i in (0, len(ln.xy) - 1)]
    e_tree = STRtree(shapely.points([ln.xy[i][0] for ln, i in ends], [ln.xy[i][1] for ln, i in ends]))
    seen: set[tuple[str, str]] = set()
    for ln, i in ends:
        v = volts[ln.id]
        if not v.ok or not inner(*ln.xy[i]):
            continue
        for j in e_tree.query(shapely.Point(*ln.xy[i]), predicate="dwithin", distance=r.snap_tolerance_m).tolist():
            other = ends[j][0]
            if other.id == ln.id:
                continue
            key = tuple(sorted((ln.id, other.id)))
            if key in seen:
                continue
            seen.add(key)
            v2 = volts[other.id]
            if v2.ok and v2.max != v.max:
                add("joint-voltage", "medium", "line", ln.id, *ln.xy[i], *ln.lonlat[i],
                    f"Joins line {other.id} but voltage differs ({ln.tags.get('voltage')} vs {other.tags.get('voltage')})")

    for s in scope_s:
        if s.tags.get("fixme"):
            add("fixme", "low", "structure", s.id, s.x, s.y, s.lon, s.lat, f"Source note: {s.tags['fixme']}")

    checks = []
    for cid, title, group, help_ in CHECKS:
        lst = [i for i in issues if i.check == cid]
        sev = "high" if any(i.severity == "high" for i in lst) else "medium" if any(i.severity == "medium" for i in lst) else "low" if lst else "pass"
        checks.append(Check(cid, title, group, help_, len(lst), sev))

    critical = [f for f in completeness["structures"] + completeness["lines"] if f["critical"]]
    attr = sum(f["have"] / max(1, f["total"]) for f in critical) / max(1, len(critical))
    topo_bad = sum(1 for i in issues if i.check in TOPOLOGY_BAD)
    geom_bad = sum(1 for i in issues if i.check in GEOMETRY_BAD)
    topo = max(0.0, 1 - topo_bad / max(1, len(scope_s) * 0.05))
    geom = max(0.0, 1 - geom_bad / max(1, len(scope_l) * 0.5))
    w = r.score_weights
    score = _round(100 * (w.get("attributes", 0.5) * attr + w.get("topology", 0.3) * topo + w.get("geometry", 0.2) * geom))
    parts = {"attributes": _round(attr * 100), "topology": _round(topo * 100), "geometry": _round(geom * 100)}

    return AnalysisResult(ds, r, issues, checks, completeness, endpoints, spans, span_stats, line_info,
                          score, parts, (minx, miny, maxx, maxy), notes, scope_s, scope_l)
