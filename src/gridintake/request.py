"""Draft the data request to the customer from the findings."""

from __future__ import annotations

from .analyse import AnalysisResult


def customer_request(res: AnalysisResult, dataset_name: str = "your network export", recipient: str = "[name]", sender: str = "[your name]") -> str:
    comp = {f["key"]: f for f in res.completeness["structures"] + res.completeness["lines"]}

    def miss(key: str) -> int:
        f = comp.get(key)
        return f["total"] - f["have"] if f else 0

    n_struct, n_lines = len(res.scope_structures), len(res.scope_lines)
    no_volt = [i for i in res.issues if i.check in {"line-voltage-missing", "line-voltage-invalid"}][:8]
    names = {ln.id: ln.tags.get("name", "") for ln in res.dataset.lines}
    examples = "; ".join((f"{names[i.feature_id]} " if names.get(i.feature_id) else "") + f"(id {i.feature_id})" for i in no_volt)
    items: list[str] = []
    if miss("ref"):
        items.append(f"- Structure numbers: missing for {miss('ref'):,} of {n_struct:,} structures. Please send the asset register with structure IDs and coordinates so we can link the model to your records and work orders.")
    if miss("line_attachment"):
        items.append(f"- Structure function (suspension / tension): missing for {miss('line_attachment'):,} structures. A list of tension (strain) structures per circuit is enough.")
    if miss("material"):
        items.append(f"- Pole and tower material/type: missing for {miss('material'):,} structures. Please share your pole and tower type codes and what each code means.")
    if miss("voltage"):
        items.append(f"- Line voltage: missing for {miss('voltage'):,} lines, e.g. {examples}.")
    if miss("cables") or miss("circuits"):
        items.append(f"- Conductor count / circuits: missing for {max(miss('cables'), miss('circuits')):,} lines, plus the conductor type per circuit if available.")
    if n := res.check("dangling-end").count:
        items.append(f"- {n} line ends stop without a structure or substation. Could you check whether structures or connections are missing in these areas? Coordinates in the attached CSV.")
    if n := res.check("span-long").count:
        items.append(f"- {n} spans are much longer than typical for their voltage, which suggests structures missing from the export. Locations are in the attached CSV.")
    if n := res.check("duplicate-structure").count:
        items.append(f"- {n} pairs of structures are less than {res.rules.duplicate_tolerance_m:g} m apart and look like duplicate records.")
    body = "\n".join(items) if items else "- Nothing blocking: all required attributes are present and topology checks passed."
    return f"""Subject: Data review for your network model: {len(items)} items to confirm

Hi {recipient},

Thank you for the data. We’ve run our intake checks on {dataset_name} ({n_struct:,} structures, {n_lines:,} line sections). Most of it is ready to use. To build an accurate model we need a few things confirmed or added:

{body}

Also useful, if available:
- The coordinate reference system and vertical datum of the GIS export and of the LiDAR.
- LiDAR capture dates per area, so we can compare against recent construction.
- Your clearance standard (required distances by voltage and object type) and design temperatures.

The attached CSV lists every item with coordinates. Happy to go through it on a call.

Best regards,
{sender}
"""
