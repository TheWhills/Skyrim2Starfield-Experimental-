"""Header of Starfield .wem files: format tag (codec), channels, sample rate, chunks. Read-only.

2026-11-20 (owner's forge test, verified): an unreplaced vanilla food-station event (Drawer_Close) and the welder's
ITM_Microscope_Up play from the forge's <audio> foley, while the events whose streamed .wem files sound_swap replaced
are silent - our files are not decoded. A streamed sound is decoded with the codec its bank names, so the replacement
has to be in the vanilla file's format: this prints both side by side.

    python -I scripts\\armor\\wem_info.py --sf-data "<Starfield>\\Data" --id 604310419 --id 578611756 ^
        --file "<MO2 mods>\\S2S Sounds\\Sound\\Soundbanks\\604310419.wem"
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "src"))

CODECS = {0x0001: "PCM", 0xFFFE: "PCM (extensible)", 0x0002: "ADPCM", 0x0165: "XMA2", 0x0166: "XMA2",
          0xFFFF: "Vorbis", 0x3039: "Opus (Wwise NX)", 0x3040: "Opus", 0x3041: "Opus WEM", 0x8311: "PTADPCM"}


def wem_header(data: bytes) -> dict:
    """{riff, format_tag, codec, channels, sample_rate, avg_bytes, block_align, bits, chunks, size}."""
    out = {"size": len(data), "riff": data[:4].decode("latin-1"), "chunks": []}
    if len(data) < 12 or data[:4] not in (b"RIFF", b"RIFX"):
        return out
    p = 12
    while p + 8 <= len(data):
        tag, n = data[p:p + 4], struct.unpack_from("<I", data, p + 4)[0]
        out["chunks"].append(f"{tag.decode('latin-1')}:{n}")
        if tag == b"fmt " and n >= 16:
            ft, ch, sr, abps, ba, bits = struct.unpack_from("<HHIIHH", data, p + 8)
            out.update(format_tag=f"0x{ft:04X}", codec=CODECS.get(ft, "?"), channels=ch, sample_rate=sr,
                       avg_bytes=abps, block_align=ba, bits=bits, fmt_size=n)
        p += 8 + n + (n & 1)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sf-data", required=True)
    ap.add_argument("--id", action="append", default=[], help="vanilla streamed file id (repeatable)")
    ap.add_argument("--file", action="append", default=[], help="a .wem file on disk (repeatable)")
    a = ap.parse_args(argv)
    from fo4sf import ba2
    want = {f"{i}.wem" for i in a.id}
    for fn in sorted(os.listdir(a.sf_data)):
        if not (fn.lower().startswith("starfield - wwisesounds") and fn.lower().endswith(".ba2")) or not want:
            continue
        arc = ba2.Ba2(os.path.join(a.sf_data, fn))
        for i, n in enumerate(arc.names):
            base = n.replace("\\", "/").split("/")[-1].lower()
            if base in want:
                print(f"{fn}: {n}: {wem_header(arc.read(i))}")
    for f in a.file:
        with open(f, "rb") as fh:
            print(f"{f}: {wem_header(fh.read())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
