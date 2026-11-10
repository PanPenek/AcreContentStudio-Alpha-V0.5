/**
 * main.js — Acre Content Studio (Electron main process).
 * Flags: --start-hidden (no visible window), --selftest (render each tab to selftest/*.png, then quit).
 */
const { app, BrowserWindow, ipcMain, shell, dialog, protocol, net: enet } = require('electron');
const path = require('path');
const fs = require('fs');
// Renamed from Acre Blender Studio (v0.5): keep the existing data folder when there is one.
{ const legacy = path.join(app.getPath('appData'), 'Acre Blender Studio'); if (fs.existsSync(legacy)) app.setPath('userData', legacy); }
const { pathToFileURL } = require('url');
const store = require('./store');
const llm = require('./llm');
const episodes = require('./episodes');
const pipeline = require('./pipeline');
const overseer = require('./overseer');
const characters = require('./characters');
const blender = require('./blender');

const ASK_I = process.argv.indexOf('--ask');
const ASK = ASK_I >= 0 ? process.argv[ASK_I + 1] : null;
const WAIT_JOBS = process.argv.includes('--wait-jobs');
const HIDDEN = process.argv.includes('--start-hidden') || process.argv.includes('--selftest') || !!ASK;
const SELFTEST = process.argv.includes('--selftest');
let win = null;

// One app instance owns the job queue. A second launch focuses the first; a second `--ask` is forwarded to it.
// --selftest is read-only (no queue pump) and may run beside a live instance.
const GOT_LOCK = SELFTEST ? true : app.requestSingleInstanceLock({ ask: ASK || null });
if (!GOT_LOCK) {
  if (ASK) console.log('[forwarded] Acre Content Studio is already running; the message went to its Overseer.');
  app.exit(0);
}
app.on('second-instance', (_e, _argv, _cwd, extra) => {
  if (extra && extra.ask) { overseer.turn(extra.ask).catch(() => {}); return; }
  if (win) { if (win.isMinimized()) win.restore(); win.show(); win.focus(); }
});

protocol.registerSchemesAsPrivileged([{ scheme: 'absfile', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true, bypassCSP: true } }]);

function send(channel, payload) {
  for (const w of BrowserWindow.getAllWindows()) if (!w.isDestroyed()) w.webContents.send('evt', { channel, payload });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1480, height: 940, minWidth: 1100, minHeight: 700, show: false, backgroundColor: '#1c1917',
    title: 'Acre Content Studio',
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: false },
  });
  win.removeMenu();
  win.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
  win.once('ready-to-show', () => { if (!HIDDEN) win.show(); });
  if (SELFTEST) win.webContents.once('did-finish-load', () => setTimeout(selftest, 1200));
}

async function selftest() {
  const out = path.join(store.APP_ROOT, 'selftest');
  fs.mkdirSync(out, { recursive: true });
  const tabs = ['dashboard', 'ideas', 'episodes', 'studio', 'overseer', 'characters', 'blender', 'automations', 'engines', 'settings'];
  win.setSize(1480, 940);
  for (const t of tabs) {
    await win.webContents.executeJavaScript(`window.__go && window.__go(${JSON.stringify(t)})`);
    await new Promise((r) => setTimeout(r, 900));
    // wait for images/videos to settle (max 4 s) and record broken ones
    for (let k = 0; k < 20; k++) {
      const pending = await win.webContents.executeJavaScript('[...document.images].filter((i) => !i.complete).length');
      if (!pending) break;
      await new Promise((r) => setTimeout(r, 200));
    }
    const broken = await win.webContents.executeJavaScript(`JSON.stringify({imgs: [...document.querySelectorAll('.pane.on img')].map((i) => [i.naturalWidth, decodeURIComponent(i.src).slice(-60)]), video: [...document.querySelectorAll('.pane.on video')].map((v) => [v.readyState, v.duration, v.error && v.error.message])})`);
    fs.appendFileSync(path.join(out, 'media.txt'), `${t}: ${broken}\n`);
    const img = await win.webContents.capturePage();
    fs.writeFileSync(path.join(out, `${t}.png`), img.toPNG());
  }
  const errs = await win.webContents.executeJavaScript('JSON.stringify(window.__errors || [])');
  fs.writeFileSync(path.join(out, 'errors.json'), errs);
  app.exit(0);
}

const handlers = {
  // settings
  'settings:get': () => store.read('settings'),
  'settings:save': (s) => { store.write('settings', s); return store.read('settings'); },
  'vocab:get': () => {
    // local voices (assets/voices/<id>/ref.wav, Ming-3.0-tts) appear first as "ming:<id>"
    const vd = path.join(store.APP_ROOT, 'assets', 'voices');
    const local = fs.existsSync(vd) ? fs.readdirSync(vd).filter((d) => fs.existsSync(path.join(vd, d, 'ref.wav'))).map((d) => `ming:${d}`) : [];
    return { ...episodes.VOCAB, voices: [...local, ...episodes.VOCAB.voices] };
  },
  'paths:open': (p) => shell.openPath(p),
  'paths:reveal': (p) => shell.showItemInFolder(p),
  'paths:pick': async (opts) => {
    const r = await dialog.showOpenDialog(win, opts || { properties: ['openFile'] });
    return r.canceled ? null : r.filePaths[0];
  },
  // engines
  'llm:test': (id) => llm.testProvider(id),
  // episodes
  'episodes:list': () => episodes.list(),
  'episodes:get': (id) => ({ episode: episodes.get(id), summary: episodes.summary(id) }),
  'episodes:save': ({ id, episode }) => {
    const { episode: ep, fixes } = episodes.validate(episode);
    return { summary: episodes.save(id, ep), fixes };
  },
  'episodes:create': (a) => episodes.create(a || {}),
  'episodes:remove': (id) => { episodes.remove(id); return episodes.list(); },
  'episodes:log': (id) => {
    const j = [...pipeline.jobs()].reverse().find((x) => (x.args || {}).episodeId === id);
    return j ? j.log || [] : [];
  },
  // jobs
  'jobs:enqueue': ({ kind, args, label }) => pipeline.enqueue(kind, args, label),
  'jobs:list': () => pipeline.jobs().map(({ log, ...j }) => j),
  'jobs:log': (id) => (pipeline.jobs().find((j) => j.id === id) || {}).log || [],
  'jobs:cancel': (id) => pipeline.cancel(id),
  'jobs:clear': () => { store.write('jobs', { items: pipeline.jobs().filter((j) => ['queued', 'running'].includes(j.state)) }); return true; },
  // ideas
  'ideas:list': () => pipeline.ideas(),
  'ideas:generate': ({ count, theme }) => pipeline.generateIdeas(count, theme),
  'ideas:status': ({ id, status }) => pipeline.setIdeaStatus(id, status),
  'ideas:save': (items) => pipeline.saveIdeas(items),
  'ideas:add': (idea) => pipeline.saveIdeas([{ id: `idea_${Date.now()}`, status: 'new', created: Date.now(), by: 'Patryk', ...idea }, ...pipeline.ideas()]),
  // ai ops
  'ai:script': (a) => pipeline.writeScript(a),
  'ai:review': (id) => pipeline.reviewStills(id),
  // overseer
  'overseer:history': () => overseer.history(),
  'overseer:send': (text) => { overseer.turn(text); return true; },
  'overseer:clear': () => { overseer.clear(); return true; },
  // characters
  'characters:list': () => characters.list(),
  'characters:recipe': (id) => characters.recipe(id),
  'characters:saveRecipe': ({ id, recipe }) => characters.saveRecipe(id, recipe),
  'characters:rebuild': (id) => characters.rebuild(id),
  'characters:bases': () => characters.baseModels(),
  // blender
  'blender:status': () => blender.status(),
  'blender:exec': (code) => blender.exec(code),
  'blender:open': (file) => blender.openGui(file),
  'blender:headless': ({ on, file }) => (on ? blender.startHeadless(file) : blender.stopHeadless()),
  'system:check': async () => {
    const s = store.read('settings');
    const { execFileSync } = require('child_process');
    const probe = (cmd, args) => { try { return execFileSync(cmd, args, { encoding: 'utf8', windowsHide: true, timeout: 20000 }).split('\n')[0].trim(); } catch (e) { return null; } };
    return {
      blender: fs.existsSync(s.blenderPath) ? s.blenderPath : null,
      python: probe(s.pythonPath, ['--version']),
      uv: probe(s.uvPath, ['--version']),
      ffmpeg: probe('ffmpeg', ['-version']),
      claude: probe(process.platform === 'win32' ? 'where' : 'which', ['claude']),
    };
  },
};

app.whenReady().then(() => {
  protocol.handle('absfile', (req) => {
    const p = decodeURIComponent(new URL(req.url).pathname.replace(/^\/+/, ''));
    return enet.fetch(pathToFileURL(p).toString());
  });
  for (const [ch, fn] of Object.entries(handlers)) {
    ipcMain.handle(ch, async (_e, arg) => {
      try { return { ok: true, data: await fn(arg) }; } catch (e) { return { ok: false, error: e.message }; }
    });
  }
  pipeline.setEmitter(send);
  overseer.setEmitter(send);
  if (ASK) return headlessAsk();
  createWindow();
  if (SELFTEST) return; // read-only: never touch the shared queue
  pipeline.resumeOnStart();
  setInterval(() => { try { pipeline.tickAutomations(); } catch (e) { console.error(e); } }, 30000);
});

/** `electron . --ask "<message>" [--wait-jobs]` : talk to the Overseer without a window (cron/Hermes friendly). */
async function headlessAsk() {
  const start = overseer.history().length;
  overseer.setEmitter((ch, m) => {
    if (ch === 'overseer') console.log(`[${m.role}] ${m.role === 'tool' ? m.content.slice(0, 600) : m.content}`);
  });
  pipeline.setEmitter((ch, m) => { if (ch === 'joblog' && /^@@PROGRESS|ERROR|WROTE|done/.test(m.line)) console.log('[job]', m.line.slice(0, 200)); });
  pipeline.resumeOnStart();
  await overseer.turn(ASK);
  if (WAIT_JOBS) {
    while (pipeline.status().running || pipeline.status().queued.length) await new Promise((r) => setTimeout(r, 3000));
  }
  console.log(`[done] ${overseer.history().length - start} new messages`);
  app.exit(0);
}

app.on('window-all-closed', () => { if (!ASK) app.quit(); });
