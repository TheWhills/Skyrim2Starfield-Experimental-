"""First pass of the races plan (docs/npc/races.md, owner 2026-11-09: "continue with this plan"): what Starfield's
head morphs are made of, how much of Starfield names HumanRace directly, and the Skyrim race morphs moved onto
Starfield's head (offline; no game). Read-only.

    python -I scripts\\npc\\race_probe.py --skyrim-data "$sky" --starfield $sf --out C:\\Modding\\work\\races

1. Starfield head morphs (meshes\\morphs\\human\\<sex>\\chargen\\head\\morph.dat, sfmorph): its keys, which are
   phenotype x region ('male_eu_md2_Nose') and which are other (body weight, expressions?); per region the head
   vertices its keys move (the region masks a new phenotype is split by); the same keys on the head parts that follow
   the head (eyebrows, eyelashes, teeth, eyes, a hairstyle); the facial bone regions file's regions and dials.
2. HumanRace by name in Starfield.esm: conditions with HumanRace as a parameter (by condition function, e.g. 69
   GetIsRace) and every other field holding its FormID, by record type and field: what a separate race per Skyrim race
   would have to match (armor race / subgraph race / keywords cover the rest).
3. Each Skyrim race morph (MaleHeadRaces.tri / FemaleHeadRaces.tri) moved onto Starfield's head (face_fit's alignment;
   --transfer surface, the default: fo4sf.headcorr's point on the Skyrim surface per Starfield vertex, seams welded,
   smoothed; --transfer nearest: the old 4-nearest-vertex average, to compare): per race and region how far it moves Starfield's head, and how
   much falls outside every region. Writes race_morphs_<sex>.npz (per race, (V, 3) metres) for the next step, and
   race_view.html: both heads with the race morphs to switch through (three.js).
Writes <out>\\race_probe.json.
"""
import argparse
import base64
import json
import os
import re
import struct
import sys
import time
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "scripts", "armor"))

from fo4sf import bsa, facefit, fo4land, headcorr, packages, sfmorph, skyrimtri  # noqa: E402

SEXES = {False: "male", True: "female"}
SF_MORPH = "meshes/morphs/human/{sex}/chargen/{part}/morph.dat"
PARTS = ["head", "eyebrow_01", "eyelashes_01_top", "eyelashes_01_bottom", "teeth", "eyes_tears", "cropped_m",
         "choppy_bob_f"]
SKY_RACE_TRI = {False: r"meshes\actors\character\character assets\maleheadraces.tri",
                True: r"meshes\actors\character\character assets\femaleheadraces.tri"}
SKY_HEAD_TRI = {False: r"meshes\actors\character\character assets\malehead.tri",
                True: r"meshes\actors\character\character assets\femalehead.tri"}
PHENO_KEY = re.compile(r"^(male|female)_([a-z]{2})_([a-z]{2}\d)_(\w+)$", re.I)
MOVE_MIN = 1e-5            # m: a vertex a key moves less than this is not that key's
GET_IS_RACE = 69           # condition function index (FO4 / Skyrim numbering; Starfield's checked by the report)


# ----------------------------------------------------------------------------------------------- 1. head morphs
def morph_regions(m):
    """{region: vertex indices any phenotype key of that region moves}, {phenotype: [regions]}, [other keys]."""
    regions, phenos, other = defaultdict(set), defaultdict(list), []
    for k in m.keys:
        g = PHENO_KEY.match(k)
        moved = {v for v, d in m.deltas[k].items() if max(abs(d[0]), abs(d[1]), abs(d[2])) > MOVE_MIN}
        if g:
            regions[g.group(4)] |= moved
            phenos[f"{g.group(1)}_{g.group(2)}_{g.group(3)}"].append(g.group(4))
        else:
            other.append(k)
    return regions, phenos, other


def region_overlap(regions):
    names = sorted(regions)
    return {f"{a}&{b}": len(regions[a] & regions[b]) for i, a in enumerate(names) for b in names[i + 1:]
            if regions[a] & regions[b]}


def head_morphs(sf_data, female, vanilla_file):
    sex = SEXES[female]
    out = {}
    for part in PARTS:
        try:
            data, _rel = vanilla_file(SF_MORPH.format(sex=sex, part=part), sf_data)
        except SystemExit as e:
            out[part] = {"error": str(e)}
            continue
        m = sfmorph.parse(data)
        regions, phenos, other = morph_regions(m)
        # a morph.dat holds at most 128 keys (sfmorph: a 128-bit key mask per vertex): the room left for new
        # phenotype x region keys decides whether Skyrim races fit in the vanilla head's file or need a head of their own
        out[part] = {"vertices": m.num_vertices, "keys": len(m.keys), "free_keys": 128 - len(m.keys), "phenotypes": {p: sorted(r) for p, r in
                                                                                    phenos.items()},
                     "region_vertices": {r: len(v) for r, v in sorted(regions.items())}, "other_keys": other}
        if part == "head":
            out[part]["region_overlap"] = region_overlap(regions)
            out["_head_morph"] = m
            out["_regions"] = {r: np.array(sorted(v), int) for r, v in regions.items()}
    return out


# ------------------------------------------------------------------------------------------ 2. HumanRace by name
def human_race_refs(esm):
    """Where Starfield.esm names HumanRace: conditions (function, which parameter) and other fields."""
    ix = packages.Index(esm)
    try:
        hr = ix.find_edid(b"RACE", "HumanRace")
        if hr is None:
            return {"error": "no HumanRace"}
        pat = struct.pack("<I", hr)
        buf = ix.p.buf
        offs = sorted((off, fid, typ, flags) for fid, (typ, off, flags) in ix.records.items())
        starts = [o[0] for o in offs]
        hits = set()
        # uncompressed records: search the file; compressed (flag 0x40000): each one decompressed
        import bisect
        raw = buf if isinstance(buf, bytes) else bytes(buf)
        i = raw.find(pat)
        while i != -1:
            j = bisect.bisect_right(starts, i) - 1
            if j >= 0:
                off, fid, typ, flags = offs[j]
                size = struct.unpack_from("<I", raw, off + 4)[0]
                if off + 24 <= i < off + 24 + size and not flags & 0x40000:
                    hits.add(fid)
            i = raw.find(pat, i + 1)
        for off, fid, typ, flags in offs:
            if flags & 0x40000 and pat in fo4land.record_data(buf, off):
                hits.add(fid)
        cond, fields, recs = Counter(), Counter(), Counter()
        for fid in hits:
            typ = ix.kind(fid)
            if fid == hr:
                continue
            found = False
            for s, d in ix.subs(fid):
                if s == b"CTDA" and len(d) >= 20:
                    func = struct.unpack_from("<H", d, 8)[0]
                    p1, p2 = struct.unpack_from("<II", d, 12)
                    comp = struct.unpack_from("<I", d, 4)[0]
                    for name, v in (("param1", p1), ("param2", p2), ("value", comp)):
                        if v == hr:
                            cond[(typ, func, name)] += 1
                            found = True
                elif pat in d:
                    fields[(typ, s.decode("latin-1"))] += 1
                    found = True
            if found:
                recs[typ] += 1
        return {"human_race": f"{hr:08X}", "records": dict(recs.most_common()),
                "conditions": [{"record": t, "function": f, "where": w, "count": n}
                               for (t, f, w), n in cond.most_common()],
                "conditions_get_is_race": sum(n for (t, f, w), n in cond.items() if f == GET_IS_RACE),
                "fields": [{"record": t, "field": s, "count": n} for (t, s), n in fields.most_common(40)]}
    finally:
        ix.close()


# ----------------------------------------------------------------------------------- 3. race morphs onto Starfield
def race_transfer(sky, sf_data, female, smooth, face_fit, legacy=False, method="surface", lip_edges=True):
    head, _rep = face_fit.starfield_head(sf_data, female)
    tri_base = skyrimtri.parse(face_fit.hkx_to_af.read_any(SKY_HEAD_TRI[female], sky))
    races = skyrimtri.parse(face_fit.hkx_to_af.read_any(SKY_RACE_TRI[female], sky), deltas=True)
    nif_base = face_fit.skyrim_head(face_fit.hkx_to_af.read_any(face_fit.SKY_HEADS[female], sky))
    base = np.asarray(races["base"], float)
    rep = {"skyrim_vertices": int(len(base)), "starfield_vertices": int(len(head.vertices)),
           "tri_vs_nif_max_units": float(np.abs(base - nif_base).max()) if nif_base is not None and
           len(nif_base) == len(base) else None,
           "races_tri_vs_head_tri_max_units": float(np.abs(base - tri_base["base"]).max())}
    nif_bytes = face_fit.hkx_to_af.read_any(face_fit.SKY_HEADS[female], sky)
    _b, al, model_space = face_fit.head_alignment(head, nif_bytes, legacy=legacy)
    deltas = {m["name"]: m["deltas"] for m in races["morphs"]}
    if model_space:                     # the .tri is in the head NIF's skin space, as its vertices: to model space
        M = face_fit.skyrim_head_matrix(nif_bytes)
        base = facefit.apply4(M, base)
        deltas = {k: v @ M[:3, :3].T for k, v in deltas.items()}
        for m in races["morphs"]:
            m["deltas"] = deltas[m["name"]]
    rep["alignment"] = {"scale": al[0], "rms_m": al[3], "model_space": model_space}
    out = {}
    corr = None
    if method == "surface":
        s, R, t = al[:3]
        node = getattr(head, "model_xf", None)
        corr = headcorr.correspond(s * base @ R.T + t, races["faces"], head.vertices, head.triangles,
                                   to_model=np.asarray(node, float) if model_space and node is not None else None)
        rep["correspondence"] = corr.report
    rep["transfer"] = method
    for m in races["morphs"]:
        if corr is not None:
            field = m["deltas"] @ al[1].T * al[0]
            disp = corr.transfer(field, smooth)
            if lip_edges:
                # 2026-11-10: the lips' meeting rows moved like Skyrim's mouth edges (the female Orc gaped)
                disp, lrep = corr.fit_lip_edges(disp, field)
                rep.setdefault("lip_edges", {})[m["name"]] = lrep
        else:
            disp = facefit.transfer(base, base + m["deltas"], al, head.vertices)
            if smooth:
                disp = facefit.smooth_field(disp, head.triangles, iterations=smooth)
        out[m["name"]] = disp
        rep.setdefault("races", {})[m["name"]] = {
            "skyrim_max_m": round(float(np.linalg.norm(m["deltas"], axis=1).max()) * al[0], 4),
            "starfield_max_m": round(float(np.linalg.norm(disp, axis=1).max()), 4)}
    return head, base, races, al, out, rep


def per_region(disp, regions, nverts):
    """Per region: max / mean of the moves on its vertices; 'outside': on vertices in no region."""
    mag = np.linalg.norm(disp, axis=1)
    inside = np.zeros(nverts, bool)
    out = {}
    for r, idx in regions.items():
        idx = idx[idx < nverts]
        inside[idx] = True
        out[r] = {"max_m": round(float(mag[idx].max()), 4) if len(idx) else 0.0,
                  "mean_m": round(float(mag[idx].mean()), 5) if len(idx) else 0.0}
    rest = mag[~inside]
    out["outside"] = {"max_m": round(float(rest.max()), 4) if len(rest) else 0.0,
                      "share_of_total": round(float(rest.sum() / max(mag.sum(), 1e-12)), 3)}
    return out


def b64(a, dt):
    return base64.b64encode(np.ascontiguousarray(a, dt).tobytes()).decode()


def viewer(path, sexes):
    """race_view.html: per sex the Starfield head (with each race morph) and the Skyrim head (same morph)."""
    payload = {}
    for sex, (head, base, races, al, disp) in sexes.items():
        s, R, t = al[:3]
        node = getattr(head, "model_xf", None)
        node = np.eye(4) if node is None else np.asarray(node, float)
        rot = node[:3, :3]
        show = lambda p: facefit.apply4(node, p)        # noqa: E731  shown in model space (+Z up, +Y forward)
        sky_v = show(s * base @ R.T + t)
        payload[sex] = {"sf_v": b64(show(head.vertices), "<f4"), "sf_f": b64(head.triangles, "<u4"),
                        "sky_v": b64(sky_v, "<f4"), "sky_f": b64(races["faces"], "<u4"),
                        "names": list(disp), "sf_d": {k: b64(v @ rot.T, "<f4") for k, v in disp.items()},
                        "sky_d": {m["name"]: b64(m["deltas"] * s @ R.T @ rot.T, "<f4") for m in races["morphs"]}}
    html = """<!doctype html><html><head><meta charset="utf-8"><title>Race morphs</title>
<style>body{margin:0;font:14px sans-serif;background:#222;color:#ddd}#ui{position:absolute;top:8px;left:8px;
background:#000a;padding:8px;border-radius:6px}select,label{margin-right:8px}</style></head><body>
<div id="ui"><select id="sex"></select><select id="race"></select><label><input type="range" id="amt" min="0" max="2"
step="0.05" value="1"> amount</label><span id="info"></span><br>left: Starfield head, right: Skyrim head (aligned)</div>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const P=__DATA__;
function f32(s){const b=atob(s),a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return new Float32Array(a.buffer)}
function u32(s){const b=atob(s),a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return new Uint32Array(a.buffer)}
const r=new THREE.WebGLRenderer({antialias:true});r.setSize(innerWidth,innerHeight);document.body.appendChild(r.domElement);
const sc=new THREE.Scene();sc.background=new THREE.Color(0x222222);
const cam=new THREE.PerspectiveCamera(30,innerWidth/innerHeight,0.01,10);cam.up.set(0,0,1);
const ctl=new THREE.OrbitControls(cam,r.domElement);
sc.add(new THREE.HemisphereLight(0xffffff,0x444444,1.0));const dl=new THREE.DirectionalLight(0xffffff,0.6);dl.position.set(1,-2,2);sc.add(dl);
let meshes=[];
function mk(v,f,off,col){const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(v.slice(),3));
g.setIndex(new THREE.BufferAttribute(f,1));g.computeVertexNormals();const m=new THREE.Mesh(g,new THREE.MeshStandardMaterial({color:col,roughness:0.7}));
m.position.x=off;m.userData.base=v;sc.add(m);return m}
function build(){meshes.forEach(m=>sc.remove(m));const d=P[sex.value];
const sv=f32(d.sf_v),kv=f32(d.sky_v);let c=[0,0,0];for(let i=0;i<sv.length;i+=3){c[0]+=sv[i];c[1]+=sv[i+1];c[2]+=sv[i+2]}
c=c.map(x=>x/(sv.length/3));meshes=[mk(sv,u32(d.sf_f),-0.13,0xd8b8a0),mk(kv,u32(d.sky_f),0.13,0xa0b8d8)];
meshes.forEach(m=>{m.position.y=-c[1];m.position.z=-c[2]});
race.innerHTML=d.names.map(n=>'<option>'+n+'</option>').join('');cam.position.set(0,0.9,0.05);ctl.target.set(0,0,0);apply()}
function apply(){const d=P[sex.value],a=+amt.value,n=race.value;[[meshes[0],d.sf_d[n]],[meshes[1],d.sky_d[n]]].forEach(([m,s])=>{
const b=m.userData.base,dd=f32(s),p=m.geometry.attributes.position.array;for(let i=0;i<p.length;i++)p[i]=b[i]+a*dd[i];
m.geometry.attributes.position.needsUpdate=true;m.geometry.computeVertexNormals()});info.textContent=n}
sex.innerHTML=Object.keys(P).map(n=>'<option>'+n+'</option>').join('');sex.onchange=build;race.onchange=apply;amt.oninput=apply;
build();(function loop(){requestAnimationFrame(loop);ctl.update();r.render(sc,cam)})();
onresize=()=>{cam.aspect=innerWidth/innerHeight;cam.updateProjectionMatrix();r.setSize(innerWidth,innerHeight)};
</script></body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html.replace("__DATA__", json.dumps(payload)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True, help="Starfield install folder")
    ap.add_argument("--out", required=True)
    ap.add_argument("--smooth", type=int, default=4, help="smoothing passes over Starfield's head (0 = none)")
    ap.add_argument("--legacy-alignment", action="store_true", help="the old alignment (to compare)")
    ap.add_argument("--transfer", choices=["surface", "nearest"], default="surface",
                    help="surface: a point on the Skyrim surface per Starfield vertex (fo4sf.headcorr); nearest: the "
                         "old 4-nearest-vertex average (to compare)")
    ap.add_argument("--skip", action="append", default=[], choices=["morphs", "refs", "transfer"])
    ap.add_argument("--no-lip-edges", dest="lip_edges", action="store_false",
                    help="leave the lips as transferred (to compare): without it the lips' meeting rows move like "
                         "Skyrim's mouth edges")
    a = ap.parse_args(argv)
    import face_fit                                     # heavy imports only when run
    t0 = time.time()
    sf_data = os.path.join(a.starfield, "Data")
    report = {}
    os.makedirs(a.out, exist_ok=True)
    regions = {}
    if "morphs" not in a.skip:
        for female in (False, True):
            hm = head_morphs(sf_data, female, face_fit.hkx_to_af.vanilla_file)
            regions[female] = hm.pop("_regions", {})
            hm.pop("_head_morph", None)
            rg = facefit.load_regions(face_fit.hkx_to_af.vanilla_file(face_fit.SF_REGIONS[female], sf_data)[0]
                                      .decode("utf-8", "replace"))
            by = Counter(s.region for s in rg)
            hm["facial_bone_regions"] = {"dials": len(rg), "by_region": dict(by),
                                         "phenotype_regions": sorted({s.region for s in rg if not s.sculpt}),
                                         "sculpt_regions": sorted({s.region for s in rg if s.sculpt})}
            report.setdefault("head_morphs", {})[SEXES[female]] = hm
            h = hm.get("head", {})
            print(f"{SEXES[female]} head morph.dat: {h.get('vertices')} vertices, {h.get('keys')} keys "
                  f"({h.get('free_keys')} of 128 free), "
                  f"{len(h.get('phenotypes', {}))} phenotypes; regions {h.get('region_vertices')}; other keys "
                  f"{(h.get('other_keys') or [])[:12]}")
            for p in PARTS[1:]:
                x = hm.get(p, {})
                print(f"   {p}: {x.get('error') or str(x.get('keys')) + ' keys, phenotypes ' + str(len(x.get('phenotypes', {})))}")
            print(f"   facial bone regions: {hm['facial_bone_regions']['dials']} dials; phenotype regions "
                  f"{hm['facial_bone_regions']['phenotype_regions']}")
    if "refs" not in a.skip:
        refs = human_race_refs(os.path.join(sf_data, "Starfield.esm"))
        report["human_race_refs"] = refs
        print(f"HumanRace {refs.get('human_race')} named in {sum((refs.get('records') or {}).values())} records "
              f"{refs.get('records')}; GetIsRace(69) HumanRace conditions {refs.get('conditions_get_is_race')}")
        for c in (refs.get("conditions") or [])[:10]:
            print(f"   condition {c['record']} function {c['function']} {c['where']}: {c['count']}")
        for f in (refs.get("fields") or [])[:15]:
            print(f"   field {f['record']}.{f['field']}: {f['count']}")
    if "transfer" not in a.skip:
        sky = bsa.SkyrimArchives(a.skyrim_data)
        views = {}
        for female in (False, True):
            head, base, races, al, disp, rep = race_transfer(sky, sf_data, female, a.smooth, face_fit,
                                                             legacy=a.legacy_alignment, method=a.transfer,
                                                             lip_edges=a.lip_edges)
            if regions.get(female):
                for name, d in disp.items():
                    rep["races"][name]["regions"] = per_region(d, regions[female], len(head.vertices))
            report.setdefault("transfer", {})[SEXES[female]] = rep
            np.savez_compressed(os.path.join(a.out, f"race_morphs_{SEXES[female]}.npz"),
                                **{k: v.astype(np.float32) for k, v in disp.items()})
            views[SEXES[female]] = (head, base, races, al, disp)
            print(f"{SEXES[female]}: Skyrim {rep['skyrim_vertices']} -> Starfield {rep['starfield_vertices']} "
                  f"vertices, alignment rms {rep['alignment']['rms_m']:.4f} m "
                  f"({'model space' if rep['alignment']['model_space'] else 'legacy'}); transfer {rep['transfer']} "
                  f"{rep.get('correspondence', '')}")
            for name, x in rep["races"].items():
                reg = x.get("regions", {})
                top = sorted(((k, v["max_m"]) for k, v in reg.items() if k != "outside"), key=lambda kv: -kv[1])[:3]
                print(f"   {name:13} Skyrim max {x['skyrim_max_m']:.3f} m, on Starfield {x['starfield_max_m']:.3f} m; "
                      f"most in {top}; outside regions {reg.get('outside')}")
                le = rep.get("lip_edges", {}).get(name)
                if le:
                    print(f"   {'':13} lips: {le}")
        viewer(os.path.join(a.out, "race_view.html"), views)
    with open(os.path.join(a.out, "race_probe.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, default=str)
    print(f"-> {os.path.join(a.out, 'race_probe.json')}, race_view.html ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
