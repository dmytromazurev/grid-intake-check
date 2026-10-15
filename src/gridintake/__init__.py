"""Grid Intake Check: pre-ingest QA for utility power-grid data."""

from .analyse import AnalysisResult, Issue, analyse, parse_voltage
from .formulas import formulas, mapping_table
from .io import Dataset, IntakeError, load_dataset
from .reconcile import Reconciliation, load_detections, reconcile, simulate_detections
from .report import html_report, issues_csv, svg_map, to_json
from .request import customer_request
from .rules import RulePack, builtin_names, load_rulepack

__version__ = "0.1.0"


def run(source, crs: str | None = None, rulepack: str | None = None) -> AnalysisResult:
    """Load a file (or dict) and run all intake checks with a rule pack."""
    rules = load_rulepack(rulepack)
    ds = load_dataset(source, crs=crs, field_aliases=rules.field_aliases)
    return analyse(ds, rules)


__all__ = [
    "AnalysisResult", "Dataset", "Issue", "IntakeError", "Reconciliation", "RulePack",
    "analyse", "builtin_names", "customer_request", "formulas", "html_report", "issues_csv",
    "load_dataset", "load_detections", "load_rulepack", "mapping_table", "parse_voltage",
    "reconcile", "run", "simulate_detections", "svg_map", "to_json", "__version__",
]
