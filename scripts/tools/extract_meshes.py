"""Copy a few Skyrim meshes out of the owner's archives into one zip for a closer look (read-only; nothing goes into
the game folder or this repository): the models the first-run survey flagged (collision misplaced, parse failed), or
names given on the command line.

    python -I scripts\\tools\\extract_meshes.py --skyrim-data "<Skyrim SE>\\Data" ^
        --report C:\\Modding\\work\\skyrim_first_run\\report.json --out C:\\Modding\\work\\problem_meshes.zip
    python -I scripts\\tools\\extract_meshes.py --skyrim-data ... --name meshes\\clutter\\bucket01.nif --out x.zip
"""
import argparse
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import bsa  # noqa: E402


def from_report(path, max_misplaced):
    with open(path, encoding="utf-8") as f:
        rep = json.load(f)
    sv = rep.get("survey", {})
    return sv.get("parse_failed_all", []) + sv.get("misplaced_all", [])[:max_misplaced]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 allow_abbrev=False)
    ap.add_argument("--skyrim-data", required=True)
    ap.add_argument("--report", help="first-run report.json: take its parse-failed and misplaced models")
    ap.add_argument("--name", action="append", default=[], help="a mesh path (repeatable)")
    ap.add_argument("--max-misplaced", type=int, default=30)
    ap.add_argument("--out", required=True, help="zip OUTSIDE the repository")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    names = list(a.name) + (from_report(a.report, a.max_misplaced) if a.report else [])
    if not names:
        sys.exit("nothing to extract: pass --report or --name")
    src = bsa.SkyrimArchives(a.skyrim_data)
    got, missing = 0, []
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in dict.fromkeys(names):
            data = src.mesh(n)
            if data is None:
                missing.append(n)
                continue
            z.writestr(bsa.norm(n).replace("\\", "/"), data)
            got += 1
    print(f"{got} meshes -> {out} ({os.path.getsize(out) / 1e6:.1f} MB)" + (f"; not found: {missing}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
