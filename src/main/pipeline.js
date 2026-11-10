/**
 * pipeline.js — AI operations (ideas, script, review) + the sequential job queue that runs engine stages.
 *
 * One job at a time: Blender renders own the GPU. Jobs persist in jobs.json so the queue survives restarts
 * (a job that was running when the app quit is re-queued). Every job ends with an optional Telegram ping.
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const https = require('https');
const store = require('./store');
const llm = require('./llm');
const episodes = require('./episodes');
const prompts = require('./prompts');

let emit = () => {};
function setEmitter(fn) { emit = fn; }

// ------------------------------------------------------------------ ideas
function ideas() { return store.read('ideas').items; }
function saveIdeas(items) { store.write('ideas', { items }); emit('ideas', items); return items; }

async function generateIdeas(count = 5, theme = '', opts = {}) {
  const existing = ideas().map((i) => i.title).concat(episodes.list().map((e) => e.title));
  const p = prompts.ideaPrompt(count, theme, existing);
  const r = await llm.chat('ideas', p.system, [{ role: 'user', content: p.user }], opts);
  const j = llm.extractJson(r.text);
  const now = Date.now();
  const fresh = (j.ideas || j || []).map((x, k) => ({ ...x, id: `idea_${now}_${k}`, status: 'new', created: now, by: r.provider }));
  saveIdeas([...fresh, ...ideas()]);
  return fresh;
}

function setIdeaStatus(id, status, extra = {}) {
  const items = ideas().map((i) => (i.id === id ? { ...i, status, ...extra } : i));
  saveIdeas(items);
  return items.find((i) => i.id === id);
}

// ------------------------------------------------------------------ script
async function writeScript({ ideaId, topic }, opts = {}) {
  const idea = ideaId ? ideas().find((i) => i.id === ideaId) : { title: topic, topic };
  if (!idea) throw new Error('unknown idea ' + ideaId);
  const p = prompts.scriptPrompt(idea);
  const r = await llm.chat('script', p.system, [{ role: 'user', content: p.user }], opts);
  const raw = llm.extractJson(r.text);
  const { episode, fixes } = episodes.validate(raw);
  const id = episodes.create({ title: episode.title || idea.title, topic: episode.topic || idea.topic });
  const s = store.read('settings');
  const full = { ...episodes.get(id), ...episode, id, characters: { host: s.channel.host, ...(episode.characters || {}) } };
  full.script_by = r.provider;
  full.script_fixes = fixes;
  episodes.save(id, full);
  if (ideaId) setIdeaStatus(ideaId, 'used', { episode: id });
  emit('episodes', episodes.list());
  return { id, fixes, provider: r.provider };
}

// ------------------------------------------------------------------ review
async function reviewStills(id, opts = {}) {
  const sum = episodes.summary(id);
  if (!sum.contact) throw new Error('no contact sheet yet — run stills first');
  const ep = episodes.get(id);
  const tl = JSON.parse(fs.readFileSync(path.join(sum.dir, 'timeline.json'), 'utf8'));
  const p = prompts.reviewPrompt(ep, tl.shots);
  const r = await llm.chat('review', p.system, [{ role: 'user', content: p.user }], { ...opts, images: [sum.contact] });
  const j = llm.extractJson(r.text);
  j.by = r.provider;
  j.at = Date.now();
  j.shots = tl.shots;
  fs.writeFileSync(path.join(sum.dir, 'review.json'), JSON.stringify(j, null, 1));
  return j;
}

/** Staging auto-fix: feed review.json issues to the Director, apply staging-only edits (never text), validate, save. */
const STAGING_FIELDS = ['shot', 'shots', 'host', 'focus', 'prop', 'card', 'label', 'cat'];
async function autoFix(id, opts = {}) {
  const dir = episodes.summary(id).dir;
  const rp = path.join(dir, 'review.json');
  if (!fs.existsSync(rp)) throw new Error('no review yet - run review_stills first');
  const review = JSON.parse(fs.readFileSync(rp, 'utf8'));
  if (!(review.issues || []).length) return { changed: 0, note: 'no QA issues' };
  const ep = episodes.get(id);
  const p = prompts.restagePrompt(ep, review);
  const r = await llm.chat('script', p.system, [{ role: 'user', content: p.user }], opts);
  const j = llm.extractJson(r.text);
  let changed = 0;
  for (const e of j.edits || []) {
    const b = ep.beats[e.index];
    if (!b || !e.set || typeof e.set !== 'object') continue;
    for (const [k, v] of Object.entries(e.set)) {
      if (!STAGING_FIELDS.includes(k)) continue;
      if (k === 'shot') delete b.shots;
      if (k === 'shots') delete b.shot;
      if (k === 'host' && v && typeof v === 'object') b.host = { ...(b.host || {}), ...v };
      else if (v === null) delete b[k];
      else b[k] = v;
      changed++;
    }
  }
  const { episode, fixes } = episodes.validate(ep);
  episode.staging_fixes = [...(episode.staging_fixes || []), { at: Date.now(), by: r.provider, score_before: review.score, notes: j.notes || '', changed }];
  episodes.save(id, episode);
  return { changed, fixes, notes: j.notes || '', provider: r.provider };
}

async function reviewAndFix(jobId, epId, opts, rounds) {
  let rv = await reviewStills(epId, opts);
  appendLog(jobId, `QA review: score ${rv.score}; ${(rv.issues || []).map((i) => `#${i.shot} ${i.problem}`).join(' | ') || 'no issues'}`);
  for (let k = 0; k < rounds && (rv.issues || []).length && (rv.ok === false || rv.score < 8); k++) {
    const f = await autoFix(epId, opts);
    appendLog(jobId, `auto-fix ${k + 1}/${rounds}: ${f.changed} staging changes${f.notes ? ` (${f.notes})` : ''}`);
    if (!f.changed) break;
    await runStage(jobId, epId, 'stills');
    rv = await reviewStills(epId, opts);
    appendLog(jobId, `QA review after fix: score ${rv.score}; ${(rv.issues || []).length} issues`);
  }
  return rv;
}

// ------------------------------------------------------------------ notifications
function telegram(text) {
  const t = store.read('settings').automations.telegram;
  if (!t.enabled || !t.botToken || !t.chatId) return;
  const body = JSON.stringify({ chat_id: t.chatId, text: `🎬 Acre Content Studio\n${text}` });
  const req = https.request({ hostname: 'api.telegram.org', path: `/bot${t.botToken}/sendMessage`, method: 'POST',
    headers: { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) } });
  req.on('error', () => {});
  req.end(body);
}

// ------------------------------------------------------------------ job queue
let running = null;
let child = null;

function jobs() { return store.read('jobs').items; }
function saveJobs(items) { store.write('jobs', { items: items.slice(-300) }); emit('jobs', items.slice(-300).map(({ log, ...j }) => j)); }
function updateJob(id, patch) {
  const items = jobs().map((j) => (j.id === id ? { ...j, ...patch } : j));
  saveJobs(items);
  return items.find((j) => j.id === id);
}

/** kind: 'stage' {episodeId, stage} | 'produce' {ideaId|topic} | 'script' {...} | 'review' {episodeId} */
function enqueue(kind, args, label) {
  const job = { id: `job_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`, kind, args, label: label || `${kind} ${args.stage || ''} ${args.episodeId || args.topic || ''}`.trim(),
    state: 'queued', progress: 0, message: '', log: [], created: Date.now() };
  saveJobs([...jobs(), job]);
  setImmediate(pump);
  return job;
}

function cancel(id) {
  const j = jobs().find((x) => x.id === id);
  if (!j) return null;
  if (j.state === 'queued') return updateJob(id, { state: 'cancelled', ended: Date.now() });
  if (j.state === 'running' && running === id && child) {
    try { spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true }); } catch { child.kill(); }
    return updateJob(id, { state: 'cancelled', ended: Date.now() });
  }
  return j;
}

function appendLog(id, line) {
  const items = jobs();
  const j = items.find((x) => x.id === id);
  if (!j) return;
  j.log = [...(j.log || []), line].slice(-400);
  const m = /^@@PROGRESS ([\d.]+) (.*)$/.exec(line);
  if (m) { j.progress = Number(m[1]); j.message = m[2]; }
  // save at most ~2x/s to keep the disk calm during renders
  const now = Date.now();
  if (!appendLog.t || now - appendLog.t > 500 || m) { appendLog.t = now; saveJobs(items); }
  emit('joblog', { id, line, progress: j.progress, message: j.message });
}

function runStage(jobId, epId, stage, extra = []) {
  const s = store.read('settings');
  const args = [path.join(store.APP_ROOT, 'engine', 'run.py'), stage, episodes.dirOf(epId), '--blender', s.blenderPath, '--uv', s.uvPath, ...extra];
  return runCmd(jobId, s.pythonPath, args, stage);
}

function runCmd(jobId, cmd, args, what) {
  return new Promise((resolve, reject) => {
    appendLog(jobId, `$ ${cmd} ${args.join(' ')}`);
    child = spawn(cmd, args, { cwd: store.APP_ROOT, windowsHide: true, env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' } });
    let buf = '';
    const onData = (d) => {
      buf += d.toString();
      const lines = buf.split(/\r?\n/);
      buf = lines.pop();
      for (const l of lines) if (l.trim()) appendLog(jobId, l);
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    child.on('error', (e) => reject(e));
    child.on('close', (code) => {
      child = null;
      if (buf.trim()) appendLog(jobId, buf);
      if (code === 0) resolve(); else reject(new Error(`${what} failed (exit ${code})`));
    });
  });
}

async function runJob(job) {
  const auto = !!job.args.automation;
  const opts = { automation: auto };
  if (job.kind === 'stage') {
    await runStage(job.id, job.args.episodeId, job.args.stage, job.args.extra || []);
    return `${job.args.stage} done for ${job.args.episodeId}`;
  }
  if (job.kind === 'script') {
    appendLog(job.id, 'writing script…');
    const r = await writeScript(job.args, opts);
    appendLog(job.id, `script ready: ${r.id} (${r.provider}); fixes: ${r.fixes.join('; ') || 'none'}`);
    return `script written: ${r.id}`;
  }
  if (job.kind === 'charbuild') {
    const c = require('./characters').buildCommand(job.args.id);
    await runCmd(job.id, c.cmd, c.args, 'character build');
    return `character ${job.args.id} built`;
  }
  if (job.kind === 'autofix') {
    const rv = await reviewAndFix(job.id, job.args.episodeId, opts, job.args.rounds || 1);
    return `staging fixed, review score ${rv.score}`;
  }
  if (job.kind === 'review') {
    const r = await reviewStills(job.args.episodeId, opts);
    appendLog(job.id, `review: score ${r.score}, ${r.issues?.length || 0} issues`);
    return `review score ${r.score}`;
  }
  if (job.kind === 'produce') {
    let epId = job.args.episodeId;
    if (!epId) {
      appendLog(job.id, '@@PROGRESS 0.02 script: writing');
      const r = await writeScript(job.args, opts);
      epId = r.id;
      updateJob(job.id, { args: { ...job.args, episodeId: epId } });
      appendLog(job.id, `script ready: ${epId} (${r.provider})`);
    }
    for (const st of ['audio', 'character', 'props', 'stills']) await runStage(job.id, epId, st);
    const au = store.read('settings').automations;
    if (au.reviewStills) {
      try {
        await reviewAndFix(job.id, epId, opts, au.autoFixRounds ?? 1);
      } catch (e) { appendLog(job.id, `QA review/fix skipped: ${e.message}`); }
    }
    for (const st of ['render', 'compose']) await runStage(job.id, epId, st);
    return `episode finished: ${epId}`;
  }
  throw new Error('unknown job kind ' + job.kind);
}

async function pump() {
  if (running) return;
  const next = jobs().find((j) => j.state === 'queued');
  if (!next) return;
  running = next.id;
  updateJob(next.id, { state: 'running', started: Date.now() });
  try {
    const msg = await runJob(next);
    const cur = jobs().find((j) => j.id === next.id);
    if (cur && cur.state !== 'cancelled') {
      updateJob(next.id, { state: 'done', progress: 1, message: msg, ended: Date.now() });
      telegram(`✅ ${next.label}\n${msg}`);
    }
  } catch (e) {
    const cur = jobs().find((j) => j.id === next.id);
    if (cur && cur.state !== 'cancelled') {
      appendLog(next.id, 'ERROR ' + e.message);
      updateJob(next.id, { state: 'error', message: e.message.slice(0, 400), ended: Date.now() });
      telegram(`❌ ${next.label}\n${e.message.slice(0, 300)}`);
    }
  } finally {
    running = null;
    emit('episodes', episodes.list());
    setImmediate(pump);
  }
}

function resumeOnStart() {
  const items = jobs().map((j) => (j.state === 'running' ? { ...j, state: 'queued', message: 're-queued after restart' } : j));
  saveJobs(items);
  setImmediate(pump);
}

function status() {
  const items = jobs();
  return { running: items.find((j) => j.id === running) || null, queued: items.filter((j) => j.state === 'queued'),
    recent: items.filter((j) => ['done', 'error', 'cancelled'].includes(j.state)).slice(-10) };
}

// ------------------------------------------------------------------ automations (nightly + autopilot)
let lastNightly = '';
function tickAutomations() {
  const a = store.read('settings').automations;
  const now = new Date();
  const hhmm = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
  const day = now.toISOString().slice(0, 10);
  if (a.nightly.enabled && hhmm === a.nightly.time && lastNightly !== day) {
    lastNightly = day;
    const approved = ideas().filter((i) => i.status === 'approved').slice(0, a.nightly.count);
    for (const idea of approved) {
      setIdeaStatus(idea.id, 'queued');
      enqueue('produce', { ideaId: idea.id, automation: true }, `nightly: ${idea.title}`);
    }
    if (!approved.length) telegram('Nightly run: no approved ideas in the backlog.');
  }
  if (a.autopilot && !running && !jobs().some((j) => j.state === 'queued')) {
    const idea = ideas().find((i) => i.status === 'approved');
    if (idea) {
      setIdeaStatus(idea.id, 'queued');
      enqueue('produce', { ideaId: idea.id, automation: true }, `autopilot: ${idea.title}`);
    }
  }
}

module.exports = {
  setEmitter, ideas, saveIdeas, generateIdeas, setIdeaStatus, writeScript, reviewStills, autoFix,
  enqueue, cancel, jobs, status, resumeOnStart, tickAutomations, telegram,
};
