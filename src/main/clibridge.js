/**
 * clibridge.js — run a locally installed AI *agent CLI* as if it were a chat endpoint.
 *
 * The point is billing, not transport. Everything else in this app talks to an
 * OpenAI-compatible URL and pays per token; the tools sitting on this machine —
 * Claude Code, Codex, Gemini CLI, Qwen Code, OpenCode — are already paid for by a
 * monthly subscription and hold their own logged-in credentials. There is no API key
 * to paste anywhere, and there is no HTTP endpoint to point at: the only interface
 * they expose is a process you start.
 *
 * So that is the interface this speaks. Write a prompt to a child process, read the
 * answer off stdout, and hand back the same `{ text, promptTokens, completionTokens }`
 * shape `callChat` returns — after which nothing downstream (routing, fallback, refusal
 * circuits, the engine badge on a card) needs to know the difference.
 *
 * Three things make this harder than "spawn and read":
 *
 *   1. Windows shims. npm installs these as `.cmd`/`.ps1`, which Node refuses to spawn
 *      directly since the 2024 argument-injection fix. `resolveCommand` finds the real
 *      file on PATH and picks the right launcher for it, so the setting stays "qwen"
 *      rather than a path nobody would guess.
 *   2. Quoting. The prompt is a multi-line paragraph containing quotes, braces and
 *      newlines — the single worst thing to pass through a shell. Default is stdin, and
 *      the shell is never involved.
 *   3. Chatter. An agent CLI writes banners, spinners and reasoning to stdout and
 *      wraps its answer in a JSON envelope when asked to. `pickText` unwraps the known
 *      envelopes and otherwise passes the bytes through untouched — the app's own
 *      `extractJson` is what actually finds the payload, and mangling the text before
 *      it gets there would break the one thing that works everywhere.
 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

/** Placeholders a user may put in the argument template. */
const PH = {
  prompt: '{{prompt}}',
  model: '{{model}}',
  image: '{{imagePath}}',
};

// ---------------------------------------------------------------- command resolution

/**
 * Find what to actually execute, and how.
 *
 * Returns { file, prefixArgs, why } where the final spawn is
 * `spawn(file, [...prefixArgs, ...args])` with no shell — the prompt never touches a
 * command line, so nothing here has to be quoted.
 */
function resolveCommand(command) {
  const raw = String(command || '').trim();
  if (!raw) throw new Error('no command set');

  const direct = raw.includes('/') || raw.includes('\\');
  const found = direct ? (fs.existsSync(raw) ? raw : null) : searchPath(raw);
  if (!found) {
    throw new Error(`"${raw}" is not on PATH — install it, or give the full path to the executable`);
  }
  const ext = path.extname(found).toLowerCase();

  // .cmd/.bat are batch scripts: Node will not exec them without a shell, and a shell
  // is exactly what must not see the prompt. Launch the interpreter explicitly instead.
  if (ext === '.cmd' || ext === '.bat') {
    return { file: process.env.ComSpec || 'cmd.exe', prefixArgs: ['/d', '/s', '/c', found], why: 'batch shim' };
  }
  if (ext === '.ps1') {
    return {
      file: 'powershell.exe',
      prefixArgs: ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', found],
      why: 'powershell shim',
    };
  }
  return { file: found, prefixArgs: [], why: 'executable' };
}

/** `where`, without the round trip. Honours PATHEXT so "qwen" finds qwen.ps1. */
function searchPath(name) {
  const dirs = String(process.env.PATH || '').split(path.delimiter).filter(Boolean);
  const exts = process.platform === 'win32'
    ? ['', ...String(process.env.PATHEXT || '.COM;.EXE;.BAT;.CMD;.PS1').split(';').filter(Boolean)]
    : [''];
  for (const dir of dirs) {
    for (const ext of exts) {
      const candidate = path.join(dir, name + ext.toLowerCase());
      try {
        if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
      } catch { /* unreadable PATH entry */ }
    }
  }
  return null;
}

/** Is this command reachable at all? Used by the settings row before anything is run. */
function probeCommand(command) {
  try {
    const r = resolveCommand(command);
    return { ok: true, path: r.file === (process.env.ComSpec || 'cmd.exe') || r.file === 'powershell.exe' ? r.prefixArgs[r.prefixArgs.length - 1] : r.file, kind: r.why };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// ---------------------------------------------------------------- message flattening

/**
 * Collapse a chat array into the single prompt an agent CLI takes.
 *
 * These tools have no `system` role on the command line, so a system message becomes a
 * leading paragraph — which is what a system prompt is anyway from the model's side.
 * An image part is written to a temp file and reported separately: a CLI reads pictures
 * off disk, not out of a data: URI.
 */
function flatten(messages) {
  const parts = [];
  const images = [];
  for (const m of messages || []) {
    const content = m && m.content;
    if (typeof content === 'string') {
      parts.push(m.role === 'system' ? content : content);
      continue;
    }
    for (const piece of content || []) {
      if (!piece) continue;
      if (piece.type === 'text') parts.push(piece.text || '');
      else if (piece.type === 'image_url') {
        const written = writeDataUrl((piece.image_url || {}).url || '');
        if (written) images.push(written);
      }
    }
  }
  return { prompt: parts.filter(Boolean).join('\n\n').trim(), images };
}

function writeDataUrl(url) {
  const m = /^data:([^;]+);base64,(.*)$/s.exec(String(url || ''));
  if (!m) return null;
  const ext = /png/.test(m[1]) ? 'png' : /webp/.test(m[1]) ? 'webp' : 'jpg';
  const file = path.join(os.tmpdir(), `ala-cli-${Date.now()}-${Math.random().toString(36).slice(2, 8)}.${ext}`);
  fs.writeFileSync(file, Buffer.from(m[2], 'base64'));
  return file;
}

// ---------------------------------------------------------------- output parsing

// Spinners and colour codes. Agent CLIs draw progress even when stdout is a pipe.
const stripAnsi = (s) => String(s || '')
  .replace(/\[[0-9;?]*[ -/]*[@-~]/g, '')
  .replace(/\r/g, '');

/** Envelope keys, most specific first. `result` is what `claude -p --output-format json` uses. */
const TEXT_KEYS = ['result', 'response', 'output_text', 'text', 'output', 'answer', 'completion'];

function fromEnvelope(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  for (const k of TEXT_KEYS) {
    if (typeof value[k] === 'string' && value[k].trim()) return value[k];
  }
  // { message: { content: "..." } } and the OpenAI-ish { choices: [...] } shape
  const msg = value.message || (Array.isArray(value.choices) && value.choices[0] && value.choices[0].message);
  if (msg) {
    if (typeof msg.content === 'string' && msg.content.trim()) return msg.content;
    if (Array.isArray(msg.content)) {
      const joined = msg.content.map((c) => (c && typeof c.text === 'string' ? c.text : '')).join('').trim();
      if (joined) return joined;
    }
  }
  return null;
}

/**
 * The model's answer, out of whatever the CLI printed.
 *
 * Deliberately conservative: it unwraps a *recognised* envelope and otherwise returns
 * the raw text. A metadata answer is itself JSON (`{"title": …}` or a top-level array),
 * and a parser that went looking for "some string field" inside it would return a
 * description where a whole object was wanted.
 */
function pickText(stdout) {
  const s = stripAnsi(stdout).trim();
  if (!s) return '';

  try {
    const unwrapped = fromEnvelope(JSON.parse(s));
    if (unwrapped) return unwrapped;
    return s; // valid JSON that isn't an envelope — it IS the answer
  } catch { /* not a single JSON document; try line-delimited below */ }

  // stream-json: one JSON object per line, the last `result` wins.
  const lines = s.split('\n').map((l) => l.trim()).filter(Boolean);
  let streamed = null;
  let sawJsonLine = false;
  for (const line of lines) {
    if (line[0] !== '{') continue;
    try {
      const obj = JSON.parse(line);
      sawJsonLine = true;
      const unwrapped = fromEnvelope(obj);
      if (unwrapped) streamed = unwrapped;
    } catch { /* a brace-leading line that isn't JSON */ }
  }
  if (sawJsonLine && streamed) return streamed;
  return s;
}

/**
 * Output that means "this tool cannot work right now" rather than "here is your answer".
 *
 * A subscription CLI has two failure modes an API key does not: the session expires and
 * has to be renewed by a human in a terminal, and the monthly allowance runs out. Both
 * are recoverable and neither should be silently written onto a card, so they are turned
 * into errors — which is what makes the chain fall through to the next provider.
 */
const NOT_USABLE = /not logged in|please run \/login|\/login\b|not authenticated|authentication (required|failed)|no active session|session (has )?expired|sign in to|usage limit|quota exceeded|out of credits|subscription (required|expired)|upgrade to (a )?(pro|plus)/i;

// ---------------------------------------------------------------- the call

/**
 * Kill the whole tree, not just the launcher.
 *
 * Every one of these CLIs is a shim that starts node, and `child.kill()` on the shim
 * leaves the node process holding the subscription session open and burning quota after
 * a timeout has already given up on it.
 */
function killTree(child) {
  if (!child || child.exitCode !== null) return;
  if (process.platform === 'win32') {
    try {
      spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
      return;
    } catch { /* fall through to the plain kill */ }
  }
  try { child.kill('SIGKILL'); } catch { /* already gone */ }
}

/**
 * One round trip through a local agent CLI.
 *
 * `endpoint` carries the provider's `command`, `args`, `promptVia`, `cwd`, `env` and
 * `model`; the return shape matches the HTTP `callChat` so `withFallback` cannot tell
 * them apart. Token counts come back as zero — a subscription does not bill per token,
 * and inventing numbers would poison the only accounting the app does keep.
 */
function runCli(endpoint, messages, { timeoutSec } = {}) {
  const { prompt, images } = flatten(messages);
  const seconds = Number(timeoutSec || endpoint.timeoutSec) || 300;
  const viaStdin = (endpoint.promptVia || 'stdin') === 'stdin';

  const template = Array.isArray(endpoint.args) && endpoint.args.length
    ? endpoint.args
    : (endpoint.args ? String(endpoint.args).split(/\s+/).filter(Boolean) : []);

  // Substitute per call rather than per provider: {{imagePath}} only exists once an
  // image has been written to disk, and that is per request.
  //
  // An unfilled placeholder takes its flag with it. `["-m", "{{model}}"]` with no model
  // configured must become `[]`, not `["-m"]` — a bare `-m` swallows the next argument
  // and the CLI ends up being asked for a model called "--output-format".
  const args = [];
  for (let i = 0; i < template.length; i++) {
    let a = String(template[i]);
    const next = i + 1 < template.length ? String(template[i + 1]) : '';
    const emptyPlaceholder = (ph, value) => next.includes(ph) && !value;
    if (a.startsWith('-') && (emptyPlaceholder(PH.model, endpoint.model) || emptyPlaceholder(PH.image, images[0]))) {
      i++;
      continue;
    }
    if (a.includes(PH.model)) {
      if (!endpoint.model) continue;
      a = a.split(PH.model).join(endpoint.model);
    }
    if (a.includes(PH.image)) {
      if (!images.length) continue;
      a = a.split(PH.image).join(images[0]);
    }
    if (a.includes(PH.prompt)) a = a.split(PH.prompt).join(prompt);
    args.push(a);
  }
  // "Prompt as an argument" with no placeholder to put it in: append it as the last
  // positional, which is how every one of these CLIs takes a one-shot message.
  if (!viaStdin && !template.some((a) => String(a).includes(PH.prompt))) args.push(prompt);

  const resolved = resolveCommand(endpoint.command);

  return new Promise((resolve, reject) => {
    let child;
    try {
      child = spawn(resolved.file, [...resolved.prefixArgs, ...args], {
        cwd: endpoint.cwd && fs.existsSync(endpoint.cwd) ? endpoint.cwd : os.tmpdir(),
        env: { ...process.env, ...(endpoint.env || {}) },
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } catch (e) {
      return reject(new Error(`could not start ${endpoint.command}: ${e.message}`));
    }

    let out = '';
    let err = '';
    let timedOut = false;
    // Bounded on purpose: a CLI stuck in a retry loop can print for as long as the
    // timeout allows, and the answer is never in megabyte 40.
    const CAP = 4_000_000;
    const timer = setTimeout(() => { timedOut = true; killTree(child); }, seconds * 1000);

    child.stdout.on('data', (d) => { if (out.length < CAP) out += d.toString(); });
    child.stderr.on('data', (d) => { if (err.length < CAP) err += d.toString(); });

    if (viaStdin) {
      child.stdin.on('error', () => { /* the CLI closed stdin early; the args may carry it */ });
      child.stdin.end(prompt);
    } else {
      child.stdin.end();
    }

    const cleanup = () => {
      clearTimeout(timer);
      for (const f of images) fs.unlink(f, () => {});
    };

    child.on('error', (e) => {
      cleanup();
      reject(new Error(`${endpoint.command} failed to run: ${e.message}`));
    });

    child.on('close', (code) => {
      cleanup();
      if (timedOut) {
        return reject(new Error(`${endpoint.name || endpoint.command} timed out after ${seconds}s`));
      }
      const text = pickText(out);
      /**
       * A non-zero exit is a failure even when something was printed.
       *
       * Measured, not assumed: `claude -p` with no active session exits 1 and prints
       * "Not logged in · Please run /login" — a perfectly well-formed string that is not
       * an answer. Accepting it because bytes arrived meant the chain stopped there and
       * that sentence went on to become an image's title. The process said it failed;
       * believing it is what lets `withFallback` move to the next provider.
       */
      if (code !== 0) {
        const detail = (text || stripAnsi(err).trim() || '(no output)').slice(0, 400);
        return reject(new Error(`${endpoint.name || endpoint.command} exited ${code}: ${detail}`));
      }
      /**
       * The same failure can also arrive with exit 0 — a CLI that prints "please log in"
       * and considers having said so a success. Narrow on purpose: only a SHORT whole
       * output is judged, because these phrases are perfectly ordinary inside a
       * description, and the cost of a false positive is a discarded good answer.
       */
      if (text.length < 240 && NOT_USABLE.test(text)) {
        return reject(new Error(`${endpoint.name || endpoint.command} is installed but not usable: ${text.slice(0, 200)}`));
      }
      resolve({
        text,
        promptTokens: 0,
        completionTokens: 0,
        // Kept for the settings panel's Test button: when a command answers with
        // something unparseable, the only useful thing to show is what it actually said.
        stdout: stripAnsi(out).slice(0, 4000),
        stderr: stripAnsi(err).slice(0, 2000),
        exitCode: code,
      });
    });
  });
}

module.exports = { runCli, probeCommand, resolveCommand, pickText, flatten, PH };
