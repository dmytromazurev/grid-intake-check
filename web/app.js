/* Grid Intake Check — UI */
(function(){
"use strict";
const G = window.GridIntake;
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const fmtInt = n => Math.round(n).toLocaleString("en-GB");
const pct = (a, b) => b ? Math.round(100 * a / b) : 0;
const LS = "grid-intake-mapping-v1";

let res = null, det = null, rec = null, tol = 3, selCheck = null, selRec = null, selected = null, datasetLabel = "", datasetName = "";
let mapOverrides = {}; try{ mapOverrides = JSON.parse(localStorage.getItem(LS) || "{}") || {}; }catch(e){ mapOverrides = {}; }

const VCLASSES = ["330 kV","110 kV","35 kV","6–20 kV","LV","unknown"];
const VVAR = {"330 kV":"--v330","110 kV":"--v110","35 kV":"--v35","6–20 kV":"--v10","LV":"--vlv","unknown":"--vunk"};
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

/* ======================= DATA LOADING ======================= */
function showError(msg){ const e = $("#err"); if(!msg){ e.hidden = true; e.innerHTML = ""; return; } e.hidden = false; e.innerHTML = `<div class="notice">${esc(msg)}</div>`; }
function load(ds, label, name){
  const v = G.validateCoords(ds);
  if(!v.ok){ showError(v.msg); return; }
  showError(null);
  res = G.analyse(ds); det = null; rec = null; selCheck = null; selRec = null; selected = null; datasetLabel = label; datasetName = name || label;
  const km = res.lines.reduce((s, l) => s + l.length, 0) / 1000;
  $("#dsline").innerHTML = `<span>${esc(label)}</span><span>${fmtInt(res.structures.length)} structures</span><span>${fmtInt(res.lines.length)} lines · ${km.toFixed(0)} km</span><span>${fmtInt(res.substations.length)} substations</span><span>Working CRS ${esc(res.crs.code)} (${esc(res.crs.name)})</span>${res.meta.fetched ? `<span>Snapshot ${esc(res.meta.fetched.slice(0, 10))}</span>` : ""}`;
  fitView(); renderAll();
}
async function loadDemo(){
  try{
    let r = await fetch("data/vilnius-osm.json");
    if(!r.ok) r = await fetch("../data/vilnius-osm.json"); // running from the repo root
    if(!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    load(G.fromOverpassCompact(d), "Demo · OpenStreetMap power grid around Vilnius (real data)", "the OpenStreetMap power-grid extract around Vilnius");
  }catch(e){ showError("Couldn’t load the demo data (" + e.message + "). Upload a GeoJSON or Overpass JSON file instead."); $("#dsline").textContent = "No data loaded."; }
}
function parseUpload(text){
  const d = JSON.parse(text);
  if(Array.isArray(d.structures) && Array.isArray(d.lines)) return G.fromOverpassCompact(d);
  if(Array.isArray(d.elements)) return G.fromOverpass(d);
  if(d.type === "FeatureCollection" || d.type === "Feature") return G.fromGeoJSON(d);
  throw new Error("Not GeoJSON or Overpass JSON");
}
$("#btn-demo").addEventListener("click", loadDemo);
$("#file-main").addEventListener("change", e => {
  const f = e.target.files[0]; if(!f) return;
  const rd = new FileReader();
  rd.onload = () => { try{ load(parseUpload(rd.result), "Upload · " + f.name, f.name); showTab("overview"); }catch(err){ showError("Couldn’t read " + f.name + ": " + err.message + ". Expected a GeoJSON FeatureCollection in EPSG:4326 (points = structures, lines = power lines) or Overpass JSON."); } };
  rd.readAsText(f); e.target.value = "";
});

/* ======================= MAP ======================= */
const canvas = $("#map"), wrap = $("#mapwrap");
let view = {cx:0, cy:0, s:0.01}, W = 0, H = 0, DPR = 1;
function resize(){ const r = wrap.getBoundingClientRect(); DPR = window.devicePixelRatio || 1; W = r.width; H = r.height; canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR); draw(); }
new ResizeObserver(resize).observe(wrap);
function fitView(b){
  if(!res) return; b = b || res.bounds;
  const w = Math.max(50, b.maxx - b.minx), h = Math.max(50, b.maxy - b.miny);
  view.cx = (b.minx + b.maxx) / 2; view.cy = (b.miny + b.maxy) / 2;
  view.s = Math.min((W || 600) / w, (H || 500) / h) * 0.9; draw();
}
function zoomTo(x, y, s){ view.cx = x; view.cy = y; if(s) view.s = s; draw(); }
const sx = x => W / 2 + (x - view.cx) * view.s, sy = y => H / 2 - (y - view.cy) * view.s;
function draw(){
  const ctx = canvas.getContext("2d"); if(!ctx) return;
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  ctx.fillStyle = css("--surface"); ctx.fillRect(0, 0, W, H);
  if(!res){ return; }
  // grid ticks for orientation
  ctx.strokeStyle = css("--line"); ctx.lineWidth = 1;
  // substations
  ctx.fillStyle = css("--sub-fill"); ctx.strokeStyle = css("--sub-line");
  for(const s of res.substations){ ctx.beginPath(); s.ring.forEach((p, i) => i ? ctx.lineTo(sx(p.x), sy(p.y)) : ctx.moveTo(sx(p.x), sy(p.y))); ctx.closePath(); ctx.fill(); ctx.stroke(); }
  // lines
  const hiLines = new Set(), hiStructs = new Set(), rings = [];
  const issuesShown = selCheck ? res.issues.filter(i => i.check === selCheck) : [];
  issuesShown.forEach(i => { if(i.ref.startsWith("l:")) hiLines.add(i.ref.slice(2)); else hiStructs.add(i.ref.slice(2)); rings.push(i.at); });
  for(const l of res.lines){
    const sel = selected === "l:" + l.id, hi = hiLines.has(l.id);
    ctx.strokeStyle = css(VVAR[l.vclass] || "--vunk");
    ctx.lineWidth = sel ? 5 : (l.vclass === "330 kV" ? 2.6 : l.vclass === "110 kV" ? 2 : 1.4);
    ctx.globalAlpha = (selCheck && !hi && !sel) || (selRec && !sel) ? 0.35 : 1;
    ctx.setLineDash(l.vclass === "unknown" ? [5, 4] : []);
    ctx.beginPath(); l.pts.forEach((p, i) => i ? ctx.lineTo(sx(p.x), sy(p.y)) : ctx.moveTo(sx(p.x), sy(p.y))); ctx.stroke();
  }
  ctx.setLineDash([]); ctx.globalAlpha = 1;
  // structures
  const r0 = view.s > 0.15 ? 3 : view.s > 0.04 ? 2 : 1.2;
  ctx.fillStyle = css("--ink");
  if(view.s >= 0.03) for(const s of res.structures){ const X = sx(s.x), Y = sy(s.y); if(X < -5 || Y < -5 || X > W + 5 || Y > H + 5) continue;
    ctx.globalAlpha = selCheck || selRec ? 0.45 : 0.85; ctx.beginPath(); ctx.arc(X, Y, r0, 0, 7); ctx.fill(); }
  ctx.globalAlpha = 1;
  // reconciliation layer
  if(rec && selRec){
    const cat = recCats()[selRec];
    for(const it of cat.items){
      if(it.s && it.d){ ctx.strokeStyle = css("--issue"); ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(sx(it.s.x), sy(it.s.y)); ctx.lineTo(sx(it.d.x), sy(it.d.y)); ctx.stroke(); }
      const p = it.d || it.s || it; const X = sx(p.x), Y = sy(p.y);
      ctx.strokeStyle = css(cat.color); ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(X, Y, 6, 0, 7); ctx.stroke();
    }
  }
  // issue rings
  ctx.strokeStyle = css("--issue"); ctx.lineWidth = 2;
  for(const a of rings){ const X = sx(a.x), Y = sy(a.y); ctx.beginPath(); ctx.arc(X, Y, 7, 0, 7); ctx.stroke(); }
  // selected structure
  if(selected && selected.startsWith("s:")){ const s = res.byId.get(selected); if(s){ ctx.strokeStyle = css("--accent"); ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(sx(s.x), sy(s.y), 9, 0, 7); ctx.stroke(); } }
  // scale bar
  const target = 120 / view.s, pow = Math.pow(10, Math.floor(Math.log10(target))), nice = [1, 2, 5].map(m => m * pow).filter(v => v <= target).pop() || pow;
  $("#scalebar").innerHTML = `<span style="display:inline-block;width:${(nice * view.s).toFixed(0)}px;border-bottom:2px solid currentColor;margin-right:6px;vertical-align:middle"></span>${nice >= 1000 ? nice / 1000 + " km" : nice + " m"}`;
}
// interaction
let drag = null; const pointers = new Map(); let pinch = null;
canvas.addEventListener("pointerdown", e => { canvas.setPointerCapture(e.pointerId); pointers.set(e.pointerId, {x:e.offsetX, y:e.offsetY});
  if(pointers.size === 2){ const [a, b] = [...pointers.values()]; pinch = {d:Math.hypot(a.x - b.x, a.y - b.y), s:view.s}; drag = null; }
  else drag = {x:e.offsetX, y:e.offsetY, cx:view.cx, cy:view.cy, moved:false}; });
canvas.addEventListener("pointermove", e => { if(!pointers.has(e.pointerId)) return; pointers.set(e.pointerId, {x:e.offsetX, y:e.offsetY});
  if(pinch && pointers.size === 2){ const [a, b] = [...pointers.values()]; view.s = Math.max(0.0005, Math.min(50, pinch.s * Math.hypot(a.x - b.x, a.y - b.y) / pinch.d)); draw(); return; }
  if(!drag) return; const dx = e.offsetX - drag.x, dy = e.offsetY - drag.y; if(Math.abs(dx) + Math.abs(dy) > 3){ drag.moved = true; canvas.classList.add("drag"); }
  view.cx = drag.cx - dx / view.s; view.cy = drag.cy + dy / view.s; draw(); });
function endPointer(e){ pointers.delete(e.pointerId); if(pointers.size < 2) pinch = null;
  if(drag && !drag.moved && e.type === "pointerup") pick(e.offsetX, e.offsetY); drag = null; canvas.classList.remove("drag"); }
canvas.addEventListener("pointerup", endPointer); canvas.addEventListener("pointercancel", endPointer);
canvas.addEventListener("wheel", e => { e.preventDefault(); const k = Math.exp(-e.deltaY * 0.0015), wx = view.cx + (e.offsetX - W / 2) / view.s, wy = view.cy - (e.offsetY - H / 2) / view.s;
  view.s = Math.max(0.0005, Math.min(50, view.s * k)); view.cx = wx - (e.offsetX - W / 2) / view.s; view.cy = wy + (e.offsetY - H / 2) / view.s; draw(); }, {passive:false});
$("#zin").onclick = () => { view.s *= 1.6; draw(); }; $("#zout").onclick = () => { view.s /= 1.6; draw(); }; $("#zfit").onclick = () => fitView();
function pick(X, Y){
  if(!res) return;
  let best = null, bd = 9;
  if(view.s >= 0.03) for(const s of res.structures){ const d = Math.hypot(sx(s.x) - X, sy(s.y) - Y); if(d < bd){ bd = d; best = "s:" + s.id; } }
  if(!best){ bd = 7;
    for(const l of res.lines) for(let i = 1; i < l.pts.length; i++){ const a = l.pts[i - 1], b = l.pts[i];
      const ax = sx(a.x), ay = sy(a.y), bx = sx(b.x), by = sy(b.y), dx = bx - ax, dy = by - ay, L2 = dx*dx + dy*dy;
      let t = L2 ? ((X - ax) * dx + (Y - ay) * dy) / L2 : 0; t = Math.max(0, Math.min(1, t)); const d = Math.hypot(X - ax - t * dx, Y - ay - t * dy);
      if(d < bd){ bd = d; best = "l:" + l.id; } } }
  selected = best; renderInfo(); draw();
}
function renderInfo(){
  const box = $("#info");
  if(!selected || !res){ box.innerHTML = `<span class="muted">Click a line or structure on the map to inspect it. Drag to pan, scroll or pinch to zoom.</span>`; return; }
  const f = res.byId.get(selected); if(!f){ box.textContent = ""; return; }
  const isL = selected.startsWith("l:");
  const iss = res.issues.filter(i => i.ref === selected);
  const tags = Object.entries(f.tags || {});
  box.innerHTML = `<div class="row between"><strong>${isL ? "Line" : "Structure"} ${esc(f.id)}</strong><span class="chip">${esc(isL ? f.vclass + " · " + (f.length / 1000).toFixed(2) + " km" : f.power)}</span></div>
    ${iss.length ? `<ul class="plain" style="margin-top:6px">${iss.map(i => `<li><span class="sev ${i.sev}" style="display:inline-block;margin-right:6px"></span>${esc(i.detail)}</li>`).join("")}</ul>` : `<p class="muted" style="margin-top:4px">No issues on this feature.</p>`}
    <dl>${tags.length ? tags.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("") : `<dt>tags</dt><dd class="muted">none</dd>`}
    ${!isL ? `<dt>lat, lon</dt><dd>${f.lat.toFixed(6)}, ${f.lon.toFixed(6)}</dd><dt>${esc(res.crs.code)}</dt><dd>${f.x.toFixed(1)}, ${f.y.toFixed(1)}</dd>` : ""}</dl>
    ${isL ? `<p style="margin-top:6px"><a href="https://www.openstreetmap.org/way/${encodeURIComponent(f.id)}" target="_blank" rel="noopener">Open in OpenStreetMap</a></p>` : `<p style="margin-top:6px"><a href="https://www.openstreetmap.org/node/${encodeURIComponent(f.id)}" target="_blank" rel="noopener">Open in OpenStreetMap</a></p>`}`;
}
function renderLegend(){
  $("#legend").innerHTML = VCLASSES.map(k => `<span><i style="background:var(${VVAR[k]})${k === "unknown" ? ";background:repeating-linear-gradient(90deg,var(--vunk) 0 5px,transparent 5px 9px)" : ""}"></i>${k === "unknown" ? "voltage unknown" : k}</span>`).join("") +
    `<span><i style="background:var(--sub-line);height:9px"></i>substation</span><span><b></b>issue</span>`;
}

/* ======================= TABS ======================= */
const TABS = ["overview","issues","reconcile","mapping","request","about"];
const RENDER = {overview:() => renderOverview(), issues:() => renderIssues(), reconcile:() => renderReconcile(), mapping:() => renderMapping(), request:() => renderRequest(), about:() => renderAbout()};
function showTab(t){ TABS.forEach(x => { $("#panel-" + x).hidden = x !== t; $("#tab-" + x).setAttribute("aria-selected", x === t ? "true" : "false"); }); if(t === "issues" && selRec){ selRec = null; draw(); } if(t === "reconcile" && selCheck && rec){ selCheck = null; draw(); } if(res && t !== "request" && t !== "mapping") RENDER[t](); }
document.querySelector("nav.tabs").addEventListener("click", e => { const b = e.target.closest("[data-tab]"); if(b) showTab(b.dataset.tab); });
function renderAll(){ renderOverview(); renderIssues(); renderReconcile(); renderMapping(); renderRequest(); renderAbout(); renderInfo(); renderLegend(); draw(); }

/* ======================= OVERVIEW ======================= */
function gauge(score){
  const r = 46, c = 2 * Math.PI * r, col = score >= 75 ? "--ok" : score >= 50 ? "--warn" : "--issue";
  return `<svg class="gauge" viewBox="0 0 112 112" role="img" aria-label="Readiness score ${score} of 100"><circle cx="56" cy="56" r="${r}" fill="none" stroke="var(--sunk)" stroke-width="10"/>
    <circle cx="56" cy="56" r="${r}" fill="none" stroke="var(${col})" stroke-width="10" stroke-linecap="round" stroke-dasharray="${(c * score / 100).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 56 56)"/>
    <text x="56" y="60" text-anchor="middle" font-family="Archivo Narrow, sans-serif" font-weight="700" font-size="30" fill="var(--ink)">${score}</text>
    <text x="56" y="78" text-anchor="middle" font-family="JetBrains Mono, monospace" font-size="9" fill="var(--muted)">/ 100</text></svg>`;
}
const barCls = v => v >= 75 ? "hi" : v >= 50 ? "mid" : "lo";
function headline(){
  const c = id => res.checks.find(x => x.id === id).count, S = res.completeness.structures, Lc = res.completeness.lines;
  const ref = S.find(f => f.key === "ref"), att = S.find(f => f.key === "line_attachment"), vol = Lc.find(f => f.key === "voltage");
  const out = [];
  if(ref.have < ref.total) out.push(`${fmtInt(ref.total - ref.have)} of ${fmtInt(ref.total)} structures (${100 - pct(ref.have, ref.total)}%) have no structure number, so the model can’t be matched to the asset register or work orders yet.`);
  if(att.have < att.total) out.push(`Suspension vs tension is known for only ${pct(att.have, att.total)}% of structures; tension sections would have to be inferred from geometry.`);
  if(vol.have < vol.total) out.push(`${fmtInt(vol.total - vol.have)} lines have no voltage, so clearance rules can’t be assigned to them.`);
  if(c("dangling-end")) out.push(`${c("dangling-end")} line ends stop in the open (not at a structure, substation or another line).`);
  if(c("span-long")) out.push(`${c("span-long")} spans are far longer than their voltage class allows for, which usually means missing structures.`);
  return out;
}
function renderOverview(){
  if(!res){ $("#panel-overview").innerHTML = ""; return; }
  const e = res.endpointStats, km = {}; res.lines.forEach(l => km[l.vclass] = (km[l.vclass] || 0) + l.length / 1000);
  const types = {}; res.structures.forEach(s => types[s.power] = (types[s.power] || 0) + 1);
  const comp = (list) => `<div class="tablewrap"><table><thead><tr><th>Attribute</th><th>Filled</th><th>Why it matters for the twin</th></tr></thead><tbody>${list.map(f => { const p = pct(f.have, f.total);
    return `<tr><td>${esc(f.label)}<div class="muted" style="font-family:var(--f-mono);font-size:11.5px">${esc(f.key)}</div></td><td><div class="cbar"><div class="bar"><i class="${barCls(p)}" style="width:${Math.max(p, 1)}%"></i></div><span class="num">${p}%</span></div><div class="muted num" style="font-size:12px">${fmtInt(f.have)} / ${fmtInt(f.total)}</div></td><td class="why">${esc(f.why)}</td></tr>`; }).join("")}</tbody></table></div>`;
  $("#panel-overview").innerHTML = `
    <div class="card"><div class="scorebox">${gauge(res.score)}<div class="parts">
      <h2>Readiness for model build</h2>
      ${[["Attributes", res.parts.attributes], ["Topology", res.parts.topology], ["Geometry", res.parts.geometry]].map(([k, v]) => `<div class="part"><span>${k}</span><div class="bar"><i class="${barCls(v)}" style="width:${Math.max(v, 1)}%"></i></div><span class="num">${v}</span></div>`).join("")}
      <p class="muted" style="font-size:12.5px">Weighted 50 / 30 / 20. Attributes = structure number, suspension/tension, material and line voltage filled. Topology and geometry fall with issues per feature.</p></div></div></div>
    <div class="card"><h2>Headline findings</h2><ol class="plain">${headline().map(h => `<li>${esc(h)}</li>`).join("")}</ol>
      <div class="row"><button class="btn sm" data-goto="issues">See all issues</button><button class="btn sm" data-goto="request">Draft the customer data request</button></div></div>
    <div class="card"><h2>What’s in the file</h2><div class="stats">
      ${Object.entries(types).map(([k, v]) => `<div class="stat"><b>${fmtInt(v)}</b><span>${esc(k)}s</span></div>`).join("")}
      <div class="stat"><b>${fmtInt(res.lines.length)}</b><span>line ways</span></div>
      ${VCLASSES.filter(k => km[k]).map(k => `<div class="stat"><b>${km[k].toFixed(0)} km</b><span>${esc(k)}</span></div>`).join("")}
      <div class="stat"><b>${fmtInt(res.substations.length)}</b><span>substations</span></div></div></div>
    <div class="card"><h2>Structure attributes</h2>${comp(res.completeness.structures)}</div>
    <div class="card"><h2>Line attributes</h2>${comp(res.completeness.lines)}</div>
    <div class="card"><h2>Where line ends land</h2>
      <div class="stats"><div class="stat"><b>${e.onStructure}</b><span>on a structure</span></div><div class="stat"><b>${e.atSubstation}</b><span>at a substation (≤ ${res.opts.subTol} m)</span></div><div class="stat"><b>${e.joint}</b><span>join another line</span></div><div class="stat"><b style="color:var(--issue)">${e.dangling}</b><span>dangling</span></div><div class="stat"><b>${e.edge}</b><span>at the data edge (ignored)</span></div></div>
      <p class="muted" style="font-size:13px">Ends within ${res.opts.edgeBuffer} m of the data boundary are ignored: lines cut by the extract would otherwise look broken. Same rule as clipping a GIS ↔ LiDAR comparison to the survey footprint.</p></div>
    <div class="card"><h2>Spans by voltage class</h2><p class="muted" style="font-size:13px">A span is the conductor between two consecutive structures along a line.</p>
      <div class="tablewrap"><table><thead><tr><th>Class</th><th class="r">Spans</th><th class="r">Median</th><th class="r">P95</th><th class="r">Max</th></tr></thead><tbody>
      ${VCLASSES.filter(k => res.spanStats[k]).map(k => { const s = res.spanStats[k]; return `<tr><td>${esc(k)}</td><td class="r num">${fmtInt(s.n)}</td><td class="r num">${fmtInt(s.median)} m</td><td class="r num">${fmtInt(s.p95)} m</td><td class="r num">${fmtInt(s.max)} m</td></tr>`; }).join("")}</tbody></table></div></div>`;
}

/* ======================= ISSUES ======================= */
const CHECK_HELP = {
  "line-voltage-missing":"Without voltage the line gets no clearance rule and no standard. Ask the utility, or infer from connected substations and structure type and mark as assumed.",
  "line-voltage-invalid":"Normalise units (V vs kV) and separators at ingest; never guess silently.",
  "line-voltage-multi":"Shared-structure lines carry several circuits. Model them as separate circuits on the same structures.",
  "cables-circuits":"For 3-phase AC, cables = 3 × circuits. A mismatch points to a wrong attribute or an earth wire counted as a cable.",
  "joint-voltage":"Two line pieces meeting end to end with different voltages usually means one of them is wrong.",
  "dangling-end":"A conductor can’t end in the air. Either a structure or substation is missing from the file, or the line is digitised short.",
  "bend-no-structure":"In a utility export a line bends only at a structure. Bends without one are missing poles or digitising noise; both change span lengths and sag.",
  "orphan-structure":"A structure carrying no line: decommissioned, a stub, or a line missing from the export.",
  "duplicate-structure":"Two records for one physical structure inflate counts and break GIS ↔ LiDAR matching (two candidates for one detection).",
  "span-long":"Compared with the median span of the same voltage class. Very long spans usually skip structures that exist in the field.",
  "span-short":"Very short spans are often duplicates or gantries inside substations.",
  "fixme":"Notes left by whoever produced the data. Read them before trusting the area."
};
function issuesCSV(){
  const rows = [["check","severity","feature","id","lat","lon","detail"]].concat(res.issues.map(i => [i.check, i.sev, i.ref.startsWith("l:") ? "line" : "structure", i.ref.slice(2), i.at.lat.toFixed(7), i.at.lon.toFixed(7), i.detail]));
  return rows.map(r => r.map(v => /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v).join(",")).join("\n");
}
function renderIssues(){
  if(!res){ $("#panel-issues").innerHTML = ""; return; }
  const groups = [...new Set(res.checks.map(c => c.group))];
  const list = selCheck ? res.issues.filter(i => i.check === selCheck) : [];
  const ck = selCheck ? res.checks.find(c => c.id === selCheck) : null;
  $("#panel-issues").innerHTML = `
    <div class="card"><div class="row between"><h2>${fmtInt(res.issues.length)} issues in ${res.checks.filter(c => c.count).length} checks</h2><button class="btn sm" id="copycsv">Copy all as CSV</button></div>
      <p class="muted" style="font-size:13px">Select a check to ring its issues on the map. Tolerances: snap ${res.opts.snapTol} m, duplicate ${res.opts.dupTol} m, substation ${res.opts.subTol} m, long span > ${res.opts.spanFactor}× class median.</p>
      <textarea id="csvbox" hidden aria-label="Issues CSV" style="min-height:140px"></textarea></div>
    ${groups.map(g => `<div class="group"><span class="eyebrow">${esc(g)}</span>${res.checks.filter(c => c.group === g).map(c => `<button class="check${selCheck === c.id ? " sel" : ""}" data-check="${c.id}"><span class="sev ${c.sev}"></span><span>${esc(c.title)}</span><span class="chip ${c.sev}">${c.count ? fmtInt(c.count) : "pass"}</span></button>`).join("")}</div>`).join("")}
    ${ck ? `<div class="card"><div class="row between"><h3>${esc(ck.title)}</h3><button class="link" data-clear>Clear selection</button></div><p class="callout" style="font-size:13.5px">${esc(CHECK_HELP[ck.id] || "")}</p>
      ${list.length ? list.slice(0, 200).map(i => `<div class="issue"><div><div>${esc(i.detail)}</div><div class="id">${i.ref.startsWith("l:") ? "line" : "structure"} ${esc(i.ref.slice(2))} · ${i.at.lat.toFixed(5)}, ${i.at.lon.toFixed(5)}</div></div><button class="btn sm" data-show="${esc(i.ref)}" data-x="${i.at.x}" data-y="${i.at.y}">Show</button></div>`).join("") + (list.length > 200 ? `<p class="muted">Showing 200 of ${list.length}. Copy the CSV for the full list.</p>` : "") : `<p class="muted">No issues for this check.</p>`}</div>` : ""}`;
}
$("#panel-issues").addEventListener("click", e => {
  const b = e.target.closest("button"); if(!b) return;
  if(b.dataset.check){ selCheck = selCheck === b.dataset.check ? null : b.dataset.check; selRec = null; renderIssues(); draw(); const first = res.issues.find(i => i.check === selCheck); if(first && window.innerWidth < 980) wrap.scrollIntoView({behavior:"smooth"}); }
  else if(b.hasAttribute("data-clear")){ selCheck = null; renderIssues(); draw(); }
  else if(b.dataset.show){ selected = b.dataset.show; zoomTo(+b.dataset.x, +b.dataset.y, Math.max(view.s, 0.25)); renderInfo(); if(window.innerWidth < 980) wrap.scrollIntoView({behavior:"smooth"}); }
  else if(b.id === "copycsv"){ const csv = issuesCSV(); const box = $("#csvbox");
    const fallback = () => { box.hidden = false; box.value = csv; box.select(); b.textContent = "Selected below: press Ctrl/Cmd+C"; };
    try{ navigator.clipboard.writeText(csv).then(() => { b.textContent = "Copied " + res.issues.length + " rows"; setTimeout(() => b.textContent = "Copy all as CSV", 1800); }, fallback); }catch(err){ fallback(); } }
});

/* ======================= RECONCILE ======================= */
function recCats(){
  if(!rec) return {};
  return {
    matched:{label:"Matched one-to-one", n:rec.pairs.length, color:"--ok", items:rec.pairs.map(p => ({s:p.s, d:p.d})), note:`Median offset ${rec.stats.median.toFixed(2)} m, P95 ${rec.stats.p95.toFixed(2)} m.`},
    offsets:{label:"Register position off", n:rec.offsets.length, color:"--warn", items:rec.offsets.map(o => ({s:o.s, d:o.d})), note:"A detection exists 3–9 m away: the record is mispositioned, not missing."},
    missing:{label:"Not found in survey", n:rec.trulyMissing.length, color:"--issue", items:rec.trulyMissing.map(s => ({s})), note:"No detection nearby: removed, outside coverage, occluded, or a missed detection."},
    unrecorded:{label:"Not in the register", n:rec.unrecorded.length, color:"--issue", items:rec.unrecorded.map(d => ({d})), note:"Detected structures with no record: new construction or a gap in the GIS."},
    nonpower:{label:"Non-power poles", n:rec.nonPower.length, color:"--muted", items:rec.nonPower.map(d => ({d})), note:"Street lights and signs (Neara’s pole_np class): exclude, don’t raise as gaps."}
  };
}
function offsetInsight(){
  if(!rec || !rec.offsets.length) return "";
  const byLine = {}; for(const o of rec.offsets){ const l = res.lines.find(l => l.pts.some(p => Math.hypot(p.x - o.s.x, p.y - o.s.y) < 1)); if(l) byLine[l.id] = (byLine[l.id] || 0) + 1; }
  const top = Object.entries(byLine).sort((a, b) => b[1] - a[1])[0];
  if(!top || top[1] < 5) return "";
  const l = res.lines.find(x => x.id === top[0]);
  const dx = rec.offsets.map(o => o.d.x - o.s.x), dy = rec.offsets.map(o => o.d.y - o.s.y);
  const mx = dx.reduce((a, b) => a + b, 0) / dx.length, my = dy.reduce((a, b) => a + b, 0) / dy.length;
  return `<p class="callout">${top[1]} of the ${rec.offsets.length} mispositioned records sit on one line (${esc(l.tags.name || "line " + l.id)}), all shifted the same way (≈ ${mx.toFixed(1)} m E, ${my.toFixed(1)} m N). That’s one systematic error, e.g. an old digitising source, not ${top[1]} separate problems: fix the source transform once and re-run.</p>`;
}
function renderReconcile(){
  if(!res){ $("#panel-reconcile").innerHTML = ""; return; }
  const cats = recCats();
  $("#panel-reconcile").innerHTML = `
    <div class="card"><h2>Register vs survey reconciliation</h2>
      <p>Matches the structures in the customer’s register (this file) to structures detected in LiDAR, one-to-one within a tolerance, in both directions. Leftovers are split into “mispositioned”, “missing” and “unrecorded” so each goes to the right fix.</p>
      <div class="row"><button class="btn primary" id="simdet">Generate simulated detections</button><label class="btn" for="file-det">Upload detections (GeoJSON points)</label><input type="file" id="file-det" accept=".json,.geojson" hidden></div>
      ${det && det.synthetic ? `<p class="synthetic"><strong>Simulated data.</strong> Detections are generated from this file with 0.5 m noise, ~3.5% structures dropped, one 110 kV line shifted ≈ 5 m (a digitising offset), 12 unrecorded structures on long spans and street-light false positives. It demonstrates the method; it is not a real survey.</p>` : ""}
      ${det && !det.synthetic ? `<p class="muted">${fmtInt(det.points.length)} detections uploaded.</p>` : ""}
      <div class="row"><label for="tol" class="muted" style="font-size:13.5px">Match tolerance</label><input type="range" id="tol" min="1" max="6" step="0.5" value="${tol}"><span class="num">${tol} m</span></div></div>
    ${rec ? `<div class="card"><div class="rec">${Object.entries(cats).map(([k, c]) => `<button class="${selRec === k ? "sel" : ""}" data-rec="${k}"><b style="color:var(${c.color})">${fmtInt(c.n)}</b><span>${esc(c.label)}</span></button>`).join("")}</div>
      ${selRec ? `<p class="muted" style="font-size:13.5px">${esc(cats[selRec].note)}</p>` : `<p class="muted" style="font-size:13.5px">Select a group to show it on the map.</p>`}
      ${offsetInsight()}</div>
    <div class="card"><h3>Method</h3><ol class="plain">
      <li>Project both layers into one metric CRS (${esc(res.crs.code)}).</li>
      <li>Candidate pairs within ${tol} m, sorted by distance; greedy one-to-one, so two records can’t claim one detection.</li>
      <li>Leftover records with a detection within ${tol * 3} m → mispositioned; otherwise → not found.</li>
      <li>Leftover detections → unrecorded, except non-power poles (street lights, signs).</li></ol>
      <div class="codehead eyebrow">Same check in PostGIS</div>
<pre><code>WITH cand AS (
  SELECT g.id AS reg_id, d.id AS det_id, ST_Distance(g.geom, d.geom) AS dist
  FROM register g JOIN detections d ON ST_DWithin(g.geom, d.geom, ${tol})
), ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY reg_id ORDER BY dist) AS r1,
            ROW_NUMBER() OVER (PARTITION BY det_id ORDER BY dist) AS r2
  FROM cand
)
SELECT reg_id, det_id, dist FROM ranked WHERE r1 = 1 AND r2 = 1;</code></pre>
      <p class="muted" style="font-size:13px">The SQL keeps mutual nearest pairs; the app’s greedy pass is slightly more complete (it re-pairs the losers). Both should be stated when presenting.</p></div>` : ""}`;
}
function runReconcile(){ rec = G.reconcile(res, det, tol); selRec = selRec || "offsets"; selCheck = null; renderReconcile(); draw(); }
$("#panel-reconcile").addEventListener("click", e => {
  const b = e.target.closest("button"); if(!b) return;
  if(b.id === "simdet"){ det = G.simulateDetections(res, 7); runReconcile(); }
  else if(b.dataset.rec){ selRec = selRec === b.dataset.rec ? null : b.dataset.rec; renderReconcile(); draw(); if(selRec && window.innerWidth < 980) wrap.scrollIntoView({behavior:"smooth"}); }
});
$("#panel-reconcile").addEventListener("input", e => { if(e.target.id === "tol"){ tol = +e.target.value; if(det) runReconcile(); else renderReconcile(); } });
$("#panel-reconcile").addEventListener("change", e => {
  if(e.target.id !== "file-det") return; const f = e.target.files[0]; if(!f) return;
  const rd = new FileReader(); rd.onload = () => { try{
    const gj = JSON.parse(rd.result), pts = [];
    (gj.features || []).forEach((ft, i) => { if(ft.geometry && ft.geometry.type === "Point"){ const [lon, lat] = ft.geometry.coordinates; const [x, y] = G.tmForward(lat, lon, res.crs); pts.push({id:String(ft.id ?? "D" + (i + 1)), x, y, cls:(ft.properties && (ft.properties.class || ft.properties.cls)) || "structure"}); } });
    if(!pts.length) throw new Error("no Point features");
    det = {points:pts, synthetic:false}; runReconcile();
  }catch(err){ showError("Couldn’t read detections: " + err.message); } }; rd.readAsText(f);
});

/* ======================= MAPPING & FORMULAS ======================= */
const DEFAULT_MAP = {
  "material":{"concrete":"CONCRETE_POLE","metal":"STEEL_LATTICE","steel":"STEEL_LATTICE","wood":"WOOD_POLE","composite":"COMPOSITE_POLE"},
  "line_attachment":{"suspension":"SUSPENSION","anchor":"TENSION","pin":"SUSPENSION","pulley":"SUSPENSION"},
  "design":{"triangle":"TRIANGLE_SC","portal":"PORTAL","three-level":"THREE_LEVEL_DC","donau":"DONAU_DC","barrel":"BARREL","one-level":"ONE_LEVEL"},
  "power":{"tower":"TOWER","pole":"POLE","portal":"GANTRY","terminal":"TERMINAL"}
};
function valueTable(field){
  const counts = {}; let missing = 0;
  res.structures.forEach(s => { const v = s.tags[field] != null ? s.tags[field] : s[field]; if(v == null || v === "") missing++; else counts[v] = (counts[v] || 0) + 1; });
  return {field, values:Object.entries(counts).sort((a, b) => b[1] - a[1]), missing};
}
const target = (field, v) => (mapOverrides[field] && mapOverrides[field][v] != null) ? mapOverrides[field][v] : ((DEFAULT_MAP[field] || {})[v] || "");
function mapFormula(field){
  const vt = valueTable(field), pairs = vt.values.filter(([v]) => target(field, v)).map(([v]) => `"${v}", "${target(field, v)}"`);
  if(!pairs.length) return `// no mapped values for ${field} yet`;
  return `map_lookup(\n  map(${pairs.join(",\n      ")}),\n  get_prop(gis_properties, "${field}", "text"),\n  "UNMAPPED"\n)`;
}
function renderMapping(){
  if(!res){ $("#panel-mapping").innerHTML = ""; return; }
  const fields = ["power","material","line_attachment","design"];
  const volt = {}; res.lines.forEach(l => { const k = l.tags.voltage || "(missing)"; volt[k] = (volt[k] || 0) + 1; });
  $("#panel-mapping").innerHTML = `
    <div class="card"><h2>Source values → model library types</h2>
      <p>Every utility codes assets differently. Map each source value to a library type once, keep the mapping with the project, and count what’s left unmapped before building the model. Edit the targets; the formulas below update.</p>
      <p class="muted" style="font-size:13px">Target names are placeholders for the customer’s pole, tower and assembly library entries.</p></div>
    ${fields.map(f => { const vt = valueTable(f), total = res.structures.length;
      return `<div class="card"><div class="row between"><h3><code>${f}</code></h3><span class="chip ${vt.missing ? "high" : "pass"}">${fmtInt(vt.missing)} missing (${pct(vt.missing, total)}%)</span></div>
      <div class="tablewrap"><table><thead><tr><th>Source value</th><th class="r">Count</th><th>Library type</th></tr></thead><tbody>
      ${vt.values.map(([v, n]) => `<tr><td><code>${esc(v)}</code></td><td class="r num">${fmtInt(n)}</td><td><input type="text" id="map-${esc(f)}-${String(v).replace(/[^a-z0-9]/gi, "_")}" data-mf="${esc(f)}" data-mv="${esc(v)}" value="${esc(target(f, v))}" placeholder="UNMAPPED" aria-label="Library type for ${esc(f)} ${esc(v)}"></td></tr>`).join("") || `<tr><td colspan="3" class="muted">No values present.</td></tr>`}
      </tbody></table></div></div>`; }).join("")}
    <div class="card"><h3>Line voltages as delivered</h3><div class="tablewrap"><table><thead><tr><th>voltage tag</th><th class="r">Lines</th></tr></thead><tbody>${Object.entries(volt).sort((a, b) => b[1] - a[1]).map(([k, n]) => `<tr><td><code>${esc(k)}</code></td><td class="r num">${n}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="card"><h2>Generated report formulas</h2>
      <p>Written with functions from Neara’s public Formula language reference (<code>map_lookup</code>, <code>get_prop</code>, <code>try</code>, <code>if</code>, <code>find_unattached_poles</code>, units). Field names such as <code>gis_properties</code> follow the reference’s examples; check them against the real schema.</p>
      <div><div class="eyebrow">u_material_type · material → library type</div><pre><code id="f-material">${esc(mapFormula("material"))}</code></pre></div>
      <div><div class="eyebrow">u_structure_role · suspension or tension</div><pre><code id="f-att">${esc(mapFormula("line_attachment"))}</code></pre></div>
      <div><div class="eyebrow">u_qa_structure_number · flag missing structure numbers</div><pre><code>if(try(get_prop(gis_properties, "ref", "text"), "") = "", "NO STRUCTURE NUMBER", "OK")</code></pre></div>
      <div><div class="eyebrow">u_qa_unattached · Spans report: loose poles next to a span</div><pre><code>if(len(find_unattached_poles(self, 5m)) > 0, "CHECK: unattached pole within 5 m", "OK")</code></pre></div>
      <div><div class="eyebrow">u_required_ground_clearance · example thresholds by voltage, not a standard</div><pre><code>let(
  v: get_prop(gis_properties, "voltage", "real"),
  if(v >= 300000, 8.0m, v >= 100000, 7.0m, v >= 30000, 6.5m, 6.0m)
)</code></pre></div>
      <p class="muted" style="font-size:13px">In a real deployment the clearance values come from the customer’s standard via the Clearance Rules table; the formula shows the pattern, not the numbers.</p></div>`;
}
$("#panel-mapping").addEventListener("input", e => {
  const el = e.target; if(!el.dataset.mf) return;
  (mapOverrides[el.dataset.mf] = mapOverrides[el.dataset.mf] || {})[el.dataset.mv] = el.value.trim();
  try{ localStorage.setItem(LS, JSON.stringify(mapOverrides)); }catch(err){}
  const fm = $("#f-material"), fa = $("#f-att"); if(fm) fm.textContent = mapFormula("material"); if(fa) fa.textContent = mapFormula("line_attachment");
});

/* ======================= CUSTOMER REQUEST ======================= */
function requestText(){
  const S = res.completeness.structures, Lc = res.completeness.lines, c = id => res.checks.find(x => x.id === id).count;
  const miss = (list, key) => { const f = list.find(x => x.key === key); return f.total - f.have; };
  const lines = [];
  const add = (cond, s) => { if(cond) lines.push(s); };
  const noVolt = res.lines.filter(l => !l.v.ok).slice(0, 8).map(l => (l.tags.name ? l.tags.name + " " : "") + "(id " + l.id + ")");
  add(miss(S, "ref"), `- Structure numbers: missing for ${fmtInt(miss(S, "ref"))} of ${fmtInt(S[0].total)} structures. Please send the asset register with structure IDs and coordinates so we can link the model to your records and work orders.`);
  add(miss(S, "line_attachment"), `- Structure function (suspension / tension): missing for ${fmtInt(miss(S, "line_attachment"))} structures. A list of tension (strain) structures per circuit is enough.`);
  add(miss(S, "material"), `- Pole and tower material/type: missing for ${fmtInt(miss(S, "material"))} structures. Please share your pole and tower type codes and what each code means.`);
  add(miss(Lc, "voltage"), `- Line voltage: missing for ${fmtInt(miss(Lc, "voltage"))} lines, e.g. ${noVolt.join("; ")}.`);
  add(miss(Lc, "cables") || miss(Lc, "circuits"), `- Conductor count / circuits: missing for ${fmtInt(Math.max(miss(Lc, "cables"), miss(Lc, "circuits")))} lines, plus the conductor type per circuit if available.`);
  add(c("dangling-end"), `- ${c("dangling-end")} line ends stop without a structure or substation. Could you check whether structures or connections are missing in these areas? Coordinates in the attached CSV.`);
  add(c("span-long"), `- ${c("span-long")} spans are much longer than typical for their voltage, which suggests structures missing from the export. Locations are in the attached CSV.`);
  add(c("duplicate-structure"), `- ${c("duplicate-structure")} pairs of structures are less than ${res.opts.dupTol} m apart and look like duplicate records.`);
  return `Subject: Data review for your network model: ${lines.length} items to confirm

Hi [name],

Thank you for the data. We’ve run our intake checks on ${datasetName} (${fmtInt(res.structures.length)} structures, ${fmtInt(res.lines.length)} line sections). Most of it is ready to use. To build an accurate model we need a few things confirmed or added:

${lines.join("\n")}

Also useful, if available:
- The coordinate reference system and vertical datum of the GIS export and of the LiDAR.
- LiDAR capture dates per area, so we can compare against recent construction.
- Your clearance standard (required distances by voltage and object type) and design temperatures.

The attached CSV lists every item with coordinates. Happy to go through it on a call.

Best regards,
[your name]`;
}
function renderRequest(){
  if(!res){ $("#panel-request").innerHTML = ""; return; }
  $("#panel-request").innerHTML = `<div class="card"><div class="row between"><h2>Data request to the utility</h2><button class="btn sm" id="copyreq">Copy text</button></div>
    <p>Generated from the findings. Sending one complete, specific request in week one replaces weeks of back-and-forth. Edit before sending; the CSV from the Issues tab goes with it.</p>
    <textarea id="reqtext" aria-label="Customer data request">${esc(requestText())}</textarea></div>`;
}
$("#panel-request").addEventListener("click", e => { const b = e.target.closest("#copyreq"); if(!b) return; const t = $("#reqtext");
  try{ navigator.clipboard.writeText(t.value).then(() => { b.textContent = "Copied"; setTimeout(() => b.textContent = "Copy text", 1500); }, () => { t.select(); b.textContent = "Selected: Ctrl/Cmd+C"; }); }catch(err){ t.select(); } });

/* ======================= ABOUT ======================= */
function renderAbout(){
  const S = res ? res : null;
  $("#panel-about").innerHTML = `
    <div class="card"><h2>The problem</h2>
      <p>Building a digital twin starts with the customer’s data: a GIS export, an asset register, LiDAR. Data gaps (no structure numbers, missing voltages, lines that stop in the air, structures in the wrong place) usually surface one by one during model build, each one a new question to the utility and a few days of waiting.</p>
      <p>This prototype runs the checks in the first hour instead: it scores how ready a delivery is, shows every issue on a map, reconciles the register with survey detections, drafts the mapping to library types and writes the data request to the customer.</p></div>
    <div class="card"><h2>What’s real here</h2><ul class="plain">
      <li><strong>Data:</strong> ${S ? fmtInt(S.structures.length) + " structures and " + fmtInt(S.lines.length) + " line sections" : "the power grid"} around Vilnius from OpenStreetMap (snapshot ${S && S.meta.fetched ? esc(S.meta.fetched.slice(0, 10)) : "October 2026"}). OSM stands in for a utility GIS export; the issues found in it are real.</li>
      <li><strong>Projection:</strong> WGS 84 → LKS-94 / Lithuania TM (EPSG:3346), computed in the browser; UTM is picked automatically elsewhere.</li>
      <li><strong>Checks:</strong> attribute completeness, voltage validity, cables vs circuits, dangling ends with substation awareness, bends without structures, orphans, duplicates, span outliers per voltage class, joint voltage mismatches. All run in the browser in well under a second.</li>
      <li><strong>Simulated:</strong> the LiDAR detections on the GIS ↔ LiDAR tab are synthetic, clearly labelled, and only there to demonstrate the matching method. Upload real detections as GeoJSON points to use it for real.</li></ul></div>
    <div class="card"><h2>How it would fit a deployment workflow</h2><div class="tablewrap"><table><thead><tr><th>Step</th><th>Today (typical)</th><th>With an intake check</th></tr></thead><tbody>
      <tr><td>Data arrives</td><td>Load into the platform, discover problems while modelling</td><td>Score and issue list in minutes, before any modelling</td></tr>
      <tr><td>Customer questions</td><td>Asked one at a time as they appear</td><td>One complete request with coordinates in week one</td></tr>
      <tr><td>Code mapping</td><td>Rebuilt per project in formulas or spreadsheets</td><td>Mapping table kept per customer, formulas generated</td></tr>
      <tr><td>GIS ↔ LiDAR</td><td>Mismatches fixed record by record</td><td>Grouped by cause: offset, missing, unrecorded, non-power</td></tr>
      <tr><td>Next delivery</td><td>Same checks repeated by hand</td><td>Same checks re-run, diff against last time</td></tr></tbody></table></div>
      <p class="muted" style="font-size:13px">“Today” describes a typical deployment, not Neara’s internal process, which I don’t know. That’s a question for the interview.</p></div>
    <div class="card"><h2>Next steps if it were real</h2><ol class="plain">
      <li>Run as a pipeline step on upload, next to LiDAR classification, with results stored as a dataset.</li>
      <li>Per-customer rule packs: tolerances, voltage classes, required attributes, clearance standard.</li>
      <li>Diff between deliveries: what changed since the last export, what the customer fixed.</li>
      <li>Move heavy checks to PostGIS or DuckDB for networks with millions of structures; keep this UI.</li>
      <li>Export issues as a report layer so they can be reviewed in the 3D model.</li></ol></div>
    <div class="card"><h2>Other improvement ideas</h2><ul class="plain">
      <li><strong>Formula linting in the editor:</strong> warn when a length is compared with a bare number, when <code>round</code> gets a unit, when a parameter field lacks <code>model().</code>, or when <code>rate_span</code> gets a non-monotonic pass field. All four are documented pitfalls.</li>
      <li><strong>Customer-facing data portal:</strong> utilities upload exports and see the same readiness score themselves, so data arrives better.</li>
      <li><strong>Deployment templates:</strong> library mappings, environments and QA reports saved as a reusable starter per region (AS/NZS 7000, NESC, EN 50341).</li></ul></div>
    <div class="card"><h2>Two-minute talk track</h2><ol class="plain">
      <li>“Your posting says deployment engineers ingest LiDAR, GIS and asset data and do QA to engineering-grade accuracy. I wanted to see what that feels like, so I took the real grid around Vilnius from OpenStreetMap as a stand-in for a utility export.”</li>
      <li>“In under a second it found that no structure has a number, suspension/tension is known for 6%, 25 lines have no voltage, 13 line ends stop in the open and some spans run for kilometres without a structure.”</li>
      <li>“The GIS ↔ LiDAR tab shows the matching method on simulated detections: it separates a systematic 5 m offset on one line from genuinely missing and unrecorded structures, so you fix one transform instead of editing each record.”</li>
      <li>“It then writes the customer data request and the map_lookup formulas for your formula language. I don’t know your internal tooling, so I’d love to hear how close this is to what the team does today.”</li></ol></div>`;
}

/* ======================= GLOBAL ======================= */
document.addEventListener("click", e => { const b = e.target.closest("[data-goto]"); if(b) showTab(b.dataset.goto); });
const mq = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)"); if(mq && mq.addEventListener) mq.addEventListener("change", draw);
new MutationObserver(draw).observe(document.documentElement, {attributes:true, attributeFilter:["data-theme"]});
renderLegend(); renderAbout(); resize(); loadDemo();
})();
