"""Headless (invisible) Chromium with the user's instagram cookies: open each profile's /reels/ page,
capture the clips API JSON the page itself requests while scrolling, save reel lists.

~/.scrapling-venv/Scripts/python.exe ig_headless.py <outdir> user1 user2
"""
import json
import os
import sys
import time

from patchright.sync_api import sync_playwright

OUT = sys.argv[1]
USERS = sys.argv[2:]
jar = os.path.join(OUT, "_ig_cookies.txt")
cookies = []
for line in open(jar):
    if line.startswith("#") or not line.strip():
        continue
    d, _, p, sec, exp, n, v = line.rstrip("\n").split("\t")
    cookies.append({"name": n, "value": v, "domain": d, "path": p, "secure": sec == "TRUE"})

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, locale="en-US")
    ctx.add_cookies(cookies)
    page = ctx.new_page()
    for u in USERS:
        items, prof = {}, {}

        def on_resp(r):
            url = r.url
            try:
                if "/api/v1/clips/user" in url or ("graphql" in url and r.request.method == "POST"):
                    j = r.json()
                    for it in (j.get("items") or []):
                        m = it.get("media", it)
                        if "code" in m:
                            items[m["code"]] = m
                    data = (j.get("data") or {})
                    for k, v in data.items():
                        if isinstance(v, dict) and "edges" in v:
                            for e in v["edges"]:
                                m = e.get("node", {}).get("media", e.get("node", {}))
                                if isinstance(m, dict) and m.get("code"):
                                    items[m["code"]] = m
                if "web_profile_info" in url:
                    prof.update(r.json()["data"]["user"])
            except Exception:
                pass
        page.on("response", on_resp)
        page.goto(f"https://www.instagram.com/{u}/reels/", wait_until="domcontentloaded", timeout=60000)
        time.sleep(6)
        for _ in range(6):
            page.mouse.wheel(0, 3000)
            time.sleep(2.5)
        # fallback: scrape reel links from the DOM
        links = page.eval_on_selector_all("a[href*='/reel/']", "els => els.map(e => [e.getAttribute('href'), e.innerText])")
        page.remove_listener("response", on_resp)
        page.screenshot(path=os.path.join(OUT, f"{u}_grid.png"), full_page=False)
        reels = []
        for code, m in items.items():
            cap = (m.get("caption") or {}).get("text", "") if isinstance(m.get("caption"), dict) else ""
            reels.append({"code": code, "views": m.get("play_count") or m.get("view_count") or m.get("ig_play_count"),
                          "likes": m.get("like_count"), "comments": m.get("comment_count"), "duration": m.get("video_duration"),
                          "taken_at": m.get("taken_at"), "caption": cap[:400]})
        reels.sort(key=lambda x: -(x["taken_at"] or 0))
        info = {"username": u, "full_name": prof.get("full_name"), "bio": prof.get("biography"),
                "followers": (prof.get("edge_followed_by") or {}).get("count"), "reels": reels,
                "dom_links": [l for l in links][:60]}
        json.dump(info, open(os.path.join(OUT, f"{u}.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(u, "followers", info["followers"], "api reels", len(reels), "dom links", len(links), "|", (info["bio"] or "")[:150].replace("\n", " "))
        for x in reels[:30]:
            print(f"  {x['code']} views={x['views']} likes={x['likes']} dur={x['duration']} | {x['caption'][:100]!r}")
        if not reels:
            for l in links[:30]:
                print("  link", l[0], repr(l[1])[:60])
    b.close()
