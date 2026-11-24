"""How much ground cover Starfield gives each terrain layer at one sample (model of Starfield.exe 1.16.244).

Read from the decompiled grass code (docs/re/ground-cover-density.md, 2026-11-24):
  * FUN_1409a0b50 takes a quadrant's texture bytes 0, 1, 2, 3, 4 and 6 (bytes 5 and 7 are not read), subtracts 1 from
    each (palette index; byte 0 = no layer) and cuts the list at the first empty one: byte 6 counts only when bytes
    0..4 are all set. The sample word holds five 3-bit alphas, layer i in bits 3i..3i+2, scaled by 1/7.
  * FUN_1409a07d0 blends front to back: w_i = rest * a_i for every layer but the last, the last layer gets what is
    left (rest). With six layers the byte-6 layer (the LDefault mask texture) gets prod(1 - a_i) over the five
    alphas, so any alpha of 7 leaves it nothing.
  * FUN_1409a9210: a cover (GCVR) on a layer grows a grass with weight w * density / 100, or 0 when w is below the
    cover's threshold (GCVR + 0x88, a 0..1 value).
Only palette entries that carry a GCVR grow anything; for an overlay that means its LDefault placeholder textures
(FUN_1409a9570). This module only does the arithmetic.

    python -I scripts\\re\\ground_cover_weights.py --bytes 50 43 52 42 34 --byte6 57 --alphas 0 0 0 7 0

prints every layer's weight (the --alphas order is the bit order: alpha i = bits 3i..3i+2 = layer of byte i).
"""
import argparse
import sys

ALPHA_SLOTS = 5
LAYER_BYTES = (0, 1, 2, 3, 4, 6)


def layer_indices(quadrant):
    """Palette indices (byte - 1) of the layers the grass sampler uses, from a quadrant's 7 or 8 bytes."""
    out = []
    for b in LAYER_BYTES:
        value = quadrant[b] if b < len(quadrant) else 0
        if value == 0:
            break
        out.append(value - 1)
    return out


def unpack_alphas(word):
    """Five 3-bit alphas (0..7) from a sample word, layer i in bits 3i..3i+2."""
    return [(word >> (3 * i)) & 7 for i in range(ALPHA_SLOTS)]


def pack_alphas(alphas):
    """The sample word for five 0..7 alphas (inverse of unpack_alphas; bit 15 stays 0)."""
    word = 0
    for i, a in enumerate(alphas):
        if not 0 <= a <= 7:
            raise ValueError(f"alpha {a} not in 0..7")
        word |= a << (3 * i)
    return word


def blend(count, alphas):
    """Weights of `count` layers (FUN_1409a07d0): every layer but the last takes its alpha of what is left, the
    last layer takes the rest. alphas are 0..7 integers (only the first count - 1 are used)."""
    if count <= 0:
        return []
    if count == 1:
        return [1.0]
    rest = 1.0
    weights = []
    for i in range(count - 1):
        a = alphas[i] / 7.0 if i < len(alphas) else 0.0
        w = rest * a
        weights.append(w)
        rest -= w
    weights.append(rest)
    return weights


def layer_weights(quadrant, word):
    """[(palette index, weight)] for one sample: quadrant bytes + sample word."""
    idx = layer_indices(quadrant)
    return list(zip(idx, blend(len(idx), unpack_alphas(word))))


def cover_weight(weight, threshold, density_percent):
    """Grass weight after the cover's threshold and the grass density (FUN_1409a9210)."""
    if weight < threshold:
        return 0.0
    return weight * density_percent / 100.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bytes", type=int, nargs=5, required=True, help="quadrant bytes 0..4")
    ap.add_argument("--byte6", type=int, default=0, help="quadrant byte 6 (the mask texture), 0 = none")
    ap.add_argument("--alphas", type=int, nargs=5, required=True, help="alphas 0..7 of layers 0..4 (bit order)")
    ap.add_argument("--threshold", type=float, default=0.0, help="cover threshold (GCVR, 0..1)")
    a = ap.parse_args(argv)
    quadrant = list(a.bytes) + [0, a.byte6, 0]
    word = pack_alphas(a.alphas)
    for pos, (index, w) in enumerate(layer_weights(quadrant, word)):
        source = "byte 6" if pos == 5 else f"byte {pos}"
        verdict = "passes the threshold" if w >= a.threshold and w > 0 else "no cover"
        print(f"{source}: table entry {index + 1} weight {w:.3f} -> {verdict} (grows only if the entry has a GCVR)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
