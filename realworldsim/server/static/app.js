/* RealWorldSim front-end. Vanilla JS + d3 (map) + uPlot (charts). */
(() => {
  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const fmt = {
    n: (v, d = 1) => (v == null || isNaN(v)) ? '—' : Number(v).toFixed(d),
    pct: (v, d = 1) => (v == null || isNaN(v)) ? '—' : `${Number(v).toFixed(d)}%`,
    big: (v) => v >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(1)}k` : `${Math.round(v)}`,
    tn: (bn) => bn >= 1000 ? `$${(bn / 1000).toFixed(1)}T` : `$${bn.toFixed(0)}B`,
    pop: (p) => p >= 1e9 ? `${(p / 1e9).toFixed(2)}B` : p >= 1e6 ? `${(p / 1e6).toFixed(1)}M` : `${(p / 1e3).toFixed(0)}k`,
  };

  // ---- metrics shown on the map ---------------------------------------------
  // seq: one-hue blue ramp (magnitude); div: blue<->red around a neutral midpoint (polarity)
  const SEQ = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#1c5cab', '#104281', '#0d366b'];
  const METRICS = {
    growth:          { label: 'Growth %',      kind: 'div', dom: [-6, 0, 8], f: (v) => fmt.pct(v) },
    inflation:       { label: 'Inflation %',   kind: 'seq', dom: [0, 20],   f: (v) => fmt.pct(v), log: true },
    unemployment:    { label: 'Unemployment',  kind: 'seq', dom: [2, 25],   f: (v) => fmt.pct(v) },
    policy_rate:     { label: 'Policy rate',   kind: 'seq', dom: [0, 20],   f: (v) => fmt.pct(v, 2) },
    debt_gdp:        { label: 'Debt / GDP',    kind: 'seq', dom: [20, 180], f: (v) => fmt.pct(v, 0) },
    unrest:          { label: 'Unrest',        kind: 'seq', dom: [0, 0.8],  f: (v) => fmt.n(v, 2) },
    stability:       { label: 'Stability',     kind: 'seq', dom: [1, 0],    f: (v) => fmt.n(v, 2) },
    war_intensity:   { label: 'War',           kind: 'seq', dom: [0, 1],    f: (v) => fmt.n(v, 2) },
    risk:            { label: 'Risk premium',  kind: 'seq', dom: [0, 0.6],  f: (v) => fmt.n(v, 2) },
    fx:              { label: 'FX vs start',   kind: 'div', dom: [60, 100, 250], f: (v) => fmt.n(v, 0), invert: true },
    mil_spend_gdp:   { label: 'Military %GDP', kind: 'seq', dom: [0, 8],    f: (v) => fmt.pct(v) },
    gdp:             { label: 'GDP',           kind: 'seq', dom: [1, 30000], f: (v) => fmt.tn(v), log: true },
    drought:         { label: 'Drought',       kind: 'div', dom: [-0.8, 0, 0.8], f: (v) => fmt.n(v, 2), invert: true },
    mil_power:       { label: 'Military power', kind: 'seq', dom: [0, 1],   f: (v) => fmt.n(v, 2) },
    tension:         { label: 'Tension with…', kind: 'seq', dom: [0, 1],    f: (v) => fmt.n(v, 2) },
  };
  const FIELD_LABELS = { gdp: 'GDP', growth: 'Growth', inflation: 'Inflation', unemployment: 'Unemployment', policy_rate: 'Policy rate',
    debt_gdp: 'Debt/GDP', fx: 'FX idx', stability: 'Stability', unrest: 'Unrest', war_intensity: 'War', mil_spend_gdp: 'Mil %GDP',
    risk: 'Risk', sanctioned_share: 'Sanctioned' };

  const seqScale = (dom, log) => {
    const base = log ? d3.scaleLog().domain([Math.max(dom[0], 0.01), dom[1]]) : d3.scaleLinear().domain(dom);
    const interp = d3.piecewise(d3.interpolateRgb, SEQ);
    return (v) => interp(Math.max(0, Math.min(1, base.clamp(true)(Math.max(v, log ? 0.01 : -1e9)))));
  };
  const divScale = (dom, invert) => {
    const s = d3.scaleLinear().domain(dom).range(invert ? ['#e66767', '#383835', '#3987e5'] : ['#e66767', '#383835', '#3987e5']).clamp(true).interpolate(d3.interpolateRgb);
    return (v) => s(v);
  };

  // ---- state -------------------------------------------------------------------
  const S = { meta: null, geo: null, state: null, running: false, speed: 30, metric: 'growth', selected: null,
    tensionRow: null, events: [], history: null, charts: {}, cCharts: {}, seenEventKey: new Set() };

  // ---- networking ----------------------------------------------------------------
  const api = async (path, body) => {
    const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : undefined);
    if (!r.ok) { const t = await r.text(); throw new Error(t); }
    return r.json();
  };
  const control = (action, extra = {}) => api('/api/control', { action, ...extra }).catch((e) => toast(e.message));
  const intervene = (body) => api('/api/intervene', body).then(() => refreshHistory()).catch((e) => toast(e.message));
  let toastT; const toast = (msg) => { const t = $('#tooltip'); t.hidden = false; t.style.left = '50%'; t.style.top = '20px'; t.innerHTML = `<b>${msg}</b>`; clearTimeout(toastT); toastT = setTimeout(() => (t.hidden = true), 2500); };

  function connect() {
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.type === 'frame') onFrame(d); };
    ws.onclose = () => setTimeout(connect, 1500);
    setInterval(() => { if (ws.readyState === 1) ws.send('.'); }, 20000);
  }

  let frameCount = 0;
  function onFrame(d) {
    const prevDay = S.state ? S.state.day : -1;
    S.state = d.state; S.running = d.running; S.speed = d.speed;
    if (d.events && d.events.length) addEvents(d.events);
    renderClock(); renderKpis(); renderMap(); renderSide();
    frameCount++;
    // refresh history charts: every frame when slow, throttled when fast
    if (S.state.day !== prevDay && (S.speed <= 91 || frameCount % 4 === 0 || !S.running)) refreshHistory();
    if (S.selected && S.state.day !== prevDay && frameCount % 3 === 0) loadCountry(S.selected, true);
  }

  // ---- header -------------------------------------------------------------------
  function renderClock() {
    const st = S.state;
    $('#date').textContent = st.date;
    $('#daycount').textContent = `day ${st.day.toLocaleString()} · ${(st.day / 365.25).toFixed(1)} yrs since ${st.start}`;
    $('#btn-play').textContent = S.running ? '❚❚' : '▶';
    $('#seedlabel').textContent = `seed ${st.seed}` + (st.live_data_date ? ` · live data ${st.live_data_date}` : ' · bundled seed data');
    const sp = $('#speed'); if (String(S.speed) !== sp.value && [...sp.options].some((o) => o.value === String(S.speed))) sp.value = String(S.speed);
    $('#live-note').textContent = st.live_data_date ? `World initialised from live data synced ${st.live_data_date}.` : 'World initialised from bundled seed data (Natural Earth + curated 2025 estimates). Run `rws sync` for live figures.';
  }
  function delta(id, cur, start) {
    const e = $(id); const r = cur / start - 1; e.textContent = `${r >= 0 ? '+' : ''}${(r * 100).toFixed(0)}%`;
    e.className = 'd ' + (r > 0.02 ? 'up' : r < -0.02 ? 'down' : '');
  }
  function renderKpis() {
    const w = S.state.world, p = S.state.prices, p0 = S.state.price_start;
    $('#k-gdp').textContent = fmt.tn(w.gdp);
    $('#k-growth').textContent = fmt.pct(w.growth);
    $('#k-infl').textContent = fmt.pct(w.inflation);
    $('#k-oil').textContent = `$${fmt.n(p.oil, 0)}`; delta('#d-oil', p.oil, p0.oil);
    $('#k-gas').textContent = `€${fmt.n(p.gas_eu, 0)}`; delta('#d-gas', p.gas_eu, p0.gas_eu);
    $('#k-wheat').textContent = `$${fmt.n(p.wheat, 2)}`; delta('#d-wheat', p.wheat, p0.wheat);
    $('#k-gold').textContent = `$${fmt.n(p.gold, 0)}`; delta('#d-gold', p.gold, p0.gold);
    $('#k-wars').textContent = w.active_wars;
    $('#k-ref').textContent = fmt.pop(w.refugees);
    $('#k-risk').textContent = fmt.n(w.risk, 2);
    if (w.enso_state) { const e = $('#d-enso'); e.textContent = w.enso_state === 'el_nino' ? 'El Niño' : w.enso_state === 'la_nina' ? 'La Niña' : 'ENSO neutral'; e.className = 'd ' + (w.enso_state === 'el_nino' ? 'up' : w.enso_state === 'la_nina' ? 'down' : ''); }
    $('#k-riskbar').style.width = `${Math.min(100, w.risk * 100)}%`;
  }

  // ---- map ---------------------------------------------------------------------------
  const svg = d3.select('#map');
  const projection = d3.geoNaturalEarth1();
  const path = d3.geoPath(projection);
  let gCountries, gMarks, byIso = {};
  function sizeMap() {
    const wrap = $('#mapwrap'); const w = wrap.clientWidth, h = wrap.clientHeight;
    svg.attr('viewBox', `0 0 ${w} ${h}`);
    projection.fitExtent([[8, 36], [w - 8, h - 8]], { type: 'Sphere' });
    if (gCountries) { svg.select('.sphere').attr('d', path({ type: 'Sphere' })); svg.select('.graticule').attr('d', path(d3.geoGraticule10())); gCountries.selectAll('path').attr('d', path); renderMarks(); }
  }
  function buildMap() {
    sizeMap();
    svg.append('path').attr('class', 'sphere').attr('d', path({ type: 'Sphere' }));
    svg.append('path').attr('class', 'graticule').attr('d', path(d3.geoGraticule10()));
    gCountries = svg.append('g');
    gMarks = svg.append('g');
    gCountries.selectAll('path').data(S.geo.features).join('path').attr('class', 'country').attr('d', path)
      .attr('id', (f) => `c-${f.id}`)
      .on('mousemove', (ev, f) => showTip(ev, f.id)).on('mouseleave', hideTip)
      .on('click', (ev, f) => selectCountry(f.id));
    S.geo.features.forEach((f) => (byIso[f.id] = f));
    const chips = $('#metrics');
    Object.entries(METRICS).forEach(([k, m]) => { const b = el('button', k === S.metric ? 'active' : '', m.label); b.dataset.k = k; b.onclick = () => setMetric(k); chips.appendChild(b); });
    window.addEventListener('resize', sizeMap);
  }
  function setMetric(k) {
    S.metric = k; document.querySelectorAll('#metrics button').forEach((b) => b.classList.toggle('active', b.dataset.k === k));
    if (k === 'tension' && S.selected) loadTension(S.selected); else renderMap();
  }
  function valueFor(iso) {
    const st = S.state; const i = st.iso.indexOf(iso); if (i < 0) return null;
    if (S.metric === 'tension') return S.tensionRow ? S.tensionRow[i] : null;
    return st.fields[S.metric][i];
  }
  function renderMap() {
    if (!gCountries || !S.state) return;
    const m = METRICS[S.metric];
    const scale = m.kind === 'div' ? divScale(m.dom, m.invert) : seqScale(m.dom, m.log);
    gCountries.selectAll('path').attr('fill', (f) => { const v = valueFor(f.id); return v == null ? '#2a2a28' : scale(v); })
      .classed('selected', (f) => f.id === S.selected);
    renderLegend(m, scale); renderMarks(); renderChokes();
  }
  function renderLegend(m, scale) {
    const L = $('#legend'); L.innerHTML = '';
    L.appendChild(el('div', '', m.label + (S.metric === 'tension' && S.selected ? ` ${S.meta.countries.find((c) => c.iso3 === S.selected)?.name || S.selected}` : '')));
    const ramp = el('div', 'ramp'); const dom = m.kind === 'div' ? [m.dom[0], m.dom[2]] : m.dom;
    const stops = d3.range(0, 1.001, 0.1).map((t) => { const v = m.log ? Math.exp(Math.log(Math.max(dom[0], 0.01)) + t * (Math.log(dom[1]) - Math.log(Math.max(dom[0], 0.01)))) : dom[0] + t * (dom[1] - dom[0]); return `${scale(v)} ${t * 100}%`; });
    ramp.style.background = `linear-gradient(90deg, ${stops.join(',')})`; L.appendChild(ramp);
    const lab = el('div', 'lab'); lab.appendChild(el('span', '', m.f(dom[0]))); if (m.kind === 'div') lab.appendChild(el('span', '', m.f(m.dom[1]))); lab.appendChild(el('span', '', m.f(dom[1]))); L.appendChild(lab);
  }
  function centroid(iso) { const c = S.meta.countries.find((x) => x.iso3 === iso); return c ? projection([c.lon, c.lat]) : null; }
  function renderMarks() {
    if (!gMarks || !S.state) return;
    const st = S.state;
    // tension arcs for hotspots
    const arcs = st.hotspots.filter((h) => h.tension > 0.5).map((h) => ({ ...h, a: S.meta.countries.find((c) => c.iso3 === h.a), b: S.meta.countries.find((c) => c.iso3 === h.b) })).filter((h) => h.a && h.b);
    gMarks.selectAll('path.arc').data(arcs, (d) => d.a.iso3 + d.b.iso3).join('path').attr('class', (d) => 'arc' + (d.tension > 0.75 ? ' hot' : ''))
      .attr('d', (d) => path({ type: 'LineString', coordinates: [[d.a.lon, d.a.lat], [d.b.lon, d.b.lat]] }));
    // conflicts: circle at participants; civil wars at the country
    const marks = [];
    st.conflicts.forEach((c) => { const pts = c.a === c.b ? [c.a] : [c.a, c.b]; pts.forEach((iso, k) => { const p = centroid(iso); if (p) marks.push({ id: c.id + k, x: p[0], y: p[1], r: 3 + 10 * c.intensity, name: c.name, i: c.intensity }); }); });
    const g = gMarks.selectAll('g.cf').data(marks, (d) => d.id).join((enter) => { const gg = enter.append('g').attr('class', 'cf'); gg.append('circle').attr('class', 'conflict'); gg.append('circle').attr('class', 'conflict pulse'); return gg; });
    g.attr('transform', (d) => `translate(${d.x},${d.y})`);
    g.select('circle.conflict:not(.pulse)').attr('r', (d) => d.r);
    g.select('circle.pulse').attr('r', (d) => d.r);
  }
  function renderChokes() {
    const C = $('#chokes'); C.innerHTML = '';
    Object.entries(S.state.chokepoints).forEach(([k, v]) => { const s = el('span', v.closed ? 'closed' : '', (v.closed ? '⛔ ' : '⚓ ') + v.name); C.appendChild(s); });
    document.querySelectorAll('#iv-chokes button').forEach((b) => b.classList.toggle('closed', !!S.state.chokepoints[b.dataset.k]?.closed));
  }
  function showTip(ev, iso) {
    const st = S.state; const i = st.iso.indexOf(iso); if (i < 0) return hideTip();
    const t = $('#tooltip'); t.hidden = false;
    const name = S.meta.countries[i].name; const f = st.fields;
    const rows = [['GDP', fmt.tn(f.gdp[i])], ['Growth', fmt.pct(f.growth[i])], ['Inflation', fmt.pct(f.inflation[i])], ['Unemployment', fmt.pct(f.unemployment[i])], ['Debt/GDP', fmt.pct(f.debt_gdp[i], 0)], ['Unrest', fmt.n(f.unrest[i], 2)], ['Stability', fmt.n(f.stability[i], 2)]];
    if (f.war_intensity[i] > 0.01) rows.push(['War', fmt.n(f.war_intensity[i], 2)]);
    if (S.metric === 'tension' && S.tensionRow) rows.unshift(['Tension', fmt.n(S.tensionRow[i], 2)]);
    t.innerHTML = `<b>${name}</b> <span class="muted">${iso}</span>` + rows.map(([k, v]) => `<div class="r"><span>${k}</span><span>${v}</span></div>`).join('');
    const wrap = $('#mapwrap').getBoundingClientRect(); let x = ev.clientX - wrap.left + 14, y = ev.clientY - wrap.top + 14;
    if (x + 270 > wrap.width) x -= 290; if (y + 200 > wrap.height) y -= 210;
    t.style.left = `${x}px`; t.style.top = `${y}px`;
  }
  function hideTip() { $('#tooltip').hidden = true; }

  // ---- side panel ------------------------------------------------------------------
  function addEvents(evs) {
    for (const e of evs) { const key = `${e.day}|${e.text}`; if (S.seenEventKey.has(key)) continue; S.seenEventKey.add(key); S.events.push(e); }
    if (S.events.length > 400) S.events = S.events.slice(-400);
    renderFeed();
  }
  function renderFeed() {
    const ul = $('#feed'); ul.innerHTML = '';
    [...S.events].reverse().slice(0, 150).forEach((e) => { const li = el('li', e.type); li.innerHTML = `<span class="t">${e.date}</span>${escapeHtml(e.text)}`; if (e.country) { li.style.cursor = 'pointer'; li.onclick = () => selectCountry(e.country); } ul.appendChild(li); });
    $('#feedcount').textContent = `${S.events.length} items`;
  }
  const escapeHtml = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  function renderSide() {
    const st = S.state; const ol = $('#hotspots'); ol.innerHTML = '';
    st.hotspots.slice(0, 10).forEach((h) => { const li = el('li'); li.innerHTML = `<span>${h.a} – ${h.b}</span><i class="${h.tension > 0.75 ? 'hot' : ''}">${h.tension.toFixed(2)}</i>`; li.onclick = () => { selectCountry(h.a); setMetric('tension'); }; ol.appendChild(li); });
    renderConflicts($('#conflicts'), false); renderConflicts($('#iv-conflicts'), true);
  }
  function renderConflicts(ul, withControls) {
    ul.innerHTML = ''; const st = S.state;
    if (!st.conflicts.length) ul.appendChild(el('li', 'muted', 'No active conflicts.'));
    st.conflicts.slice().sort((a, b) => b.intensity - a.intensity).forEach((c) => {
      const li = el('li'); const n = el('span', 'n', c.name); const ib = el('span', 'ib'); const bar = el('i'); bar.style.width = `${c.intensity * 100}%`; ib.appendChild(bar);
      li.appendChild(n); li.appendChild(ib);
      const m = el('span', 'm', `${c.type} · since ${c.started} · ${Math.floor(c.days / 30)} mo · intensity ${c.intensity.toFixed(2)}${c.supporters_b?.length ? ' · backed: ' + c.supporters_b.slice(0, 4).join(' ') : ''}`); li.appendChild(m);
      if (withControls) { const row = el('span'); const b1 = el('button', '', 'ceasefire'); b1.onclick = () => intervene({ kind: 'ceasefire', conflict: c.id }); const b2 = el('button', '', 'escalate'); b2.onclick = () => intervene({ kind: 'set_intensity', conflict: c.id, value: Math.min(1, c.intensity + 0.25) }); row.appendChild(b1); row.appendChild(b2); li.appendChild(row); li.style.gridTemplateColumns = '1fr auto'; }
      li.onclick = (ev) => { if (ev.target.tagName !== 'BUTTON') selectCountry(c.a); };
      ul.appendChild(li);
    });
  }

  // ---- country detail -------------------------------------------------------------
  async function selectCountry(iso) {
    S.selected = iso; document.querySelectorAll('.tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === 'country'));
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.id === 'tab-country'));
    if (S.metric === 'tension') loadTension(iso); else renderMap();
    $('#iv-a').value = iso; $('#iv-c').value = iso;
    await loadCountry(iso, false);
  }
  async function loadTension(iso) { const r = await api(`/api/tension/${iso}`); S.tensionRow = r.tension; renderMap(); }
  async function loadCountry(iso, quiet) {
    const [c, h] = await Promise.all([api(`/api/country/${iso}`), api(`/api/history/country/${iso}`)]);
    if (S.selected !== iso) return;
    $('#country-empty').hidden = true; $('#country').hidden = false;
    $('#c-name').textContent = c.name; $('#c-iso').textContent = c.iso3;
    $('#c-meta').textContent = `${c.region} · ${c.income_group.replace('_', ' ')} · pop ${fmt.pop(c.population)}${c.nuclear ? ' · ☢ nuclear' : ''}`;
    const stats = [['GDP', fmt.tn(c.gdp)], ['Growth', fmt.pct(c.growth)], ['Inflation', fmt.pct(c.inflation)], ['Unemployment', fmt.pct(c.unemployment)], ['Policy rate', fmt.pct(c.policy_rate, 2)], ['Debt/GDP', fmt.pct(c.debt_gdp, 0)], ['Deficit', fmt.pct(c.deficit)], ['FX idx', fmt.n(c.fx, 0)], ['Stability', fmt.n(c.stability, 2)], ['Unrest', fmt.n(c.unrest, 2)], ['Regime', c.regime < 0.3 ? 'democracy' : c.regime < 0.6 ? 'hybrid' : 'autocracy'], ['Mil %GDP', fmt.pct(c.mil_spend_gdp)], ['Oil prod', `${fmt.n(c.oil_prod, 2)} mb/d`], ['Oil cons', `${fmt.n(c.oil_cons, 2)} mb/d`], ['Refugees out', fmt.pop(c.refugees_out)]];
    const g = $('#c-stats'); g.innerHTML = ''; stats.forEach(([k, v]) => { const cell = el('div', 'cell'); cell.appendChild(el('div', 'k', k)); cell.appendChild(el('div', 'v', v)); g.appendChild(cell); });
    const rel = $('#c-rel'); rel.innerHTML = '';
    if (c.conflicts.length) { rel.appendChild(el('div', 'h', 'Conflicts')); c.conflicts.forEach((k) => rel.appendChild(el('div', 'r', `${k.name} (${k.intensity})`))); }
    rel.appendChild(el('div', 'h', 'Highest tension')); c.tensions.forEach((t) => { const d = el('div', 'r'); d.innerHTML = `<span>${S.meta.countries.find((x) => x.iso3 === t.with)?.name || t.with}</span><span>${t.value.toFixed(2)}</span>`; rel.appendChild(d); });
    rel.appendChild(el('div', 'h', 'Top trade partners')); c.trade_partners.forEach((t) => { const d = el('div', 'r'); d.innerHTML = `<span>${S.meta.countries.find((x) => x.iso3 === t.with)?.name || t.with}</span><span>${(t.share * 100).toFixed(0)}%</span>`; rel.appendChild(d); });
    if (c.sanctioned_by.length) { rel.appendChild(el('div', 'h', `Sanctioned by (${c.sanctioned_by.length})`)); const d = el('div'); c.sanctioned_by.slice(0, 20).forEach((s) => d.appendChild(el('span', 'tag', s))); rel.appendChild(d); }
    drawCountryCharts(h);
  }
  const ts = (dates) => dates.map((d) => Date.parse(d) / 1000);
  function uplotOpts(title, series, height, width, yfmt) {
    return { title: '', width, height, cursor: { drag: { x: false, y: false }, points: { size: 6 } }, legend: { live: true },
      scales: { x: { time: true } }, axes: [{ stroke: '#8a897f', grid: { stroke: '#2f2f2d', width: 1 }, ticks: { stroke: '#2f2f2d' }, font: '10px monospace' }, { stroke: '#8a897f', grid: { stroke: '#2f2f2d', width: 1 }, ticks: { stroke: '#2f2f2d' }, font: '10px monospace', size: 44, values: yfmt ? (u, vals) => vals.map(yfmt) : undefined }],
      series: [{ label: 'date', value: (u, v) => v == null ? '' : new Date(v * 1000).toISOString().slice(0, 10) }, ...series.map((s) => ({ label: s.label, stroke: s.color, width: 2, points: { show: false }, value: (u, v) => v == null ? '' : s.fmt ? s.fmt(v) : fmt.n(v, 2) }))] };
  }
  function makeOrUpdate(store, key, container, opts, data) {
    const w = container.clientWidth || 300;
    if (store[key]) { store[key].setSize({ width: w, height: opts.height }); store[key].setData(data); return; }
    container.innerHTML = ''; store[key] = new uPlot({ ...opts, width: w }, data, container);
  }
  function drawCountryCharts(h) {
    const x = ts(h.dates);
    makeOrUpdate(S.cCharts, 'gdp', $('#cc-gdp'), uplotOpts('', [{ label: 'GDP $bn', color: '#3987e5', fmt: (v) => fmt.tn(v) }], 110, 0, (v) => fmt.tn(v)), [x, h.gdp]);
    makeOrUpdate(S.cCharts, 'macro', $('#cc-macro'), uplotOpts('', [{ label: 'growth %', color: '#3987e5' }, { label: 'inflation %', color: '#d95926' }, { label: 'unemployment %', color: '#199e70' }, { label: 'rate %', color: '#c98500' }], 130, 0), [x, h.growth, h.inflation, h.unemployment, h.policy_rate]);
    makeOrUpdate(S.cCharts, 'social', $('#cc-social'), uplotOpts('', [{ label: 'stability', color: '#3987e5' }, { label: 'unrest', color: '#d95926' }, { label: 'war', color: '#e66767' }], 110, 0), [x, h.stability, h.unrest, h.war_intensity]);
  }

  // ---- global charts --------------------------------------------------------------------
  async function refreshHistory() {
    const h = await api('/api/history/global'); S.history = h; const x = ts(h.dates);
    const idx = (arr) => arr.map((v) => (v / arr[0]) * 100);
    const hgt = Math.max(90, $('#ch-comm').parentElement.clientHeight - 48);
    makeOrUpdate(S.charts, 'comm', $('#ch-comm'), uplotOpts('', [{ label: 'oil', color: '#3987e5', fmt: (v) => fmt.n(v, 0) }, { label: 'EU gas', color: '#d95926', fmt: (v) => fmt.n(v, 0) }, { label: 'wheat', color: '#199e70', fmt: (v) => fmt.n(v, 0) }, { label: 'gold', color: '#c98500', fmt: (v) => fmt.n(v, 0) }], hgt, 0, (v) => fmt.n(v, 0)), [x, idx(h.oil), idx(h.gas_eu), idx(h.wheat), idx(h.gold)]);
    makeOrUpdate(S.charts, 'macro', $('#ch-macro'), uplotOpts('', [{ label: 'growth', color: '#3987e5' }, { label: 'inflation', color: '#d95926' }], hgt, 0, (v) => fmt.n(v, 1)), [x, h.world_growth, h.world_inflation]);
    makeOrUpdate(S.charts, 'risk', $('#ch-risk'), uplotOpts('', [{ label: 'risk ×10', color: '#3987e5' }, { label: 'wars', color: '#e66767', fmt: (v) => fmt.n(v, 0) }], hgt, 0, (v) => fmt.n(v, 0)), [x, h.global_risk.map((v) => v * 10), h.active_wars]);
  }

  // ---- intervention panel ----------------------------------------------------------
  function buildIntervene() {
    const fill = (sel, def) => { const s = $(sel); s.innerHTML = ''; S.meta.countries.slice().sort((a, b) => a.name.localeCompare(b.name)).forEach((c) => { const o = el('option', '', c.name); o.value = c.iso3; s.appendChild(o); }); s.value = def; };
    fill('#iv-a', 'USA'); fill('#iv-b', 'CHN'); fill('#iv-c', 'FRA');
    const sh = $('#iv-shock'); S.meta.shocks.forEach((k) => { const o = el('option', '', k); o.value = k; sh.appendChild(o); });
    const fl = $('#iv-field'); ['inflation', 'growth', 'unemployment', 'policy_rate', 'debt_gdp', 'stability', 'unrest', 'regime', 'mil_spend_gdp', 'oil_prod'].forEach((k) => { const o = el('option', '', k); o.value = k; fl.appendChild(o); });
    const ch = $('#iv-chokes'); Object.entries(S.meta.chokepoints).forEach(([k, name]) => { const b = el('button', 'chk', name); b.dataset.k = k; b.onclick = () => intervene({ kind: 'chokepoint', key: k, closed: !S.state.chokepoints[k].closed }); ch.appendChild(b); });
    $('#iv-t').oninput = (e) => ($('#iv-tval').value = Number(e.target.value).toFixed(2));
    $('#iv-i').oninput = (e) => ($('#iv-ival').value = Number(e.target.value).toFixed(2));
    $('#iv-o').oninput = (e) => ($('#iv-oval').value = `${e.target.value}%`);
    $('#iv-set-t').onclick = () => intervene({ kind: 'set_tension', a: $('#iv-a').value, b: $('#iv-b').value, value: +$('#iv-t').value });
    $('#iv-war').onclick = () => intervene({ kind: 'declare_war', a: $('#iv-a').value, b: $('#iv-b').value, value: +$('#iv-i').value });
    $('#iv-sanction').onclick = () => intervene({ kind: 'sanction', a: $('#iv-a').value, b: $('#iv-b').value, value: 1 });
    $('#iv-nato').onclick = () => { intervene({ kind: 'alliance_sanction', alliance: 'NATO', b: $('#iv-b').value, value: 1 }); intervene({ kind: 'alliance_sanction', alliance: 'EU', b: $('#iv-b').value, value: 1 }); };
    $('#iv-oil').onclick = () => intervene({ kind: 'oil_shock', value: +$('#iv-o').value / 100 });
    $('#iv-doshock').onclick = () => intervene({ kind: 'shock', a: $('#iv-c').value, shock: $('#iv-shock').value, value: 1 });
    $('#iv-setvar').onclick = () => intervene({ kind: 'set_variable', a: $('#iv-c').value, field: $('#iv-field').value, value: +$('#iv-val').value });
  }

  // ---- data tab -------------------------------------------------------------------
  let dataPoll = null;
  async function refreshData() {
    const d = await api('/api/data');
    const c = d.cache; const st = $('#data-status');
    if (!c.exists) st.innerHTML = '<b>No live data yet.</b> The world is running on the bundled seed figures. Press <i>Sync now</i> to pull today\'s data.';
    else st.innerHTML = `Cache from <b>${c.date}</b> (${c.age_days} days old) · ${c.countries} countries · world currently ${d.world_live_date ? 'running on live data from ' + d.world_live_date : 'on bundled data — press <i>Restart world with live data</i>'}`;
    const ul = $('#sources'); ul.innerHTML = '';
    const logBy = Object.fromEntries((d.sync.log || []).map((r) => [r.source, r]));
    d.sources.forEach((s) => {
      const r = logBy[s.name]; const prev = c.sources && c.sources[s.name];
      const status = r ? r.status : prev ? (prev.ok ? 'ok' : 'failed') : '';
      const li = el('li', status);
      const chk = el('label', 'src'); const cb = el('input'); cb.type = 'checkbox'; cb.checked = true; cb.dataset.src = s.name; chk.appendChild(cb);
      li.appendChild(chk); li.appendChild(el('span', 'n', s.name));
      li.appendChild(el('span', 'st', r ? r.detail : prev ? (prev.ok ? `${prev.countries || ''} ok ${prev.seconds}s` : 'failed: ' + (prev.error || 'no data')) : 'never run'));
      li.appendChild(el('span', 'd', s.description));
      li.insertBefore(el('span', 'dot'), li.querySelector('.n'));
      ul.appendChild(li);
    });
    $('#btn-sync').disabled = d.sync.running; $('#btn-sync').textContent = d.sync.running ? 'Syncing…' : 'Sync now';
    if (d.sync.running && !dataPoll) dataPoll = setInterval(refreshData, 1500);
    if (!d.sync.running && dataPoll) { clearInterval(dataPoll); dataPoll = null; }
    const w = S.state && S.state.world;
    if (w) $('#climate-status').textContent = `ENSO: ${w.enso_state} (ONI ${w.enso >= 0 ? '+' : ''}${w.enso}). Drought index per country is on the map (chip "Drought").`;
  }
  function bindData() {
    $('#btn-sync').onclick = async () => { const srcs = [...document.querySelectorAll('#sources input[type=checkbox]')].filter((c) => c.checked).map((c) => c.dataset.src); await api('/api/sync', { sources: srcs.length ? srcs : null }).catch((e) => toast(e.message)); refreshData(); };
    $('#btn-apply').onclick = async () => { if (confirm('Restart the world from the live data cache? Current history is lost unless saved.')) { S.events = []; S.seenEventKey.clear(); Object.values(S.charts).forEach((c) => c.destroy()); S.charts = {}; await api('/api/apply_live', {}).catch((e) => toast(e.message)); refreshHistory(); refreshData(); } };
    document.querySelector('.tabs button[data-tab=data]').addEventListener('click', refreshData);
  }

  // ---- controls --------------------------------------------------------------------
  function bindControls() {
    $('#btn-play').onclick = () => control(S.running ? 'pause' : 'play');
    $('#btn-step').onclick = () => control('step', { days: 1 });
    $('#btn-step-m').onclick = () => control('step', { days: 30 });
    $('#speed').onchange = (e) => control('speed', { speed: +e.target.value });
    $('#btn-runto').onclick = () => { const y = +$('#runto').value; if (y) control('run_to', { until: `${y}-01-01` }); };
    $('#btn-reset').onclick = () => { if (confirm('Start a new world with this seed? Current history is lost unless saved.')) { S.events = []; S.seenEventKey.clear(); Object.values(S.charts).forEach((c) => c.destroy()); S.charts = {}; control('reset', { seed: +$('#seed').value }).then(refreshHistory); } };
    $('#btn-save').onclick = async () => { const name = prompt('Save as', 'world'); if (name) { await api('/api/save', { name }); toast(`saved ${name}`); } };
    $('#btn-load').onclick = async () => { const list = await api('/api/saves'); const name = prompt(`Load which? available: ${list.join(', ') || '(none)'}`, list[0] || ''); if (name) { S.events = []; S.seenEventKey.clear(); await api('/api/load', { name }).catch((e) => toast(e.message)); refreshHistory(); } };
    document.querySelectorAll('.tabs button').forEach((b) => (b.onclick = () => { document.querySelectorAll('.tabs button').forEach((x) => x.classList.toggle('active', x === b)); document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.id === `tab-${b.dataset.tab}`)); }));
    window.addEventListener('keydown', (e) => { if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return; if (e.code === 'Space') { e.preventDefault(); control(S.running ? 'pause' : 'play'); } else if (e.key === '.') control('step', { days: 1 }); else if (e.key === '>') control('step', { days: 30 }); else if (e.key === 'Escape') { S.selected = null; renderMap(); } });
    window.addEventListener('resize', () => { Object.values(S.charts).forEach((c) => c.setSize({ width: c.root.parentElement.clientWidth, height: c.height })); });
  }

  // ---- boot --------------------------------------------------------------------
  (async () => {
    const [meta, geo, st] = await Promise.all([api('/api/meta'), api('/api/geo'), api('/api/state')]);
    S.meta = meta; S.geo = geo;
    buildMap(); buildIntervene(); bindControls(); bindData();
    onFrame({ state: st.state, running: st.running, speed: st.speed, events: await api('/api/events?limit=80') });
    refreshHistory();
    connect();
  })().catch((e) => { console.error(e); document.body.insertAdjacentHTML('afterbegin', `<pre style="color:#ffb3b3;padding:12px">${e.stack || e}</pre>`); });
})();
