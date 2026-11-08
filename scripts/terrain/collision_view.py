"""How Skyrim handles walking on a model, against what our conversion gives it (owner, 2026-11-08: "Can we look at how
skyrim handles walking over that road mesh" - RoadStraightLongRamp01 in Riverwood, an invisible hump the player
climbs and Ralof gets stuck on, gone with the road disabled).

    python -I scripts\\terrain\\collision_view.py --skyrim-data "<Skyrim SE>\\Data" ^
        --model meshes\\Landscape\\Roads\\RoadStraightLongRamp01.nif --out C:\\Modding\\work\\collision_view.html

For each model: the visible mesh, Skyrim's own collision (each Havok body with its layer), and the boxes the box
converter builds from it (skyrimconvert.collision_boxes: column boxes for landscape pieces, surface + voxel boxes for
the rest), all in metres. Measured on a 0.25 m grid from above: how far Skyrim's walkable top (its collision) is from
the visible top, and how far our boxes' top is from Skyrim's collision top (a positive excess is a step the player has
to climb that Skyrim does not have). Writes one HTML (3-D view with toggles, a top-down map of the excess) and prints
the numbers. Read-only; nothing of the game is written anywhere but --out.
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import bsa, meshcollision, nif as nifmod, sfcollision, skyrimconvert, skyrimnif  # noqa: E402

U = 1.0 / 70.0
STEP = 0.25


def visual(n):
    """(points m, triangles) of every visible shape, world-transformed."""
    P, T = [], []
    for s in skyrimnif.trishapes(n):
        t, r, k = s.translation, s.rotation, s.scale
        base = len(P)
        for x, y, z in s.positions:
            P.append(tuple((t[i] + k * (r[3 * i] * x + r[3 * i + 1] * y + r[3 * i + 2] * z)) * U for i in range(3)))
        T += [(a + base, b + base, c + base) for a, b, c in s.triangles]
    return P, T


def top_z(P, T, xs, ys):
    """Highest surface z of the triangles above each (x, y) sample (nan where none)."""
    P = np.asarray(P, np.float64)
    T = np.asarray(T, np.int64)
    out = np.full((len(ys), len(xs)), np.nan)
    if len(T) == 0:
        return out
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    lox, hix = np.minimum(np.minimum(a[:, 0], b[:, 0]), c[:, 0]), np.maximum(np.maximum(a[:, 0], b[:, 0]), c[:, 0])
    loy, hiy = np.minimum(np.minimum(a[:, 1], b[:, 1]), c[:, 1]), np.maximum(np.maximum(a[:, 1], b[:, 1]), c[:, 1])
    det = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    ok = np.abs(det) > 1e-12
    for r, y in enumerate(ys):
        rows = ok & (loy <= y) & (hiy >= y)
        if not rows.any():
            continue
        ia = np.flatnonzero(rows)
        for cidx, x in enumerate(xs):
            sel = ia[(lox[ia] <= x) & (hix[ia] >= x)]
            if len(sel) == 0:
                continue
            d = det[sel]
            l1 = ((b[sel, 1] - c[sel, 1]) * (x - c[sel, 0]) + (c[sel, 0] - b[sel, 0]) * (y - c[sel, 1])) / d
            l2 = ((c[sel, 1] - a[sel, 1]) * (x - c[sel, 0]) + (a[sel, 0] - c[sel, 0]) * (y - c[sel, 1])) / d
            l3 = 1 - l1 - l2
            inside = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
            if inside.any():
                z = l1 * a[sel, 2] + l2 * b[sel, 2] + l3 * c[sel, 2]
                out[r, cidx] = z[inside].max()
    return out


def box_top(boxes, xs, ys):
    out = np.full((len(ys), len(xs)), np.nan)
    X, Y = np.meshgrid(xs, ys)
    for (cx, cy, cz), (hx, hy, hz) in boxes:
        m = (np.abs(X - cx) <= hx) & (np.abs(Y - cy) <= hy)
        out[m] = np.fmax(out[m], cz + hz)
    return out


def stats(v):
    v = v[np.isfinite(v)]
    if not len(v):
        return None
    return {"n": int(len(v)), "median": round(float(np.median(v)), 3), "p95": round(float(np.percentile(v, 95)), 3),
            "max": round(float(v.max()), 3), "min": round(float(v.min()), 3)}


def one(src, name):
    data = src.mesh(name)
    if data is None:
        return {"model": name, "error": "not found in the Skyrim archives / loose files"}
    n = nifmod.parse(data)
    vp, vt = visual(n)
    rep = {}
    bodies = skyrimnif.collision_bodies(n, rep)
    coll = [{"layer": l, "points": [[round(c * U, 4) for c in p] for p in pts], "tris": [list(t) for t in tri],
             "solid": l not in meshcollision.NON_SOLID_LAYERS} for l, pts, tri in bodies]
    cp = [tuple(c * U for c in p) for l, pts, tri in bodies if l not in meshcollision.NON_SOLID_LAYERS for p in pts]
    ct, base = [], 0
    for l, pts, tri in bodies:
        if l in meshcollision.NON_SOLID_LAYERS:
            continue
        ct += [(a + base, b + base, c + base) for a, b, c in tri]
        base += len(pts)
    landscape = bool(skyrimconvert.LANDSCAPE_RE.search(name))
    brep = {}
    if not ct:
        boxes = []
    elif landscape:
        boxes = skyrimconvert.column_boxes(cp, ct, report=brep)
    else:
        boxes = sfcollision.mesh_boxes(cp, ct, report=brep)
    allp = np.asarray(vp + cp or [(0, 0, 0)])
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    xs = np.arange(lo[0], hi[0] + STEP / 2, STEP)
    ys = np.arange(lo[1], hi[1] + STEP / 2, STEP)
    vz, cz, bz = top_z(vp, vt, xs, ys), top_z(cp, ct, xs, ys), box_top(boxes, xs, ys)
    sky_vs_visual = cz - vz
    ours_vs_sky = bz - cz
    res = {"model": name, "landscape_rule": landscape, "box_method": "columns" if landscape else "surfaces+voxels",
           "visible_triangles": len(vt), "skyrim_bodies": [{"layer": c["layer"], "triangles": len(c["tris"]),
                                                             "solid": c["solid"]} for c in coll],
           "boxes": len(boxes), "box_report": {k: v for k, v in brep.items() if not isinstance(v, (list, dict))},
           "skyrim_collision_top_minus_visible_top_m": stats(sky_vs_visual),
           "our_box_top_minus_skyrim_collision_top_m": stats(ours_vs_sky),
           "samples_where_ours_is_over_10cm_higher": int(np.nansum(ours_vs_sky > 0.10)),
           "samples_where_ours_is_over_30cm_higher": int(np.nansum(ours_vs_sky > 0.30))}
    view = {"visual": {"points": [[round(c, 4) for c in p] for p in vp], "tris": [list(t) for t in vt]},
            "collision": coll, "boxes": [[list(c), list(h)] for c, h in boxes],
            "grid": {"x0": float(xs[0]), "y0": float(ys[0]), "step": STEP, "cols": len(xs), "rows": len(ys),
                     "excess": [[None if not np.isfinite(v) else round(float(v), 3) for v in row]
                                for row in ours_vs_sky]}}
    return res, view


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--model", action="append", required=True, help="meshes\\... path (repeatable)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    src = bsa.SkyrimArchives(a.skyrim_data)
    results, views = [], []
    for m in a.model:
        name = m.replace("/", "\\")
        if not name.lower().startswith("meshes\\"):
            name = "meshes\\" + name
        r = one(src, name)
        if isinstance(r, dict):
            print(json.dumps(r))
            continue
        res, view = r
        results.append(res)
        views.append(dict(view, title=name))
        print(json.dumps(res, indent=1))
    if views:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(PAGE.replace("__DATA__", json.dumps({"models": views, "results": results})))
        print(f"-> {a.out}")
    return 0 if views else 1


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Collision view</title>
<style>body{background:#15171a;color:#ddd;font:14px system-ui;margin:12px}label{margin-right:14px}select{background:#2a2e35;color:#ddd}
#row{display:flex;gap:12px;flex-wrap:wrap}#three{width:760px;height:560px;border:1px solid #333}canvas#map{border:1px solid #333}
pre{background:#1b1d21;padding:8px;max-width:1100px;overflow:auto}</style></head><body>
<div><select id="pick"></select>
<label><input type="checkbox" data-l="visual" checked> visible mesh (grey)</label>
<label><input type="checkbox" data-l="collision" checked> Skyrim collision (green)</label>
<label><input type="checkbox" data-l="boxes" checked> our boxes (red)</label></div>
<div id="row"><div id="three"></div><div><canvas id="map" width="360" height="360"></canvas>
<div>Top-down: our box top minus Skyrim's collision top.<br>Grey = same, red = ours higher (full red at 0.3 m: a step to climb), blue = lower.</div></div></div>
<pre id="res"></pre>
<script>const D=__DATA__;</script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const pick=document.getElementById('pick');D.models.forEach((m,i)=>{const o=document.createElement('option');o.value=i;o.textContent=m.title;pick.appendChild(o)});
let groups={},sc,cam,rn,ctl;
function meshOf(pts,tris,col,op,wire){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(pts.flat(),3));
 g.setIndex(tris.flat());g.computeVertexNormals();const grp=new THREE.Group();
 grp.add(new THREE.Mesh(g,new THREE.MeshLambertMaterial({color:col,transparent:op<1,opacity:op,side:THREE.DoubleSide,depthWrite:op>=1})));
 if(wire)grp.add(new THREE.LineSegments(new THREE.WireframeGeometry(g),new THREE.LineBasicMaterial({color:col})));return grp}
function show(i){const m=D.models[i];document.getElementById('res').textContent=JSON.stringify(D.results[i],null,1);drawMap(m);
 if(!window.THREE){document.getElementById('three').textContent='3-D view needs internet (three.js from jsdelivr)';return}
 if(!sc){sc=new THREE.Scene();sc.background=new THREE.Color(0x15171a);cam=new THREE.PerspectiveCamera(50,760/560,0.01,2000);
  rn=new THREE.WebGLRenderer({antialias:true});rn.setSize(760,560);document.getElementById('three').appendChild(rn.domElement);
  sc.add(new THREE.AmbientLight(0xffffff,0.5));const s=new THREE.DirectionalLight(0xffffff,0.7);s.position.set(-30,60,40);sc.add(s);
  ctl=new THREE.OrbitControls(cam,rn.domElement);(function loop(){requestAnimationFrame(loop);rn.render(sc,cam)})()}
 for(const k in groups)sc.remove(groups[k]);groups={};
 const conv=p=>[p[0],p[2],-p[1]];   // z up -> three's y up
 groups.visual=meshOf(m.visual.points.map(conv),m.visual.tris,0x9a9a96,1,false);
 groups.collision=new THREE.Group();for(const c of m.collision){if(!c.tris.length)continue;groups.collision.add(meshOf(c.points.map(conv),c.tris,c.solid?0x30d060:0x3080ff,0.15,true))}
 groups.boxes=new THREE.Group();for(const [c,h] of m.boxes){const b=new THREE.Mesh(new THREE.BoxGeometry(2*h[0],2*h[2],2*h[1]),new THREE.MeshLambertMaterial({color:0xff3b3b,transparent:true,opacity:0.35}));
  b.position.set(c[0],c[2],-c[1]);groups.boxes.add(b);const e=new THREE.LineSegments(new THREE.EdgesGeometry(b.geometry),new THREE.LineBasicMaterial({color:0xff3b3b}));e.position.copy(b.position);groups.boxes.add(e)}
 for(const k in groups){sc.add(groups[k]);groups[k].visible=document.querySelector(`input[data-l=${k}]`).checked}
 const box=new THREE.Box3().setFromObject(groups.visual.children.length?groups.visual:groups.collision),ctr=box.getCenter(new THREE.Vector3()),sz=box.getSize(new THREE.Vector3()).length();
 ctl.target.copy(ctr);cam.position.copy(ctr.clone().add(new THREE.Vector3(sz*0.6,sz*0.5,sz*0.6)));ctl.update()}
function drawMap(m){const cv=document.getElementById('map'),ctx=cv.getContext('2d'),g=m.grid,S=360/Math.max(g.rows,g.cols);ctx.fillStyle='#000';ctx.fillRect(0,0,360,360);
 for(let r=0;r<g.rows;r++)for(let c=0;c<g.cols;c++){const v=g.excess[r][c];if(v===null)continue;const t=Math.max(-1,Math.min(1,v/0.3)),q=110;
 ctx.fillStyle=t<0?`rgb(${Math.round(q*(1+t))},${Math.round(q*(1+t))},${Math.round(q-(255-q)*t)})`:`rgb(${Math.round(q+(255-q)*t)},${Math.round(q*(1-t))},${Math.round(q*(1-t))})`;
 ctx.fillRect(c*S,(g.rows-1-r)*S,Math.ceil(S),Math.ceil(S))}}
pick.onchange=()=>show(+pick.value);for(const c of document.querySelectorAll('input[data-l]'))c.onchange=()=>{if(groups[c.dataset.l])groups[c.dataset.l].visible=c.checked};show(0);
</script></body></html>"""


if __name__ == "__main__":
    sys.exit(main())
