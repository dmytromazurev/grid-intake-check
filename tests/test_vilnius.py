"""Golden numbers on the real OpenStreetMap extract around Vilnius (snapshot 2026-10-15, coverage box 25.00–25.50 E, 54.58–54.82 N)."""

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
    assert s["counts"]["context_structures"] == 985  # on the same lines, outside the coverage box
    assert s["coverage"] == "declared"


def test_checks_golden(res):
    c = {x.id: x.count for x in res.checks}
    assert c == {
        "line-voltage-missing": 25, "line-voltage-invalid": 0, "line-voltage-multi": 0, "cables-circuits": 0,
        "joint-voltage": 0, "dangling-end": 4, "bend-no-structure": 29, "orphan-structure": 1,
        "duplicate-structure": 0, "span-long": 3, "span-short": 0, "fixme": 1,
    }


def test_score_and_endpoints(res):
    assert res.score == 53
    assert res.parts == {"attributes": 24, "topology": 92, "geometry": 66}
    assert res.endpoints == {"total": 378, "on_structure": 224, "at_substation": 118, "joint": 4, "dangling": 4, "edge": 28}


def test_span_medians(res):
    med = {k: round(v["median"]) for k, v in res.span_stats.items()}
    assert med["110 kV"] == 200 and med["330 kV"] == 300
    assert max(v["max"] for v in res.span_stats.values()) < 1000  # no artefact spans across the coverage edge


def test_headline_mentions_structure_numbers(res):
    assert res.headline()[0].startswith("1,275 of 1,275 structures")


def test_no_issue_outside_coverage(res):
    for i in res.issues:
        assert 25.00 <= i.lon <= 25.50 and 54.58 <= i.lat <= 54.82, i


def test_dangling_ends_name_the_nearby_line(res):
    d = [i for i in res.issues if i.check == "dangling-end"]
    assert d and all("passes" in i.detail and "m away" in i.detail for i in d)


def test_reports_render(res):
    assert gi.issues_csv(res).count("\n") == len(res.issues) + 1
    svg = gi.svg_map(res)
    assert svg.startswith("<svg") and svg.count("<circle") >= len(res.issues)
    html = gi.html_report(res, request_text=gi.customer_request(res, "Vilnius extract"))
    assert "Readiness" not in html or "/ 100" in html
    assert "Draft customer request" in html
