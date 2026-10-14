"""Audit converted door body wiring and known box motion types, without running the game.

Missing frame collision is unassessed: fixed visual trim need not be solid.
Keyframed flags are necessary evidence, not proof that animation/physics works.
"""
import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from fo4sf import nif, sfcollision, sfnif


def audit(data):
    f = nif.parse(data)
    result = {"moving_bodies": 0, "frame_bodies": 0, "unassessed": [], "errors": []}
    nodes = {}
    for i, block in enumerate(f.blocks):
        if f.type_of(i) == "NiNode":
            name = f.strings[struct.unpack_from("<i", block)[0]]
            if name in nodes:
                result["errors"].append("duplicate node name: " + name.decode(errors="replace"))
            nodes[name] = i
    anim = nodes.get(sfnif.DOOR_TEMPLATE["anim_root"])
    if anim is None:
        result["errors"].append("expected animation root is absent")
        return result
    moving = nif.descendants(f, anim)
    frame = nif.descendants(f, nodes[b"Frame"]) if b"Frame" in nodes else set()
    if moving & frame:
        result["errors"].append("stationary frame is inside the animation tree")
    for i, block in enumerate(f.blocks):
        if f.type_of(i) != "bhkNPCollisionObject":
            continue
        target, _, system = struct.unpack_from("<iHi", block)
        if not 0 <= target < len(f.blocks) or not 0 <= system < len(f.blocks) or f.type_of(system) != "bhkPhysicsSystem":
            result["errors"].append("invalid collision target/system link")
            continue
        group = "moving" if target in moving else "frame" if target in frame else None
        if group is None:
            result["unassessed"].append("collision body is outside known door branches")
            continue
        result[group + "_bodies"] += 1
        payload = f.blocks[system]
        size = struct.unpack_from("<I", payload)[0]
        if size != len(payload) - 4:
            result["errors"].append(group + " collision payload length mismatch")
            continue
        blob = payload[4:]
        try:
            sfcollision.check_template(blob)
        except ValueError:
            result["unassessed"].append(group + " body uses an unrecognized physics layout")
            continue
        motion = struct.unpack_from("<I", blob, 240)[0]
        expected = 2 if group == "moving" else 1
        if motion != expected:
            result["errors"].append(f"{group} box motion type {motion}; expected {expected}")
    if not result["moving_bodies"]:
        result["errors"].append("animated door has no moving collision body")
    if frame and not result["frame_bodies"]:
        result["unassessed"].append("fixed frame geometry has no stationary collision body")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--require-assessed", action="store_true")
    args = parser.parse_args()
    root = (args.staging / "meshes").resolve()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    reports = []
    for item in manifest["items"]:
        if "door" not in item:
            continue
        try:
            path = (root / item["model"].replace("\\", "/")).resolve()
            if not path.is_relative_to(root):
                raise ValueError("model path escapes staging meshes")
            report = audit(path.read_bytes())
        except (ValueError, IndexError, struct.error, OSError) as error:
            report = {"errors": [str(error)], "unassessed": []}
        reports.append({"source": item["source"], **report})
    print(json.dumps({"doors": len(reports), "reports": reports}, indent=2))
    return int(not reports or any(r["errors"] or (args.require_assessed and r["unassessed"]) for r in reports))


if __name__ == "__main__":
    raise SystemExit(main())
