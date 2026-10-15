"""Grid Intake Check: pre-ingest QA for utility power-grid data."""

from .analyse import AnalysisResult, Issue, analyse, parse_voltage
from .formulas import formulas, mapping_table
from .io import Dataset, IntakeError, load_dataset
from .reconcile import Reconciliation, load_detections, reconcile, simulate_detections
from .report import html_report, issues_csv, svg_map, to_json
from .request import customer_request
from .rules import RulePack, builtin_names, load_rulepack

__version__ = "0.1.0"


def parse_coverage(value: str | None) -> list[float] | None:
    """``"west,south,east,north"`` in lon/lat → list, or None."""
    if not value:
        return None
    parts = [float(v) for v in value.replace(" ", "").split(",")]
    if len(parts) != 4:
        raise ValueError("Coverage must be west,south,east,north in lon/lat, e.g. 25.0,54.58,25.5,54.82")
    return parts


def run(source, crs: str | None = None, rulepack: str | None = None, coverage=None) -> AnalysisResult:
    """Load a file (or dict) and run all intake checks with a rule pack.

    ``coverage``: [west, south, east, north] in lon/lat (or "w,s,e,n"), limiting checks to that area."""
    rules = load_rulepack(rulepack)
    cov = parse_coverage(coverage) if isinstance(coverage, str) else coverage
    ds = load_dataset(source, crs=crs, field_aliases=rules.field_aliases, coverage=cov)
    return analyse(ds, rules)


__all__ = [
    "AnalysisResult", "Dataset", "Issue", "IntakeError", "Reconciliation", "RulePack",
    "analyse", "builtin_names", "customer_request", "formulas", "html_report", "issues_csv",
    "load_dataset", "load_detections", "load_rulepack", "mapping_table", "parse_coverage", "parse_voltage",
    "reconcile", "run", "simulate_detections", "svg_map", "to_json", "__version__",
]
