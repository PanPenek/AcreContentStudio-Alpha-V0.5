/* Acre Content Studio — renderer (vanilla JS, no build step). */
'use strict';

window.__errors = [];
window.addEventListener('error', (e) => window.__errors.push(String(e.message)));
window.addEventListener('unhandledrejection', (e) => window.__errors.push(String(e.reason && e.reason.message || e.reason)));

const A = window.abs;
const $ = (s, r = document) => r.querySelector(s);
const S = { tab: 'dashboard', settings: null, vocab: null, episodes: [], jobs: [], ideas: [], studioId: null, studio: null, chat: [], busy: false };

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'html') el.innerHTML = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) if (c !== null && c !== undefined && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}
function toast(msg, err) {
  const d = h('div', { class: err ? 'err' : '' }, msg);
  $('#toast').append(d);
  setTimeout(() => d.remove(), err ? 9000 : 4000);
}
async function call(ch, arg, quiet) {
  try { return await A.call(ch, arg); } catch (e) { if (!quiet) toast(e.message, true); throw e; }
}
const fmtDur = (s) => (s == null ? '—' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`);
const ago = (t) => { if (!t) return ''; const s = (Date.now() - (t < 1e12 ? t * 1000 : t)) / 1000; return s < 60 ? 'just now' : s < 3600 ? `${Math.floor(s / 60)}m ago` : s < 86400 ? `${Math.floor(s / 3600)}h ago` : `${Math.floor(s / 86400)}d ago`; };
function sel(options, value, onchange, attrs = {}) {
  const s = h('select', { ...attrs, onchange: (e) => onchange(e.target.value) });
  for (const o of options) {
    const [v, l] = Array.isArray(o) ? o : [o, o];
    s.append(h('option', { value: v, selected: String(v) === String(value) }, l));
  }
  return s;
}
function field(label, input) { return h('label', { class: 'f' }, label, input); }
function txt(value, onchange, attrs = {}) { return h('input', { type: 'text', value: value ?? '', ...attrs, oninput: (e) => onchange(e.target.value) }); }

// ------------------------------------------------------------------ navigation
const RENDER = {};
function go(tab) {
  S.tab = tab;
  document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('on', b.dataset.tab === tab));
  document.querySelectorAll('.pane').forEach((p) => p.classList.toggle('on', p.id === `pane-${tab}`));
  (RENDER[tab] || (() => {}))();
}
window.__go = go;
document.querySelectorAll('#nav button').forEach((b) => b.addEventListener('click', () => go(b.dataset.tab)));

// ------------------------------------------------------------------ live events
A.on((ch, p) => {
  if (ch === 'jobs') { S.jobs = p; renderPill(); if (['dashboard', 'automations'].includes(S.tab)) RENDER[S.tab](); if (S.tab === 'studio') refreshStudioStatus(); }
  if (ch === 'joblog') { appendStudioLog(p); renderPillProgress(p); }
  if (ch === 'episodes') { S.episodes = p; if (S.tab === 'episodes') RENDER.episodes(); if (S.tab === 'studio') refreshStudioStatus(); }
  if (ch === 'ideas') { S.ideas = p; if (S.tab === 'ideas') RENDER.ideas(); }
  if (ch === 'overseer') { S.chat.push(p); if (S.tab === 'overseer') renderMsgs(); }
  if (ch === 'overseer-busy') { S.busy = p; if (S.tab === 'overseer') renderMsgs(); }
});

function runningJob() { return S.jobs.find((j) => j.state === 'running'); }
function renderPill() {
  const j = runningJob();
  const q = S.jobs.filter((x) => x.state === 'queued').length;
  const el = $('#jobpill');
  el.className = 'jobpill ' + (j ? 'run' : 'idle');
  el.innerHTML = '';
  if (!j) { el.append(q ? `${q} queued` : 'Queue idle'); return; }
  el.append(h('div', {}, `▶ ${j.label}`), h('div', { class: 'small dim', id: 'pillmsg' }, j.message || ''), h('div', { class: 'bar' }, h('i', { id: 'pillbar', style: { width: `${Math.round((j.progress || 0) * 100)}%` } })));
  if (q) el.append(h('div', { class: 'small dim' }, `+${q} queued`));
}
function renderPillProgress(p) {
  const b = $('#pillbar'); const m = $('#pillmsg');
  if (b && p.progress != null) b.style.width = `${Math.round(p.progress * 100)}%`;
  if (m && p.message) m.textContent = p.message;
}

// ------------------------------------------------------------------ dashboard
RENDER.dashboard = async () => {
  const pane = $('#pane-dashboard');
  const [eps, ideas, jobs] = await Promise.all([call('episodes:list'), call('ideas:list'), call('jobs:list')]);
  S.episodes = eps; S.ideas = ideas; S.jobs = jobs; renderPill();
  const fin = eps.filter((e) => e.hasFinal);
  const j = runningJob();
  pane.innerHTML = '';
  pane.append(
    h('h1', {}, `Hi Patryk — ${S.settings.channel.name}`),
    h('p', { class: 'sub' }, 'Ideas → script → voice → characters → stills → QA → render → final video. The Overseer can run all of it for you.'),
    h('div', { class: 'grid g4' },
      h('div', { class: 'card stat' }, h('div', { class: 'n' }, eps.length), h('div', { class: 'l' }, 'episodes')),
      h('div', { class: 'card stat' }, h('div', { class: 'n' }, fin.length), h('div', { class: 'l' }, 'finished videos')),
      h('div', { class: 'card stat' }, h('div', { class: 'n' }, ideas.filter((i) => i.status === 'new').length), h('div', { class: 'l' }, 'new ideas')),
      h('div', { class: 'card stat' }, h('div', { class: 'n' }, ideas.filter((i) => i.status === 'approved').length), h('div', { class: 'l' }, 'approved, ready to produce'))),
    h('div', { class: 'grid g2', style: { marginTop: '14px' } },
      h('div', { class: 'card' }, h('h2', {}, 'Now running'),
        j ? h('div', { class: 'col' }, h('div', {}, j.label), h('div', { class: 'prog' }, h('i', { style: { width: `${Math.round((j.progress || 0) * 100)}%` } })), h('div', { class: 'small muted' }, j.message || ''))
          : h('div', { class: 'muted' }, 'Nothing running.'),
        h('div', { class: 'row', style: { marginTop: '12px' } },
          h('button', { class: 'btn pri', onclick: () => go('overseer') }, 'Ask the Overseer'),
          h('button', { class: 'btn', onclick: () => go('ideas') }, 'Get new ideas'),
          h('button', { class: 'btn', onclick: produceNext }, 'Produce next approved idea'))),
      h('div', { class: 'card' }, h('h2', {}, 'System'), h('div', { id: 'syscheck', class: 'col small' }, 'checking…'))),
    h('h2', { style: { marginTop: '22px' } }, 'Latest videos'),
    fin.length ? h('div', { class: 'epgrid' }, fin.slice(0, 6).map(epCard)) : h('div', { class: 'empty' }, 'No finished videos yet.'));
  call('system:check', null, true).then((c) => {
    const box = $('#syscheck'); if (!box) return;
    box.innerHTML = '';
    for (const [k, v] of Object.entries(c)) box.append(h('div', { class: 'row' }, h('span', { class: `chip ${v ? 'ok' : 'err'}` }, v ? 'ok' : 'missing'), h('b', {}, k), h('span', { class: 'dim' }, (v || '').slice(0, 70))));
  }).catch(() => {});
};

async function produceNext() {
  const idea = S.ideas.find((i) => i.status === 'approved');
  if (!idea) return toast('No approved idea — approve one in Idea Maker first.', true);
  await call('ideas:status', { id: idea.id, status: 'queued' });
  await call('jobs:enqueue', { kind: 'produce', args: { ideaId: idea.id }, label: `produce: ${idea.title}` });
  toast(`Queued: ${idea.title}`);
}

// ------------------------------------------------------------------ ideas
RENDER.ideas = async () => {
  const pane = $('#pane-ideas');
  S.ideas = await call('ideas:list');
  let count = 6; let theme = '';
  const gen = h('button', { class: 'btn pri' }, 'Generate ideas');
  gen.onclick = async () => {
    gen.disabled = true; gen.textContent = 'Thinking…';
    try { const r = await call('ideas:generate', { count, theme }); toast(`${r.length} new ideas`); } finally { gen.disabled = false; gen.textContent = 'Generate ideas'; RENDER.ideas(); }
  };
  const filt = S.ideaFilter || 'all';
  const items = S.ideas.filter((i) => filt === 'all' || i.status === filt);
  pane.innerHTML = '';
  pane.append(
    h('h1', {}, 'Idea Maker'), h('p', { class: 'sub' }, 'Pitches that fit what the pipeline can actually produce. Approve the good ones — Autopilot and the nightly run produce approved ideas.'),
    h('div', { class: 'card row' },
      field('How many', h('input', { type: 'number', value: count, min: 1, max: 20, style: { width: '80px' }, oninput: (e) => { count = Number(e.target.value); } })),
      h('label', { class: 'f grow' }, 'Theme (optional)', txt('', (v) => { theme = v; }, { placeholder: 'e.g. medieval inventions, survival tricks, how the body works' })),
      h('div', { style: { alignSelf: 'flex-end' } }, gen)),
    h('div', { class: 'row', style: { margin: '16px 0 10px' } }, ['all', 'new', 'approved', 'queued', 'used', 'rejected'].map((f) =>
      h('button', { class: `btn sm ${f === filt ? 'pri' : 'ghost'}`, onclick: () => { S.ideaFilter = f; RENDER.ideas(); } }, `${f} (${f === 'all' ? S.ideas.length : S.ideas.filter((i) => i.status === f).length})`)),
    h('span', { class: 'grow' }), h('button', { class: 'btn sm', onclick: addIdeaManually }, '+ Add my own idea')),
    items.length ? h('div', { class: 'grid g3' }, items.map(ideaCard)) : h('div', { class: 'empty' }, 'No ideas here yet.'));
};
function ideaCard(i) {
  const st = (status) => async () => { await call('ideas:status', { id: i.id, status }); RENDER.ideas(); };
  return h('div', { class: 'card col' },
    h('div', { class: 'row' }, h('span', { class: `chip ${i.status === 'approved' ? 'ok' : i.status === 'rejected' ? 'err' : i.status === 'queued' ? 'run' : ''}` }, i.status), i.score ? h('span', { class: 'chip info' }, `score ${i.score}`) : null, h('span', { class: 'grow' }), h('span', { class: 'small dim' }, i.by || '')),
    h('div', { style: { fontWeight: 650, fontSize: '15px' } }, i.title),
    i.hook ? h('div', { class: 'muted' }, `“${i.hook}”`) : null,
    i.lessons ? h('div', { class: 'small' }, (i.lessons || []).map((l) => `• ${l}`).join('\n').split('\n').map((l) => h('div', {}, l))) : null,
    i.source_hint ? h('div', { class: 'small dim' }, `Source: ${i.source_hint}`) : null,
    i.episode ? h('div', { class: 'small' }, h('a', { href: '#', onclick: (e) => { e.preventDefault(); openStudio(i.episode); } }, `→ ${i.episode}`)) : null,
    h('div', { class: 'row' },
      i.status !== 'approved' ? h('button', { class: 'btn sm pri', onclick: st('approved') }, 'Approve') : null,
      i.status !== 'rejected' ? h('button', { class: 'btn sm ghost', onclick: st('rejected') }, 'Reject') : null,
      h('button', { class: 'btn sm', onclick: async (e) => { e.target.disabled = true; e.target.textContent = 'Writing…'; try { const r = await call('ai:script', { ideaId: i.id }); toast(`Script ready: ${r.id}`); openStudio(r.id); } finally { e.target.disabled = false; } } }, 'Write script'),
      h('button', { class: 'btn sm', onclick: async () => { await call('ideas:status', { id: i.id, status: 'queued' }); await call('jobs:enqueue', { kind: 'produce', args: { ideaId: i.id }, label: `produce: ${i.title}` }); toast('Queued full production'); RENDER.ideas(); } }, 'Produce video')));
}
function addIdeaManually() {
  const d = { title: '', hook: '', topic: '' };
  const m = modal('Add an idea', h('div', { class: 'col' },
    field('Title', txt('', (v) => { d.title = v; })), field('Hook (first line)', txt('', (v) => { d.hook = v; })),
    field('Topic / notes', h('textarea', { rows: 4, oninput: (e) => { d.topic = e.target.value; } }))),
  [h('button', { class: 'btn pri', onclick: async () => { if (!d.title) return; await call('ideas:add', d); m.remove(); RENDER.ideas(); } }, 'Add')]);
}
function modal(title, body, actions = []) {
  const m = h('div', { class: 'modal', onclick: (e) => { if (e.target === m) m.remove(); } },
    h('div', { class: 'card box col' }, h('div', { class: 'row' }, h('h2', { class: 'grow', style: { margin: 0 } }, title), h('button', { class: 'btn sm ghost', onclick: () => m.remove() }, '✕')), body, h('div', { class: 'row', style: { justifyContent: 'flex-end' } }, actions)));
  document.body.append(m);
  return m;
}

// ------------------------------------------------------------------ episodes
function epCard(e) {
  const st = e.status || {};
  const badge = e.hasFinal ? h('span', { class: 'chip ok' }, 'final') : st.state === 'running' ? h('span', { class: 'chip run' }, `${st.stage} ${Math.round((st.progress || 0) * 100)}%`) : st.state === 'error' ? h('span', { class: 'chip err' }, `${st.stage} failed`) : h('span', { class: 'chip' }, e.hasStills ? 'stills' : e.hasAudio ? 'audio' : e.beats ? 'script' : 'empty');
  return h('div', { class: 'card ep', onclick: () => openStudio(e.id) },
    h('div', { class: 'th', style: e.thumb ? { backgroundImage: `url("${A.file(e.thumb)}")` } : {} }, e.thumb ? '' : 'no preview'),
    h('div', { class: 'meta' }, h('div', { class: 't' }, e.title), h('div', { class: 'row small muted', style: { marginTop: '4px' } }, badge, `${e.beats} beats`, fmtDur(e.duration))));
}
RENDER.episodes = async () => {
  const pane = $('#pane-episodes');
  S.episodes = await call('episodes:list');
  pane.innerHTML = '';
  let topic = '';
  pane.append(h('h1', {}, 'Episodes'), h('p', { class: 'sub' }, `Workspace: ${S.settings.workspace}`),
    h('div', { class: 'card row', style: { marginBottom: '16px' } },
      h('label', { class: 'f grow' }, 'New episode from a topic', txt('', (v) => { topic = v; }, { placeholder: 'e.g. How a water mill turns a river into flour (in the woods)' })),
      h('div', { class: 'row', style: { alignSelf: 'flex-end' } },
        h('button', { class: 'btn pri', onclick: async (e) => { if (!topic) return; e.target.disabled = true; e.target.textContent = 'Writing script…'; try { const r = await call('ai:script', { topic }); openStudio(r.id); } finally { e.target.disabled = false; e.target.textContent = 'AI script'; } } }, 'AI script'),
        h('button', { class: 'btn', onclick: async () => { const id = await call('episodes:create', { title: topic || 'New episode', topic }); openStudio(id); } }, 'Blank'),
        h('button', { class: 'btn', onclick: async () => { if (!topic) return; await call('jobs:enqueue', { kind: 'produce', args: { topic }, label: `produce: ${topic}` }); toast('Queued full production'); } }, 'Produce whole video'))),
    S.episodes.length ? h('div', { class: 'epgrid' }, S.episodes.map(epCard)) : h('div', { class: 'empty' }, 'No episodes yet.'));
};

// ------------------------------------------------------------------ studio
async function openStudio(id) { S.studioId = id; go('studio'); }
const STAGES = [['audio', 'Voice + music', 'TTS, SFX, chiptune, timing'], ['props', 'Props', 'generate the 3D objects (~4 min each)'], ['stills', 'Stills', 'contact sheet per shot'], ['render', 'Render', 'Blender EEVEE frames'], ['compose', 'Compose', 'captions + final mp4'], ['all', 'Run all', 'audio → final']];

RENDER.studio = async () => {
  const pane = $('#pane-studio');
  if (!S.episodes.length) S.episodes = await call('episodes:list');
  if (!S.studioId && S.episodes.length) S.studioId = S.episodes[0].id;
  pane.innerHTML = '';
  if (!S.studioId) { pane.append(h('h1', {}, 'Studio'), h('div', { class: 'empty' }, 'Create an episode first.')); return; }
  const { episode, summary } = await call('episodes:get', S.studioId);
  S.studio = episode; S.studioSum = summary;
  const V = S.vocab; const SET = V.sets[episode.set] || V.sets.cozy_room;
  const ep = episode;
  const dirty = () => { $('#savebtn').classList.add('pri'); $('#savebtn').textContent = 'Save changes'; };
  const save = async () => {
    const r = await call('episodes:save', { id: S.studioId, episode: S.studio });
    $('#savebtn').classList.remove('pri'); $('#savebtn').textContent = 'Saved';
    if (r.fixes.length) toast('Adjusted: ' + r.fixes.join('; '));
  };
  const beatsBox = h('div');
  const renderBeats = () => {
    beatsBox.innerHTML = '';
    ep.beats.forEach((b, i) => {
      b.host = b.host || {};
      const hasCat = (ep.props || []).includes('cat');
      if (hasCat) b.cat = b.cat || {};
      const propIds = (ep.props || []).filter((x) => x && typeof x === 'object').map((x) => x.id);
      const upd = (fn) => (v) => { fn(v); dirty(); };
      const shotsVal = (b.shots || [b.shot || 'wide']).join(', ');
      beatsBox.append(h('div', { class: 'beat' },
        h('div', { class: 'bh' }, h('span', { class: 'bn' }, i + 1),
          h('textarea', { rows: 2, class: 'grow', oninput: (e) => { b.text = e.target.value; dirty(); } }, b.text || ''),
          h('div', { class: 'col', style: { gap: '4px' } },
            h('button', { class: 'btn sm ghost', title: 'move up', onclick: () => { if (i) { [ep.beats[i - 1], ep.beats[i]] = [ep.beats[i], ep.beats[i - 1]]; dirty(); renderBeats(); } } }, '↑'),
            h('button', { class: 'btn sm ghost danger', title: 'delete', onclick: () => { ep.beats.splice(i, 1); dirty(); renderBeats(); } }, '✕'))),
        h('div', { class: 'fields' },
          field('Shots', txt(shotsVal, upd((v) => { const arr = v.split(',').map((x) => x.trim()).filter(Boolean); delete b.shot; b.shots = arr; }), { title: SET.shots.join(', ') })),
          field('Host pose', sel(V.host_poses, b.host.pose || 'idle', upd((v) => { b.host.pose = v; }))),
          field('Host face', sel(V.host_faces, b.host.face || 'smile', upd((v) => { b.host.face = v; }))),
          field('Host look', txt(b.host.look ?? 'camera', upd((v) => { b.host.look = /^-?\d+(\.\d+)?$/.test(v) ? Number(v) : v; }))),
          propIds.length ? field('Focus (prop shots)', sel(['', ...propIds], b.focus || '', upd((v) => { if (v) b.focus = v; else delete b.focus; }))) : null,
          propIds.length ? field('Prop action', txt(Object.entries(b.prop || {}).map(([k, v]) => `${k}:${v}`).join(', '), upd((v) => { const o = {}; v.split(',').map((x) => x.trim()).filter(Boolean).forEach((x) => { const [k, a] = x.split(':').map((y) => y.trim()); if (k && a) o[k] = a; }); if (Object.keys(o).length) b.prop = o; else delete b.prop; }), { title: `id:action, e.g. ${propIds[0]}:appear. Actions: ${V.prop_actions.join(', ')}` })) : null,
          ...(hasCat ? [
            field('Cat action', sel(['', ...V.cat_actions], b.cat.action || '', upd((v) => { if (v) b.cat.action = v; else delete b.cat.action; }))),
            field('Cat at (teleport)', sel(['', ...SET.anchors], typeof b.cat.at === 'string' ? b.cat.at : '', upd((v) => { if (v) b.cat.at = v; else delete b.cat.at; }))),
            field('Cat walks to', sel(['', ...SET.anchors], typeof b.cat.to === 'string' ? b.cat.to : '', upd((v) => { if (v) b.cat.to = v; else delete b.cat.to; }))),
            field('Cat faces', txt(b.cat.face ?? '', upd((v) => { if (v === '') delete b.cat.face; else b.cat.face = /^-?\d+(\.\d+)?$/.test(v) ? Number(v) : v; })))] : []),
          field('Card (big title)', txt(b.card || '', upd((v) => { b.card = v.toUpperCase(); }))),
          field('Label', txt(b.label || '', upd((v) => { b.label = v; }))),
          field('Opening title', txt(b.title || '', upd((v) => { b.title = v; }))),
          field('SFX', txt((b.sfx || []).map((x) => (Array.isArray(x) ? `${x[0]}@${x[1]}` : x)).join(', '), upd((v) => { b.sfx = v.split(',').map((x) => x.trim()).filter(Boolean).map((x) => { const [n, t] = x.split('@'); return t ? [n, Number(t)] : n; }); }), { title: V.sfx.join(', ') })))));
    });
    beatsBox.append(h('button', { class: 'btn', onclick: () => { ep.beats.push({ text: '', shot: 'host', host: { pose: 'explain', face: 'smile' } }); dirty(); renderBeats(); } }, '+ Add beat'));
  };
  renderBeats();
  const epSel = sel(S.episodes.map((e) => [e.id, `${e.id} — ${e.title}`]), S.studioId, (v) => { S.studioId = v; RENDER.studio(); });
  const left = h('div', { class: 'col' },
    h('div', { class: 'card col' },
      h('div', { class: 'row' }, h('label', { class: 'f grow' }, 'Episode', epSel), h('button', { id: 'savebtn', class: 'btn', style: { alignSelf: 'flex-end' }, onclick: save }, 'Saved')),
      h('div', { class: 'grid g2' },
        field('Title', txt(ep.title, (v) => { ep.title = v; dirty(); })),
        field('Topic', txt(ep.topic, (v) => { ep.topic = v; dirty(); }))),
      h('div', { class: 'grid g4' },
        field('Voice', sel(V.voices, ep.voice?.narrator, (v) => { ep.voice = { ...ep.voice, narrator: v }; dirty(); })),
        field('Rate', txt(ep.voice?.rate || '+0%', (v) => { ep.voice = { ...ep.voice, rate: v }; dirty(); })),
        field('Pitch', txt(ep.voice?.pitch || '+0Hz', (v) => { ep.voice = { ...ep.voice, pitch: v }; dirty(); }))),
      h('div', { class: 'grid g2' },
        field('Set (location)', sel(Object.keys(V.sets), ep.set, (v) => { ep.set = v; dirty(); renderBeats(); }))),
      (ep.props || []).includes('cat') ? field('Cat colour', sel(V.cat_palettes, ep.cat_palette || 'orange', (v) => { ep.cat_palette = v; dirty(); })) : null,
      (ep.props || []).some((x) => x && typeof x === 'object') ? h('div', { class: 'small' }, h('b', {}, 'Props: '), (ep.props || []).filter((x) => x && typeof x === 'object').map((x) => `${x.id} (${x.describe})${x.asset ? '' : ' - not built yet'}`).join(' · ')) : null,
      h('div', { class: 'small dim' }, `Host: ${ep.characters?.host || '—'} · Set: ${ep.set} · ${ep.beats.length} beats${ep.script_by ? ` · script by ${ep.script_by}` : ''}. Text changes need "Voice + music" again; staging changes only need Stills/Render.`)),
    h('h3', { style: { marginTop: '8px' } }, 'Beats'), beatsBox,
    h('details', {}, h('summary', { class: 'muted', style: { cursor: 'pointer' } }, 'Raw episode.json'),
      h('textarea', { class: 'mono', rows: 18, id: 'rawjson', onchange: (e) => { try { S.studio = JSON.parse(e.target.value); dirty(); toast('JSON parsed — Save to keep it'); } catch (err) { toast('Invalid JSON: ' + err.message, true); } } }, JSON.stringify(ep, null, 2))));

  const right = h('div', { class: 'col sticky' },
    h('div', { class: 'card col' }, h('h2', {}, 'Pipeline'), h('div', { class: 'steps', id: 'steps' }),
      h('div', { class: 'row' },
        h('button', { class: 'btn sm', onclick: () => call('paths:open', summary.dir) }, 'Open folder'),
        h('button', { class: 'btn sm', title: 'Opens Blender with this episode scene (built by the Stills/Render stage)', onclick: () => call('blender:open', summary.dir + '\\scene.blend') }, 'Open scene in Blender'),
        h('button', { class: 'btn sm', onclick: async (e) => { e.target.disabled = true; e.target.textContent = 'Reviewing…'; try { await call('ai:review', S.studioId); toast('Review saved'); RENDER.studio(); } finally { e.target.disabled = false; } } }, 'AI review stills'),
        h('span', { class: 'grow' }),
        h('button', { class: 'btn sm danger ghost', onclick: async () => { if (!confirm(`Move ${S.studioId} to trash?`)) return; await call('episodes:remove', S.studioId); S.studioId = null; RENDER.studio(); } }, 'Delete'))),
    summary.final ? h('div', { class: 'card' }, h('h2', {}, 'Final video'), h('video', { src: A.file(summary.final), controls: true, preload: 'metadata', style: { maxHeight: '560px', objectFit: 'contain' } })) : null,
    summary.review ? h('div', { class: 'card col' }, h('h2', {}, `AI review — ${summary.review.ok ? 'OK' : 'needs fixes'} (score ${summary.review.score})`),
      (summary.review.issues || []).map((x) => h('div', { class: 'small' }, h('b', {}, `#${x.shot} `), x.problem, h('div', { class: 'dim' }, `fix: ${x.fix}`)))) : null,
    summary.contact ? h('div', { class: 'card' }, h('h2', {}, 'Contact sheet'), h('img', { class: 'contact', src: A.file(summary.contact) })) : null,
    h('div', { class: 'card' }, h('h2', {}, 'Log'), h('div', { class: 'log mono', id: 'studiolog' })));
  pane.append(h('div', { class: 'studio' }, left, right));
  refreshStudioStatus();
  const log = await call('episodes:log', S.studioId, true).catch(() => []);
  const lb = $('#studiolog'); if (lb) { lb.textContent = log.slice(-200).join('\n'); lb.scrollTop = 1e9; }
};
async function refreshStudioStatus() {
  const box = $('#steps'); if (!box || !S.studioId) return;
  const { summary } = await call('episodes:get', S.studioId, true).catch(() => ({}));
  if (!summary) return;
  const st = summary.status || {}; const stages = st.stages || {};
  const job = S.jobs.find((j) => ['running', 'queued'].includes(j.state) && (j.args || {}).episodeId === S.studioId);
  box.innerHTML = '';
  for (const [k, name, desc] of STAGES) {
    const s = stages[k] || {};
    const isRun = st.stage === k && st.state === 'running';
    const done = { audio: summary.hasAudio, stills: summary.hasStills, render: summary.framesNeeded && summary.frames >= summary.framesNeeded, compose: summary.hasFinal, all: summary.hasFinal }[k];
    box.append(h('div', { class: `step ${isRun ? 'run' : s.state === 'error' && !done ? 'err' : done ? 'done' : ''}` },
      h('div', { class: 'sn' }, name), h('div', { class: 'ss' }, isRun ? `${Math.round((st.progress || 0) * 100)}% ${st.message || ''}`.slice(0, 40) : done ? '✓ done' : desc),
      h('button', { class: `btn sm ${k === 'all' ? 'pri' : ''}`, disabled: !!job, onclick: async () => { await call('jobs:enqueue', { kind: 'stage', args: { episodeId: S.studioId, stage: k }, label: `${k}: ${S.studioId}` }); toast(`Queued ${name}`); } }, done && k !== 'all' ? 'Redo' : 'Run')));
  }
}
function appendStudioLog(p) {
  const lb = $('#studiolog'); if (!lb || S.tab !== 'studio') return;
  const j = S.jobs.find((x) => x.id === p.id);
  if (j && (j.args || {}).episodeId !== S.studioId) return;
  if (p.line.startsWith('@@PROGRESS')) { refreshStudioStatus(); return; }
  lb.textContent += (lb.textContent ? '\n' : '') + p.line;
  if (lb.textContent.length > 60000) lb.textContent = lb.textContent.slice(-40000);
  lb.scrollTop = 1e9;
}

// ------------------------------------------------------------------ overseer
RENDER.overseer = async () => {
  const pane = $('#pane-overseer');
  S.chat = await call('overseer:history');
  pane.innerHTML = '';
  const ta = h('textarea', { placeholder: 'Tell the Overseer what to make… e.g. "Pitch 5 ideas about dogs, pick the best and produce it"', onkeydown: (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); } } });
  const sendMsg = async () => { const t = ta.value.trim(); if (!t || S.busy) return; ta.value = ''; await call('overseer:send', t); };
  const quick = ['Pitch 5 new ideas and tell me your favourite', 'Produce the best approved idea', 'What is running right now?', 'Review the stills of the latest episode'];
  pane.append(h('div', { class: 'row' }, h('div', { class: 'grow' }, h('h1', {}, 'Overseer'), h('p', { class: 'sub', style: { marginBottom: '8px' } }, 'The manager: writes, stages, queues and checks whole videos. Uses the model routed to "overseer" in AI Engines.')),
    h('button', { class: 'btn sm ghost', onclick: async () => { await call('overseer:clear'); RENDER.overseer(); } }, 'Clear chat')),
  h('div', { class: 'chat card' }, h('div', { class: 'msgs', id: 'msgs' }),
    h('div', { class: 'row small', style: { marginBottom: '8px' } }, quick.map((q) => h('button', { class: 'btn sm ghost', onclick: () => { ta.value = q; sendMsg(); } }, q))),
    h('div', { class: 'composer' }, ta, h('button', { class: 'btn pri', onclick: sendMsg }, 'Send'))));
  renderMsgs();
};
function renderMsgs() {
  const box = $('#msgs'); if (!box) return;
  box.innerHTML = '';
  if (!S.chat.length) box.append(h('div', { class: 'empty' }, 'Say hi. The Overseer can pitch ideas, write scripts, queue renders and check results.'));
  for (const m of S.chat) {
    if (m.role === 'tool') { box.append(h('details', { class: 'msg tool' }, h('summary', {}, 'tool results'), h('div', { class: 'mono' }, m.content))); continue; }
    box.append(h('div', { class: `msg ${m.role}` }, m.content, (m.actions && m.actions.length) || m.provider ? h('div', { class: 'by' }, [m.provider, m.actions && m.actions.length ? `→ ${m.actions.join(', ')}` : ''].filter(Boolean).join(' ')) : null));
  }
  if (S.busy) box.append(h('div', { class: 'msg assistant dim' }, 'working…'));
  box.scrollTop = 1e9;
}

// ------------------------------------------------------------------ characters
RENDER.characters = async () => {
  const pane = $('#pane-characters');
  const chars = await call('characters:list');
  pane.innerHTML = '';
  pane.append(h('h1', {}, 'Characters'), h('p', { class: 'sub' }, 'Two kinds: exact-likeness models made from your reference art (3D mesh + projected pixel texture, 8 face textures), and VRoid-based models styled by a recipe. Rebuild after editing a recipe.'),
    h('div', { class: 'grid g2' }, chars.map((c) => h('div', { class: 'card col charcard' },
      h('div', { class: 'row' }, h('h2', { class: 'grow', style: { margin: 0 } }, c.name), h('span', { class: `chip ${c.built ? 'ok' : ''}` }, c.built ? 'built' : 'not built'), c.id === S.settings.channel.host ? h('span', { class: 'chip info' }, 'channel host') : null),
      h('div', { class: 'pics' },
        h('div', {}, c.reference ? h('img', { src: A.file(c.reference) }) : h('div', { class: 'empty' }, 'no ref'), h('div', { class: 'cap' }, 'reference')),
        h('div', {}, c.preview ? h('img', { src: A.file(c.preview) }) : h('div', { class: 'empty' }, '—'), h('div', { class: 'cap' }, '3D build')),
        h('div', {}, c.face ? h('img', { src: A.file(c.face) }) : h('div', { class: 'empty' }, '—'), h('div', { class: 'cap' }, 'close-up'))),
      h('div', { class: 'small dim' }, `id ${c.id} · ${c.kind === 'projected' ? 'exact likeness from reference art' : `VRoid base ${c.base || '?'}`}${c.builtAt ? ` · built ${ago(c.builtAt)}` : ''}`),
      h('div', { class: 'row' },
        h('button', { class: 'btn sm pri', onclick: async () => { await call('characters:rebuild', c.id); toast('Character build queued'); } }, 'Rebuild'),
        h('button', { class: 'btn sm', onclick: () => editRecipe(c.id) }, 'Edit recipe'),
        h('button', { class: 'btn sm', onclick: () => newCharacterFrom(c.id) }, 'Duplicate as new'),
        c.id !== S.settings.channel.host ? h('button', { class: 'btn sm ghost', onclick: async () => { S.settings.channel.host = c.id; S.settings = await call('settings:save', S.settings); RENDER.characters(); } }, 'Make channel host') : null)))));
};
async function editRecipe(id) {
  const r = await call('characters:recipe', id);
  const ta = h('textarea', { class: 'mono', rows: 28 }, JSON.stringify(r, null, 1));
  const m = modal(`Recipe — ${id}`, ta, [h('button', { class: 'btn pri', onclick: async () => { try { await call('characters:saveRecipe', { id, recipe: JSON.parse(ta.value) }); m.remove(); toast('Saved — click Rebuild'); } catch (e) { toast(e.message, true); } } }, 'Save')]);
}
async function newCharacterFrom(src) {
  const r = await call('characters:recipe', src);
  const bases = await call('characters:bases');
  const d = { id: `${src}_2`, name: `${r.name} 2`, base: r.base_vrm };
  const m = modal('New character', h('div', { class: 'col' }, field('Id (folder name)', txt(d.id, (v) => { d.id = v.replace(/[^a-z0-9_]/gi, '_').toLowerCase(); })), field('Name', txt(d.name, (v) => { d.name = v; })), field('Base model', sel(bases, d.base, (v) => { d.base = v; })),
    h('div', { class: 'small dim' }, 'The colour rules are tuned for the Sendagaya_Shino texture layout; other bases may need recipe tweaks.')),
  [h('button', { class: 'btn pri', onclick: async () => { await call('characters:saveRecipe', { id: d.id, recipe: { ...r, id: d.id, name: d.name, base_vrm: d.base } }); m.remove(); RENDER.characters(); } }, 'Create')]);
}

// ------------------------------------------------------------------ blender
RENDER.blender = async () => {
  const pane = $('#pane-blender');
  pane.innerHTML = '';
  const st = h('div', { class: 'col' }, 'checking…');
  const out = h('div', { class: 'log mono', style: { height: '260px' } });
  const code = h('textarea', { class: 'mono', rows: 10 }, 'import bpy\nresult = {"objects": [o.name for o in bpy.data.objects][:40], "frame": bpy.context.scene.frame_current}');
  const refresh = async () => {
    const s = await call('blender:status', null, true).catch((e) => ({ error: e.message }));
    st.innerHTML = '';
    st.append(h('div', { class: 'row' }, h('span', { class: `chip ${s.exe ? 'ok' : 'err'}` }, 'blender exe'), h('span', { class: `chip ${s.bridge ? 'ok' : ''}` }, s.bridge ? 'live bridge connected' : 'no live bridge'), s.headless ? h('span', { class: 'chip run' }, 'headless bridge running') : null),
      s.bridge ? h('div', { class: 'small muted' }, `Blender ${s.info.version} · ${s.info.background ? 'background' : 'GUI'} · ${s.info.objects} objects · ${s.info.file || 'unsaved'}`) : h('div', { class: 'small dim' }, s.error || ''));
  };
  pane.append(h('h1', {}, 'Blender'), h('p', { class: 'sub' }, 'Episodes render headless through the engine. Here you can also drive a live Blender through the official Blender MCP add-on (port 9876): the same bridge Hermes / Claude use.'),
    h('div', { class: 'grid g2' },
      h('div', { class: 'card col' }, h('h2', {}, 'Connection'), st,
        h('div', { class: 'row' },
          h('button', { class: 'btn', onclick: refresh }, 'Refresh'),
          h('button', { class: 'btn', onclick: async () => { await call('blender:open', null); toast('Blender is starting (the add-on auto-starts the bridge)'); } }, 'Open Blender'),
          h('button', { class: 'btn', onclick: async () => { await call('blender:headless', { on: true }); setTimeout(refresh, 6000); } }, 'Start headless bridge'),
          h('button', { class: 'btn ghost', onclick: async () => { await call('blender:headless', { on: false }); refresh(); } }, 'Stop headless')),
        h('div', { class: 'small dim' }, `Executable: ${S.settings.blenderPath}`)),
      h('div', { class: 'card col' }, h('h2', {}, 'Python console (live Blender)'), code,
        h('div', { class: 'row' }, h('button', { class: 'btn pri', onclick: async () => { try { const r = await call('blender:exec', code.value); out.textContent = JSON.stringify(r, null, 2); } catch (e) { out.textContent = e.message; } } }, 'Run in Blender'),
          h('span', { class: 'small dim' }, 'Set `result = {...}` to return data. Runs unsandboxed with your permissions.')), out)));
  refresh();
};

// ------------------------------------------------------------------ automations
RENDER.automations = async () => {
  const pane = $('#pane-automations');
  S.jobs = await call('jobs:list');
  const a = S.settings.automations; const sf = S.settings.safety;
  const saveS = async () => { S.settings = await call('settings:save', S.settings); toast('Saved'); };
  pane.innerHTML = '';
  pane.append(h('h1', {}, 'Automations'), h('p', { class: 'sub' }, 'Long-term production: the queue runs one job at a time (Blender owns the GPU), survives restarts, and can ping you on Telegram.'),
    h('div', { class: 'grid g3' },
      h('div', { class: 'card col' }, h('h2', {}, 'Autopilot'),
        h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: a.autopilot, onchange: (e) => { a.autopilot = e.target.checked; saveS(); } }), 'Produce approved ideas whenever the queue is empty'),
        h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: a.reviewStills, onchange: (e) => { a.reviewStills = e.target.checked; saveS(); } }), 'AI-review stills before rendering'),
        field('Auto-fix rounds (restage from the review, re-check stills)', h('input', { type: 'number', min: 0, max: 3, value: a.autoFixRounds ?? 1, style: { width: '80px' }, onchange: (e) => { a.autoFixRounds = Number(e.target.value); saveS(); } })),
        h('div', { class: 'small dim' }, 'Only ideas you approved are produced. Auto-fix changes camera/pose/props only, never the narration.')),
      h('div', { class: 'card col' }, h('h2', {}, 'Nightly run'),
        h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: a.nightly.enabled, onchange: (e) => { a.nightly.enabled = e.target.checked; saveS(); } }), 'Enabled'),
        h('div', { class: 'row' }, field('Time', h('input', { type: 'time', value: a.nightly.time, onchange: (e) => { a.nightly.time = e.target.value; saveS(); } })),
          field('Videos', h('input', { type: 'number', min: 1, max: 10, value: a.nightly.count, style: { width: '80px' }, onchange: (e) => { a.nightly.count = Number(e.target.value); saveS(); } })))),
      h('div', { class: 'card col' }, h('h2', {}, 'Notify + safety'),
        h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: a.telegram.enabled, onchange: (e) => { a.telegram.enabled = e.target.checked; saveS(); } }), 'Telegram ping when a job ends'),
        h('div', { class: 'row' }, field('Bot token', h('input', { type: 'password', value: a.telegram.botToken, onchange: (e) => { a.telegram.botToken = e.target.value; saveS(); } })), field('Chat id', txt(a.telegram.chatId, (v) => { a.telegram.chatId = v; }, { onchange: saveS }))),
        h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: sf.confirmPaid, onchange: (e) => { sf.confirmPaid = e.target.checked; saveS(); } }), 'Ask before pay-per-token models'),
        h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: sf.allowPaidInAutomations, onchange: (e) => { sf.allowPaidInAutomations = e.target.checked; saveS(); } }), 'Allow paid models in unattended runs'))),
    h('div', { class: 'row', style: { margin: '20px 0 10px' } }, h('h2', { class: 'grow', style: { margin: 0 } }, 'Jobs'), h('button', { class: 'btn sm ghost', onclick: async () => { await call('jobs:clear'); RENDER.automations(); } }, 'Clear finished')),
    S.jobs.length ? h('table', { class: 't' }, h('tr', {}, h('th', {}, 'Job'), h('th', {}, 'State'), h('th', {}, 'Progress'), h('th', {}, 'When'), h('th', {})),
      [...S.jobs].reverse().slice(0, 60).map((j) => h('tr', {},
        h('td', {}, h('div', {}, j.label), h('div', { class: 'small dim' }, j.message || '')),
        h('td', {}, h('span', { class: `chip ${j.state === 'done' ? 'ok' : j.state === 'error' ? 'err' : j.state === 'running' ? 'run' : ''}` }, j.state)),
        h('td', { style: { width: '160px' } }, h('div', { class: 'prog' }, h('i', { style: { width: `${Math.round((j.progress || 0) * 100)}%` } }))),
        h('td', { class: 'small dim' }, ago(j.started || j.created)),
        h('td', {}, h('div', { class: 'row' }, h('button', { class: 'btn sm ghost', onclick: async () => { const log = await call('jobs:log', j.id); modal(j.label, h('div', { class: 'log mono', style: { height: '60vh' } }, log.join('\n'))); } }, 'Log'),
          ['queued', 'running'].includes(j.state) ? h('button', { class: 'btn sm danger', onclick: () => call('jobs:cancel', j.id) }, 'Cancel') : null))))) : h('div', { class: 'empty' }, 'No jobs yet.'));
};

// ------------------------------------------------------------------ engines
RENDER.engines = async () => {
  const pane = $('#pane-engines');
  const s = S.settings;
  const saveS = async () => { S.settings = await call('settings:save', s); toast('Saved'); };
  pane.innerHTML = '';
  const roles = [['ideas', 'Idea Maker'], ['script', 'Script Writer'], ['overseer', 'Overseer'], ['review', 'Still reviewer (needs vision)']];
  const ids = s.providers.map((p) => [p.id, p.name]);
  pane.append(h('h1', {}, 'AI Engines'), h('p', { class: 'sub' }, 'Link any model. Subscription CLIs (Claude Code with your Opus subscription, Gemini CLI) cost nothing per call; API providers are pay-per-token and ask first.'),
    h('div', { class: 'card col' }, h('h2', {}, 'Routing (first available wins, then falls back)'),
      roles.map(([r, label]) => h('div', { class: 'row' }, h('div', { style: { width: '220px' } }, label),
        [0, 1, 2].map((k) => sel([['', '—'], ...ids], (s.routing[r] || [])[k] || '', (v) => { const arr = [...(s.routing[r] || [])]; arr[k] = v; s.routing[r] = arr.filter(Boolean); saveS(); }))))),
    h('h2', { style: { marginTop: '20px' } }, 'Providers'),
    h('div', { class: 'col' }, s.providers.map((p) => {
      const res = h('span', { class: 'small' });
      return h('div', { class: `card col prov ${p.enabled ? 'on' : ''}` },
        h('div', { class: 'row' }, h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: p.enabled, onchange: (e) => { p.enabled = e.target.checked; saveS(); RENDER.engines(); } }), h('b', {}, p.name)),
          h('span', { class: 'chip' }, p.kind), p.paid ? h('span', { class: 'chip err' }, 'pay per token') : h('span', { class: 'chip ok' }, 'no per-call cost'), p.vision ? h('span', { class: 'chip info' }, 'vision') : null,
          h('span', { class: 'grow' }), res,
          h('button', { class: 'btn sm', onclick: async (e) => { e.target.disabled = true; res.textContent = 'testing…'; try { const r = await call('llm:test', p.id); res.textContent = r.ok ? `✓ ${r.ms} ms` : `✗ ${r.error || r.text}`; } catch (err) { res.textContent = '✗ ' + err.message.slice(0, 90); } finally { e.target.disabled = false; } } }, 'Test')),
        p.note ? h('div', { class: 'small dim' }, p.note) : null,
        h('div', { class: 'grid g4' },
          field('Name', txt(p.name, (v) => { p.name = v; }, { onchange: saveS })),
          p.kind === 'cli' ? field('Command', txt(p.command, (v) => { p.command = v; }, { onchange: saveS })) : field('Base URL', txt(p.baseUrl, (v) => { p.baseUrl = v; }, { onchange: saveS })),
          p.kind === 'cli' ? field('Args', txt((p.args || []).join(' '), (v) => { p.args = v.split(' ').filter(Boolean); }, { onchange: saveS })) : field('API key', h('input', { type: 'password', value: p.apiKey || '', onchange: (e) => { p.apiKey = e.target.value; saveS(); } })),
          field('Model', txt(p.model, (v) => { p.model = v; }, { onchange: saveS, placeholder: p.kind === 'cli' ? 'opus / sonnet / blank' : 'model id' }))),
        h('div', { class: 'row small' },
          h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: !!p.vision, onchange: (e) => { p.vision = e.target.checked; saveS(); } }), 'vision'),
          h('label', { class: 'chk' }, h('input', { type: 'checkbox', checked: !!p.paid, onchange: (e) => { p.paid = e.target.checked; saveS(); } }), 'pay per token'),
          field('Timeout s', h('input', { type: 'number', value: p.timeoutSec || 600, style: { width: '90px' }, onchange: (e) => { p.timeoutSec = Number(e.target.value); saveS(); } })),
          h('span', { class: 'grow' }), h('button', { class: 'btn sm ghost danger', onclick: () => { s.providers = s.providers.filter((x) => x !== p); saveS(); RENDER.engines(); } }, 'Remove')));
    })),
    h('div', { class: 'row', style: { marginTop: '12px' } },
      h('button', { class: 'btn', onclick: () => { s.providers.push({ id: `p_${Date.now()}`, name: 'New OpenAI-compatible', kind: 'openai', enabled: false, baseUrl: 'http://127.0.0.1:8000/v1', apiKey: '', model: '', timeoutSec: 600 }); saveS(); RENDER.engines(); } }, '+ OpenAI-compatible'),
      h('button', { class: 'btn', onclick: () => { s.providers.push({ id: `p_${Date.now()}`, name: 'New CLI', kind: 'cli', enabled: false, command: 'claude', args: ['-p', '--output-format', 'json', '--model', '{{model}}'], model: 'sonnet', promptVia: 'stdin', timeoutSec: 900 }); saveS(); RENDER.engines(); } }, '+ Subscription CLI'),
      h('button', { class: 'btn', onclick: () => { s.providers.push({ id: `p_${Date.now()}`, name: 'Anthropic API', kind: 'anthropic', enabled: false, paid: true, vision: true, baseUrl: 'https://api.anthropic.com', apiKey: '', model: 'claude-opus-5-5', timeoutSec: 600 }); saveS(); RENDER.engines(); } }, '+ Anthropic API')));
};

// ------------------------------------------------------------------ settings
RENDER.settings = async () => {
  const pane = $('#pane-settings');
  const s = S.settings; const c = s.channel;
  const saveS = async () => { S.settings = await call('settings:save', s); toast('Saved'); };
  const chars = await call('characters:list');
  const pick = (key, props) => h('button', { class: 'btn sm', onclick: async () => { const p = await call('paths:pick', { properties: props }); if (p) { s[key] = p; saveS(); RENDER.settings(); } } }, 'Browse');
  pane.innerHTML = '';
  pane.append(h('h1', {}, 'Settings'), h('p', { class: 'sub' }, 'Paths, channel identity and render quality.'),
    h('div', { class: 'grid g2' },
      h('div', { class: 'card col' }, h('h2', {}, 'Tools'),
        h('div', { class: 'row' }, h('label', { class: 'f grow' }, 'Blender 5.1+ executable', txt(s.blenderPath, (v) => { s.blenderPath = v; }, { onchange: saveS })), pick('blenderPath', ['openFile'])),
        h('div', { class: 'row' }, h('label', { class: 'f grow' }, 'Python', txt(s.pythonPath, (v) => { s.pythonPath = v; }, { onchange: saveS })), h('label', { class: 'f grow' }, 'uv', txt(s.uvPath, (v) => { s.uvPath = v; }, { onchange: saveS }))),
        h('div', { class: 'row' }, h('label', { class: 'f grow' }, 'Workspace (episodes live here)', txt(s.workspace, (v) => { s.workspace = v; }, { onchange: saveS })), pick('workspace', ['openDirectory'])),
        h('div', { class: 'row' }, field('Render size', sel(['540x960', '720x1280', '1080x1920'], s.render.res, (v) => { s.render.res = v; saveS(); })), field('EEVEE samples', h('input', { type: 'number', value: s.render.samples, min: 1, max: 64, style: { width: '90px' }, onchange: (e) => { s.render.samples = Number(e.target.value); saveS(); } }))),
        h('div', { class: 'small dim' }, '540x960 + nearest-neighbour upscale is the pixel look. Higher sizes look smoother and render slower.')),
      h('div', { class: 'card col' }, h('h2', {}, 'Channel'),
        h('div', { class: 'grid g2' }, field('Channel name', txt(c.name, (v) => { c.name = v; }, { onchange: saveS })), field('Handle (shown on video)', txt(c.handle, (v) => { c.handle = v; }, { onchange: saveS, placeholder: '@yourchannel' }))),
        field('Niche / format brief (the AI reads this)', h('textarea', { rows: 4, onchange: (e) => { c.niche = e.target.value; saveS(); } }, c.niche)),
        h('div', { class: 'grid g4' },
          field('Host', sel(chars.filter((x) => x.built).map((x) => x.id), chars.find((x) => x.id === c.host && x.built) ? c.host : (chars.find((x) => x.built) || {}).id, (v) => { c.host = v; saveS(); }, { title: 'Only characters that are built and rigged can host. ' + chars.filter((x) => !x.built).map((x) => x.id).join(', ') + ' not ready yet.' })),
          field('Voice', sel(S.vocab.voices, c.voice, (v) => { c.voice = v; saveS(); })),
          field('Rate', txt(c.rate, (v) => { c.rate = v; }, { onchange: saveS })),
          field('Pitch', txt(c.pitch, (v) => { c.pitch = v; }, { onchange: saveS }))),
        chars.some((x) => !x.built) ? h('div', { class: 'small dim' }, `Not ready to host yet (no skeleton): ${chars.filter((x) => !x.built).map((x) => x.id).join(', ')}.`) : null)));
};

// ------------------------------------------------------------------ boot
(async () => {
  try {
    S.settings = await call('settings:get');
    S.vocab = await call('vocab:get');
    S.jobs = await call('jobs:list');
    renderPill();
    go('dashboard');
  } catch (e) { document.body.append(h('pre', {}, 'Startup failed: ' + e.message)); }
})();
