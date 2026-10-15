/* Grid Intake Check — analysis engine (no DOM). Works in the browser and in Node for testing. */
(function(root){
"use strict";

/* ---------- Projection: WGS 84 lon/lat → Transverse Mercator (Snyder series) ---------- */
const GRS80 = {a:6378137, f:1/298.257222101};
function tmForward(latDeg, lonDeg, p){
  const a = p.a, f = p.f, e2 = f * (2 - f), ep2 = e2 / (1 - e2);
  const phi = latDeg * Math.PI / 180, lam = lonDeg * Math.PI / 180, lam0 = p.lon0 * Math.PI / 180;
  const s = Math.sin(phi), c = Math.cos(phi), t = Math.tan(phi);
  const N = a / Math.sqrt(1 - e2 * s * s), T = t * t, C = ep2 * c * c, A = (lam - lam0) * c;
  const e4 = e2 * e2, e6 = e4 * e2;
  const M = a * ((1 - e2/4 - 3*e4/64 - 5*e6/256) * phi - (3*e2/8 + 3*e4/32 + 45*e6/1024) * Math.sin(2*phi)
            + (15*e4/256 + 45*e6/1024) * Math.sin(4*phi) - (35*e6/3072) * Math.sin(6*phi));
  const x = p.k0 * N * (A + (1 - T + C) * A**3 / 6 + (5 - 18*T + T*T + 72*C - 58*ep2) * A**5 / 120);
  const y = p.k0 * (M + N * t * (A*A/2 + (5 - T + 9*C + 4*C*C) * A**4 / 24 + (61 - 58*T + T*T + 600*C - 330*ep2) * A**6 / 720));
  return [p.fe + x, p.fn + y];
}
function pickCRS(lat, lon){
  if(lat > 53.8 && lat < 56.5 && lon > 20.9 && lon < 26.9)
    return {code:"EPSG:3346", name:"LKS-94 / Lithuania TM", a:GRS80.a, f:GRS80.f, lon0:24, k0:0.9998, fe:500000, fn:0};
  const zone = Math.floor((lon + 180) / 6) + 1, north = lat >= 0;
  return {code:"EPSG:" + (north ? 32600 : 32700) + zone, name:"WGS 84 / UTM zone " + zone + (north ? "N" : "S"),
          a:6378137, f:1/298.257223563, lon0:zone * 6 - 183, k0:0.9996, fe:500000, fn:north ? 0 : 10000000};
}

/* ---------- Helpers ---------- */
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
function median(arr){ if(!arr.length) return 0; const s = [...arr].sort((a, b) => a - b), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }
function pct(arr, q){ if(!arr.length) return 0; const s = [...arr].sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.floor(q * (s.length - 1)))]; }
function makeGrid(items, cell){
  const g = new Map();
  for(const it of items){ const k = Math.floor(it.x / cell) + ":" + Math.floor(it.y / cell); if(!g.has(k)) g.set(k, []); g.get(k).push(it); }
  return {near(p, r){ const out = [], x0 = Math.floor((p.x - r) / cell), x1 = Math.floor((p.x + r) / cell), y0 = Math.floor((p.y - r) / cell), y1 = Math.floor((p.y + r) / cell);
    for(let i = x0; i <= x1; i++) for(let j = y0; j <= y1; j++){ const b = g.get(i + ":" + j); if(b) for(const it of b) if(dist(p, it) <= r) out.push(it); } return out; }};
}
function pointInRing(p, ring){ let inside = false; for(let i = 0, j = ring.length - 1; i < ring.length; j = i++){ const a = ring[i], b = ring[j];
  if(((a.y > p.y) !== (b.y > p.y)) && (p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x)) inside = !inside; } return inside; }
function distToSeg(p, a, b){ const dx = b.x - a.x, dy = b.y - a.y, L = dx*dx + dy*dy; let t = L ? ((p.x - a.x) * dx + (p.y - a.y) * dy) / L : 0; t = Math.max(0, Math.min(1, t));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy)); }
function distToBoundary(p, ring){ let d = Infinity; for(let i = 0; i < ring.length - 1; i++) d = Math.min(d, distToSeg(p, ring[i], ring[i + 1])); return d; }
function distToRing(p, ring){ return pointInRing(p, ring) ? 0 : distToBoundary(p, ring); }
function segCross(a, b, c, d){ const o = (p, q, r) => Math.sign((q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x));
  return o(a, b, c) !== o(a, b, d) && o(c, d, a) !== o(c, d, b); }
function coverageRing(cov){ // [west, south, east, north] or GeoJSON Polygon → densified [[lat, lon], ...]
  if(!cov) return null;
  if(cov.type === "Polygon") return cov.coordinates[0].map(c => [c[1], c[0]]);
  if(!Array.isArray(cov) || cov.length !== 4) return null;
  const [w, s, e, n] = cov.map(Number), k = 64, out = [];
  for(let i = 0; i < k; i++) out.push([s, w + (e - w) * i / k]);
  for(let i = 0; i < k; i++) out.push([s + (n - s) * i / k, e]);
  for(let i = 0; i < k; i++) out.push([n, e - (e - w) * i / k]);
  for(let i = 0; i < k; i++) out.push([n - (n - s) * i / k, w]);
  out.push(out[0]); return out;
}

function parseVoltage(v){
  if(v == null || v === "") return {ok:false, kind:"missing"};
  const parts = String(v).split(/[;,]/).map(s => s.trim()).filter(Boolean);
  const nums = parts.map(s => Number(s.replace(/\s/g, "")));
  if(nums.some(n => !isFinite(n) || n <= 0)) return {ok:false, kind:"unparseable", raw:v};
  return {ok:true, values:nums, max:Math.max(...nums), multi:nums.length > 1};
}
function vClass(maxV){ if(maxV == null) return "unknown"; if(maxV >= 300000) return "330 kV"; if(maxV >= 100000) return "110 kV"; if(maxV >= 30000) return "35 kV"; if(maxV >= 1000) return "6–20 kV"; return "LV"; }

/* ---------- Normalise input ---------- */
function fromOverpassCompact(d){ // our compact demo format
  const cov = d.coverage || (Array.isArray(d.bbox) && d.bbox.length === 4 ? [d.bbox[1], d.bbox[0], d.bbox[3], d.bbox[2]] : null);
  return {meta:{source:d.source, fetched:d.fetched}, coverage:coverageRing(cov),
    structures:d.structures.map(n => ({id:String(n.id), lat:n.lat, lon:n.lon, power:n.power, tags:n.tags || {}})),
    lines:d.lines.map(w => ({id:String(w.id), power:w.power, tags:w.tags || {}, coords:w.coords})),
    substations:(d.substations || []).map(s => ({id:String(s.id), name:s.name, voltage:s.voltage, ring:s.ring}))};
}
function fromOverpass(d){
  const structures = [], lines = [], substations = [];
  for(const e of d.elements || []){
    const t = e.tags || {};
    if(e.type === "node" && /^(tower|pole|portal|terminal)$/.test(t.power || "")) structures.push({id:String(e.id), lat:e.lat, lon:e.lon, power:t.power, tags:t});
    else if(e.type === "way" && e.geometry && /^(line|minor_line|cable)$/.test(t.power || "")) lines.push({id:String(e.id), power:t.power, tags:t, coords:e.geometry.map(g => [g.lat, g.lon])});
    else if(e.type === "way" && e.geometry && /^(substation|plant)$/.test(t.power || "")) substations.push({id:String(e.id), name:t.name || "", voltage:t.voltage || "", ring:e.geometry.map(g => [g.lat, g.lon])});
  }
  return {meta:{source:"Overpass JSON upload"}, structures, lines, substations};
}
function fromGeoJSON(gj){
  const structures = [], lines = [], substations = [], problems = [];
  let n = 0;
  const feats = gj.type === "FeatureCollection" ? gj.features : gj.type === "Feature" ? [gj] : [];
  for(const f of feats){
    if(!f || !f.geometry) continue;
    const p = f.properties || {}, g = f.geometry, id = String(f.id ?? p.id ?? p.ref ?? ("f" + (++n)));
    const tags = {}; for(const k in p) if(p[k] != null && typeof p[k] !== "object") tags[k] = String(p[k]);
    if(g.type === "Point") structures.push({id, lat:g.coordinates[1], lon:g.coordinates[0], power:tags.power || "structure", tags});
    else if(g.type === "LineString") lines.push({id, power:tags.power || "line", tags, coords:g.coordinates.map(c => [c[1], c[0]])});
    else if(g.type === "MultiLineString") g.coordinates.forEach((part, i) => lines.push({id:id + "/" + i, power:tags.power || "line", tags, coords:part.map(c => [c[1], c[0]])}));
    else if(g.type === "Polygon" && /substation|plant/.test(tags.power || "")) substations.push({id, name:tags.name || "", voltage:tags.voltage || "", ring:g.coordinates[0].map(c => [c[1], c[0]])});
  }
  return {meta:{source:"GeoJSON upload"}, coverage:coverageRing(gj.coverage), structures, lines, substations, problems};
}
function validateCoords(ds){
  const all = ds.structures.map(s => [s.lat, s.lon]).concat(ds.lines.flatMap(l => l.coords));
  if(!all.length) return {ok:false, msg:"The file contains no points or lines that look like structures or power lines."};
  const badLat = all.filter(c => Math.abs(c[0]) > 90).length, badLon = all.filter(c => Math.abs(c[1]) > 180).length;
  if(badLat || badLon) return {ok:false, msg:"Coordinates are outside the longitude/latitude range (" + (badLat + badLon) + " values). The file is probably in a projected CRS. GeoJSON must be EPSG:4326 (RFC 7946): ask the customer for the source CRS and re-export, e.g. ogr2ogr -t_srs EPSG:4326."};
  return {ok:true};
}

/* ---------- Main analysis ---------- */
const STRUCT_FIELDS = [
  {key:"ref", label:"Structure number", why:"Needed to match the model to the utility’s asset register, work orders and field reports."},
  {key:"line_attachment", label:"Suspension / tension (anchor)", why:"Decides how load and tension sections are modelled; wrong type means wrong sag and wrong structure loads."},
  {key:"material", label:"Material", why:"Selects the pole/tower library type, strength and stiffness for loading and FEA."},
  {key:"design", label:"Design / configuration", why:"Picks the assembly (crossarm layout, phase spacing) used for clearance and clash checks."},
  {key:"height", label:"Height", why:"Attachment heights drive ground clearance; without it the model relies on LiDAR or defaults."}
];
const LINE_FIELDS = [
  {key:"voltage", label:"Voltage", why:"Selects clearance rules (by voltage and object type) and the right standards."},
  {key:"cables", label:"Cables (conductor count)", why:"Number of phase conductors to model per span."},
  {key:"circuits", label:"Circuits", why:"Single or double circuit changes geometry, loads and clash pairs."},
  {key:"name", label:"Line name / circuit ID", why:"Needed for reporting by circuit and for talking to the utility’s engineers."},
  {key:"operator", label:"Operator", why:"Confirms asset ownership; foreign-owned crossings must be excluded or flagged."}
];

function analyse(raw, opts){
  opts = Object.assign({snapTol:1.0, dupTol:2.0, subTol:30, edgeBuffer:300, spanFactor:2.5, minSpan:15}, opts || {});
  const ds = raw;
  // projection
  const all = ds.structures.map(s => [s.lat, s.lon]).concat(ds.lines.flatMap(l => l.coords));
  const cLat = all.reduce((s, c) => s + c[0], 0) / all.length, cLon = all.reduce((s, c) => s + c[1], 0) / all.length;
  const crs = pickCRS(cLat, cLon), P = (la, lo) => { const [x, y] = tmForward(la, lo, crs); return {x, y, lat:la, lon:lo}; };
  const S = ds.structures.map(s => Object.assign({}, s, P(s.lat, s.lon), {kind:"structure"}));
  const L = ds.lines.map(l => ({id:l.id, power:l.power, tags:l.tags, kind:"line", pts:l.coords.map(c => P(c[0], c[1]))}));
  const SUB = (ds.substations || []).map(s => ({id:s.id, name:s.name, voltage:s.voltage, ring:s.ring.map(c => P(c[0], c[1]))}));
  // footprint (data extent) and inner zone
  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  for(const p of S.concat(L.flatMap(l => l.pts))){ minx = Math.min(minx, p.x); miny = Math.min(miny, p.y); maxx = Math.max(maxx, p.x); maxy = Math.max(maxy, p.y); }
  const bounds = {minx, miny, maxx, maxy};
  // coverage = the area the data is meant to describe; outside it features are context only
  const COV = ds.coverage ? ds.coverage.map(c => P(c[0], c[1])) : null;
  const eb = opts.edgeBuffer;
  const inCov = p => !COV || pointInRing(p, COV);
  const inner = p => COV ? pointInRing(p, COV) && (eb <= 0 || distToBoundary(p, COV) >= eb)
                         : eb <= 0 || p.x > minx + eb && p.x < maxx - eb && p.y > miny + eb && p.y < maxy - eb;
  const lineInCov = l => !COV || l.pts.some(inCov) || l.pts.some((p, i) => i > 0 && COV.some((c, j) => j > 0 && segCross(l.pts[i - 1], p, COV[j - 1], c)));
  const scopeS = S.filter(inCov), scopeL = L.filter(lineInCov), scopeSIds = new Set(scopeS.map(s => s.id)), scopeLIds = new Set(scopeL.map(l => l.id));
  const sGrid = makeGrid(S, 10);
  const byId = new Map(); S.forEach(s => byId.set("s:" + s.id, s)); L.forEach(l => byId.set("l:" + l.id, l));

  const issues = []; // {check, sev, ref:"s:id"|"l:id", at:{x,y,lat,lon}, detail}
  const add = (check, sev, ref, at, detail) => issues.push({check, sev, ref, at:{x:at.x, y:at.y, lat:at.lat, lon:at.lon}, detail});

  // line voltage parse + class
  for(const l of L){ const v = parseVoltage(l.tags.voltage); l.v = v; l.vclass = v.ok ? vClass(v.max) : "unknown"; }

  // 1. completeness
  const completeness = {structures:STRUCT_FIELDS.map(f => { const have = scopeS.filter(s => s.tags[f.key] != null && s.tags[f.key] !== "").length; return Object.assign({}, f, {have, total:scopeS.length}); }),
                        lines:LINE_FIELDS.map(f => { const have = scopeL.filter(l => l.tags[f.key] != null && l.tags[f.key] !== "").length; return Object.assign({}, f, {have, total:scopeL.length}); })};
  for(const l of scopeL) if(!l.v.ok && l.v.kind === "missing") add("line-voltage-missing", "high", "l:" + l.id, l.pts[l.pts.length >> 1], "Line has no voltage" + (l.tags.name ? " (" + l.tags.name + ")" : ""));
  for(const l of scopeL) if(!l.v.ok && l.v.kind === "unparseable") add("line-voltage-invalid", "high", "l:" + l.id, l.pts[l.pts.length >> 1], "Voltage value “" + l.v.raw + "” can’t be parsed");
  for(const l of scopeL) if(l.v.ok && l.v.multi) add("line-voltage-multi", "medium", "l:" + l.id, l.pts[l.pts.length >> 1], "Several voltages on one line (" + l.tags.voltage + "): split into circuits or confirm a shared-structure line");

  // 2. cables vs circuits
  for(const l of scopeL){ const c = Number(l.tags.cables), k = Number(l.tags.circuits);
    if(l.tags.cables && l.tags.circuits && isFinite(c) && isFinite(k) && c !== 3 * k) add("cables-circuits", "medium", "l:" + l.id, l.pts[l.pts.length >> 1], "cables=" + l.tags.cables + " but circuits=" + l.tags.circuits + " (expected cables = 3 × circuits for 3-phase AC)"); }

  // vertex → structure snapping
  const onStruct = p => { const n = sGrid.near(p, opts.snapTol); return n.length ? n[0] : null; };
  const usedStruct = new Set();
  // endpoint index for joints
  const ends = []; L.forEach(l => { ends.push({x:l.pts[0].x, y:l.pts[0].y, line:l.id}); ends.push({x:l.pts[l.pts.length - 1].x, y:l.pts[l.pts.length - 1].y, line:l.id}); });
  const vtx = []; L.forEach(l => l.pts.forEach(p => vtx.push({x:p.x, y:p.y, line:l.id})));
  const vGrid = makeGrid(vtx, 10);
  const endpointStats = {total:0, onStructure:0, atSubstation:0, joint:0, dangling:0, edge:0};
  const spans = [];
  let bends = 0;
  for(const l of L){
    let prevS = null, prevIdx = -1, along = 0, alongSinceStruct = 0, interior = 0;
    l.pts.forEach((p, i) => {
      if(i > 0){ const d = dist(l.pts[i - 1], p); along += d; alongSinceStruct += d; }
      const st = onStruct(p);
      if(st) usedStruct.add(st.id);
      const isEnd = i === 0 || i === l.pts.length - 1;
      if(isEnd){
        endpointStats.total++;
        if(!inner(p)){ endpointStats.edge++; }
        else if(st){ endpointStats.onStructure++; }
        else if(SUB.some(s => distToRing(p, s.ring) <= opts.subTol)){ endpointStats.atSubstation++; }
        else if(vGrid.near(p, opts.snapTol).some(v => v.line !== l.id)){ endpointStats.joint++; }
        else { endpointStats.dangling++;
          let detail = "Line end is not on a structure, a substation or another line";
          const nb = vGrid.near(p, 50).filter(v => v.line !== l.id).sort((a, b) => dist(p, a) - dist(p, b))[0];
          if(nb) detail += "; line " + nb.line + " passes " + Math.round(dist(p, nb)) + " m away, so a structure or connection is probably missing between them";
          add("dangling-end", "high", "l:" + l.id, p, detail); }
      } else if(!st && inner(p)){ bends++; interior++; }
      if(st){
        if(prevS && prevS.id !== st.id && inner(prevS) && inner(st)){ spans.push({line:l.id, vclass:l.vclass, a:prevS, b:st, len:alongSinceStruct, chord:dist(prevS, st), vertices:i - prevIdx - 1}); }
        prevS = st; prevIdx = i; alongSinceStruct = 0;
      }
    });
    l.length = along;
    l.inScope = scopeLIds.has(l.id);
    l.lengthInCoverage = !COV ? along : l.pts.reduce((acc, p, i) => i && inCov({x:(p.x + l.pts[i - 1].x) / 2, y:(p.y + l.pts[i - 1].y) / 2}) ? acc + dist(l.pts[i - 1], p) : acc, 0);
    if(interior) add("bend-no-structure", interior > 2 ? "medium" : "low", "l:" + l.id, l.pts[Math.max(1, l.pts.length >> 1)], interior + " line vertex(es) with no structure: missing pole/tower or digitising noise");
  }

  // 3. orphan structures
  for(const s of S) if(!usedStruct.has(s.id) && inner(s)) add("orphan-structure", "medium", "s:" + s.id, s, "Structure (" + s.power + ") is not on any line");

  // 4. duplicates
  const seen = new Set();
  for(const s of S){ for(const o of sGrid.near(s, opts.dupTol)){ if(o.id === s.id) continue; const k = [s.id, o.id].sort().join("|"); if(seen.has(k)) continue; seen.add(k); if(!scopeSIds.has(s.id) || !scopeSIds.has(o.id)) continue;
    add("duplicate-structure", "high", "s:" + s.id, s, "Within " + dist(s, o).toFixed(2) + " m of structure " + o.id + ": likely duplicate record"); } }

  // 5. span outliers by voltage class
  const spanStats = {};
  const groups = {}; spans.forEach(sp => (groups[sp.vclass] = groups[sp.vclass] || []).push(sp.len));
  for(const k in groups) spanStats[k] = {n:groups[k].length, median:median(groups[k]), p95:pct(groups[k], .95), max:Math.max(...groups[k])};
  for(const sp of spans){
    const m = spanStats[sp.vclass].median, mid = {x:(sp.a.x + sp.b.x) / 2, y:(sp.a.y + sp.b.y) / 2, lat:(sp.a.lat + sp.b.lat) / 2, lon:(sp.a.lon + sp.b.lon) / 2};
    if(sp.len > opts.spanFactor * m) add("span-long", "medium", "l:" + sp.line, mid, "Span " + Math.round(sp.len) + " m is " + (sp.len / m).toFixed(1) + "× the " + sp.vclass + " median (" + Math.round(m) + " m): missing structure or skipped pole");
    else if(sp.len < opts.minSpan) add("span-short", "low", "l:" + sp.line, mid, "Span only " + sp.len.toFixed(1) + " m: possible duplicate structure or gantry");
  }

  // 6. joint voltage mismatch
  const endIdx = makeGrid(ends, 10);
  const vm = new Set();
  for(const e of ends){ const l = L.find(x => x.id === e.line); if(!l.v.ok || !inner(e)) continue;
    for(const o of endIdx.near(e, opts.snapTol)){ if(o.line === e.line) continue; const k = [e.line, o.line].sort().join("|"); if(vm.has(k)) continue; vm.add(k);
      const l2 = L.find(x => x.id === o.line); if(l2.v.ok && l2.v.max !== l.v.max) add("joint-voltage", "medium", "l:" + l.id, e, "Joins line " + l2.id + " but voltage differs (" + l.tags.voltage + " vs " + l2.tags.voltage + ")"); } }

  // 7. flags from source
  for(const s of scopeS) if(s.tags.fixme) add("fixme", "low", "s:" + s.id, s, "Source note: " + s.tags.fixme);

  // checks catalogue + score
  const CHECKS = [
    {id:"line-voltage-missing", title:"Lines without voltage", group:"Attributes"},
    {id:"line-voltage-invalid", title:"Unparseable voltage values", group:"Attributes"},
    {id:"line-voltage-multi", title:"Several voltages on one line", group:"Attributes"},
    {id:"cables-circuits", title:"Cables don’t match circuits", group:"Attributes"},
    {id:"joint-voltage", title:"Voltage changes at a line joint", group:"Topology"},
    {id:"dangling-end", title:"Dangling line ends", group:"Topology"},
    {id:"bend-no-structure", title:"Line vertices without a structure", group:"Topology"},
    {id:"orphan-structure", title:"Structures not on any line", group:"Topology"},
    {id:"duplicate-structure", title:"Duplicate structures", group:"Geometry"},
    {id:"span-long", title:"Unusually long spans", group:"Geometry"},
    {id:"span-short", title:"Very short spans", group:"Geometry"},
    {id:"fixme", title:"Notes left in the source data", group:"Source"}
  ].map(c => { const list = issues.filter(i => i.check === c.id); const sev = list.some(i => i.sev === "high") ? "high" : list.some(i => i.sev === "medium") ? "medium" : list.length ? "low" : "pass"; return Object.assign(c, {count:list.length, sev}); });

  const critical = completeness.structures.filter(f => ["ref","line_attachment","material"].includes(f.key)).concat(completeness.lines.filter(f => f.key === "voltage"));
  const attrScore = critical.reduce((s, f) => s + f.have / Math.max(1, f.total), 0) / critical.length;           // 0..1
  const topoBad = issues.filter(i => ["dangling-end","orphan-structure","duplicate-structure","joint-voltage"].includes(i.check)).length;
  const topoScore = Math.max(0, 1 - topoBad / Math.max(1, scopeS.length * 0.05));
  const geomBad = issues.filter(i => ["span-long","bend-no-structure"].includes(i.check)).length;
  const geomScore = Math.max(0, 1 - geomBad / Math.max(1, scopeL.length * 0.5));
  const score = Math.round(100 * (0.5 * attrScore + 0.3 * topoScore + 0.2 * geomScore));

  return {opts, crs, bounds, coverage:COV, scopeStructures:scopeS, scopeLines:scopeL, structures:S, lines:L, substations:SUB, byId, issues, checks:CHECKS, completeness, endpointStats, spans, spanStats,
          bends, score, parts:{attributes:Math.round(attrScore * 100), topology:Math.round(topoScore * 100), geometry:Math.round(geomScore * 100)}, meta:ds.meta || {}};
}

/* ---------- Reconciliation: register structures vs detected structures ---------- */
function mulberry32(a){ return function(){ a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function gauss(r){ let u = 0, v = 0; while(!u) u = r(); while(!v) v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
function simulateDetections(res, seed){
  const r = mulberry32(seed || 7), crs = res.crs, det = [];
  // one line digitised with a systematic offset (old map source)
  const offsetLine = res.scopeLines.filter(l => l.vclass === "110 kV").sort((a, b) => b.pts.length - a.pts.length)[3];
  const offsetIds = new Set(offsetLine ? offsetLine.pts.map(p => { const n = res.scopeStructures.find(s => Math.hypot(s.x - p.x, s.y - p.y) < 1); return n && n.id; }).filter(Boolean) : []);
  let k = 0;
  for(const s of res.scopeStructures){
    if(r() < 0.035) continue; // missed / removed in the field
    let dx = gauss(r) * 0.5, dy = gauss(r) * 0.5;
    if(offsetIds.has(s.id)){ dx -= 4.2; dy += 2.6; } // register is ~5 m off the true position here
    det.push({id:"D" + (++k), x:s.x - dx, y:s.y - dy, cls:s.power === "pole" ? "structure" : "tower", truth:s.id});
  }
  // unrecorded structures: mid-span on some long spans
  const longSpans = res.spans.filter(sp => sp.len > 1.6 * (res.spanStats[sp.vclass] || {median:1e9}).median);
  longSpans.slice(0, 12).forEach(sp => det.push({id:"D" + (++k), x:(sp.a.x + sp.b.x) / 2 + gauss(r), y:(sp.a.y + sp.b.y) / 2 + gauss(r), cls:"tower", truth:null}));
  // false positives: street lights / signs near lines (pole_np)
  const L = res.scopeLines; for(let i = 0; i < Math.round(res.scopeStructures.length * 0.015); i++){ const l = L[Math.floor(r() * L.length)], p = l.pts[Math.floor(r() * l.pts.length)];
    det.push({id:"D" + (++k), x:p.x + 6 + r() * 20, y:p.y + 6 + r() * 20, cls:"pole_np", truth:null}); }
  // lat/lon not needed for matching; keep for export via inverse-free approximation
  return {points:det, offsetLine:offsetLine ? offsetLine.id : null, synthetic:true};
}
function reconcile(res, det, tol){
  tol = tol || 3;
  const D = det.points.filter(p => p.cls !== "pole_np" || true);
  const grid = makeGrid(D, 10), cand = [];
  for(const s of res.scopeStructures) for(const d of grid.near(s, tol)) cand.push({s, d, dd:dist(s, d)});
  cand.sort((a, b) => a.dd - b.dd);
  const usedS = new Set(), usedD = new Set(), pairs = [];
  for(const c of cand){ if(usedS.has(c.s.id) || usedD.has(c.d.id)) continue; usedS.add(c.s.id); usedD.add(c.d.id); pairs.push(c); }
  const regOnly = res.scopeStructures.filter(s => !usedS.has(s.id));
  const detOnly = D.filter(d => !usedD.has(d.id));
  // near-misses: register-only with a detection within 3×tol → likely positional offset, not missing
  const wide = makeGrid(detOnly, 10);
  const offsets = regOnly.map(s => { const n = wide.near(s, tol * 3).sort((a, b) => dist(s, a) - dist(s, b))[0]; return n ? {s, d:n, dd:dist(s, n)} : null; }).filter(Boolean);
  const offsetDet = new Set(offsets.map(o => o.d.id));
  const disp = pairs.map(p => p.dd);
  return {tol, pairs, regOnly, detOnly, offsets,
          trulyMissing:regOnly.filter(s => !offsets.some(o => o.s.id === s.id)),
          unrecorded:detOnly.filter(d => !offsetDet.has(d.id) && d.cls !== "pole_np"),
          nonPower:detOnly.filter(d => d.cls === "pole_np"),
          stats:{median:median(disp), p95:pct(disp, .95), max:disp.length ? Math.max(...disp) : 0}};
}

root.GridIntake = {analyse, reconcile, simulateDetections, fromOverpass, fromOverpassCompact, fromGeoJSON, validateCoords, tmForward, pickCRS, parseVoltage, STRUCT_FIELDS, LINE_FIELDS};
})(typeof window !== "undefined" ? window : globalThis);
