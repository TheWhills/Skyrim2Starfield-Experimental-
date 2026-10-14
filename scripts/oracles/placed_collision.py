"""List placed refs whose FO4 collision did not become a native body.

`no_collision` means the conversion failed and no box was written. `guessed` means
it failed and a box fallback was written instead. A `skipped_parts` note with a box
fallback is still guessed. `partial` means some native bodies remain and an undecoded
part was left out. `unbuilt` means the build rejected
that mesh, so the ref has nothing to place. A model FO4 shipped with no collision,
a passable door, and a rigged door (an empty report plus a door record) are not
this list. A model that was never part of the build is not this list either.
Exit 1 when any list is non-empty. This does not score a walk.

usage: python scripts/oracles/placed_collision.py --cell cell.json --manifest manifest.json
"""
import argparse
import json


_OK = {"fo4-native", "fo4-none", "fo4-mesh", "passable-door"}


def _key(path):
    text = (path or "").replace("/", "\\").lstrip("\\").lower()
    if text.startswith("meshes\\"):
        return text
    return "meshes\\" + text


def _items(manifest):
    return {_key(item.get("source", "")): item for item in manifest.get("items", [])}


def failure_kind(item):
    """`no_collision`, `guessed`, `partial`, or None when this item is not a placed failure."""
    report = item.get("collision_report")
    if not isinstance(report, dict) or not report:
        return None if item.get("door") else "no_collision"
    source = report.get("source")
    skipped = report.get("skipped_parts")
    if source == "fo4-native" and skipped:
        return "partial"
    if source in _OK:
        return None
    if source == "fo4-native-failed":
        return "no_collision"
    boxes = report.get("boxes") or 0
    if report.get("fo4_collision_error") or skipped:
        return "guessed" if boxes else "no_collision"
    return None


def placed(cell, items, failures=None):
    """Refs whose manifest item failed native collision, or whose mesh the build rejected."""
    rejected = {}
    for row in failures or []:
        nif = row.get("nif") if isinstance(row, dict) else None
        if nif:
            rejected[_key(nif)] = row.get("reason") or "build failed"
    no_collision = []
    guessed = []
    partial = []
    unbuilt = []
    for ref in cell.get("refs", []):
        model = ref.get("model") or ""
        if not model:
            continue
        key = _key(model)
        form = ref.get("formkey") or ref.get("ref")
        if key in rejected:
            unbuilt.append({"ref": form, "model": model, "reason": rejected[key]})
            continue
        item = items.get(key)
        if not item:
            continue
        kind = failure_kind(item)
        if kind is None:
            continue
        report = item.get("collision_report") or {}
        skipped = report.get("skipped_parts")
        reason = report.get("source") or report.get("fo4_collision_error")
        if not reason and isinstance(skipped, list) and skipped:
            reason = skipped[0]
        row = {"ref": form, "model": model, "reason": reason or "empty report"}
        if kind == "no_collision":
            no_collision.append(row)
        elif kind == "partial":
            partial.append(row)
        else:
            guessed.append(row)
    return {"no_collision": no_collision, "guessed": guessed, "partial": partial, "unbuilt": unbuilt}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    with open(args.cell, encoding="utf-8-sig") as handle:
        cell = json.load(handle)
    with open(args.manifest, encoding="utf-8-sig") as handle:
        manifest = json.load(handle)
    report = placed(cell, _items(manifest), manifest.get("failures"))
    print(json.dumps(report, indent=2))
    return 1 if any(report[key] for key in ("no_collision", "guessed", "partial", "unbuilt")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
