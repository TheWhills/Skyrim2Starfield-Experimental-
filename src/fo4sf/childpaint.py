"""A Skyrim child's own face paint carried onto Starfield's child head (2026-11-19).

Owner (16:26) on Frodnar: "I can't figure out why it looks like he's someone ethnic or someone doing whiteface" - his
face skin was Starfield's painted child face (its own lid shading, smooth even skin), lightened. His Skyrim FaceGen
tint (facegendata/facetint/<plugin>/<FormID>.dds) holds what makes him him: freckles, rosy cheeks, brows, lips.

How: the feature-matched shape (childshape) puts each Starfield head vertex on the Skyrim face; its closest point
there gives a Skyrim UV. Starfield's triangles are drawn in Starfield's UV space carrying those Skyrim UVs, the tint is
read through them, and its colour relative to its own skin (median) multiplies a softened Starfield face texture
(its painted features blurred away on the face, kept elsewhere). Off the face (ears, neck, scalp, eye and mouth
insides) the Starfield texture stays as it is, with a feathered edge.
"""
from typing import Dict, Tuple

import numpy as np

from fo4sf import childshape
from fo4sf.textures import linear_to_srgb, srgb_to_linear

REACH = 0.008        # m: a Starfield vertex this far or farther from the Skyrim face takes no paint (fading from half)
BLUR = 0.02          # of the texture size: the Starfield face's painted features softened away under the paint
FEATHER = 0.015      # of the texture size: the painted area's edge
STRENGTH = 0.9       # the paint's contrast against its own skin (1 = as in Skyrim; a little less on Starfield's
                     # lighting: Frodnar's freckles and cheeks read grimy at full strength on the preview)
CHROMA = 1.4         # the paint's colour against its skin, apart from its lightness (2026-11-19, owner: "maybe we
                     # need to darken/pinken the lips and cheek" - the blur takes Starfield's own lip colour away,
                     # and the Skyrim tint's lips / cheeks are only a little redder than its skin)
LIP_TINT = (0.80, 0.56, 0.58)   # linear-light multiplier on the lips (2026-11-19, owner: "his lips still look light,
                                # and off in a way"; the goal shot: rosy, darker lips)
EYE_CHROMA = 1.0     # the colour boost around the eyes (owner's close-up: raw red lower lids at CHROMA 2)
GRAIN = 0.004        # of the texture size: detail finer than this (pores, grain) is kept from Starfield's face under
                     # the paint; only the features between it and BLUR are softened away (2026-11-19, owner's goal
                     # shot vs ours: ours airbrushed - the blur had taken the skin grain too)
# 2026-11-19 (owner's goal shot): CHROMA 2.0 -> 1.4: the cheeks and nose read as blush / sunburn; the lips have LIP_TINT.
VERSION = 5


def barycentric(p, a, b, c) -> np.ndarray:
    """(N, 3) barycentric weights of points p on triangles (a, b, c) (rows), clipped and renormalised."""
    v0, v1, v2 = b - a, c - a, p - a
    d00 = (v0 * v0).sum(1)
    d01 = (v0 * v1).sum(1)
    d11 = (v1 * v1).sum(1)
    d20 = (v2 * v0).sum(1)
    d21 = (v2 * v1).sum(1)
    den = np.where(np.abs(d00 * d11 - d01 * d01) < 1e-20, 1e-20, d00 * d11 - d01 * d01)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    out = np.clip(np.stack([1 - v - w, v, w], 1), 0, 1)
    return out / np.maximum(out.sum(1, keepdims=True), 1e-12)


def lip_eye_weights(v, eyes, mouth) -> Tuple[np.ndarray, np.ndarray]:
    """(lips, eye surroundings) weights per Starfield head vertex (model space, +Y forward, +Z up): the lips an
    ellipse around the mouth centre (24 mm across each way, 9 mm up / down, on the front), fading over its outer
    third; the eye surroundings within 20 mm of an eye opening's centre, fading over 8 mm."""
    v = np.asarray(v, float)
    m = np.asarray(mouth, float)
    r = np.sqrt(((v[:, 0] - m[0]) / 0.024) ** 2 + ((v[:, 2] - m[2]) / 0.009) ** 2)
    lips = np.clip((1.0 - r) / 0.33, 0, 1) * (v[:, 1] > m[1] - 0.008)
    d = np.min([np.linalg.norm(v - c, axis=1) for c in np.asarray(eyes, float)], axis=0)
    eye_w = np.clip((0.020 - d) / 0.008, 0, 1)
    return lips.astype(float), eye_w


def upright_uv(uv, v, eyes, mouth, near: float = 0.02) -> Tuple[np.ndarray, bool]:
    """(uv, flipped): UVs turned so the face reads upright in the texture (rows top to bottom: the eyes above the
    mouth, as Starfield's child face tone textures and Skyrim's face tints are painted): when the vertices near the
    eyes have a larger v than those near the mouth, v becomes 1 - v. A guard on the UV convention (unverified for
    Starfield's .mesh uv1)."""
    uv = np.asarray(uv, float)
    v = np.asarray(v, float)
    ne = np.min([np.linalg.norm(v - c, axis=1) for c in np.asarray(eyes, float)], axis=0) < near
    nm = np.linalg.norm(v - np.asarray(mouth, float), axis=1) < near
    if not ne.any() or not nm.any():
        return uv, False
    if uv[ne, 1].mean() > uv[nm, 1].mean():
        out = uv.copy()
        out[:, 1] = 1.0 - out[:, 1]
        return out, True
    return uv, False


def vertex_sky_uv(points, sky_v, sky_t, sky_uv, weight) -> Tuple[np.ndarray, np.ndarray]:
    """(Skyrim UV per point (N, 2), weight (N,)): each point's closest point on the Skyrim face, its UV there; weight
    the given one fading to 0 between REACH / 2 and REACH from the face."""
    sky_v, sky_t, sky_uv = np.asarray(sky_v, float), np.asarray(sky_t, int), np.asarray(sky_uv, float)
    tgt, dist, j = childshape.closest_points(np.asarray(points, float), sky_v, sky_t)
    tri = sky_t[j]
    bc = barycentric(tgt, sky_v[tri[:, 0]], sky_v[tri[:, 1]], sky_v[tri[:, 2]])
    uv = (bc[:, :, None] * sky_uv[tri]).sum(1)
    w = np.asarray(weight, float) * np.clip((REACH - dist) / (REACH / 2), 0, 1)
    return uv, w


def raster(uv, tris, attrs, size: int) -> Tuple[np.ndarray, np.ndarray]:
    """(image (size, size, C), covered (size, size) bool): triangles drawn in UV space (u right, v down, 0-1;
    pixel centres), per-vertex attrs (N, C) interpolated across each."""
    uv = np.asarray(uv, float) * size - 0.5
    attrs = np.asarray(attrs, float)
    img = np.zeros((size, size, attrs.shape[1]))
    cov = np.zeros((size, size), bool)
    for t in np.asarray(tris, int):
        p = uv[t]
        x0, y0 = np.floor(p.min(0)).astype(int)
        x1, y1 = np.ceil(p.max(0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, size - 1), min(y1, size - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        q = np.stack([xs.ravel(), ys.ravel()], 1).astype(float)
        (ax, ay), (bx, by), (cx, cy) = p
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        l0 = ((by - cy) * (q[:, 0] - cx) + (cx - bx) * (q[:, 1] - cy)) / den
        l1 = ((cy - ay) * (q[:, 0] - cx) + (ax - cx) * (q[:, 1] - cy)) / den
        l2 = 1 - l0 - l1
        inside = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
        if not inside.any():
            continue
        lam = np.stack([l0, l1, l2], 1)[inside]
        qi = q[inside].astype(int)
        img[qi[:, 1], qi[:, 0]] = lam @ attrs[t]
        cov[qi[:, 1], qi[:, 0]] = True
    return img, cov


def sample(img, uv) -> np.ndarray:
    """Bilinear samples of img (H, W, C) at UVs (..., 2) (0-1, pixel centres; clamped)."""
    h, w = img.shape[:2]
    x = np.clip(np.asarray(uv[..., 0], float) * w - 0.5, 0, w - 1)
    y = np.clip(np.asarray(uv[..., 1], float) * h - 0.5, 0, h - 1)
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    img = np.asarray(img, float)
    return (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x1] * fx * (1 - fy) +
            img[y1, x0] * (1 - fx) * fy + img[y1, x1] * fx * fy)


def blur(img, radius: int, passes: int = 3) -> np.ndarray:
    """Box blur `passes` times (about a Gaussian), edges clamped; img (H, W) or (H, W, C)."""
    out = np.asarray(img, float)
    if radius < 1:
        return out
    for _ in range(passes):
        for ax in (0, 1):
            pad = [(0, 0)] * out.ndim
            pad[ax] = (radius + 1, radius)
            c = np.cumsum(np.pad(out, pad, mode="edge"), axis=ax)
            n = out.shape[ax]
            hi = np.take(c, np.arange(2 * radius + 1, 2 * radius + 1 + n), axis=ax)
            lo = np.take(c, np.arange(0, n), axis=ax)
            out = (hi - lo) / (2 * radius + 1)
    return out


LUMA = np.array([0.2126, 0.7152, 0.0722])


def paint_factor(ratio, strength: float = STRENGTH, chroma: float = CHROMA) -> np.ndarray:
    """Linear-light multiplier from the tint's ratio to its own skin (..., 3): its lightness (luma) to the power
    strength, its colour (the ratio over its luma) to the power chroma - lips and cheeks pinker, freckles no
    darker."""
    ratio = np.maximum(np.asarray(ratio, float), 1e-4)
    luma = np.maximum((ratio * LUMA).sum(-1, keepdims=True), 1e-4)
    return np.power(luma, strength) * np.power(ratio / luma, chroma)


def paint_layer(sf_uv, sf_t, sky_uv_per_vertex, weight, tint_rgba, size: int, lips=None, eyes=None) -> Dict:
    """{"factor": (size, size, 3) linear-light multiplier (1 off the face), "weight": (size, size)}: the Skyrim tint
    read through each Starfield pixel's Skyrim UV, over its own skin colour (median where the weight is full).
    lips / eyes (V,) 0-1: where the lips are (LIP_TINT on them) and the eye surroundings (colour boost EYE_CHROMA
    there)."""
    n = len(np.asarray(weight))
    lips = np.zeros(n) if lips is None else np.asarray(lips, float)
    eyes = np.zeros(n) if eyes is None else np.asarray(eyes, float)
    attrs = np.concatenate([np.asarray(sky_uv_per_vertex, float), np.asarray(weight, float)[:, None],
                            lips[:, None], eyes[:, None]], 1)
    img, cov = raster(sf_uv, sf_t, attrs, size)
    lip_img = np.where(cov, img[..., 3], 0.0)[..., None]
    eye_img = np.where(cov, img[..., 4], 0.0)[..., None]
    w = np.where(cov, img[..., 2], 0.0)
    feather = max(1, int(round(FEATHER * size)))
    w = np.minimum(w, blur(w, feather)) if feather > 1 else w
    tint = srgb_to_linear(sample(np.asarray(tint_rgba)[..., :3].astype(float), img[..., :2]))
    full = w > 0.9
    if full.sum() < 16:
        raise ValueError("the Skyrim face covers almost none of the Starfield head's texture")
    skin = np.median(tint[full], axis=0)
    chroma = CHROMA + (EYE_CHROMA - CHROMA) * eye_img
    factor = paint_factor(tint / np.maximum(skin, 1e-4), STRENGTH, chroma)
    factor = factor * (1.0 + lip_img * (np.array(LIP_TINT) - 1.0))
    factor = 1.0 + w[..., None] * (factor - 1.0)
    return {"factor": factor, "weight": w, "lips": lip_img[..., 0], "tint_skin": [float(x) for x in skin]}


def painted_face(face_rgba, layer, blur_frac: float = BLUR) -> np.ndarray:
    """Starfield face texture (RGBA uint8) with the paint layer on it: under the paint its own painted features
    softened (blurred, by the paint's weight) but its fine grain kept (detail under GRAIN of the size), then
    multiplied by the paint's factor (linear light)."""
    face = np.asarray(face_rgba)
    size = face.shape[0]
    if layer["factor"].shape[:2] != face.shape[:2]:
        raise ValueError(f"paint layer {layer['factor'].shape[:2]} for a {face.shape[:2]} texture")
    lin = srgb_to_linear(face[..., :3].astype(float))
    # no softening on the lips: Starfield's painted lip outline (vermilion border, cupid's bow) stays crisp under the
    # lip colour (2026-11-19, owner: "the mouth just looks so different" - ours had no lip edge at all)
    lips = layer.get("lips")
    w = (layer["weight"] * (1.0 - (lips if lips is not None else 0.0)))[..., None]
    soft = blur(lin, max(1, int(round(blur_frac * size))))
    fine = blur(lin, max(1, int(round(GRAIN * size))), passes=2)
    grain = lin / np.maximum(fine, 1e-4)                 # the fine detail, as a ratio around 1
    base = lin * (1 - w) + soft * grain * w
    out = linear_to_srgb(np.clip(base * layer["factor"], 0.0, 1.0))
    return np.concatenate([np.round(out).clip(0, 255).astype(np.uint8), face[..., 3:4]], -1)
