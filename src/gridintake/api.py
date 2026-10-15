"""REST API. Run with ``gridintake serve`` or ``uvicorn gridintake.api:app``; docs at /docs."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse

from . import (
    IntakeError,
    __version__,
    builtin_names,
    customer_request,
    formulas,
    html_report,
    issues_csv,
    load_detections,
    load_rulepack,
    mapping_table,
    reconcile,
    run,
    simulate_detections,
)

MAX_BYTES = 50 * 1024 * 1024

app = FastAPI(
    title="Grid Intake Check API",
    version=__version__,
    description="Pre-ingest QA for utility power-grid data: readiness score, topology and attribute checks, "
                "register vs survey reconciliation, library mapping with formula snippets, and a customer data request.",
)


async def _read(upload: UploadFile) -> bytes:
    data = await upload.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File larger than {MAX_BYTES // (1024 * 1024)} MB")
    if not data:
        raise HTTPException(400, "Empty file")
    return data


async def _analyse(file: UploadFile, crs: str | None, rulepack: str):
    data = await _read(file)
    try:
        return run(data, crs=crs or None, rulepack=rulepack)
    except (IntakeError, ValueError) as e:
        raise HTTPException(422, str(e)) from e
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"Not valid JSON: {e}") from e


FileArg = Annotated[UploadFile, File(description="GeoJSON, Overpass JSON or compact demo JSON")]
CrsArg = Annotated[str | None, Form(description="Source CRS if not EPSG:4326, e.g. EPSG:3346")]
RulesArg = Annotated[str, Form(description="Built-in rule pack name")]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/v1/rulepacks")
def rulepacks() -> dict[str, Any]:
    return {"rulepacks": builtin_names()}


@app.get("/v1/rulepacks/{name}")
def rulepack(name: str) -> dict[str, Any]:
    try:
        return load_rulepack(name).to_dict()
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.post("/v1/check", response_model=None)
async def check(file: FileArg, crs: CrsArg = None, rulepack: RulesArg = "default",
                format: Annotated[str, Query(pattern="^(json|csv|html)$")] = "json",
                issue_limit: Annotated[int | None, Query(ge=0)] = None):
    """Run all intake checks. ``format=csv`` returns the issues list, ``format=html`` a standalone report."""
    res = await _analyse(file, crs, rulepack)
    if format == "csv":
        return PlainTextResponse(issues_csv(res), media_type="text/csv")
    if format == "html":
        return HTMLResponse(html_report(res, title=f"Grid intake report: {file.filename}", request_text=customer_request(res, file.filename or "the export")))
    return res.to_dict(issue_limit)


@app.post("/v1/reconcile")
async def reconcile_endpoint(file: Annotated[UploadFile, File(description="Register: GeoJSON, Overpass JSON or compact JSON")],
                             detections: Annotated[UploadFile | None, File(description="Survey detections, GeoJSON points")] = None,
                             simulate: Annotated[bool, Form(description="Use synthetic detections (demo only)")] = False,
                             tolerance_m: Annotated[float, Form(gt=0, le=50)] = 3.0,
                             crs: CrsArg = None, rulepack: RulesArg = "default") -> dict[str, Any]:
    res = await _analyse(file, crs, rulepack)
    if simulate:
        det = simulate_detections(res)
    elif detections is not None:
        try:
            det = load_detections(await _read(detections), res)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    else:
        raise HTTPException(422, "Upload detections or set simulate=true")
    return reconcile(res, det, tolerance_m=tolerance_m).to_dict()


@app.post("/v1/formulas")
async def formulas_endpoint(file: FileArg, mapping: Annotated[str | None, Form(description='JSON overrides, e.g. {"material": {"concrete": "CONC_9M"}}')] = None,
                            crs: CrsArg = None, rulepack: RulesArg = "default") -> dict[str, Any]:
    res = await _analyse(file, crs, rulepack)
    try:
        overrides = json.loads(mapping) if mapping else None
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"mapping is not valid JSON: {e}") from e
    return {"mapping": mapping_table(res, overrides), "formulas": formulas(res, overrides)}


@app.post("/v1/customer-request", response_class=PlainTextResponse)
async def customer_request_endpoint(file: FileArg, dataset_name: Annotated[str | None, Form()] = None,
                                    recipient: Annotated[str, Form()] = "[name]", sender: Annotated[str, Form()] = "[your name]",
                                    crs: CrsArg = None, rulepack: RulesArg = "default") -> str:
    res = await _analyse(file, crs, rulepack)
    return customer_request(res, dataset_name or file.filename or "your network export", recipient, sender)
