"""Gate the interior slice on pinned in-game evidence. Offline parses are not passes.

Usage: python scripts/oracles/interior_acceptance.py --evidence <evidence.json>
Exit 0 only when every cell criterion and every build gate is a game pass pinned to a
git revision, a build id, and hashes of the installed files. Missing rows stay unverified.
"""
import argparse
import json
import re

# Same rule as scripts/guard.py. The pattern is split so this file does not itself contain a machine path.
_DRIVE = "[A-Za-z]:[\\\\/]" + "Users" + "[\\\\/][^\\\\/\\s\"']+"
_MAC = "/Users" + "/[^/\\s\"']+"
_HOME = "/home" + "/[^/\\s\"']+"
LOCAL_PATH = re.compile(_DRIVE + "|" + _MAC + "|" + _HOME)
ALLOWED_PATH_WORDS = {"<user>", "<you>", "%USERNAME%", "$HOME", "username"}

CELLS = (
    "Vault 111",
    "Vault 81",
    "Red Rocket cave",
    "Vault 114",
    "Prydwen",
    "Hotel Rexford",
    "Boston Public Library",
    "Parsons",
)
CRITERIA = (
    "walkable",
    "doorways",
    "door_swing",
    "selected_body",
    "frame_collision",
    "lighting",
    "materials",
)
GATES = ("startup", "single_model", "rollback")


def _hex(value, size):
    return isinstance(value, str) and len(value) == size and all(c in "0123456789abcdef" for c in value)


def _pins(doc, errors):
    if not _hex(doc.get("revision"), 40):
        errors.append("revision must be a 40-digit lowercase git sha")
    build = doc.get("build_id")
    if not isinstance(build, str) or not build.strip():
        errors.append("build_id required")
    installed = doc.get("installed")
    if not isinstance(installed, list) or not installed:
        errors.append("installed hashes required")
        return
    for index, row in enumerate(installed):
        label = f"installed[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{label}: must be an object")
            continue
        path = row.get("path")
        if not isinstance(path, str) or not path.strip() or ":" in path or path.startswith(("/", "\\")):
            errors.append(f"{label}: relative install path required")
        if not _hex(row.get("sha256"), 64):
            errors.append(f"{label}: sha256 must be 64 lowercase hex digits")


def _observation(label, obs, errors, failures, unverified, passed, pins_ok):
    if obs is None:
        unverified.append(label)
        return
    if not isinstance(obs, dict):
        errors.append(f"{label}: observation must be an object")
        unverified.append(label)
        return
    result, kind, evidence = obs.get("result"), obs.get("kind"), obs.get("evidence")
    if result not in ("pass", "fail", "unverified"):
        errors.append(f"{label}: result must be pass, fail, or unverified")
        return
    if kind not in ("game", "offline"):
        errors.append(f"{label}: kind must be game or offline")
        return
    if not isinstance(evidence, str) or not evidence.strip():
        errors.append(f"{label}: evidence text required")
        return
    for match in LOCAL_PATH.finditer(evidence):
        if any(word in match.group(0) for word in ALLOWED_PATH_WORDS):
            continue
        errors.append(f"{label}: evidence names a machine path")
        unverified.append(label)
        return
    if result == "unverified":
        unverified.append(label)
        return
    if result == "fail":
        failures.append({"check": label, "evidence": evidence.strip()})
        return
    if kind != "game":
        errors.append(f"{label}: offline result cannot close a game criterion")
        unverified.append(label)
        return
    if not pins_ok:
        errors.append(f"{label}: game pass is not pinned to revision, build, and installed hashes")
        unverified.append(label)
        return
    passed.append(label)


def audit(doc):
    """Classify one evidence document. A pass is in-game, pinned, and written down. Nothing else counts."""
    result = {"passed": [], "failures": [], "unverified": [], "errors": []}
    if not isinstance(doc, dict):
        result["errors"].append("evidence must be an object")
        return result
    pin_errors = []
    _pins(doc, pin_errors)
    result["errors"].extend(pin_errors)
    pins_ok = not pin_errors
    for gate in GATES:
        _observation(gate, doc.get(gate), result["errors"], result["failures"], result["unverified"],
                     result["passed"], pins_ok)
    cells = doc.get("cells")
    if not isinstance(cells, dict):
        result["errors"].append("cells must be an object")
        cells = {}
    else:
        for name in cells:
            if name not in CELLS:
                result["errors"].append(f"unknown cell {name}")
    for name in CELLS:
        cell = cells.get(name)
        if not isinstance(cell, dict):
            if name in cells:
                result["errors"].append(f"{name}: cell must be an object")
            for criterion in CRITERIA:
                result["unverified"].append(f"{name}: {criterion}")
            continue
        for key in cell:
            if key not in CRITERIA:
                result["errors"].append(f"{name}: unknown criterion {key}")
        for criterion in CRITERIA:
            _observation(f"{name}: {criterion}", cell.get(criterion), result["errors"], result["failures"],
                         result["unverified"], result["passed"], pins_ok)
    return result


def failed(result):
    return bool(result["errors"] or result["failures"] or result["unverified"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    with open(args.evidence, encoding="utf-8-sig") as handle:
        result = audit(json.load(handle))
    print(json.dumps(result, indent=2))
    return int(failed(result))


if __name__ == "__main__":
    raise SystemExit(main())
