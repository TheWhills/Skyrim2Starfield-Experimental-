"""Skyrim's forge sounds as Wwise events Starfield can play from an animation (docs/npc/furniture.md, sounds).

2026-11-20 (owner's probes, verified): an animation's SoundPlay payload is a Wwise event NAME (the game hashes it,
FNV-1 32 of the lower-case name: WPNGrenadeThrow is event 2467229328 in Starfield_WPN). Skyrim's forge clips carry
SoundPlay.<SOUN EditorID> (NPCHumanBlacksmithHammer ...). So each Skyrim sound becomes a Wwise event of that same
name, made in the Creation Kit's own Wwise project (<Starfield>\\Tools\\wwise\\Starfield\\Starfield.wproj, Wwise
v2021.1.10; the owner has 2021.1.14, as used for the voices), and put in Starfield_XXX_Scratch - a bank the game ships
empty (1490023241.bnk) - so our generated bank replaces nothing that plays.

On the owner's PC (needs Wwise and `pip install waapi-client`):
    python -I scripts\\armor\\sound_bank.py --skyrim-data "<Skyrim>\\Data" --starfield "<Starfield>" ^
        --work C:\\Modding\\work\\sound_bank --mod "<MO2 mods>\\S2S Sounds"

Steps: (1) Skyrim's files for each event (sound_records.skyrim_sound_files) -> work\\wav\\<event>\\*.wav (xWMA through
ffmpeg); (2) the Wwise project copied to work\\project (Bethesda's stays untouched); (3) WwiseConsole waapi-server on
the copy; over WAAPI: a random container per event, made next to a vanilla NPC furniture sound's container
(--template-event, default NPC_Human_FoodStation_Drawer_Close: it inherits that parent's bus, attenuation and
conversion), the .wav files imported into it (not streamed: the media goes in the bank), an Event of the Skyrim name
playing it, the events added to the bank; project saved; (4) WwiseConsole generate-soundbank for that bank (Windows);
(5) the .bnk copied to <mod>\\Sound\\Soundbanks and checked (wwise_probe.parse_bank: our events' ids present).
"""
import argparse
import json
import ntpath
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))
sys.path.insert(0, HERE)

import wwise_probe as WP  # noqa: E402

WWISE_CONSOLE = r"C:\Audiokinetic\Wwise_2021.1.14.8108\Authoring\x64\Release\bin\WwiseConsole.exe"
# Skyrim's forge clip sounds (smithing_probe), one-shots; OBJBlacksmithForge (the fire's loop) left out: a loop needs a
# stop event and an emitter, not an animation trigger
EVENTS = ("NPCHumanBlacksmithHammer", "NPCHumanBlacksmithHammerDistant", "NPCHumanBlacksmithForgeQuench",
          "NPCHumanBlacksmithForgeQuenchDrop", "NPCHumanBlacksmithForgeTake")
BANK = "Starfield_XXX_Scratch"
TEMPLATE_EVENT = "NPC_Human_FoodStation_Drawer_Close"
ACTION_PLAY = 1
RANDOM = 1


def wav_kind(data: bytes) -> str:
    """'pcm' (RIFF WAVE), 'xwma' (RIFF XWMA, needs ffmpeg) or 'unknown'."""
    if len(data) >= 12 and data[:4] == b"RIFF":
        return {b"WAVE": "pcm", b"XWMA": "xwma"}.get(data[8:12], "unknown")
    return "unknown"


def file_stem(event: str, path: str) -> str:
    return f"{event}_{os.path.splitext(os.path.basename(path.replace(chr(92), '/')))[0]}"


def container_args(parent_id: str, event: str) -> dict:
    return {"parent": parent_id, "type": "RandomSequenceContainer", "name": f"S2S_{event}",
            "onNameConflict": "replace", "@RandomOrSequence": RANDOM}


def import_args(container_path: str, wavs) -> dict:
    return {"importOperation": "replaceExisting", "default": {"importLanguage": "SFX"},
            "imports": [{"audioFile": w, "objectPath": f"{container_path}\\<Sound SFX>{os.path.splitext(ntpath.basename(w))[0]}",
                         "originalsSubFolder": "S2S"} for w in wavs]}


def event_args(event: str, container_path: str, parent="\\Events\\Default Work Unit") -> dict:
    return {"parent": parent, "type": "Event", "name": event, "onNameConflict": "replace",
            "children": [{"name": "", "type": "Action", "@ActionType": ACTION_PLAY, "@Target": container_path}]}


def inclusion_args(bank_path: str, event_ids) -> dict:
    return {"soundbank": bank_path, "operation": "add",
            "inclusions": [{"object": i, "filter": ["events", "structures", "media"]} for i in event_ids]}


def find_bank_file(generated_dir: str, bank: str):
    """The generated bank: <id>.bnk (Starfield names banks by id) or <name>.bnk, newest first."""
    want = {f"{WP.fnv1_32(bank)}.bnk", f"{bank}.bnk".lower()}
    hits = []
    for root, _d, files in os.walk(generated_dir):
        hits += [os.path.join(root, f) for f in files if f.lower() in want]
    return max(hits, key=os.path.getmtime) if hits else None


def extract(sky_data, events, wav_dir, ffmpeg=None) -> dict:
    import sound_records as SR
    got = SR.skyrim_sound_files(sky_data, events)
    out = {}
    for ev, files in got.items():
        d = os.path.join(wav_dir, ev)
        os.makedirs(d, exist_ok=True)
        out[ev] = []
        for path, data in files:
            if data is None:
                print(f"  {ev}: {path} not found")
                continue
            dst = os.path.join(d, file_stem(ev, path) + ".wav")
            kind = wav_kind(data)
            if kind == "pcm":
                with open(dst, "wb") as fh:
                    fh.write(data)
            elif kind == "xwma" and ffmpeg:
                src = dst + ".xwm"
                with open(src, "wb") as fh:
                    fh.write(data)
                subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", src, "-acodec", "pcm_s16le", dst])
                os.remove(src)
            else:
                print(f"  {ev}: {path} is {kind} (xWMA needs --ffmpeg)")
                continue
            if os.path.isfile(dst):
                out[ev].append(dst)
    return out


def waapi_client():
    """waapi-client's WaapiClient, or exit with how to install it (2026-11-20, owner: `pip` not on PATH)."""
    try:
        from waapi import WaapiClient
    except ImportError:
        sys.exit("waapi-client is not installed: python -m pip install waapi-client")
    return WaapiClient


class Waapi:
    def __init__(self, url, timeout=180):
        WaapiClient = waapi_client()
        t0, err = time.time(), None
        while time.time() - t0 < timeout:
            try:
                self.c = WaapiClient(url=url)
                return
            except Exception as e:                          # noqa: BLE001  (server still loading the project)
                err = e
                time.sleep(3)
        raise RuntimeError(f"no WAAPI server at {url}: {err}")

    def call(self, uri, args=None, options=None):
        r = self.c.call(uri, args or {}, options=options or {})
        if r is None:
            raise RuntimeError(f"{uri} failed: {json.dumps(args)[:300]}")
        return r

    def get(self, waql, ret=("id", "name", "path", "type")):
        return self.call("ak.wwise.core.object.get", {"waql": waql}, {"return": list(ret)}).get("return", [])

    def close(self):
        self.c.disconnect()


def build(w: "Waapi", wavs: dict, template_event: str, bank: str) -> dict:
    tpl = w.get(f'$ from type Event where name = "{template_event}" select children', ("id", "name", "@Target"))
    target = next((a["@Target"] for a in tpl if a.get("@Target")), None)
    if not target:
        raise RuntimeError(f"template event {template_event}: no action target")
    tgt = w.get(f'$ "{target["id"]}"')[0]
    # the nearest Actor-Mixer above the template's sound (2026-11-20, owner's run: its direct parent was
    # NPC_Human_FoodStation_LeftSide, which may be a container): ours sit beside its children and inherit its settings
    parent = w.get(f'$ "{target["id"]}" select parent')[0]
    for _ in range(12):
        if parent["type"] == "ActorMixer":
            break
        up = w.get(f'$ "{parent["id"]}" select parent')
        if not up or up[0]["type"] in ("WorkUnit", "Folder"):
            break
        parent = up[0]
    rep = {"template": {"event": template_event, "target": tgt["path"], "parent": parent["path"],
                        "parent_type": parent["type"]}, "events": {}}
    banks = w.get(f'$ from type SoundBank where name = "{bank}"')
    rep["project_banks"] = sorted(b["name"] for b in w.get('$ from type SoundBank'))
    if not banks:
        # 2026-11-20 (owner's run): the CK's project has no Starfield_XXX_Scratch. A bank's id is the hash of its
        # name, so a bank of that name made here is the game's empty 1490023241.bnk
        units = [u for u in w.get('$ "\\SoundBanks" select children') if u["type"] == "WorkUnit"]
        if not units:
            raise RuntimeError("no work unit under \\SoundBanks")
        w.call("ak.wwise.core.object.create", {"parent": units[0]["id"], "type": "SoundBank", "name": bank,
                                                 "onNameConflict": "merge"})
        banks = w.get(f'$ from type SoundBank where name = "{bank}"')
        rep["bank_created_in"] = units[0]["path"]
    ids = []
    for ev, files in wavs.items():
        if not files:
            continue
        cont = w.call("ak.wwise.core.object.create", container_args(parent["id"], ev))
        cpath = w.get(f'$ "{cont["id"]}"')[0]["path"]
        w.call("ak.wwise.core.audio.import", import_args(cpath, files))
        for snd in w.get(f'$ "{cont["id"]}" select children'):
            w.call("ak.wwise.core.object.setProperty", {"object": snd["id"], "property": "IsStreamingEnabled",
                                                        "value": False})
        e = w.call("ak.wwise.core.object.create", event_args(ev, cpath))
        ids.append(e["id"])
        rep["events"][ev] = {"container": cpath, "files": len(files), "id": WP.fnv1_32(ev)}
    w.call("ak.wwise.core.soundbank.setInclusions", inclusion_args(banks[0]["path"], ids))
    w.call("ak.wwise.core.project.save")
    return rep


MASTER_BUS = "Master Audio Bus"
OWN_PROJECT = "S2SSounds"


def first_set(chain, override_key, value_key):
    """The value of value_key on the first object of chain (the sound, then its ancestors) that overrides it
    (override_key true) or, failing that, on the top one: how Wwise inherits output bus / positioning."""
    for o in chain:
        if o.get(override_key):
            return o.get(value_key), o
    return (chain[-1].get(value_key), chain[-1]) if chain else (None, None)


def ref_name(v):
    return v.get("name") if isinstance(v, dict) else v


def read_template(w: "Waapi", template_event: str) -> dict:
    """The bus, spatialization and attenuation radius a vanilla sound plays with (inherited down the Actor-Mixer
    chain), read from the CK's project: our own project copies them (2026-11-20, owner's run: generating a bank in
    the CK's project fails on the Wwise trial's 200-media limit, the project has 28451)."""
    props = ("id", "name", "type", "path", "@OverrideOutput", "@OutputBus", "@OverridePositioning",
             "@3DSpatialization", "@EnableAttenuation", "@Attenuation")
    tpl = w.get(f'$ from type Event where name = "{template_event}" select children', ("id", "name", "@Target"))
    target = next((a["@Target"] for a in tpl if a.get("@Target")), None)
    if not target:
        raise RuntimeError(f"template event {template_event}: no action target")
    chain = w.get(f'$ "{target["id"]}"', props)
    for _ in range(16):
        up = w.get(f'$ "{chain[-1]["id"]}" select parent', props)
        if not up or up[0]["type"] in ("WorkUnit", "Folder", "ProjectFolder"):
            break
        chain.append(up[0])
    bus, bus_on = first_set(chain, "@OverrideOutput", "@OutputBus")
    _sp, pos_on = first_set(chain, "@OverridePositioning", "@3DSpatialization")
    att = pos_on.get("@Attenuation") if pos_on else None
    radius = None
    if isinstance(att, dict) and att.get("id"):
        got = w.get(f'$ "{att["id"]}"', ("id", "name", "@RadiusMax"))
        radius = got[0].get("@RadiusMax") if got else None
    return {"sound": chain[0]["path"], "bus": ref_name(bus), "bus_from": bus_on["path"] if bus_on else None,
            "spatialization": pos_on.get("@3DSpatialization") if pos_on else None,
            "attenuation": ref_name(att), "radius": radius, "positioning_from": pos_on["path"] if pos_on else None}


def own_container_args(event: str, bus_path: str, att_path: str, spatialization: int) -> dict:
    a = container_args("\\Actor-Mixer Hierarchy\\Default Work Unit", event)
    a.update({"@OverrideOutput": True, "@OutputBus": bus_path, "@OverridePositioning": True,
              "@3DSpatialization": spatialization, "@EnableAttenuation": True, "@Attenuation": att_path})
    return a


def build_own(w: "Waapi", wavs: dict, bank: str, bus: str, radius: float, spatialization: int) -> dict:
    """Our events in our own small project (under the trial's 200 media): containers routed to a bus of the vanilla
    template's name (bus ids are name hashes, so it is Starfield's bus in game; our project's Init bank is not
    shipped), 3D with an attenuation of the template's radius, in a bank named as Starfield's empty scratch bank."""
    master = f"\\Master-Mixer Hierarchy\\Default Work Unit\\{MASTER_BUS}"
    bus_path = master
    if bus and bus != MASTER_BUS:
        b = w.call("ak.wwise.core.object.create", {"parent": master, "type": "Bus", "name": bus,
                                                    "onNameConflict": "merge"})
        bus_path = w.get(f'$ "{b["id"]}"')[0]["path"]
    att = w.call("ak.wwise.core.object.create", {"parent": "\\Attenuations\\Default Work Unit",
                                                 "type": "Attenuation", "name": "S2S_Forge",
                                                 "onNameConflict": "replace", "@RadiusMax": float(radius)})
    att_path = w.get(f'$ "{att["id"]}"')[0]["path"]
    rep = {"bus": bus_path, "attenuation": {"path": att_path, "radius": radius}, "events": {}}
    ids = []
    for ev, files in wavs.items():
        if not files:
            continue
        cont = w.call("ak.wwise.core.object.create", own_container_args(ev, bus_path, att_path, spatialization))
        cpath = w.get(f'$ "{cont["id"]}"')[0]["path"]
        w.call("ak.wwise.core.audio.import", import_args(cpath, files))
        for snd in w.get(f'$ "{cont["id"]}" select children'):
            w.call("ak.wwise.core.object.setProperty", {"object": snd["id"], "property": "IsStreamingEnabled",
                                                        "value": False})
        e = w.call("ak.wwise.core.object.create", event_args(ev, cpath))
        ids.append(e["id"])
        rep["events"][ev] = {"container": cpath, "files": len(files), "id": WP.fnv1_32(ev)}
    b = w.call("ak.wwise.core.object.create", {"parent": "\\SoundBanks\\Default Work Unit", "type": "SoundBank",
                                                "name": bank, "onNameConflict": "merge"})
    w.call("ak.wwise.core.soundbank.setInclusions", inclusion_args(w.get(f'$ "{b["id"]}"')[0]["path"], ids))
    w.call("ak.wwise.core.project.save")
    return rep


def serve(wwise, wproj, port, fn):
    """fn(Waapi) with a WwiseConsole waapi-server on wproj; the server stopped afterwards."""
    server = subprocess.Popen([wwise, "waapi-server", wproj, "--allow-migration", "--wamp-port", str(port)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        w = Waapi(f"ws://127.0.0.1:{port}/waapi")
        try:
            return fn(w)
        finally:
            w.close()
    finally:
        server.terminate()
        try:
            server.wait(60)
        except subprocess.TimeoutExpired:
            server.kill()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--starfield", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--mod", required=True, help="mod folder: the bank goes to <mod>\\Sound\\Soundbanks")
    ap.add_argument("--wwise", default=WWISE_CONSOLE, help="WwiseConsole.exe")
    ap.add_argument("--ffmpeg")
    ap.add_argument("--event", action="append", help="Skyrim SOUN EditorIDs (default: the forge's)")
    ap.add_argument("--bank", default=BANK)
    ap.add_argument("--template-event", default=TEMPLATE_EVENT)
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--fresh-project", action="store_true", help="copy Bethesda's project / make ours again")
    ap.add_argument("--in-ck-project", action="store_true",
                    help="build in the CK's project itself (needs a Wwise licence: the trial stops at 200 media)")
    ap.add_argument("--bus", help="output bus name (default: the template sound's, read from the CK project)")
    ap.add_argument("--radius", type=float, help="attenuation radius in m (default: the template's)")
    a = ap.parse_args(argv)
    waapi_client()                                        # before the slow steps
    if not os.path.isfile(a.wwise):
        sys.exit(f"no WwiseConsole.exe at {a.wwise} (--wwise)")
    events = a.event or list(EVENTS)
    wavs = extract(a.skyrim_data, events, os.path.join(a.work, "wav"), a.ffmpeg)
    print("sounds:", {k: len(v) for k, v in wavs.items()})
    src = os.path.join(a.starfield, "Tools", "wwise", "Starfield")
    ck_dir = os.path.join(a.work, "project")
    own_dir = os.path.join(a.work, OWN_PROJECT)
    if a.fresh_project:
        for d in (ck_dir, own_dir):
            if os.path.isdir(d):
                shutil.rmtree(d)
    rep = {}
    if a.in_ck_project or not (a.bus and a.radius):
        if not os.path.isdir(ck_dir):
            shutil.copytree(src, ck_dir)
        ck_proj = os.path.join(ck_dir, "Starfield.wproj")
    if a.in_ck_project:                                  # needs a Wwise licence for the CK's 28k media
        rep = serve(a.wwise, ck_proj, a.port, lambda w: build(w, wavs, a.template_event, a.bank))
        wproj = ck_proj
    else:
        tpl = {"bus": a.bus, "radius": a.radius, "spatialization": 1}
        if not (a.bus and a.radius):
            tpl = serve(a.wwise, ck_proj, a.port, lambda w: read_template(w, a.template_event))
        rep["template"] = dict(tpl, event=a.template_event)
        bus = a.bus or tpl.get("bus") or MASTER_BUS
        radius = a.radius or tpl.get("radius") or 20.0
        spatial = tpl.get("spatialization") or 1
        wproj = os.path.join(own_dir, OWN_PROJECT + ".wproj")
        if not os.path.isfile(wproj):
            made = subprocess.run([a.wwise, "create-new-project", wproj, "--platform", "Windows"],
                                  capture_output=True, text=True)
            if not os.path.isfile(wproj):
                sys.exit("create-new-project failed:\n" + (made.stdout + made.stderr)[-1500:])
        rep.update(serve(a.wwise, wproj, a.port, lambda w: build_own(w, wavs, a.bank, bus, radius, spatial)))
    gen_dir = os.path.join(a.work, "generated")          # the project's own output path is Bethesda's build machine
    gen = subprocess.run([a.wwise, "generate-soundbank", wproj, "--bank", a.bank, "--platform", "Windows",
                          "--soundbank-path", "Windows", gen_dir], capture_output=True, text=True)
    # (2026-11-20, owner's run: generate-soundbank rejects --allow-migration; the WAAPI part had worked)
    rep["generate"] = {"returncode": gen.returncode, "tail": (gen.stdout + gen.stderr)[-1500:]}
    bnk = find_bank_file(gen_dir, a.bank)
    if bnk:
        dst_dir = os.path.join(a.mod, "Sound", "Soundbanks")
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, f"{WP.fnv1_32(a.bank)}.bnk")
        shutil.copyfile(bnk, dst)
        with open(dst, "rb") as fh:
            info = WP.parse_bank(fh.read())
        rep["bank"] = {"from": bnk, "to": dst, "bank_id": info["bank_id"], "chunks": info["chunks"],
                       "media": info["media"], "events": len(info["events"]),
                       "ours_present": {ev: WP.fnv1_32(ev) in info["events"] for ev in rep["events"]}}
    else:
        rep["bank"] = "not generated (see generate.tail)"
    with open(os.path.join(a.work, "sound_bank.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(json.dumps({k: rep.get(k) for k in ("template", "bus", "attenuation", "bank")}, indent=1))
    print(f"-> {os.path.join(a.work, 'sound_bank.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
