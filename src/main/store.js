/**
 * store.js — JSON persistence in Electron userData (settings, ideas, overseer chat, jobs).
 * Writes are atomic (tmp + rename) and every getter deep-merges defaults so new keys appear
 * automatically after an update.
 */
const fs = require('fs');
const path = require('path');
const { app } = require('electron');

const APP_ROOT = path.resolve(__dirname, '..', '..');
const DEFAULT_BLENDER = 'C:\\Users\\rAzzren\\Apps\\blender-5.2.3-windows-x64\\blender.exe';

const NICHE_DEFAULT = 'Cute pixel-3D anime explainer shorts (9:16, 45-70 s). One cheerful host character explains how things work, science, history, nature and everyday curiosities, on a set that fits the topic, showing the objects she talks about. Facts must be real and checkable.';

const DEFAULTS = {
  settings: {
    workspace: path.join(APP_ROOT, 'workspace'),
    blenderPath: fs.existsSync(DEFAULT_BLENDER) ? DEFAULT_BLENDER : 'blender',
    pythonPath: 'python',
    uvPath: 'uv',
    channel: {
      name: 'Pixel Pals',
      handle: '',
      niche: NICHE_DEFAULT,
      host: 'astolfo_like',
      voice: 'en-US-AvaNeural',
      rate: '+4%',
      pitch: '+12Hz',
      language: 'English',
    },
    render: { res: '540x960', samples: 8 },
    providers: [
      {
        id: 'claude-sub', name: 'Claude subscription (Opus)', kind: 'cli', enabled: true, paid: false,
        command: 'claude', args: ['-p', '--output-format', 'json', '--model', '{{model}}'], model: 'opus',
        promptVia: 'stdin', vision: true, timeoutSec: 900,
        note: 'Uses the Claude Code CLI already signed in on this PC (Pro/Max subscription). Model box takes an alias: opus, sonnet, haiku.',
      },
      {
        id: 'lmstudio', name: 'LM Studio (local)', kind: 'openai', enabled: true, paid: false,
        baseUrl: 'http://127.0.0.1:1234/v1', apiKey: '', model: '', vision: false, timeoutSec: 600,
        note: 'Any OpenAI-compatible local server (LM Studio, llama.cpp, vLLM, Ollama /v1).',
      },
      {
        id: 'gemini-cli', name: 'Gemini CLI (subscription/free tier)', kind: 'cli', enabled: false, paid: false,
        command: 'gemini', args: ['-m', '{{model}}'], model: '', promptVia: 'stdin', vision: false, timeoutSec: 600,
      },
      {
        id: 'anthropic-api', name: 'Anthropic API (pay per token)', kind: 'anthropic', enabled: false, paid: true,
        baseUrl: 'https://api.anthropic.com', apiKey: '', model: 'claude-opus-5-5', vision: true, timeoutSec: 600,
      },
      {
        id: 'openrouter', name: 'OpenRouter (pay per token)', kind: 'openai', enabled: false, paid: true,
        baseUrl: 'https://openrouter.ai/api/v1', apiKey: '', model: '', vision: true, timeoutSec: 600,
      },
    ],
    routing: {
      ideas: ['claude-sub', 'lmstudio'],
      script: ['claude-sub', 'lmstudio'],
      overseer: ['claude-sub', 'lmstudio'],
      review: ['claude-sub'],
    },
    safety: { confirmPaid: true, allowPaidInAutomations: false },
    automations: {
      autopilot: false,
      reviewStills: true,
      autoFixRounds: 1,
      nightly: { enabled: false, time: '02:00', count: 1 },
      telegram: { enabled: false, botToken: '', chatId: '' },
    },
  },
  ideas: { items: [] },
  overseer: { messages: [] },
  jobs: { items: [] },
};

function dataDir() {
  const d = app.getPath('userData');
  fs.mkdirSync(d, { recursive: true });
  return d;
}

function isObj(v) { return v && typeof v === 'object' && !Array.isArray(v); }

function deepMerge(base, over) {
  if (!isObj(base) || !isObj(over)) return over === undefined ? base : over;
  const out = { ...base };
  for (const k of Object.keys(over)) out[k] = isObj(base[k]) && isObj(over[k]) ? deepMerge(base[k], over[k]) : over[k];
  return out;
}

const cache = {};

function read(name) {
  if (cache[name]) return cache[name];
  const file = path.join(dataDir(), `${name}.json`);
  let v = {};
  try { v = JSON.parse(fs.readFileSync(file, 'utf8')); } catch { /* first run */ }
  const merged = deepMerge(JSON.parse(JSON.stringify(DEFAULTS[name] || {})), v);
  if (name === 'settings') {
    // provider list: keep user's entries, append any new default providers by id
    const have = new Set((merged.providers || []).map((p) => p.id));
    for (const p of DEFAULTS.settings.providers) if (!have.has(p.id)) merged.providers.push(p);
    // v0.2: the channel is general now (no default cat)
    if (/demonstrated by a cat/.test(merged.channel.niche || '')) merged.channel.niche = NICHE_DEFAULT;
    delete merged.channel.catPalette;
  }
  cache[name] = merged;
  return merged;
}

function write(name, value) {
  cache[name] = value;
  const file = path.join(dataDir(), `${name}.json`);
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(value, null, 1));
  fs.renameSync(tmp, file);
  return value;
}

function patch(name, partial) {
  return write(name, deepMerge(read(name), partial));
}

module.exports = { read, write, patch, deepMerge, dataDir, APP_ROOT, DEFAULTS };
