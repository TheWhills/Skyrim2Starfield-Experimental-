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


def build_plugin(sf_esm, made, race_head=False, keep_hair=False):
    """made: {female: {"folder", "keys_by_race": {race: [keys]}, "keys_by_region": {region: [keys]}}}.
    Returns (records, info, report)."""
    import face_fit
    info = sfplugin.header_info(sf_esm)
    recs_all = sfplugin.records(sf_esm, [b"HDPT", b"MRPH", b"RACE", b"NPC_", b"OTFT"])
    by_fid = {fid: (t, h, s) for t, h, s, fid in recs_all}
    part_types = {fid: _u32(dict(s).get(b"PNAM", b"\0\0\0\0")) for t, h, s, fid in recs_all if t == b"HDPT"}
    hdpts = {fid: s for t, h, s, fid in recs_all if t == b"HDPT"}
    human = next((fid for t, _h, s, fid in recs_all if t == b"RACE" and sfplugin.edid(s) == "HumanRace"), None)
    npc_recs = [r for r in recs_all if r[0] == b"NPC_"]
    masters = 1
    nxt = iter(range(10 ** 6))
    recs, rep = [], {"npcs": [], "head_parts": {}}
    otft = next((r for r in recs_all if r[0] == b"OTFT"), None)
    no_outfit = None
    if otft is not None:
        no_outfit = sfplugin.new_form_id(next(nxt), masters)
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
        m_fid = sfplugin.new_form_id(next(nxt), masters)
        tcmp_old = dict(mrph[2]).get(b"TCMP", b"")
        msubs = sfplugin.edit(list(mrph[2]), {b"EDID": sfplugin.zs(f"S2S_SkyrimRaces_{sex}_HeadMorph"),
                                              b"TCMP": os_export.replace_text(tcmp_old, m["folder"])})
        recs.append((b"MRPH", mrph[1], msubs, m_fid))
        h_fid = sfplugin.new_form_id(next(nxt), masters)
        hsubs = sfplugin.edit(list(part[2]), {b"EDID": sfplugin.zs(f"S2S_SkyrimRaces_{sex}_Head"),
                                              b"MNAM": struct.pack("<I", m_fid)})
        recs.append((b"HDPT", part[1], hsubs, h_fid))
        heads[female] = h_fid
        rep["head_parts"][sex] = {"HDPT": f"{h_fid:08X}", "MRPH": f"{m_fid:08X}", "template": HEAD_PART[female],
                                  "template_morph_folder": text_of(tcmp_old), "morph_folder": m["folder"]}
        tpl = face_fit.pick_template(npc_recs, human, female)
        if tpl is None:
            raise SystemExit(f"no plain vanilla {sex} NPC to copy")
        for race, keys in [(None, [])] + list(m["keys_by_race"].items()):
            fid = sfplugin.new_form_id(next(nxt), masters)
            label = NAMES[race] if race else "Control"
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
    ap.add_argument("--no-symmetry", action="store_true", help="keep the transfer's left / right differences")
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
        head, _base, _races, _al, disp, trep = race_probe.race_transfer(sky, sf_data, female, a.smooth, face_fit)
        if not a.no_symmetry:
            # 2026-11-09 (owner: one ear looked better than the other on every NPC, the other side for each sex):
            # the transfer's left / right noise; Skyrim's race heads are symmetric
            ax = facefit.lateral_axis(head.vertices)
            disp = {r: facefit.symmetrize(np.asarray(d, float), head.vertices, ax) for r, d in disp.items()}
        nv = len(head.vertices)
        if morph.num_vertices != nv:
            raise SystemExit(f"{sex}: head morph.dat has {morph.num_vertices} vertices, the head mesh {nv}")
        fc = frame_check(morph, head.vertices, head.triangles)
        srep = {"vanilla_morph": rel, "vanilla_keys": len(morph.keys), "frame_check_overweight_outward": fc,
                "transfer": trep.get("transfer"), "alignment_rms_m": trep["alignment"]["rms_m"]}
        report["sexes"][sex] = srep
        print(f"{sex}: vanilla head morph {len(morph.keys)} keys; frame check (Overweight outward) {fc}")
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
        made[female] = {"folder": folder, "keys_by_race": by_race, "keys_by_region": by_region}
        rel_out = folder.replace("\\", "/").lower() + "/morph.dat"
        path = os.path.join(a.out, *rel_out.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(sfmorph.build(morph.num_vertices, keys, deltas, extra, version=morph.version,
                                   default_extra=neutral))
        srep.update(keys=len(keys), morph_file=rel_out)
        print(f"  {len(keys)} keys -> {rel_out}")
        for race, x in srep.get("races", {}).items():
            print(f"  {race}: max {x['max_m']:.3f} m, split error {x['split_error_max_m']:.6f} m")
    recs, info, prep = build_plugin(os.path.join(sf_data, "Starfield.esm"), made, a.race_head, a.keep_hair)
    report.update(prep)
    if a.baked_face_textures:
        report["baked_faces"] = bake_faces(report["npcs"], sf_data, a.out)
    with open(os.path.join(a.out, PLUGIN), "wb") as fh:
        fh.write(sfplugin.build(recs, info, author="Skyrim2Starfield races", masters=["Starfield.esm"]))
    with open(os.path.join(a.out, "race_heads.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print("  hair on the test NPCs:", report.get("hair") or "none cropped found (the race's default; --keep-hair: "
          "the template's)")
    for n in report["npcs"]:
        print(f"  {n['edid']}: {n['console']}")
    print(f"-> {os.path.join(a.out, PLUGIN)}, race_heads.json ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
