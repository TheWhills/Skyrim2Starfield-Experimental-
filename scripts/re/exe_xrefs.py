"""Which code in Starfield.exe uses given strings, and what else that code uses (read-only).

2026-11-24: ground cover on the Skyrim world grows in the same patches whatever our terrain file says (mask, texture,
table reading, alpha all tested in game): the per-spot density comes from elsewhere. Vanilla terrain source tiles ship
density maps (<block>_{base,flatinner,flatouter,flow,solid,talus}.dds); the code that loads or samples them names the
source. This tool, without a disassembler:

  1. finds the ASCII / UTF-16 strings matching --pattern and their addresses;
  2. finds every RIP-relative reference to them in executable sections (any 32-bit displacement d at offset i with
     address(i + 4) + d == the string, the form LEA / MOV use);
  3. maps each reference to its function through the exception table (.pdata: begin, end of every function);
  4. per function: all strings it references (any pattern), the functions it calls (E8 rel32) and, one level down,
     the strings those callees reference.

    python -I scripts\\re\\exe_xrefs.py --exe "D:\\SteamLibrary\\steamapps\\common\\Starfield\\Starfield.exe" ^
        --out C:\\Modding\\work\\density_xrefs.txt

Needs numpy. Takes a few minutes on a 100 MB executable.
"""
import argparse
import re
import struct
import sys

import numpy as np

DEFAULT = r"flatinner|flatouter|talus|densitymap|density map|_base\.dds|overlaysource|groundcover|gcvr"
ASCII = re.compile(rb"[\x20-\x7e]{4,}")
UTF16 = re.compile(rb"(?<![\x20-\x7e])(?:[\x20-\x7e]\x00){4,}")


class PE:
    """Sections and the exception table of a PE32+ image."""

    def __init__(self, data: bytes):
        self.data = data
        if data[:2] != b"MZ":
            raise ValueError("not an MZ executable")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("no PE header")
        nsec = struct.unpack_from("<H", data, pe + 6)[0]
        opt_size = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        if struct.unpack_from("<H", data, opt)[0] != 0x20B:
            raise ValueError("not PE32+ (64-bit)")
        self.image_base = struct.unpack_from("<Q", data, opt + 24)[0]
        ndirs = struct.unpack_from("<I", data, opt + 108)[0]
        dirs = [struct.unpack_from("<II", data, opt + 112 + 8 * i) for i in range(ndirs)]
        self.sections = []
        for i in range(nsec):
            o = opt + opt_size + 40 * i
            name = data[o:o + 8].rstrip(b"\0").decode("ascii", "replace")
            vsize, va, rsize, raw = struct.unpack_from("<IIII", data, o + 8)
            chars = struct.unpack_from("<I", data, o + 36)[0]
            self.sections.append({"name": name, "va": va, "vsize": vsize, "raw": raw, "rsize": rsize,
                                  "exec": bool(chars & 0x20000000)})
        self.pdata = dirs[3] if len(dirs) > 3 else (0, 0)

    def off_to_rva(self, off):
        for s in self.sections:
            if s["raw"] <= off < s["raw"] + s["rsize"]:
                return off - s["raw"] + s["va"]
        return None

    def rva_to_off(self, rva):
        for s in self.sections:
            if s["va"] <= rva < s["va"] + max(s["vsize"], s["rsize"]):
                return rva - s["va"] + s["raw"]
        return None

    def functions(self):
        """Sorted (begin, end) RVAs from .pdata."""
        rva, size = self.pdata
        off = self.rva_to_off(rva) if rva else None
        if off is None:
            return np.zeros((0, 2), np.int64)
        n = size // 12
        a = np.frombuffer(self.data, "<u4", 3 * n, off).reshape(n, 3)[:, :2].astype(np.int64)
        return a[np.argsort(a[:, 0])]


def strings(pe: PE, pattern=None):
    """{rva: (text, 'a' or 'u')} of strings outside executable sections (matching pattern when given)."""
    rx = re.compile(pattern, re.I) if pattern else None
    out = {}
    for s in pe.sections:
        if s["exec"]:
            continue
        blob = pe.data[s["raw"]:s["raw"] + s["rsize"]]
        for m in ASCII.finditer(blob):
            t = m.group().decode("ascii")
            if rx is None or rx.search(t):
                out[s["va"] + m.start()] = (t, "a")
        for m in UTF16.finditer(blob):
            t = m.group().decode("utf-16-le")
            if rx is None or rx.search(t):
                out[s["va"] + m.start()] = (t, "u")
    return out


def rip_refs(pe: PE, targets):
    """[(ref rva, target rva)]: 32-bit displacements in executable sections whose rva + 4 + d hits a target."""
    tg = np.array(sorted(targets), np.int64)
    out = []
    if not len(tg):
        return out
    chunk = 1 << 23                                 # 8 MB at a time: a few hundred MB of memory at most
    for s in pe.sections:
        if not s["exec"] or s["rsize"] < 4:
            continue
        full = np.frombuffer(pe.data, np.uint8, s["rsize"], s["raw"])
        for start in range(0, len(full) - 3, chunk):
            blob = full[start:start + chunk + 3]
            d = (blob[:-3].astype(np.int64) | (blob[1:-2].astype(np.int64) << 8)
                 | (blob[2:-1].astype(np.int64) << 16) | (blob[3:].astype(np.int64) << 24))
            d = np.where(d >= 1 << 31, d - (1 << 32), d)
            at = s["va"] + start + np.arange(len(d), dtype=np.int64)
            hit = at + 4 + d
            idx = np.searchsorted(tg, hit)
            ok = (idx < len(tg)) & (tg[np.minimum(idx, len(tg) - 1)] == hit)
            for i in np.nonzero(ok)[0]:
                out.append((int(at[i]), int(hit[i])))
    return out


def calls_in(pe: PE, begin, end):
    """RVAs called by E8 rel32 inside [begin, end)."""
    off = pe.rva_to_off(begin)
    if off is None:
        return []
    code = pe.data[off:off + (end - begin)]
    out = []
    for m in re.finditer(rb"\xE8", code):
        i = m.start()
        if i + 5 <= len(code):
            out.append(begin + i + 5 + struct.unpack_from("<i", code, i + 1)[0])
    return out


def func_of(funcs, rva):
    i = int(np.searchsorted(funcs[:, 0], rva, side="right")) - 1
    if i >= 0 and funcs[i, 0] <= rva < funcs[i, 1]:
        return int(funcs[i, 0]), int(funcs[i, 1])
    return None


def report(pe: PE, pattern, max_funcs=200):
    want = strings(pe, pattern)
    allstr = strings(pe)
    funcs = pe.functions()
    lines = [f"{len(want)} strings match /{pattern}/; {len(funcs)} functions in .pdata"]
    for rva, (t, k) in sorted(want.items(), key=lambda kv: kv[1][0].lower()):
        lines.append(f"  {pe.image_base + rva:#x} {k} {t!r}")
    refs = rip_refs(pe, want)
    by_func = {}
    for at, tgt in refs:
        f = func_of(funcs, at)
        by_func.setdefault(f, set()).add(tgt)
    lines.append(f"{len(refs)} references in {len(by_func)} functions")
    ref_all = None
    for f, tg in sorted(by_func.items(), key=lambda kv: (kv[0] is None, kv[0] or (0, 0)))[:max_funcs]:
        if f is None:
            lines.append("\n(references outside any .pdata function): " + ", ".join(repr(want[t][0]) for t in tg))
            continue
        if ref_all is None:
            ref_all = {}
            for at, tgt in rip_refs(pe, allstr):
                g = func_of(funcs, at)
                if g is not None:
                    ref_all.setdefault(g, []).append(allstr[tgt][0])
        b, e = f
        lines.append(f"\nfunction {pe.image_base + b:#x} ({e - b} bytes): matches " + ", ".join(
            repr(want[t][0]) for t in sorted(tg)))
        lines.append("  strings: " + "; ".join(repr(s) for s in dict.fromkeys(ref_all.get(f, []))))
        for c in dict.fromkeys(calls_in(pe, b, e)):
            g = func_of(funcs, c)
            if g is None:
                continue
            ss = list(dict.fromkeys(ref_all.get(g, [])))
            if ss:
                lines.append(f"  calls {pe.image_base + c:#x}: " + "; ".join(repr(s) for s in ss[:12])
                             + (" ..." if len(ss) > 12 else ""))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", required=True)
    ap.add_argument("--pattern", default=DEFAULT)
    ap.add_argument("--out", default="")
    ap.add_argument("--max-funcs", type=int, default=200)
    a = ap.parse_args(argv)
    with open(a.exe, "rb") as f:
        pe = PE(f.read())
    lines = report(pe, a.pattern, a.max_funcs)
    text = "\n".join(lines)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("\n".join(lines[:40]) + (f"\n... ({len(lines)} lines) -> {a.out}" if len(lines) > 40 else ""))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
