"""Golden numbers on the real OpenStreetMap extract around Vilnius (snapshot 2026-10-15)."""

from __future__ import annotations

import pytest

import gridintake as gi


@pytest.fixture(scope="module")
def res(vilnius_path):
    return gi.run(vilnius_path)


def test_counts(res):
    s = res.summary()
    assert s["counts"]["structures"] == 1275
    assert s["counts"]["lines"] == 189
    assert s["counts"]["substations"] == 34
    assert s["working_crs"] == "EPSG:3346"


def test_checks_golden(res):
    c = {x.id: x.count for x in res.checks}
    assert c == {
        "line-voltage-missing": 25, "line-voltage-invalid": 0, "line-voltage-multi": 0, "cables-circuits": 0,
        "joint-voltage": 0, "dangling-end": 13, "bend-no-structure": 42, "orphan-structure": 1,
        "duplicate-structure": 0, "span-long": 7, "span-short": 0, "fixme": 1,
    }


def test_score_and_endpoints(res):
    assert res.score == 45
    assert res.parts == {"attributes": 24, "topology": 78, "geometry": 48}
    assert res.endpoints == {"total": 378, "on_structure": 230, "at_substation": 127, "joint": 4, "dangling": 13, "edge": 4}


def test_span_medians(res):
    med = {k: round(v["median"]) for k, v in res.span_stats.items()}
    assert med["110 kV"] == 200 and med["330 kV"] == 310


def test_headline_mentions_structure_numbers(res):
    assert res.headline()[0].startswith("1,275 of 1,275 structures")


def test_reports_render(res):
    assert gi.issues_csv(res).count("\n") == len(res.issues) + 1
    svg = gi.svg_map(res)
    assert svg.startswith("<svg") and svg.count("<circle") >= len(res.issues)
    html = gi.html_report(res, request_text=gi.customer_request(res, "Vilnius extract"))
    assert "Readiness" not in html or "/ 100" in html
    assert "Draft customer request" in html
