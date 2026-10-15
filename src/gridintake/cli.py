"""Command line: ``gridintake check|reconcile|formulas|request|rules|serve|mcp``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import (
    IntakeError,
    builtin_names,
    customer_request,
    formulas,
    html_report,
    issues_csv,
    load_detections,
    load_rulepack,
    reconcile,
    run,
    simulate_detections,
    svg_map,
    to_json,
)


def _write(path: str, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")
    print(f"wrote {path}", file=sys.stderr)


def cmd_check(a: argparse.Namespace) -> int:
    res = run(a.file, crs=a.crs, rulepack=a.rules)
    s = res.summary()
    print(f"{Path(a.file).name}: {s['counts']['structures']:,} structures, {s['counts']['lines']:,} lines, "
          f"{s['counts']['line_km']:,} km, {s['counts']['substations']:,} substations · CRS {s['working_crs']}")
    print(f"Readiness {s['score']}/100  (attributes {s['parts']['attributes']}, topology {s['parts']['topology']}, geometry {s['parts']['geometry']})")
    for c in res.checks:
        mark = {"pass": "ok  ", "low": "low ", "medium": "MED ", "high": "HIGH"}[c.severity]
        print(f"  [{mark}] {c.title:<38} {c.count if c.count else '':>5}")
    if s["headline"]:
        print("Findings:")
        for h in s["headline"]:
            print(f"  - {h}")
    for n in s["notes"]:
        print(f"note: {n}", file=sys.stderr)
    if a.json:
        _write(a.json, to_json(res))
    if a.csv:
        _write(a.csv, issues_csv(res))
    if a.svg:
        _write(a.svg, svg_map(res))
    if a.html:
        _write(a.html, html_report(res, title=f"Grid intake report: {Path(a.file).name}", request_text=customer_request(res, Path(a.file).name)))
    if a.fail_under is not None and s["score"] < a.fail_under:
        print(f"Readiness {s['score']} is below --fail-under {a.fail_under}", file=sys.stderr)
        return 1
    return 0


def cmd_reconcile(a: argparse.Namespace) -> int:
    res = run(a.file, crs=a.crs, rulepack=a.rules)
    if a.simulate:
        det = simulate_detections(res, seed=a.seed)
    elif a.detections:
        det = load_detections(a.detections, res, crs=a.detections_crs)
    else:
        print("Give --detections FILE or --simulate", file=sys.stderr)
        return 2
    rec = reconcile(res, det, tolerance_m=a.tolerance)
    d = rec.to_dict(limit=a.limit)
    if det.synthetic:
        print("SIMULATED detections (synthetic, for demonstration only)")
    c = d["counts"]
    print(f"Tolerance {a.tolerance} m · matched {c['matched']:,} · mispositioned {c['mispositioned']} · missing {c['missing']} · "
          f"unrecorded {c['unrecorded']} · non-power poles {c['non_power']}")
    st = d["offset_stats_m"]
    print(f"Matched offset median {st['median']:.2f} m, P95 {st['p95']:.2f} m, max {st['max']:.2f} m")
    for so in d["systematic_offsets"]:
        print(f"Systematic offset: {so['records']} records on line {so['line_id']} {so['line_name']} "
              f"shifted ≈ {so['mean_shift_east_m']} m E, {so['mean_shift_north_m']} m N. {so['advice']}")
    if a.json:
        _write(a.json, json.dumps(d, ensure_ascii=False, indent=2))
    return 0


def cmd_formulas(a: argparse.Namespace) -> int:
    res = run(a.file, crs=a.crs, rulepack=a.rules)
    for f in formulas(res):
        print(f"// {f['name']} · {f['purpose']}\n{f['formula']}\n")
    return 0


def cmd_request(a: argparse.Namespace) -> int:
    res = run(a.file, crs=a.crs, rulepack=a.rules)
    print(customer_request(res, a.name or Path(a.file).name))
    return 0


def cmd_rules(a: argparse.Namespace) -> int:
    if a.show:
        print(json.dumps(load_rulepack(a.show).to_dict(), ensure_ascii=False, indent=2))
    else:
        print("\n".join(builtin_names()))
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("gridintake.api:app", host=a.host, port=a.port)
    return 0


def cmd_mcp(_: argparse.Namespace) -> int:
    from .mcp_server import main as mcp_main

    mcp_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gridintake", description="Pre-ingest QA for utility power-grid data.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("file", help="GeoJSON, Overpass JSON or compact demo JSON")
        sp.add_argument("--crs", help="source CRS if not EPSG:4326, e.g. EPSG:3346")
        sp.add_argument("--rules", default="default", help="built-in rule pack name or path to a YAML rule pack")

    c = sub.add_parser("check", help="run all intake checks")
    common(c)
    c.add_argument("--json")
    c.add_argument("--csv")
    c.add_argument("--svg")
    c.add_argument("--html")
    c.add_argument("--fail-under", type=int, help="exit 1 if readiness is below this (for CI / pipelines)")
    c.set_defaults(fn=cmd_check)

    r = sub.add_parser("reconcile", help="match register structures to survey detections")
    common(r)
    r.add_argument("--detections", help="GeoJSON points from the survey")
    r.add_argument("--detections-crs")
    r.add_argument("--simulate", action="store_true", help="use synthetic detections (demo only)")
    r.add_argument("--seed", type=int, default=7)
    r.add_argument("--tolerance", type=float, default=3.0)
    r.add_argument("--limit", type=int, default=200)
    r.add_argument("--json")
    r.set_defaults(fn=cmd_reconcile)

    f = sub.add_parser("formulas", help="print report-formula snippets from the value mapping")
    common(f)
    f.set_defaults(fn=cmd_formulas)

    q = sub.add_parser("request", help="draft the data request to the customer")
    common(q)
    q.add_argument("--name", help="how to name the dataset in the message")
    q.set_defaults(fn=cmd_request)

    ru = sub.add_parser("rules", help="list built-in rule packs or show one")
    ru.add_argument("--show")
    ru.set_defaults(fn=cmd_rules)

    s = sub.add_parser("serve", help="run the REST API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)

    m = sub.add_parser("mcp", help="run the MCP server over stdio")
    m.set_defaults(fn=cmd_mcp)
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    except (IntakeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
