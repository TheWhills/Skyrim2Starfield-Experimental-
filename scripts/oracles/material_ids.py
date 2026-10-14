"""Check generated material JSON for duplicate defined resource IDs.

Usage: python scripts/oracles/material_ids.py --materials <staging/materials>
Reads local generated files only; does not deploy or modify them.
"""
import argparse
import json
from pathlib import Path


def audit_material_ids(root):
    root = Path(root)
    owners, duplicates, errors = {}, [], []
    files = sorted(root.rglob("*.mat"))
    if not root.is_dir() or not files:
        errors.append({"error": "no material files found"})
    for path in files:
        relative = str(path.relative_to(root))
        try:
            with path.open(encoding="utf-8-sig") as f:
                material = json.load(f)
            objects = material["Objects"]
            if not isinstance(objects, list):
                raise ValueError("Objects must be a list")
            for obj in objects:
                if "ID" not in obj:
                    continue
                identity = obj["ID"]
                if not isinstance(identity, str) or not identity:
                    raise ValueError("defined ID must be a nonempty string")
                # Hexadecimal resource identifiers are case-insensitive.
                key = identity.lower()
                if key in owners:
                    duplicates.append({"id": identity, "first": owners[key], "second": relative})
                else:
                    owners[key] = relative
        except (OSError, ValueError, KeyError, TypeError) as e:
            errors.append({"file": relative, "error": f"{type(e).__name__}: {e}"})
    return {"materials": len(files), "defined_ids": len(owners), "duplicates": duplicates, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materials", required=True)
    args = parser.parse_args()
    report = audit_material_ids(args.materials)
    print(json.dumps(report, indent=2))
    return 1 if report["duplicates"] or report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
