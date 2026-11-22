"""Estimativa de perfil de tronco por fatias para marcos humanoides (camada L1)."""

from __future__ import annotations

import os
import sys

from mathutils import Vector

if __package__:
    from .autorig_const import _clamped, _mediana
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import _clamped, _mediana

_FRACS_PERFIL = (0.50, 0.53, 0.56, 0.59, 0.62, 0.65, 0.68, 0.71, 0.74, 0.77, 0.80)


def _bfs_mascara(edges_list: list[tuple[int, int]], mask: bytearray | set[int], seeds: list[int]) -> list[int]:
    adj: dict[int, list[int]] = {}
    in_mask = (lambda idx: idx in mask) if isinstance(mask, set) else (lambda idx: bool(mask[idx]))
    for a, b in edges_list:
        if in_mask(a) and in_mask(b):
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
    vis, fila, pos = set(seeds), list(seeds), 0
    while pos < len(fila):
        u = fila[pos]
        pos += 1
        for w in adj.get(u, ()):
            if w not in vis:
                vis.add(w)
                fila.append(w)
    return fila


def _trim_slab_braco(cc_pts: list[Vector], w_raw: float, altura: float) -> float:
    """Remove saliencia fina de braco/coxa da largura da fatia mantendo o tronco."""
    core_ys = [p.y for p in cc_pts if abs(p.x) <= max(0.08 * altura, 0.35 * w_raw)]
    if len(core_ys) < 2:
        return w_raw
    y_min_c, y_max_c = min(core_ys), max(core_ys)
    dy_core = y_max_c - y_min_c
    if dy_core <= 1e-4:
        return w_raw
    y_mid = 0.5 * (y_min_c + y_max_c)
    win, req_dy = max(0.055 * altura, 1e-3), min(0.19 * altura, 0.35 * dy_core)
    out_ys = [p.y for p in cc_pts if abs(p.x) >= w_raw - win]
    if len(out_ys) >= 2 and (max(out_ys) - min(out_ys)) >= req_dy:
        return w_raw
    for x_cand in sorted({round(abs(p.x), 4) for p in cc_pts}, reverse=True):
        if x_cand <= 0.35 * w_raw:
            break
        wys = [p.y for p in cc_pts if x_cand - win <= abs(p.x) <= x_cand + 1e-4]
        if len(wys) >= 2 and (max(wys) - min(wys)) >= req_dy:
            largo = [
                abs(p.x)
                for p in cc_pts
                if abs(p.x) <= x_cand + 1e-4 and abs(p.y - y_mid) >= min(0.038 * altura, 0.35 * dy_core)
            ]
            return min(w_raw, max(largo) if largo else x_cand)
    return w_raw


def _recortar_gaps_x(cc_pts: list[Vector], altura: float) -> tuple[list[Vector], list[float]]:
    """Recorta vazamento lateral de bracos quando existe gap > 0.022*h em |x|."""
    xs_all = sorted(abs(p.x) for p in cc_pts if abs(p.x) <= 0.45 * altura)
    if len(xs_all) < 4:
        return cc_pts, sorted(abs(p.x) for p in cc_pts)
    dedup_tol = max(1e-3 * altura, 1e-5)
    uniq_x: list[float] = [xs_all[0]]
    for x in xs_all[1:]:
        if x - uniq_x[-1] > dedup_tol:
            uniq_x.append(x)
    gap_lim = 0.022 * altura
    x_cut: float | None = None
    steps: list[float] = []
    for k in range(1, len(uniq_x)):
        prev_x, cur_x = uniq_x[k - 1], uniq_x[k]
        gap = cur_x - prev_x
        if prev_x >= 0.055 * altura:
            step_ref = _mediana(steps[-3:], 0.0) if steps else 0.0
            if gap > max(gap_lim, 1.25 * step_ref):
                x_cut = prev_x
                break
        steps.append(gap)
    if x_cut is None:
        return cc_pts, xs_all
    pts_cut = [p for p in cc_pts if abs(p.x) <= x_cut + 1e-6]
    xs_cut = [x for x in xs_all if x <= x_cut + 1e-6]
    if len(xs_cut) < 4:
        return cc_pts, xs_all
    return pts_cut, xs_cut


def _perfil_tronco_fatias(
    coords: list[Vector],
    edges: list[tuple[int, int]] | None,
    z_min: float,
    altura: float,
    ignorar: set[int] | None = None,
) -> tuple[float, list[tuple[float, float]]]:
    """Calcula meia-largura base e contorno Z->largura do tronco por CC central com guarda de cintura."""
    n = len(coords)
    if n == 0:
        return 0.12 * altura, []
    ign = ignorar or set()
    band_lo, band_hi = z_min + 0.46 * altura, z_min + 0.84 * altura
    in_band = bytearray(n)
    band_indices: list[int] = []
    has_central = False
    for i, v in enumerate(coords):
        if i not in ign and band_lo <= v.z <= band_hi:
            in_band[i] = 1
            band_indices.append(i)
            if abs(v.x) <= 0.07 * altura:
                has_central = True

    adj: dict[int, list[int]] = {}
    if edges:
        for a, b in edges:
            if in_band[a] and in_band[b]:
                adj.setdefault(a, []).append(b)
                adj.setdefault(b, []).append(a)

    half_dz = 0.028 * altura
    raw_slices: list[tuple[float, float, float, list[Vector], float]] = []
    for f in _FRACS_PERFIL:
        zc = z_min + f * altura
        slab_idx = [i for i in band_indices if zc - half_dz <= coords[i].z <= zc + half_dz]
        if not slab_idx:
            continue
        seeds = [i for i in slab_idx if abs(coords[i].x) <= 0.055 * altura]
        if not seeds:
            if has_central:
                continue
            min_ax = min(abs(coords[i].x) for i in slab_idx)
            seeds = [i for i in slab_idx if abs(coords[i].x) <= min_ax + 1e-4]

        if edges:
            slab_set = set(slab_idx)
            vis, fila, pos = set(seeds), list(seeds), 0
            while pos < len(fila):
                u = fila[pos]
                pos += 1
                for w in adj.get(u, ()):
                    if w in slab_set and w not in vis:
                        vis.add(w)
                        fila.append(w)
            cc_pts, xs = _recortar_gaps_x([coords[i] for i in fila], altura)
        else:
            xs_all = sorted(abs(coords[i].x) for i in slab_idx if abs(coords[i].x) <= 0.45 * altura)
            xs = [x for x in xs_all if x <= 0.055 * altura]
            prev_x = xs[-1] if xs else 0.0
            for x in xs_all:
                if x <= 0.055 * altura:
                    continue
                if x - prev_x > 0.022 * altura:
                    break
                xs.append(x)
                prev_x = x
            cc_pts = [coords[i] for i in slab_idx if abs(coords[i].x) <= prev_x + 1e-6]

        if len(xs) < 4:
            continue
        w_raw = xs[-2] if len(xs) >= 16 else xs[-1]
        w_clean = _trim_slab_braco(cc_pts, w_raw, altura)
        raw_slices.append((f, zc, _clamped(w_clean, 0.065 * altura, 0.45 * altura), cc_pts, w_raw))

    waist_ws = [w for f, _z, w, _cc, _wr in raw_slices if 0.48 <= f <= 0.59]
    w_waist: float | None = _mediana(waist_ws, waist_ws[0]) if waist_ws else None
    if w_waist is not None:
        w_armpit_cap = max(w_waist * 1.30, w_waist + 0.045 * altura)
        raw_slices = [
            (f, z, min(w, w_armpit_cap) if f >= 0.60 else w, cc_pts, wr)
            for f, z, w, cc_pts, wr in raw_slices
        ]

    base_pts = [(f, z, w, wr) for f, z, w, _, wr in raw_slices if 0.55 <= f <= 0.63] or [
        (f, z, w, wr) for f, z, w, _, wr in raw_slices if 0.48 <= f <= 0.63
    ]
    upper_base = [(f, z, w, wr) for f, z, w, wr in base_pts if f >= 0.58]
    if upper_base:
        w_up = max(w for _, _, w, _ in upper_base)
        base_pts = [(f, z, w, wr) for f, z, w, wr in base_pts if f >= 0.58 or wr <= w_up + 0.028 * altura] or upper_base

    max_hw = max(0.065 * altura, min(0.30 * altura, w_waist * 1.35)) if w_waist is not None else 0.45 * altura
    if base_pts:
        torso_hw = _clamped(max(w for _, _, w, _ in base_pts), 0.065 * altura, max_hw)
    else:
        torso_hw = _clamped(max((w for _, _, w, _, _ in raw_slices), default=0.12 * altura), 0.065 * altura, max_hw)

    waist_ref = [(f, z, w) for f, z, w, _, _ in raw_slices if 0.48 <= f <= 0.59]
    if waist_ref:
        z_ref, w_ref = waist_ref[-1][1], min(waist_ref[-1][2], torso_hw)
        slope = (
            _clamped((w_ref - waist_ref[0][2]) / max(z_ref - waist_ref[0][1], 0.03 * altura), 0.0, 0.22)
            if len(waist_ref) >= 2
            else 0.0
        )
    elif base_pts:
        z_ref, w_ref = base_pts[-1][1], min(base_pts[-1][2], torso_hw)
        slope = (
            _clamped((w_ref - base_pts[0][2]) / max(z_ref - base_pts[0][1], 0.03 * altura), 0.0, 0.22)
            if len(base_pts) >= 2
            else 0.0
        )
    else:
        z_ref, w_ref, slope = z_min + 0.59 * altura, torso_hw, 0.0

    perfil: list[tuple[float, float]] = []
    jumped, z_trk, w_trk, slp_trk = False, z_ref, w_ref, slope
    for f, z, w, cc_pts, _wr in raw_slices:
        if f < 0.55:
            perfil.append((z, min(w, torso_hw * 1.15)))
        elif f <= 0.59:
            perfil.append((z, min(w, torso_hw * 1.05) if f < 0.58 else min(w, torso_hw)))
        else:
            w_pred = w_trk + slp_trk * (z - z_trk)
            if not jumped and w > w_pred + 0.030 * altura:
                ys_out = [p.y for p in cc_pts if abs(p.x) > w_pred] or [p.y for p in cc_pts if abs(p.x) >= 0.70 * w]
                dy_out = (max(ys_out) - min(ys_out)) if len(ys_out) >= 2 else 0.0
                if dy_out < 0.20 * altura and dy_out < 0.45 * w:
                    jumped = True
            if not jumped:
                perfil.append((z, w))
                slp_trk = _clamped((w - w_trk) / max(z - z_trk, 0.03 * altura), 0.0, 1.5) if w > w_trk else 0.0
                z_trk, w_trk = z, w
            else:
                perfil.append((z, min(w, w_pred)))
    return torso_hw, perfil


def _largura_em_z(perfil: list[tuple[float, float]], torso_hw: float, z: float) -> float:
    """Interpola linearmente a meia-largura do tronco na cota Z."""
    if not perfil:
        return torso_hw
    if z <= perfil[0][0]:
        return perfil[0][1]
    if z >= perfil[-1][0]:
        return perfil[-1][1]
    for i in range(1, len(perfil)):
        z1, w1 = perfil[i]
        if z <= z1:
            z0, w0 = perfil[i - 1]
            return w0 + ((z - z0) / max(z1 - z0, 1e-6)) * (w1 - w0)
    return perfil[-1][1]


def _torso_meia_largura(
    obj,
    coords: list[Vector],
    z_min: float,
    altura: float,
    ignorar: set[int] | None = None,
    z_lo_fracs: tuple[float, ...] = (0.55, 0.48),
    z_hi_frac: float = 0.66,
    x_cap_frac: float = 0.45,
) -> float:
    """Estima meia-largura do tronco por componente conexo sem invadir bracos ou ilhas soltas."""
    arestas = getattr(obj.data, "edges", None)
    edges_list = [(e.vertices[0], e.vertices[1]) for e in arestas] if arestas else []
    if z_lo_fracs == (0.55, 0.48) and abs(z_hi_frac - 0.66) < 1e-6 and abs(x_cap_frac - 0.45) < 1e-6:
        return _perfil_tronco_fatias(coords, edges_list, z_min, altura, ignorar=ignorar)[0]

    n, ign = len(coords), ignorar or set()
    if edges_list and n > 0:
        for z_lo_frac in z_lo_fracs:
            z_lo, z_hi = z_min + z_lo_frac * altura, z_min + z_hi_frac * altura
            dentro = bytearray(1 if i not in ign and z_lo <= v.z <= z_hi else 0 for i, v in enumerate(coords))
            sementes = [i for i, v in enumerate(coords) if dentro[i] and abs(v.x) <= 0.08 * altura]
            if not sementes:
                xs_d = [abs(coords[i].x) for i in range(n) if dentro[i]]
                if xs_d:
                    sementes = [
                        i
                        for i, v in enumerate(coords)
                        if dentro[i] and abs(v.x) <= max(0.08 * altura, min(xs_d) + 1e-4)
                    ]
            if not sementes:
                continue
            xs = sorted(abs(coords[i].x) for i in _bfs_mascara(edges_list, dentro, sementes))
            if len(xs) >= 4:
                return _clamped(xs[-2] if len(xs) >= 16 else xs[-1], 0.065 * altura, x_cap_frac * altura)
    cintura_x = sorted(
        abs(v.x)
        for i, v in enumerate(coords)
        if i not in ign and z_min + z_lo_fracs[0] * altura <= v.z <= z_min + z_hi_frac * altura and abs(v.x) <= x_cap_frac * altura
    )
    return _clamped(cintura_x[-1] if cintura_x else 0.12 * altura, 0.065 * altura, x_cap_frac * altura)
