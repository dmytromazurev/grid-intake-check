"""Formulas, customer request and CLI."""

from __future__ import annotations

import json

import gridintake as gi
from gridintake.cli import main


def test_formulas_use_mapping_and_overrides(vilnius_path):
    res = gi.run(vilnius_path)
    f = {x["name"]: x["formula"] for x in gi.formulas(res)}
    assert 'map("concrete", "CONCRETE_POLE"' in f["u_material_type"]
    assert 'get_prop(gis_properties, "material", "text")' in f["u_material_type"]
    over = {x["name"]: x["formula"] for x in gi.formulas(res, {"material": {"concrete": "CONC_12M"}})}
    assert '"concrete", "CONC_12M"' in over["u_material_type"]
    table = {row["field"]: row for row in gi.mapping_table(res)}
    assert table["material"]["missing"] == 1254


def test_customer_request_lists_gaps(vilnius_path):
    text = gi.customer_request(gi.run(vilnius_path), "the Vilnius extract")
    assert "Structure numbers: missing for 1,275 of 1,275 structures" in text
    assert "Line voltage: missing for 25 lines" in text
    assert "4 line ends stop without a structure or substation" in text


def test_cli_check_outputs(vilnius_path, tmp_path, capsys):
    out = tmp_path / "r.json"
    assert main(["check", str(vilnius_path), "--json", str(out), "--csv", str(tmp_path / "i.csv")]) == 0
    assert "Readiness 53/100" in capsys.readouterr().out
    assert json.loads(out.read_text())["summary"]["score"] == 53


def test_cli_fail_under_gate(vilnius_path):
    assert main(["check", str(vilnius_path), "--fail-under", "90"]) == 1


def test_cli_reports_bad_input(tmp_path, capsys):
    bad = tmp_path / "bad.geojson"
    bad.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [582510, 6061948]}}]}))
    assert main(["check", str(bad)]) == 2
    assert "projected CRS" in capsys.readouterr().err


def test_cli_reconcile_simulate(vilnius_path, capsys):
    assert main(["reconcile", str(vilnius_path), "--simulate"]) == 0
    out = capsys.readouterr().out
    assert "SIMULATED" in out and "Systematic offset" in out


def test_cli_and_run_accept_coverage(vilnius_path, capsys):
    small = "25.20,54.65,25.35,54.75"
    res = gi.run(vilnius_path, coverage=small)
    assert 0 < len(res.scope_structures) < 1275
    assert all(25.20 <= i.lon <= 25.35 and 54.65 <= i.lat <= 54.75 for i in res.issues)
    assert main(["check", str(vilnius_path), "--coverage", small]) == 0
    assert "coverage declared" in capsys.readouterr().out
