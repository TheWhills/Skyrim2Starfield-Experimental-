"""Side-by-side check of how a converted KS wig fits Starfield's head (docs/armor/animation-port.md "SMP hair ->
Starfield cloth"): writes one HTML page (open it in a browser: drag to turn, wheel to zoom) with

  * the Starfield female base head (tan), its mesh read from the game (shape node transform applied),
  * the Skyrim female base head moved by the same fit as the wig (blue): where the two heads differ is where a wig
    made for Skyrim's head cannot fit Starfield's,
  * the wig at rest (grey), its points inside the Starfield head in red (deeper = redder),

with a slice slider (a thin left-right slab: the middle slab shows the forehead profile) and the numbers printed and
written next to the page. Read-only on both games' files.

    python -I scripts\\armor\\hair_fit_view.py --ks "<KS Hairdos SMP>" --starfield "<Starfield>"
        --skyrim-data "<Skyrim SE>\\Data" --wig Anna --out C:\\Modding\\work\\hair_fit_anna.html

By default the wig is placed with the per-axis female fit measured from the two heads (as hair_pack --skyrim-data;
--uniform: one scale); --male
uses the male constants (hair_pack without --skyrim-data); --head-scale / --head-offset place it by hand. Base heads
only: a character's own face sliders move Starfield's face bones on top of this.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

from fo4sf import nif as nifmod  # noqa: E402
from fo4sf import skyrimhair, smpcloth  # noqa: E402
from fo4sf import smpconfig as smp  # noqa: E402
import hair_pack  # noqa: E402

INSIDE = -0.002          # m: a wig point this far under the head surface counts as inside


def head_depth(points: np.ndarray, head_pts: np.ndarray, head_nrm: np.ndarray) -> np.ndarray:
    """Signed distance of each point to the head surface (skyrimhair.nearest_surface), NaN where the test cannot
    judge it (over 3 cm from the head, or below the head mesh's neck cut)."""
    depth, dist, _idx = skyrimhair.nearest_surface(points, head_pts, head_nrm)
    return np.where(skyrimhair.judged(points, head_pts, dist), depth, np.nan)


def regions(points: np.ndarray, depth: np.ndarray, head: np.ndarray) -> dict:
    """Judged points inside the head, split by where they are relative to C_Head (model axes: +Y forward, +Z up)."""
    rel = np.asarray(points, float) - head[:3, 3]
    ok = ~np.isnan(depth)
    inside = ok & (np.nan_to_num(depth, nan=1.0) < INSIDE)
    parts = {"forehead / face (front)": rel[:, 1] > 0.04, "top": (rel[:, 1] <= 0.04) & (rel[:, 2] > 0.08),
             "sides": (np.abs(rel[:, 0]) > 0.05) & (rel[:, 1] <= 0.04) & (rel[:, 2] <= 0.08),
             "back": (rel[:, 1] < -0.04) & (rel[:, 2] <= 0.08)}
    out = {"wig_points": int(len(points)), "judged (near the head)": int(ok.sum()), "inside": int(inside.sum()),
           "inside_percent_of_judged": round(100.0 * float(inside.sum()) / max(int(ok.sum()), 1), 2),
           "deepest_mm": round(-1000.0 * float(np.nanmin(depth)), 1) if ok.any() else 0.0}
    for name, m in parts.items():
        out[name] = int((inside & m).sum())
    return out


hairline = skyrimhair.hairline


def page(sets: dict, title: str, stats: dict) -> str:
    """The HTML viewer: sets {name: (points (N, 3) model space, colours (N, 3) 0..1[, triangles])}; sets with
    triangles can also be drawn as shaded surfaces (the 'Surfaces' button). three.js maps model (x, y, z) to (x, z, y)
    so +Z is up and the face looks at the 'front' camera."""
    data = {}
    for k, v in sets.items():
        p, c = v[0], v[1]
        d = {"p": np.round(np.asarray(p, float)[:, [0, 2, 1]] * 1000.0).astype(int).ravel().tolist(),
             "c": np.round(np.asarray(c, float) * 255).astype(int).ravel().tolist()}
        if len(v) > 2 and v[2] is not None and len(v[2]):
            d["t"] = np.asarray(v[2], int).ravel().tolist()
        data[k] = d
    return """<!doctype html><html><head><meta charset="utf-8"><title>Hair fit</title>
<style>body{margin:0;background:#1b1d22;color:#ddd;font:13px system-ui,sans-serif}#ui{position:fixed;top:10px;left:10px;
background:#2a2d34e0;padding:10px 12px;border-radius:8px;max-width:330px}#ui label{display:block;margin:3px 0}
button{margin:2px;background:#3b4050;color:#eee;border:1px solid #555;border-radius:4px;padding:3px 8px;cursor:pointer}
pre{white-space:pre-wrap;font-size:12px;margin:6px 0 0}</style></head><body><div id="ui"><b>TITLE</b>
<div id="toggles"></div><div><button data-v="front">Front</button><button data-v="side">Side</button>
<button data-v="top">Top</button><button data-v="back">Back</button></div>
<div><button id="surf">Surfaces</button> <span id="mode">points</span></div>
<label>Slice (left-right, cm): <input id="slice" type="range" min="-12" max="12" step="0.5" value="0"
 style="width:150px"> <span id="sv">off</span></label><label><input id="sliceon" type="checkbox"> show slice only
</label><pre id="stats">STATS</pre></div>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const DATA=DATAJSON;const scene=new THREE.Scene();const cam=new THREE.PerspectiveCamera(35,innerWidth/innerHeight,0.01,20);
scene.background=new THREE.Color(0x1b1d22);const r=new THREE.WebGLRenderer({antialias:true});r.setSize(innerWidth,innerHeight);r.setPixelRatio(devicePixelRatio);
document.body.appendChild(r.domElement);const ctl=new THREE.OrbitControls(cam,r.domElement);
let cx=0,cy=0,cz=0,n=0;for(const k in DATA){const p=DATA[k].p;for(let i=0;i<p.length;i+=3){cx+=p[i];cy+=p[i+1];cz+=p[i+2];n++;}}
const C=new THREE.Vector3(cx/n/1000,cy/n/1000,cz/n/1000);ctl.target.copy(C);
const objs={};const tg=document.getElementById('toggles');
scene.add(new THREE.AmbientLight(0xffffff,0.45));const sun=new THREE.DirectionalLight(0xffffff,0.8);cam.add(sun);scene.add(cam);
let surfaces=false;
for(const k in DATA){const g=new THREE.BufferGeometry();const p=Float32Array.from(DATA[k].p,v=>v/1000);
 g.setAttribute('position',new THREE.BufferAttribute(p,3));g.setAttribute('color',new THREE.BufferAttribute(Float32Array.from(DATA[k].c,v=>v/255),3));
 const m=new THREE.Points(g,new THREE.PointsMaterial({size:0.003,vertexColors:true}));scene.add(m);
 let mesh=null;if(DATA[k].t){const mg=new THREE.BufferGeometry();mg.setAttribute('position',new THREE.BufferAttribute(p.slice(),3));
  mg.setAttribute('color',g.getAttribute('color'));mg.setIndex(DATA[k].t);mg.computeVertexNormals();
  mesh=new THREE.Mesh(mg,new THREE.MeshStandardMaterial({vertexColors:true,side:THREE.DoubleSide,roughness:0.85}));mesh.visible=false;scene.add(mesh);}
 objs[k]={m,mesh,on:true,all:g.getAttribute('position').array.slice()};
 const l=document.createElement('label');l.innerHTML='<input type=checkbox checked> '+k;l.firstChild.onchange=e=>{objs[k].on=e.target.checked;show();};tg.appendChild(l);}
function show(){const sl=document.getElementById('sliceon').checked;for(const k in objs){const o=objs[k];
 const asMesh=surfaces&&o.mesh&&!sl;o.m.visible=o.on&&!asMesh;if(o.mesh)o.mesh.visible=o.on&&asMesh;}
 document.getElementById('mode').textContent=surfaces&&!sl?'surfaces':'points';}
document.getElementById('surf').onclick=()=>{surfaces=!surfaces;show();};
function view(v){const d=0.75;const o={front:[0,0,d],back:[0,0,-d],side:[d,0,0],top:[0,d,0.0001]}[v];
 cam.position.set(C.x+o[0],C.y+o[1],C.z+o[2]);ctl.update();}
document.querySelectorAll('button[data-v]').forEach(b=>b.onclick=()=>view(b.dataset.v));
function slice(){const on=document.getElementById('sliceon').checked;const s=parseFloat(document.getElementById('slice').value)/100;
 document.getElementById('sv').textContent=on?(s*100).toFixed(1)+' cm':'off';
 for(const k in objs){const o=objs[k];const a=o.m.geometry.getAttribute('position');const src=o.all;
  for(let i=0;i<src.length;i+=3){const keep=!on||Math.abs(src[i]-s)<0.008;a.array[i]=src[i];a.array[i+1]=keep?src[i+1]:1e6;a.array[i+2]=src[i+2];}
  a.needsUpdate=true;}}
document.getElementById('slice').oninput=slice;document.getElementById('sliceon').onchange=()=>{slice();show();if(document.getElementById('sliceon').checked)view('side');};
view('front');addEventListener('resize',()=>{cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix();r.setSize(innerWidth,innerHeight);});
(function loop(){requestAnimationFrame(loop);r.render(scene,cam);})();
</script></body></html>""".replace("TITLE", title).replace("STATS", json.dumps(stats, indent=1)).replace(
        "DATAJSON", json.dumps(data, separators=(",", ":")))


def wig_hair_of(ks, sf_world, wig, scale, offset):
    src = hair_pack.LooseRoots(ks)
    want = wig.lower()
    rel = next((k for k in src.index if k.startswith("meshes/") and hair_pack.WIG_GLOB.search(k)
                and os.path.splitext(os.path.basename(k))[0].lower() == want), None)
    if rel is None:
        raise SystemExit(f"no wig '{wig}' (meshes/armor/kswigshdt/f/{wig}.nif under --ks)")
    raw = src._read(rel)
    paths = smp.nif_physics_paths(nifmod.parse(raw))
    xml = src.data(paths[0]) if paths else None
    return skyrimhair.convert(raw, xml, sf_world, scale, offset)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ks", required=True, nargs="+")
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--wig", default="Anna")
    ap.add_argument("--out", required=True, help="the .html page to write (outside the repository)")
    ap.add_argument("--male", action="store_true", help="place the wig with the male constants instead")
    ap.add_argument("--uniform", action="store_true", help="the female fit with one scale instead of one per axis")
    ap.add_argument("--head-scale", type=float)
    ap.add_argument("--head-offset", type=float, nargs=3, metavar=("X", "Y", "Z"))
    ap.add_argument("--max-points", type=int, default=20000, help="points per set in the page")
    ap.add_argument("--no-push-out", action="store_true", help="show the wig without the conform step hair_pack does")
    ap.add_argument("--hairline-lift", type=float, help="mm to raise the front hairline everywhere (default: per "
                                                        "angle up to the vanilla hair's, as hair_pack; 0 = off)")
    ap.add_argument("--volume", type=float, help="mm to stand the hair off the scalp (default: up to the vanilla "
                                                 "hair's crown, at most 20, as hair_pack; 0 = off)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    report = {}
    root = smpcloth.check_template(hair_pack.find_template(a.starfield, report))
    sk = smpcloth.human_skeleton(root)
    world = smpcloth.skeleton_world(sk)
    sf_world = {b["name"]: world[i] for i, b in enumerate(sk["bones"])}
    head = sf_world[skyrimhair.SF_HEAD]
    sky_pts, anchor, sf_pts, sf_nrm = hair_pack.load_female_heads(a.skyrim_data, a.starfield)
    head_tris = hair_pack.game_mesh_of(a.starfield, hair_pack.read_game_file(a.starfield, hair_pack.SF_FEMALE_HEAD))[3]
    fit_s, fit_t, fit_rms = skyrimhair.fit_head(sky_pts, anchor, sf_pts, head)
    ax_s, ax_t, ax_rms = skyrimhair.fit_head_axes(sky_pts, anchor, sf_pts, head)
    if a.head_scale is not None or a.head_offset is not None:
        scale = a.head_scale if a.head_scale is not None else skyrimhair.HEAD_SCALE
        offset = tuple(a.head_offset) if a.head_offset is not None else skyrimhair.HEAD_OFFSET
        used = "by hand"
    elif a.male:
        scale, offset, used = skyrimhair.HEAD_SCALE, skyrimhair.HEAD_OFFSET, "male constants"
    elif a.uniform:
        scale, offset, used = fit_s, fit_t, "female fit, one scale (measured)"
    else:
        scale, offset, used = np.array(ax_s), ax_t, "female fit, per axis (measured)"
    sky_moved = head[:3, 3] + np.asarray(offset) + scale * (sky_pts - anchor[:3, 3]) * skyrimhair.UNIT
    wig_hair = wig_hair_of(a.ks, sf_world, a.wig, scale, offset)
    vanilla = vanilla_tris = None                      # the cloth template hair's facebones mesh: Starfield's own fit
    tpl = report.get("cloth_template") or ""
    if ":" in tpl:
        rel = os.path.splitext(tpl.split(":", 1)[1].replace("\\", "/"))[0] + "_facebones.nif"
        raw = hair_pack.read_game_file(a.starfield, rel)
        got = hair_pack.game_mesh_of(a.starfield, raw) if raw is not None else None
        vanilla = got[0] if got is not None else None
        vanilla_tris = got[3] if got is not None else None
    raw_pts = np.concatenate([np.asarray(sh.positions, float) for sh in wig_hair.shapes])
    hl_van = hairline(vanilla, sf_pts, sf_nrm, head) if vanilla is not None else None
    hl_raw = hairline(raw_pts, sf_pts, sf_nrm, head)
    prof_van = skyrimhair.hairline_profile(vanilla, sf_pts, sf_nrm, head) if vanilla is not None else None
    prof_raw = skyrimhair.hairline_profile(raw_pts, sf_pts, sf_nrm, head)
    crown_van = skyrimhair.crown_height(vanilla, head) if vanilla is not None else None
    crown_raw = skyrimhair.crown_height(raw_pts, head)
    lift = 0.0
    if a.hairline_lift is not None:
        lift = a.hairline_lift / 1000.0
    elif prof_van is not None:
        lift = skyrimhair.lift_profile(prof_raw, prof_van)
    if lift:
        wig_hair = skyrimhair.lift_hairline(wig_hair, sf_pts, sf_nrm, head, lift)
    volume = 0.0
    if a.volume is not None:
        volume = a.volume / 1000.0
    elif crown_van is not None and crown_raw is not None:
        volume = float(np.clip(crown_van - crown_raw, 0.0, 0.02))
    if volume:                         # as hair_pack: fading to nothing at the (lifted) hairline
        edge = skyrimhair.hairline_profile(np.concatenate([np.asarray(sh.positions, float) for sh in wig_hair.shapes]),
                                           sf_pts, sf_nrm, head)
        wig_hair = skyrimhair.add_volume(wig_hair, sf_pts, sf_nrm, head, volume, edge=edge)
    before = None
    if not a.no_push_out:
        before = regions(np.concatenate([np.asarray(sh.positions, float) for sh in wig_hair.shapes]),
                         head_depth(np.concatenate([np.asarray(sh.positions, float) for sh in wig_hair.shapes]),
                                    sf_pts, sf_nrm), head)
        wig_hair, _push = skyrimhair.push_out(wig_hair, sf_pts, sf_nrm)
    wig = np.concatenate([np.asarray(sh.positions, float) for sh in wig_hair.shapes])
    depth = head_depth(wig, sf_pts, sf_nrm)
    sky_depth, _d, _i = skyrimhair.nearest_surface(sky_moved, sf_pts, sf_nrm)
    hl_wig = hairline(wig, sf_pts, sf_nrm, head)
    prof_new = skyrimhair.hairline_profile(wig, sf_pts, sf_nrm, head)
    stats = {"wig": a.wig, "placement": used, "scale": np.round(np.asarray(scale, float), 4).tolist(),
             "offset_m": [round(x, 4) for x in offset],
             "female_fit_per_axis": {"scale_xyz (width, depth, height)": [round(x, 4) for x in ax_s],
                                     "offset_m": [round(x, 4) for x in ax_t], "rms_mm": round(1000 * ax_rms, 1)},
             "female_fit": {"scale": round(fit_s, 4), "offset_m": [round(x, 4) for x in fit_t],
                            "rms_mm": round(1000 * fit_rms, 1)},
             "male_constants": {"scale": skyrimhair.HEAD_SCALE, "offset_m": list(skyrimhair.HEAD_OFFSET)},
             "wig_inside_head": regions(wig, depth, head),
             "hairline_above_C_Head_mm": {
                 a.wig: None if hl_wig is None else round(1000 * hl_wig, 1),
                 a.wig + " before the lift": None if hl_raw is None else round(1000 * hl_raw, 1),
                 "lift_mm_by_angle": ({k: round(1000 * v, 1) for k, v in lift.items()} if isinstance(lift, dict)
                                      else round(1000 * lift, 1)),
                 "by_angle (deg from the front: wig before / after / vanilla)": {
                     k: [None if prof_raw[k] is None else round(1000 * prof_raw[k], 1),
                         None if prof_new[k] is None else round(1000 * prof_new[k], 1),
                         None if prof_van is None or prof_van.get(k) is None else round(1000 * prof_van[k], 1)]
                     for k in prof_raw},
                 "vanilla " + os.path.basename(tpl.split(":", 1)[-1]): None if hl_van is None else round(1000 * hl_van, 1),
                 "note": "middle of the forehead; lower = the hair covers more of the forehead"},
             "crown_above_C_Head_mm": {"wig before": None if crown_raw is None else round(1000 * crown_raw, 1),
                                       "wig after": round(1000 * skyrimhair.crown_height(wig, head), 1),
                                       "vanilla": None if crown_van is None else round(1000 * crown_van, 1),
                                       "volume_mm": round(1000 * volume, 1)},
             "conformed": not a.no_push_out,
             "wig_inside_head_before_conform": before,
             "skyrim_head_vs_starfield_mm": {"median_gap": round(1000 * float(np.median(sky_depth)), 1),
                                             "inside_starfield_percent": round(100 * float((sky_depth < INSIDE).mean()), 1),
                                             "outside_by_5mm_percent": round(100 * float((sky_depth > 0.005).mean()), 1)}}
    rng = np.random.default_rng(0)

    def thin(p, extra=None):
        if len(p) <= a.max_points:
            return (p, extra) if extra is not None else p
        k = np.sort(rng.choice(len(p), a.max_points, replace=False))
        return (p[k], extra[k]) if extra is not None else p[k]
    wp, wd = wig, depth                                  # all points: the surfaces need every vertex
    wd = np.nan_to_num(wd, nan=1.0)
    red = np.clip(-wd / 0.01, 0, 1)[:, None]
    wig_col = np.where(wd[:, None] < INSIDE, np.hstack([0.6 + 0.4 * red, 0.15 * (1 - red), 0.1 * (1 - red)]),
                       np.array([[0.55, 0.55, 0.58]]))
    skp = thin(sky_moved)
    wig_tris, base = [], 0
    for sh in wig_hair.shapes:
        wig_tris += [(t[0] + base, t[1] + base, t[2] + base) for t in sh.triangles]
        base += len(sh.positions)
    sets = {"Starfield female head": (sf_pts, np.tile([0.85, 0.68, 0.52], (len(sf_pts), 1)), head_tris),
            "Skyrim female head (moved by the fit)": (skp, np.tile([0.35, 0.55, 0.95], (len(skp), 1))),
            f"{a.wig} wig (red = inside the head)": (wp, wig_col, wig_tris)}
    if vanilla is not None:
        sets["Starfield's own hair (" + os.path.basename(tpl.split(":", 1)[-1]) + ")"] = (
            vanilla, np.tile([0.35, 0.85, 0.45], (len(vanilla), 1)), vanilla_tris)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page(sets, f"{a.wig}: {used}", stats))
    with open(re.sub(r"\.html?$", "", out, flags=re.I) + ".json", "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=1)
    print(json.dumps(stats, indent=1))
    print(f"\nopen in a browser: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
