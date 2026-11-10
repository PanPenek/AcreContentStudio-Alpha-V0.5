"""Read instagram.com cookies from the running Brave via the BROWSER-level CDP socket (opens no tab),
list the latest reels of the given profiles, and download a sample with yt-dlp.

uv run --no-project --with websocket-client --with requests python ig_research.py <outdir> user1 user2 ...
The cookie jar is written to <outdir>/_ig_cookies.txt and DELETED at the end.
"""
import json
import os
import subprocess
import sys
import time

import requests
import websocket

OUT = sys.argv[1]
USERS = sys.argv[2:]
os.makedirs(OUT, exist_ok=True)
ver = requests.get("http://127.0.0.1:9222/json/version", timeout=5).json()
ws = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=15, suppress_origin=True)
ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
while True:
    msg = json.loads(ws.recv())
    if msg.get("id") == 1:
        break
ws.close()
cookies = [c for c in msg["result"]["cookies"] if c["domain"].endswith("instagram.com")]
print("instagram cookies:", len(cookies), "logged in:", any(c["name"] == "sessionid" for c in cookies))
jar = os.path.join(OUT, "_ig_cookies.txt")
with open(jar, "w") as f:
    f.write("# Netscape HTTP Cookie File\n")
    for c in cookies:
        f.write("\t".join([c["domain"], "TRUE" if c["domain"].startswith(".") else "FALSE", c["path"],
                           "TRUE" if c.get("secure") else "FALSE", str(int(c.get("expires", 0)) if c.get("expires", -1) > 0 else 0),
                           c["name"], c["value"]]) + "\n")
S = requests.Session()
for c in cookies:
    S.cookies.set(c["name"], c["value"], domain=c["domain"])
H = {"x-ig-app-id": "936619743392459", "User-Agent": ver["User-Agent"], "x-requested-with": "XMLHttpRequest",
     "referer": "https://www.instagram.com/"}
csrf = next((c["value"] for c in cookies if c["name"] == "csrftoken"), None)
if csrf:
    H["x-csrftoken"] = csrf
try:
    for u in USERS:
        r = S.get(f"https://www.instagram.com/api/v1/users/web_profile_info/?username={u}", headers=H, timeout=30)
        print(u, "profile", r.status_code)
        if r.status_code != 200:
            print(r.text[:300])
            continue
        user = r.json()["data"]["user"]
        info = {"username": u, "full_name": user.get("full_name"), "bio": user.get("biography"),
                "followers": user["edge_followed_by"]["count"], "posts": user["edge_owner_to_timeline_media"]["count"], "id": user["id"]}
        # reels tab
        reels = []
        r2 = S.post("https://www.instagram.com/api/v1/clips/user/", headers=H, data={"target_user_id": user["id"], "page_size": 24, "include_feed_video": "true"}, timeout=30)
        print(u, "clips", r2.status_code)
        if r2.status_code == 200:
            for it in r2.json().get("items", []):
                m = it["media"]
                cap = (m.get("caption") or {}).get("text", "")
                reels.append({"code": m["code"], "views": m.get("play_count") or m.get("view_count"), "likes": m.get("like_count"),
                              "comments": m.get("comment_count"), "duration": m.get("video_duration"), "taken_at": m.get("taken_at"),
                              "caption": cap[:300]})
        else:
            print(r2.text[:300])
        info["reels"] = reels
        json.dump(info, open(os.path.join(OUT, f"{u}.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(json.dumps({k: v for k, v in info.items() if k != "reels"}, ensure_ascii=False))
        for x in reels:
            print(f"  {x['code']} views={x['views']} likes={x['likes']} dur={x['duration']} | {x['caption'][:90]!r}")
        time.sleep(2)
finally:
    pass
print("JAR", jar)
