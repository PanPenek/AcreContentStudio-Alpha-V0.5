/**
 * llm.js — role-routed model calls with fallback.
 *
 * Provider kinds:
 *   cli        a signed-in agent CLI (Claude Code subscription, Gemini CLI) via clibridge — no per-token billing
 *   openai     any OpenAI-compatible HTTP endpoint (LM Studio, llama.cpp, OpenRouter, OpenAI)
 *   anthropic  Anthropic Messages API (API key, pay per token)
 *
 * Paid providers (paid:true) need an explicit OK: the first call per app session asks the user,
 * and automations skip them unless settings.safety.allowPaidInAutomations is on.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { dialog, BrowserWindow } = require('electron');
const store = require('./store');
const { runCli, probeCommand } = require('./clibridge');

const paidOk = new Set();

function providers() { return store.read('settings').providers || []; }
function byId(id) { return providers().find((p) => p.id === id); }

async function askPaid(p) {
  const s = store.read('settings');
  if (!p.paid || !s.safety.confirmPaid || paidOk.has(p.id)) return true;
  const win = BrowserWindow.getAllWindows()[0];
  const r = await dialog.showMessageBox(win, {
    type: 'question', buttons: ['Allow for this session', 'Block'], defaultId: 1, cancelId: 1,
    title: 'Paid model request',
    message: `PAID MODEL REQUEST: ${p.name} (${p.model || 'default model'}) is billed per token. Allow it for this app session?`,
  });
  if (r.response === 0) { paidOk.add(p.id); return true; }
  return false;
}

function writeImage(img) {
  if (!img) return null;
  if (fs.existsSync(img)) return img;
  const m = /^data:([^;]+);base64,(.*)$/s.exec(img);
  if (!m) return null;
  const f = path.join(os.tmpdir(), `abs-img-${Date.now()}-${Math.random().toString(36).slice(2, 7)}.png`);
  fs.writeFileSync(f, Buffer.from(m[2], 'base64'));
  return f;
}

function toDataUrl(img) {
  if (/^data:/.test(img)) return img;
  const ext = path.extname(img).slice(1).toLowerCase() || 'png';
  return `data:image/${ext === 'jpg' ? 'jpeg' : ext};base64,${fs.readFileSync(img).toString('base64')}`;
}

async function callProvider(p, system, messages, { images = [], timeoutSec } = {}) {
  const t = timeoutSec || p.timeoutSec || 600;
  if (p.kind === 'cli') {
    const parts = [];
    if (system) parts.push({ role: 'system', content: system });
    for (const m of messages) parts.push({ role: m.role, content: `${m.role === 'user' ? 'USER' : 'ASSISTANT'}:\n${m.content}` });
    const endpoint = { ...p };
    if (images.length) {
      const files = images.map(writeImage).filter(Boolean);
      parts.push({ role: 'user', content: `Image files to inspect (open them with your Read tool):\n${files.join('\n')}` });
      if (/claude/i.test(p.command || '')) endpoint.args = [...(p.args || []), '--allowedTools', 'Read'];
    }
    const r = await runCli(endpoint, parts, { timeoutSec: t });
    return r.text;
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), t * 1000);
  try {
    if (p.kind === 'anthropic') {
      const msgs = messages.map((m, i) => {
        if (i === messages.length - 1 && m.role === 'user' && images.length) {
          return {
            role: 'user',
            content: [...images.map((img) => {
              const d = toDataUrl(writeImage(img) || img);
              const mm = /^data:([^;]+);base64,(.*)$/s.exec(d);
              return { type: 'image', source: { type: 'base64', media_type: mm[1], data: mm[2] } };
            }), { type: 'text', text: m.content }],
          };
        }
        return { role: m.role, content: m.content };
      });
      const res = await fetch(`${p.baseUrl.replace(/\/$/, '')}/v1/messages`, {
        method: 'POST', signal: ctrl.signal,
        headers: { 'content-type': 'application/json', 'x-api-key': p.apiKey, 'anthropic-version': '2023-06-01' },
        body: JSON.stringify({ model: p.model, max_tokens: 8000, system, messages: msgs }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(`${p.name}: ${res.status} ${JSON.stringify(j).slice(0, 300)}`);
      return (j.content || []).map((c) => c.text || '').join('');
    }
    // openai-compatible
    const msgs = [];
    if (system) msgs.push({ role: 'system', content: system });
    messages.forEach((m, i) => {
      if (i === messages.length - 1 && m.role === 'user' && images.length && p.vision) {
        msgs.push({ role: 'user', content: [{ type: 'text', text: m.content },
          ...images.map((img) => ({ type: 'image_url', image_url: { url: toDataUrl(writeImage(img) || img) } }))] });
      } else msgs.push({ role: m.role, content: m.content });
    });
    const headers = { 'content-type': 'application/json' };
    if (p.apiKey) headers.authorization = `Bearer ${p.apiKey}`;
    const body = { messages: msgs, temperature: 0.8 };
    if (p.model) body.model = p.model;
    const res = await fetch(`${p.baseUrl.replace(/\/$/, '')}/chat/completions`, {
      method: 'POST', signal: ctrl.signal, headers, body: JSON.stringify(body),
    });
    const j = await res.json();
    if (!res.ok) throw new Error(`${p.name}: ${res.status} ${JSON.stringify(j).slice(0, 300)}`);
    let text = j.choices?.[0]?.message?.content || '';
    text = text.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
    return text;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * chat(role, system, messages, opts) -> { text, provider }
 * Walks settings.routing[role]; skips disabled providers, unconfirmed paid ones and (when opts.automation)
 * paid providers unless allowed.
 */
async function chat(role, system, messages, opts = {}) {
  const s = store.read('settings');
  const chain = (s.routing[role] || []).map(byId).filter((p) => p && p.enabled);
  if (!chain.length) throw new Error(`no enabled provider routed for "${role}" — open Engines`);
  const errors = [];
  for (const p of chain) {
    if (opts.images?.length && !p.vision) { errors.push(`${p.name}: no vision`); continue; }
    if (p.paid) {
      if (opts.automation && !s.safety.allowPaidInAutomations) { errors.push(`${p.name}: paid provider skipped in automation`); continue; }
      if (!(await askPaid(p))) { errors.push(`${p.name}: blocked by user`); continue; }
    }
    try {
      const text = await callProvider(p, system, messages, opts);
      if (!text || !text.trim()) throw new Error('empty answer');
      return { text, provider: p.name };
    } catch (e) {
      errors.push(`${p.name}: ${e.message}`);
    }
  }
  throw new Error(`all providers failed for ${role}:\n- ${errors.join('\n- ')}`);
}

/** First balanced JSON object/array in a model answer (handles ```json fences and chatter). */
function extractJson(text) {
  const s = String(text || '');
  const fence = /```(?:json)?\s*([\s\S]*?)```/i.exec(s);
  const candidates = fence ? [fence[1], s] : [s];
  for (const c of candidates) {
    for (let i = 0; i < c.length; i++) {
      const ch = c[i];
      if (ch !== '{' && ch !== '[') continue;
      const close = ch === '{' ? '}' : ']';
      let depth = 0; let inStr = false; let esc = false;
      for (let j = i; j < c.length; j++) {
        const x = c[j];
        if (inStr) { if (esc) esc = false; else if (x === '\\') esc = true; else if (x === '"') inStr = false; continue; }
        if (x === '"') inStr = true;
        else if (x === ch) depth++;
        else if (x === close) { depth--; if (depth === 0) { try { return JSON.parse(c.slice(i, j + 1)); } catch { break; } } }
      }
    }
  }
  throw new Error('no JSON found in model answer: ' + s.slice(0, 200));
}

async function testProvider(id) {
  const p = byId(id);
  if (!p) throw new Error('unknown provider');
  if (p.kind === 'cli') {
    const probe = probeCommand(p.command);
    if (!probe.ok) return { ok: false, error: probe.error };
  }
  if (p.paid && !(await askPaid(p))) return { ok: false, error: 'blocked by user' };
  const t0 = Date.now();
  const text = await callProvider(p, 'You are a connectivity test.', [{ role: 'user', content: 'Reply with exactly: READY' }], { timeoutSec: 180 });
  return { ok: /READY/i.test(text), text: text.slice(0, 200), ms: Date.now() - t0 };
}

module.exports = { chat, extractJson, testProvider, providers };
