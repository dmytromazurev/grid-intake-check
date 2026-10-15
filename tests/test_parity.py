"""The browser demo (web/engine.js) and the Python package must agree on the same data."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap

import pytest
from conftest import ROOT

import gridintake as gi

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_js_and_python_agree(vilnius_path):
    script = textwrap.dedent(f"""
        const fs = require('fs');
        require({json.dumps(str(ROOT / 'web' / 'engine.js'))});
        const G = globalThis.GridIntake;
        const d = JSON.parse(fs.readFileSync({json.dumps(str(vilnius_path))}, 'utf8'));
        const r = G.analyse(G.fromOverpassCompact(d));
        const checks = {{}}; r.checks.forEach(c => checks[c.id] = c.count);
        console.log(JSON.stringify({{score: r.score, parts: r.parts, checks, ends: r.endpointStats}}));
    """)
    out = json.loads(subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True).stdout)
    py = gi.run(vilnius_path)
    assert out["score"] == py.score
    assert out["parts"] == py.parts
    assert out["checks"] == {c.id: c.count for c in py.checks}
    e = py.endpoints
    assert out["ends"] == {"total": e["total"], "onStructure": e["on_structure"], "atSubstation": e["at_substation"],
                           "joint": e["joint"], "dangling": e["dangling"], "edge": e["edge"]}
