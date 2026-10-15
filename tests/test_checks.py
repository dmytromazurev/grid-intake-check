"""One small synthetic network per check, so each rule is tested in isolation."""

from __future__ import annotations

from conftest import fc, line, point

from gridintake import analyse, load_dataset, parse_voltage


def run(gj, rules):
    return analyse(load_dataset(gj, field_aliases=rules.field_aliases), rules)


def towers(n, step=200.0, y=0.0, prefix="t", **props):
    return [point(f"{prefix}{i}", i * step, y, **props) for i in range(n)]


def straight(n, step=200.0, y=0.0, lid="L1", **props):
    return line(lid, [(i * step, y) for i in range(n)], **props)


def counts(res):
    return {c.id: c.count for c in res.checks}


def test_clean_line_passes(rules_no_edge):
    res = run(fc(*towers(6, ref="A", material="concrete", line_attachment="suspension"),
                 straight(6, voltage="110000", cables="3", circuits="1", name="L", operator="X")), rules_no_edge)
    assert all(v == 0 for v in counts(res).values())
    assert len(res.spans) == 5 and abs(res.span_stats["110 kV"]["median"] - 200) < 0.5
    assert res.parts["attributes"] == 100


def test_voltage_missing_invalid_multi(rules_no_edge):
    res = run(fc(*towers(3), straight(3, lid="a"), straight(3, lid="b", voltage="abc"), straight(3, lid="c", voltage="110000;10000")), rules_no_edge)
    c = counts(res)
    assert (c["line-voltage-missing"], c["line-voltage-invalid"], c["line-voltage-multi"]) == (1, 1, 1)


def test_parse_voltage():
    assert parse_voltage("110000").values == [110000]
    assert parse_voltage("110 000").values == [110000]
    assert parse_voltage("").kind == "missing"
    assert parse_voltage("-5").kind == "unparseable"
    assert parse_voltage("110000,10000").values == [110000, 10000]


def test_kv_values_are_scaled(rules_no_edge):
    res = run(fc(*towers(3), straight(3, voltage="110")), rules_no_edge)
    assert res.line_info["L1"]["voltage_class"] == "110 kV"
    assert any("kV" in n for n in res.notes)


def test_cables_vs_circuits(rules_no_edge):
    res = run(fc(*towers(3), straight(3, voltage="110000", cables="6", circuits="1")), rules_no_edge)
    assert counts(res)["cables-circuits"] == 1


def test_dangling_end_and_joint(rules_no_edge):
    # L1 ends at tower t2; L2 starts at that end; L3 ends in the open
    gj = fc(*towers(3), straight(3, voltage="110000"),
            line("L2", [(400, 0), (400, 200)], voltage="110000"), point("t9", 400, 200),
            line("L3", [(0, 400), (200, 400)], voltage="110000"), point("t10", 0, 400))
    res = run(gj, rules_no_edge)
    assert counts(res)["dangling-end"] == 1
    d = next(i for i in res.issues if i.check == "dangling-end")
    assert d.feature_id == "L3"


def test_line_end_at_substation_is_fine(rules_no_edge):
    from conftest import ll
    sub = {"type": "Feature", "id": "S1", "properties": {"power": "substation"},
           "geometry": {"type": "Polygon", "coordinates": [[ll(390, -20), ll(440, -20), ll(440, 20), ll(390, 20), ll(390, -20)]]}}
    gj = fc(*towers(2), line("L1", [(0, 0), (200, 0), (410, 0)], voltage="110000"), sub)
    res = run(gj, rules_no_edge)
    assert counts(res)["dangling-end"] == 0
    assert res.endpoints["at_substation"] == 1


def test_bend_without_structure(rules_no_edge):
    res = run(fc(point("a", 0, 0), point("b", 400, 0), line("L1", [(0, 0), (200, 30), (400, 0)], voltage="110000")), rules_no_edge)
    assert counts(res)["bend-no-structure"] == 1


def test_orphan_and_duplicate(rules_no_edge):
    gj = fc(*towers(3), straight(3, voltage="110000"), point("lonely", 100, 500), point("dup", 201.2, 0.5))
    c = counts(run(gj, rules_no_edge))
    assert c["duplicate-structure"] == 1
    assert c["orphan-structure"] == 2  # the duplicate record carries no line either


def test_long_and_short_spans(rules_no_edge):
    xs = [0, 200, 400, 600, 800, 1000, 2400, 2410]
    gj = fc(*[point(f"t{i}", x, 0) for i, x in enumerate(xs)], line("L1", [(x, 0) for x in xs], voltage="110000"))
    c = counts(run(gj, rules_no_edge))
    assert c["span-long"] == 1
    assert c["span-short"] == 1


def test_joint_voltage_mismatch(rules_no_edge):
    gj = fc(*towers(5), line("A", [(0, 0), (200, 0), (400, 0)], voltage="110000"), line("B", [(400, 0), (600, 0), (800, 0)], voltage="10000"))
    assert counts(run(gj, rules_no_edge))["joint-voltage"] == 1


def test_fixme_is_surfaced(rules_no_edge):
    gj = fc(*towers(2), point("t2", 400, 0, fixme="check position"), straight(3, voltage="110000"))
    assert counts(run(gj, rules_no_edge))["fixme"] == 1


def test_field_aliases(rules_no_edge):
    gj = fc(*towers(3, STRUCT_NO="A-1"), straight(3, VOLTAGE_KV="110"))
    res = run(gj, rules_no_edge)
    comp = {f["key"]: f for f in res.completeness["structures"] + res.completeness["lines"]}
    assert comp["ref"]["have"] == 3 and comp["voltage"]["have"] == 1
    assert res.line_info["L1"]["voltage_class"] == "110 kV"


def test_edge_buffer_ignores_cut_lines():
    from gridintake import load_rulepack
    r = load_rulepack("default")
    gj = fc(*towers(10), straight(10, voltage="110000"), line("cut", [(900, 300), (1800, 300)], voltage="110000"))
    res = analyse(load_dataset(gj), r)
    assert res.endpoints["edge"] >= 2
