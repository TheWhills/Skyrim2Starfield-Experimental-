"""Skyrim mouths (teeth, tongue, the orc's tusks) on Starfield's head, offline (races plan; owner 2026-11-09: "do we
have any way to convert the orc mouths and teeth"). Read-only.

    python -I scripts\\npc\\mouth_probe.py --skyrim-data "$sky" --starfield $sf --out C:\\Modding\\work\\races

Skyrim keeps a race's teeth in a separate head part (verified, race_survey: MouthHuman.nif 141 vertices for humans and
elves, MouthOrc.nif / MouthOrcFemale.nif 348 for orcs) with its own expression tri (Aah, BigAah, ... no race morph:
the orc mouth is made for the orc head). Starfield also has teeth as a head part (HDPT type Teeth, Human_Male_Teeth ->
Teeth.nif), skinned to face bones. Per sex this probe:
  1. reads the Skyrim mouths (human, orc) and places them on Starfield's head with face_fit's head alignment (the
     same one the race shapes use);
  2. marks each Skyrim mouth vertex jaw or upper by its expression morph Aah (mouth open: the jaw's vertices drop);
  3. reads Starfield's Teeth.nif (vertices, bone weights) and gives each Skyrim mouth vertex the weights of the
     nearest Starfield tooth vertex on the same side (jaw / upper: Starfield's side from its bone names), so lower
     teeth and tusks would follow the jaw bone in lip sync;
  4. measures how far each mouth vertex sits from the head's surface in Skyrim (Skyrim orc head) and in Starfield
     (Starfield head + the transferred orc shape): equal distances = the tusks stand out of the lips as in Skyrim;
  5. writes mouth_probe.json and mouth_view.html (Skyrim orc head + mouth next to Starfield's orc head + the placed
     mouth, jaw part coloured; Starfield's own teeth in grey).
"""
import argparse
import base64
import json
import os
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
SKY_MOUTHS = {False: {"human": r"meshes\actors\character\character assets\mouth\mouthhuman.nif",
                      "orc": r"meshes\actors\character\character assets\mouth\mouthorc.nif"},
              True: {"human": r"meshes\actors\character\character assets\mouth\mouthhumanf.nif",
                     "orc": r"meshes\actors\character\character assets\mouth\mouthorcfemale.nif"}}
SF_TEETH_PART = {False: "Human_Male_Teeth", True: "Human_Female_Teeth"}
JAW_SHARE = 0.25            # a vertex is jaw when Aah drops it by at least this share of the largest drop


# ------------------------------------------------------------------------------------------------- Skyrim side
def skyrim_mesh(data):
    """(points model space (V, 3) Skyrim units, triangles (T, 3), skin-space points, the first shape's skin -> model
    4x4) of every skinned shape of a NIF, concatenated (skin -> model per shape, as face_fit.skyrim_head)."""
    from fo4sf import nif as nifmod, skyrimskin
    pts, tris, raw, first = [], [], [], None
    for s in skyrimskin.skinned_shapes(nifmod.parse(data)):
        p = np.array(s.positions, float)
        if not len(p):
            continue
        m = facefit.skin_to_model_matrix(s.skin_transform)
        first = m if first is None else first
        tris.append(np.asarray(s.triangles, int).reshape(-1, 3) + sum(len(x) for x in pts))
        pts.append(facefit.apply4(m, p))
        raw.append(p)
    if not pts:
        return None
    return np.concatenate(pts), np.concatenate(tris), np.concatenate(raw), first


def jaw_labels(skin_pts, tri_base, aah, model_matrix=None, share=JAW_SHARE):
    """(jaw bool (V,), drop per vertex (V,)): each mouth vertex takes the Aah move of the nearest .tri base vertex (the
    .tri and the NIF share a frame, not always an order); jaw = it drops (model -z) by >= share of the largest drop."""
    j, _d = facefit._nearest(np.asarray(tri_base, float), np.asarray(skin_pts, float), 1)
    move = np.asarray(aah, float)[j[:, 0]]
    if model_matrix is not None:
        move = move @ np.asarray(model_matrix, float)[:3, :3].T
    drop = -move[:, 2]
    top = drop.max() if len(drop) else 0.0
    return (drop >= share * top) & (drop > 0) if top > 0 else np.zeros(len(drop), bool), drop


# ---------------------------------------------------------------------------------------------- Starfield side
def is_jaw_bone(name):
    n = name.lower()
    return "jaw" in n or "chin" in n or "lowerlip" in n or "lower_lip" in n or "tongue" in n


def side_of(weights):
    """Per vertex True when its heaviest bone is a jaw bone (is_jaw_bone)."""
    out = []
    for row in weights:
        if not row:
            out.append(False)
            continue
        b, _w = max(row, key=lambda bw: bw[1])
        out.append(is_jaw_bone(b))
    return np.array(out, bool)


def copy_weights(points, jaw, sf_points, sf_weights, sf_jaw):
    """Per point the bone weights of the nearest Starfield vertex on the same side (jaw / upper; any side when that
    side has none), and the distances."""
    sf_points = np.asarray(sf_points, float)
    out, dist = [None] * len(points), np.zeros(len(points))
    for side in (True, False):
        mine = np.nonzero(jaw == side)[0]
        pool = np.nonzero(sf_jaw == side)[0]
        if not len(pool):
            pool = np.arange(len(sf_points))
        if not len(mine):
            continue
        j, d = facefit._nearest(sf_points[pool], np.asarray(points, float)[mine], 1)
        for k, i in enumerate(mine):
            out[i] = sf_weights[pool[j[k, 0]]]
            dist[i] = d[k, 0]
    return out, dist


# --------------------------------------------------------------------------------------------------- measures
def surface_distance(points, verts, tris, chunk=64):
    """Signed distance of points to a closed-ish head surface: + outside (along the head's outward normals)."""
    verts, tris = np.asarray(verts, float), np.asarray(tris, int)
    a, b, c = (verts[tris[:, i]] for i in range(3))
    fn = np.cross(b - a, c - a)
    centre = verts.mean(0)
    if np.mean(np.sum(fn * ((a + b + c) / 3 - centre), 1)) < 0:     # wound inward: flip
        fn = -fn
    out = np.zeros(len(points))
    for s in range(0, len(points), chunk):
        p = np.asarray(points[s:s + chunk], float)
        bc, d2 = headcorr.closest_on_triangles(p, a, b, c)
        j = d2.argmin(1)
        r = np.arange(len(p))
        q = np.einsum("nk,nkc->nc", bc[r, j], np.stack([a[j], b[j], c[j]], 1))
        sign = np.sign(np.sum((p - q) * fn[j], 1))
        out[s:s + chunk] = np.where(sign == 0, 1, sign) * np.sqrt(d2[r, j])
    return out


def b64(a, dt):
    return base64.b64encode(np.ascontiguousarray(a, dt).tobytes()).decode()


def viewer(path, scenes):
    """scenes: {sex: [(label, [(verts, tris, colour_hex or per-vertex jaw mask, ...)])]}: meshes side by side."""
    payload = {}
    for sex, cols in scenes.items():
        payload[sex] = []
        for label, meshes in cols:
            payload[sex].append({"l": label, "m": [{"v": b64(v, "<f4"), "f": b64(f, "<u4"), "c": col,
                                                    "j": b64(np.asarray(jaw, "<u1"), "<u1") if jaw is not None else None,
                                                    "head": bool(head)}
                                                   for v, f, col, jaw, head in meshes]})
    html = """<!doctype html><html><head><meta charset="utf-8"><title>Mouths</title>
<style>body{margin:0;font:14px sans-serif;background:#222;color:#ddd}#ui{position:absolute;top:8px;left:8px;
background:#000a;padding:8px;border-radius:6px;z-index:2}#lab{position:absolute;top:44px;width:100%;display:flex;
pointer-events:none}#lab div{flex:1;text-align:center}</style></head><body>
<div id="ui"><select id="sex"></select> <label><input type="checkbox" id="heads" checked> heads</label>
<label><input type="range" id="op" min="0.1" max="1" step="0.05" value="0.55"> head opacity</label>
<br>jaw part red, upper part white; Starfield's own teeth grey</div><div id="lab"></div>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const P=__DATA__;
function dec(s,T){const b=atob(s),a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return new T(a.buffer)}
const r=new THREE.WebGLRenderer({antialias:true});r.setSize(innerWidth,innerHeight);document.body.appendChild(r.domElement);
const sc=new THREE.Scene();sc.background=new THREE.Color(0x222222);
const cam=new THREE.PerspectiveCamera(25,innerWidth/innerHeight,0.005,10);cam.up.set(0,0,1);
const ctl=new THREE.OrbitControls(cam,r.domElement);
sc.add(new THREE.HemisphereLight(0xffffff,0x444444,1.0));const dl=new THREE.DirectionalLight(0xffffff,0.6);dl.position.set(1,2,2);sc.add(dl);
let objs=[],heads=[];
function build(){objs.forEach(o=>sc.remove(o));objs=[];heads=[];const cols=P[sex.value];const n=cols.length;
lab.innerHTML=cols.map(c=>'<div>'+c.l+'</div>').join('');let ctr=null;
cols.forEach((c,i)=>{const off=(i-(n-1)/2)*0.16;c.m.forEach(m=>{const v=dec(m.v,Float32Array);const g=new THREE.BufferGeometry();
g.setAttribute('position',new THREE.BufferAttribute(v,3));g.setIndex(new THREE.BufferAttribute(dec(m.f,Uint32Array),1));g.computeVertexNormals();
let mat;if(m.j){const j=dec(m.j,Uint8Array),col=new Float32Array(v.length);for(let k=0;k<j.length;k++){col[3*k]=1;col[3*k+1]=j[k]?0.25:1;col[3*k+2]=j[k]?0.25:1}
g.setAttribute('color',new THREE.BufferAttribute(col,3));mat=new THREE.MeshStandardMaterial({vertexColors:true,roughness:0.5,side:THREE.DoubleSide})}
else mat=new THREE.MeshStandardMaterial({color:m.c,roughness:0.7,side:THREE.DoubleSide,transparent:m.head,opacity:m.head?+op.value:1,depthWrite:!m.head});
const o=new THREE.Mesh(g,mat);o.position.x=off;sc.add(o);objs.push(o);if(m.head)heads.push(o);
if(!ctr&&!m.head){g.computeBoundingBox();ctr=new THREE.Vector3();g.boundingBox.getCenter(ctr)}})});
objs.forEach(o=>{o.position.y-=ctr.y;o.position.z-=ctr.z});cam.position.set(0,0.75,0.02);ctl.target.set(0,0,0);upd()}
function upd(){heads.forEach(h=>{h.visible=document.getElementById('heads').checked;h.material.opacity=+op.value})}
sex.innerHTML=Object.keys(P).map(s=>'<option>'+s+'</option>').join('');sex.onchange=build;document.getElementById('heads').onchange=upd;op.oninput=upd;
build();(function loop(){requestAnimationFrame(loop);ctl.update();r.render(sc,cam)})();
onresize=()=>{cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix();r.setSize(innerWidth,innerHeight)};
</script></body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html.replace("__DATA__", json.dumps(payload)))


# ------------------------------------------------------------------------------------------------------- main
def sf_teeth(sf_data, female, face_fit, hair_pack):
    """(points model space, weights [(bone, w)], triangles, model path) of the race's vanilla teeth head part."""
    from fo4sf import sfplugin
    recs = sfplugin.records(os.path.join(sf_data, "Starfield.esm"), [b"HDPT"])
    part = next((r for r in recs if sfplugin.edid(r[2]) == SF_TEETH_PART[female]), None)
    if part is None:
        return None
    model = next((bytes(d).split(b"\0")[0].decode("latin-1") for s, d in part[2] if s == b"MODL"), None)
    if not model:
        return None
    rel = "meshes/" + model.replace("\\", "/").lower()
    raw, _ = face_fit.hkx_to_af.vanilla_file(rel, sf_data)
    got = hair_pack.game_mesh_of(os.path.dirname(sf_data), raw,
                                 read=lambda p: face_fit.hkx_to_af.vanilla_file(p, sf_data)[0])
    if got is None:
        return None
    pts, _nrm, ws, tris = got
    return pts, ws, np.asarray(tris, int).reshape(-1, 3), rel


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True, help="Starfield install folder")
    ap.add_argument("--out", required=True)
    ap.add_argument("--race", default="OrcRace", help="the Skyrim race whose head shape the mouth is shown in")
    a = ap.parse_args(argv)
    import face_fit
    import hair_pack
    import race_probe
    t0 = time.time()
    sf_data = os.path.join(a.starfield, "Data")
    sky = race_heads_archives(a.skyrim_data)
    os.makedirs(a.out, exist_ok=True)
    report, scenes = {}, {}
    for female in (False, True):
        sex = SEXES[female]
        head, base, races, al, disp, trep = race_probe.race_transfer(sky, sf_data, female, 4, face_fit)
        node = np.asarray(head.model_xf if getattr(head, "model_xf", None) is not None else np.eye(4), float)
        s, R, t = al[:3]
        to_sf = lambda p: facefit.apply4(node, s * np.asarray(p, float) @ R.T + t)      # noqa: E731
        race_d = disp.get(a.race)
        sf_head = facefit.apply4(node, head.vertices + (race_d if race_d is not None else 0.0))
        sky_race = next((m for m in races["morphs"] if m["name"] == a.race), None)
        sky_head = to_sf(base + (sky_race["deltas"] if sky_race is not None else 0.0))
        srep = {"alignment_rms_m": trep["alignment"]["rms_m"], "race": a.race, "mouths": {}}
        teeth = sf_teeth(sf_data, female, face_fit, hair_pack)
        if teeth is not None:
            tp, tw, tt, trel = teeth
            tjaw = side_of(tw)
            bones = sorted({b for row in tw for b, _w in row})
            srep["starfield_teeth"] = {"model": trel, "vertices": int(len(tp)), "bones": bones,
                                       "jaw_vertices": int(tjaw.sum()),
                                       "jaw_bones": [b for b in bones if is_jaw_bone(b)]}
        cols = [(f"Skyrim {a.race}", []), (f"Starfield + {a.race}", [])]
        cols[0][1].append((sky_head, races["faces"], 0xa0b8d8, None, True))
        cols[1][1].append((sf_head, head.triangles, 0xd8b8a0, None, True))
        if teeth is not None:
            cols[1][1].append((tp, tt, 0x888888, None, False))
        for kind, path in SKY_MOUTHS[female].items():
            mrep = {"nif": path}
            try:
                data = face_fit.hkx_to_af.read_any(path, sky)
                mesh = skyrim_mesh(data)
                if mesh is None:
                    raise ValueError("no skinned shape")
                model_pts, mtris, skin_pts, M = mesh
                jaw = np.zeros(len(model_pts), bool)
                try:
                    tri = skyrimtri.parse(face_fit.hkx_to_af.read_any(path[:-4] + ".tri", sky), deltas=True)
                    aah = next((m["deltas"] for m in tri["morphs"] if m["name"].lower() == "aah"), None)
                    if aah is not None:
                        jaw, drop = jaw_labels(skin_pts, tri["base"], aah, M)
                        mrep["aah_max_units"] = round(float(drop.max()), 3)
                except (SystemExit, skyrimtri.TriError) as e:
                    mrep["tri"] = f"not read: {e}"
                placed = to_sf(model_pts)
                mrep.update(vertices=int(len(model_pts)), jaw_vertices=int(jaw.sum()))
                if teeth is not None:
                    w, dist = copy_weights(placed, jaw, tp, tw, tjaw)
                    used = sorted({b for row in w if row for b, _w in row})
                    mrep["weights"] = {"bones": used, "nearest_tooth_m_median": round(float(np.median(dist)), 4),
                                       "nearest_tooth_m_max": round(float(dist.max()), 4)}
                if kind == "orc" or a.race != "OrcRace":
                    d_sky = surface_distance(to_sf(model_pts), sky_head, races["faces"])
                    d_sf = surface_distance(placed, sf_head, head.triangles)
                    diff = np.abs(d_sf - d_sky)
                    mrep["vs_head_surface"] = {
                        "skyrim_outside": int((d_sky > 0.001).sum()), "starfield_outside": int((d_sf > 0.001).sum()),
                        "difference_m_p95": round(float(np.percentile(diff, 95)), 4),
                        "difference_m_max": round(float(diff.max()), 4)}
                    cols[0][1].append((to_sf(model_pts), mtris, None, jaw, False))
                    cols[1][1].append((placed, mtris, None, jaw, False))
            except (SystemExit, ValueError) as e:
                mrep["error"] = str(e)
            srep["mouths"][kind] = mrep
            print(f"{sex} {kind}: {mrep}")
        report[sex] = srep
        scenes[sex] = cols
    viewer(os.path.join(a.out, "mouth_view.html"), scenes)
    with open(os.path.join(a.out, "mouth_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    print(f"-> {os.path.join(a.out, 'mouth_probe.json')}, mouth_view.html ({time.time() - t0:.0f} s)")
    return 0


def race_heads_archives(skyrim_data):
    from fo4sf import bsa
    return bsa.SkyrimArchives(skyrim_data)


if __name__ == "__main__":
    sys.exit(main())
