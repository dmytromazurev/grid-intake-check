from __future__ import annotations

import sys

import anyio
import pytest

from gridintake import mcp_server as m


def test_tools_direct(vilnius_path, tmp_path):
    p = str(vilnius_path)
    assert m.check_grid_data(p)["summary"]["score"] == 45
    assert m.list_issues(p, check="dangling-end")["total"] == 13
    assert m.list_issues(p, severity="high", limit=3)["total"] == 38
    assert m.reconcile_with_survey(p, simulate=True)["synthetic_detections"] is True
    assert "map_lookup" in m.generate_formulas(p)["formulas"][0]["formula"]
    assert "Structure numbers" in m.draft_customer_request(p)
    out = tmp_path / "report.html"
    assert "Wrote" in m.export_report(p, str(out))
    assert out.read_text().startswith("<!doctype html>")


def test_missing_file():
    with pytest.raises(ValueError, match="not found"):
        m.check_grid_data("/nope/missing.geojson")


def test_stdio_server_lists_and_calls_tools(vilnius_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        with anyio.fail_after(60):
            params = StdioServerParameters(command=sys.executable, args=["-m", "gridintake.mcp_server"])
            async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                assert {"check_grid_data", "list_issues", "reconcile_with_survey", "generate_formulas",
                        "draft_customer_request", "export_report"} <= names
                out = await s.call_tool("check_grid_data", {"path": str(vilnius_path)})
                assert not out.is_error
                assert '"score": 45' in out.content[0].text or '"score":45' in out.content[0].text

    anyio.run(go)
