"""Dump a Skyrim behaviour graph (.hkx) as a readable tree and as JSON (read-only): state machines with their states,
transitions (event -> state, condition), clips (animation path, speed), blends and variable bindings. For planning
the Starfield side of a creature (docs/armor/animation-port.md "Creatures").

    python -I scripts\\armor\\behavior_dump.py --hkx <behaviors\\horsebehavior.hkx> --out C:\\Modding\\work\\behaviors
    python -I scripts\\armor\\behavior_dump.py --dir <folder of behaviour .hkx> --out ...     (every graph in a folder)
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "src"))

from fo4sf import skyrimbehavior as SB  # noqa: E402

SKIP = ("hkbVariableBindingSet", "hkbClipTriggerArray", "hkbBoneWeightArray", "hkbStateMachineEventPropertyArray",
        "hkbBoneIndexArray", "hkbExpressionDataArray")


def tree(b: dict, limit: int = 100000):
    N, E, V = b["nodes"], b["events"], b["variables"]
    lines, seen = [], set()

    def ev(i):
        return E[i] if 0 <= i < len(E) else "-"

    def binds(n):
        bs = [f"{x['member']}={V[x['variable']] if 0 <= x['variable'] < len(V) else x['variable']}"
              for x in n.get("bindings", [])]
        return f"  [{', '.join(bs)}]" if bs else ""

    def walk(o, d=0):
        if o is None or o not in N or len(lines) >= limit:
            return
        n, pad = N[o], "  " * d
        c = n["class"]
        if o in seen:
            lines.append(f"{pad}(see {c} {n.get('name')})")
            return
        seen.add(o)
        if c == "hkbStateMachine":
            lines.append(f"{pad}SM {n.get('name')} (start {n['start_state']}){binds(n)}")
            for t in (N.get(n["wildcard"], {}).get("transitions") or []):
                cond = f" if {t['condition_expr']}" if t["condition_expr"] else ""
                lines.append(f"{pad}  * on {ev(t['event'])} -> {t['to_state']}{cond}")
            for s in n["states"]:
                st = N[s]
                tr = N.get(st.get("transitions"), {}).get("transitions") or []
                arrows = ", ".join(f"{ev(t['event'])}->{t['to_state']}" + (f" if {t['condition_expr']}"
                                                                         if t["condition_expr"] else "") for t in tr)
                lines.append(f"{pad}  [{st['state_id']}] {st.get('name')}: {arrows}")
                walk(st.get("generator"), d + 2)
        elif c == "hkbClipGenerator":
            lines.append(f"{pad}clip {n.get('name')}: {n.get('animation')} x{n.get('speed', 1):.2f}{binds(n)}")
        elif c == "hkbBlenderGenerator":
            lines.append(f"{pad}blend {n.get('name')}{binds(n)}")
            for ch in n.get("blend_children", []):
                walk(N[ch].get("generator"), d + 1)
        else:
            lines.append(f"{pad}{c} {n.get('name') or ''}{binds(n)}")
            for ch in n["children"]:
                if N[ch]["class"] not in SKIP:
                    walk(ch, d + 1)
    walk(b["root"])
    return lines


def dump(path, out):
    with open(path, "rb") as fh:
        b = SB.read(fh.read())
    base = os.path.splitext(os.path.basename(path))[0]
    with open(os.path.join(out, base + ".txt"), "w", encoding="utf-8") as fh:
        s = SB.summary(b)
        fh.write(f"{b['name']}: {s}\nevents ({len(b['events'])}): {', '.join(b['events'])}\n"
                 f"variables ({len(b['variables'])}): {', '.join(b['variables'])}\n"
                 f"checks: {b['checks'] or 'none'}\n\n" + "\n".join(tree(b)) + "\n")
    with open(os.path.join(out, base + ".json"), "w", encoding="utf-8") as fh:
        json.dump({**b, "nodes": {str(k): v for k, v in b["nodes"].items()}}, fh, indent=1)
    return b


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hkx", action="append", default=[])
    ap.add_argument("--dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    files = list(a.hkx)
    if a.dir:
        for d, _ds, fns in os.walk(a.dir):
            files += [os.path.join(d, f) for f in sorted(fns) if f.lower().endswith(".hkx")]
    done = 0
    for f in files:
        try:
            b = dump(f, a.out)
            done += 1
            print(f"{os.path.basename(f)}: {SB.summary(b)}")
        except SB.BehaviorError as e:
            print(f"{os.path.basename(f)}: skipped ({e})")
    print(f"{done} graphs dumped to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
