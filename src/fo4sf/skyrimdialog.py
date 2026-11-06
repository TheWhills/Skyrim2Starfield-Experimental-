"""Skyrim dialogue: topics (DIAL), their responses (INFO, in each topic's child group), the response text (localized
string tables) and the voice files (.fuz) that hold each spoken line. For converting Skyrim voice lines to Starfield
(owner 2026-11-05; Starfield's side is docs/npc/voice-pipeline.md, from UNITY).

Formats (UESP's Skyrim Mod File Format pages; checked here on synthetic files only):
* DIAL: EDID, FULL topic text, QNAM quest, DATA (u8 flags, u8 category, u16 subtype), SNAM subtype code ('HELO').
  Its INFOs follow it in a GRUP of type 7 (topic children) labelled with the topic's FormID.
* INFO: TRDT per response (u32 emotion type, u32 emotion value, 4 unused, u8 response number, 3 unused, u32 sound,
  u8 flags ...), NAM1 the response text after its TRDT (a string id in a localized plugin), CTDA conditions (32 bytes:
  u8 type, 3 unused, f32 comparison value, u16 function, 2 unused, u32 param 1, u32 param 2, u32 run on, u32 reference,
  i32 param 3).
* .DLSTRINGS / .ILSTRINGS: like .STRINGS, but each string is a u32 length then the bytes.
* .fuz: 'FUZE', u32 version, u32 lip size, the .lip, then the .xwm audio.
* Voice files: sound\\voice\\<plugin>\\<voice type EditorID>\\<...>_<INFO FormID 8 hex>_<response number>.fuz.
"""
import re
import struct
from typing import Dict, Iterable, List, Optional, Tuple

from . import fo4land

GET_IS_ID = 72               # CTDA function indices (Skyrim)
GET_IS_VOICE_TYPE = 426
GET_IS_RACE = 69
GET_IS_SEX = 130
FUNCTION_NAMES = {GET_IS_ID: "GetIsID", GET_IS_VOICE_TYPE: "GetIsVoiceType", GET_IS_RACE: "GetIsRace",
                  GET_IS_SEX: "GetIsSex"}


def _z(d) -> str:
    return fo4land.zstring(d)


def parse_condition(d: bytes) -> Dict:
    d = bytes(d)
    if len(d) < 24:
        return {}
    typ = d[0]
    use_global = bool(typ & 0x04)
    comp = struct.unpack_from("<I" if use_global else "<f", d, 4)[0]
    func, = struct.unpack_from("<H", d, 8)
    p1, p2 = struct.unpack_from("<II", d, 12)
    run_on = struct.unpack_from("<I", d, 20)[0] if len(d) >= 24 else 0
    return {"op": typ >> 5, "or": bool(typ & 1), "value": comp, "function": func,
            "name": FUNCTION_NAMES.get(func, str(func)), "param1": p1, "param2": p2, "run_on": run_on}


def parse_info(subs, fid: int) -> Dict:
    out = {"form_id": fid, "edid": "", "responses": [], "conditions": []}
    cur = None
    for sig, d in subs:
        d = bytes(d)
        if sig == b"EDID":
            out["edid"] = _z(d)
        elif sig == b"TRDT" and len(d) >= 13:
            cur = {"emotion": struct.unpack_from("<I", d, 0)[0], "number": d[12], "text": None, "text_id": None}
            out["responses"].append(cur)
        elif sig == b"NAM1" and cur is not None:
            if len(d) == 4:
                cur["text_id"] = struct.unpack_from("<I", d, 0)[0]
            else:
                cur["text"] = _z(d)
        elif sig == b"CTDA":
            c = parse_condition(d)
            if c:
                out["conditions"].append(c)
    return out


def parse_topic(subs, fid: int) -> Dict:
    out = {"form_id": fid, "edid": "", "text": None, "text_id": None, "quest": None, "subtype": None,
           "subtype_code": ""}
    for sig, d in subs:
        d = bytes(d)
        if sig == b"EDID":
            out["edid"] = _z(d)
        elif sig == b"FULL":
            if len(d) == 4:
                out["text_id"] = struct.unpack_from("<I", d, 0)[0]
            else:
                out["text"] = _z(d)
        elif sig == b"QNAM" and len(d) >= 4:
            out["quest"] = struct.unpack_from("<I", d, 0)[0]
        elif sig == b"DATA" and len(d) >= 4:
            out["subtype"] = struct.unpack_from("<H", d, 2)[0]
        elif sig == b"SNAM" and len(d) >= 4:
            out["subtype_code"] = d[:4].decode("latin-1")
    return out


def topics(esm_path: str) -> List[Dict]:
    """Every DIAL of the plugin with its INFOs (parse_topic + "infos": [parse_info])."""
    out, by_fid = [], {}
    with fo4land.Plugin(esm_path) as p:
        for item in fo4land.iter_items(p.buf, p.body, len(p.buf)):
            if item[0] != "GRUP" or item[3] != b"DIAL":
                continue
            for it in fo4land.iter_items(p.buf, item[1] + 24, item[2]):
                if it[0] == "GRUP":
                    owner = struct.unpack_from("<I", it[3], 0)[0] if len(it[3]) == 4 else None
                    topic = by_fid.get(owner)
                    if topic is None or it[4] != 7:
                        continue
                    for r in fo4land.iter_items(p.buf, it[1] + 24, it[2]):
                        if r[0] == "GRUP" or r[0] != b"INFO":
                            continue
                        subs = list(fo4land.iter_subrecords(fo4land.record_data(p.buf, r[1])))
                        topic["infos"].append(parse_info(subs, r[3]))
                    continue
                typ, off, _fl, fid = it
                if typ != b"DIAL":
                    continue
                t = parse_topic(list(fo4land.iter_subrecords(fo4land.record_data(p.buf, off))), fid)
                t["infos"] = []
                by_fid[fid] = t
                out.append(t)
    return out


def read_lstrings(raw: bytes, length_prefixed: bool) -> Dict[int, str]:
    """A Skyrim string table: u32 count, u32 data size, count x (id, offset), then the strings (zero-terminated; in
    .DLSTRINGS / .ILSTRINGS each after a u32 length)."""
    if not raw or len(raw) < 8:
        return {}
    count, _size = struct.unpack_from("<II", raw, 0)
    base = 8 + 8 * count
    out = {}
    for i in range(count):
        sid, off = struct.unpack_from("<II", raw, 8 + 8 * i)
        p = base + off
        if p >= len(raw):
            continue
        if length_prefixed:
            n, = struct.unpack_from("<I", raw, p)
            s = raw[p + 4:p + 4 + n]
            s = s[:-1] if s.endswith(b"\0") else s
        else:
            end = raw.find(b"\0", p)
            s = raw[p:end if end >= 0 else len(raw)]
        out[sid] = s.decode("utf-8", "replace")
    return out


def response_texts(sky, language: str = "english") -> Dict[int, str]:
    """Skyrim.esm's dialogue response strings (strings\\skyrim_<language>.ilstrings: INFO texts; .dlstrings holds
    descriptions and book text: the owner's first run found 2,686 of those and no response text)."""
    raw = sky._read(f"strings\\skyrim_{language}.ilstrings") if hasattr(sky, "_read") else None
    return read_lstrings(raw, True) if raw else {}


def speaks(info: Dict, npc_fid: int, voice_fid: Optional[int]) -> Optional[str]:
    """How this NPC says the INFO: 'own' (a GetIsID condition on it), 'voice' (GetIsVoiceType its voice type, no
    GetIsID of anyone else), 'anyone' (no GetIsID / voice type condition), None (someone else's line)."""
    ids = [c["param1"] for c in info["conditions"] if c["function"] == GET_IS_ID and c["value"] == 1.0]
    vts = [c["param1"] for c in info["conditions"] if c["function"] == GET_IS_VOICE_TYPE and c["value"] == 1.0]
    if ids:
        return "own" if npc_fid in ids else None
    if vts:
        return "voice" if voice_fid in vts else None
    return "anyone"


def unpack_fuz(raw: bytes) -> Tuple[bytes, bytes]:
    """(lip, xwm) of a .fuz."""
    if raw[:4] != b"FUZE":
        raise ValueError("not a .fuz (no FUZE magic)")
    _ver, lip_size = struct.unpack_from("<II", raw, 4)
    return raw[12:12 + lip_size], raw[12 + lip_size:]


def voice_index(names: Iterable[str], plugin: str = "skyrim.esm") -> Dict[Tuple[str, int, int], str]:
    """{(voice type EditorID lower, INFO FormID, response number): archive path} of the .fuz / .xwm / .wav voice files
    of `plugin` among archive names."""
    out = {}
    rx = re.compile(r"sound[\\/]voice[\\/]" + re.escape(plugin.lower()) +
                    r"[\\/]([^\\/]+)[\\/][^\\/]*_([0-9a-f]{8})_(\d+)\.(fuz|xwm|wav)$")
    for n in names:
        m = rx.search(n.lower())
        if m:
            key = (m.group(1), int(m.group(2), 16), int(m.group(3)))
            if key not in out or m.group(4) == "fuz":
                out[key] = n
    return out
