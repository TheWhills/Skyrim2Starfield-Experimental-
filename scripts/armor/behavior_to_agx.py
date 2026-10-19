"""Translate a Skyrim behaviour graph (.hkx) into Starfield .agx graphs (prototype; docs/armor/animation-port.md):
state machines, states, transitions (events, conditions, blend times), clips (tags = clip names, as hkx_to_af.py
writes their .afx), blends (weights as blend-input curves on the bound variable), selectors (switches), behaviour
references and shared parts (separate graphs + NT_GRAPH_REF). Writes <out>\\<Name>.agx, one .agx per shared part,
and <Name>.report.json (what carried over, what did not: modifiers, unbound blends, empty states).

    python -I scripts\\armor\\behavior_to_agx.py --hkx <behaviors\\dragonbehavior.hkx> --name Dragon --out C:\\Modding\\work\\agx
        [--machine BHR_Flight]   (translate one state machine instead of the whole graph)

Not yet tested in game: outputs are research material until a translated graph runs.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import agx_write, behavior_to_agx as T, skyrimbehavior as SB  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hkx", required=True)
    ap.add_argument("--name", required=True, help="graph name (file Name.agx, prefix of the shared parts)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--machine", help="state machine name to translate (default: the whole graph)")
    a = ap.parse_args(argv)
    out = os.path.abspath(a.out)
    if out.lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    os.makedirs(out, exist_ok=True)
    with open(a.hkx, "rb") as fh:
        data = fh.read()
    b = SB.read(data)
    m = None
    if a.machine:
        m = T.find_machine(b, a.machine)
        if m is None:
            sys.exit(f"no state machine named {a.machine}")
    g, rep = T.translate(b, m, a.name + ".agx", SB._Reader(data))
    sizes = {}
    for gname, model in [(a.name, g)] + list(rep["extra_graphs"].items()):
        x = agx_write.write(model)
        with open(os.path.join(out, gname + ".agx"), "wb") as fh:
            fh.write(x)
        sizes[gname] = len(x)
    rep = {k: v for k, v in rep.items() if k != "extra_graphs"}
    rep["graphs"] = sizes
    with open(os.path.join(out, a.name + ".report.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    print(f"{len(sizes)} graphs ({sum(sizes.values()):,} bytes): states {rep['states']}, machines {rep['machines']}, "
          f"clip states {rep['clip_states']}, blends {rep['blends']}, switches {rep['switches']}, "
          f"shared-part refs {rep['graph_refs']}, behaviour refs {rep['behavior_refs']}, empty {rep['empty_states']}, "
          f"modifiers not translated {sum(rep['modifiers'].values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
