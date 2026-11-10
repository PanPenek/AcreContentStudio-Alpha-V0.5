"""Stage 4 — overlays + final video.

    uv run --no-project --with pillow python engine/compose.py <episode_dir> [--out final.mp4]

Pixel look: nearest-neighbour upscale of the 540x960 frames to 1080x1920, then ASS overlays
(word-by-word captions, labels, title cards, opening title, channel handle) and the mixed audio.
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W, H = 1080, 1920


def log(*a):
    print("[compose]", *a, flush=True)


def ts(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def ass_color(hexstr, alpha=0):
    h = hexstr.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def esc(s):
    return s.replace("{", "(").replace("}", ")").replace("\n", "\\N")


def build_ass(ep, tl, style):
    beats = tl["beats"]
    timing = {"i", "start", "end", "until", "words"}
    if len(ep.get("beats", [])) == len(beats):  # staging edits without new audio
        for b, eb in zip(beats, ep["beats"]):
            b.update({k: v for k, v in eb.items() if k not in timing})
    font = style.get("font", "Silkscreen")
    acc = ass_color(style.get("accent", "#8a50c0"))
    acc2 = ass_color(style.get("accent2", "#ff9a3c"))
    dark = ass_color("#1a1420")
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,{font},86,&H00FFFFFF,&H00FFFFFF,{dark},&H00000000,-1,0,0,0,100,100,2,0,1,7,0,5,20,20,20,1
Style: Label,{font},58,&H00FFFFFF,&H00FFFFFF,{acc},&H00000000,-1,0,0,0,100,100,2,0,3,14,0,5,20,20,20,1
Style: Card,{font},112,&H00FFFFFF,&H00FFFFFF,{acc2},&H00000000,-1,0,0,0,100,100,4,0,3,22,0,5,20,20,20,1
Style: Title,{font},64,&H00FFFFFF,&H00FFFFFF,{acc},&H00000000,-1,0,0,0,100,100,2,0,3,18,0,5,40,40,20,1
Style: Handle,{font},36,&H00FFFFFF,&H00FFFFFF,{dark},&H00000000,-1,0,0,0,100,100,1,0,1,4,0,9,30,30,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    pop = r"{\fscx125\fscy125\t(0,110,\fscx100\fscy100)}"
    words = [w for b in beats for w in b.get("words", [])]
    cap_y = style.get("caption_y", 1330)
    for i, (w0, w1, word) in enumerate(words):
        nxt = words[i + 1][0] if i + 1 < len(words) else w1 + 0.6
        end = min(nxt, w1 + 0.45)
        txt = re.sub(r"[^A-Za-z0-9'\-!?.,&]", "", word).upper()
        if txt:
            ev.append(f"Dialogue: 1,{ts(w0)},{ts(end)},Word,,0,0,0,,{{\\pos(540,{cap_y})}}{pop}{esc(txt)}")
    for b in beats:
        a0 = b["start"] if b["i"] else 0.0
        if b.get("card"):
            d = float(b.get("card_dur", 1.7))
            ev.append(f"Dialogue: 3,{ts(a0)},{ts(min(b['until'], a0 + d))},Card,,0,0,0,,"
                      f"{{\\pos(540,430)\\fscx40\\fscy40\\t(0,160,\\fscx108\\fscy108)\\t(160,260,\\fscx100\\fscy100)}}{esc(b['card'])}")
        if b.get("label"):
            ev.append(f"Dialogue: 2,{ts(a0 + 0.35)},{ts(b['until'])},Label,,0,0,0,,{{\\pos(540,1585)}}{pop}{esc(b['label'])}")
        if b.get("title"):
            ev.append(f"Dialogue: 2,{ts(0.0)},{ts(b['until'])},Title,,0,0,0,,{{\\pos(540,250)\\q0}}{esc(b['title'])}")
    if style.get("handle"):
        ev.append(f"Dialogue: 4,{ts(0)},{ts(tl['duration'])},Handle,,0,0,0,,{esc(style['handle'])}")
    return hdr + "\n".join(ev) + "\n"


def main(ep_dir, out_name="final.mp4"):
    ep = json.load(open(os.path.join(ep_dir, "episode.json"), encoding="utf-8"))
    tl = json.load(open(os.path.join(ep_dir, "timeline.json"), encoding="utf-8"))
    style = {**json.load(open(os.path.join(ROOT, "engine", "style.json"), encoding="utf-8")), **ep.get("style", {})} \
        if os.path.exists(os.path.join(ROOT, "engine", "style.json")) else ep.get("style", {})
    frames = os.path.join(ep_dir, "frames")
    n = len([f for f in os.listdir(frames) if f.startswith("f_") and f.endswith(".png")]) if os.path.isdir(frames) else 0
    need = int(tl["duration"] * tl["fps"] + 0.999)
    if n < need:
        raise SystemExit(f"only {n}/{need} frames rendered — run the render stage first")
    open(os.path.join(ep_dir, "caps.ass"), "w", encoding="utf-8").write(build_ass(ep, tl, style))
    fonts = os.path.join(ROOT, "assets", "fonts").replace("\\", "/").replace(":", "\\:")
    vf = f"scale=1080:1920:flags=neighbor,subtitles=caps.ass:fontsdir='{fonts}'"
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats", "-framerate", str(tl["fps"]), "-i", os.path.join("frames", "f_%04d.png"),
           "-i", "mix.wav", "-vf", vf, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-crf", "17",
           "-pix_fmt", "yuv420p", "-r", str(tl["fps"]), "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
           out_name]
    log("ffmpeg", " ".join(cmd[-14:]))
    subprocess.run(cmd, check=True, cwd=ep_dir)
    # thumbnail: frame at the first card (or 1s)
    tcard = next(((b["start"] + 0.5) for b in tl["beats"] if (b.get("card") or (ep["beats"][b["i"]].get("card")))), 1.0)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{tcard:.2f}", "-i", out_name, "-frames:v", "1", "thumb.jpg"],
                   cwd=ep_dir, check=False)
    log("WROTE", os.path.join(ep_dir, out_name))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], a[a.index("--out") + 1] if "--out" in a else "final.mp4")
