"""Skyrim's animationdatasinglefile: which clip generator plays which motion, per behaviour project.

Skyrim keeps the root motion of vanilla clips (and of older packs such as TK Dodge) outside the .hkx, in
meshes\\animationdatasinglefile.txt. Layout (verified 2026-10-20 by walking TK Dodge For RE's full copy, 171,765 lines,
429 projects, ending exactly at the last line; read for the format only):

    <project count>
    <project file name>           x count ("DefaultMale.txt", ...)
    then per project, in that order:
      <line count of the project block>, then that many lines:
        1
        <file count>, then that many paths (behaviour, character, skeleton .hkx)
        <1 if the project has clip data, else 0>
        clip blocks, each: clip generator name, motion id, playback speed, crop start, crop end, event count,
                           that many "event:time" lines, a blank line
      only when the flag is 1: <line count of the motion block>, then that many lines of motion blocks
        (id, duration, n "t x y z", m "t x y z w", blank: parse_motion_blocks)

A clip generator is a node of a behaviour graph (hkbClipGenerator: name -> animation file, skyrimbehavior.read); the
motion follows the generator, so a clip file gets its motion through the generators that play it. Behaviour mods
patched with Nemesis / Pandora ship the same blocks as fragments: animationdatasinglefile\\<Project>~<n>\\
<ClipGenerator>~<id>.txt (a clip block) and <id>.txt (a motion block), e.g. TK Dodge RE's DefaultMale~1\\
TKDodgeForward~tkds$0.txt + tkds$0.txt.
"""
import os
import re
from collections import Counter
from typing import Dict, Iterable, List, Optional



class AnimDataError(ValueError):
    pass


def _int(line: str, what: str) -> int:
    try:
        return int(line.strip())
    except ValueError:
        raise AnimDataError(f"expected {what}, found {line!r}") from None


def _float(line: str, default: float = 0.0) -> float:
    try:
        return float(line.strip())
    except ValueError:
        return default


def parse_clip_blocks(lines: List[str]) -> List[Dict]:
    """Clip blocks [{"name", "id", "speed", "crop": (start, end), "events": [(name, time)]}] from the lines after a
    project's clip-data flag (or one Nemesis clip fragment)."""
    out, i = [], 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        if i + 5 >= len(lines):
            raise AnimDataError(f"clip block {lines[i]!r} cut short")
        name, ident = lines[i].strip(), lines[i + 1].strip()
        speed, c0, c1 = _float(lines[i + 2], 1.0), _float(lines[i + 3]), _float(lines[i + 4])
        n = _int(lines[i + 5], f"event count of clip {name}")
        events = []
        for ln in lines[i + 6:i + 6 + n]:
            ev, _, t = ln.strip().rpartition(":")
            events.append((ev, _float(t)))
        out.append({"name": name, "id": ident, "speed": speed, "crop": (c0, c1), "events": events})
        i += 6 + n
    return out


def parse_motion_blocks(lines: List[str]) -> Dict[str, Dict]:
    """Motion blocks read in sequence (strict, unlike rootmotion.parse_motion_data's scan of arbitrary text): id,
    duration, key count, "t x y z" lines, key count, "t x y z w" lines, blank lines between blocks."""
    out, i = {}, 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        if i + 2 >= len(lines):
            raise AnimDataError(f"motion block {lines[i]!r} cut short")
        ident, duration = lines[i].strip(), _float(lines[i + 1])
        n = _int(lines[i + 2], f"translation count of motion {ident}")
        tr = [tuple(_floats(ln, 4, ident)) for ln in lines[i + 3:i + 3 + n]]
        j = i + 3 + n
        m = _int(lines[j], f"rotation count of motion {ident}") if j < len(lines) else 0
        rot = [tuple(_floats(ln, 5, ident)) for ln in lines[j + 1:j + 1 + m]]
        out[ident] = {"duration": duration, "translations": tr, "rotations": rot}
        i = j + 1 + m
    return out


def _floats(line: str, n: int, ident: str) -> List[float]:
    parts = line.split()
    if len(parts) != n:
        raise AnimDataError(f"motion {ident}: expected {n} numbers, found {line!r}")
    try:
        return [float(x) for x in parts]
    except ValueError:
        raise AnimDataError(f"motion {ident}: not numbers: {line!r}") from None


def parse(text: str) -> Dict[str, Dict]:
    """{project name without .txt: {"files": [...], "clips": [clip blocks], "motion": {id: motion block}}}."""
    lines = text.splitlines()
    if not lines:
        raise AnimDataError("empty file")
    count = _int(lines[0], "project count")
    names = [ln.strip() for ln in lines[1:1 + count]]
    i, out = 1 + count, {}
    for name in names:
        if i >= len(lines):
            raise AnimDataError(f"project {name}: missing block")
        n = _int(lines[i], f"line count of project {name}")
        block = lines[i + 1:i + 1 + n]
        i += 1 + n
        if len(block) < 3:
            raise AnimDataError(f"project {name}: block of {len(block)} lines")
        files_n = _int(block[1], f"file count of project {name}")
        files = [ln.strip() for ln in block[2:2 + files_n]]
        has_clips = 2 + files_n < len(block) and block[2 + files_n].strip() == "1"
        clips, motion = [], {}
        if has_clips:
            clips = parse_clip_blocks(block[3 + files_n:])
            m = _int(lines[i], f"motion line count of project {name}")
            motion = parse_motion_blocks(lines[i + 1:i + 1 + m])
            i += 1 + m
        # a few object projects are listed twice (Moth.txt, SmallBird01.txt, ...): the first one is kept
        out.setdefault(re.sub(r"\.txt$", "", name, flags=re.I), {"files": files, "clips": clips, "motion": motion})
    if i != len(lines) and any(ln.strip() for ln in lines[i:]):
        raise AnimDataError(f"{len(lines) - i} unread lines after the last project")
    return out


MARKUP = re.compile(r"^\s*<!--\s*(MOD_CODE\s*~[^~]*~\s*OPEN|ORIGINAL|CLOSE)\s*-->\s*$", re.I)


def apply_markup(lines: List[str]) -> List[str]:
    """A Nemesis patch fragment with its edits applied: lines between MOD_CODE ... OPEN and ORIGINAL (or CLOSE) are
    kept, lines between ORIGINAL and CLOSE (what the mod replaces) are dropped, the markers removed."""
    out, state = [], "plain"
    for ln in lines:
        m = MARKUP.match(ln)
        if m:
            tag = m.group(1).upper()
            state = "new" if tag.startswith("MOD_CODE") else "old" if tag == "ORIGINAL" else "plain"
            continue
        if state != "old":
            out.append(ln)
    return out


def _numbers(line: str) -> Optional[List[float]]:
    try:
        return [float(x) for x in line.split()]
    except ValueError:
        return None


def _fragment_motion(lines: List[str]) -> Dict[str, Dict]:
    """A motion fragment after apply_markup. Nemesis rewrites the key counts when it merges, so patched fragments keep
    the vanilla counts; keys are taken by shape instead: 4 numbers = translation, 5 = rotation."""
    lines = [ln.strip() for ln in lines if ln.strip()]
    if len(lines) < 2:
        raise AnimDataError("motion fragment cut short")
    tr, rot = [], []
    for ln in lines[2:]:
        v = _numbers(ln)
        if v and len(v) == 4:
            tr.append(tuple(v))
        elif v and len(v) == 5:
            rot.append(tuple(v))
    return {lines[0]: {"duration": _float(lines[1]), "translations": tr, "rotations": rot}}


def _fragment_clip(lines: List[str]) -> List[Dict]:
    lines = [ln.strip() for ln in lines if ln.strip()]
    if len(lines) < 5:
        raise AnimDataError("clip fragment cut short")
    events = []
    for ln in lines[6:]:                            # counts may be stale (see _fragment_motion)
        ev, _, t = ln.rpartition(":")
        if ev:
            events.append((ev, _float(t)))
    return [{"name": lines[0], "id": lines[1], "speed": _float(lines[2], 1.0), "crop": (_float(lines[3]),
             _float(lines[4])), "events": events}]


def read_fragments(folder: str) -> Dict[str, Dict]:
    """Nemesis / Pandora fragments under an `animationdatasinglefile` folder: {project: {"files": [], "clips",
    "motion"}} (project = folder name before "~"; patch markup applied)."""
    out: Dict[str, Dict] = {}
    for entry in sorted(os.listdir(folder)):
        sub = os.path.join(folder, entry)
        if not os.path.isdir(sub):
            continue
        proj = out.setdefault(entry.split("~")[0], {"files": [], "clips": [], "motion": {}})
        for fn in sorted(os.listdir(sub)):
            if not fn.lower().endswith(".txt"):
                continue
            with open(os.path.join(sub, fn), encoding="utf-8", errors="replace") as fh:
                lines = apply_markup(fh.read().splitlines())
            if "~" in fn:                                  # <ClipGenerator>~<id>.txt: a clip block
                proj["clips"].extend(_fragment_clip(lines))
            else:                                          # <id>.txt: a motion block
                proj["motion"].update(_fragment_motion(lines))
    return out


def merge(*sources: Dict[str, Dict]) -> Dict[str, Dict]:
    """Later sources (mods' fragments) add to and override earlier ones (the game's file), per project."""
    out: Dict[str, Dict] = {}
    for src in sources:
        for name, p in src.items():
            q = out.setdefault(name, {"files": [], "clips": [], "motion": {}})
            q["files"] = q["files"] or list(p.get("files", []))
            names = {c["name"].lower() for c in p.get("clips", [])}
            q["clips"] = [c for c in q["clips"] if c["name"].lower() not in names] + list(p.get("clips", []))
            q["motion"].update(p.get("motion", {}))
    return out


def clip_generators(behaviors: Iterable[Dict]) -> Dict[str, str]:
    """{clip generator name (lower case): animation path} from skyrimbehavior.read() results."""
    out = {}
    for b in behaviors:
        for n in b.get("nodes", {}).values():
            if n.get("class") == "hkbClipGenerator" and n.get("name") and n.get("animation"):
                out.setdefault(str(n["name"]).lower(), str(n["animation"]))
    return out


def _stem(path: str) -> str:
    return os.path.splitext(re.split(r"[\\/]", path)[-1])[0].lower()


def clip_motion(project: Dict, generators: Optional[Dict[str, str]] = None, report: Optional[Dict] = None) -> Dict[str, Dict]:
    """{clip file stem (lower case): motion block} for one project.

    A file gets the motion of the clip generators that play it (generators: clip_generators() of the project's
    behaviours). Without a behaviour mapping for a generator, its name is taken as the file stem (TK Dodge's
    TKDodgeForward plays TKDodgeForward.hkx; supported, not general: vanilla names such as "AttackRight" differ from
    their files). Mirrored generators ("[mirror" in the name) are skipped: their motion is the mirror image. When the
    generators of one file disagree, the most common motion id wins (report["conflicts"])."""
    generators = generators or {}
    ids: Dict[str, Counter] = {}
    rep = {"by_behavior": 0, "by_name": 0, "mirrored_skipped": 0, "no_motion_block": [], "conflicts": {}}
    for c in project.get("clips", []):
        if "[mirror" in c["name"].lower():
            rep["mirrored_skipped"] += 1
            continue
        path = generators.get(c["name"].lower())
        stem = _stem(path) if path else c["name"].lower()
        rep["by_behavior" if path else "by_name"] += 1
        if c["id"] not in project.get("motion", {}):
            rep["no_motion_block"].append(c["name"])
            continue
        ids.setdefault(stem, Counter())[c["id"]] += 1
    out = {}
    for stem, cnt in ids.items():
        best = cnt.most_common(1)[0][0]
        if len(cnt) > 1:
            rep["conflicts"][stem] = dict(cnt)
        out[stem] = project["motion"][best]
    if report is not None:
        report.update(rep)
    return out
