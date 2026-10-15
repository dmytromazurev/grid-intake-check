"""Source-value mapping and report-formula snippets.

Snippets use only functions documented in Neara’s public Formula language reference
(knowledge.neara.com): ``map_lookup``, ``map``, ``get_prop``, ``try``, ``if``, ``let``, ``len``,
``find_unattached_poles`` and unit literals. Field names such as ``gis_properties`` follow the
reference’s examples and must be checked against the real project schema. Library type names
come from the rule pack and are placeholders.
"""

from __future__ import annotations

from typing import Any

from .analyse import AnalysisResult

MAPPED_FIELDS = ["power", "material", "line_attachment", "design"]


def value_counts(res: AnalysisResult, field: str) -> dict[str, Any]:
    counts: dict[str, int] = {}
    missing = 0
    for s in res.scope_structures:
        v = s.power if field == "power" else s.tags.get(field)
        if v in (None, ""):
            missing += 1
        else:
            counts[v] = counts.get(v, 0) + 1
    return {"field": field, "values": dict(sorted(counts.items(), key=lambda kv: -kv[1])), "missing": missing, "total": len(res.scope_structures)}


def mapping_table(res: AnalysisResult, overrides: dict[str, dict[str, str]] | None = None) -> list[dict[str, Any]]:
    overrides = overrides or {}
    rows = []
    for f in MAPPED_FIELDS:
        vc = value_counts(res, f)
        base = {**res.rules.mapping.get(f, {}), **overrides.get(f, {})}
        rows.append({**vc, "mapping": {v: base.get(v, "") for v in vc["values"]},
                     "unmapped_values": [v for v in vc["values"] if not base.get(v)]})
    return rows


def map_lookup_formula(field: str, mapping: dict[str, str]) -> str:
    pairs = [(k, v) for k, v in mapping.items() if v]
    if not pairs:
        return f"// no mapped values for {field} yet"
    body = ",\n      ".join(f'"{k}", "{v}"' for k, v in pairs)
    return f'map_lookup(\n  map({body}),\n  get_prop(gis_properties, "{field}", "text"),\n  "UNMAPPED"\n)'


def formulas(res: AnalysisResult, overrides: dict[str, dict[str, str]] | None = None) -> list[dict[str, str]]:
    table = {row["field"]: row for row in mapping_table(res, overrides)}
    return [
        {"name": "u_material_type", "purpose": "material → library type", "formula": map_lookup_formula("material", table["material"]["mapping"])},
        {"name": "u_structure_role", "purpose": "suspension or tension", "formula": map_lookup_formula("line_attachment", table["line_attachment"]["mapping"])},
        {"name": "u_qa_structure_number", "purpose": "flag missing structure numbers",
         "formula": 'if(try(get_prop(gis_properties, "ref", "text"), "") = "", "NO STRUCTURE NUMBER", "OK")'},
        {"name": "u_qa_unattached", "purpose": "Spans report: loose poles next to a span",
         "formula": 'if(len(find_unattached_poles(self, 5m)) > 0, "CHECK: unattached pole within 5 m", "OK")'},
        {"name": "u_required_ground_clearance", "purpose": "example thresholds by voltage, not a standard",
         "formula": 'let(\n  v: get_prop(gis_properties, "voltage", "real"),\n  if(v >= 300000, 8.0m, v >= 100000, 7.0m, v >= 30000, 6.5m, 6.0m)\n)'},
    ]
