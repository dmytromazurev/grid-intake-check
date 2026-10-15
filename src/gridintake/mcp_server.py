"""MCP server: lets an AI assistant (Claude Desktop, Claude Code, any MCP client) run intake checks
on local files. Start with ``gridintake mcp`` (stdio transport).

Tools take local file paths. Results are cached per (path, modification time, CRS, rule pack),
so follow-up questions about the same file don't re-run the analysis.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import (
    AnalysisResult,
    customer_request,
    formulas,
    html_report,
    issues_csv,
    load_detections,
    mapping_table,
    reconcile,
    run,
    simulate_detections,
    to_json,
)

mcp = MCPServer(
    "grid-intake-check",
    instructions="Pre-ingest QA for utility power-grid data. Start with check_grid_data on a GeoJSON or Overpass JSON file, "
                 "then drill into list_issues, reconcile_with_survey, generate_formulas or draft_customer_request.",
)
_cache: dict[tuple[str, float, str | None, str, str | None], AnalysisResult] = {}


def _result(path: str, crs: str | None = None, rulepack: str = "default", coverage: str | None = None) -> AnalysisResult:
    p = str(Path(path).expanduser().resolve())
    if not os.path.exists(p):
        raise ValueError(f"File not found: {path}")
    key = (p, os.path.getmtime(p), crs, rulepack, coverage)
    if key not in _cache:
        _cache.clear()
        _cache[key] = run(p, crs=crs, rulepack=rulepack, coverage=coverage)
    return _cache[key]


def check_grid_data(path: str, crs: str | None = None, rulepack: str = "default", coverage: str | None = None) -> dict[str, Any]:
    """Run all intake checks on a GeoJSON / Overpass JSON file of power-grid data.

    Returns the readiness score (0–100), its parts, headline findings, counts, and each check with
    its issue count and why it matters. Use list_issues for individual problems.
    crs: source CRS if the file isn't EPSG:4326, e.g. "EPSG:3346". rulepack: built-in name or YAML path.
    coverage: "west,south,east,north" in lon/lat to limit checks to the surveyed area; data outside it is context.
    """
    res = _result(path, crs, rulepack, coverage)
    return {"summary": res.summary(), "checks": [asdict(c) for c in res.checks], "completeness": res.completeness}


def list_issues(path: str, check: str | None = None, severity: str | None = None, limit: int = 50,
                crs: str | None = None, rulepack: str = "default") -> dict[str, Any]:
    """List individual issues with coordinates, optionally filtered by check id (e.g. "dangling-end",
    "span-long", "line-voltage-missing") and severity ("high", "medium", "low")."""
    res = _result(path, crs, rulepack)
    items = [i for i in res.issues if (check is None or i.check == check) and (severity is None or i.severity == severity)]
    return {"total": len(items), "issues": [asdict(i) for i in items[: max(0, limit)]]}


def reconcile_with_survey(path: str, detections_path: str | None = None, simulate: bool = False, tolerance_m: float = 3.0,
                          crs: str | None = None, rulepack: str = "default") -> dict[str, Any]:
    """Match register structures to survey (LiDAR) detections one-to-one within tolerance_m.

    Give detections_path (GeoJSON points; properties.class = "pole_np" marks street lights/signs)
    or simulate=True for synthetic demo detections. Returns matched / mispositioned / missing /
    unrecorded / non-power counts, offset statistics and systematic offsets grouped by line.
    """
    res = _result(path, crs, rulepack)
    if simulate:
        det = simulate_detections(res)
    elif detections_path:
        det = load_detections(str(Path(detections_path).expanduser()), res)
    else:
        raise ValueError("Give detections_path or set simulate=True")
    return reconcile(res, det, tolerance_m=tolerance_m).to_dict(limit=50)


def generate_formulas(path: str, mapping: dict[str, dict[str, str]] | None = None,
                      crs: str | None = None, rulepack: str = "default") -> dict[str, Any]:
    """Show source attribute values (material, line_attachment, design, power) with counts, their mapping to
    library types, and report-formula snippets (map_lookup etc.). mapping overrides the rule pack, e.g.
    {"material": {"concrete": "CONC_POLE_12M"}}."""
    res = _result(path, crs, rulepack)
    return {"mapping": mapping_table(res, mapping), "formulas": formulas(res, mapping)}


def draft_customer_request(path: str, dataset_name: str | None = None, recipient: str = "[name]", sender: str = "[your name]",
                           crs: str | None = None, rulepack: str = "default") -> str:
    """Draft the data request to the utility listing every gap found, with counts and examples."""
    res = _result(path, crs, rulepack)
    return customer_request(res, dataset_name or Path(path).name, recipient, sender)


def export_report(path: str, out_path: str, format: str = "html", crs: str | None = None, rulepack: str = "default") -> str:
    """Write a report next to the data: format "html" (standalone report with map), "csv" (issues) or "json"."""
    res = _result(path, crs, rulepack)
    if format == "html":
        text = html_report(res, title=f"Grid intake report: {Path(path).name}", request_text=customer_request(res, Path(path).name))
    elif format == "csv":
        text = issues_csv(res)
    elif format == "json":
        text = to_json(res)
    else:
        raise ValueError('format must be "html", "csv" or "json"')
    out = Path(out_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return f"Wrote {out} ({len(text):,} characters)"


for _fn in (check_grid_data, list_issues, reconcile_with_survey, generate_formulas, draft_customer_request):
    mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))(_fn)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))(export_report)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
