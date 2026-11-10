"""Proportion-aware pose retargeting for non-VRoid bodies (projected chibi hosts).

The pose library (abs_poses) is FK tuned for VRoid proportions. On a body with wider shoulders / bigger head the same
angles leave the hands far from the face or each other. retarget(spec) runs the pose on the VRoid reference skeleton,
expresses each hand's position in the upper-chest frame, maps it onto this body's proportions and re-solves
UpperArm/LowerArm with analytic 2-bone IK (elbow pole + twist kept from the FK pose).

character.json "ik": {"ref": SKEL, "own": SKEL}, SKEL = {"bones": {name: [x, y, z] rest head}, "head_c": z}
"""
from mathutils import Matrix, Vector

CHAIN = ["J_Bip_C_Hips", "J_Bip_C_Spine", "J_Bip_C_Chest", "J_Bip_C_UpperChest", "J_Bip_C_Neck", "J_Bip_C_Head"]
PARENT = {"J_Bip_C_Spine": "J_Bip_C_Hips", "J_Bip_C_Chest": "J_Bip_C_Spine", "J_Bip_C_UpperChest": "J_Bip_C_Chest",
          "J_Bip_C_Neck": "J_Bip_C_UpperChest", "J_Bip_C_Head": "J_Bip_C_Neck"}
for _s in "LR":
    PARENT[f"J_Bip_{_s}_Shoulder"] = "J_Bip_C_UpperChest"
    PARENT[f"J_Bip_{_s}_UpperArm"] = f"J_Bip_{_s}_Shoulder"
    PARENT[f"J_Bip_{_s}_LowerArm"] = f"J_Bip_{_s}_UpperArm"
    PARENT[f"J_Bip_{_s}_Hand"] = f"J_Bip_{_s}_LowerArm"
ORDER = CHAIN + [f"J_Bip_{s}_{b}" for s in "LR" for b in ("Shoulder", "UpperArm", "LowerArm", "Hand")]
I3 = Matrix.Identity(3)
DEBUG = False


def fk(skel, spec):
    rest = {k: Vector(v) for k, v in skel["bones"].items()}
    W, P = {}, {}
    for b in ORDER:
        if b not in rest:
            continue
        par = PARENT.get(b)
        S = spec.get(b, I3)
        if par is None or par not in W:
            W[b], P[b] = S.copy(), rest[b].copy()
        else:
            W[b] = W[par] @ S
            P[b] = P[par] + W[par] @ (rest[b] - rest[par])
    return W, P


def _rot_between(a, b):
    a, b = a.normalized(), b.normalized()
    return a.rotation_difference(b).to_matrix()


def _map_axis(v, ref_knee, own_knee, ratio_in, ratio_out):
    """piecewise: |v| up to the reference landmark scales by landmark ratio, beyond it by limb ratio"""
    s = 1 if v >= 0 else -1
    a = abs(v)
    if a <= ref_knee:
        return s * a * ratio_in
    return s * (own_knee + (a - ref_knee) * ratio_out)


def retarget(spec, ik):
    ref, own = ik["ref"], ik["own"]
    Wr, Pr = fk(ref, spec)
    Wo, Po = fk(own, spec)
    out = dict(spec)
    rb, ob = ref["bones"], own["bones"]

    def L(sk, a, b):
        return (Vector(sk["bones"][b]) - Vector(sk["bones"][a])).length

    for sd in "LR":
        ua, la, hd, sh = (f"J_Bip_{sd}_{n}" for n in ("UpperArm", "LowerArm", "Hand", "Shoulder"))
        if ua not in Po or ua not in Pr:
            continue
        uc = "J_Bip_C_UpperChest"
        l1r, l2r = L(ref, ua, la), L(ref, la, hd)
        l1, l2 = L(own, ua, la), L(own, la, hd)
        arm_k = (l1 + l2) / (l1r + l2r)
        # hand offset in the upper-chest frame (reference body)
        o = Wr[uc].transposed() @ (Pr[hd] - Pr[uc])
        sh_r, sh_o = abs(rb[ua][0]), abs(ob[ua][0])
        shz_r, shz_o = rb[ua][2] - rb[uc][2], ob[ua][2] - ob[uc][2]
        hz_r, hz_o = ref["head_c"] - rb[uc][2], own["head_c"] - ob[uc][2]
        # x: hands at the sides keep clear of the (wider) body; hands in front keep their absolute spacing so
        # together/clap/chin gestures still meet; up at the (bigger) face they widen with the head
        x_side = _map_axis(o.x, sh_r, sh_o, sh_o / sh_r, arm_k)
        head_k = (hz_o - shz_o) / max(1e-4, hz_r - shz_r)
        up = min(1.0, max(0.0, (o.z - shz_r) / 0.1))
        x_front = o.x * (1.0 + up * (head_k - 1.0))
        fwd = min(1.0, max(0.0, (-o.y - 0.06) / 0.12))
        ox = x_side + (x_front - x_side) * fwd
        if o.z >= shz_r:  # up toward the face: map shoulder->head-centre span onto this body's
            oz = shz_o + (o.z - shz_r) * (hz_o - shz_o) / max(1e-4, hz_r - shz_r)
        else:
            oz = shz_o + (o.z - shz_r) * arm_k
        oy = o.y * arm_k
        # faces are bigger: keep hands near the face out of it (push forward a little when above the shoulders)
        if o.z >= shz_r and abs(o.x) < sh_r:
            oy -= 0.25 * (hz_o - hz_r)
        T = Po[uc] + Wo[uc] @ Vector((ox, oy, oz))
        S0 = Po[ua]
        d = T - S0
        dl = max(abs(l1 - l2) + 1e-3, min(d.length, (l1 + l2) * 0.995))
        dh = d.normalized()
        # pole: the reference elbow's offset from its shoulder-hand line, expressed in the chest frame
        dr = (Pr[hd] - Pr[ua])
        pr = (Pr[la] - Pr[ua])
        pr = pr - dr.normalized() * pr.dot(dr.normalized()) if dr.length > 1e-6 else Vector((0, 0.3, -1))
        pole = Wo[uc] @ (Wr[uc].transposed() @ pr)
        pole = pole - dh * pole.dot(dh)
        if pole.length < 1e-5:
            pole = Vector((0, 0.3, -1)) - dh * Vector((0, 0.3, -1)).dot(dh)
        pole.normalize()
        a = (l1 * l1 - l2 * l2 + dl * dl) / (2 * dl)
        h = max(0.0, l1 * l1 - a * a) ** 0.5
        E = S0 + dh * a + pole * h
        Tc = S0 + dh * dl
        if DEBUG:
            print("IK", sd, "o", tuple(round(x, 3) for x in o), "T", tuple(round(x, 3) for x in T), "S0", tuple(round(x, 3) for x in S0),
                  "E", tuple(round(x, 3) for x in E), "l1", round(l1, 3), "l2", round(l2, 3), "d", round(d.length, 3))
        # upper arm: correct the FK world rotation so it points at the elbow (keeps the FK twist)
        u_rest = Vector(ob[la]) - Vector(ob[ua])
        Wua = Wo[ua]
        Wua_new = _rot_between(Wua @ u_rest, E - S0) @ Wua
        out[ua] = Wo[sh].transposed() @ Wua_new
        f_rest = Vector(ob[hd]) - Vector(ob[la])
        Wla = Wua_new @ spec.get(la, I3)
        Wla_new = _rot_between(Wla @ f_rest, Tc - E) @ Wla
        out[la] = Wua_new.transposed() @ Wla_new
    return out
