"""Exports: issues CSV, JSON, an SVG map and a standalone HTML report."""

from __future__ import annotations

import csv
import html
import io
import json
from typing import Any

from .analyse import AnalysisResult

CLASS_COLOURS = {"330 kV": "#6A3FB5", "110 kV": "#1F6FC4", "35 kV": "#0E8C86", "6–20 kV": "#4C8A2B", "LV": "#8A7B2B", "unknown": "#8C8F97"}
SEV_COLOURS = {"high": "#D9480F", "medium": "#B07A00", "low": "#5D6472"}


def issues_csv(res: AnalysisResult) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["check", "severity", "feature", "id", "lat", "lon", "x", "y", "detail"])
    for i in res.issues:
        w.writerow([i.check, i.severity, i.feature, i.feature_id, f"{i.lat:.7f}", f"{i.lon:.7f}", f"{i.x:.2f}", f"{i.y:.2f}", i.detail])
    return buf.getvalue()


def to_json(res: AnalysisResult, issue_limit: int | None = None) -> str:
    return json.dumps(res.to_dict(issue_limit), ensure_ascii=False, indent=2)


def svg_map(res: AnalysisResult, width: int = 900, checks: set[str] | None = None) -> str:
    minx, miny, maxx, maxy = res.bounds
    w, h = maxx - minx or 1, maxy - miny or 1
    height = max(200, int(width * h / w))
    pad = 12
    k = min((width - 2 * pad) / w, (height - 2 * pad) / h)

    def X(x: float) -> float:
        return pad + (x - minx) * k

    def Y(y: float) -> float:
        return height - pad - (y - miny) * k

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" font-family="sans-serif">',
             f'<rect width="{width}" height="{height}" fill="#F7F6F2"/>']
    for sb in res.dataset.substations:
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in sb.ring_xy)
        parts.append(f'<polygon points="{pts}" fill="rgba(31,78,140,.12)" stroke="rgba(31,78,140,.4)" stroke-width="0.6"/>')
    for ln in res.dataset.lines:
        cls = res.line_info[ln.id]["voltage_class"]
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in ln.xy)
        dash = ' stroke-dasharray="4 3"' if cls == "unknown" else ""
        sw = 2.2 if cls == "330 kV" else 1.6 if cls == "110 kV" else 1.1
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{CLASS_COLOURS.get(cls, "#888")}" stroke-width="{sw}"{dash}/>')
    for i in res.issues:
        if checks is not None and i.check not in checks:
            continue
        parts.append(f'<circle cx="{X(i.x):.1f}" cy="{Y(i.y):.1f}" r="5" fill="none" stroke="{SEV_COLOURS[i.severity]}" stroke-width="1.6"><title>{html.escape(i.check)}: {html.escape(i.detail)}</title></circle>')
    ly = 18
    for name, col in CLASS_COLOURS.items():
        if any(info["voltage_class"] == name for info in res.line_info.values()):
            parts.append(f'<line x1="{pad + 4}" y1="{ly}" x2="{pad + 26}" y2="{ly}" stroke="{col}" stroke-width="3"/><text x="{pad + 32}" y="{ly + 4}" font-size="11" fill="#1A1F2B">{html.escape(name)}</text>')
            ly += 16
    for sev in ("high", "medium", "low"):
        parts.append(f'<circle cx="{pad + 15}" cy="{ly}" r="5" fill="none" stroke="{SEV_COLOURS[sev]}" stroke-width="1.6"/><text x="{pad + 32}" y="{ly + 4}" font-size="11" fill="#1A1F2B">{sev} issue</text>')
        ly += 16
    parts.append("</svg>")
    return "\n".join(parts)


def html_report(res: AnalysisResult, title: str = "Grid intake report", request_text: str | None = None) -> str:
    s: dict[str, Any] = res.summary()
    e = html.escape

    def comp_rows(key: str) -> str:
        return "".join(f"<tr><td>{e(f['label'])}<br><code>{e(f['key'])}</code></td><td class=r>{f['have']:,} / {f['total']:,}</td>"
                       f"<td class=r>{(100 * f['have'] // max(1, f['total']))}%</td><td>{e(f['why'])}</td></tr>" for f in res.completeness[key])

    checks = "".join(f"<tr><td><span class='sev {c.severity}'></span>{e(c.title)}</td><td class=r>{c.count if c.count else 'pass'}</td><td>{e(c.help)}</td></tr>" for c in res.checks)
    issues = "".join(f"<tr><td>{e(i.check)}</td><td>{e(i.severity)}</td><td>{e(i.feature)} {e(i.feature_id)}</td><td>{i.lat:.5f}, {i.lon:.5f}</td><td>{e(i.detail)}</td></tr>" for i in res.issues[:500])
    spans = "".join(f"<tr><td>{e(k)}</td><td class=r>{v['n']:,.0f}</td><td class=r>{v['median']:,.0f} m</td><td class=r>{v['p95']:,.0f} m</td><td class=r>{v['max']:,.0f} m</td></tr>" for k, v in s["span_stats"].items())
    req = f"<h2>Draft customer request</h2><pre>{e(request_text)}</pre>" if request_text else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>
body{{font-family:-apple-system,"Segoe UI",Roboto,sans-serif;margin:0;background:#F3F2EE;color:#1A1F2B;line-height:1.5}}
main{{max-width:1000px;margin:0 auto;padding:24px 16px 48px}} h1,h2{{line-height:1.2}} table{{border-collapse:collapse;width:100%;font-size:14px;margin:8px 0 24px}}
th,td{{text-align:left;vertical-align:top;padding:6px 8px;border-bottom:1px solid #D6D4CC}} td.r{{text-align:right;font-variant-numeric:tabular-nums}}
code,pre{{font-family:ui-monospace,Menlo,monospace;font-size:12.5px}} pre{{background:#E9E8E2;padding:12px;border-radius:6px;white-space:pre-wrap}}
.score{{font-size:48px;font-weight:700}} .sev{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;background:#2F7D4A}}
.sev.high{{background:#D9480F}} .sev.medium{{background:#B07A00}} .sev.low{{background:#5D6472}} svg{{max-width:100%;height:auto;border:1px solid #D6D4CC;border-radius:6px}}
</style></head><body><main>
<h1>{e(title)}</h1>
<p>{s['counts']['structures']:,} structures · {s['counts']['lines']:,} lines · {s['counts']['line_km']:,} km · {s['counts']['substations']:,} substations · working CRS {e(s['working_crs'])} · rule pack {e(s['rulepack'])}</p>
<p class="score">{s['score']} / 100</p><p>Attributes {s['parts']['attributes']} · Topology {s['parts']['topology']} · Geometry {s['parts']['geometry']}</p>
<h2>Headline findings</h2><ol>{''.join(f'<li>{e(h)}</li>' for h in s['headline'])}</ol>
{svg_map(res)}
<h2>Checks</h2><table><tr><th>Check</th><th class=r>Issues</th><th>Why it matters</th></tr>{checks}</table>
<h2>Structure attributes</h2><table><tr><th>Attribute</th><th class=r>Filled</th><th class=r>%</th><th>Why it matters</th></tr>{comp_rows('structures')}</table>
<h2>Line attributes</h2><table><tr><th>Attribute</th><th class=r>Filled</th><th class=r>%</th><th>Why it matters</th></tr>{comp_rows('lines')}</table>
<h2>Spans by voltage class</h2><table><tr><th>Class</th><th class=r>Spans</th><th class=r>Median</th><th class=r>P95</th><th class=r>Max</th></tr>{spans}</table>
<h2>Issues (first 500 of {len(res.issues):,})</h2><table><tr><th>Check</th><th>Severity</th><th>Feature</th><th>Lat, lon</th><th>Detail</th></tr>{issues}</table>
{req}
</main></body></html>"""
