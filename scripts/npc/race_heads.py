"""Skyrim race shapes as Starfield head morph keys, and a test plugin to see them in game (races plan step 3,
docs/npc/races.md).

    python -I scripts\\npc\\race_heads.py --skyrim-data "$sky" --starfield $sf --out C:\\Modding\\work\\races\\heads

What it writes (under --out):
  meshes\\morphs\\s2s\\races\\<sex>\\chargen\\<folder>\\morph.dat: Starfield's head morph.dat (every vanilla key, so the
    head still does everything vanilla does) plus, per Skyrim race, one key per Starfield region:
    <sex>_sk_<code>_<Region> (e.g. male_sk_he1_Nose). A race's shape (race_probe's transfer onto Starfield's head) is
    split over the 9 regions by soft weights: per vertex, how far each region's vanilla phenotype keys move it,
    normalised (vertices no vanilla key moves take their neighbours' weights), so the 9 keys at 1.0 add up to the whole
    race shape. A morph.dat holds at most 128 keys: vanilla's 84 leave room for 4 races (36 keys) per file.
  S2SRaceTest.esm (master Starfield.esm):
    MRPH per sex: a copy of the vanilla head's morph record (HDPT MNAM) with TCMP (the folder holding morph.dat,
      verified for armor 2026-11-06) pointed at ours;
    HDPT per sex: a copy of the vanilla head part (Human_Male_Head / Human_Female_Head) using that MRPH;
    NPC_ per race and sex: a plain vanilla NPC copy (no face dials, empty outfit) with our head part in its head
      parts (PNAM) and the race's 9 keys as morph blends (BMPN name / BMPV 1.0): the way vanilla NPCs name the head
      morph keys they use (verified on vanilla NPCs 2026-11-09: BMPN carries phenotype keys like male_eu_ol1_Mouth
      with their intensities; FMRI / FMRG is the chargen's per-phenotype record and does not always match it);
    a control NPC per sex: our head part, no blends (must look like a plain vanilla face);
    --race-head: also an override of HumanRace with our head part as its Face part per sex and our keys added to its
      morph groups (MPGM), in case the game takes head morphs from the race's head part and groups rather than the
      NPC's. Our morph.dat holds every vanilla key, so vanilla NPCs keep their faces with it.
  --new-races (2026-11-10, default --race-shape baked): the race's shape baked into a head NIF + meshes of its own
    (meshes\\s2s\\races\\<race>\\<sex>head.nif, src/fo4sf/headbake.py) and a head part per sex using it, so every
    face of the race starts from that shape and HumanRace's chargen (blends, sliders) works on top; the race's chargen
    lists stay HumanRace's. --race-shape blend: the earlier way (the shape as an extra chargen phenotype).
    Face parts (2026-11-10): every eye, eyelash, eyebrow, beard, teeth and jewelry head part HumanRace offers gets a race
    copy per sex baked the same way (headbake.baked_part_files: each part point moves like its nearest head vertex,
    the part's frame found through the skin binds), on a list of the race's own (S2S_HeadParts<race>Race); the vanilla
    ones move to a humans-only list (S2S_HeadPartsHumanOnly); hair and the rest stay shared. --no-bake-parts: off.
  race_heads.json: per race the console command, the weights, a frame check.
Unverified in game: whether an NPC's own Face head part replaces the race's (Skyrim does), and whether BMPN alone
applies a key (A/B: --race-head).
"""
import argparse
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

from fo4sf import facefit, headcorr, sfmorph, sfplugin  # noqa: E402

PLUGIN = "S2SRaceTest.esm"
SEXES = {False: "male", True: "female"}
HEAD_PART = {False: "Human_Male_Head", True: "Human_Female_Head"}
CODES = {"NordRace": "no1", "ImperialRace": "im1", "BretonRace": "br1", "RedguardRace": "rg1", "HighElfRace": "he1",
         "WoodElfRace": "we1", "DarkElfRace": "de1", "OrcRace": "or1", "ElderRace": "el1", "DremoraRace": "dr1"}
NAMES = {"NordRace": "Nord", "ImperialRace": "Imperial", "BretonRace": "Breton", "RedguardRace": "Redguard",
         "HighElfRace": "Altmer", "WoodElfRace": "Bosmer", "DarkElfRace": "Dunmer", "OrcRace": "Orc",
         "ElderRace": "Elder", "DremoraRace": "Dremora"}
DEFAULT_RACES = ("HighElfRace", "OrcRace", "WoodElfRace", "DarkElfRace")
PHENO_KEY = re.compile(r"^(male|female)_([a-z]{2})_([a-z]{2}\d)_(\w+)$", re.I)
MIN_MOVE = 1e-5                 # m: smaller key moves are left out of the file
MAX_KEYS = 128


# --------------------------------------------------------------------------------------------- region weights
def region_weights(morph, triangles, nverts):
    """(regions, W (V, R)): per vertex, how much each region's phenotype keys move it (the largest move over the
    phenotypes), normalised to sum 1. Vertices no phenotype key moves take the mean of their mesh neighbours' weights
    (repeated until every reachable vertex has some; seam-split vertices are welded)."""
    regions = sorted({PHENO_KEY.match(k).group(4) for k in morph.keys if PHENO_KEY.match(k)})
    col = {r: i for i, r in enumerate(regions)}
    M = np.zeros((nverts, len(regions)))
    for k in morph.keys:
        g = PHENO_KEY.match(k)
        if not g:
            continue
        for v, d in morph.deltas[k].items():
            if v < nverts:
                M[v, col[g.group(4)]] = max(M[v, col[g.group(4)]], float(np.linalg.norm(d)))
    M[M < MIN_MOVE] = 0.0
    return regions, fill_weights(M, triangles)


def fill_weights(M, triangles, iters=400):
    """Rows of M normalised to 1; zero rows filled from their mesh neighbours (seams: weld_weights afterwards)."""
    t = np.asarray(triangles, int)
    nverts = len(M)
    known = M.sum(1) > 0
    W = np.where(known[:, None], M / np.maximum(M.sum(1, keepdims=True), 1e-30), 0.0)
    if known.all() or not len(t):
        return W
    a = np.concatenate([t[:, 0], t[:, 1], t[:, 2], t[:, 1], t[:, 2], t[:, 0]])
    b = np.concatenate([t[:, 1], t[:, 2], t[:, 0], t[:, 0], t[:, 1], t[:, 2]])
    have = known.copy()
    for _ in range(iters):
        acc = np.zeros_like(W)
        cnt = np.zeros(nverts)
        np.add.at(acc, a, W[b] * have[b, None])
        np.add.at(cnt, a, have[b].astype(float))
        new = (~have) & (cnt > 0)
        if not new.any():
            break
        W[new] = acc[new] / cnt[new, None]
        have |= new
    W[~have] = 1.0 / W.shape[1]                       # unreachable: an even share
    return W / W.sum(1, keepdims=True)


def weld_weights(W, vertices):
    """W averaged over vertices at the same position (Starfield's UV-seam splits), so seams move together."""
    inv, _cnt = headcorr.weld_index(vertices)
    return headcorr.welded(W, inv)[inv]


def race_keys(sex, race, disp, regions, W):
    """{key: {vertex: delta}} for one race: its displacement (V, 3) split over the regions by W."""
    out = {}
    for i, r in enumerate(regions):
        d = disp * W[:, i:i + 1]
        mag = np.abs(d).max(1)
        idx = np.nonzero(mag > MIN_MOVE)[0]
        out[f"{sex}_sk_{CODES[race]}_{r}"] = {int(v): tuple(float(x) for x in d[v]) for v in idx}
    return out


def frame_check(morph, vertices, triangles, key="Overweight"):
    """Share of the vanilla `key`'s moves pointing out of the head (along the vertex normal): about 1 when the morph's
    deltas are in the same frame as the head's vertices (as our transferred shapes are), about 0.5 if not."""
    if key not in morph.keys or not morph.deltas[key]:
        return None
    n = headcorr.vertex_normals(np.asarray(vertices, float), np.asarray(triangles, int))
    v = np.array(list(morph.deltas[key]), int)
    d = np.array([morph.deltas[key][i] for i in v], float)
    big = np.linalg.norm(d, axis=1) > 1e-4
    if not big.any():
        return None
    return round(float(np.mean(np.sum(d[big] * n[v[big]], 1) > 0)), 3)


# ------------------------------------------------------------------------------------------------- plugin
def _u32(d):
    return struct.unpack_from("<I", bytes(d), 0)[0]


def tcmp_folder(old: str, sex: str) -> str:
    """Our TCMP: vanilla's last folder (the head shape's) under Meshes\\Morphs\\S2S\\Races\\<Sex>\\Chargen."""
    last = re.split(r"[\\/]", old.strip("\\/ \0"))[-1] or "Head"
    return f"Meshes\\Morphs\\S2S\\Races\\{sex.capitalize()}\\Chargen\\{last}"


def text_of(d) -> str:
    """The longest printable run of a field (TCMP may be length-prefixed or zero-terminated)."""
    runs = re.findall(rb"[ -~]{3,}", bytes(d))
    return max(runs, key=len).decode("latin-1") if runs else ""


def race_override(race_subs, head_fid, keys_by_region, part_types, female):
    """(HumanRace's subrecords with, in one sex's chargen section, the Face head part (HEAD whose HDPT has type 1)
    replaced by head_fid and our keys added at the end of each morph group (MPGN name = region), counts). A sex
    section starts at an empty MNAM (male) / FNAM (female) marker."""
    out, sex, group, head_n, added = [], None, None, 0, 0
    subs = list(race_subs)
    for i, (s, d) in enumerate(subs):
        if s in (b"MNAM", b"FNAM") and len(d) == 0:
            sex, group = (s == b"FNAM"), None
        elif sex == female and s == b"MPGN":
            group = bytes(d).split(b"\0", 1)[0].decode("latin-1")
        elif s != b"MPGM":
            group = None
        if sex == female and s == b"HEAD" and len(d) == 4 and part_types.get(_u32(d)) == 1:
            d = struct.pack("<I", head_fid)
            head_n += 1
        out.append((s, d))
        nxt = subs[i + 1][0] if i + 1 < len(subs) else None
        if group is not None and nxt != b"MPGM":
            mine = keys_by_region.get(group, [])
            out += [(b"MPGM", sfplugin.zs(k)) for k in mine]
            added += len(mine)
            group = None
    return out, {"head_parts_replaced": head_n, "morph_group_entries_added": added}


def phenotype_blocks(subs, female):
    """[(start, end)] index ranges of one sex's chargen phenotype entries (FMRI + the subrecords it carries, up to the
    next FMRI; the last entry ends at the first signature no earlier entry carried)."""
    sex, starts = None, []
    for i, (s, d) in enumerate(subs):
        if s in (b"MNAM", b"FNAM") and len(d) == 0:
            sex = (s == b"FNAM")
        elif s == b"FMRI" and sex == female:
            starts.append(i)
    if not starts:
        return []
    blocks = [(a, b) for a, b in zip(starts, starts[1:])]
    inner = {subs[k][0] for a, b in blocks for k in range(a, b)} or {b"FMRI", b"FMRU"}
    end = starts[-1] + 1
    while end < len(subs) and subs[end][0] in inner and subs[end][0] != b"FMRI":
        end += 1
    return blocks + [(starts[-1], end)]


def add_phenotype(subs, female, pid, like="eu_md", label=None):
    """(subrecords, new FMRI index) with one more chargen phenotype for one sex: a copy of the vanilla entry whose id
    has `like` (its textures and settings), index = the largest + 1, FMRU = pid (e.g. male_sk_or1)."""
    blocks = phenotype_blocks(subs, female)
    if not blocks:
        return subs, None
    ids = []
    for a, b in blocks:
        u = next((bytes(d).split(b"\0", 1)[0].decode("latin-1") for s, d in subs[a:b] if s == b"FMRU"), "")
        ids.append(u)
    pick = next((i for i, u in enumerate(ids) if like in u.lower()), 0)
    a, b = blocks[pick]
    index = max(_u32(subs[x][1]) for x, _y in blocks) + 1
    names = {b"FMRI": struct.pack("<I", index), b"FMRU": sfplugin.zs(pid)}
    if label:
        names[b"FMRN"] = sfplugin.zs(label)      # the chargen's name for it (vanilla: a string id; ours is not localized)
    block = [(s, names.get(s, d)) for s, d in subs[a:b]]
    end = blocks[-1][1]
    return subs[:end] + block + subs[end:], index


HEIGHT_REFERENCE = "ImperialRace"      # Skyrim's plain human (1.0 / 1.0): Starfield's HumanRace heights stand for it


def race_names(text):
    """Skyrim race EditorIDs from a comma list of EditorIDs, short names (Orc, HighElf) or our names (Altmer); 'all':
    every known race."""
    if text.strip().lower() == "all":
        return list(CODES)
    by_name = {v.lower(): k for k, v in NAMES.items()}
    out = []
    for x in (y.strip() for y in text.split(",")):
        if not x:
            continue
        r = by_name.get(x.lower()) or (x if x.endswith("Race") else x + "Race")
        r = next((k for k in CODES if k.lower() == r.lower()), r)
        if r not in CODES:
            raise SystemExit(f"unknown race {x!r}; known: {', '.join(CODES)} (or {', '.join(NAMES.values())})")
        out.append(r)
    return out


def skyrim_heights(sky_esm, races, reference=HEIGHT_REFERENCE):
    """{race: (male, female)} heights from Skyrim's RACE DATA (floats at 16 and 20, as race_survey reads them; owner's
    survey: Nord 1.03, Altmer 1.08, Orc 1.045, Bosmer 0.98 / 1.0 ...), for races and the reference race."""
    from fo4sf import packages
    ix = packages.Index(sky_esm)
    try:
        out = {}
        for r in set(races) | {reference}:
            fid = ix.find_edid(b"RACE", r)
            d = next((bytes(x) for sg, x in ix.subs(fid) if sg == b"DATA"), b"") if fid is not None else b""
            if len(d) >= 24:
                out[r] = struct.unpack_from("<2f", d, 16)
        return out
    finally:
        ix.close()


def with_heights(subs, factors):
    """RACE subrecords with DAT2's male / female height (floats at 0 and 4, xEdit SF1 RACE DAT2) multiplied by
    factors (male, female). 2026-11-10: a race's height relative to Skyrim's plain human (the Orc 1.045)."""
    out = []
    for sg, d in subs:
        if sg == b"DAT2" and len(d) >= 8 and factors:
            hm, hf = struct.unpack_from("<2f", d, 0)
            d = struct.pack("<2f", hm * factors[0], hf * factors[1]) + bytes(d[8:])
        out.append((sg, d))
    return out


def new_race(human, mannequin, name, heads, keys, part_types):
    """A Skyrim race as a RACE of its own, thin over HumanRace (docs/npc/races.md, "Decision"): a copy of HumanRace
    (skeleton, behaviour, chargen, bone modifiers, keywords) named `name`, armor race (RNAM) HumanRace so every
    HumanRace gear piece fits, and HumanRace as its subgraph template race (SRAC), without subgraph entries of its own
    (see below). `mannequin` is unused (kept for the call). Per sex: our head
    part as its Face part, a phenotype of its own (a copy of the eu_md one, FMRU <sex>_sk_<code>) and that phenotype's
    keys added to the morph groups. heads: {female: HDPT FormID}; keys: {female: {region: [keys]}} for this race.
    Returns (subrecords, report)."""
    human_fid, hsubs = human
    subs = sfplugin.edit(list(hsubs), {b"EDID": sfplugin.zs(f"S2S_{name}Race"), b"FULL": sfplugin.zs(name)})
    # Where the race names its armor race and subgraphs (owner's record dump 2026-11-09, verified on the vanilla
    # records): MannequinRace / HumanCorpseRace carry RNAM (armor race = HumanRace) after the last skin-tone section
    # (BSTT / HSTT), right where HumanRace's 400 subgraph entries (subgraph.FIELDS) begin, before PTOP. A copy of those
    # entries under a race of our own did not animate (owner: its NPCs in the reference pose; first build had RNAM at
    # the top and the entries copied): the precomputed animation data is per race, so, as Fallout 4 races do, ours
    # names HumanRace as its subgraph template race (SRAC) and carries no entries of its own.
    from fo4sf import subgraph
    hr = struct.pack("<I", human_fid)
    rep = {"armor_race": "HumanRace", "subgraph_race": "HumanRace"}
    subs = [(s, d) for s, d in subs if s not in (b"RNAM", b"SRAC")]
    at = next((i for i, (s, _d) in enumerate(subs) if s in subgraph.FIELDS), None)
    if at is None:
        at = next((i for i, (s, _d) in enumerate(subs) if s == b"PTOP"), len(subs))
    before = len(subs)
    tail = [(s, d) for s, d in subs[at:] if s not in subgraph.FIELDS]
    subs = subs[:at] + [(b"RNAM", hr), (b"SRAC", hr)] + tail
    rep["subgraph_subrecords_dropped"] = before - at - len(tail)
    for female, h_fid in heads.items():
        subs, counts = race_override(subs, h_fid, keys.get(female, {}), part_types, female)
        code = next((PHENO_KEY.match(k).group(3) for ks in keys.get(female, {}).values() for k in ks), None)
        subs, index = add_phenotype(subs, female, f"{SEXES[female]}_sk_{code}", label=name) if code else (subs, None)
        rep[SEXES[female]] = dict(counts, phenotype_index=index)
    return subs, rep


def vanilla_head_tcmp(sf_esm, female):
    """The TCMP text of the vanilla head part's morph record."""
    recs = sfplugin.records(sf_esm, [b"HDPT", b"MRPH"])
    part = next((r for r in recs if r[0] == b"HDPT" and sfplugin.edid(r[2]) == HEAD_PART[female]), None)
    if part is None:
        raise SystemExit(f"no HDPT {HEAD_PART[female]} in {sf_esm}")
    want = _u32(dict(part[2]).get(b"MNAM", b"\0\0\0\0"))
    m = next((r for r in recs if r[0] == b"MRPH" and r[3] == want), None)
    if m is None:
        raise SystemExit(f"{HEAD_PART[female]} has no morph record (MNAM)")
    return text_of(dict(m[2]).get(b"TCMP", b""))


def vanilla_head_model(sf_esm, female):
    """The MODL (NIF under Meshes\\) of the vanilla head part."""
    recs = sfplugin.records(sf_esm, [b"HDPT"])
    part = next((r for r in recs if sfplugin.edid(r[2]) == HEAD_PART[female]), None)
    if part is None or b"MODL" not in dict(part[2]):
        raise SystemExit(f"no HDPT {HEAD_PART[female]} with a model in {sf_esm}")
    return text_of(dict(part[2])[b"MODL"])


def race_model_path(name, female):
    """MODL (under Meshes\\) of a race's baked head NIF."""
    return f"S2S\\Races\\{name}\\{SEXES[female].capitalize()}Head.nif"


# Head part types (HDPT PNAM, xEdit wbDefinitionsSF1) that sit on the face and get race copies baked with the race shape
# (2026-11-10): right eye, facial hair, jewelry, eyebrows, teeth, left eye, eyelashes. Hair, scars, meatcaps and the rest
# stay shared with HumanRace (the race is added to their valid-race list).
FACE_PART_TYPES = {2: "right eye", 4: "facial hair", 7: "jewelry", 6: "eyebrows", 9: "teeth", 12: "left eye",
                   13: "eyelashes"}
HUMAN_PART_LIST = "HeadPartsHumanRace"
TEETH_TYPE = 9
RIGID_TYPES = {2, 12}      # eyes: moved as one piece with their socket (headbake.rigid_displacement)


def face_parts(recs_all, types=FACE_PART_TYPES):
    """[(FormID, EditorID, MODL, sexes [female...], type)] of the head parts HumanRace offers (RNAM = HeadPartsHumanRace)
    of the face types, plus their extra parts (HNAM), recursively; sexes from DATA (bit 1 male, bit 2 female; neither
    or both: both)."""
    lst = next((fid for t, _h, sb, fid in recs_all if t == b"FLST" and sfplugin.edid(sb) == HUMAN_PART_LIST), None)
    hd = {fid: sb for t, _h, sb, fid in recs_all if t == b"HDPT"}
    want = [fid for fid, sb in hd.items() if lst is not None and _u32(dict(sb).get(b"RNAM", bytes(4))) == lst
            and _u32(dict(sb).get(b"PNAM", bytes(4))) in types]
    seen, order = set(), []
    while want:
        fid = want.pop(0)
        if fid in seen or fid not in hd:
            continue
        seen.add(fid)
        order.append(fid)
        want += [_u32(d) for sg, d in hd[fid] if sg == b"HNAM"]
    out = []
    for fid in order:
        sb = dict(hd[fid])
        modl = text_of(sb[b"MODL"]) if b"MODL" in sb else ""
        if not modl:
            continue
        fl = sb.get(b"DATA", b"\0")[0]
        sexes = [f for f, bit in ((False, 2), (True, 4)) if fl & bit] or [False, True]
        out.append((fid, sfplugin.edid(hd[fid]), modl, sexes, _u32(sb.get(b"PNAM", bytes(4)))))
    return out


def twin(path):
    """The <model>_facebones.nif twin of a model path (Data-relative or MODL): actors with face bones (the player,
    named NPCs) are drawn from it (scripts/armor/hair_pack.py; HDPT model flag 'Has FaceBones Model'), so the looks
    menu's sculpt controls, which move face bones, act on it (2026-11-10: the Orc head had none, the shape pads did
    nothing)."""
    stem, ext = os.path.splitext(path)
    return stem + "_facebones" + ext


def _write_files(out, files):
    for rel, data in files.items():
        path = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)


def _vanilla_or_none(face_fit, rel, sf_data):
    try:
        return face_fit.hkx_to_af.vanilla_file(rel, sf_data)[0]
    except (SystemExit, KeyError, OSError):
        return None


def race_part_model(name, edid, female):
    return f"S2S\\Races\\{name}\\Parts\\{edid}_{'F' if female else 'M'}.nif"


TEXCONV_CANDIDATES = (r"C:\Modding\tools\texconv.exe", r"C:\Modding\tools\xedit\Edit Scripts\Texconvx64.exe")


def mouth_converter(sky, out, starfield, texconv="", content_resources=""):
    """(SkyrimConverter, staging folder) for the mouth's material, or (None, why) without texconv / ContentResources."""
    import shutil
    from fo4sf import skyrimconvert
    tc = next((c for c in (texconv, *TEXCONV_CANDIDATES, shutil.which("texconv") or "") if c and os.path.isfile(c)),
              "")
    cr = content_resources or os.path.join(starfield, "Tools", "ContentResources.zip")
    if not tc or not os.path.isfile(cr):
        return None, f"no texconv ({tc or 'not found'}) or ContentResources.zip ({cr})"
    staging = os.path.join(out, "_mouth_staging")
    shutil.rmtree(staging, ignore_errors=True)
    return skyrimconvert.SkyrimConverter(sky, staging, tc, cr, collision_template=None, prefix="s2s"), staging


def vanilla_teeth(recs, sf_data, female, face_fit):
    """(HDPT FormID, NIF bytes, {"TMPP" / "TCMP": Morph or None}, MRPH FormID, vanilla vertex count) of the default
    teeth part of a sex (mouth_probe.SF_TEETH_PART)."""
    import mouth_probe
    hd = {fid: sb for t, _h, sb, fid in recs if t == b"HDPT"}
    mr = {fid: sb for t, _h, sb, fid in recs if t == b"MRPH"}
    fid = next((f for f, sb in hd.items() if sfplugin.edid(sb) == mouth_probe.SF_TEETH_PART[female]), None)
    if fid is None:
        raise ValueError(f"no HDPT {mouth_probe.SF_TEETH_PART[female]}")
    sb = dict(hd[fid])
    nb = face_fit.hkx_to_af.vanilla_file("meshes/" + text_of(sb[b"MODL"]).replace("\\", "/"), sf_data)[0]
    m_fid = _u32(sb.get(b"MNAM", bytes(4)))
    morphs = {}
    for sig in (b"TMPP", b"TCMP"):
        folder = text_of(dict(mr.get(m_fid, [])).get(sig, b"")) if m_fid in mr else ""
        if not folder:
            continue
        try:
            morphs[sig.decode()] = sfmorph.parse(face_fit.hkx_to_af.vanilla_file(
                folder.replace("\\", "/").lower() + "/morph.dat", sf_data)[0])
        except (SystemExit, KeyError, OSError, sfmorph.MorphError):
            morphs[sig.decode()] = None
    return fid, nb, morphs, m_fid


def write_mouths(sf_data, out, made, races, recs, sky, conv_args, face_fit, gain=None, uv_test=False):
    """{race: {female: info}} of the races in race_mouths.RACE_MOUTHS: Skyrim's mouth converted as the race's teeth
    (race_mouths.convert_mouth), files under out; info carries the vanilla teeth part / morph record it replaces.
    gain: the mouth texture's colour multiplied by this (race_mouths.MOUTH_ALBEDO_GAIN when None); uv_test: the
    colour texture replaced by race_mouths.uv_test_pixels (to see which way the tusks sample it in game)."""
    import shutil
    import mouth_probe
    import race_mouths
    want = [r for r in races if r in race_mouths.RACE_MOUTHS]
    if not want or sky is None:
        return {}, {}
    conv, staging = mouth_converter(sky, out, *conv_args)
    rep, done = {}, {}
    teeth_types = {fid for t, _h, sb, fid in recs if t == b"HDPT" and _u32(dict(sb).get(b"PNAM", bytes(4))) ==
                   race_mouths.TEETH_TYPE}
    for race in want:
        for female, m in made.items():
            key = f"{race} {SEXES[female]}"
            if "align" not in m:
                rep[key] = {"error": "no head alignment"}
                continue
            sky_path = mouth_probe.SKY_MOUTHS[female][race_mouths.RACE_MOUTHS[race]]
            try:
                t_fid, t_nif, t_morphs, m_fid = vanilla_teeth(recs, sf_data, female, face_fit)
                head_raw = face_fit.hkx_to_af.vanilla_file(face_fit.SF_HEADS[female], sf_data)[0]
                _p, head_skin = facefit.starfield_head_parts(head_raw)
                material = None
                if conv is not None:
                    from fo4sf import nif as nifmod, skyrimskin
                    sn = nifmod.parse(face_fit.hkx_to_af.read_any(sky_path, sky))
                    shp = next(iter(skyrimskin.skinned_shapes(sn)), None)
                    g = race_mouths.MOUTH_ALBEDO_GAIN if gain is None else gain
                    material = (conv._shape_material(sn, shp, albedo_tint=(g, g, g) if g != 1.0 else None)
                                if shp is not None else None)
                    if material == conv.neutral:
                        material = None
                base = f"meshes/s2s/races/{NAMES[race].lower()}/mouth_{'f' if female else 'm'}"
                t_modl = next((text_of(d) for t_, _h, sb_, f_ in recs if t_ == b"HDPT" and f_ == t_fid
                               for x, d in sb_ if x == b"MODL"), "")
                t_fb = _vanilla_or_none(face_fit, twin("meshes/" + t_modl.replace("\\", "/")), sf_data) if t_modl \
                    else None
                files, info = race_mouths.convert_mouth(
                    lambda p: face_fit.hkx_to_af.read_any(p, sky),
                    lambda p: face_fit.hkx_to_af.vanilla_file(p, sf_data)[0], sky_path, m["align"], m["vertices"],
                    head_skin, t_nif, t_morphs, base, material, t_fb)
            except (SystemExit, KeyError, ValueError, OSError) as e:
                rep[key] = {"error": str(e)[:300]}
                continue
            _write_files(out, files)
            info.update(part_fid=t_fid, mrph_fid=m_fid, material_converted=material is not None,
                        replaces=sorted(f for f in teeth_types if f in _sex_parts(recs, female)))
            done.setdefault(race, {})[female] = info
            rep[key] = {k: v for k, v in info.items() if k not in ("replaces",)}
            print(f"  {key}: mouth {info['vertices']} vertices ({info['jaw_vertices']} on the jaw), material "
                  f"{'converted' if material else 'vanilla teeth (no texconv / ContentResources)'}; _facebones: "
                  f"{info.get('facebones')}")
    if conv is not None:
        for d in ("materials", "textures"):
            if os.path.isdir(os.path.join(staging, d)):
                shutil.copytree(os.path.join(staging, d), os.path.join(out, d), dirs_exist_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
        if uv_test:
            for race, by_sex in done.items():
                for female, info in by_sex.items():
                    rel = race_mouths.color_texture_of(info.get("material") or "")
                    if not rel:
                        continue
                    from fo4sf import textures
                    p = os.path.join(out, *rel.split("/"))
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    textures.write_dds_dx10(p, 256, 256, race_mouths.DXGI_RGBA8_SRGB, race_mouths.uv_test_pixels(256),
                                            4)
                    info["uv_test"] = rel
                    rep[f"{race} {SEXES[female]}"]["uv_test"] = rel
    elif want:
        rep["material"] = staging
    return done, rep


def _sex_parts(recs, female):
    """FormIDs of HDPTs usable by a sex (DATA bit 1 male, bit 2 female; neither = both)."""
    out = set()
    for t, _h, sb, fid in recs:
        if t != b"HDPT":
            continue
        fl = dict(sb).get(b"DATA", b"\0")[0]
        if not fl & 6 or fl & (4 if female else 2):
            out.add(fid)
    return out


def write_race_heads(sf_data, out, made, races, parts=True, sky=None, conv_args=("", "", ""), mouth_gain=None,
                     mouth_uv_test=False):
    """Per race and sex: the vanilla head part's NIF with the race shape baked into its head meshes
    (headbake.baked_head_files), and (parts) every face head part HumanRace offers baked the same way
    (headbake.baked_part_files), written under out. Returns ({race: {female: MODL}}, {race: [(part FormID, female,
    MODL)]}, report)."""
    from fo4sf import headbake
    import face_fit
    import time
    esm = os.path.join(sf_data, "Starfield.esm")
    models, race_parts, rep = {}, {}, {}
    precs = sfplugin.records(esm, [b"HDPT", b"FLST", b"MRPH"])
    plist = face_parts(precs) if parts else []
    mouths, mrep = (write_mouths(sf_data, out, made, races, precs, sky, conv_args, face_fit, mouth_gain, mouth_uv_test)
                    if parts else ({}, {}))
    for female, m in made.items():
        modl = vanilla_head_model(esm, female)
        nif_bytes, _rel = face_fit.hkx_to_af.vanilla_file("meshes/" + modl.replace("\\", "/"), sf_data)
        paths, _skin = facefit.starfield_head_parts(nif_bytes)
        if not paths:
            raise SystemExit(f"{modl}: no head geometry")
        for race in races:
            if race not in m.get("disp", {}):
                continue
            mp = race_model_path(NAMES[race], female)
            read = lambda r: face_fit.hkx_to_af.vanilla_file(r, sf_data)[0]
            files = headbake.baked_head_files(nif_bytes, read, paths[0], m["vertices"], m["disp"][race],
                                              "meshes/" + mp.replace("\\", "/").lower())
            fb = _vanilla_or_none(face_fit, twin("meshes/" + modl.replace("\\", "/")), sf_data)
            if fb is not None:          # the _facebones twin, what the player is drawn from
                fpaths, _s = facefit.starfield_head_parts(fb)
                files.update(headbake.baked_head_files(fb, read, fpaths[0], m["vertices"], m["disp"][race],
                                                       twin("meshes/" + mp.replace("\\", "/").lower())))
            # the facial bone regions file (the sculpt dials), named after the race like vanilla's
            # humanracefacialboneregions<sex>.txt (hypothesis: looked up by race EditorID): a copy under our name
            reg = _vanilla_or_none(face_fit, face_fit.SF_REGIONS[female], sf_data)
            if reg is not None:
                files[face_fit.SF_REGIONS[female].replace(
                    "humanrace", f"s2s_{NAMES[race].lower()}race")] = reg
            _write_files(out, files)
            models.setdefault(race, {})[female] = mp
            rep.setdefault(race, {})[SEXES[female]] = {"from": modl, "model": mp, "files": len(files),
                                                       "facebones_twin": fb is not None,
                                                       "max_move_m": round(float(np.linalg.norm(
                                                           m["disp"][race], axis=1).max()), 4)}
        if not plist:
            continue
        head_raw, _ = face_fit.hkx_to_af.vanilla_file(face_fit.SF_HEADS[female], sf_data)
        _p, head_skin = facefit.starfield_head_parts(head_raw)
        for race in races:
            if race not in m.get("disp", {}):
                continue
            t0, prep, done = time.time(), {}, 0
            todo = sum(1 for x in plist if female in x[3])
            print(f"  {race} {SEXES[female]}: baking {todo} face parts ...", flush=True)
            seen = 0
            for fid, edid, modl, sexes, ptype in plist:
                if female not in sexes:
                    continue
                seen += 1
                if seen % 25 == 0:
                    print(f"    {seen} / {todo} ({time.time() - t0:.0f} s)", flush=True)
                if ptype == TEETH_TYPE and female in mouths.get(race, {}):
                    continue                # the race's own mouth replaces the teeth (write_mouths)
                try:
                    nb, _r = face_fit.hkx_to_af.vanilla_file("meshes/" + modl.replace("\\", "/"), sf_data)
                except (SystemExit, KeyError, OSError) as e:
                    prep[edid] = {"error": f"model not found: {e}"}
                    continue
                mp = race_part_model(NAMES[race], edid, female)
                try:
                    files, frep = headbake.baked_part_files(
                        nb, lambda r: face_fit.hkx_to_af.vanilla_file(r, sf_data)[0], m["vertices"],
                        m["disp"][race], head_skin, "meshes/" + mp.replace("\\", "/").lower(), ptype in RIGID_TYPES)
                except (SystemExit, KeyError, ValueError, OSError) as e:
                    prep[edid] = {"error": str(e)[:200]}
                    continue
                fb = _vanilla_or_none(face_fit, twin("meshes/" + modl.replace("\\", "/")), sf_data)
                if fb is not None:
                    try:
                        f2, r2 = headbake.baked_part_files(
                            fb, lambda r: face_fit.hkx_to_af.vanilla_file(r, sf_data)[0], m["vertices"],
                            m["disp"][race], head_skin, twin("meshes/" + mp.replace("\\", "/").lower()),
                            ptype in RIGID_TYPES)
                        files.update(f2)
                        frep["facebones_twin"] = r2
                    except (SystemExit, KeyError, ValueError, OSError) as e:
                        frep["facebones_twin"] = {"error": str(e)[:200]}
                _write_files(out, files)
                race_parts.setdefault(race, []).append((fid, female, mp))
                prep[edid] = frep
                done += 1
            rep[race][SEXES[female]]["parts"] = prep
            print(f"  {race} {SEXES[female]}: {done} face parts baked ({time.time() - t0:.0f} s)")
    return models, race_parts, rep, mouths, mrep


def neutral_extra(morph):
    """(colour, normal, tangent) words for our new keys' records: the vanilla head's most common colour word (the
    clothing files use 0xC618 throughout) and zero normal / tangent deltas (2026-11-09, owner: the race faces came out
    dark red; our records carried zeros, which decode to normal deltas of -511)."""
    from collections import Counter
    cols = Counter(e[0] for k in morph.keys for e in morph.extra.get(k, {}).values())
    col = cols.most_common(1)[0][0] if cols else sfmorph.NEUTRAL_EXTRA[0]
    return (col, sfmorph.NEUTRAL_EXTRA[1], sfmorph.NEUTRAL_EXTRA[2])


HAIR_TYPES = (3, 4)          # HDPT PNAM: hair, facial hair (npc_hair.HAIR, FACIAL_HAIR)


def without_hair(subs, part_types):
    """NPC subrecords without hair / facial hair head parts (2026-11-09, owner: the males' long hair hid the ears and
    the sides of the face the race shapes change)."""
    return [(s, d) for s, d in subs if not (s == b"PNAM" and len(d) == 4 and part_types.get(_u32(d)) in HAIR_TYPES)]


SHORT_HAIR = ("bald", "shaved", "shaven", "buzz")


def short_hair(hdpts, part_types, female):
    """(FormID, EditorID) of the closest-cropped vanilla hair for the sex, or None (2026-11-09, owner: with no hair
    part the race's default hair came back and still hid the ears and the head's shape): a hair head part whose
    EditorID says bald / shaved / buzz, the sex's own first (DATA flags: 0x2 male, 0x4 female, as npc_hair)."""
    want = 0x4 if female else 0x2
    hits = []
    for fid, subs in hdpts.items():
        e = sfplugin.edid(subs)
        if part_types.get(fid) != HAIR_TYPES[0] or not any(w in e.lower() for w in SHORT_HAIR):
            continue
        flags = (dict(subs).get(b"DATA") or b"\0")[0]
        rank = next(i for i, w in enumerate(SHORT_HAIR) if w in e.lower())
        hits.append((not (flags & want), rank, e, fid))
    if not hits:
        return None
    best = min(hits)
    return best[3], best[2]


def with_head_part(subs, head_fid, part_types):
    """NPC subrecords with Face-type head parts (PNAM) dropped and head_fid added after the last PNAM (or after DNAM /
    DATA when there is none)."""
    out = [(s, d) for s, d in subs if not (s == b"PNAM" and len(d) == 4 and part_types.get(_u32(d)) == 1)]
    at = max([i + 1 for i, (s, _d) in enumerate(out) if s == b"PNAM"] or
             [i + 1 for i, (s, _d) in enumerate(out) if s in (b"DNAM", b"DATA")] or [len(out)])
    return out[:at] + [(b"PNAM", struct.pack("<I", head_fid))] + out[at:]


def with_blends(subs, blends):
    """NPC subrecords with BMPN / BMPV blends (name sorted, as xEdit's sorted array) after the face data."""
    subs = [(s, d) for s, d in subs if s not in (b"BMPN", b"BMPV")]
    face = [i for i, (s, _d) in enumerate(subs) if s in (b"FMSI", b"FMRS", b"FMRI", b"FMRG")]
    at = face[-1] + 1 if face else next((i for i, (s, _d) in enumerate(subs) if s in (b"ATTX", b"STON", b"HCOL")),
                                        len(subs))
    add = []
    for name in sorted(blends):
        add += [(b"BMPN", sfplugin.zs(name)), (b"BMPV", struct.pack("<f", float(blends[name])))]
    return subs[:at] + add + subs[at:]


PRESET_SIG = {False: b"RPRM", True: b"RPRF"}


def add_presets(subs, presets):
    """RACE subrecords with chargen race presets added per sex: RPRM (male) / RPRF (female) NPC FormIDs after the
    sex's last one, or after its chargen marker block (NAM0 / NNAM) when it has none. presets: {female: [NPC FormIDs]}.
    2026-11-10: the first version appended FDSI / FDSL pairs, which are the Face Dials (index + localized label;
    xEdit wbDefinitionsSF1 RACE "Chargen": NAM0, NNAM, RPRM/RPRF "Race Presets", morph groups, phenotypes, FDDS,
    FDSI/FDSL "Face Dials"), so they showed up as extra, unnamed face rows."""
    sex, last, anchor = None, {}, {}
    for i, (s_, d) in enumerate(subs):
        if s_ in (b"MNAM", b"FNAM") and len(d) == 0:
            sex = (s_ == b"FNAM")
        elif sex is not None and s_ == PRESET_SIG[sex]:
            last[sex] = i
        elif sex is not None and s_ in (b"NAM0", b"NNAM") and sex not in last:
            anchor[sex] = i
    at = {f: last.get(f, anchor.get(f)) for f in presets}
    out = []
    for i, sd in enumerate(subs):
        out.append(sd)
        for f, fids in presets.items():
            if at.get(f) == i:
                out += [(PRESET_SIG[f], struct.pack("<I", fid)) for fid in fids]
    return out


def with_extra_part(subs, part_fid):
    """HDPT subrecords with part_fid added as an extra part (HNAM) after its type (PNAM) / other extra parts."""
    at = max((i for i, (s_, _d) in enumerate(subs) if s_ in (b"PNAM", b"HNAM")), default=len(subs) - 1)
    return list(subs[:at + 1]) + [(b"HNAM", struct.pack("<I", part_fid))] + list(subs[at + 1:])


def race_preset_copies(rsubs, npcs, name, race_fid, heads, part_types, copies, new_fid):
    """(RACE subrecords, [NPC_ records]): each chargen preset of the race (RPRM / RPRF, copied from HumanRace: vanilla
    preset NPCs) replaced by a copy on the race - RNAM ours, its Face head part the race's head, its other parts the
    race copies (2026-11-11: a new game's player is built from the first preset, so the Orc player kept the preset's
    human teeth, brows and eyes; only the head, which the menu takes from the race, was ours). npcs: {FormID: (header,
    subs)}; heads {female: HDPT}; copies {female: {vanilla: copy}}."""
    made, out, recs = {}, [], []
    for s_, d in rsubs:
        if s_ in PRESET_SIG.values() and len(d) == 4 and _u32(d) in npcs:
            v = _u32(d)
            if v not in made:
                female = s_ == PRESET_SIG[True]
                h, sb = npcs[v]
                edid = f"S2S_{name}Race_{sfplugin.edid(sb) or f'Preset{v:08X}'}"
                fid = new_fid(edid)
                subs = sfplugin.edit(list(sb), {b"EDID": sfplugin.zs(edid), b"RNAM": struct.pack("<I", race_fid)})
                if female in heads:
                    subs = with_head_part(subs, heads[female], part_types)
                subs = swap_parts(subs, copies.get(female, {}))
                recs.append((b"NPC_", h, subs, fid))
                made[v] = fid
            d = struct.pack("<I", made[v])
        out.append((s_, d))
    return out, recs


LSTRING_SIGS = {b"FULL": "strings", b"DESC": "dlstrings", b"FMRN": "strings", b"FDSL": "strings",
                b"MPPN": "strings"}


def load_lstrings(sf_data, language="en"):
    """{"strings" / "dlstrings" / "ilstrings": {id: text}} of Starfield.esm: loose Data\\Strings\\starfield_<lang>.*
    or from the localization archives. {} if none found."""
    from fo4sf import ba2, skyrimdialog
    out = {}
    for ext in ("strings", "dlstrings", "ilstrings"):
        name = f"strings/starfield_{language}.{ext}"
        raw = None
        loose = os.path.join(sf_data, "Strings", f"starfield_{language}.{ext}")
        if os.path.isfile(loose):
            with open(loose, "rb") as fh:
                raw = fh.read()
        else:
            for fn in sorted(os.listdir(sf_data)) if os.path.isdir(sf_data) else []:
                if fn.lower().startswith("starfield - localization") and fn.lower().endswith(".ba2"):
                    arc = ba2.Ba2(os.path.join(sf_data, fn))
                    i = arc.find(name)
                    if i is not None:
                        raw = arc.read(i)
                        break
        if raw:
            out[ext] = skyrimdialog.read_lstrings(raw, ext != "strings")
    return out


def delocalize(subs, tables):
    """Subrecords with localized string ids (Starfield.esm is localized; our plugins are not, so a copied id shows as
    garbage, 2026-11-10: the Orc race's face rows read "U", "Z") replaced by their text from tables (load_lstrings).
    An id not in the table becomes an empty string."""
    if not tables:
        return subs
    out = []
    for s_, d in subs:
        t = LSTRING_SIGS.get(s_)
        if t and len(d) == 4 and t in tables:
            sid = _u32(d)
            d = sfplugin.zs(tables[t].get(sid, "")) if sid else d
        out.append((s_, d))
    return out


def swap_parts(subs, mapping, sig=b"PNAM"):
    """subs with each sig FormID found in mapping replaced (head parts: vanilla -> the race's baked copy)."""
    return [(s_, struct.pack("<I", mapping[_u32(d)]) if s_ == sig and len(d) == 4 and _u32(d) in mapping else d)
            for s_, d in subs]


def swap_race_heads(subs, by_sex):
    """RACE subrecords with each default head part (HEAD) swapped per sex section (the empty MNAM / FNAM markers):
    by_sex {female: {vanilla FormID: copy FormID}}."""
    sex, out = None, []
    for s_, d in subs:
        if s_ in (b"MNAM", b"FNAM") and len(d) == 0:
            sex = (s_ == b"FNAM")
        elif s_ == b"HEAD" and len(d) == 4 and sex is not None and _u32(d) in by_sex.get(sex, {}):
            d = struct.pack("<I", by_sex[sex][_u32(d)])
        out.append((s_, d))
    return out


def race_part_records(recs_all, name, race_fid, parts, new_fid, mouths=None):
    """(records, {female: {vanilla FormID: copy FormID}}, list FormID): the race's valid-race list (FLST
    S2S_HeadParts<name>Race, holding the race) and a copy of each baked face part (EDID S2S_<name>Race_<part>_M/F,
    MODL the baked model, RNAM that list, DATA this sex only, extra parts HNAM -> their copies of the same sex).
    parts: [(vanilla FormID, female, MODL)]."""
    by = {fid: (h, sb) for t, h, sb, fid in recs_all if t in (b"HDPT", b"FLST", b"MRPH")}
    src_list = next((v for v in by.values() if sfplugin.edid(v[1]) == HUMAN_PART_LIST), None)
    l_fid = new_fid(f"S2S_HeadParts{name}Race")
    recs = [(b"FLST", src_list[0] if src_list else b"", [(b"EDID", sfplugin.zs(f"S2S_HeadParts{name}Race")),
                                                        (b"LNAM", struct.pack("<I", race_fid))], l_fid)]
    copies = {}
    for vfid, female, _modl in parts:
        copies.setdefault(female, {})[vfid] = new_fid(
            f"S2S_{name}Race_{sfplugin.edid(by[vfid][1])}_{'F' if female else 'M'}")
    for vfid, female, modl in parts:
        h, sb = by[vfid]
        ed = {b"EDID": sfplugin.zs(f"S2S_{name}Race_{sfplugin.edid(sb)}_{'F' if female else 'M'}"),
              b"MODL": sfplugin.zs(modl), b"RNAM": struct.pack("<I", l_fid)}
        fl = dict(sb).get(b"DATA")
        if fl:                              # this sex only (DATA is required on vanilla parts; not added if missing)
            ed[b"DATA"] = bytes([(fl[0] & ~0x6) | (4 if female else 2)]) + bytes(fl[1:])
        sub = sfplugin.edit(list(sb), ed)
        sub = swap_parts(sub, copies[female], sig=b"HNAM")
        recs.append((b"HDPT", h, sub, copies[female][vfid]))
    for female, info in (mouths or {}).items():
        recs += mouth_records(by, info, name, female, l_fid, copies.setdefault(female, {}), new_fid)
    return recs, copies, l_fid


def mouth_records(by, info, name, female, l_fid, copies, new_fid):
    """The race's mouth (race_mouths.convert_mouth info): a copy of the vanilla teeth's morph record (TMPP / TCMP ->
    our folders, its vertex count in MOBC -> ours) and of the vanilla teeth part (MODL ours, MNAM that record, RNAM
    the race's list, this sex only); every vanilla teeth part of the sex maps to it (copies)."""
    import os_export
    allrecs = by
    out = []
    t_fid, m_fid = info["part_fid"], info["mrph_fid"]
    mrph = allrecs.get(m_fid)
    new_m = None
    if mrph is not None:
        msubs = dict(mrph[1])
        ed = {b"EDID": sfplugin.zs(f"S2S_{name}Race_Mouth_{'F' if female else 'M'}_Morph")}
        for sig in (b"TMPP", b"TCMP"):
            folder = info["morph_folders"].get(sig.decode())
            if folder and sig in msubs:
                ed[sig] = os_export.replace_text(msubs[sig], "Meshes\\" + folder.split("\\", 1)[1]
                                                 if folder.lower().startswith("meshes\\") else folder)
        mobc = bytes(msubs.get(b"MOBC", b""))
        if mobc and info.get("vanilla_vertices"):
            b = bytearray(mobc)
            for i in os_export.u32_offsets(mobc, int(info["vanilla_vertices"])):
                struct.pack_into("<I", b, i, int(info["vertices"]))
            ed[b"MOBC"] = bytes(b)
        new_m = new_fid(f"S2S_{name}Race_Mouth_{'F' if female else 'M'}_Morph")
        out.append((b"MRPH", mrph[0], sfplugin.edit(list(mrph[1]), ed), new_m))
    h, sb = allrecs[t_fid]
    ed = {b"EDID": sfplugin.zs(f"S2S_{name}Race_Mouth_{'F' if female else 'M'}"), b"MODL": sfplugin.zs(info["model"]),
          b"RNAM": struct.pack("<I", l_fid)}
    if new_m is not None:
        ed[b"MNAM"] = struct.pack("<I", new_m)
    fl = dict(sb).get(b"DATA")
    if fl:
        ed[b"DATA"] = bytes([(fl[0] & ~0x6) | (4 if female else 2)]) + bytes(fl[1:])
    p_fid = new_fid(f"S2S_{name}Race_Mouth_{'F' if female else 'M'}")
    out.append((b"HDPT", h, sfplugin.edit(list(sb), ed), p_fid))
    for v in set(info.get("replaces", [])) | {t_fid}:
        copies[v] = p_fid
    return out


def human_only_parts(recs_all, vanilla_fids, new_fid):
    """(records): a list S2S_HeadPartsHumanOnly holding HeadPartsHumanRace's vanilla entries, and an override of each
    vanilla face part that has race copies with its valid races (RNAM) set to it, so a race of ours (in
    HeadPartsHumanRace for the shared parts: hair, ...) is offered its own copies only."""
    src = next(((h, sb) for t, h, sb, fid in recs_all if t == b"FLST" and sfplugin.edid(sb) == HUMAN_PART_LIST), None)
    if src is None:
        return []
    l_fid = new_fid("S2S_HeadPartsHumanOnly")
    out = [(b"FLST", src[0], [(b"EDID", sfplugin.zs("S2S_HeadPartsHumanOnly"))] +
            [(s_, d) for s_, d in src[1] if s_ != b"EDID" and len(d) == 4], l_fid)]
    for t, h, sb, fid in recs_all:
        if t == b"HDPT" and fid in vanilla_fids:
            out.append((b"HDPT", h, sfplugin.edit(list(sb), {b"RNAM": struct.pack("<I", l_fid)}), fid))
    return out


CHARGEN_PART_LISTS = ("HeadPartsChargenOptionsMale", "HeadPartsChargenOptionsFemale")


def chargen_option_lists(recs_all, part_copies):
    """(records): an override of each of Starfield's chargen head part lists (CHARGEN_PART_LISTS) with every race copy
    of its entries added after the entries (2026-11-11: the race's records hand the player our Orc mouth, yet the looks
    menu showed the human teeth even on a new game: the menu takes its parts from these lists, where only the vanilla
    parts were; with human_only_parts those are not valid for our races, the copies are). part_copies:
    {race: {female: {vanilla FormID: copy FormID}}}."""
    by_vanilla = {}
    for per_sex in part_copies.values():
        for m in per_sex.values():
            for v, c in m.items():
                by_vanilla.setdefault(v, [])
                if c not in by_vanilla[v]:
                    by_vanilla[v].append(c)
    out = []
    for t, h, sb, fid in recs_all:
        if t != b"FLST" or sfplugin.edid(sb) not in CHARGEN_PART_LISTS:
            continue
        have = [_u32(d) for s_, d in sb if s_ == b"LNAM" and len(d) == 4]
        add = [c for v in have for c in by_vanilla.get(v, []) if c not in have]
        if add:
            out.append((b"FLST", h, list(sb) + [(b"LNAM", struct.pack("<I", c)) for c in dict.fromkeys(add)], fid))
    return out


def player_patch(player_subs, race_fid, heads, part_types, part_copies=None):
    """The vanilla Player record (NPC_ 00000007) with its race (RNAM) set to ours and its Face head part ours, as
    the Exo Race mod's player patch does (Nexus 7992: ExoRacePlayer.esm edits the player record; 2026-11-09, owner's
    setrace on the player left getisrace 0)."""
    acbs = next((bytes(d) for s, d in player_subs if s == b"ACBS"), b"")
    female = bool(acbs and struct.unpack_from("<I", acbs, 0)[0] & 1)
    subs = sfplugin.edit(list(player_subs), {b"RNAM": struct.pack("<I", race_fid)})
    if female in heads:
        subs = with_head_part(subs, heads[female], part_types)
    if part_copies and female in part_copies:
        subs = swap_parts(subs, part_copies[female])
    return subs


def with_races(flst_subs, human_fid, race_fids):
    """A form list (FLST) with race_fids appended after its last HumanRace-or-other 4-byte entry, in the entries'
    own signature, or None if it does not hold HumanRace. 2026-11-10 (owner: showlooksmenu as S2S_OrcRace crashes
    when hovering facial hair): every vanilla beard names its valid races as a list (HDPT RNAM 0024A024 =
    HeadPartsHumanRace), which our race was not in."""
    entries = [i for i, (sg, d) in enumerate(flst_subs) if sg != b"EDID" and len(d) == 4]
    hits = [i for i in entries if _u32(flst_subs[i][1]) == human_fid]
    if not hits:
        return None
    sig = flst_subs[hits[0]][0]
    have = {_u32(flst_subs[i][1]) for i in entries}
    add = [(sig, struct.pack("<I", f)) for f in race_fids if f not in have]
    at = entries[-1] + 1
    return list(flst_subs[:at]) + add + list(flst_subs[at:])


class FormIds:
    """Stable FormIDs per EditorID across rebuilds (2026-11-10, races roadmap A: a rebuild must not move S2S_OrcRace
    or a saved game loses it). The ledger (race_formids.json in --out) maps each EditorID to its object id; a new
    EditorID takes the next id after every id ever used (ids of dropped records are never reused)."""

    def __init__(self, path=None, masters=1):
        self.path, self.masters, self.ids, self.new = path, masters, {}, []
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                self.ids = {k: int(v, 16) for k, v in json.load(fh).get("ids", {}).items()}
        self.next = max(list(self.ids.values()) + [sfplugin.FIRST_OBJECT - 1]) + 1

    def take(self, edid: str) -> int:
        if edid not in self.ids:
            self.ids[edid] = self.next
            self.next += 1
            self.new.append(edid)
        return (self.masters << 24) | self.ids[edid]

    def save(self):
        if self.path:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump({"note": "EditorID -> object id of our records; keep this file: rebuilds reuse it so "
                                   "FormIDs stay the same (saved games)",
                           "ids": {k: f"{v:06X}" for k, v in sorted(self.ids.items(), key=lambda kv: kv[1])}},
                          fh, indent=1)


LEDGER = "race_formids.json"
GET_IS_RACE_SF = 69        # Starfield's condition function index for GetIsRace (race_probe counted 19 on HumanRace)
CONDITION_TYPES = (b"CNDF", b"IDLE", b"CPTH")       # top-level records whose CTDAs we patch (INFOs: later)


def with_race_conditions(subs, human_fid, race_fids):
    """(subs, changed) with each 'GetIsRace HumanRace' condition widened to our races (2026-11-10, races roadmap A):
    'is HumanRace' (== 1 / != 0) becomes an OR group with one GetIsRace per race of ours; 'is not HumanRace'
    (== 0 / != 1) gets one 'is not' per race ANDed after it (skipped when it sits in an OR group). CTDA: u8 flags
    (bit 0 OR, operator in the top 3 bits), f32 value, u16 function, param 1 at 12."""
    out, changed = [], 0
    for s_, d in subs:
        d = bytes(d)
        if s_ != b"CTDA" or len(d) < 16 or struct.unpack_from("<H", d, 8)[0] != GET_IS_RACE_SF \
                or struct.unpack_from("<I", d, 12)[0] != human_fid or d[0] & 0x04:
            out.append((s_, d))
            continue
        op, val = d[0] >> 5, struct.unpack_from("<f", d, 4)[0]
        positive = (op == 0 and val == 1.0) or (op == 1 and val == 0.0)
        negative = (op == 0 and val == 0.0) or (op == 1 and val == 1.0)
        copies = [d[:12] + struct.pack("<I", r) + d[16:] for r in race_fids]
        if positive:
            orig_or = d[0] & 1
            seq = [d] + copies
            for i, c in enumerate(seq):
                flag = 1 if i < len(seq) - 1 else orig_or
                out.append((s_, bytes([(c[0] & ~1) | flag]) + c[1:]))
            changed += 1
        elif negative and not d[0] & 1:
            out += [(s_, d)] + [(s_, c) for c in copies]
            changed += 1
        else:
            out.append((s_, d))
    return out, changed


def race_condition_patches(recs_all, human_fid, race_fids):
    """[(type, header, subs, FormID)] overrides of the CONDITION_TYPES records whose conditions ask GetIsRace
    HumanRace, widened to our races."""
    out = []
    for t, h, s_, fid in recs_all:
        if t in CONDITION_TYPES:
            new, n = with_race_conditions(s_, human_fid, race_fids)
            if n:
                out.append((t, h, new, fid))
    return out


def head_part_race_lists(recs_all, human_fid, race_fids):
    """[(header, subs, FormID)]: each form list that holds HumanRace (the head parts' valid races, HDPT RNAM, and since
    2026-11-10 every other: races roadmap A, conditions asking IsInList of such a list), with race_fids added, so
    the looks menu, NPCs and conditions take our races as human."""
    out = []
    for t, h, s, fid in recs_all:
        if t == b"FLST":
            new = with_races(s, human_fid, race_fids)
            if new is not None:
                out.append((h, new, fid))
    return out


def build_plugin(sf_esm, made, race_head=False, keep_hair=False, new_races=(), race_models=None, strings=None,
                 race_parts=None, heights=None, mouths=None, ids=None, mouth_on_head=False):
    """made: {female: {"folder", "keys_by_race": {race: [keys]}, "keys_by_region": {region: [keys]}}}.
    race_models: {race: {female: MODL}}: new races whose shape is baked into a head model of their own (2026-11-10):
    such a race gets a head part per sex (ours with that MODL), no chargen phenotype or morph-group keys (its chargen
    lists stay HumanRace's), and its NPCs no race blends. Returns (records, info, report)."""
    race_models = race_models or {}
    import face_fit
    info = sfplugin.header_info(sf_esm)
    recs_all = sfplugin.records(sf_esm, [b"HDPT", b"MRPH", b"RACE", b"NPC_", b"OTFT", b"FLST", *CONDITION_TYPES])
    if strings:                       # our plugins are not localized: copies carry text, not string ids
        recs_all = [(t, h, delocalize(sb, strings), fid) for t, h, sb, fid in recs_all]
    by_fid = {fid: (t, h, s) for t, h, s, fid in recs_all}
    part_types = {fid: _u32(dict(s).get(b"PNAM", b"\0\0\0\0")) for t, h, s, fid in recs_all if t == b"HDPT"}
    hdpts = {fid: s for t, h, s, fid in recs_all if t == b"HDPT"}
    human = next((fid for t, _h, s, fid in recs_all if t == b"RACE" and sfplugin.edid(s) == "HumanRace"), None)
    npc_recs = [r for r in recs_all if r[0] == b"NPC_"]
    npc_by = {fid: (h, s) for t, h, s, fid in npc_recs}
    masters = 1
    ids = ids or FormIds(None, masters)
    recs, rep = [], {"npcs": [], "head_parts": {}}
    otft = next((r for r in recs_all if r[0] == b"OTFT"), None)
    no_outfit = None
    if otft is not None:
        no_outfit = ids.take("S2S_NoOutfit")
        recs.append((b"OTFT", otft[1], [(b"EDID", sfplugin.zs("S2S_NoOutfit")), (b"INAM", b"")], no_outfit))
    heads = {}
    for female, m in made.items():
        sex = SEXES[female]
        part = next((r for r in recs_all if r[0] == b"HDPT" and sfplugin.edid(r[2]) == HEAD_PART[female]), None)
        if part is None:
            raise SystemExit(f"no HDPT {HEAD_PART[female]} in {sf_esm}")
        mrph = by_fid.get(_u32(dict(part[2]).get(b"MNAM", b"\0\0\0\0")))
        if mrph is None or mrph[0] != b"MRPH":
            raise SystemExit(f"{HEAD_PART[female]} has no morph record (MNAM)")
        import os_export
        m_fid = ids.take(f"S2S_SkyrimRaces_{sex}_HeadMorph")
        tcmp_old = dict(mrph[2]).get(b"TCMP", b"")
        msubs = sfplugin.edit(list(mrph[2]), {b"EDID": sfplugin.zs(f"S2S_SkyrimRaces_{sex}_HeadMorph"),
                                              b"TCMP": os_export.replace_text(tcmp_old, m["folder"])})
        recs.append((b"MRPH", mrph[1], msubs, m_fid))
        h_fid = ids.take(f"S2S_SkyrimRaces_{sex}_Head")
        hsubs = sfplugin.edit(list(part[2]), {b"EDID": sfplugin.zs(f"S2S_SkyrimRaces_{sex}_Head"),
                                              b"MNAM": struct.pack("<I", m_fid)})
        recs.append((b"HDPT", part[1], hsubs, h_fid))
        heads[female] = h_fid
        part_types[h_fid] = 1           # ours too: with_head_part must drop it when an NPC gets another head
        rep["head_parts"][sex] = {"HDPT": f"{h_fid:08X}", "MRPH": f"{m_fid:08X}", "template": HEAD_PART[female],
                                  "template_morph_folder": text_of(tcmp_old), "morph_folder": m["folder"]}
        tpl = face_fit.pick_template(npc_recs, human, female)
        if tpl is None:
            raise SystemExit(f"no plain vanilla {sex} NPC to copy")
        for race, keys in [(None, [])] + list(m["keys_by_race"].items()):
            label = NAMES[race] if race else "Control"
            fid = ids.take(f"S2SRace_{label}_{sex}")
            subs = face_fit.with_face(list(tpl[2]), {})
            subs = sfplugin.edit(subs, {b"EDID": sfplugin.zs(f"S2SRace_{label}_{sex}"),
                                        b"FULL": sfplugin.zs(f"{label} {sex} (S2S race test)")},
                                 drop=face_fit.STRIP + face_fit.STRIP_GEAR)
            subs = face_fit.without_templates(subs)
            if no_outfit is not None:
                subs = sfplugin.edit(subs, {b"DOFT": struct.pack("<I", no_outfit),
                                            b"SOFT": struct.pack("<I", no_outfit)})
            subs = with_head_part(subs, h_fid, part_types)
            if not keep_hair:
                subs = without_hair(subs, part_types)
                cropped = short_hair(hdpts, part_types, female)
                if cropped is not None:
                    subs = subs + [(b"PNAM", struct.pack("<I", cropped[0]))]
                    rep.setdefault("hair", {})[sex] = cropped[1]
            if keys:
                subs = with_blends(subs, {k: 1.0 for k in keys})
            recs.append((b"NPC_", tpl[1], subs, fid))
            rep["npcs"].append({"race": race or "control", "sex": sex, "edid": f"S2SRace_{label}_{sex}",
                                "form_id": f"{fid:08X}", "template": sfplugin.edid(tpl[2]),
                                "template_form_id": f"{tpl[3]:08X}", "blends": len(keys),
                                "console": f"player.placeatme xx{fid & 0xFFFFFF:06X}  (xx = {PLUGIN}'s load order "
                                           f"index)"})
    race_fids, race_heads, part_copies = {}, {}, {}
    if new_races and human is not None:
        mann = next((s for t, _h, s, fid in recs_all if t == b"RACE" and sfplugin.edid(s) == "MannequinRace"), None)
        rep["new_races"] = {}
        for race in new_races:
            per = {f: {} for f in made}
            for f, m in made.items():
                for k in m["keys_by_race"].get(race, []):
                    per[f].setdefault(PHENO_KEY.match(k).group(4), []).append(k)
            if not any(per.values()) and race not in race_models:
                rep["new_races"][race] = {"note": "no keys (not in --races)"}
                continue
            rheads = heads
            if race in race_models:
                rheads, per = {}, {}
                for f, modl in race_models[race].items():
                    # the vanilla head part with only its model changed: its own (vanilla) morph record, so the
                    # race's chargen is exactly the human one on top of the baked shape
                    src_h = next(r for r in recs_all if r[0] == b"HDPT" and sfplugin.edid(r[2]) == HEAD_PART[f])
                    h_fid = ids.take(f"S2S_{NAMES[race]}Race_{SEXES[f]}_Head")
                    recs.append((b"HDPT", src_h[1], sfplugin.edit(list(src_h[2]), {
                        b"EDID": sfplugin.zs(f"S2S_{NAMES[race]}Race_{SEXES[f]}_Head"),
                        b"MODL": sfplugin.zs(modl)}), h_fid))
                    rheads[f] = h_fid
                    part_types[h_fid] = 1
                race_heads[race] = rheads
            r_fid = ids.take(f"S2S_{NAMES[race]}Race")
            rsubs, rrep = new_race((human, by_fid[human][2]), mann, NAMES[race], rheads, per, part_types)
            if heights and race in heights and HEIGHT_REFERENCE in heights:
                fac = tuple(heights[race][i] / (heights[HEIGHT_REFERENCE][i] or 1.0) for i in (0, 1))
                rsubs = with_heights(rsubs, fac)
                rrep["height_factor"] = {"male": round(fac[0], 4), "female": round(fac[1], 4)}
            if race in race_models:
                rrep["shape"] = "baked into its head model"
                rrep["head_parts"] = {SEXES[f]: {"HDPT": f"{h:08X}", "MODL": race_models[race][f]}
                                      for f, h in rheads.items()}
            if race_parts and race_parts.get(race):
                prs, copies, _l = race_part_records(recs_all, NAMES[race], r_fid, race_parts[race],
                                                    ids.take,
                                                    (mouths or {}).get(race))
                recs += prs
                rsubs = swap_race_heads(rsubs, copies)
                if mouth_on_head and race in race_models:
                    # 2026-11-11 test: the player shows no Orc mouth though every record names it; the head (ours on
                    # the player: the ears) brings it along as an extra part, as Skyrim's Orc head does
                    for f, h_fid in rheads.items():
                        mouth = next((c for v, c in copies.get(f, {}).items() if part_types.get(v) == 9), None)
                        k = next((i for i, r in enumerate(recs) if r[0] == b"HDPT" and r[3] == h_fid), None)
                        if mouth is not None and k is not None:
                            t_, h_, s_, f_ = recs[k]
                            recs[k] = (t_, h_, with_extra_part(s_, mouth), f_)
                            rrep.setdefault("mouth_on_head", {})[SEXES[f]] = f"{mouth:08X}"
                rsubs, prec = race_preset_copies(rsubs, npc_by, NAMES[race], r_fid, rheads, part_types, copies,
                                                 ids.take)
                recs += prec
                rrep["preset_copies"] = len(prec)
                part_copies[race] = copies
                rrep["face_parts"] = {SEXES[f]: len(set(c.values())) for f, c in copies.items()}
            recs.append((b"RACE", by_fid[human][1], rsubs, r_fid))
            race_fids[race] = r_fid
            rrep.update(form_id=f"{r_fid:08X}", edid=f"S2S_{NAMES[race]}Race", setrace=f"player.setrace xx{r_fid & 0xFFFFFF:06X}  (xx = {PLUGIN}'s "
                                                        f"load order index; then showlooksmenu player 1)")
            rep["new_races"][race] = rrep
        # an NPC of each new race and sex: the race test NPC with its race (RNAM) set to ours (also its chargen
        # face preset)
        race_npcs = {}
        for n in list(rep["npcs"]):
            race = next((r for r in race_fids if NAMES[r] == n["edid"].split("_")[1]), None)
            if race is None or n["race"] == "control":
                continue
            src = next(r for r in recs if r[0] == b"NPC_" and r[3] == int(n["form_id"], 16))
            edid = f"S2SRace_{NAMES[race]}Race_{n['sex']}"
            fid = ids.take(edid)
            subs = sfplugin.edit(list(src[2]), {b"EDID": sfplugin.zs(edid), b"RNAM": struct.pack("<I", race_fids[race]),
                                                b"FULL": sfplugin.zs(f"{NAMES[race]} {n['sex']} (S2S race)")})
            if race in race_heads:          # the shape is in the head: the race's head part, no race blends
                subs = with_head_part([x for x in subs if x[0] not in (b"BMPN", b"BMPV")],
                                      race_heads[race][n["sex"] == "female"], part_types)
            if race in part_copies:
                subs = swap_parts(subs, part_copies[race].get(n["sex"] == "female", {}))
            recs.append((b"NPC_", src[1], subs, fid))
            rep["npcs"].append(dict(n, edid=edid, form_id=f"{fid:08X}", race_record=f"S2S_{NAMES[race]}Race",
                                    blends=0 if race in race_heads else n["blends"],
                                    console=f"player.placeatme xx{fid & 0xFFFFFF:06X}  (xx = {PLUGIN}'s load order "
                                            f"index)"))
            race_npcs.setdefault(race, {}).setdefault(n["sex"] == "female", []).append(fid)
        for race, per in race_npcs.items():
            k = next(i for i, r in enumerate(recs) if r[0] == b"RACE" and r[3] == race_fids[race])
            t_, h_, rsubs, rf = recs[k]
            recs[k] = (t_, h_, add_presets(rsubs, per), rf)
            rep["new_races"][race]["presets"] = {SEXES[f]: [f"{x:08X}" for x in v] for f, v in per.items()}
        if race_fids:
            lists = head_part_race_lists(recs_all, human, list(race_fids.values()))
            for h_, s_, f_ in lists:
                recs.append((b"FLST", h_, s_, f_))
            rep["head_part_race_lists"] = [f"{sfplugin.edid(s_)} {f_:08X}" for _h, s_, f_ in lists]
            conds = race_condition_patches(recs_all, human, list(race_fids.values()))
            recs += conds
            rep["race_condition_patches"] = [f"{t_.decode()} {sfplugin.edid(s_)} {f_:08X}" for t_, _h, s_, f_ in conds]
        baked = {v for c in part_copies.values() for per in c.values() for v in per}
        if baked:
            ho = human_only_parts(recs_all, baked, ids.take)
            recs += ho
            rep["human_only_parts"] = len(ho) - 1
            co = chargen_option_lists(recs_all, part_copies)
            recs += co
            rep["chargen_option_lists"] = {sfplugin.edid(s_): sum(1 for x, _d in s_ if x == b"LNAM")
                                           for _t, _h, s_, _f in co}
        rep["_player_parts"] = (heads, part_types, next(((h_, s) for t, h_, s, fid in recs_all
                                                         if t == b"NPC_" and fid == 0x7), None), race_heads,
                                part_copies)
    if race_head and human is not None:
        _t, rh, rs = by_fid[human]
        rep["race_override"] = {"form_id": f"{human:08X}"}
        for female, m in made.items():
            rs, counts = race_override(rs, heads[female], m["keys_by_region"], part_types, female)
            rep["race_override"][SEXES[female]] = counts
        recs.append((b"RACE", rh, rs, human))
    return recs, info, rep


def bake_faces(npcs, sf_data, out):
    """The template's pre-built face textures under each test NPC's FormID, as face_fit does (2026-11-09, owner: the
    race NPCs, without them, came out dark red with light nose / lips / eyelids; the control, also without, was a
    plain light face: the runtime face texture follows the morph blends, and ours name no textures). The shape stays
    the runtime one (morph keys). Returns the count written per NPC."""
    import face_fit
    from fo4sf import ba2
    names = {}
    for fn in sorted(os.listdir(sf_data)):
        if fn.lower().startswith("starfield - textures") and fn.lower().endswith(".ba2"):
            names[fn] = ba2.Ba2(os.path.join(sf_data, fn)).names
    index = face_fit.baked_face_index(names)
    done = {}
    for n in npcs:
        tpl, fid = int(n["template_form_id"], 16), int(n["form_id"], 16)
        written = face_fit.write_baked_face(index, tpl, fid, sf_data, out, PLUGIN) if tpl in index else []
        n["baked_face_textures"] = [os.path.basename(p) for p in written]
        done[n["edid"]] = len(written)
    return done


# ----------------------------------------------------------------------------------------------------- main
def bsa_archives(skyrim_data):
    from fo4sf import bsa
    return bsa.SkyrimArchives(skyrim_data)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True, help="Starfield install folder")
    ap.add_argument("--out", required=True)
    ap.add_argument("--races", default=",".join(DEFAULT_RACES),
                    help=f"Skyrim races (at most 4 per file next to vanilla's keys); of {', '.join(CODES)}")
    ap.add_argument("--smooth", type=int, default=4, help="smoothing of the transferred shape (as race_probe)")
    ap.add_argument("--race-head", action="store_true",
                    help="also override HumanRace: our head part as its Face part, our keys in its morph groups")
    ap.add_argument("--force", action="store_true", help="write even if the frame check fails")
    ap.add_argument("--player-race", default="",
                    help="also write S2S<Name>Player.esm: the player record set to that new race (e.g. Orc), as the "
                         "Exo Race mod's player patch")
    ap.add_argument("--new-races", default="",
                    help="Skyrim races to also make a RACE of their own, thin over HumanRace, e.g. Orc (comma list; "
                         "with --race-shape blend each must be in --races; baked: any of the known races, 'all' for "
                         "every one)")
    ap.add_argument("--race-shape", choices=("baked", "blend"), default="baked",
                    help="new races (--new-races): their shape baked into a head model of their own, so every face "
                         "of the race has it and HumanRace's chargen works on top (default, 2026-11-10), or an extra "
                         "chargen blend option (the faces have to pick it)")
    ap.add_argument("--race-height", choices=("skyrim", "human"), default="skyrim",
                    help="new races' height: Skyrim's relative to its Imperial (default; Orc x1.045) or HumanRace's")
    ap.add_argument("--texconv", default="", help="texconv.exe for the converted mouths' textures (default: the "
                                                  "usual places; without it the race mouth uses the vanilla teeth "
                                                  "material)")
    ap.add_argument("--content-resources", default="", help="default <Starfield>/Tools/ContentResources.zip")
    ap.add_argument("--no-bake-parts", action="store_true",
                    help="--race-shape baked: no race copies of the face head parts (eyes, brows, beards, teeth, "
                         "lashes, jewelry); the race then uses HumanRace's (2026-11-10 default: baked copies)")
    ap.add_argument("--no-lip-edges", dest="lip_edges", action="store_false",
                    help="the race shapes' lips as transferred: without it the lips' meeting rows move like Skyrim's "
                         "visible lip edges (2026-11-10: the female Orc gaped where Skyrim's lips look closed)")
    ap.add_argument("--mouth-brightness", type=float, default=None,
                    help="the converted mouth texture's colour times this (default race_mouths.MOUTH_ALBEDO_GAIN; "
                         "1 = Skyrim's as is: 2026-11-11 the Orc teeth drew near black in Starfield's light)")
    ap.add_argument("--mouth-on-head", action="store_true",
                    help="test: the race's head part also carries its mouth as an extra part (HNAM), so whatever "
                         "head the game draws brings the mouth (2026-11-11: the player showed no Orc mouth)")
    ap.add_argument("--mouth-uv-test", action="store_true",
                    help="the mouth's colour texture replaced by four coloured quarters (red top-left, green "
                         "top-right, blue bottom-left, yellow bottom-right): the tusks sample the top half, so red / "
                         "green tusks in game = Skyrim's UVs read as they are, blue / yellow = flipped")
    ap.add_argument("--ear-fit", action="store_true",
                    help="first move Skyrim's ears onto Starfield's (race_probe.ear_fit; experimental, off by default: "
                         "on the owner's heads 2026-11-10 it matched the sides of the heads, not the ears)")
    ap.add_argument("--symmetry", choices=("stronger", "mean", "none"), default="stronger",
                    help="left / right: per vertex pair the side that moved more (default), their mean, or as "
                         "transferred")
    ap.add_argument("--keep-hair", action="store_true", help="keep the template's hair and beard (default: none, so "
                    "the ears and the sides of the face show)")
    ap.add_argument("--no-baked-face-textures", dest="baked_face_textures", action="store_false",
                    help="leave the NPCs without the template's pre-built face textures (the game builds them)")
    a = ap.parse_args(argv)
    races = [r.strip() for r in a.races.split(",") if r.strip()]
    bad = [r for r in races if r not in CODES]
    if bad:
        raise SystemExit(f"unknown race(s) {bad}; known: {', '.join(CODES)}")
    import face_fit
    import race_probe
    t0 = time.time()
    sf_data = os.path.join(a.starfield, "Data")
    sky = bsa_archives(a.skyrim_data)
    report = {"races": races, "sexes": {}}
    made = {}
    for female in (False, True):
        sex = SEXES[female]
        data, rel = face_fit.hkx_to_af.vanilla_file(race_probe.SF_MORPH.format(sex=sex, part="head"), sf_data)
        morph = sfmorph.parse(data)
        head, _base, _races, _al, disp, trep = race_probe.race_transfer(sky, sf_data, female, a.smooth, face_fit,
                                                                          lip_edges=a.lip_edges, ears=a.ear_fit)
        align = tuple(_al[:3]) if _al is not None else None
        if a.symmetry != "none":
            # 2026-11-09 (owner: one ear looked better than the other on every NPC, the other side for each sex):
            # the transfer lost the point on one side; Skyrim's race heads are symmetric. "stronger" keeps, per
            # vertex pair, the side that moved more (the mean gave half-pointed ears)
            ax = facefit.lateral_axis(head.vertices)
            disp = {r: facefit.symmetrize(np.asarray(d, float), head.vertices, ax, a.symmetry,
                                          faces=head.triangles)
                    for r, d in disp.items()}
        nv = len(head.vertices)
        if morph.num_vertices != nv:
            raise SystemExit(f"{sex}: head morph.dat has {morph.num_vertices} vertices, the head mesh {nv}")
        fc = frame_check(morph, head.vertices, head.triangles)
        srep = {"vanilla_morph": rel, "vanilla_keys": len(morph.keys), "frame_check_overweight_outward": fc,
                "transfer": trep.get("transfer"), "alignment_rms_m": trep["alignment"]["rms_m"],
                "lip_edges": trep.get("lip_edges"), "ears": trep.get("ears")}
        report["sexes"][sex] = srep
        print(f"{sex}: vanilla head morph {len(morph.keys)} keys; frame check (Overweight outward) {fc}")
        print(f"  ears: {trep.get('ears')}")
        if fc is not None and fc < 0.7 and not a.force:
            raise SystemExit(f"{sex}: the vanilla Overweight key points outward on only {fc:.0%} of its vertices: the "
                             f"morph.dat frame may differ from the head's; nothing written (--force to write anyway)")
        regions, W = region_weights(morph, head.triangles, nv)
        W = weld_weights(W, head.vertices)
        srep["regions"] = regions
        srep["weight_share"] = {r: round(float(W[:, i].sum() / nv), 3) for i, r in enumerate(regions)}
        keys, deltas, extra = list(morph.keys), dict(morph.deltas), dict(morph.extra)
        neutral = neutral_extra(morph)
        srep["new_key_words"] = [f"{w:08X}" for w in neutral]
        by_race, by_region = {}, {r: [] for r in regions}
        for race in races:
            if race not in disp:
                srep.setdefault("missing", []).append(race)
                continue
            rk = race_keys(sex, race, disp[race], regions, W)
            whole = disp[race]
            summed = np.zeros_like(whole)
            for k, dd in rk.items():
                for v, d in dd.items():
                    summed[v] += d
            srep.setdefault("races", {})[race] = {
                "max_m": round(float(np.linalg.norm(whole, axis=1).max()), 4),
                "split_error_max_m": round(float(np.abs(summed - whole).max()), 6),
                "keys": {k: len(dd) for k, dd in rk.items()}}
            for k, dd in rk.items():
                keys.append(k)
                deltas[k] = dd
                by_region[PHENO_KEY.match(k).group(4)].append(k)
            by_race[race] = list(rk)
        if len(keys) > MAX_KEYS:
            raise SystemExit(f"{sex}: {len(keys)} keys > {MAX_KEYS}; give fewer --races")
        folder = tcmp_folder(vanilla_head_tcmp(os.path.join(sf_data, "Starfield.esm"), female), sex)
        made[female] = {"folder": folder, "keys_by_race": by_race, "keys_by_region": by_region,
                        "vertices": np.asarray(head.vertices, float), "disp": disp}
        if align is not None:
            made[female]["align"] = align
        rel_out = folder.replace("\\", "/").lower() + "/morph.dat"
        path = os.path.join(a.out, *rel_out.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(sfmorph.build(morph.num_vertices, keys, deltas, extra, version=morph.version,
                                   default_extra=neutral))
        srep.update(keys=len(keys), morph_file=rel_out)
        print(f"  {len(keys)} keys -> {rel_out}")
        for race, x in srep.get("races", {}).items():
            le = (srep.get("lip_edges") or {}).get(race) or {}
            op = le.get("visible_opening_m") or {}
            lips = (f"; lips open {op['before'] * 1000:.1f} -> {op['after'] * 1000:.1f} mm (Skyrim "
                    f"{op['skyrim_before'] * 1000:.1f} -> {op['skyrim_after'] * 1000:.1f})") if op else ""
            print(f"  {race}: max {x['max_m']:.3f} m, split error {x['split_error_max_m']:.6f} m{lips}")
    wanted = race_names(a.new_races)
    models, rparts, mouths = None, None, None
    if wanted and a.race_shape == "baked":
        models, rparts, report["baked_heads"], mouths, report["mouths"] = write_race_heads(
            sf_data, a.out, made, wanted, not a.no_bake_parts, sky, (a.starfield, a.texconv, a.content_resources),
            a.mouth_brightness, a.mouth_uv_test)
        for race, per in report["baked_heads"].items():
            for sex, x in per.items():
                print(f"  {race} {sex}: shape baked into {x['model']} ({x['files']} files; _facebones twin: "
                      f"{'yes' if x.get('facebones_twin') else 'NOT FOUND'})")
    heights = {}
    sky_esm = os.path.join(a.skyrim_data, "Skyrim.esm")
    if wanted and a.race_height == "skyrim" and os.path.isfile(sky_esm):
        heights = skyrim_heights(sky_esm, wanted)
        report["skyrim_heights"] = {r: [round(x, 3) for x in h] for r, h in heights.items()}
    ids = FormIds(os.path.join(a.out, LEDGER))       # stable FormIDs across rebuilds (saved games)
    strings = load_lstrings(sf_data)
    report["localized_strings"] = {k: len(v) for k, v in strings.items()}
    if not strings:
        print("  WARNING: no Starfield string tables found: copied names stay string ids (garbled in game)")
    recs, info, prep = build_plugin(os.path.join(sf_data, "Starfield.esm"), made, a.race_head, a.keep_hair,
                                    wanted, models, strings, rparts, heights, mouths, ids, a.mouth_on_head)
    ids.save()
    report["formids"] = {"ledger": os.path.join(a.out, LEDGER), "new": ids.new}
    report.update(prep)
    if a.baked_face_textures:
        report["baked_faces"] = bake_faces(report["npcs"], sf_data, a.out)
    with open(os.path.join(a.out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build(recs, info, author="Skyrim2Starfield races", masters=["Starfield.esm"]))
    parts = report.pop("_player_parts", None)
    if a.player_race:
        race = race_names(a.player_race)[0]
        r = (report.get("new_races") or {}).get(race)
        if r is None or "form_id" not in r or parts is None or parts[2] is None:
            print(f"  player patch: {race} not built (needs --new-races {a.player_race}) or no Player record")
        else:
            heads_, part_types_, player, race_heads_, part_copies_ = parts
            heads_ = race_heads_.get(race, heads_)
            pcopies = {f: {v: (c & 0xFFFFFF) | 0x01000000 for v, c in per.items()}
                       for f, per in part_copies_.get(race, {}).items()}
            # our plugin's own forms are 01xxxxxx (master 0 Starfield.esm); in the patch S2SRaceTest.esm is master 1
            race_fid = (int(r["form_id"], 16) & 0xFFFFFF) | 0x01000000
            pheads = {f: (h & 0xFFFFFF) | 0x01000000 for f, h in heads_.items()}
            psubs = player_patch(player[1], race_fid, pheads, part_types_, pcopies)
            name = f"S2S{NAMES[race]}Player.esm"
            with open(os.path.join(a.out, name), "wb") as fh:
                fh.write(sfplugin.build([(b"NPC_", player[0], psubs, 0x7)], info,
                                        author="Skyrim2Starfield races", masters=["Starfield.esm", PLUGIN]))
            report["player_patch"] = {"plugin": name, "race": f"S2S_{NAMES[race]}Race"}
            print(f"  player patch: {name} (load it after {PLUGIN}; the player starts as S2S_{NAMES[race]}Race)")
    with open(os.path.join(a.out, "race_heads.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print("  hair on the test NPCs:", report.get("hair") or "none cropped found (the race's default; --keep-hair: "
          "the template's)")
    for n in report["npcs"]:
        print(f"  {n['edid']}: {n['console']}")
    for race, r in (report.get("new_races") or {}).items():
        print(f"  race {race}: {r.get('setrace') or r.get('note')}")
    print(f"-> {os.path.join(a.out, PLUGIN)}, race_heads.json ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
