"""Tiny web UI for Ming-3.0-tts (stdlib only, model stays loaded).
Run:  tools/Ming-3.0-tts/.venv/Scripts/python.exe engine/ming_web.py   ->  http://127.0.0.1:7860
"""
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import tts_ming as T  # noqa: E402

ROOT = T.ROOT
NEW_VOICES = os.path.join(ROOT, "workspace", "ming_web", "voices")
OUT = os.path.join(ROOT, "workspace", "ming_web", "out")
VOICE_ROOTS = [os.path.join(ROOT, "assets", "voices"), NEW_VOICES, os.path.join(ROOT, "workspace", "ming_test")]
os.makedirs(NEW_VOICES, exist_ok=True)
os.makedirs(OUT, exist_ok=True)

LOCK = threading.Lock()
MODEL = None


def model():
    global MODEL
    if MODEL is None:
        MODEL = T.load()
    return MODEL


def voices():
    res = {}
    for r in VOICE_ROOTS:
        if not os.path.isdir(r):
            continue
        for n in sorted(os.listdir(r)):
            d = os.path.join(r, n)
            if os.path.isfile(os.path.join(d, "ref.wav")) and os.path.isfile(os.path.join(d, "ref.txt")):
                res[n] = d
    return res


def slug(s):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", s).strip("_")[:40] or "voice"


def do_design(name, style, ip, text):
    name = slug(name)
    d = os.path.join(NEW_VOICES, name)
    text = text or T.SAMPLE
    with LOCK:
        m = model()
        if ip:
            wav = m.synthesize(task="IP", text=text, controls={"ip": ip}, raw_text=True)
            T.write_voice(d, m, wav, text, {"ip": ip})
        else:
            wav = m.synthesize(task="VOICE_DESIGN", text=text, controls={"style": style}, use_zero_spk_emb=True, raw_text=True)
            T.write_voice(d, m, wav, text, {"style": style})
    return name


def do_synth(voice, text, emotion):
    d = voices()[voice]
    ref = os.path.join(d, "ref.wav")
    ref_text = open(os.path.join(d, "ref.txt"), encoding="utf-8").read().strip()
    emo = T.EMO.get((emotion or "").lower())
    common = dict(text=T.normalize(text), prompt_wav_path=ref, prompt_text=ref_text, use_spk_emb=True,
                  language_id="en", raw_text=True)
    t0 = time.time()
    with LOCK:
        m = model()
        try:
            if emo and emo != "中性":
                wav = m.synthesize(task="EMOTION", controls={"emotion": emo}, **common)
            else:
                wav = m.synthesize(task="TTS", **common)
        except Exception as e:
            print("[ming] emotion fallback:", e, flush=True)
            wav = m.synthesize(task="TTS", **common)
        fn = f"{int(time.time())}_{slug(voice)}.wav"
        T.save(wav, T.sample_rate(m), os.path.join(OUT, fn))
    return fn, round(time.time() - t0, 1)


PAGE = r"""<!doctype html><meta charset=utf-8><title>Ming TTS</title>
<style>
:root{--bg:#1c1917;--card:#292524;--bd:#44403c;--fg:#f5f5f4;--mut:#a8a29e;--ac:#f59e0b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:32px 20px}h1{font-size:22px;margin:0 0 4px}p.s{color:var(--mut);margin:0 0 24px}
section{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:18px;margin-bottom:18px}
h2{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:0 0 12px}
label{display:block;color:var(--mut);font-size:13px;margin:10px 0 4px}
textarea,input,select{width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--bd);border-radius:8px;padding:9px 11px;font:inherit}
textarea{min-height:110px;resize:vertical}.row{display:flex;gap:12px}.row>*{flex:1}
button{background:var(--ac);color:#1c1917;border:0;border-radius:8px;padding:10px 18px;font:600 15px system-ui;cursor:pointer;margin-top:14px}
button:disabled{opacity:.5;cursor:wait}#st{color:var(--mut);margin-left:12px;font-size:13px}
audio{width:100%;margin-top:12px}.tags span{cursor:pointer;color:var(--ac);margin-right:10px;font-size:13px}
</style><main>
<h1>Ming-3.0-tts</h1><p class=s>Local, RTX 3090. First request loads the model (~10 s); a line takes ~15 s.</p>
<section><h2>Speak</h2>
<div class=row><div><label>Voice</label><select id=voice></select></div>
<div><label>Emotion</label><select id=emo><option value="">neutral</option><option>happy</option><option>sad</option><option>angry</option><option>surprised</option><option>fearful</option><option>disgusted</option></select></div></div>
<label>Text</label><textarea id=text>Hello there! [Laughter] This is Ming speaking, running fully on my own GPU.</textarea>
<div class=tags>Insert: <span>[Laughter]</span><span>[Sigh]</span><span>[Breathing]</span><span>[Uhm]</span><span>[Surprise-ah]</span><span>[Surprise-oh]</span></div>
<button id=go>Generate</button><span id=st></span><div id=res></div></section>
<section><h2>New voice</h2>
<div class=row><div><label>Name</label><input id=vn placeholder="narrator"></div>
<div><label>Built-in IP (optional, e.g. US_Emma)</label><input id=ip></div></div>
<label>Voice description (English, used when IP is empty)</label>
<input id=vs value="A warm, cheerful young female narrator, clear and friendly.">
<button id=mk>Create voice</button><span id=st2></span></section></main>
<script>
const $=id=>document.getElementById(id);
async function api(p,b){const r=await fetch(p,b&&{method:'POST',body:JSON.stringify(b)});const j=await r.json();if(!r.ok)throw j.error;return j}
async function load(sel){const v=await api('/voices');$('voice').innerHTML=v.map(n=>`<option>${n}</option>`).join('');if(sel)$('voice').value=sel}
document.querySelectorAll('.tags span').forEach(s=>s.onclick=()=>{const t=$('text');const i=t.selectionStart;t.value=t.value.slice(0,i)+s.textContent+' '+t.value.slice(i);t.focus()});
$('go').onclick=async()=>{$('go').disabled=true;$('st').textContent='generating…';
 try{const r=await api('/synth',{voice:$('voice').value,text:$('text').value,emotion:$('emo').value});
 $('st').textContent=`done in ${r.sec}s`;$('res').innerHTML=`<audio controls autoplay src="/out/${r.file}"></audio>`}
 catch(e){$('st').textContent='error: '+e}$('go').disabled=false};
$('mk').onclick=async()=>{$('mk').disabled=true;$('st2').textContent='designing…';
 try{const r=await api('/design',{name:$('vn').value||'voice_'+Date.now(),style:$('vs').value,ip:$('ip').value});
 await load(r.name);$('st2').textContent='created '+r.name}catch(e){$('st2').textContent='error: '+e}$('mk').disabled=false};
load();
</script>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if self.path == "/voices":
            return self.send(200, list(voices().keys()))
        if self.path.startswith("/out/"):
            p = os.path.join(OUT, os.path.basename(self.path[5:]))
            if os.path.isfile(p):
                return self.send(200, open(p, "rb").read(), "audio/wav")
        self.send(404, {"error": "not found"})

    def do_POST(self):
        try:
            b = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/synth":
                if not b.get("text", "").strip():
                    raise ValueError("empty text")
                fn, sec = do_synth(b["voice"], b["text"], b.get("emotion"))
                return self.send(200, {"file": fn, "sec": sec})
            if self.path == "/design":
                return self.send(200, {"name": do_design(b.get("name", "voice"), b.get("style", ""), b.get("ip", "").strip(), None)})
        except Exception as e:
            print("[ming-web] error:", repr(e), flush=True)
            return self.send(500, {"error": str(e)})
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    print(f"Ming web UI: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
