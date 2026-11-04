(() => {
  'use strict';

  const $ = (s, el = document) => el.querySelector(s);
  const NF = {};
  const fmt = (v, d = 0) => (NF[d] ||= new Intl.NumberFormat('de-DE', {
    minimumFractionDigits: d, maximumFractionDigits: d })).format(v || 0);
  const pad2 = (n) => String(n).padStart(2, '0');
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const DAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];
  const CHEV_L = '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const CHEV_R = '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5l7 7-7 7" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  // ---------------------------------------------------------------- Format
  function clock(s) {
    s = Math.max(0, Math.round(s || 0));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return h ? `${h}:${pad2(m)}:${pad2(r)}` : `${m}:${pad2(r)}`;
  }
  function hoursMin(s) {
    const m = Math.round((s || 0) / 60);
    if (m < 60) return `${m}<small> Min.</small>`;
    const h = Math.floor(m / 60), r = m % 60;
    return r ? `${h}<small> Std. </small>${r}<small> Min.</small>` : `${h}<small> Std.</small>`;
  }
  function pace(sPerKm) {
    if (!isFinite(sPerKm) || sPerKm <= 0) return '–';
    const s = Math.round(sPerKm);
    return `${Math.floor(s / 60)}'${pad2(s % 60)}"`;
  }
  const time = (ts) => new Date(ts * 1000).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  function dayStart(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
  function weekStart(d) {
    const x = dayStart(d);
    x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
    return x;
  }
  function relDay(ts) {
    const d = dayStart(new Date(ts * 1000)), today = dayStart(new Date());
    const diff = Math.round((today - d) / 86400000);
    if (diff === 0) return 'Heute';
    if (diff === 1) return 'Gestern';
    return d.toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'short' });
  }
  function weekRange(ws) {
    const we = new Date(ws); we.setDate(we.getDate() + 6);
    const sameMonth = ws.getMonth() === we.getMonth();
    const a = ws.toLocaleDateString('de-DE', sameMonth ? { day: 'numeric' } : { day: 'numeric', month: 'short' });
    const b = we.toLocaleDateString('de-DE', { day: 'numeric', month: 'short' });
    return sameMonth ? `${a}.–${b}` : `${a} – ${b}`;
  }

  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json();
  }

  // -------------------------------------------------------------- Anzeige
  const display = $('#display');
  let lastActiveId = null;
  let liveTimer = null;

  function setDisplay(cls, status, speed) {
    display.className = `display ${cls}`;
    $('#d-status').innerHTML = `<span class="dot"></span><span>${esc(status)}</span>`;
    $('#d-speed').textContent = speed;
  }

  function renderLive(d) {
    const a = d.active, p = d.pad || {};
    const sp = (p.speed ?? null) === null ? '-.-' : Number(p.speed).toFixed(1);
    const st = p.state;
    $('#d-stats').hidden = !a;
    if (!d.ha_connected) {
      setDisplay('offline', 'Keine Verbindung zu Home Assistant', '-.-');
    } else if (a && a.phase === 'lost') {
      setDisplay('offline', 'Verbindung zum Band unterbrochen', '-.-');
    } else if (!st || st === 'disconnected') {
      setDisplay('offline', 'Laufband nicht verbunden', '-.-');
    } else if (a && a.phase === 'ending') {
      setDisplay('idle', 'Training wird gespeichert …', sp);
    } else if (st === 'running') {
      setDisplay('running', 'Läuft', sp);
    } else if (st === 'paused') {
      setDisplay('paused', 'Pausiert', sp);
    } else if (st === 'countdown') {
      setDisplay('running', 'Startet …', sp);
    } else {
      setDisplay('idle', 'Bereit', sp);
    }
    if (a) {
      $('#d-time').textContent = clock(a.duration_s);
      $('#d-dist').textContent = `${fmt(a.distance_km, 2)} km`;
      $('#d-kcal').textContent = fmt(a.calories);
    }
    drawTrace(a ? a.recent : [], d.now);
    renderControls(d);
  }

  // ------------------------------------------------------------- Bedienung
  const ctl = {
    box: $('#controls'), speed: $('#ctl-speed'), target: $('#ctl-target'), msg: $('#ctl-msg'),
    start: $('#c-start'), pause: $('#c-pause'), stop: $('#c-stop'),
  };
  let maxSpeed = 6, padSpeed = 0, target = null, targetTimer = null, busy = false;

  function renderControls(d) {
    const st = d.pad?.state, a = d.active;
    maxSpeed = d.max_control_speed || 6;
    padSpeed = Number(d.pad?.speed) || 0;
    const usable = d.ha_connected && st && st !== 'disconnected' && !(a && ['lost', 'ending'].includes(a.phase));
    ctl.box.hidden = !usable;
    if (!usable) return;
    ctl.start.hidden = !['stopped', 'paused'].includes(st);
    ctl.start.querySelector('.lbl').textContent = st === 'paused' ? 'Zum Fortsetzen halten' : 'Zum Starten halten';
    ctl.pause.hidden = st !== 'running';
    ctl.stop.hidden = !['running', 'paused', 'countdown'].includes(st);
    ctl.speed.hidden = st !== 'running';
    if (st !== 'running') target = null;
    if (target === null) showTarget(padSpeed);
  }

  function showTarget(v) {
    ctl.target.innerHTML = `${fmt(v, 1)}<small> km/h</small>`;
  }

  async function send(action, value) {
    if (busy && action !== 'stop') return;
    busy = true;
    ctl.msg.textContent = '';
    try {
      const r = await fetch('api/control', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, value }),
      });
      if (!r.ok) throw new Error(await r.text());
    } catch (e) {
      ctl.msg.textContent = e.message || 'Befehl fehlgeschlagen';
    } finally {
      busy = false;
      setTimeout(pollLive, 400);
    }
  }

  ctl.stop.addEventListener('click', () => { target = null; send('stop'); });
  ctl.pause.addEventListener('click', () => send('pause'));

  // Start nur durch Halten (0,8 s) – ein versehentlicher Tipp startet das Band nicht
  let holdTimer = null;
  const holdStart = (ev) => {
    if (ev.type === 'keydown' && ev.key !== 'Enter' && ev.key !== ' ') return;
    if (ev.repeat || holdTimer) return;
    ev.preventDefault();
    ctl.start.classList.add('holding');
    holdTimer = setTimeout(() => { holdEnd(); send('start'); }, 800);
  };
  const holdEnd = () => {
    clearTimeout(holdTimer); holdTimer = null;
    ctl.start.classList.remove('holding');
  };
  ctl.start.addEventListener('pointerdown', holdStart);
  ctl.start.addEventListener('keydown', holdStart);
  ['pointerup', 'pointerleave', 'pointercancel', 'keyup', 'blur'].forEach((e) => ctl.start.addEventListener(e, holdEnd));
  ctl.start.addEventListener('contextmenu', (e) => e.preventDefault());

  // Tempo: Tipps sammeln, nach kurzer Ruhe einmal senden
  function setTarget(v) {
    target = Math.round(Math.min(maxSpeed, Math.max(0.5, v)) * 10) / 10;
    showTarget(target);
    clearTimeout(targetTimer);
    targetTimer = setTimeout(async () => {
      await send('speed', target);
      setTimeout(() => { target = null; }, 2500);   // danach wieder Bandwert anzeigen
    }, 450);
  }
  ctl.speed.querySelectorAll('[data-step]').forEach((b) => b.addEventListener('click', () =>
    setTarget((target ?? padSpeed) + Number(b.dataset.step))));
  ctl.speed.querySelectorAll('[data-preset]').forEach((b) => b.addEventListener('click', () =>
    setTarget(Number(b.dataset.preset))));

  function drawTrace(pts, now) {
    const svg = $('#d-trace');
    const empty = !pts || pts.length < 2;
    svg.toggleAttribute('hidden', empty);   // SVG kennt .hidden nicht als Property
    if (empty) { svg.innerHTML = ''; return; }
    const span = 180, top = 7;
    svg.setAttribute('viewBox', `0 0 ${span} ${top}`);
    const x = (t) => span - Math.min(span, Math.max(0, now - t));
    const y = (v) => top - Math.min(top, v || 0);
    let line = '';
    pts.forEach(([t, v], i) => { line += `${i ? 'L' : 'M'}${x(t).toFixed(2)},${y(v).toFixed(3)}`; });
    const area = `${line}L${x(pts[pts.length - 1][0]).toFixed(2)},${top}L${x(pts[0][0]).toFixed(2)},${top}Z`;
    svg.innerHTML = `<path class="a" d="${area}"/><path class="l" d="${line}"/>`;
  }

  async function pollLive() {
    clearTimeout(liveTimer);
    let next = 8000;
    try {
      const d = await api('api/live');
      renderLive(d);
      const aid = d.active ? d.active.id : null;
      if (lastActiveId && !aid) {          // Training gerade gespeichert
        cache.list = null;
        if (!location.hash.startsWith('#/w/')) route();
      }
      lastActiveId = aid;
      if (aid || ['running', 'countdown', 'paused'].includes(d.pad?.state)) next = 2000;
    } catch (e) {
      setDisplay('offline', 'Laufband-Log nicht erreichbar', '-.-');
      ctl.box.hidden = true;
    }
    liveTimer = setTimeout(pollLive, next);
  }

  // ------------------------------------------------------------- Übersicht
  const cache = { list: null };
  let weekOffset = 0;

  async function loadList() {
    if (!cache.list) cache.list = await api('api/workouts');
    return cache.list;
  }

  function sparkPath(vals, w = 84, h = 28) {
    if (!vals || vals.length < 2) return '';
    const max = Math.max(6, ...vals), min = 0;
    return vals.map((v, i) => {
      const x = (i / (vals.length - 1)) * w;
      const y = h - 2 - ((v - min) / (max - min)) * (h - 4);
      return `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join('');
  }

  function renderWeek(list) {
    const now = new Date();
    const ws = weekStart(now); ws.setDate(ws.getDate() + weekOffset * 7);
    const we = new Date(ws); we.setDate(we.getDate() + 7);
    const days = Array.from({ length: 7 }, () => 0);
    let dist = 0, dur = 0, kcal = 0, n = 0;
    for (const w of list) {
      const d = new Date(w.started_at * 1000);
      if (d < ws || d >= we) continue;
      days[(d.getDay() + 6) % 7] += w.distance_km;
      dist += w.distance_km; dur += w.duration_s; kcal += w.calories; n++;
    }
    const max = Math.max(...days, 0.5);
    const todayIdx = weekOffset === 0 ? (now.getDay() + 6) % 7 : -1;
    const title = weekOffset === 0 ? 'Diese Woche' : weekOffset === -1 ? 'Letzte Woche' : 'Woche';
    const bars = days.map((v) => `
      <div class="bar"><span class="val">${v > 0 ? fmt(v, 1) : ''}</span>
        <div class="col ${v > 0 ? '' : 'zero'}" style="height:${v > 0 ? Math.max(4, (v / max) * 92) : 3}${v > 0 ? '%' : 'px'}"></div></div>`).join('');
    const labels = DAYS.map((d, i) => `<span class="${i === todayIdx ? 'today' : ''}">${d}</span>`).join('');
    return `
      <section class="section">
        <div class="section-head">
          <h2>${title}</h2>
          <div class="week-nav">
            <button class="icon-btn" data-week="-1" aria-label="Vorherige Woche">${CHEV_L}</button>
            <span class="num">${weekRange(ws)}</span>
            <button class="icon-btn" data-week="1" aria-label="Nächste Woche" ${weekOffset >= 0 ? 'disabled' : ''}>${CHEV_R}</button>
          </div>
        </div>
        <div class="group week">
          <dl class="week-totals">
            <div><dt>Strecke</dt><dd class="c-dist">${fmt(dist, 1)}<small> km</small></dd></div>
            <div><dt>Trainingszeit</dt><dd class="c-time">${hoursMin(dur)}</dd></div>
            <div><dt>Kalorien</dt><dd class="c-kcal">${fmt(kcal)}<small> kcal</small></dd></div>
            <div><dt>Workouts</dt><dd>${n}</dd></div>
          </dl>
          <div class="bars" role="img" aria-label="Strecke pro Tag in Kilometern: ${days.map((v, i) => `${DAYS[i]} ${fmt(v, 1)}`).join(', ')}">${bars}</div>
          <div class="bar-labels" aria-hidden="true">${labels}</div>
        </div>
      </section>`;
  }

  function renderRows(list) {
    if (!list.length) {
      return `<section class="section"><div class="group empty">
        <p>Noch keine Workouts gespeichert.</p>
        <p>Starte das Laufband. Jedes Training ab einer Minute wird automatisch aufgezeichnet und erscheint hier.</p>
      </div></section>`;
    }
    const groups = new Map();
    for (const w of list) {
      const key = new Date(w.started_at * 1000).toLocaleDateString('de-DE', { month: 'long', year: 'numeric' });
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(w);
    }
    let html = '';
    for (const [month, ws] of groups) {
      html += `<section class="month"><h3>${month}</h3><div class="group">`;
      for (const w of ws) {
        html += `<a class="row" href="#/w/${w.id}">
          <div><div class="when">${relDay(w.started_at)}, ${time(w.started_at)}</div>
            <div class="meta">Dauer ${clock(w.duration_s)}, Ø ${fmt(w.avg_speed, 1)} km/h</div></div>
          <div class="big">${fmt(w.distance_km, 2)}<small> km</small></div>
          <svg viewBox="0 0 84 28" aria-hidden="true"><path d="${sparkPath(w.spark)}"/></svg>
        </a>`;
      }
      html += '</div></section>';
    }
    return html;
  }

  async function renderOverview(view) {
    let list;
    try {
      list = await loadList();
    } catch (e) {
      view.innerHTML = errorBanner(e);
      return;
    }
    view.innerHTML = renderWeek(list) + renderRows(list);
    view.querySelectorAll('[data-week]').forEach((b) => b.addEventListener('click', () => {
      weekOffset = Math.min(0, weekOffset + Number(b.dataset.week));
      renderOverview(view);
    }));
  }

  function errorBanner(e) {
    return `<div class="error-banner">Daten konnten nicht geladen werden (${esc(e.message)}).
      <button class="btn" onclick="location.reload()">Neu laden</button></div>`;
  }

  // --------------------------------------------------------------- Diagramm
  function niceStep(raw) {
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    const f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  }

  let chartSeq = 0;
  function makeChart(el, o) {
    const id = `c${++chartSeq}`;
    const H = o.height || 190;
    const P = { l: 34, r: 10, t: 14, b: 24 };
    const pts = o.points;
    const xs = pts.map((p) => p[0]);
    const tip = document.createElement('div');
    tip.className = 'tip';
    tip.hidden = true;
    let geo = null;
    let hoverX = null;

    function render() {
      const W = Math.max(240, el.clientWidth);
      const vals = pts.map((p) => p[1]).filter((v) => v != null);
      const yMaxRaw = Math.max(o.yFloor || 1, ...vals);
      const step = niceStep(yMaxRaw / 3);
      const yTop = Math.ceil((yMaxRaw * 1.04) / step) * step;
      const xMax = Math.max(1, o.xMax);
      const X = (x) => P.l + (x / xMax) * (W - P.l - P.r);
      const Y = (y) => P.t + (1 - y / yTop) * (H - P.t - P.b);
      geo = { W, X, Y, xMax };

      let grid = '', axis = '';
      for (let v = 0; v <= yTop + 1e-9; v += step) {
        grid += `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(v)}" y2="${Y(v)}"/>`;
        axis += `<text x="${P.l - 6}" y="${Y(v) + 4}" text-anchor="end">${fmt(v, step < 1 ? 1 : 0)}</text>`;
      }
      const xStep = [60, 120, 300, 600, 900, 1200, 1800, 3600, 7200].find((s) => xMax / s <= 6) || 7200;
      for (let x = 0; x <= xMax + 1e-9; x += xStep) {
        const anchor = x === 0 ? 'start' : 'middle';
        if (X(x) > W - P.r - 14 && x !== 0) continue;
        axis += `<text x="${X(x)}" y="${H - 6}" text-anchor="${anchor}">${clock(x)}</text>`;
      }

      let bands = '';
      for (const b of o.bands || []) {
        const x1 = X(Math.max(0, b.s)), x2 = X(Math.min(xMax, b.e));
        if (x2 - x1 < 0.5) continue;
        if (b.kind === 'pause') {
          bands += `<rect x="${x1}" y="${P.t}" width="${x2 - x1}" height="${H - P.t - P.b}" fill="url(#${id}h)"/>`;
        } else {
          bands += `<rect x="${x1}" y="${P.t}" width="${x2 - x1}" height="${H - P.t - P.b}" style="fill:var(--hatch);opacity:.5"/>`
            + `<line x1="${x1}" x2="${x1}" y1="${P.t}" y2="${H - P.b}" style="stroke:var(--muted)" stroke-dasharray="3 3"/>`
            + `<line x1="${x2}" x2="${x2}" y1="${P.t}" y2="${H - P.b}" style="stroke:var(--muted)" stroke-dasharray="3 3"/>`;
        }
      }

      let line = '', area = '', seg = [];
      const flush = () => {
        if (seg.length > 1) {
          const d = seg.map((p, i) => `${i ? 'L' : 'M'}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('');
          line += d;
          area += `${d}L${X(seg[seg.length - 1][0]).toFixed(1)},${Y(0)}L${X(seg[0][0]).toFixed(1)},${Y(0)}Z`;
        }
        seg = [];
      };
      for (const p of pts) { if (p[1] == null) flush(); else seg.push(p); }
      flush();

      let avg = '';
      if (o.avg) {
        avg = `<g class="avg"><line x1="${P.l}" x2="${W - P.r}" y1="${Y(o.avg)}" y2="${Y(o.avg)}"/>
          <text x="${P.l + 6}" y="${Y(o.avg) - 6}" text-anchor="start">Ø ${fmt(o.avg, 1)}</text></g>`;
      }

      el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(o.label)}">
        <defs><pattern id="${id}h" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="2.2" height="6" style="fill:var(--hatch)"/></pattern></defs>
        <g class="grid">${grid}</g>${bands}
        <path d="${area}" style="fill:${o.color};opacity:.16"/>
        <path d="${line}" style="fill:none;stroke:${o.color};stroke-width:2;stroke-linejoin:round;stroke-linecap:round"/>
        ${avg}<g class="axis">${axis}</g>
        <line class="cross" x1="0" x2="0" y1="${P.t}" y2="${H - P.b}" visibility="hidden"/>
        <circle class="pt" r="4" style="fill:${o.color};stroke:var(--surface);stroke-width:2" visibility="hidden"/>
      </svg>`;
      el.appendChild(tip);
      if (hoverX != null) hover(hoverX);
    }

    function nearest(x) {
      let lo = 0, hi = xs.length - 1;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (xs[m] < x) lo = m; else hi = m; }
      let i = Math.abs(xs[lo] - x) <= Math.abs(xs[hi] - x) ? lo : hi;
      for (let k = 0; k < 40 && pts[i] && pts[i][1] == null; k++) i = i > 0 ? i - 1 : i + 1;
      return pts[i] && pts[i][1] != null ? pts[i] : null;
    }

    function hover(x) {
      hoverX = x;
      const cross = el.querySelector('.cross'), dot = el.querySelector('.pt');
      if (x == null || !geo) { cross?.setAttribute('visibility', 'hidden'); dot?.setAttribute('visibility', 'hidden'); tip.hidden = true; return; }
      const p = nearest(x);
      if (!p) return hover(null);
      const px = geo.X(p[0]), py = geo.Y(p[1]);
      cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.setAttribute('visibility', 'visible');
      dot.setAttribute('cx', px); dot.setAttribute('cy', py); dot.setAttribute('visibility', 'visible');
      tip.innerHTML = o.tip(p);
      tip.hidden = false;
      const half = tip.offsetWidth / 2;
      tip.style.left = `${Math.min(geo.W - half, Math.max(half, px))}px`;
      const above = py - tip.offsetHeight - 10;
      tip.style.top = `${above >= 0 ? above : py + 12}px`;   // kein Platz oben -> unter den Punkt
    }

    function xFromEvent(ev) {
      const r = el.getBoundingClientRect();
      const px = ev.clientX - r.left;
      return Math.max(0, Math.min(geo.xMax, ((px - P.l) / (geo.W - P.l - P.r)) * geo.xMax));
    }
    el.addEventListener('pointermove', (ev) => o.onHover(xFromEvent(ev)));
    el.addEventListener('pointerdown', (ev) => o.onHover(xFromEvent(ev)));
    el.addEventListener('pointerleave', () => o.onHover(null));
    return { render, hover };
  }

  // ---------------------------------------------------------------- Detail
  let charts = [];
  let resizeObs = null;

  async function renderDetail(view, wid) {
    let w;
    try {
      w = await api(`api/workouts/${wid}`);
    } catch (e) {
      view.innerHTML = `<a class="back" href="#/">${CHEV_L}Alle Workouts</a>${errorBanner(e)}`;
      return;
    }
    const start = new Date(w.started_at * 1000);
    const dateStr = start.toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    const pace_s = w.distance_km > 0 ? w.duration_s / w.distance_km : 0;
    const wall = (w.ended_at || w.started_at) - w.started_at;
    const lost = (w.intervals || []).filter((i) => i.kind === 'lost');
    const notes = {
      connection_lost: 'Die Verbindung zum Band ist abgerissen. Gespeichert ist der letzte bekannte Stand.',
      stopped_while_lost: 'Das Training endete, während das Band nicht verbunden war. Gespeichert ist der letzte bekannte Stand.',
      pause_timeout: 'Nach langer Pause automatisch beendet.',
    };

    const metric = (label, value, cls) => `<div class="metric"><dt>${label}</dt><dd class="${cls}">${value}</dd></div>`;
    let metrics = metric('Trainingszeit', clock(w.duration_s), 'c-time')
      + metric('Strecke', `${fmt(w.distance_km, 2)}<small> km</small>`, 'c-dist')
      + metric('Ø Tempo', `${fmt(w.avg_speed, 1)}<small> km/h</small>`, 'c-speed')
      + metric('Ø Pace', `${pace(pace_s)}<small> /km</small>`, 'c-speed')
      + metric('Höchsttempo', `${fmt(w.max_speed, 1)}<small> km/h</small>`, 'c-speed')
      + metric('Kalorien', `${fmt(w.calories)}<small> kcal</small>`, 'c-kcal');
    if (w.steps > 0) metrics += metric('Schritte', fmt(w.steps), 'c-steps');
    if (w.pause_count > 0) metrics += metric(w.pause_count === 1 ? 'Pause' : `Pausen (${w.pause_count})`, clock(w.pause_s), 'c-muted');
    if (wall - w.duration_s > 30) metrics += metric('Gesamtdauer', clock(wall), 'c-muted');

    const maxSplit = Math.max(...(w.splits || []).map((s) => s.speed), 0.1);
    const splitRows = (w.splits || []).map((s) => {
      const partial = s.dist < 0.999;
      return `<tr class="${partial ? 'partial' : ''}">
        <td class="km">${partial ? `${fmt(s.dist, 2)}` : s.km}</td>
        <td class="t">${clock(s.time_s)}</td>
        <td class="p">${pace(s.pace_s)} /km</td>
        <td class="barcell"><div class="sbar" style="width:${(s.speed / maxSplit) * 100}%" title="${fmt(s.speed, 1)} km/h"></div></td>
      </tr>`;
    }).join('');

    const hasPause = (w.intervals || []).some((i) => i.kind === 'pause');
    const legend = (hasPause || lost.length) ? `<div class="legend">
        ${hasPause ? '<span class="pause"><i></i>Pause</span>' : ''}
        ${lost.length ? '<span class="lost"><i></i>Keine Verbindung</span>' : ''}</div>` : '';

    view.innerHTML = `
      <a class="back" href="#/">${CHEV_L}Alle Workouts</a>
      <header class="detail-head">
        <h1>Gehen auf dem Laufband</h1>
        <p class="hero">${fmt(w.distance_km, 2)}<small> km</small></p>
        <p class="when">${dateStr}, ${time(w.started_at)}–${time(w.ended_at || w.started_at)}</p>
        ${notes[w.end_reason] ? `<p class="note">${notes[w.end_reason]}</p>` : ''}
      </header>
      <section class="section"><dl class="group metrics">${metrics}</dl></section>
      <section class="section group chart-card">
        <div class="chart-title"><h3>Geschwindigkeit</h3><span class="sum c-speed">Ø ${fmt(w.avg_speed, 1)} km/h</span></div>
        <div class="chart" id="ch-speed"></div>${legend}
      </section>
      <section class="section group chart-card">
        <div class="chart-title"><h3>Strecke</h3><span class="sum c-dist">${fmt(w.distance_km, 2)} km</span></div>
        <div class="chart" id="ch-dist"></div>
      </section>
      ${splitRows ? `<section class="section">
        <div class="section-head"><h2>Kilometer</h2></div>
        <div class="group"><table class="splits">
          <thead><tr><th>Km</th><th>Zeit</th><th>Pace</th><th class="barcell">Tempo</th></tr></thead>
          <tbody>${splitRows}</tbody></table></div></section>` : ''}
      <div class="actions">
        <a class="btn" href="api/workouts/${w.id}/csv" download>CSV exportieren</a>
        <button class="btn danger" id="del">Workout löschen</button>
        <button class="btn" id="del-cancel" hidden>Abbrechen</button>
      </div>`;

    // Messpunkte -> Serien; Lücken > 15 s (Verbindung weg) unterbrechen die Linie
    const speedPts = [], distPts = [];
    let prevT = null;
    for (const s of w.samples) {
      const x = s[0] - w.started_at;
      if (prevT !== null && s[0] - prevT > 15) {
        speedPts.push([x - 0.01, null]); distPts.push([x - 0.01, null]);
      }
      speedPts.push([x, s[1]]); distPts.push([x, s[2]]);
      prevT = s[0];
    }
    const xMax = Math.max(wall, speedPts.length ? speedPts[speedPts.length - 1][0] : 0);
    const bands = (w.intervals || []).map((i) => ({ s: i.s - w.started_at, e: (i.e || i.s) - w.started_at, kind: i.kind }));
    const sync = (x) => charts.forEach((c) => c.hover(x));
    const when = (x) => `<span class="c-muted">${clock(x)} ${x >= 3600 ? 'Std.' : 'Min.'}, ${time(w.started_at + x)} Uhr</span>`;

    charts = [
      makeChart($('#ch-speed'), {
        points: speedPts, xMax, bands, avg: w.avg_speed, yFloor: 4, color: 'var(--speed)',
        label: `Geschwindigkeit über die Zeit, Durchschnitt ${fmt(w.avg_speed, 1)} km/h, maximal ${fmt(w.max_speed, 1)} km/h`,
        tip: (p) => `<b class="c-speed">${fmt(p[1], 1)} km/h</b><br>${when(p[0])}`, onHover: sync,
      }),
      makeChart($('#ch-dist'), {
        points: distPts, xMax, bands, yFloor: 0.5, color: 'var(--led)', height: 150,
        label: `Zurückgelegte Strecke über die Zeit, gesamt ${fmt(w.distance_km, 2)} km`,
        tip: (p) => `<b class="c-dist">${fmt(p[1], 2)} km</b><br>${when(p[0])}`, onHover: sync,
      }),
    ];
    charts.forEach((c) => c.render());
    resizeObs?.disconnect();
    resizeObs = new ResizeObserver(() => charts.forEach((c) => c.render()));
    resizeObs.observe(view);

    const del = $('#del'), cancel = $('#del-cancel');
    del.addEventListener('click', async () => {
      if (!del.classList.contains('armed')) {
        del.classList.add('armed'); del.textContent = 'Endgültig löschen'; cancel.hidden = false;
        return;
      }
      del.disabled = true;
      try {
        await api(`api/workouts/${w.id}`, { method: 'DELETE' });
        cache.list = null;
        location.hash = '#/';
      } catch (e) {
        del.disabled = false;
        view.insertAdjacentHTML('afterbegin', errorBanner(e));
      }
    });
    cancel.addEventListener('click', () => {
      del.classList.remove('armed'); del.textContent = 'Workout löschen'; cancel.hidden = true;
    });
  }

  // ---------------------------------------------------------------- Router
  async function route() {
    const view = $('#view');
    resizeObs?.disconnect();
    charts = [];
    const m = location.hash.match(/^#\/w\/(\d+)/);
    if (m) {
      await renderDetail(view, m[1]);
      window.scrollTo(0, 0);
    } else {
      await renderOverview(view);
    }
  }

  window.addEventListener('hashchange', route);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) pollLive(); });
  route();
  pollLive();
})();
