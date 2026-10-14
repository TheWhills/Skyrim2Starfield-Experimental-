"""Source door animation topology for planning faithful multi-part conversion.

This describes source motion branches; it does not generate animation graphs or
claim that independent leaves can share the vanilla single-hinge animation.
"""
import struct
import base64
from . import nif, animation_curves


def sequence_timing(source, block, count):
    at = 12 + 29 * count
    if len(block) < at + 34:
        raise nif.NifError("truncated door sequence timing")
    weight, text, cycle, frequency, start, stop, manager, root, notes = struct.unpack_from("<fiIfffiiH", block, at)
    if len(block) != at + 34 + 4 * notes:
        raise nif.NifError("invalid door sequence note-array length")
    events = []
    if text != -1:
        if not 0 <= text < len(source.blocks) or source.type_of(text) != "NiTextKeyExtraData":
            raise nif.NifError("invalid door text-key link")
        data = source.blocks[text]
        num = struct.unpack_from("<I", data, 4)[0]
        if len(data) != 8 + 8 * num:
            raise nif.NifError("invalid door text-key length")
        for i in range(num):
            time, name = struct.unpack_from("<fi", data, 8 + 8 * i)
            if not 0 <= name < len(source.strings):
                raise nif.NifError("invalid door event string")
            events.append({"time": time, "text": source.strings[name].decode("latin-1")})
    if root != -1 and not 0 <= root < len(source.strings):
        raise nif.NifError("invalid door accumulation root")
    return {"weight": weight, "cycle_type": cycle, "frequency": frequency, "start": start, "stop": stop,
            "manager_block": manager, "accumulation_root": source.strings[root].decode("latin-1") if root != -1 else None,
            "text_events": events, "animation_note_blocks": list(struct.unpack_from(f"<{notes}i", block, at + 34))}


def transform_track(source, index):
    """Retain bind values, raw keys and decoded curves without resampling.

    Decoded curves still require a target animation emitter.
    Local generated reports contain source animation data and must not be published.
    """
    if index == -1:
        return None
    if not 0 <= index < len(source.blocks):
        raise nif.NifError("invalid door interpolator link")
    kind = source.type_of(index)
    if kind != "NiTransformInterpolator":
        return {"type": kind, "status": "unsupported_interpolator"}
    block = source.blocks[index]
    if len(block) < 36:
        raise nif.NifError("truncated door transform interpolator")
    values = struct.unpack_from("<8f", block)
    data = struct.unpack_from("<i", block, 32)[0]
    result = {"type": kind, "translation": list(values[:3]), "quaternion_wxyz": list(values[3:7]),
              "scale": values[7], "data_block": data, "source_keys": None}
    if data != -1:
        if not 0 <= data < len(source.blocks) or source.type_of(data) != "NiTransformData":
            raise nif.NifError("invalid door transform-data link")
        result["source_keys"] = {"type": "NiTransformData", "encoding": "base64",
                                 "data": base64.b64encode(source.blocks[data]).decode("ascii")}
        result["decoded_keys"] = animation_curves.decode(source.blocks[data])
    return result


def inspect(source):
    nodes = {}
    for i, block in enumerate(source.blocks):
        if source.type_of(i) == "NiNode":
            name = struct.unpack_from("<i", block)[0]
            nodes.setdefault(name, []).append(i)
    shapes = {s.block for s in nif.fo4_trishapes(source) if s.positions and s.triangles}
    world = nif.world_transforms(source)
    sequences, issues = [], []
    for i, block in enumerate(source.blocks):
        if source.type_of(i) != "NiControllerSequence":
            continue
        name, count = struct.unpack_from("<iI", block)
        if not 0 <= name < len(source.strings):
            raise nif.NifError("invalid sequence name")
        if source.strings[name] not in (b"Open", b"Close"):
            continue
        if 12 + 29 * count > len(block):
            raise nif.NifError("truncated door controlled-block list")
        targets = []
        for k in range(count):
            at = 12 + 29 * k
            interpolator, controller = struct.unpack_from("<ii", block, at)
            target_name = struct.unpack_from("<i", block, at + 9)[0]
            if not 0 <= target_name < len(source.strings):
                raise nif.NifError("invalid controlled node name")
            matches = nodes.get(target_name, [])
            if len(matches) != 1:
                issues.append({"sequence": i, "target": source.strings[target_name].decode("latin-1"),
                               "reason": "node binding absent or ambiguous"})
                continue
            node = matches[0]
            translation, rotation, scale = world(node)
            targets.append({"node": node, "name": source.strings[target_name].decode("latin-1"),
                            "interpolator": interpolator, "controller": controller,
                            "transform_track": transform_track(source, interpolator),
                            "pivot_source_units": list(translation), "rotation": list(rotation), "scale": scale,
                            "shape_blocks": sorted(shapes & nif.descendants(source, node))})
        sequences.append({"block": i, "name": source.strings[name].decode("latin-1"), "targets": targets,
                          "timing": sequence_timing(source, block, count)})
    hinge = nif.door_hinge(source)
    selected = shapes & nif.descendants(source, hinge[0]) if hinge else set()
    animated = {shape for seq in sequences if seq["name"] == "Open" for target in seq["targets"] for shape in target["shape_blocks"]}
    return {"sequences": sequences, "issues": issues, "single_hinge_node": hinge[0] if hinge else None,
            "single_hinge_shape_blocks": sorted(selected), "all_animated_shape_blocks": sorted(animated),
            "animated_shapes_outside_single_hinge": sorted(animated - selected),
            "requires_additional_motion_support": bool(animated - selected)}
