"""Khajiit and Argonians on Starfield's face rig, offline (races plan, beast races; owner 2026-11-09: "how are we gonna
go about Khajiit and argonians and getting them in game with sliders for their features"). Read-only.

    python -I scripts\\npc\\beast_probe.py --skyrim-data "$sky" --starfield $sf --out C:\\Modding\\work\\races

Skyrim (verified, race_survey): each beast race has its own head (Khajiit 1356 / 1342 vertices, Argonian 1219), its
own expression tri (the same names as the human head's: Aah, BlinkLeft, BrowUp, phonemes, moods) and chargen tri (52
sliders), a mouth and eyes with their own tris, skeletonBeast.nif, a tail (slot 40), and the human body with beast
hands / feet. Starfield's face moves by face bones, so a beast head needs those bones' weights. Per race and sex this
probe:
  1. reads the head (model space) with its mouth and eyes;
  2. finds landmarks on it and on Skyrim's human head (eye centres from the eye parts, mouth corners from the head's
     mouth hole, nose tip, crown, back of the head, the head's sides at eye height) and warps the beast head onto the
     human one (thin-plate spline through the landmarks): how far the warped head lies from the human surface;
  3. carries the warped head onto Starfield's head (face_fit's alignment, fo4sf.headcorr's surface matching) and
     gives each beast vertex the face-bone weights there; checks them against the beast's own Aah (mouth open): the
     vertices Aah drops should be the ones on Starfield's jaw bones;
  4. counts the sliders (head + mouth + eyes chargen morphs) against morph.dat's 128 keys;
  5. lists the beast skeleton's bones that the human skeleton lacks (the tail's) and the tail's skin bones;
  6. lists what Starfield's morph records name (MRPH TMPP / TCMP / BMPP "Bone Morph Definition File": may let a head
     part bring its own slider definitions);
  7. writes beast_probe.json and beast_view.html (beast head, its warp over the human head, jaw weights as colour).
"""
import argparse
import base64
import json
import os
import re
import struct
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))

from fo4sf import facefit, headcorr, skyrimtri  # noqa: E402

SEXES = {False: "male", True: "female"}
CA = "meshes\\actors\\character\\character assets\\"
BEASTS = {
    "KhajiitRace": {False: {"head": "maleheadkhajiit", "mouth": "mouth\\malemouthkhajiit", "eyes": "eyeskhajiit",
                            "tail": "maletailkhajiit"},
                    True: {"head": "femaleheadkhajiit", "mouth": "mouth\\mouthkhajiitfemale",
                           "eyes": "eyeskhajiitfemale", "tail": "femaletailkhajiit"}},
    "ArgonianRace": {False: {"head": "maleheadargonian", "mouth": "mouth\\mouthargonian", "eyes": "eyesargonian",
                             "tail": "maletailargonian"},
                     True: {"head": "femaleheadargonian", "mouth": "mouth\\mouthargonian", "eyes": "eyesargonian",
                            "tail": "femaletailargonian"}}}
HUMAN_EYES = {False: "eyesmale", True: "eyesfemale"}
SKELETONS = {False: ("meshes\\actors\\character\\character assets\\skeleton.nif",
                     "meshes\\actors\\character\\character assets\\skeletonbeast.nif"),
             True: ("meshes\\actors\\character\\character assets female\\skeleton_female.nif",
                    "meshes\\actors\\character\\character assets female\\skeletonbeast_female.nif")}
LANDMARKS = ("eye_left", "eye_right", "mouth_left", "mouth_right", "nose_tip", "crown", "back", "side_left",
             "side_right")
MAX_KEYS = 128


# ----------------------------------------------------------------------------------------------- landmarks
def mesh_points(data):
    """(model-space points, triangles) of every skinned shape of a Skyrim NIF (mouth_probe.skyrim_mesh)."""
    import mouth_probe
    got = mouth_probe.skyrim_mesh(data)
    return (got[0], got[1]) if got is not None else (None, None)


def eye_centres(eye_pts):
    """(left, right) centres of an eyes part (two eyeballs: split by the sign of x)."""
    p = np.asarray(eye_pts, float)
    return p[p[:, 0] > 0].mean(0), p[p[:, 0] < 0].mean(0)


def landmarks(v, f, eyes):
    """{name: point} on a head in model space (+Z up, +Y forward): eye centres (given), mouth corners (the ends of the
    mouth hole; else None), nose tip (front-most near the middle above the mouth), crown (highest), back (rear-most
    at eye height), sides (furthest out at eye height)."""
    v = np.asarray(v, float)
    out = {"eye_left": np.asarray(eyes[0], float), "eye_right": np.asarray(eyes[1], float)}
    eye_z = (out["eye_left"][2] + out["eye_right"][2]) / 2
    span = np.ptp(v[:, 2])
    hole = headcorr.mouth_hole(v, headcorr.main_triangles(f, len(v)))
    if hole is not None:
        hx = v[hole][:, 0]
        out["mouth_left"], out["mouth_right"] = v[hole[hx.argmax()]], v[hole[hx.argmin()]]
        mouth_z = v[hole][:, 2].mean()
    else:
        out["mouth_left"] = out["mouth_right"] = None
        mouth_z = eye_z - 0.25 * span
    mid = np.abs(v[:, 0]) < 0.03 * span
    above = mid & (v[:, 2] > mouth_z) & (v[:, 2] < eye_z)
    out["nose_tip"] = v[above][v[above][:, 1].argmax()] if above.any() else None
    out["crown"] = v[v[:, 2].argmax()]
    band = np.abs(v[:, 2] - eye_z) < 0.05 * span
    out["back"] = v[band & mid][v[band & mid][:, 1].argmin()] if (band & mid).any() else None
    out["side_left"] = v[band][v[band][:, 0].argmax()] if band.any() else None
    out["side_right"] = v[band][v[band][:, 0].argmin()] if band.any() else None
    return out


# ------------------------------------------------------------------------------------------------ the warp
def tps_fit(src, dst):
    """3-D thin-plate spline (kernel |r|) taking src landmarks exactly onto dst: (weights (n, 3), affine (4, 3))."""
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    n = len(src)
    K = np.linalg.norm(src[:, None] - src[None], axis=2)
    P = np.hstack([np.ones((n, 1)), src])
    A = np.zeros((n + 4, n + 4))
    A[:n, :n], A[:n, n:], A[n:, :n] = K, P, P.T
    b = np.zeros((n + 4, 3))
    b[:n] = dst
    sol = np.linalg.lstsq(A, b, rcond=None)[0]
    return sol[:n], sol[n:]


def tps_apply(src_landmarks, fit, pts):
    w, aff = fit
    pts = np.asarray(pts, float)
    K = np.linalg.norm(pts[:, None] - np.asarray(src_landmarks, float)[None], axis=2)
    return K @ w + np.hstack([np.ones((len(pts), 1)), pts]) @ aff


def warp(beast_v, beast_lm, human_lm):
    """beast_v warped by the landmarks both heads have (None ones left out). Returns (points, names used)."""
    names = [k for k in LANDMARKS if beast_lm.get(k) is not None and human_lm.get(k) is not None]
    if len(names) < 5:
        raise ValueError(f"only {len(names)} landmarks on both heads: {names}")
    src = np.array([beast_lm[k] for k in names])
    dst = np.array([human_lm[k] for k in names])
    return tps_apply(src, tps_fit(src, dst), beast_v), names


# --------------------------------------------------------------------------------------------- jaw check
def jaw_check(aah_drop, jaw_weight, share=0.25):
    """Mean jaw weight on the vertices Aah drops (>= share of the largest drop) and on those it leaves still (< 2 %)."""
    d = np.asarray(aah_drop, float)
    top = d.max() if len(d) else 0.0
    if top <= 0:
        return None
    moving, still = d >= share * top, d < 0.02 * top
    return {"moving_vertices": int(moving.sum()), "jaw_weight_moving": round(float(jaw_weight[moving].mean()), 3),
            "jaw_weight_still": round(float(jaw_weight[still].mean()), 3) if still.any() else None}


# -------------------------------------------------------------------------------------------- skeleton etc.
def node_names(data):
    """Names of every *Node block of a NIF (Skyrim / FO4 layout: name string index first)."""
    from fo4sf import nif as nifmod
    n = nifmod.parse(data)
    out = []
    for i, b in enumerate(n.blocks):
        if n.type_of(i).endswith("Node") and len(b) >= 4:
            k = struct.unpack_from("<i", b, 0)[0]
            if 0 <= k < len(n.strings):
                out.append(n.strings[k].decode("latin-1"))
    return out


def morph_records(sf_esm, wanted_parts=("Human_Male_Head", "Human_Female_Head")):
    """Starfield's MRPH fields: per distinct BMPP value how many records use it, and the fields of the morph records
    the given head parts name."""
    from fo4sf import sfplugin
    recs = sfplugin.records(sf_esm, [b"MRPH", b"HDPT"])

    def text(d):
        runs = re.findall(rb"[ -~]{3,}", bytes(d))
        return max(runs, key=len).decode("latin-1") if runs else ""
    bmpp, out = {}, {"bone_morph_files": {}, "head_parts": {}}
    by_fid = {}
    for t, _h, s, fid in recs:
        if t == b"MRPH":
            by_fid[fid] = s
            v = text(dict(s).get(b"BMPP", b""))
            if v:
                bmpp[v] = bmpp.get(v, 0) + 1
    out["bone_morph_files"] = dict(sorted(bmpp.items(), key=lambda kv: -kv[1])[:40])
    out["morph_records"] = sum(1 for r in recs if r[0] == b"MRPH")
    out["with_bone_morph_file"] = sum(bmpp.values())
    for t, _h, s, fid in recs:
        if t == b"HDPT" and sfplugin.edid(s) in wanted_parts:
            m = by_fid.get(struct.unpack_from("<I", bytes(dict(s).get(b"MNAM", b"\0\0\0\0")), 0)[0])
            out["head_parts"][sfplugin.edid(s)] = None if m is None else {
                sig.decode(): text(d) for sig, d in m if sig in (b"EDID", b"TMPP", b"TCMP", b"BMPP")}
    return out


def b64(a, dt):
    return base64.b64encode(np.ascontiguousarray(a, dt).tobytes()).decode()


def viewer(path, scenes):
    """scenes: {name: [(label, [(verts, tris, colour or None, per-vertex value 0..1 or None, transparent)])]}."""
    payload = {}
    for name, cols in scenes.items():
        payload[name] = [{"l": l, "m": [{"v": b64(v, "<f4"), "f": b64(f, "<u4"), "c": c,
                                         "w": b64(np.clip(w, 0, 1), "<f4") if w is not None else None, "t": bool(t)}
                                        for v, f, c, w, t in ms]} for l, ms in cols]
    html = """<!doctype html><html><head><meta charset="utf-8"><title>Beast heads</title>
<style>body{margin:0;font:14px sans-serif;background:#222;color:#ddd}#ui{position:absolute;top:8px;left:8px;
background:#000a;padding:8px;border-radius:6px;z-index:2}#lab{position:absolute;top:48px;width:100%;display:flex;
pointer-events:none}#lab div{flex:1;text-align:center}</style></head><body>
<div id="ui"><select id="pick"></select><br>colour: Starfield jaw-bone weight (red = jaw)</div><div id="lab"></div>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const P=__DATA__;
function dec(s,T){const b=atob(s),a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return new T(a.buffer)}
const r=new THREE.WebGLRenderer({antialias:true});r.setSize(innerWidth,innerHeight);document.body.appendChild(r.domElement);
const sc=new THREE.Scene();sc.background=new THREE.Color(0x222222);
const cam=new THREE.PerspectiveCamera(30,innerWidth/innerHeight,0.01,10);cam.up.set(0,0,1);
const ctl=new THREE.OrbitControls(cam,r.domElement);
sc.add(new THREE.HemisphereLight(0xffffff,0x444444,1.0));const dl=new THREE.DirectionalLight(0xffffff,0.6);dl.position.set(1,2,2);sc.add(dl);
let objs=[];
function build(){objs.forEach(o=>sc.remove(o));objs=[];const cols=P[pick.value],n=cols.length;
lab.innerHTML=cols.map(c=>'<div>'+c.l+'</div>').join('');let ctr=null;
cols.forEach((c,i)=>{c.m.forEach(m=>{const v=dec(m.v,Float32Array),g=new THREE.BufferGeometry();
g.setAttribute('position',new THREE.BufferAttribute(v,3));g.setIndex(new THREE.BufferAttribute(dec(m.f,Uint32Array),1));g.computeVertexNormals();
let mat;if(m.w){const w=dec(m.w,Float32Array),col=new Float32Array(v.length);for(let k=0;k<w.length;k++){col[3*k]=0.85;col[3*k+1]=0.85*(1-w[k])+0.1;col[3*k+2]=0.85*(1-w[k])+0.1}
g.setAttribute('color',new THREE.BufferAttribute(col,3));mat=new THREE.MeshStandardMaterial({vertexColors:true,roughness:0.6,side:THREE.DoubleSide})}
else mat=new THREE.MeshStandardMaterial({color:m.c,roughness:0.7,side:THREE.DoubleSide,transparent:m.t,opacity:m.t?0.35:1,depthWrite:!m.t});
const o=new THREE.Mesh(g,mat);o.position.x=(i-(n-1)/2)*0.3;sc.add(o);objs.push(o);
if(!ctr){g.computeBoundingBox();ctr=new THREE.Vector3();g.boundingBox.getCenter(ctr)}})});
objs.forEach(o=>{o.position.y-=ctr.y;o.position.z-=ctr.z});cam.position.set(0,1.3,0.1);ctl.target.set(0,0,0)}
pick.innerHTML=Object.keys(P).map(s=>'<option>'+s+'</option>').join('');pick.onchange=build;
build();(function loop(){requestAnimationFrame(loop);ctl.update();r.render(sc,cam)})();
onresize=()=>{cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix();r.setSize(innerWidth,innerHeight)};
</script></body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html.replace("__DATA__", json.dumps(payload)))


# ------------------------------------------------------------------------------------------------------ main
def read_tri(face_fit, sky, path, deltas=True):
    try:
        return skyrimtri.parse(face_fit.hkx_to_af.read_any(path, sky), deltas=deltas)
    except (SystemExit, skyrimtri.TriError):
        return None


def probe_sex(a, sky, sf_data, female, face_fit, race_probe):
    sex = SEXES[female]
    rep, scenes = {}, {}
    head, _base, _races, al, _disp, trep = race_probe.race_transfer(sky, sf_data, female, 0, face_fit)
    node = np.asarray(head.model_xf if getattr(head, "model_xf", None) is not None else np.eye(4), float)
    s, R, t = al[:3]
    sk_to_local = lambda p: s * np.asarray(p, float) @ R.T + t           # noqa: E731
    hum_bytes = face_fit.hkx_to_af.read_any(face_fit.SKY_HEADS[female], sky)
    hum_v = face_fit.skyrim_head(hum_bytes, model=True)
    hum_f = face_fit.skyrim_head_triangles(hum_bytes)
    hum_eyes = mesh_points(face_fit.hkx_to_af.read_any(CA + HUMAN_EYES[female] + ".nif", sky))[0]
    hum_lm = landmarks(hum_v, hum_f, eye_centres(hum_eyes))
    jaw_cols = [i for i, b in enumerate(head.bones) if "jaw" in b.lower()]
    rep["starfield_jaw_bones"] = [head.bones[i] for i in jaw_cols]
    for race, parts in BEASTS.items():
        p = parts[female]
        r = {}
        try:
            hb = face_fit.hkx_to_af.read_any(CA + p["head"] + ".nif", sky)
            bv = face_fit.skyrim_head(hb, model=True)
            bf = face_fit.skyrim_head_triangles(hb)
            if bv is None or bf is None:
                raise ValueError("no head shape in the beast head NIF")
            M = face_fit.skyrim_head_matrix(hb)
            eyes = mesh_points(face_fit.hkx_to_af.read_any(CA + p["eyes"] + ".nif", sky))[0]
            if eyes is None:
                raise ValueError("no eyes")
            blm = landmarks(bv, bf, eye_centres(eyes))
            warped, used = warp(bv, blm, hum_lm)
            dist = np.sqrt(np.min(headcorr.closest_on_triangles(warped[::3], *(hum_v[hum_f[:, i]]
                                                                              for i in range(3)))[1], 1))
            r.update(vertices=int(len(bv)), landmarks_used=used,
                     landmarks={k: [round(float(x), 2) for x in v] if v is not None else None for k, v in blm.items()},
                     warped_to_human_surface_units={"median": round(float(np.median(dist)), 3),
                                                    "p95": round(float(np.percentile(dist, 95)), 3)})
            # onto Starfield's head: the surface matching, then the face-bone weights there
            # Starfield's head is the source here (15,000 vertices): nearest compatible point, no neighbour table
            corr = headcorr.correspond(head.vertices, head.triangles, sk_to_local(warped), bf, to_model=None, mu=0.0)
            W = corr.sample(head.weights)
            W = W / np.maximum(W.sum(1, keepdims=True), 1e-9)
            jaw_w = W[:, jaw_cols].sum(1) if jaw_cols else np.zeros(len(bv))
            top = np.argsort(-W.sum(0))[:12]
            r["weights"] = {"bones_used": int((W.max(0) > 0.05).sum()),
                            "top_bones": {head.bones[i]: round(float(W[:, i].sum() / len(bv)), 3) for i in top}}
            expr = read_tri(face_fit, sky, CA + p["head"] + ".tri")
            if expr is not None:
                aah = next((m["deltas"] for m in expr["morphs"] if m["name"].lower() == "aah"), None)
                if aah is not None and len(aah) == len(bv):
                    drop = -(aah @ M[:3, :3].T)[:, 2]
                    r["jaw_check"] = jaw_check(drop, jaw_w)
                r["expressions"] = [m["name"] for m in expr["morphs"]]
            sliders = {}
            for part in ("head", "mouth", "eyes"):
                cg = read_tri(face_fit, sky, CA + p[part] + "chargen.tri", deltas=False)
                sliders[part] = [m["name"] for m in cg["morphs"]] if cg is not None else None
            names = sorted({n.lower() for v in sliders.values() if v for n in v})
            r["sliders"] = {"per_part": {k: len(v) if v is not None else None for k, v in sliders.items()},
                            "distinct": len(names), "fit_in_one_morph_dat": len(names) + 3 <= MAX_KEYS,
                            "names": names}
            try:
                tail = face_fit.hkx_to_af.read_any(CA + p["tail"] + ".nif", sky)
                from fo4sf import nif as nifmod, skyrimskin
                ts = skyrimskin.skinned_shapes(nifmod.parse(tail))
                r["tail"] = {"vertices": sum(len(x.positions) for x in ts),
                             "bones": sorted({b.decode("latin-1") for x in ts for b in x.bones})}
            except (SystemExit, ValueError) as e:
                r["tail"] = {"error": str(e)}
            key = f"{race} {sex}"
            scenes[key] = [
                ("Skyrim " + race, [(bv, bf, 0xc8b090, None, False)]),
                ("warped onto Skyrim's human head", [(warped, bf, 0xc8b090, None, False),
                                                     (hum_v, hum_f, 0x7090c0, None, True)]),
                ("Starfield jaw weight", [(bv, bf, None, jaw_w, False)])]
        except (SystemExit, ValueError) as e:
            r["error"] = str(e)
        rep[race] = r
        print(f"{sex} {race}: " + json.dumps({k: v for k, v in r.items() if k not in ("landmarks", "expressions",
                                                                                       "sliders", "weights")}))
    rep["alignment_rms_m"] = trep["alignment"]["rms_m"]
    return rep, scenes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True, help="Starfield install folder")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    import face_fit
    import race_probe
    t0 = time.time()
    sf_data = os.path.join(a.starfield, "Data")
    sky = archives(a.skyrim_data)
    os.makedirs(a.out, exist_ok=True)
    report, scenes = {"morph_records": morph_records(os.path.join(sf_data, "Starfield.esm"))}, {}
    print("Starfield morph records:", json.dumps(report["morph_records"])[:600])
    for female in (False, True):
        rep, sc = probe_sex(a, sky, sf_data, female, face_fit, race_probe)
        report[SEXES[female]] = rep
        scenes.update(sc)
        try:
            human, beast = (set(node_names(face_fit.hkx_to_af.read_any(p, sky))) for p in SKELETONS[female])
            report[SEXES[female]]["skeleton"] = {"human_nodes": len(human), "beast_nodes": len(beast),
                                                 "beast_only": sorted(beast - human),
                                                 "human_only": sorted(human - beast)}
        except (SystemExit, ValueError) as e:
            report[SEXES[female]]["skeleton"] = {"error": str(e)}
    viewer(os.path.join(a.out, "beast_view.html"), scenes)
    with open(os.path.join(a.out, "beast_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    print(f"-> {os.path.join(a.out, 'beast_probe.json')}, beast_view.html ({time.time() - t0:.0f} s)")
    return 0


def archives(skyrim_data):
    from fo4sf import bsa
    return bsa.SkyrimArchives(skyrim_data)


if __name__ == "__main__":
    sys.exit(main())
