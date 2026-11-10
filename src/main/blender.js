/**
 * blender.js — Blender integration beyond the headless engine:
 *  - live bridge client for the official Blender Lab MCP add-on (TCP 127.0.0.1:9876, NUL-delimited JSON:
 *    {"type":"execute","code":"...","strict_json":true} -> {"status":"ok","result":{...},"stdout":...})
 *  - open an episode's scene.blend in the Blender GUI (only when the user clicks it)
 *  - start/stop a headless bridge so the Overseer / console can drive Blender without a window
 */
const net = require('net');
const fs = require('fs');
const { spawn } = require('child_process');
const store = require('./store');

const HOST = '127.0.0.1';
const PORT = 9876;
let headless = null;

function exec(code, { timeoutMs = 60000 } = {}) {
  return new Promise((resolve, reject) => {
    const sock = net.createConnection({ host: HOST, port: PORT });
    let buf = '';
    const timer = setTimeout(() => { sock.destroy(); reject(new Error('Blender bridge timed out')); }, timeoutMs);
    sock.on('connect', () => sock.write(JSON.stringify({ type: 'execute', code, strict_json: true }) + '\0'));
    sock.on('data', (d) => {
      buf += d.toString('utf8');
      const i = buf.indexOf('\0');
      if (i >= 0) {
        clearTimeout(timer);
        sock.end();
        try { resolve(JSON.parse(buf.slice(0, i))); } catch (e) { reject(e); }
      }
    });
    sock.on('error', (e) => { clearTimeout(timer); reject(new Error(`Blender bridge not reachable on ${PORT} (${e.code || e.message}). Open Blender 5.2+ with the MCP add-on, or start the headless bridge.`)); });
  });
}

async function status() {
  const s = store.read('settings');
  const exe = fs.existsSync(s.blenderPath);
  try {
    const r = await exec('import bpy\nresult = {"version": bpy.app.version_string, "file": bpy.data.filepath, "objects": len(bpy.data.objects), "background": bpy.app.background}', { timeoutMs: 3000 });
    return { exe, bridge: true, info: r.result || r, headless: !!headless };
  } catch (e) {
    return { exe, bridge: false, error: e.message, headless: !!headless };
  }
}

function openGui(blendFile) {
  const s = store.read('settings');
  const args = blendFile && fs.existsSync(blendFile) ? [blendFile] : [];
  const p = spawn(s.blenderPath, args, { detached: true, stdio: 'ignore' });
  p.unref();
  return { pid: p.pid };
}

function startHeadless(blendFile) {
  if (headless) return { running: true, pid: headless.pid };
  const s = store.read('settings');
  const args = ['--background'];
  if (blendFile && fs.existsSync(blendFile)) args.push(blendFile);
  args.push('--command', 'blender_mcp');
  headless = spawn(s.blenderPath, args, { windowsHide: true, stdio: 'ignore' });
  headless.on('close', () => { headless = null; });
  return { running: true, pid: headless.pid };
}

function stopHeadless() {
  if (!headless) return { running: false };
  try { spawn('taskkill', ['/pid', String(headless.pid), '/T', '/F'], { windowsHide: true }); } catch { headless.kill(); }
  headless = null;
  return { running: false };
}

module.exports = { exec, status, openGui, startHeadless, stopHeadless };
