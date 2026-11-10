/**
 * episodes.js — workspace/episodes/<id>/ management + staging validation against engine/vocab.json.
 */
const fs = require('fs');
const path = require('path');
const store = require('./store');

const VOCAB = JSON.parse(fs.readFileSync(path.join(store.APP_ROOT, 'engine', 'vocab.json'), 'utf8'));

function root() {
  const d = path.join(store.read('settings').workspace, 'episodes');
  fs.mkdirSync(d, { recursive: true });
  return d;
}

function dirOf(id) { return path.join(root(), id); }

function slug(s) {
  return String(s || 'episode').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 40) || 'episode';
}

function nextId(title) {
  const ids = list().map((e) => e.id);
  let n = 1;
  for (const id of ids) { const m = /^ep(\d+)_/.exec(id); if (m) n = Math.max(n, Number(m[1]) + 1); }
  return `ep${String(n).padStart(2, '0')}_${slug(title)}`;
}

function readJson(f, dflt = null) { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return dflt; } }

function summary(id) {
  const d = dirOf(id);
  const ep = readJson(path.join(d, 'episode.json'), {});
  const st = readJson(path.join(d, 'status.json'), {});
  const tl = readJson(path.join(d, 'timeline.json'), null);
  const has = (f) => fs.existsSync(path.join(d, f));
  const frames = fs.existsSync(path.join(d, 'frames')) ? fs.readdirSync(path.join(d, 'frames')).filter((f) => f.endsWith('.png')).length : 0;
  return {
    id, dir: d, title: ep.title || id, topic: ep.topic || '', beats: (ep.beats || []).length,
    duration: tl ? tl.duration : null, status: st, hasAudio: has('mix.wav'), hasStills: has('contact.png'),
    frames, framesNeeded: tl ? Math.ceil(tl.duration * tl.fps) : null, hasFinal: has('final.mp4'),
    final: has('final.mp4') ? path.join(d, 'final.mp4') : null, thumb: has('thumb.jpg') ? path.join(d, 'thumb.jpg') : (has('contact.png') ? path.join(d, 'contact.png') : null),
    contact: has('contact.png') ? path.join(d, 'contact.png') : null, review: readJson(path.join(d, 'review.json'), null),
    updated: Math.max(...['episode.json', 'status.json', 'final.mp4'].map((f) => (has(f) ? fs.statSync(path.join(d, f)).mtimeMs : 0))),
  };
}

function list() {
  return fs.readdirSync(root(), { withFileTypes: true })
    .filter((e) => e.isDirectory() && fs.existsSync(path.join(root(), e.name, 'episode.json')))
    .map((e) => summary(e.name))
    .sort((a, b) => b.id.localeCompare(a.id));
}

function get(id) { return readJson(path.join(dirOf(id), 'episode.json')); }

function save(id, ep) {
  fs.mkdirSync(dirOf(id), { recursive: true });
  const f = path.join(dirOf(id), 'episode.json');
  fs.writeFileSync(f + '.tmp', JSON.stringify(ep, null, 2));
  fs.renameSync(f + '.tmp', f);
  return summary(id);
}

function readyHost(id) {
  // only built (rigged) characters can host; fall back to the first built one
  const dir = path.join(store.APP_ROOT, 'assets', 'characters');
  const ok = (x) => x && fs.existsSync(path.join(dir, x, 'character.blend'));
  if (ok(id)) return id;
  const any = fs.existsSync(dir) ? fs.readdirSync(dir).find(ok) : null;
  return any || id;
}

function create({ title, topic, beats }) {
  const s = store.read('settings');
  const id = nextId(title || topic);
  const ep = {
    id, title: title || topic || 'New episode', topic: topic || '', format: 'host_explainer',
    characters: { host: readyHost(s.channel.host) }, props: [], set: 'studio',
    voice: { narrator: s.channel.voice, rate: s.channel.rate, pitch: s.channel.pitch },
    music: { bpm: 104, seed: Math.floor(Math.random() * 1000), key: 60 + Math.floor(Math.random() * 5) },
    render: { ...s.render }, sources: [], beats: beats || [],
  };
  save(id, ep);
  return id;
}

function remove(id) {
  const trash = path.join(store.read('settings').workspace, 'trash');
  fs.mkdirSync(trash, { recursive: true });
  fs.renameSync(dirOf(id), path.join(trash, `${id}_${Date.now()}`));
}

/** Clamp an AI-written episode to the vocabulary. Returns { episode, fixes[] }. */
function validate(ep) {
  const fixes = [];
  if (!Array.isArray(ep.beats) || !ep.beats.length) throw new Error('episode has no beats');
  if (ep.characters && ep.characters.host && readyHost(ep.characters.host) !== ep.characters.host) {
    fixes.push(`host ${ep.characters.host} is not rigged yet -> ${readyHost(ep.characters.host)}`);
    ep.characters.host = readyHost(ep.characters.host);
  }
  const set = VOCAB.sets[ep.set] ? ep.set : 'studio';
  if (set !== ep.set) { fixes.push(`set ${ep.set} -> studio`); ep.set = set; }
  const S = VOCAB.sets[set];
  const pick = (v, allowed, dflt, what) => {
    if (v === undefined || v === null || allowed.includes(v)) return v;
    if (typeof v === 'number') return v;
    fixes.push(`${what} "${v}" -> "${dflt}"`);
    return dflt;
  };
  // props: "cat" (procedural) + objects. v0.3: {id, kit, params, at, scale, yaw} = procedural low-poly kit model
  // (engine/blender/abs_kit.py, real size); legacy {id, describe, at, height} = image-to-3D (last resort). max 6.
  ep.props = (Array.isArray(ep.props) ? ep.props : []).filter((p) => p === 'cat' || (p && typeof p === 'object' && p.id && (p.kit || p.describe)));
  const gen = ep.props.filter((p) => typeof p === 'object');
  if (gen.length > 6) { fixes.push(`${gen.length - 6} extra props dropped`); ep.props = ep.props.filter((p) => typeof p !== 'object' || gen.indexOf(p) < 6); }
  const propIds = ep.props.filter((p) => typeof p === 'object').map((p) => {
    p.id = String(p.id).toLowerCase().replace(/[^a-z0-9_]+/g, '_');
    if (p.at !== undefined && typeof p.at === 'string') p.at = pick(p.at, S.anchors, 'center', `prop ${p.id} at`);
    if (p.kit) {
      p.kit = String(p.kit).toLowerCase().replace(/[^a-z0-9_]+/g, '_');
      if (p.params && typeof p.params !== 'object') delete p.params;
      if (p.scale !== undefined) p.scale = Math.min(3, Math.max(0.1, Number(p.scale) || 1));
    } else p.height = Math.min(4, Math.max(0.1, Number(p.height) || 1));
    return p.id;
  });
  const usesCat = ep.props.includes('cat') || ep.beats.some((b) => b && b.cat);
  if (usesCat && !ep.props.includes('cat')) ep.props.push('cat');
  if (!usesCat) delete ep.cat_palette;
  const shotOk = S.shots.filter((x) => usesCat || !['cat', 'cat_low'].includes(x));
  ep.beats = ep.beats.filter((b) => b && (b.text || b.hold));
  ep.beats.forEach((b, i) => {
    if (b.shot) b.shot = pick(b.shot, shotOk, 'wide', `beat ${i} shot`);
    if (Array.isArray(b.shots)) b.shots = b.shots.map((x) => pick(x, shotOk, 'wide', `beat ${i} shot`));
    if (b.arrows !== undefined) {
      b.arrows = (Array.isArray(b.arrows) ? b.arrows : []).filter((a) => a && a.from !== undefined && a.to !== undefined).slice(0, 4);
      if (!b.arrows.length) delete b.arrows;
    }
    if (b.focus !== undefined) b.focus = pick(b.focus, [...propIds, ...(usesCat ? ['cat'] : [])], propIds[0], `beat ${i} focus`);
    if (b.prop && typeof b.prop === 'object') {
      for (const [k, v] of Object.entries(b.prop)) {
        if (!propIds.includes(k)) { delete b.prop[k]; fixes.push(`beat ${i} action for unknown prop ${k} dropped`); continue; }
        b.prop[k] = pick(v, VOCAB.prop_actions, 'still', `beat ${i} prop ${k}`);
      }
    }
    if (b.host) {
      b.host.pose = pick(b.host.pose, VOCAB.host_poses, 'idle', `beat ${i} pose`);
      b.host.face = pick(b.host.face, VOCAB.host_faces, 'smile', `beat ${i} face`);
      if (b.host.look !== undefined && typeof b.host.look !== 'number') b.host.look = pick(b.host.look, ['camera', ...propIds, ...(usesCat ? ['cat'] : [])], 'camera', `beat ${i} look`);
    }
    if (b.cat && !usesCat) delete b.cat;
    if (b.cat) {
      b.cat.action = pick(b.cat.action, VOCAB.cat_actions, 'sit', `beat ${i} cat action`);
      for (const k of ['at', 'to']) if (b.cat[k] !== undefined && typeof b.cat[k] === 'string') b.cat[k] = pick(b.cat[k], S.anchors, 'bench_mid', `beat ${i} cat.${k}`);
      if (b.cat.face !== undefined && typeof b.cat.face !== 'number') b.cat.face = pick(b.cat.face, ['camera', 'host'], 'camera', `beat ${i} cat face`);
    }
    if (b.sfx) {
      b.sfx = (Array.isArray(b.sfx) ? b.sfx : [b.sfx]).filter((c) => {
        const k = Array.isArray(c) ? c[0] : c;
        const ok = VOCAB.sfx.includes(k);
        if (!ok) fixes.push(`beat ${i} sfx "${k}" dropped`);
        return ok;
      });
    }
    if (b.label && b.label.length > 28) { b.label = b.label.slice(0, 28); fixes.push(`beat ${i} label trimmed`); }
    if (b.card) b.card = String(b.card).toUpperCase().slice(0, 18);
  });
  return { episode: ep, fixes };
}

module.exports = { list, get, save, create, remove, summary, validate, dirOf, VOCAB, slug };
