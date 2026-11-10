"""Pose + expression vocabulary for VRoid characters (T-pose-relative rotations, see abs_common.apply_pose).

Every pose is a function pose(t) -> {bone: Matrix3} so it can carry a little life (sway, wiggle).
Expression presets map to VRoid face shape-key suffixes.
"""
import math

from abs_common import P, Rot, merged, hand_shape

ARMS_DOWN = P(L_UpperArm=Rot("Y", 72), R_UpperArm=Rot("Y", -72), L_LowerArm=Rot("Z", -12), R_LowerArm=Rot("Z", 12))


def _breath(t, ph=0.0):
    return P(C_Spine=Rot("X", 1.2 * math.sin(2 * math.pi * 0.28 * t + ph)),
             C_Head=Rot("Y", 2.5 * math.sin(2 * math.pi * 0.17 * t + ph)))


def idle(t):
    return merged(ARMS_DOWN, hand_shape("L", "relaxed"), hand_shape("R", "relaxed"),
                  # stance: L leg is +X, so NEGATIVE Y-rotation swings it outward (positive merged the legs into one)
                  P(L_UpperLeg=Rot("Y", -4), R_UpperLeg=Rot("Y", 4)))


def hip_l(t):
    """Left hand on hip (elbow out)."""
    return merged(P(L_UpperArm=Rot("Y", 60) @ Rot("Z", 28), L_LowerArm=Rot("Z", -105), L_Hand=Rot("Y", -15)),
                  hand_shape("L", "relaxed"))


def peace_r(t):
    """Right hand V-sign beside the face."""
    s = math.sin(2 * math.pi * 1.2 * t)
    return merged(P(R_UpperArm=Rot("Y", -45) @ Rot("Z", 28), R_LowerArm=Rot("Z", 132 + 3 * s), R_Hand=Rot("X", -90)),
                  hand_shape("R", "peace"), P(C_Head=Rot("Z", -7)))


def wave_r(t):
    """Right forearm up beside the head, swinging side to side (old version only reached chest height)."""
    s = math.sin(2 * math.pi * 2.0 * t)
    return merged(P(R_UpperArm=Rot("Y", -18) @ Rot("Z", 12), R_LowerArm=Rot("Y", 112 + 16 * s), R_Hand=Rot("X", -70)),
                  hand_shape("R", "open"), P(C_Head=Rot("Z", -5)))


def point_l(t):
    """Point with the right hand toward screen-left (character's right side, -X)."""
    s = math.sin(2 * math.pi * 1.5 * t)
    return merged(P(R_UpperArm=Rot("Y", -18) @ Rot("Z", 25 + 3 * s), R_LowerArm=Rot("Z", 15)),
                  hand_shape("R", "point"), P(C_Head=Rot("Y", -12), C_Chest=Rot("Y", -6)))


def point_r(t):
    """Point with the left hand toward screen-right (+X)."""
    s = math.sin(2 * math.pi * 1.5 * t)
    return merged(P(L_UpperArm=Rot("Y", 18) @ Rot("Z", -25 - 3 * s), L_LowerArm=Rot("Z", -15)),
                  hand_shape("L", "point"), P(C_Head=Rot("Y", 12), C_Chest=Rot("Y", 6)))


def point_down_r(t):
    """Left hand points down-right (at a cat on the floor/couch to screen-right)."""
    s = math.sin(2 * math.pi * 1.5 * t)
    return merged(P(L_UpperArm=Rot("Y", 50) @ Rot("Z", -30 - 3 * s), L_LowerArm=Rot("Z", -10)),
                  hand_shape("L", "point"), P(C_Head=Rot("Y", 14) @ Rot("X", 12), C_Chest=Rot("Y", 8)))


def explain(t):
    """Both palms up, forearms forward."""
    s = math.sin(2 * math.pi * 0.9 * t)
    return merged(P(L_UpperArm=Rot("Y", 68) @ Rot("Z", -8), R_UpperArm=Rot("Y", -68) @ Rot("Z", 8),
                    L_LowerArm=Rot("Z", -70 - 6 * s) @ Rot("X", 70), R_LowerArm=Rot("Z", 70 + 6 * s) @ Rot("X", -70)),
                  hand_shape("L", "open"), hand_shape("R", "open"))


def think(t):
    """Right index finger on the chin, head tilted."""
    return merged(P(R_UpperArm=Rot("Y", -70) @ Rot("Z", 30), R_LowerArm=Rot("Z", 140), R_Hand=Rot("X", -60)),
                  hand_shape("R", "point"),
                  P(L_UpperArm=Rot("Y", 68) @ Rot("Z", -20), L_LowerArm=Rot("Z", -95)), hand_shape("L", "relaxed"),
                  P(C_Head=Rot("Z", 10) @ Rot("X", -4)))


def cheer(t):
    s = math.sin(2 * math.pi * 2.4 * t)
    return merged(P(L_UpperArm=Rot("Y", -35 + 6 * s), R_UpperArm=Rot("Y", 35 - 6 * s), L_LowerArm=Rot("Z", -25),
                    R_LowerArm=Rot("Z", 25)), hand_shape("L", "fist"), hand_shape("R", "fist"))


def surprised(t):
    return merged(P(L_UpperArm=Rot("Y", 70) @ Rot("Z", -25), R_UpperArm=Rot("Y", -70) @ Rot("Z", 25),
                    L_LowerArm=Rot("Z", -125), R_LowerArm=Rot("Z", 125)),
                  hand_shape("L", "open"), hand_shape("R", "open"), P(C_Spine=Rot("X", -4), C_Head=Rot("X", -5)))


def laugh(t):
    s = math.sin(2 * math.pi * 4.5 * t)
    return merged(P(L_UpperArm=Rot("Y", 66) @ Rot("Z", -20), R_UpperArm=Rot("Y", -66) @ Rot("Z", 20),
                    L_LowerArm=Rot("Z", -110), R_LowerArm=Rot("Z", 110),
                    C_Spine=Rot("X", 3 * s - 3), C_Head=Rot("X", -8 + 3 * s)),
                  hand_shape("L", "relaxed"), hand_shape("R", "relaxed"))


def pet_r(t):
    """Reach forward-down to screen-right with the left hand and stroke (cat on a cushion at hip height)."""
    s = math.sin(2 * math.pi * 1.3 * t)
    return merged(P(L_UpperArm=Rot("Y", 45) @ Rot("Z", -48), L_LowerArm=Rot("Z", -10) @ Rot("Y", 10 + 8 * s),
                    L_Hand=Rot("Y", 10 * s), C_Spine=Rot("X", 10) @ Rot("Y", 8), C_Chest=Rot("X", 6),
                    C_Head=Rot("X", 14) @ Rot("Y", 16)),
                  hand_shape("L", "open"))


def pet_front(t):
    """Lean forward and stroke something in front at bench height with the right hand."""
    s = math.sin(2 * math.pi * 1.2 * t)
    return merged(P(R_UpperArm=Rot("X", 48 + 6 * s) @ Rot("Z", 78), R_LowerArm=Rot("Z", 18), R_Hand=Rot("Z", -10),
                    C_Spine=Rot("X", 14), C_Chest=Rot("X", 6), C_Head=Rot("X", 18)),
                  hand_shape("R", "open"))


def slow_blink(t):
    return merged(idle(t), P(C_Head=Rot("Z", 6) @ Rot("X", 3)))


def hands_together(t):
    return merged(P(L_UpperArm=Rot("Y", 70) @ Rot("Z", -22), R_UpperArm=Rot("Y", -70) @ Rot("Z", 22),
                    L_LowerArm=Rot("Z", -100), R_LowerArm=Rot("Z", 100)),
                  hand_shape("L", "open"), hand_shape("R", "open"))


POSES = {
    "idle": idle, "hip": lambda t: merged(idle(t), hip_l(t)), "peace": lambda t: merged(idle(t), hip_l(t), peace_r(t)),
    "wave": lambda t: merged(idle(t), wave_r(t)), "point_left": lambda t: merged(idle(t), point_l(t)),
    "point_right": lambda t: merged(idle(t), point_r(t)), "point_down_right": lambda t: merged(idle(t), point_down_r(t)),
    "explain": explain, "think": think, "cheer": cheer, "surprised": surprised, "laugh": laugh,
    "pet_right": lambda t: merged(idle(t), pet_r(t)), "pet_front": lambda t: merged(idle(t), pet_front(t)), "slow_blink": slow_blink, "hands_together": hands_together,
}

# expression presets -> VRoid shape-key suffixes
FACES = {
    "neutral": {"Fcl_MTH_Fun": 0.3},
    "smile": {"Fcl_ALL_Joy": 0.55, "Fcl_MTH_Fun": 0.3},
    "happy": {"Fcl_ALL_Joy": 1.0},
    "fang_grin": {"Fcl_EYE_Joy": 0.5, "Fcl_MTH_A": 0.35, "Fcl_MTH_Fun": 0.6, "Fcl_HA_Fung1": 1.0, "Fcl_BRW_Fun": 0.8},
    "wink": {"Fcl_EYE_Close_R": 1.0, "Fcl_MTH_A": 0.45, "Fcl_MTH_Fun": 0.6, "Fcl_HA_Fung1": 1.0, "Fcl_BRW_Fun": 0.8},
    "surprised": {"Fcl_ALL_Surprised": 1.0},
    "sad": {"Fcl_ALL_Sorrow": 0.8},
    "angry": {"Fcl_ALL_Angry": 0.7},
    "thinking": {"Fcl_BRW_Sorrow": 0.35, "Fcl_EYE_Joy": 0.15, "Fcl_MTH_Neutral": 0.6},
    "slow_blink": {"Fcl_EYE_Joy": 0.85, "Fcl_MTH_Fun": 0.5},
    "soft": {"Fcl_EYE_Joy": 0.4, "Fcl_MTH_Fun": 0.55, "Fcl_BRW_Fun": 0.4},
}
FACE_KEYS = sorted({k for f in FACES.values() for k in f} | {"Fcl_EYE_Close", "Fcl_MTH_A", "Fcl_MTH_I", "Fcl_MTH_O"})


# ------------------------------------------------------------------ body-type overrides
# Optional per-body pose replacements, selected by character.json "pose_set". Proportion differences (wide chibi
# shoulders) are handled generically by abs_retarget (IK), so this stays empty unless a body needs a bespoke pose.
POSE_SETS = {}


def use_pose_set(name):
    """Swap in a body-type pose set (call once after loading the character)."""
    if name in POSE_SETS:
        POSES.update(POSE_SETS[name])
