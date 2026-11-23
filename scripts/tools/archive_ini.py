"""The StarfieldCustom.ini [Archive] line that loads extra BA2s the way the game's own archives load (read-only).

2026-11-23 (native grass): Starfield grows ground cover with any model inside the game's own archives (GrassMossMounds02
named by our grass record grew, owner 12:30) and with no model of ours, whether in our plugin's "S2SGrass - Main.ba2",
loose, or in MO2. Supported hypothesis: the grass loader only sees the archives the game lists in Starfield.ini
[Archive] (sResourceIndexFileList / sResourceArchiveList / sResourceArchiveList2 ...), not the plugin-named ones. A
custom ini value REPLACES the game's, so this reads the game's own list from <Starfield>\\Starfield.ini and prints it
with ours appended, to paste under [Archive] in StarfieldCustom.ini (MO2: Tools > INI Editor).

    python -I scripts\\tools\\archive_ini.py --starfield "D:\\SteamLibrary\\steamapps\\common\\Starfield" ^
        --add "S2SGrass - Main.ba2" --key sResourceArchiveList2
"""
import argparse
import configparser
import os
import sys

KEYS = ("sResourceIndexFileList", "sResourceStartUpArchiveList", "sResourceArchiveList", "sResourceArchiveList2",
        "sResourceArchiveMemoryCacheList", "sResourceEnglishVoiceList")


def read_archive_section(path):
    """{key (original case): value} of the [Archive] section of an ini (case-insensitive, duplicates: last wins)."""
    cp = configparser.ConfigParser(strict=False, interpolation=None, comment_prefixes=(";", "#"))
    cp.optionxform = str
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        cp.read_string(fh.read())
    for sec in cp.sections():
        if sec.lower() == "archive":
            return dict(cp[sec])
    return {}


def merged(value: str, add):
    """The comma list with the new entries appended once (case-insensitive)."""
    items = [x.strip() for x in (value or "").split(",") if x.strip()]
    have = {x.lower() for x in items}
    return ", ".join(items + [x for x in add if x.lower() not in have])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--starfield", required=True, help="the game folder (its Starfield.ini)")
    ap.add_argument("--add", action="append", required=True, help="BA2 file name in Data (repeatable)")
    ap.add_argument("--key", default="sResourceArchiveList2", choices=KEYS)
    a = ap.parse_args(argv)
    ini = os.path.join(a.starfield, "Starfield.ini")
    if not os.path.isfile(ini):
        sys.exit(f"not found: {ini}")
    sec = read_archive_section(ini)
    print(f"{ini} [Archive]:")
    for k in KEYS:
        v = next((val for key, val in sec.items() if key.lower() == k.lower()), None)
        if v is not None:
            print(f"  {k} = {v[:160]}{'...' if len(v) > 160 else ''}")
    cur = next((val for key, val in sec.items() if key.lower() == a.key.lower()), None)
    if cur is None:
        sys.exit(f"{a.key} is not set in {ini}: the game's built-in list is unknown, and a custom value would replace "
                 f"it. Pick a --key that is listed above.")
    data = os.path.join(a.starfield, "Data")
    for x in a.add:
        if not os.path.isfile(os.path.join(data, x)):
            print(f"note: {x} is not in {data} itself (fine if MO2 provides it)")
    print("\nPaste into StarfieldCustom.ini (MO2: Tools > INI Editor > StarfieldCustom.ini):\n")
    print("[Archive]")
    print(f"{a.key}={merged(cur, a.add)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
