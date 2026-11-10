#!/usr/bin/env bash
# Download + analyse reference reels: metadata, transcript, scene cuts, contact sheets, detail frames.
cd "$(dirname "$0")/refs"
JAR=_ig_cookies.txt
CODES="yuimasensei:DfBg9x7DZvW yuimasensei:DfGPq5Hgc1g yuimasensei:De27tA9BANQ yuimasensei:De5u5XGhRYT yuimasensei:DfCD7KFieZy yuimasensei:DfFmdt1jJyB
drinkseidon:DfDXO2GjY3Z drinkseidon:DfCwj_JFSit drinkseidon:DfDyGJjjb-C drinkseidon:DfFT4irgISF drinkseidon:De72lBXCQ91 purponyt:DfAySyisueK"
for cu in $CODES; do
  u=${cu%%:*}; c=${cu##*:}; d="$u/$c"; mkdir -p "$d"
  if [ ! -f "$d/v.mp4" ]; then
    uvx yt-dlp -q --cookies "$JAR" --write-info-json -o "$d/v.%(ext)s" "https://www.instagram.com/reel/$c/" 2>&1 | grep -v -i csrf
  fi
  [ -f "$d/v.mp4" ] || { echo "MISSING $d"; continue; }
  D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$d/v.mp4")
  ffmpeg -y -v error -i "$d/v.mp4" -vf "fps=16/$D,scale=240:-2,tile=8x2" -frames:v 1 "$d/sheet.jpg"
  for t in 0.5 3 10 20; do ffmpeg -y -v error -ss $t -i "$d/v.mp4" -frames:v 1 "$d/f_$t.png"; done
  ffmpeg -v error -i "$d/v.mp4" -vf "select='gt(scene,0.28)',showinfo" -f null - 2>&1 | grep -o 'pts_time:[0-9.]*' | cut -d: -f2 > "$d/cuts.txt"
  ffmpeg -y -v error -i "$d/v.mp4" -ac 1 -ar 16000 "$d/a.wav"
  echo "OK $d dur=$D cuts=$(wc -l < "$d/cuts.txt")"
done
