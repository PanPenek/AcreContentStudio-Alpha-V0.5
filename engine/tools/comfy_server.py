"""Local ComfyUI server for the engine: reuse :8199 if it answers, else start the Desktop install headless.

python comfy_server.py ensure   -> prints the server URL once /system_stats answers (starts it if needed)
python comfy_server.py stop     -> frees VRAM (POST /free) so Blender/TTS get the GPU back
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

PORT = int(os.environ.get("ABS_COMFY_PORT", "8199"))
URL = f"http://127.0.0.1:{PORT}"
LOCAL = os.environ.get("LOCALAPPDATA", "")
COMFY = os.path.join(LOCAL, r"Comfy-Desktop\ComfyUI-Installs\ComfyUI_rAzzren\ComfyUI")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def alive():
    try:
        return urllib.request.urlopen(URL + "/system_stats", timeout=3).status == 200
    except Exception:
        return False


def model_paths_yaml():
    d = os.path.join(os.environ.get("APPDATA", ""), "Comfy Desktop", "instance-model-paths")
    ys = [os.path.join(d, f) for f in os.listdir(d)] if os.path.isdir(d) else []
    return ys[0] if ys else None


def ensure(timeout=240):
    if alive():
        return URL
    py = os.path.join(COMFY, ".venv", "Scripts", "python.exe")
    if not os.path.exists(py):
        raise SystemExit(f"ComfyUI not found at {COMFY}")
    out = os.path.join(ROOT, "workspace", "comfy_out")
    logd = os.path.join(ROOT, "workspace", "logs")
    os.makedirs(out, exist_ok=True)
    os.makedirs(logd, exist_ok=True)
    cmd = [py, "-s", "main.py", "--port", str(PORT), "--listen", "127.0.0.1", "--output-directory", out]
    y = model_paths_yaml()
    if y:
        cmd += ["--extra-model-paths-config", y]
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(cmd, cwd=COMFY, env=env, stdout=open(os.path.join(logd, f"comfy{PORT}.log"), "ab"),
                     stderr=subprocess.STDOUT, creationflags=flags, close_fds=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if alive():
            return URL
        time.sleep(3)
    raise SystemExit("ComfyUI did not come up in time (see workspace/logs)")


def free():
    if alive():
        req = urllib.request.Request(URL + "/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                     headers={"content-type": "application/json"})
        urllib.request.urlopen(req, timeout=30)


if __name__ == "__main__":
    if sys.argv[1:] == ["stop"]:
        free()
        print("freed")
    else:
        print(ensure())
