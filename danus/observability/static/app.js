/* Danus dashboard client. Overview / Fact Graph (echarts DAG) / Global Memory
   (per-channel). Read-only; polls the FastAPI app in app.py. */
'use strict';
const $ = (s) => document.querySelector(s);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const esc = (s) => (s == null ? '' : String(s));

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(path + ' ' + r.status);
  return r.json();
}
function connError(on) { const b = $('#conn-banner'); if (b) b.hidden = !on; }

// ---- markdown + math ----------------------------------------------------- //
// elaboration / master_guidance / pro replies are markdown with LaTeX. Render
// markdown, but PROTECT math spans first so markdown-it doesn't mangle _ * { }.
let _md = null;
function md() {
  if (!_md && window.markdownit) _md = window.markdownit({ html: false, linkify: true, breaks: false });
  return _md;
}
function mdmath(node, text) {
  text = esc(text);
  node.classList.add('md');
  const m = md();
  const hasKatex = !!window.katex;
  const store = [];
  const stash = (tex, disp) => { store.push({ tex, disp }); return `@@MATH${store.length - 1}@@`; };
  let t = text;
  t = t.replace(/\\\[([\s\S]+?)\\\]/g, (_, x) => stash(x, true));
  t = t.replace(/\$\$([\s\S]+?)\$\$/g, (_, x) => stash(x, true));
  t = t.replace(/\\\(([\s\S]+?)\\\)/g, (_, x) => stash(x, false));
  t = t.replace(/\$([^\n$]+?)\$/g, (_, x) => stash(x, false));
  let html = m ? m.render(t) : t.replace(/\n/g, '<br>');
  html = html.replace(/@@MATH(\d+)@@/g, (_, i) => {
    const { tex, disp } = store[i];
    if (!hasKatex) return tex;
    try { return katex.renderToString(tex, { displayMode: disp, throwOnError: false }); }
    catch (e) { return esc(tex); }
  });
  node.innerHTML = html;
}

// ---- tabs ---------------------------------------------------------------- //
function switchTab(name) {
  document.querySelectorAll('.nav-link').forEach((a) => a.classList.toggle('active', a.dataset.tab === name));
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.id === 'tab-' + name));
  if (name === 'overview') loadOverview();
  if (name === 'graph') loadGraph();
  if (name === 'memory') loadMemory();
  if (name === 'graph' && graphChart) setTimeout(() => graphChart.resize(), 50);
}
document.querySelectorAll('.nav-link').forEach((a) => (a.onclick = () => switchTab(a.dataset.tab)));

// ---- overview ------------------------------------------------------------ //
function bars(container, obj, colorFn) {
  container.innerHTML = '';
  const entries = Object.entries(obj).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map((e) => e[1]));
  for (const [k, v] of entries) {
    const row = el('div', 'bar-row');
    row.appendChild(el('div', 'bar-label', k));
    const track = el('div', 'bar-track');
    const fill = el('div', 'bar-fill');
    fill.style.width = (v / max * 100).toFixed(1) + '%';
    if (colorFn) fill.style.background = colorFn(k);
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el('div', 'bar-val', String(v)));
    container.appendChild(row);
  }
}
async function loadOverview() {
  try {
    const d = await api('/api/overview');
    connError(false);
    $('#project-badge').textContent = d.project || '';
    $('#refresh-note').textContent = 'updated ' + new Date(d.updated_at * 1000).toLocaleTimeString();
    const cards = [
      ['Verified facts', d.facts, `${d.facts_with_predecessors} with predecessors`],
      ['Global-memory entries', Object.values(d.channel_counts).reduce((a, b) => a + b, 0), `${Object.keys(d.channel_counts).length} channels`],
      ['Verifier verdicts', (d.verdicts.correct || 0) + (d.verdicts.wrong || 0), `${d.verdicts.correct || 0} correct · ${d.verdicts.wrong || 0} wrong`],
      ['Pro consults', d.consult_count, `$${d.consult_cost_usd} spent`],
    ];
    const c = $('#ov-cards'); c.innerHTML = '';
    for (const [k, v, sub] of cards) {
      const card = el('div', 'card');
      card.appendChild(el('div', 'k', k));
      card.appendChild(el('div', 'v', String(v)));
      card.appendChild(el('div', 'sub', sub));
      c.appendChild(card);
    }
    bars($('#ov-channels'), d.channel_counts);
    bars($('#ov-authors'), d.facts_by_author);
    const vd = $('#ov-verdicts'); vd.innerHTML = '';
    const chips = el('div', 'chips');
    const vmap = { correct: 'var(--green)', wrong: 'var(--red)', error: 'var(--orange)' };
    for (const [k, v] of Object.entries(d.verdicts)) {
      const chip = el('div', 'chip');
      const dot = el('span', 'dot'); dot.style.background = vmap[k] || 'var(--text-muted)';
      chip.appendChild(dot); chip.appendChild(document.createTextNode(`${k}: ${v}`));
      chips.appendChild(chip);
    }
    vd.appendChild(chips);
  } catch (e) { connError(true); }
}

// ---- fact graph (echarts) ------------------------------------------------ //
let graphChart = null;
let factById = {};
// importance = dependency depth (longest path from an axiom/leaf up to a fact).
// Continuous shade: the deeper a fact, the darker — shallow=light, deep=dark.
function depthColor(depth, maxDepth) {
  const t = maxDepth > 0 ? Math.min(1, depth / maxDepth) : 0;
  return `hsl(248, ${(50 + t * 26).toFixed(0)}%, ${(80 - t * 52).toFixed(0)}%)`;
}
async function loadGraph() {
  try {
    const d = await api('/api/factgraph');
    connError(false);
    factById = {}; d.nodes.forEach((n) => (factById[n.id] = n));
    const maxD = d.max_depth || 1;
    const nodes = d.nodes.map((n) => {
      const dp = n.depth || 0;
      return {
        id: n.id, name: n.id.slice(0, 7),
        symbolSize: 6 + Math.min(16, dp * 2.5),        // bigger = deeper, but capped small so circles don't overlap when zoomed out
        itemStyle: { color: depthColor(dp, maxD) },
        depth: dp, author: n.author,                   // no per-node label (would clutter)
      };
    });
    const links = d.edges.map((e) => ({ source: e.source, target: e.target }));
    if (!graphChart) graphChart = echarts.init($('#graph'));
    graphChart.setOption({
      tooltip: {
        formatter: (p) => p.dataType === 'node'
          ? `<b>${p.data.id.slice(0, 10)}</b> · by ${p.data.author}<br/>dependency depth: ${p.data.depth} layer(s)<br/>${esc((factById[p.data.id] || {}).statement).slice(0, 100)}…`
          : '',
      },
      series: [{
        type: 'graph', layout: 'force', roam: true, draggable: true,
        force: { repulsion: 160, edgeLength: 80, gravity: 0.06 },
        label: { show: false }, emphasis: { focus: 'adjacency', label: { show: false } },
        lineStyle: { color: '#cbd5e1', width: 1, opacity: 0.55, curveness: 0.05 },
        edgeSymbol: ['none', 'arrow'], edgeSymbolSize: 5,
        data: nodes, links: links,
      }],
    });
    graphChart.off('click');
    graphChart.on('click', (p) => { if (p.dataType === 'node') showFact(p.data.id); });
    $('#graph-stat').textContent = `${d.nodes.length} facts · ${d.edges.length} edges · max depth ${d.max_depth}`;
    graphChart.resize();
  } catch (e) { connError(true); }
}
function showFact(id) {
  const f = factById[id]; if (!f) return;
  const d = $('#fact-detail'); d.innerHTML = '';
  d.appendChild(el('div', 'fid', f.id));
  if (f.author || f.problem_id) d.appendChild(el('div', 'muted', `${f.author || '?'} · ${f.problem_id || ''}`));
  const addSec = (h, txt) => { if (!txt) return; d.appendChild(el('div', 'sec-h', h)); const m = el('div', 'math'); mdmath(m, txt); d.appendChild(m); };
  addSec('Statement', f.statement);
  addSec('Proof', f.proof);
  addSec('Intuition', f.intuition);
  if (f.predecessors.length) {
    d.appendChild(el('div', 'sec-h', `Predecessors (${f.predecessors.length})`));
    const wrap = el('div');
    f.predecessors.forEach((p) => { const a = el('span', 'pred-link', p.slice(0, 10)); a.onclick = () => showFact(p); wrap.appendChild(a); });
    d.appendChild(wrap);
  }
}

// ---- global memory ------------------------------------------------------- //
let memInit = false;
// channels whose entries are long markdown (summary/strategy) — render full, no clamp.
const LONGFORM = new Set(['elaboration', 'master_guidance', 'verification']);
async function loadMemory() {
  if (memInit) return; memInit = true;
  try {
    const d = await api('/api/channels');
    connError(false);
    const st = $('#mem-subtabs'); st.innerHTML = '';
    d.channels.forEach((ch, i) => {
      const b = el('div', 'subtab' + (i === 0 ? ' active' : ''));
      b.appendChild(document.createTextNode(ch.kind));
      b.appendChild(el('span', 'cnt', String(ch.count)));
      b.onclick = () => { document.querySelectorAll('.subtab').forEach((x) => x.classList.remove('active')); b.classList.add('active'); loadChannel(ch.kind); };
      st.appendChild(b);
    });
    if (d.channels.length) loadChannel(d.channels[0].kind);
  } catch (e) { connError(true); memInit = false; }
}
async function loadChannel(kind) {
  const list = $('#mem-list'); list.innerHTML = '<div class="empty">loading…</div>';
  const longform = LONGFORM.has(kind);
  try {
    const d = await api('/api/channel/' + kind);
    list.innerHTML = '';
    if (!d.entries.length) { list.innerHTML = '<div class="empty">no entries in this channel</div>'; return; }
    for (const e of d.entries) {
      const card = el('div', 'entry' + (longform ? ' longform' : ''));
      const head = el('div', 'entry-head');
      head.appendChild(el('span', 'entry-author', e.author || '?'));
      if (e.verdict) head.appendChild(el('span', 'tag ' + (e.verdict === 'correct' ? 'correct' : e.verdict === 'wrong' ? 'wrong' : ''), e.verdict));
      if (e.fact_id) head.appendChild(el('span', 'tag fid', String(e.fact_id).slice(0, 10)));
      if (e.cost_usd != null) head.appendChild(el('span', 'tag cost', '$' + e.cost_usd));
      if (e.status) head.appendChild(el('span', 'tag', e.status));
      head.appendChild(el('span', 'entry-ts', (e.timestamp_utc || '').slice(0, 19).replace('T', ' ')));
      card.appendChild(head);
      const claim = el('div', 'entry-claim'); mdmath(claim, e.claim); card.appendChild(claim);
      if (e.evidence) {
        const ev = el('div', 'entry-evidence' + (longform ? '' : ' clamp'));
        mdmath(ev, e.evidence); card.appendChild(ev);
        if (!longform) {
          const more = el('div', 'more', 'show more ▾');
          more.onclick = () => { const open = ev.classList.toggle('open'); more.textContent = open ? 'show less ▴' : 'show more ▾'; };
          card.appendChild(more);
        }
      }
      list.appendChild(card);
    }
  } catch (err) { list.innerHTML = '<div class="empty">failed to load</div>'; }
}

// ---- init + polling ------------------------------------------------------ //
loadOverview();
setInterval(() => { const active = document.querySelector('.nav-link.active'); if (active && active.dataset.tab === 'overview') loadOverview(); }, 15000);
