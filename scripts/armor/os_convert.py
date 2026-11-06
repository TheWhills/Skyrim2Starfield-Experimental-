"""A Skyrim NPC's outfit onto Starfield's body with Outfit Studio (owner 2026-11-06: clothing next, Ralof first).

The route is Outfit Studio's own guides ("Converting models from other programs", "Converting between games";
docs/ai/decisions.md 2026-11-06): there is no Skyrim -> Starfield conversion reference, so the Skyrim gear is
treated like an outside model, with the Skyrim body it was made on as its guide.

Skyrim side (here): the NPC's default outfit (DOFT) -> its items (OTFT INAM; levelled lists LVLI followed to their
first entry) -> each armor's addon (ARMA) for the NPC's race and sex -> the worn .nif (the heavier _1 when the weight
slider is on), extracted with the matching Skyrim body into --work.

Outfit Studio side (its MCP server, Starfield as target game, Starfield skeleton loaded; os_probe / os_skeleton):
  new_project -> load Starfield's naked body from the archives, set it as the reference -> import_from_game the
  Skyrim body and the gear -> scale_to_body (measured on the Skyrim body) -> fit_pose_to_shapes -> unpose_shapes
  (Skyrim's pose and proportions to Starfield's rest pose) -> fit_to_body (stiff, keeping each vertex's gap to the
  old Skyrim body) -> delete the Skyrim body -> copy_bone_weights from the Starfield body -> validate_project ->
  render_view (front / left / back) -> export_file the gear as a Starfield NIF into --out.

Not yet: body sliders (morph.dat), materials, the plugin records. Every call's result is saved under --out\\calls
and report.txt lists them; the run stops at the first failed step.

    python -I scripts\\armor\\os_convert.py --skyrim-data "<Skyrim>\\Data" --npc Ralof --work C:\\Modding\\work\\os_convert --out C:\\Modding\\work\\os_convert\\out
"""
import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from fo4sf import bsa, sfplugin, skyrimarmor, skyrimnpc  # noqa: E402
import os_probe  # noqa: E402

SF_BODY = {False: "meshes/actors/human/mesh/naked_body/naked_m.nif",
           True: "meshes/actors/human/mesh/naked_body/naked_f.nif"}
SKYRIM_BODY = {False: "meshes\\actors\\character\\character assets\\malebody_1.nif",
               True: "meshes\\actors\\character\\character assets\\femalebody_1.nif"}


# ------------------------------------------------------------------------------------------------------ Skyrim side
def outfit_armor(esm: str, npc_edid: str) -> dict:
    """{"npc": parsed NPC, "race": race EditorID, "armor": [ARMO FormIDs]} of a Skyrim NPC's default outfit."""
    npcs = {fid: skyrimnpc.parse_npc(s, fid) for _t, _h, s, fid in sfplugin.records(esm, [b"NPC_"])}
    n = next((v for v in npcs.values() if v["edid"].lower() == npc_edid.lower()), None)
    if n is None:
        raise SystemExit(f"no NPC {npc_edid} in {esm}")
    races = {fid: sfplugin.edid(s) for _t, _h, s, fid in sfplugin.records(esm, [b"RACE"])}
    recs = {fid: (t, s) for t, _h, s, fid in sfplugin.records(esm, [b"OTFT", b"LVLI", b"ARMO"])}
    items = []
    if n.get("outfit") in recs:
        _t, subs = recs[n["outfit"]]
        for sig, d in subs:
            if sig == b"INAM":
                d = bytes(d)
                items += [struct.unpack_from("<I", d, i)[0] for i in range(0, len(d) - 3, 4)]
    armor, seen = [], set()

    def follow(fid, depth=0):
        if fid in seen or depth > 8 or fid not in recs:
            return
        seen.add(fid)
        typ, subs = recs[fid]
        if typ == b"ARMO":
            armor.append(fid)
        elif typ == b"LVLI":
            first = next((bytes(d) for s, d in subs if s == b"LVLO" and len(d) >= 8), None)
            if first:
                follow(struct.unpack_from("<I", first, 4)[0], depth + 1)
    for fid in items:
        follow(fid)
    return {"npc": n, "race": races.get(n.get("race"), ""), "armor": armor}


def worn_meshes(inv: dict, armor_fids, race_edid: str, female: bool) -> list:
    """[{"armor", "addon", "slots", "mesh"}]: per armor the addon for the race (else the first addon), its worn model
    for the sex (the _1 variant when the weight slider names both)."""
    out = []
    for fid in armor_fids:
        a = inv["armo"].get(fid)
        if not a:
            continue
        addons = [inv["arma"][x] for x in a["addons"] if x in inv["arma"]]
        fit = [m for m in addons if race_edid and (m["race"] == race_edid or race_edid in m["extra_races"])]
        m = (fit or addons or [None])[0]
        if m is None:
            continue
        path = m["female"] if female and m["female"] else m["male"]
        if not path:
            continue
        if path.lower().endswith("_0.nif"):
            path = path[:-6] + "_1.nif"
        out.append({"armor": a["edid"], "addon": m["edid"], "slots": a["slots"], "mesh": "meshes\\" + path})
    return out


def extract(sky, paths, work: str) -> dict:
    """{archive path: file on disk} of the files copied out of Skyrim's archives into work\\skyrim."""
    out = {}
    for p in paths:
        data = sky._read(bsa.norm(p))
        if data is None:
            raise SystemExit(f"not in Skyrim's archives: {p}")
        dst = os.path.join(work, "skyrim", *p.replace("/", "\\").split("\\"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
        out[p] = dst
    return out


# ----------------------------------------------------------------------------------------------- Outfit Studio side
def _text(res) -> str:
    return " ".join(c.get("text", "") for c in (res or {}).get("content") or [] if c.get("type") == "text")


def _json(res):
    try:
        return json.loads(_text(res))
    except ValueError:
        return {}


class StepFailed(RuntimeError):
    pass


class Session:
    """Runs tool calls, saving each result (os_probe.save_result) and stopping at the first error."""

    def __init__(self, client, out: str):
        self.client, self.out, self.n, self.rows = client, out, 0, []

    def __call__(self, _tool: str, **args):
        self.n += 1
        try:
            res = self.client.call(_tool, args)
        except os_probe.McpError as e:
            self.rows.append({"call": f"{self.n:02d}_{_tool}", "error": True, "text": str(e)})
            raise StepFailed(_tool) from e
        row = os_probe.save_result(self.out, self.n, _tool, res)
        self.rows.append(row)
        if row["error"]:
            raise StepFailed(_tool)
        return _json(res)

    def shapes(self) -> list:
        return [s["name"] for s in self("list_shapes").get("shapes", [])]


def bounds(s, shape: str):
    """(min, max) of a shape as list_shapes reports it."""
    for row in s("list_shapes").get("shapes", []):
        if row.get("name") == shape and row.get("bounds"):
            return row["bounds"]["min"], row["bounds"]["max"]
    return None


def unweighted(validate) -> dict:
    """{shape: count} of validate_project's "unweighted" errors."""
    return {e.get("shape"): e.get("count") for e in (validate or {}).get("errors", [])
            if e.get("check") == "unweighted" and e.get("shape")}


def union(bs):
    bs = [b for b in bs if b]
    if not bs:
        return None
    return ([min(b[0][i] for b in bs) for i in range(3)], [max(b[1][i] for b in bs) for i in range(3)])


def overlaps(a, b, share: float = 0.5) -> bool:
    """Whether a's height range covers at least `share` of b's (both (min, max))."""
    if not a or not b:
        return False
    lo, hi = max(a[0][2], b[0][2]), min(a[1][2], b[1][2])
    return hi - lo >= share * (b[1][2] - b[0][2])


def convert(client, body_nif: str, gear_nifs: list, female: bool, out: str, name: str) -> dict:
    """The Outfit Studio half (module docstring). Returns {"steps": [...], "gear": [shape names], "exported": path}."""
    s = Session(client, out)
    rep = {"steps": s.rows}
    try:
        s("new_project", discardChanges=True)
        loaded = s("load_from_archive", files=[SF_BODY[female]], mode="import")
        sf_body = next((n for f in loaded.get("loaded", []) for n in f.get("shapes", [])), None) or s.shapes()[0]
        s("set_reference_shape", shape=sf_body)
        # 2026-11-06: Starfield's body sits at z -113 .. -6 in its own mesh space and is drawn standing only through
        # its skin transform. That raw space is where the game skins it, so the Skyrim gear is fitted there (the
        # first run's fit_to_body found the body right beside the gear) and later takes the body's skin transform
        # (copy_bone_weights copySkinTransform). Baking the node transform (second run) moved it 1.6 units: not it.
        rep["body_bounds"] = bounds(s, sf_body)
        before = set(s.shapes())
        s("import_from_game", file=body_nif)
        old_body = [n for n in s.shapes() if n not in before]
        before = set(s.shapes())
        for nif in gear_nifs:
            s("import_from_game", file=nif)
        gear = [n for n in s.shapes() if n not in before]
        rep["gear"], rep["old_body"] = gear, old_body
        if not gear:
            raise StepFailed("import_from_game brought in no gear shapes")
        figure = old_body + gear
        s("snapshot_save", name="imported")
        s("scale_to_body", shapes=figure, targets=old_body or gear)
        rep["figure_bounds"] = union([bounds(s, n) for n in figure])
        if not overlaps(rep["figure_bounds"], rep["body_bounds"]):
            raise StepFailed(f"the scaled Skyrim figure {rep['figure_bounds']} does not overlap the body "
                             f"{rep['body_bounds']}")
        s("fit_pose_to_shapes", targets=old_body or gear)
        s("unpose_shapes", shapes=figure, rigidParts=True)
        s("snapshot_save", name="unposed")
        fit = dict(shapes=gear, stiffness=4, clippingPasses=1, rigidParts=True)
        if old_body:
            fit.update(gapMode="fromShape", gapFrom=old_body)
        s("fit_to_body", **fit)
        if old_body:
            s("delete_shapes", shapes=old_body)
        # the gear takes the body's skin transform, its vertices stay where they were fitted (same raw space)
        s("copy_bone_weights", shapes=gear, copySkinTransform=True, transformGeometry=False)
        rep["validate"] = s("validate_project", shapes=gear)
        # 2026-11-06 third run: 66 (cloak hem) + 51 (boot tips) vertices were beyond the default 10-unit search;
        # Outfit Studio's hint: copy again with a larger proximityRadius (a long dress needed 25)
        loose = unweighted(rep["validate"])
        if loose:
            s("copy_bone_weights", shapes=sorted(loose), copySkinTransform=True, transformGeometry=False,
              proximityRadius=25)
            rep["validate"] = s("validate_project", shapes=gear)
        s("render_view", views=["front", "left", "back"], grid=True, width=1024, height=1024)
        path = os.path.join(out, name + ".nif")
        s("export_file", path=path, shapes=gear, overwrite=True)
        rep["exported"] = path
        # export_file kept the imported Skyrim shape types (Gamebryo 20.2.0.7, NiTriShape, BSShaderPPLighting): not a
        # Starfield NIF. BodySlide's build writes the target game's format, so save the set and build it.
        display = f"S2S {name}"
        s("save_project", sliderSetFile=f"S2S_{name}.osp", displayName=display, outputFileName=name,
          outputDataPath=f"meshes\\S2S\\{name}", shapeDataFolder=f"S2S_{name}", shapeDataFile=f"{name}.nif",
          copyReference=False, overwrite=True)
        built = s("build_outfits", outfits=[display], targetDir=os.path.join(out, "build"))
        rep["built"] = built
    except StepFailed as e:
        rep["failed_at"] = str(e)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--npc", required=True, help="Skyrim NPC EditorID (its default outfit is converted)")
    ap.add_argument("--work", required=True, help="a folder for the extracted Skyrim files")
    ap.add_argument("--out", required=True, help="a folder for Outfit Studio's results (outside the repository)")
    ap.add_argument("--url", default=os_probe.DEFAULT_URL)
    ap.add_argument("--token", default="")
    a = ap.parse_args(argv)
    for p in (a.work, a.out):
        if os.path.abspath(p).lower().startswith(os.path.abspath(REPO).lower()):
            sys.exit("--work / --out must be outside the repository")
    os.makedirs(a.out, exist_ok=True)
    esm = os.path.join(a.skyrim_data, "Skyrim.esm")
    o = outfit_armor(esm, a.npc)
    female = o["npc"]["female"]
    meshes = worn_meshes(skyrimarmor.read_armor(esm), o["armor"], o["race"], female)
    if not meshes:
        sys.exit(f"{a.npc}: no worn armor meshes in the default outfit")
    sky = bsa.SkyrimArchives(a.skyrim_data)
    files = extract(sky, [m["mesh"] for m in meshes] + [SKYRIM_BODY[female]], a.work)
    print(f"{a.npc} ({o['race']}, {'female' if female else 'male'}):",
          *[f"{m['armor']} [{', '.join(map(skyrimarmor.slot_label, m['slots']))}] {m['mesh']}" for m in meshes],
          sep="\n  ")
    client = os_probe.Client(a.url, a.token)
    client.initialize()
    rep = convert(client, files[SKYRIM_BODY[female]], [files[m["mesh"]] for m in meshes], female, a.out,
                  f"{a.npc}_outfit")
    rep.update(npc=a.npc, race=o["race"], female=female, meshes=meshes)
    with open(os.path.join(a.out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    with open(os.path.join(a.out, "report.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(f"{r['call']}: {'ERROR ' if r['error'] else ''}{r['text']}" for r in rep["steps"]) + "\n")
    print("failed at:", rep["failed_at"]) if "failed_at" in rep else print("exported:", rep.get("exported"))
    print("report:", os.path.join(a.out, "report.txt"))
    return 0 if "failed_at" not in rep else 1


if __name__ == "__main__":
    sys.exit(main())
