"""Skyrim head -> Starfield head correspondence on the surface, for moving a displacement field (a race morph, a
FaceGen face) from Skyrim's ~900-vertex head onto Starfield's ~15,000-vertex head.

Why (2026-11-09, the owner's race_probe run, measured on its race_view.html data): the inverse-distance average over
the 4 nearest Skyrim vertices (facefit.transfer) is blind to which side of a thin part a point is on. It closed the
orc's underbite (Starfield lip vertices averaged Skyrim's upper and lower lip), tore a strip behind the ears, and jumped
wherever the set of 4 nearest changed. Its smoothing also treated the 464 vertex pairs split along Starfield's UV
seams as unrelated, so they drifted apart by up to 6.4 mm: the cracks on the scalp.

Here every Starfield vertex gets one point on the Skyrim surface (a triangle and barycentric weights), chosen by:
  - distance to the triangle (closest point on it), counting only triangles that face the same way (normals),
  - agreement with its mesh neighbours: the neighbours' points must be close along the Skyrim surface (edge
    geodesics), not just in space; Skyrim's upper and lower lip are millimetres apart in space but centimetres apart
    around the mouth corner,
  - lip side: on both heads, d_up / (d_up + d_down) with d the surface distance to a point above / below the mouth.
    Skyrim's mouth is a hole; Starfield's is a closed pocket (the lips meet through the inner mouth), so the contact
    rows of Starfield's lips get the side they belong to, which geometry alone does not tell.
Solved as a small labelling problem over each vertex's 8 nearest compatible triangles (alternating updates of half the
vertices so it settles). Fields are then sampled with the weights, averaged over seam-split vertices and smoothed on
the welded mesh, so seams cannot open.
Measured on the owner's data: seam splits 0 (were up to 6.4 mm); the orc's open underbite kept; see docs/npc/races.md.
Directions (above the mouth, the front) are in model space: +Z up, +Y forward (both games).
"""
import heapq
from typing import Dict, List, Optional

import numpy as np


def weld_index(v: np.ndarray, tol: float = 1e-5):
    """(inv, counts): inv[i] = the welded vertex of vertex i (vertices at the same position, e.g. split along UV
    seams, share one), counts per welded vertex."""
    key = np.round(np.asarray(v, float) / tol).astype(np.int64)
    _, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    return inv.ravel(), cnt


def welded(field: np.ndarray, inv: np.ndarray) -> np.ndarray:
    """Per welded vertex: the mean of its members' values."""
    out = np.zeros((inv.max() + 1,) + field.shape[1:])
    np.add.at(out, inv, field)
    return out / np.bincount(inv).reshape((-1,) + (1,) * (field.ndim - 1))


def vertex_normals(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    v = np.asarray(v, float)
    n = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    vn = np.zeros_like(v)
    for i in range(3):
        np.add.at(vn, f[:, i], n)
    return vn / np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)


def edges(f: np.ndarray) -> np.ndarray:
    f = np.asarray(f, int)
    return np.unique(np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), 1), axis=0)


def closest_on_triangles(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray):
    """Closest points of points p (N, 3) on triangles (a, b, c each (T, 3)): barycentrics (N, T, 3) and squared
    distances (N, T). Ericson, Real-Time Collision Detection 5.1.5, vectorised."""
    ab, ac = b - a, c - a
    ap, bp, cp = p[:, None] - a[None], p[:, None] - b[None], p[:, None] - c[None]
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    den = va + vb + vc
    den = np.where(np.abs(den) < 1e-30, 1e-30, den)
    v, w = vb / den, vc / den
    with np.errstate(divide="ignore", invalid="ignore"):
        vab, vac, wbc = d1 / (d1 - d3), d2 / (d2 - d6), (d4 - d3) / ((d4 - d3) + (d5 - d6))
    bary = np.stack([1 - v - w, v, w], -1)
    one, zero = np.ones_like(d1), np.zeros_like(d1)

    def put(m, b0, b1, b2):
        bary[m] = np.stack([b0[m], b1[m], b2[m]], -1)
    put((vc <= 0) & (d1 >= 0) & (d3 <= 0), 1 - vab, vab, zero)                 # edge ab
    put((vb <= 0) & (d2 >= 0) & (d6 <= 0), 1 - vac, zero, vac)                 # edge ac
    put((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), zero, 1 - wbc, wbc)   # edge bc
    put((d6 >= 0) & (d5 <= d6), zero, zero, one)                              # corner c
    put((d3 >= 0) & (d4 <= d3), zero, one, zero)                              # corner b
    put((d1 <= 0) & (d2 <= 0), one, zero, zero)                               # corner a
    q = bary[..., :1] * a[None] + bary[..., 1:2] * b[None] + bary[..., 2:] * c[None]
    return bary, ((q - p[:, None]) ** 2).sum(-1)


def main_triangles(f: np.ndarray, nverts: int, min_share: float = 0.05) -> np.ndarray:
    """The triangles of the connected pieces with at least min_share of all triangles: small loose pieces out (Skyrim's
    female head has 37 single triangles floating inside the lips, which pulled the lip side off)."""
    f = np.asarray(f, int)
    par = np.arange(nverts)

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for a, b, c in f.tolist():
        ra = find(a)
        par[find(b)] = ra
        par[find(c)] = ra
    piece = np.array([find(int(t[0])) for t in f])
    _, inv, cnt = np.unique(piece, return_inverse=True, return_counts=True)
    return f[cnt[inv.ravel()] >= min_share * len(f)]


def boundary_loops(f: np.ndarray) -> List[np.ndarray]:
    """Vertex sets of the open-edge loops, largest first."""
    e = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), 1)
    u, c = np.unique(e, axis=0, return_counts=True)
    par: Dict[int, int] = {}

    def find(x):
        while par.get(x, x) != x:
            x = par[x]
        return x
    b = u[c == 1]
    for a, d in b.tolist():
        ra, rd = find(a), find(d)
        if ra != rd:
            par[ra] = rd
    comp: Dict[int, set] = {}
    for a, d in b.tolist():
        comp.setdefault(find(a), set()).update((a, d))
    return [np.array(sorted(s)) for s in sorted(comp.values(), key=len, reverse=True)]


def mouth_hole(v_model: np.ndarray, f: np.ndarray, min_size: int = 6) -> Optional[np.ndarray]:
    """The mouth opening of a head with an open mouth (Skyrim's): of the open-edge loops other than the largest (the
    neck), the frontmost (+Y) with at least min_size vertices; None if there is none (Starfield's closed mouth)."""
    loops = [l for l in boundary_loops(f)[1:] if len(l) >= min_size]
    return max(loops, key=lambda l: v_model[l, 1].mean()) if loops else None


def edge_geodesics(v: np.ndarray, f: np.ndarray, sources) -> np.ndarray:
    """(len(sources), V) shortest paths along mesh edges (inf where unreachable)."""
    e = edges(f)
    length = np.linalg.norm(v[e[:, 0]] - v[e[:, 1]], axis=1)
    adj: List[list] = [[] for _ in range(len(v))]
    for (a, b), l in zip(e.tolist(), length.tolist()):
        adj[a].append((b, l))
        adj[b].append((a, l))
    out = np.full((len(sources), len(v)), np.inf)
    for k, s in enumerate(sources):
        d = out[k]
        d[s] = 0.0
        h = [(0.0, int(s))]
        while h:
            ds, u = heapq.heappop(h)
            if ds > d[u]:
                continue
            for w, l in adj[u]:
                nd = ds + l
                if nd < d[w]:
                    d[w] = nd
                    heapq.heappush(h, (nd, w))
    return out


def lip_side(v: np.ndarray, f: np.ndarray, up: int, down: int) -> np.ndarray:
    """0 near the vertex above the mouth, 1 near the one below, by surface distance (0.5 where unreachable)."""
    du, dd = edge_geodesics(v, f, [up, down])
    with np.errstate(invalid="ignore"):
        s = du / (du + dd)
    return np.where(np.isfinite(s), s, 0.5)


def lip_anchors(v_model: np.ndarray, centre: np.ndarray, offset: float, allowed: Optional[np.ndarray] = None):
    """Vertices nearest the points offset above / below the mouth centre on the front (y > centre y - offset / 2)."""
    ok = v_model[:, 1] > centre[1] - offset / 2
    if allowed is not None:
        ok &= allowed

    def near(p):
        d = np.linalg.norm(v_model - p, axis=1)
        d[~ok] = np.inf
        return int(d.argmin())
    return near(centre + [0, 0, offset]), near(centre - [0, 0, offset])


class Correspondence:
    """Per dst vertex: src triangle corners (N, 3) and barycentric weights (N, 3); inv / dst_f for welded smoothing."""

    def __init__(self, corners, bary, inv, dst_f, report):
        self.corners, self.bary, self.inv, self.dst_f, self.report = corners, bary, inv, dst_f, report

    def sample(self, field: np.ndarray) -> np.ndarray:
        return np.einsum("nk,nkc->nc", self.bary, np.asarray(field, float)[self.corners])

    def smooth(self, field: np.ndarray, iterations: int, keep: float = 0.5) -> np.ndarray:
        """Average over seam-split vertices, then smooth on the welded mesh (facefit.smooth_field)."""
        from .facefit import smooth_field
        g = welded(np.asarray(field, float), self.inv)
        if iterations > 0:
            g = smooth_field(g, self.inv[self.dst_f], iterations=iterations, keep=keep)
        return g[self.inv]

    def transfer(self, field: np.ndarray, smooth: int = 0) -> np.ndarray:
        return self.smooth(self.sample(field), smooth)

    mouth = None        # set by correspond when the lip term ran: see fit_lip_edges

    def fit_lip_edges(self, disp: np.ndarray, field: np.ndarray, reach: float = 0.006, radius: float = 0.015):
        """(disp, report): disp (per dst vertex) with the lips' visible edges moving up / down like Skyrim's.

        2026-11-10 (owner's race_view: the female Orc's lips gape on Starfield's head where Skyrim's look closed):
        seen from the front, a lip's visible edge is its lowest (upper lip) / highest (lower lip) point per column
        across the mouth, near the mouth and not in the pocket behind. On Skyrim's head (sides from the lip term, the
        mouth hole's edges for "near"; reach from the edge plus half the opening's height) these edges are measured
        before and after the field: Skyrim's female Orc mouth edges part by ~5 mm, but its upper lip's front comes
        down over the lower, so the visible opening hardly changes. Starfield's closed lips meet in rows (the same
        per-column extremes, 2 mm columns); each row vertex gets the vertical move of Skyrim's visible edge at its
        column (interpolated; forward / sideways moves stay as transferred); the change spreads over its own lip,
        fading to nothing at radius. Model axes through to_model. Unchanged without the lip term's data."""
        disp = np.asarray(disp, float)
        if self.mouth is None:
            return disp, {"lip_edges": "no mouth data"}
        m = self.mouth
        field = np.asarray(field, float)
        g = welded(disp, self.inv)
        wv, side = m["dst_v"], m["dst_side"] >= 0.5                 # True: lower lip
        hole, src_v = m["hole"], m["src_v"]
        hup = hole[m["src_side"][hole] < 0.5]
        hdn = hole[m["src_side"][hole] >= 0.5]
        if len(hup) < 2 or len(hdn) < 2:
            return disp, {"lip_edges": "mouth edge not split into upper / lower"}
        ax, fw, lat = m["up_axis"], m["fwd_axis"], m["lat_axis"]
        hz = src_v[hole] @ ax
        reach = reach + (hz.max() - hz.min()) / 2           # the lips meet about mid-way across the opening
        dh = np.linalg.norm(wv[:, None, :] - src_v[hole][None, :, :], axis=2).min(1)
        near = (dh < reach) & (wv @ fw > (src_v[hole] @ fw).mean() - 0.005)   # not the mouth pocket behind
        # the meeting rows: per column across the mouth (2 mm wide), the upper lip's lowest vertex and the lower
        # lip's highest (Starfield's lips join through the pocket, so the rows need not share an edge)
        col = np.floor((wv @ lat) / 0.002).astype(int)
        rows = []
        for lower in (False, True):
            cand = np.where(near & (side == lower))[0]
            z = wv[cand] @ ax
            best = {}
            for v, c, zz in zip(cand.tolist(), col[cand].tolist(), z.tolist()):
                if c not in best or (zz > best[c][1] if lower else zz < best[c][1]):
                    best[c] = (v, zz)
            rows += [v for v, _z in best.values()]
        rows = np.array(sorted(rows), int)
        if not len(rows):
            return disp, {"lip_edges": "no meeting rows near the mouth edge"}
        # Skyrim's visible lip edges: per 6 mm column the upper lip's lowest point and the lower lip's highest, over
        # its lip vertices near the mouth, before and after the field (an overhanging lip front counts: from the
        # front, Skyrim's female Orc lips overlap although its mouth edges part)
        sside = m["src_side"] >= 0.5
        sd = np.linalg.norm(src_v[:, None, :] - src_v[hole][None, :, :], axis=2).min(1)
        snear = (sd < reach) & (src_v @ fw > (src_v[hole] @ fw).mean() - 0.005)
        lat_lo, lat_hi = (src_v[hole] @ lat).min(), (src_v[hole] @ lat).max()

        def edges_of(pos, near_, sides, width):
            """{lower: (column centres, edge heights)} of pos's visible lip edges."""
            c_ = np.floor((pos @ lat) / width).astype(int)
            out_ = {}
            for lower in (False, True):
                idx = np.where(near_ & (sides == lower))[0]
                best = {}
                for v, c, zz in zip(idx.tolist(), c_[idx].tolist(), (pos[idx] @ ax).tolist()):
                    if c not in best or (zz > best[c] if lower else zz < best[c]):
                        best[c] = zz
                ks = sorted(best)
                out_[lower] = (np.array([(k + 0.5) * width for k in ks]), np.array([best[k] for k in ks]))
            return out_
        sb = edges_of(src_v, snear, sside, 0.006)
        sa = edges_of(src_v + field, snear, sside, 0.006)
        corr = np.zeros((len(rows), 3))
        for i, v in enumerate(rows):
            lower = bool(side[v])
            xb, zb = sb[lower]
            xa, za = sa[lower]
            if not len(xb) or not len(xa):
                continue
            x = float(np.clip(wv[v] @ lat, lat_lo, lat_hi))
            dz = float(np.interp(x, xa, za) - np.interp(x, xb, zb))     # Skyrim's visible edge moved this much
            corr[i] = (dz - float(g[v] @ ax)) * ax                       # up / down only; forward stays
        out = g.copy()
        for lower in (False, True):
            r = rows[side[rows] == lower]
            if not len(r):
                continue
            c = corr[side[rows] == lower]
            mine = np.where(side == lower)[0]
            d = np.linalg.norm(wv[mine][:, None, :] - wv[r][None, :, :], axis=2)
            j = d.argmin(1)
            fall = np.clip(1.0 - d[np.arange(len(mine)), j] / radius, 0.0, 1.0) ** 2
            out[mine] += c[j] * fall[:, None]

        def visible(e):
            """Median visible opening (upper edge - lower edge) over the columns both lips have, metres."""
            (xu, zu), (xl, zl) = e[False], e[True]
            if not len(xu) or not len(xl):
                return 0.0
            xs = xu[(xu >= max(xu.min(), xl.min())) & (xu <= min(xu.max(), xl.max()))]
            return float(np.median(np.interp(xs, xu, zu) - np.interp(xs, xl, zl))) if len(xs) else 0.0
        dnear = near
        rep = {"rows": [int((~side[rows]).sum()), int(side[rows].sum())],
               "mean_change_m": round(float(np.linalg.norm(corr, axis=1).mean()), 5),
               "max_change_m": round(float(np.linalg.norm(corr, axis=1).max()), 5),
               "visible_opening_m": {"skyrim_before": round(visible(sb), 5), "skyrim_after": round(visible(sa), 5),
                                     "starfield_base": round(visible(edges_of(wv, dnear, side, 0.002)), 5),
                                     "before": round(visible(edges_of(wv + g, dnear, side, 0.002)), 5),
                                     "after": round(visible(edges_of(wv + out, dnear, side, 0.002)), 5)}}
        return out[self.inv], rep


def correspond(src_v: np.ndarray, src_f: np.ndarray, dst_v: np.ndarray, dst_f: np.ndarray,
               to_model: Optional[np.ndarray] = None, candidates: int = 8, min_dot: float = 0.2,
               sigma_d: float = 0.3, mu: float = 1.0, slack: float = 1.5, lip_weight: float = 1.0,
               lip_sigma: float = 0.1, lip_offset: float = 0.018, iters: int = 40, seed: int = 0,
               chunk: int = 192) -> Correspondence:
    """src (Skyrim base head, already aligned into dst's frame) -> dst (Starfield head). to_model (4x4, dst frame ->
    model space: +Z up, +Y forward) places the mouth; without it the lip term is off. Distances in dst units
    (metres for Starfield); sigma_d, slack in units of the src head's median edge length."""
    src_v, dst_v = np.asarray(src_v, float), np.asarray(dst_v, float)
    sf = main_triangles(src_f, len(src_v))
    df = np.asarray(dst_f, int)
    inv, cnt = weld_index(dst_v)
    wv = welded(dst_v, inv)
    wf = inv[df]
    wn = vertex_normals(wv, wf)
    nw = len(wv)
    e_src = edges(sf)
    h = float(np.median(np.linalg.norm(src_v[e_src[:, 0]] - src_v[e_src[:, 1]], axis=1)))
    # candidates: the nearest triangles facing the same way (others only as a last resort)
    a, b, c = (src_v[sf[:, i]] for i in range(3))
    fn = np.cross(b - a, c - a)
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    C = min(candidates, len(sf))
    chunk = max(8, min(chunk, int(4e6 // max(len(sf), 1))))     # (chunk x triangles) arrays: ~100 MB at most
    T = np.zeros((nw, C), int)
    B = np.zeros((nw, C, 3))
    D2 = np.zeros((nw, C))
    for s in range(0, nw, chunk):
        p = wv[s:s + chunk]
        bc, d2 = closest_on_triangles(p, a, b, c)
        cost = np.where(wn[s:s + chunk] @ fn.T > min_dot, d2, d2 + 1.0)
        j = np.argsort(cost, 1)[:, :C]
        r = np.arange(len(p))[:, None]
        T[s:s + chunk], B[s:s + chunk], D2[s:s + chunk] = j, bc[r, j], cost[r, j]
    U = D2 / (sigma_d * h) ** 2
    report = {"src_triangles": int(len(sf)), "src_loose_triangles": int(len(src_f) - len(sf)),
              "dst_seam_vertices": int((cnt[inv] > 1).sum()), "src_edge_m": round(h, 5)}
    # lip side
    mouth = None
    if to_model is not None and lip_weight > 0:
        src_m = src_v @ to_model[:3, :3].T + to_model[:3, 3]
        dst_m = wv @ to_model[:3, :3].T + to_model[:3, 3]
        hole = mouth_hole(src_m, sf)
        if hole is not None:
            scale = float(np.cbrt(abs(np.linalg.det(to_model[:3, :3]))))
            centre = src_m[hole].mean(0)
            used = np.zeros(len(src_v), bool)
            used[sf.ravel()] = True
            up, down = lip_anchors(src_m, centre, lip_offset * scale, used)
            sup = int(np.linalg.norm(dst_m - src_m[up], axis=1).argmin())
            sdn = int(np.linalg.norm(dst_m - src_m[down], axis=1).argmin())
            ls = lip_side(src_v, sf, up, down)
            ld = lip_side(wv, wf, sup, sdn)
            lc = np.einsum("nck,nck->nc", B, ls[sf[T]])
            U = U + lip_weight * ((lc - ld[:, None]) / lip_sigma) ** 2
            mouth = {"hole": np.asarray(hole, int), "src_side": ls, "src_v": src_v, "dst_v": wv,
                     **{k: to_model[:3, :3].T[:, i] / np.linalg.norm(to_model[:3, :3].T[:, i])
                        for i, k in enumerate(("lat_axis", "fwd_axis", "up_axis"))},
                     "dst_side_of": None}
            report["mouth"] = {"hole_vertices": int(len(hole)),
                               "anchor_gap_m": [round(float(np.linalg.norm(dst_m[sup] - src_m[up])) / scale, 4),
                                                round(float(np.linalg.norm(dst_m[sdn] - src_m[down])) / scale, 4)]}
        else:
            report["mouth"] = None
    # neighbour agreement along the src surface
    rep = sf[T, np.argmax(B, -1)]                                  # (nw, C) the candidate's strongest corner
    lab = U.argmin(1)
    rng = np.random.default_rng(seed)
    it, changed = 0, 0
    if mu > 0:                                                     # (mu 0: nearest compatible point, no table)
        used_v = np.unique(rep)
        G_used = edge_geodesics(src_v, sf, used_v)
        col = np.full(len(src_v), -1)
        col[used_v] = np.arange(len(used_v))
        ew = edges(wf)
        ea, eb = np.concatenate([ew[:, 0], ew[:, 1]]), np.concatenate([ew[:, 1], ew[:, 0]])
    for it in range(1, iters + 1 if mu > 0 else 1):
        nb = rep[eb, lab[eb]]                                      # neighbour's chosen corner, per directed edge
        g = G_used[col[rep[ea]], nb[:, None]]                       # (E, C) surface distance candidate -> neighbour
        g = np.where(np.isfinite(g), g, 1e3 * h)
        P = mu * (np.maximum(0.0, g - slack * h) / h) ** 2
        S = np.zeros_like(U)
        np.add.at(S, ea, P)
        new = (U + S).argmin(1)
        upd = rng.random(nw) < 0.5                                 # half the vertices per step: settles
        changed = int(((new != lab) & upd).sum())
        lab = np.where(upd, new, lab)
        if changed == 0 and it > 4:
            break
    r = np.arange(nw)
    report.update(iterations=it, last_changes=changed,
                  nearest_kept=round(float(np.mean(lab == U.argmin(1))), 3))
    corners = sf[T[r, lab]][inv]
    bary = B[r, lab][inv]
    out = Correspondence(corners, bary, inv, df, report)
    if mouth is not None:              # each welded dst vertex's lip side: that of its chosen src point
        mouth.pop("dst_side_of")
        mouth["dst_side"] = (B[r, lab] * ls[sf[T[r, lab]]]).sum(1)
        out.mouth = mouth
    return out
