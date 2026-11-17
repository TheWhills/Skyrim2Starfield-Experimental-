"""Skyrim's and Starfield's sandbox game settings side by side, and what they give per activity (read-only).

2026-11-16 (owner): "can we figure out how Skyrim decides which thing they do, how often and when". The Creation Kit
wiki's Sandbox procedure (ck.uesp.net/wiki/Sandbox_Package): the sandbox scores nearby objects, weights each by the
probability of its activity type (sleep, eat, furniture, idle marker, dialogue; the type just done drops to zero and
the others rise, and the object just used scores zero), and stays for
    Base = fSandboxDurationBase * fSandboxDurationMult<Type>
    EnergyDuration = Base * (1 + Energy * fSandboxEnergyMult * fSandboxEnergyMult<Type>)
    random in EnergyDuration * (1 -/+ fSandboxDurationRangeMult)          (game hours)
This prints every GMST whose EditorID mentions "sandbox" in both masters, and that duration per type at --energy.
A setting missing from a master is the engine's built-in default (not readable here).

    python -I scripts\\npc\\sandbox_settings.py --skyrim "<Skyrim Data>\\Skyrim.esm" --starfield "<Starfield>"
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))


def value(edid: str, data: bytes):
    """A GMST's DATA by its EditorID prefix (f float, i / u int, b bool); strings and others as hex."""
    k = edid[:1].lower()
    if len(data) >= 4:
        if k == "f":
            return round(struct.unpack("<f", data[:4])[0], 6)
        if k == "i":
            return struct.unpack("<i", data[:4])[0]
        if k in ("u", "b"):
            return struct.unpack("<I", data[:4])[0]
    return data.hex()


def sandbox_settings(records) -> dict:
    """{EditorID: value} for (edid, data) pairs whose EditorID mentions sandbox (any case)."""
    return {e: value(e, d) for e, d in records if e and "sandbox" in e.lower()}


def lookup(settings: dict, name: str):
    """A setting by name, ignoring case (the masters spell SandBox / Sandbox both ways)."""
    low = name.lower()
    return next((v for k, v in settings.items() if k.lower() == low), None)


def durations(settings: dict, energy: float) -> dict:
    """{type: (low, mid, high) game hours} per fSandboxDurationMult<Type> found, by the wiki's formula."""
    base = lookup(settings, "fSandboxDurationBase")
    emult = lookup(settings, "fSandboxEnergyMult")
    rng = lookup(settings, "fSandboxDurationRangeMult") or 0.0
    if base is None:
        return {}
    out = {}
    for k, v in settings.items():
        if not k.lower().startswith("fsandboxdurationmult") or k.lower() == "fsandboxdurationmult":
            continue
        typ = k[len("fSandboxDurationMult"):]
        tmult = lookup(settings, "fSandboxEnergyMult" + typ)
        mid = base * v
        if emult is not None and tmult is not None:
            mid *= 1.0 + energy * emult * tmult
        out[typ] = (mid * (1 - rng), mid, mid * (1 + rng))
    return out


def read(path: str) -> dict:
    from fo4sf import packages
    ix = packages.Index(path)
    try:
        recs = []
        for fid in ix.by_type.get(b"GMST", []):
            subs = ix.subs(fid)
            e = next((d.rstrip(b"\0").decode("utf-8", "replace") for s, d in subs if s == b"EDID"), None)
            d = next((d for s, d in subs if s == b"DATA"), b"")
            recs.append((e, d))
        return sandbox_settings(recs)
    finally:
        ix.close()


def report(sky: dict, sf: dict, energy: float) -> str:
    lines = [f"{'setting':42} {'Skyrim':>14} {'Starfield':>14}"]
    names = sorted({k.lower(): k for k in list(sky) + list(sf)}.values(), key=str.lower)
    for n in names:
        a, b = lookup(sky, n), lookup(sf, n)
        lines.append(f"{n:42} {'-' if a is None else str(a):>14} {'-' if b is None else str(b):>14}")
    for label, s in (("Skyrim", sky), ("Starfield", sf)):
        lines.append(f"\n{label}: time per activity at Energy {energy:g} (game hours: low / mid / high; minutes mid)")
        d = durations(s, energy)
        if not d:
            lines.append("  (no fSandboxDurationBase in the master: engine default)")
        for typ, (lo, mid, hi) in sorted(d.items()):
            lines.append(f"  {typ:20} {lo:6.2f} / {mid:6.2f} / {hi:6.2f}   {mid * 60:6.1f} min")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skyrim", required=True, help="Skyrim.esm")
    ap.add_argument("--starfield", required=True, help="the Starfield folder")
    ap.add_argument("--energy", type=float, default=50.0)
    a = ap.parse_args(argv)
    sky = read(a.skyrim)
    sf = read(os.path.join(a.starfield, "Data", "Starfield.esm"))
    print(report(sky, sf, a.energy))


if __name__ == "__main__":
    main()
