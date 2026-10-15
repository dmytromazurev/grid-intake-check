"""Rule packs: per-customer tolerances, required attributes, voltage classes and code mappings.

A rule pack is a YAML file. ``default.yaml`` ships with the package; a deployment team would keep
one pack per customer (field aliases, voltage classes, mapping to library types) and reuse it on
every data delivery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class FieldRule:
    key: str
    label: str
    why: str
    critical: bool = False


@dataclass(frozen=True)
class VoltageClass:
    name: str
    min_volts: float


@dataclass
class RulePack:
    name: str
    snap_tolerance_m: float = 1.0
    duplicate_tolerance_m: float = 2.0
    substation_tolerance_m: float = 30.0
    edge_buffer_m: float = 300.0
    span_long_factor: float = 2.5
    span_min_length_m: float = 15.0
    voltage_unit: str = "auto"  # "V", "kV" or "auto"
    voltage_classes: list[VoltageClass] = field(default_factory=list)
    structure_fields: list[FieldRule] = field(default_factory=list)
    line_fields: list[FieldRule] = field(default_factory=list)
    field_aliases: dict[str, list[str]] = field(default_factory=dict)
    score_weights: dict[str, float] = field(default_factory=lambda: {"attributes": 0.5, "topology": 0.3, "geometry": 0.2})
    mapping: dict[str, dict[str, str]] = field(default_factory=dict)

    def voltage_class(self, volts: float | None) -> str:
        if volts is None:
            return "unknown"
        for vc in self.voltage_classes:
            if volts >= vc.min_volts:
                return vc.name
        return "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "snap_tolerance_m": self.snap_tolerance_m,
            "duplicate_tolerance_m": self.duplicate_tolerance_m,
            "substation_tolerance_m": self.substation_tolerance_m,
            "edge_buffer_m": self.edge_buffer_m,
            "span": {"long_factor": self.span_long_factor, "min_length_m": self.span_min_length_m},
            "voltage_unit": self.voltage_unit,
            "voltage_classes": [{"name": v.name, "min_volts": v.min_volts} for v in self.voltage_classes],
            "required_fields": {
                "structure": [vars(f) for f in self.structure_fields],
                "line": [vars(f) for f in self.line_fields],
            },
            "field_aliases": self.field_aliases,
            "score_weights": self.score_weights,
            "mapping": self.mapping,
        }


def _parse(data: dict[str, Any]) -> RulePack:
    span = data.get("span", {}) or {}
    req = data.get("required_fields", {}) or {}
    return RulePack(
        name=str(data.get("name", "custom")),
        snap_tolerance_m=float(data.get("snap_tolerance_m", 1.0)),
        duplicate_tolerance_m=float(data.get("duplicate_tolerance_m", 2.0)),
        substation_tolerance_m=float(data.get("substation_tolerance_m", 30.0)),
        edge_buffer_m=float(data.get("edge_buffer_m", 300.0)),
        span_long_factor=float(span.get("long_factor", 2.5)),
        span_min_length_m=float(span.get("min_length_m", 15.0)),
        voltage_unit=str(data.get("voltage_unit", "auto")),
        voltage_classes=sorted(
            (VoltageClass(str(v["name"]), float(v["min_volts"])) for v in data.get("voltage_classes", [])),
            key=lambda v: -v.min_volts,
        ),
        structure_fields=[FieldRule(**f) for f in req.get("structure", [])],
        line_fields=[FieldRule(**f) for f in req.get("line", [])],
        field_aliases={k: list(v) for k, v in (data.get("field_aliases") or {}).items()},
        score_weights=dict(data.get("score_weights") or {"attributes": 0.5, "topology": 0.3, "geometry": 0.2}),
        mapping={k: {str(a): str(b) for a, b in v.items()} for k, v in (data.get("mapping") or {}).items()},
    )


def builtin_names() -> list[str]:
    return sorted(p.name.removesuffix(".yaml") for p in resources.files("gridintake.rulepacks").iterdir() if p.name.endswith(".yaml"))


def load_rulepack(name_or_path: str | Path | None = None) -> RulePack:
    """Load a built-in pack by name (``default``) or a YAML file by path."""
    if name_or_path is None:
        name_or_path = "default"
    p = Path(name_or_path)
    if p.suffix in {".yaml", ".yml"} and p.exists():
        text = p.read_text(encoding="utf-8")
    else:
        name = str(name_or_path)
        if name not in builtin_names():
            raise ValueError(f"Unknown rule pack {name!r}. Built-in packs: {', '.join(builtin_names())}")
        text = (resources.files("gridintake.rulepacks") / f"{name}.yaml").read_text(encoding="utf-8")
    return _parse(yaml.safe_load(text) or {})
