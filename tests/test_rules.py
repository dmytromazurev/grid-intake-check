from __future__ import annotations

import pytest
from conftest import ROOT, fc, line, point

import gridintake as gi


def test_builtin_and_unknown():
    assert "default" in gi.builtin_names()
    with pytest.raises(ValueError, match="Unknown rule pack"):
        gi.load_rulepack("nope")


def test_customer_pack_aliases_and_units():
    r = gi.load_rulepack(ROOT / "examples" / "rulepack-customer.yaml")
    assert r.name == "example-utility" and r.voltage_unit == "kV"
    gj = fc(point("a", 0, 0, STRUCT_NO="P-1", MAT_CODE="B"), point("b", 300, 0, STRUCT_NO="P-2", MAT_CODE="B"),
            line("L", [(0, 0), (300, 0)], VOLTAGE_KV="10", COND_TYPE="AC-70", CIRCUIT="F12"))
    r.edge_buffer_m = 0
    res = gi.analyse(gi.load_dataset(gj, field_aliases=r.field_aliases), r)
    comp = {f["key"]: f["have"] for f in res.completeness["structures"] + res.completeness["lines"]}
    assert comp["ref"] == 2 and comp["conductor"] == 1 and comp["name"] == 1
    assert res.line_info["L"]["voltage_class"] == "10 kV"
    table = {row["field"]: row for row in gi.mapping_table(res)}
    assert table["material"]["mapping"] == {"B": "CONCRETE_POLE"}
