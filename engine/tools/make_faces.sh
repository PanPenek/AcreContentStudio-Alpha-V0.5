#!/usr/bin/env bash
# Expression variants of the T-pose sheet (same pose, only the face changes) for the pixel face-sprite atlas.
cd "$(dirname "$0")/../.."
R=assets/characters/astolfo_v2/tpose_s1.png
O=assets/characters/astolfo_v2/faces
mkdir -p $O
BASE="Keep this exact image unchanged: same character, same T-pose, same framing, same position and size in the frame, same outfit, same hair, same pixel-art 3D style, same background. Change ONLY the facial expression:"
declare -A E=(
  [neutral]="both eyes open looking at the viewer, mouth closed with a tiny calm smile."
  [blink]="both eyes fully closed as gentle curved lines, mouth closed with a tiny calm smile."
  [talk]="both eyes open, mouth open mid-word in a small rounded open mouth showing the inside of the mouth."
  [wink]="her right eye winking closed, left eye open, big open happy smile with one small cute fang visible."
  [happy]="both eyes closed in happy upside-down U arcs, wide open laughing smile with one small cute fang."
  [surprised]="eyes wide open with small pupils, eyebrows raised, mouth open in a small round O shape."
  [smug]="eyes half closed with a confident smirk, one corner of the mouth raised, eyebrows relaxed."
  [sad]="eyes looking down sadly, eyebrows angled up in the middle, small frown."
)
for k in neutral blink talk wink happy surprised smug sad; do
  [ -f "$O/$k.png" ] && continue
  python engine/tools/qedit.py http://127.0.0.1:8199 $R $O/$k 101 1152 1152 "$BASE ${E[$k]}" 8 || echo "FAIL $k"
done
