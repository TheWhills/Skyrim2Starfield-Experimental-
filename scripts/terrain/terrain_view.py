"""Look at the converted terrain around one spot: the heights the game actually has (the staged BTD), compared with
Skyrim's own ground (LAND + the height offset), plus the objects and water pieces placed there. Owner, 2026-11-08: "is
there a way we can have a visualizer of the terrain mesh to see if theres bumps we arent accounting for".

    python -I scripts\\terrain\\terrain_view.py --terrain C:\\Modding\\staging\\skyrim_all ^
        --skyrim "<Skyrim SE>\\Data\\Skyrim.esm" --pos 226.08 -628.10 --radius 40 --out C:\\Modding\\work\\terrain_view.html

--pos is `player.getpos x` / `y` (metres; with --spawn-at as in ground_at.py when the game reports the planet's merged
grid). Writes one HTML file (open it in a browser): a top-down map with four views (shaded relief of the game's
terrain; game minus Skyrim, blue lower / red higher; bumps = the terrain minus its 3 x 3-sample mean, which shows ridges
and steps; Skyrim's own relief), hover for heights and the nearest object, and a 3-D view of the same patch (drag to
turn, wheel to zoom) with the objects as boxes and the water pieces as planes. Also prints the largest differences and
bumps. Reads the whole BTD (a few hundred MB for Tamriel), so it takes a while.
"""
import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import btd, fo4land, skyrimland  # noqa: E402
from fo4sf import terrain_grid as tg  # noqa: E402

U = 70.0
SKY_CELL = 4096.0


def window(path, x, y, radius):
    """(heights m [rows, cols], x of column 0, y of row 0) of the BTD samples within radius of (x, y)."""
    with open(path, "rb") as fh:
        t = btd.read(fh.read())
    o = tg.grid_origin(t.ncx)
    s = tg.SF_STEP_M
    c0, c1 = int(math.floor((x - radius - o) / s)), int(math.ceil((x + radius - o) / s))
    r0, r1 = int(math.floor((y - radius - o) / s)), int(math.ceil((y + radius - o) / s))
    rows, cols = t.heights_raw.shape
    c0, r0, c1, r1 = max(0, c0), max(0, r0), min(cols - 1, c1), min(rows - 1, r1)
    if c0 >= c1 or r0 >= r1:
        sys.exit(f"({x}, {y}) is outside the BTD")
    raw = t.heights_raw[r0:r1 + 1, c0:c1 + 1].astype(np.float64)
    return t.hmin + raw / 65535.0 * (t.hmax - t.hmin), o + c0 * s, o + r0 * s


def skyrim_heights(esm, world, xs, ys, origin, hoff):
    """Skyrim's LAND height (metres, + hoff) under each (x, y) of the Starfield frame."""
    sx = [(x + origin[0]) * U for x in xs]
    sy = [(y + origin[1]) * U for y in ys]
    cx0, cx1 = int(min(sx) // SKY_CELL) - 1, int(max(sx) // SKY_CELL) + 1
    cy0, cy1 = int(min(sy) // SKY_CELL) - 1, int(max(sy) // SKY_CELL) + 1
    want = {(i, j) for i in range(cx0, cx1 + 1) for j in range(cy0, cy1 + 1)}
    with fo4land.Plugin(esm) as p:
        w = p.read_world(world, cells=want, refs=False)
    grids = {xy: fo4land.decode_vhgt(c["vhgt"]) for xy, c in w["cells"].items() if c.get("vhgt")}
    if not grids:
        return None
    g = skyrimland.merge_with_fill(grids, cx0, cx1, cy0, cy1, min(float(v.min()) for v in grids.values()))
    out = np.full((len(ys), len(xs)), np.nan)
    for r, yu in enumerate(sy):
        for c, xu in enumerate(sx):
            h = fo4land.height_at(g, cx0 * SKY_CELL, cy0 * SKY_CELL, xu, yu)
            if h is not None:
                out[r, c] = h / U + hoff
    return out


def bumps(h):
    """h minus the mean of its 3 x 3 neighbourhood (edges: what is there)."""
    p = np.pad(h, 1, mode="edge")
    m = sum(p[1 + dr:1 + dr + h.shape[0], 1 + dc:1 + dc + h.shape[1]] for dr in (-1, 0, 1) for dc in (-1, 0, 1)) / 9.0
    return h - m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--terrain", required=True, help="the staged exterior (overlays_params.json, Data\\Terrain\\*.btd)")
    ap.add_argument("--skyrim", default="", help="Skyrim.esm (for the comparison with Skyrim's ground)")
    ap.add_argument("--pos", type=float, nargs=2, required=True, metavar=("X", "Y"))
    ap.add_argument("--spawn-at", type=float, nargs=2, metavar=("X", "Y"), help="as ground_at.py")
    ap.add_argument("--radius", type=float, default=40.0, help="metres (default 40)")
    ap.add_argument("--world-edid", default="Tamriel")
    ap.add_argument("--out", required=True, help="the HTML file to write (outside the repo)")
    a = ap.parse_args(argv)
    with open(os.path.join(a.terrain, "overlays_params.json"), encoding="utf-8") as fh:
        prm = json.load(fh)
    ov = prm["overlays"][0]
    x, y = a.pos
    if a.spawn_at:
        sx, sy = ov["spawn"][:2]
        x, y = x - a.spawn_at[0] + sx, y - a.spawn_at[1] + sy
    origin = [float(v) for v in ov.get("origin_cw_m", [0, 0])]
    hoff = float(ov.get("height_offset_m") or 0.0)
    h, x0, y0 = window(os.path.join(a.terrain, "Data", "Terrain", f"{ov['world']}.btd"), x, y, a.radius)
    s = tg.SF_STEP_M
    xs = [x0 + c * s for c in range(h.shape[1])]
    ys = [y0 + r * s for r in range(h.shape[0])]
    sky = skyrim_heights(a.skyrim, a.world_edid, xs, ys, origin, hoff) if a.skyrim else None
    diff = h - sky if sky is not None else None
    bump = bumps(h)
    objs = []
    try:
        with open(os.path.join(a.terrain, "objects.json"), encoding="utf-8") as fh:
            ob = json.load(fh)
        bases = ob["bases"]
        for r in ob["refs"]:
            px, py, pz = r["pos"]
            if abs(px - x) <= a.radius and abs(py - y) <= a.radius:
                b = bases[r["base"]] if isinstance(r.get("base"), int) else {}
                objs.append({"x": round(px, 2), "y": round(py, 2), "z": round(pz, 2), "name": b.get("edid", "?"),
                             "src": r["src"], "model": b.get("source", ""), "scale": r.get("scale", 1)})
    except FileNotFoundError:
        pass
    cx, cy = int(round((x - x0) / s)), int(round((y - y0) / s))
    here = float(h[min(max(cy, 0), h.shape[0] - 1), min(max(cx, 0), h.shape[1] - 1)])
    print(f"window {h.shape[1]} x {h.shape[0]} samples ({s} m) round ({x:.2f}, {y:.2f}); game terrain there {here:.2f} m")
    if diff is not None:
        ad = np.abs(diff)
        r, c = np.unravel_index(np.nanargmax(ad), ad.shape)
        print(f"game minus Skyrim (+{hoff} m): median {np.nanmedian(diff):+.3f} m, largest {diff[r, c]:+.3f} m at "
              f"({xs[c]:.2f}, {ys[r]:.2f}); samples off by more than 0.25 m: {int(np.nansum(ad > 0.25))}")
    r, c = np.unravel_index(np.argmax(np.abs(bump)), bump.shape)
    print(f"largest bump {bump[r, c]:+.3f} m at ({xs[c]:.2f}, {ys[r]:.2f}); samples over 0.15 m: "
          f"{int(np.sum(np.abs(bump) > 0.15))}; {len(objs)} objects in the window")
    summary = (f"Game vs Skyrim: largest difference {np.nanmax(np.abs(diff)):.3f} m. " if diff is not None else "") + \
        f"Largest bump {np.abs(bump).max():.3f} m."
    rnd = lambda m: None if m is None else [[None if not np.isfinite(v) else round(float(v), 3) for v in row]  # noqa
                                            for row in m]
    data = {"x0": x0, "y0": y0, "step": s, "rows": h.shape[0], "cols": h.shape[1], "player": [x, y, here],
            "game": rnd(h), "skyrim": rnd(sky), "diff": rnd(diff), "bump": rnd(bump), "objects": objs,
            "offset": hoff, "summary": summary}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(PAGE.replace("__DATA__", json.dumps(data)))
    print(f"-> {a.out}")
    return 0


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Terrain view</title>
<style>body{background:#15171a;color:#ddd;font:14px system-ui;margin:12px}button{margin:0 4px 6px 0;background:#2a2e35;
color:#ddd;border:1px solid #444;padding:4px 10px;border-radius:4px;cursor:pointer}button.on{background:#4e79a7}
#wrap{display:flex;gap:12px;flex-wrap:wrap}canvas{border:1px solid #333}#info{font-family:monospace;white-space:pre;
min-height:5em}#three{width:640px;height:640px;border:1px solid #333}</style></head><body>
<div><button data-m="game" class="on">game terrain (relief)</button><button data-m="diff">game minus Skyrim</button>
<button data-m="bump">bumps</button><button data-m="skyrim">Skyrim (relief)</button>
<label><input type="checkbox" id="showobj" checked> objects</label></div>
<div id="wrap"><div><canvas id="c" width="640" height="640"></canvas><div id="info"></div><div id="legend"></div></div>
<div id="three"></div></div>
<script>const D=__DATA__;</script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const cv=document.getElementById('c'),ctx=cv.getContext('2d');let mode='game';
const R=D.rows,C=D.cols,S=640/Math.max(R,C);
function relief(h){const out=[];for(let r=0;r<R;r++){out.push([]);for(let c=0;c<C;c++){const a=h[r][c];
 if(a===null){out[r].push(null);continue}const e=h[r][Math.min(C-1,c+1)]??a,n=h[Math.min(R-1,r+1)][c]??a;
 const dx=(e-a)/D.step,dy=(n-a)/D.step;const l=Math.max(0,Math.min(1,0.6+(-dx*0.7+dy*0.7)*0.8));out[r].push(l)}}return out}
function colour(v,m){if(v===null)return[60,0,60];if(m==='game'||m==='skyrim'){const g=Math.round(40+v*200);return[g,g,g]}
 const lim=m==='diff'?1.0:0.3,t=Math.max(-1,Math.min(1,v/lim)),g=110;   // grey = no difference / flat
 return t<0?[Math.round(g*(1+t)),Math.round(g*(1+t)),Math.round(g+(255-g)*-t)]:[Math.round(g+(255-g)*t),Math.round(g*(1-t)),Math.round(g*(1-t))]}
function draw(){const src=mode==='game'?relief(D.game):mode==='skyrim'?(D.skyrim?relief(D.skyrim):null):D[mode];
 ctx.fillStyle='#000';ctx.fillRect(0,0,640,640);if(!src){ctx.fillStyle='#ddd';ctx.fillText('no Skyrim data (run with --skyrim)',20,20);return}
 for(let r=0;r<R;r++)for(let c=0;c<C;c++){const [a,b,d]=colour(src[r][c],mode);ctx.fillStyle=`rgb(${a},${b},${d})`;
 ctx.fillRect(c*S,(R-1-r)*S,Math.ceil(S),Math.ceil(S))}
 if(document.getElementById('showobj').checked){for(const o of D.objects){const [px,py]=toPx(o.x,o.y);
 if(o.name.toLowerCase().includes('water')){const w=16*(o.scale||1)/D.step*S;ctx.strokeStyle='#3d8bff';ctx.lineWidth=1;ctx.strokeRect(px-w/2,py-w/2,w,w)}
 else{ctx.fillStyle='#ffd400';ctx.fillRect(px-2,py-2,4,4)}}}
 const [qx,qy]=toPx(D.player[0],D.player[1]);ctx.strokeStyle='#00e0ff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(qx,qy,7,0,7);ctx.stroke();
 document.getElementById('legend').textContent=(mode==='diff'?'grey: same as Skyrim; blue: game lower, red: higher (full colour at 1 m). ':
 mode==='bump'?'grey: smooth; red: sample above its neighbours, blue: below (full colour at 0.3 m). ':'')+
 'Cyan ring: your position; yellow dots: objects; blue squares: water pieces. '+D.summary}
function toPx(x,y){return[(x-D.x0)/D.step*S,(R-1-(y-D.y0)/D.step)*S]}
cv.onmousemove=e=>{const b=cv.getBoundingClientRect(),c=Math.floor((e.clientX-b.left)/S),r=R-1-Math.floor((e.clientY-b.top)/S);
 if(r<0||r>=R||c<0||c>=C)return;const x=D.x0+c*D.step,y=D.y0+r*D.step;let best=null,bd=1e9;
 for(const o of D.objects){const d=Math.hypot(o.x-x,o.y-y);if(d<bd){bd=d;best=o}}
 const f=v=>v===null||v===undefined?'-':v.toFixed(3);
 document.getElementById('info').textContent=`x ${x.toFixed(2)}  y ${y.toFixed(2)}\ngame ${f(D.game[r][c])} m   Skyrim ${D.skyrim?f(D.skyrim[r][c]):'-'} m   diff ${D.diff?f(D.diff[r][c]):'-'}   bump ${f(D.bump[r][c])}\n`+
 (best?`nearest object ${bd.toFixed(1)} m: ${best.name} (${best.src}) z ${best.z}\n  ${best.model}`:'')};
for(const b of document.querySelectorAll('button'))b.onclick=()=>{mode=b.dataset.m;for(const x of document.querySelectorAll('button'))x.classList.toggle('on',x===b);draw();paint3d()};
document.getElementById('showobj').onchange=draw;draw();
// 3-D
let mesh=null;function paint3d(){if(!mesh)return;const src=mode==='game'||mode==='skyrim'?null:D[mode];const col=mesh.geometry.attributes.color;
 let i=0;for(let r=0;r<R;r++)for(let c=0;c<C;c++){let rgb=[150,150,140];if(src){rgb=colour(src[r][c],mode)}col.setXYZ(i++,rgb[0]/255,rgb[1]/255,rgb[2]/255)}col.needsUpdate=true}
if(window.THREE){const el=document.getElementById('three'),sc=new THREE.Scene();sc.background=new THREE.Color(0x15171a);
 const cam=new THREE.PerspectiveCamera(50,1,0.1,5000),rn=new THREE.WebGLRenderer({antialias:true});rn.setSize(640,640);el.appendChild(rn.domElement);
 const pos=[],idx=[];const zc=D.player[2];for(let r=0;r<R;r++)for(let c=0;c<C;c++){const h=D.game[r][c]??zc;pos.push(c*D.step,h-zc,-r*D.step)}
 for(let r=0;r<R-1;r++)for(let c=0;c<C-1;c++){const a=r*C+c;idx.push(a,a+1,a+C,a+1,a+C+1,a+C)}
 const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3));g.setIndex(idx);
 g.setAttribute('color',new THREE.Float32BufferAttribute(new Array(R*C*3).fill(0.6),3));g.computeVertexNormals();
 mesh=new THREE.Mesh(g,new THREE.MeshLambertMaterial({vertexColors:true,side:THREE.DoubleSide}));sc.add(mesh);
 const wire=new THREE.LineSegments(new THREE.WireframeGeometry(g),new THREE.LineBasicMaterial({color:0x000000,transparent:true,opacity:0.12}));sc.add(wire);
 sc.add(new THREE.AmbientLight(0xffffff,0.45));const sun=new THREE.DirectionalLight(0xffffff,0.8);sun.position.set(-50,80,40);sc.add(sun);
 const P=(x,y,z)=>new THREE.Vector3(x-D.x0,z-zc,-(y-D.y0));
 for(const o of D.objects){const isW=o.name.toLowerCase().includes('water');const m=isW?new THREE.Mesh(new THREE.PlaneGeometry(16*o.scale,16*o.scale),
  new THREE.MeshBasicMaterial({color:0x2266ff,transparent:true,opacity:0.35,side:THREE.DoubleSide})):new THREE.Mesh(new THREE.BoxGeometry(0.6,0.6,0.6),new THREE.MeshBasicMaterial({color:0xffd400}));
  m.position.copy(P(o.x,o.y,o.z));if(isW)m.rotation.x=-Math.PI/2;sc.add(m)}
 const pl=new THREE.Mesh(new THREE.CylinderGeometry(0.3,0.3,1.8,12),new THREE.MeshBasicMaterial({color:0x00e0ff}));pl.position.copy(P(D.player[0],D.player[1],D.player[2]+0.9));sc.add(pl);
 const ctl=new THREE.OrbitControls(cam,rn.domElement);ctl.target.copy(P(D.player[0],D.player[1],D.player[2]));cam.position.copy(ctl.target.clone().add(new THREE.Vector3(25,25,25)));ctl.update();
 paint3d();(function loop(){requestAnimationFrame(loop);rn.render(sc,cam)})()}
else document.getElementById('three').textContent='3-D view needs internet (three.js from jsdelivr)';
</script></body></html>"""


if __name__ == "__main__":
    sys.exit(main())
