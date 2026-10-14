"""Turntable GIF of a converted Starfield static, rendered from the files we wrote (not from the Fallout 4 source).

Needs Pillow + numpy (not installed by default):  pip install pillow numpy
usage: python render_preview.py <staging dir> <nif path relative to staging> <out.gif> [caption lines...]
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from fo4sf import nif, sfmesh, sfnif  # noqa: E402


def load_geometry(staging, nif_rel):
    n = nif.parse(open(os.path.join(staging, *nif_rel.split("/")), "rb").read())
    verts, tris = [], []
    for k, b in enumerate(n.blocks):
        if n.type_of(k) != "BSGeometry":
            continue
        ref = sfnif.parse_bsgeometry(b).meshes[0]
        path = os.path.join(staging, "geometries", *ref.path.decode().split("\\")) + ".mesh"
        m = sfmesh.parse(open(path, "rb").read())
        base = len(verts)
        verts += [sfmesh.decode_position(p, m.scale) for p in m.positions]
        tris += [(a + base, b_ + base, c + base) for a, b_, c in m.triangles]
    return np.array(verts, dtype=float), np.array(tris, dtype=int)


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render(staging, nif_rel, out_gif, caption):
    v, t = load_geometry(staging, nif_rel)
    v = v - (v.min(0) + v.max(0)) / 2
    radius = np.abs(v).max()
    W, H, VIEW = 880, 440, 440
    light = np.array([0.4, -0.5, 0.75]); light /= np.linalg.norm(light)
    base_col = np.array([120, 170, 220], dtype=float)
    frames = []
    for f in range(72):
        a = 2 * math.pi * f / 72
        ca, sa = math.cos(a), math.sin(a)
        Rz = np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]])
        el = math.radians(22)
        Rx = np.array([[1, 0, 0], [0, math.cos(el), -math.sin(el)], [0, math.sin(el), math.cos(el)]])
        P = (v @ Rz.T) @ Rx.T                      # x right, y depth (away), z up
        scale = VIEW * 0.36 / radius
        sx = VIEW / 2 + P[:, 0] * scale
        sy = VIEW * 0.55 - P[:, 2] * scale
        tri = t
        p0, p1, p2 = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
        nrm = np.cross(p1 - p0, p2 - p0)
        ln = np.linalg.norm(nrm, axis=1, keepdims=True); ln[ln == 0] = 1
        nrm = nrm / ln
        # two-sided lighting: orient the normal toward the viewer (-y is toward camera)
        flip = nrm[:, 1] > 0
        nrm[flip] *= -1
        Lr = (light @ Rx.T)
        shade = 0.28 + 0.72 * np.clip(nrm @ Lr, 0, 1)
        depth = (p0[:, 1] + p1[:, 1] + p2[:, 1]) / 3
        order = np.argsort(-depth)
        img = Image.new("RGB", (W, H), (16, 20, 28))
        d = ImageDraw.Draw(img)
        d.ellipse([VIEW * 0.18, VIEW * 0.78, VIEW * 0.82, VIEW * 0.92], fill=(28, 34, 46))
        for i in order:
            col = tuple(int(c) for c in np.clip(base_col * shade[i], 0, 255))
            d.polygon([(sx[tri[i, 0]], sy[tri[i, 0]]), (sx[tri[i, 1]], sy[tri[i, 1]]), (sx[tri[i, 2]], sy[tri[i, 2]])], fill=col)
        x0 = VIEW + 14
        y = 26
        for j, line in enumerate(caption):
            fnt = font(22 if j == 0 else 15)
            colr = (255, 214, 120) if j == 0 else ((140, 220, 160) if line.startswith("OK") else (200, 206, 216))
            if line.startswith("NOT"):
                colr = (255, 150, 120)
            d.text((x0, y), line, fill=colr, font=fnt)
            y += 34 if j == 0 else 24
        frames.append(img)
    frames[0].save(out_gif, save_all=True, append_images=frames[1:], duration=45, loop=0, optimize=True)
    return len(t), len(v)


if __name__ == "__main__":
    staging, nif_rel, out = sys.argv[1:4]
    n_tri, n_vert = render(staging, nif_rel, out, sys.argv[4:])
    print(f"wrote {out}: {n_vert} verts, {n_tri} tris")
