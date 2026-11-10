/**
 * characters.js — character library (assets/characters/<id>/) + recipes (assets/characters/recipes/<id>.json).
 */
const fs = require('fs');
const path = require('path');
const store = require('./store');

const DIR = path.join(store.APP_ROOT, 'assets', 'characters');
const RECIPES = path.join(DIR, 'recipes');

function readJson(f) { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return null; } }

function list() {
  const ids = new Set();
  if (fs.existsSync(RECIPES)) for (const f of fs.readdirSync(RECIPES)) if (f.endsWith('.json')) ids.add(f.slice(0, -5));
  if (fs.existsSync(DIR)) for (const d of fs.readdirSync(DIR, { withFileTypes: true })) if (d.isDirectory() && d.name !== 'recipes') ids.add(d.name);
  return [...ids].sort().map((id) => {
    const recipe = readJson(path.join(RECIPES, `${id}.json`));
    const meta = readJson(path.join(DIR, id, 'character.json'));
    const pic = (n) => (fs.existsSync(path.join(DIR, id, n)) ? path.join(DIR, id, n) : null);
    const ref = recipe && recipe.reference ? path.join(store.APP_ROOT, recipe.reference) : null;
    return {
      id, name: (recipe && recipe.name) || (meta && meta.name) || id, built: !!meta, hasRecipe: !!recipe,
      base: recipe && recipe.base_vrm, kind: (recipe && recipe.kind) || 'vroid', preview: pic('preview.png'), face: pic('p_face.png'), side: pic('p_side.png'),
      reference: ref && fs.existsSync(ref) ? ref : null,
      builtAt: meta ? fs.statSync(path.join(DIR, id, 'character.json')).mtimeMs : null,
    };
  });
}

function recipe(id) { return readJson(path.join(RECIPES, `${id}.json`)); }

function saveRecipe(id, obj) {
  fs.mkdirSync(RECIPES, { recursive: true });
  fs.writeFileSync(path.join(RECIPES, `${id}.json`), JSON.stringify(obj, null, 1));
  return list().find((c) => c.id === id);
}

function rebuild(id) {
  const pipeline = require('./pipeline');
  if (!recipe(id)) throw new Error(`no recipe for ${id}`);
  return pipeline.enqueue('charbuild', { id }, `build character: ${id}`);
}

function buildCommand(id) {
  const s = store.read('settings');
  return {
    cmd: s.blenderPath,
    // projected characters (exact-likeness mesh from reference art) are rigged, not built from a VRoid base
    args: ['--background', '--python', path.join(store.APP_ROOT, 'engine', 'blender',
      (recipe(id) || {}).kind === 'projected' ? 'rig_projected.py' : 'character_build.py'), '--',
      path.join(RECIPES, `${id}.json`), path.join(DIR, id), '--preview'],
  };
}

function baseModels() {
  const d = path.join(store.APP_ROOT, 'assets', 'vrm');
  return fs.existsSync(d) ? fs.readdirSync(d).filter((f) => f.endsWith('.vrm')).map((f) => `assets/vrm/${f}`) : [];
}

module.exports = { list, recipe, saveRecipe, rebuild, buildCommand, baseModels, DIR, RECIPES };
