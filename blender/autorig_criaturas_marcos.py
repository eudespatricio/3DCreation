"""Orientacao, marcos anatomicos e ossos para quadrupedes e montarias aladas (camada L2)."""

from __future__ import annotations

import itertools
import math
import os
import sys

import bmesh

if __package__:
    from .autorig_const import _clamped, _mediana
    from .autorig_criaturas_orient import _alinhar_orientacao_criatura as _alinhar_orientacao_criatura
    from .autorig_ossos import _osso
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import _clamped, _mediana
    from autorig_criaturas_orient import _alinhar_orientacao_criatura as _alinhar_orientacao_criatura
    from autorig_ossos import _osso


_FWD_OFFSETS = tuple((dx, dy, dz) for dx in (0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dy, dz) > (0, 0, 0))


def _pares_coincidentes(pts: list[tuple[float, float, float]], idxs: list[int] | None = None, tol: float = 1e-4) -> list[tuple[int, int, float]]:
    """Retorna pares (i, j, dist) espacialmente coincidentes via hash quantizado."""
    if (len(pts) if idxs is None else len(idxs)) < 2:
        return []
    inv, tol2 = 1.0 / tol, tol * tol
    buckets: dict[tuple[int, int, int], list[tuple[int, float, float, float]]] = {}
    for i in (range(len(pts)) if idxs is None else idxs):
        p = pts[i]
        px, py, pz = p[0], p[1], p[2]
        buckets.setdefault((math.floor(px * inv), math.floor(py * inv), math.floor(pz * inv)), []).append((i, px, py, pz))
    pares: list[tuple[int, int, float]] = []

    def _scan(g1, g2, same: bool) -> None:
        for ai, (i, xi, yi, zi) in enumerate(g1):
            for j, xj, yj, zj in (g1[ai + 1:] if same else g2):
                d2 = (xi - xj) ** 2 + (yi - yj) ** 2 + (zi - zj) ** 2
                if d2 <= tol2:
                    pares.append((i, j, math.sqrt(d2)))

    for (ix, iy, iz), grp in buckets.items():
        _scan(grp, grp, True)
        for dx0, dy0, dz0 in _FWD_OFFSETS:
            if (oth := buckets.get((ix + dx0, iy + dy0, iz + dz0))):
                _scan(grp, oth, False)
    return pares


def _ilha_tronco_indices(
    pts: list[tuple[float, float, float]], edges, sag_lim: float, bnd_idxs: list[int] | None = None, tol_coinc: float | None = None
) -> set[int]:
    """Retorna indices da componente conexa sagital do tronco (ou vazio sem arestas)."""
    if not edges or not pts:
        return set()
    adj: list[list[int]] = [[] for _ in range(len(pts))]
    if tol_coinc is None:
        h_m = max(p[2] for p in pts) - min(p[2] for p in pts)
        tol_coinc = max(1e-7, min(1e-4, 1e-4 * h_m))
    coinc_pares = _pares_coincidentes(pts, idxs=bnd_idxs, tol=tol_coinc) if (bnd_idxs is None or len(bnd_idxs) >= 2) else []
    for i, j in itertools.chain(((e.vertices[0], e.vertices[1]) for e in edges), ((a, b) for a, b, _d in coinc_pares)):
        adj[i].append(j)
        adj[j].append(i)
    seeds = [i for i, p in enumerate(pts) if abs(p[0]) <= sag_lim]
    if not seeds:
        return set()
    vis, fila = set(seeds), list(seeds)
    for u in fila:
        for w in adj[u]:
            if w not in vis:
                vis.add(w)
                fila.append(w)
    return vis


def _wall_x_band(
    pts_src: list[tuple[float, float, float]], y0: float, y1: float, z_belly: float, z_torso_top: float,
    h_b: float, len_y: float, span_x: float, leg_safe: bool = False, has_island: bool = False,
) -> float | None:
    """Estima meia-largura da parede lateral do tronco na faixa Y [y0, y1] sem invadir asas/patas."""
    torso_h = max(z_torso_top - z_belly, 0.10 * h_b)
    z_mid = 0.5 * (z_belly + z_torso_top)
    band_pts = [p for p in pts_src if y0 <= p[1] <= y1 and z_belly - 0.02 * h_b <= p[2] <= z_torso_top + 0.03 * h_b]
    if not band_pts:
        return None
    n_slices = 6
    dy_slice = max(y1 - y0, 1e-7) / float(n_slices)
    dx_bin = max(0.03 * h_b, 0.02 * len_y)
    slices = [sl for k in range(n_slices) if len(sl := [p for p in band_pts if y0 + k * dy_slice <= p[1] <= y0 + (k + 1) * dy_slice]) >= 6]
    max_bx = max((abs(p[0]) for p in band_pts), default=0.16 * h_b)
    w_slice_min = min((max(abs(p[0]) for p in sl) for sl in slices), default=max_bx)
    below_cols = (
        {(1 if p[0] >= 0.0 else -1, int(abs(p[0]) / dx_bin), min(n_slices - 1, max(0, int((p[1] - y0) / dy_slice))))
         for p in pts_src if y0 <= p[1] <= y1 and p[2] < z_belly - 0.10 * torso_h}
        if leg_safe else set()
    )

    def _side_wall_x(side_pts: list[tuple[float, float, float]], sgn: int) -> float | None:
        if not side_pts:
            return None
        bins: dict[int, list[tuple[float, float, float]]] = {}
        sbins: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
        for p in side_pts:
            k = int(abs(p[0]) / dx_bin)
            bins.setdefault(k, []).append(p)
            sbins.setdefault((k, min(n_slices - 1, max(0, int((p[1] - y0) / dy_slice)))), []).append(p)

        def _ok_dz(ps: list[tuple[float, float, float]], k: int, si: int | None) -> bool:
            if len(ps) < 2:
                return False
            z0, z1 = min(p[2] for p in ps), max(p[2] for p in ps)
            if (z1 - z0) < 0.42 * torso_h:
                return False
            if leg_safe:
                if z1 < z_mid + 0.12 * torso_h:
                    return False
                in_b = ((sgn, k, si) in below_cols) if si is not None else any((sgn, k, sj) in below_cols for sj in range(n_slices))
                if in_b and z1 < z_mid + 0.22 * torso_h:
                    return False
                return z0 <= z_belly + 0.44 * torso_h
            return z0 <= z_belly + 0.33 * torso_h or (z0 <= z_belly + 0.44 * torso_h and z1 >= z_mid + 0.12 * torso_h)

        def _is_wall(ps: list[tuple[float, float, float]]) -> bool:
            return len(ps) >= 2 and (max(p[2] for p in ps) - (z0 := min(p[2] for p in ps))) >= 0.38 * torso_h and z0 <= z_belly + 0.50 * torso_h and (not leg_safe or max(p[2] for p in ps) >= z_mid + 0.08 * torso_h)

        valid_set = {k for k in bins if len(bins[k]) >= 2 and any(_ok_dz(sb, k, si) for si in range(n_slices) if (sb := sbins.get((k, si))))}
        if not valid_set:
            valid_set = {k for k, bp in bins.items() if _ok_dz(bp, k, None)}
        v_ks, bad_run = [], 0
        for k in sorted(bins):
            if k in valid_set:
                v_ks.append(k)
                bad_run = 0
            elif len(bins[k]) >= 3 and not any(_is_wall(sb) for si in range(n_slices) if (sb := sbins.get((k, si)))):
                bad_run += 1
                if bad_run >= 2 and v_ks:
                    break
        while v_ks:
            bp_top = bins[(k_top := v_ks[-1])]
            if len(bp_top) >= 3:
                zs_b = sorted(p[2] for p in bp_top)
                max_zgap = max(zs_b[i + 1] - zs_b[i] for i in range(len(zs_b) - 1))
                outer_mid = any(z_mid - 0.18 * torso_h <= p[2] <= z_mid + 0.18 * torso_h for ko in (k_top + 1, k_top + 2) for p in bins.get(ko, ()))
                if max_zgap > 0.52 * torso_h and not outer_mid and not any(z_mid - 0.18 * torso_h <= z <= z_mid + 0.18 * torso_h for z in zs_b):
                    v_ks.pop()
                    continue
            break
        if not v_ks:
            return None
        bp_last = bins[v_ks[-1]]
        tx = max(abs(p[0]) for p in bp_last)
        z0_l, z1_l = min(p[2] for p in bp_last), max(p[2] for p in bp_last)
        z0_prev, z1_prev, empty_run = z0_l, z1_l, 0
        for ko in range(v_ks[-1] + 1, max(bins) + 1):
            bp_next = bins.get(ko)
            if not bp_next:
                empty_run += 1
                if empty_run > 1:
                    break
                continue
            empty_run = 0
            if len(bp_next) < 2:
                break
            z0_n, z1_n = min(p[2] for p in bp_next), max(p[2] for p in bp_next)
            if (z1_n - z0_n) < 0.08 * torso_h:
                break
            if (
                z0_n >= z0_l + 0.02 * torso_h
                and z1_n <= z1_l - 0.02 * torso_h
                and z0_n >= z0_prev - 0.005 * torso_h
                and z1_n <= z1_prev + 0.005 * torso_h
                and z0_n <= z_mid + 0.06 * torso_h
                and z1_n >= z_mid - 0.06 * torso_h
            ):
                tx = max(tx, max(abs(p[0]) for p in bp_next))
                z0_prev, z1_prev = z0_n, z1_n
            else:
                break
        return tx

    cands_tx = [t for t in (_side_wall_x([p for p in band_pts if p[0] >= 0.0], 1), _side_wall_x([p for p in band_pts if p[0] <= 0.0], -1)) if t is not None]
    if leg_safe and not cands_tx:
        return None
    thick_x = min(cands_tx) if cands_tx else w_slice_min
    if leg_safe:
        return thick_x
    if slices and w_slice_min < 0.35 * span_x and thick_x < w_slice_min:
        if has_island and w_slice_min <= thick_x * 1.45 and max((abs(p[0]) for p in pts_src), default=0.0) <= w_slice_min * 1.08:
            thick_x = max(thick_x, w_slice_min)
        elif w_slice_min <= thick_x * 1.18:
            rim = [p for p in min(slices, key=lambda sl: max(abs(p[0]) for p in sl)) if abs(p[0]) >= 0.72 * w_slice_min]
            if rim and min(p[2] for p in rim) <= z_mid - 0.05 * torso_h and max(p[2] for p in rim) >= z_mid + 0.05 * torso_h:
                thick_x = max(thick_x, w_slice_min)
    return min(w_slice_min, thick_x) if (not cands_tx or w_slice_min >= 0.72 * thick_x) else thick_x


def _estimar_torso_rx(
    pts: list[tuple[float, float, float]], y_gap_lo: float, y_gap_hi: float, z_belly: float, z_torso_top: float,
    h: float, len_y: float, span_x: float, com_asas: bool, torso_island: set[int] | None = None,
) -> float:
    """Estima meia-largura real do tronco nas faixas inter-patas, peito e quadril sem invadir asas."""
    torso_h = max(z_torso_top - z_belly, 0.10 * h)
    h_b = min(h, max(torso_h * 1.85, min(len_y * 0.85, torso_h * 3.5))) if com_asas else h
    x_cap = max(0.50 * span_x, 0.08 * h_b)
    body_pts = [pts[i] for i in torso_island] if torso_island else pts
    gap_pts = [p for p in body_pts if y_gap_lo <= p[1] <= y_gap_hi and z_belly - 0.02 * h_b <= p[2] <= z_torso_top + 0.03 * h_b]
    if not gap_pts:
        gap_pts = [p for p in body_pts if y_gap_lo <= p[1] <= y_gap_hi] or body_pts
    max_gap_x = max((abs(p[0]) for p in gap_pts), default=0.16 * h_b)
    if not com_asas:
        return _clamped(max_gap_x, 0.08 * h_b, x_cap)
    span_y = max(y_gap_hi - y_gap_lo, 1e-6) / 0.56
    cands = [
        v for v in (
            _wall_x_band(body_pts, y_gap_lo, y_gap_hi, z_belly, z_torso_top, h_b, len_y, span_x, False, bool(torso_island)),
            _wall_x_band(body_pts, y_gap_hi, y_gap_hi + 0.38 * span_y, z_belly, z_torso_top, h_b, len_y, span_x, True),
            _wall_x_band(body_pts, y_gap_lo - 0.38 * span_y, y_gap_lo, z_belly, z_torso_top, h_b, len_y, span_x, True),
        ) if v is not None
    ]
    return _clamped(max(cands) if cands else max_gap_x, 0.08 * h_b, x_cap)


def _estimar_marcos_criatura(obj, com_asas: bool = False) -> dict:
    """Estima marcos anatomicos de quadrupedes e montarias aladas no espaco canonico (+Y frente)."""
    pts = [(v.co[0], v.co[1], v.co[2]) for v in obj.data.vertices]
    xs, ys, zs = [p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts]
    x_min, x_max, y_min, y_max, z_min, z_max = min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)
    h, len_y, span_x = max(z_max - z_min, 1e-6), max(y_max - y_min, 1e-6), max(x_max - x_min, 1e-6)

    sag_lim = max(0.05 * len_y, min(0.06 * h, 0.08 * len_y)) if com_asas else max(0.06 * h, 0.05 * len_y)
    sag_pts = [p for p in pts if abs(p[0]) <= sag_lim]
    if len(sag_pts) < max(8, len(pts) // 30):
        xs_abs = sorted(abs(p[0]) for p in pts)
        sag_lim = min(0.25 * len_y, xs_abs[min(len(xs_abs) - 1, max(7, len(pts) // 12))])
        sag_pts = [p for p in pts if abs(p[0]) <= sag_lim] or pts
    y_core_min, y_core_max = min(p[1] for p in sag_pts), max(p[1] for p in sag_pts)
    core_len = max(y_core_max - y_core_min, 1e-6)
    h_s = min(h, max(max(p[2] for p in sag_pts) - z_min, 0.55 * core_len, 1e-6)) if com_asas else h

    def _cy_low(src: list[tuple[float, float, float]]) -> float:
        leg_src = [p for p in src if abs(p[0]) > 0.01 * h_s] or src
        if leg_src:
            ys_l = [p[1] for p in leg_src]
            return 0.5 * (min(ys_l) + max(ys_l))
        return 0.5 * (y_core_min + y_core_max)

    def _quads(src: list[tuple[float, float, float]], y_split: float) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[float, float, float]]]:
        return ([p for p in src if p[1] > y_split and p[0] > 0.01 * h_s], [p for p in src if p[1] > y_split and p[0] < -0.01 * h_s],
                [p for p in src if p[1] < y_split and p[0] > 0.01 * h_s], [p for p in src if p[1] < y_split and p[0] < -0.01 * h_s])

    if com_asas:
        x_low_lim = max(0.42 * h_s, 0.24 * core_len)
        low_cand = [p for p in pts if p[2] <= z_min + 0.20 * h_s and abs(p[0]) <= x_low_lim]
        cy = _cy_low(low_cand)
        f_l, f_r, b_l, b_r = _quads(low_cand, cy)
        if min(len(f_l), len(f_r), len(b_l), len(b_r)) >= 4:
            low_pts = low_cand
        else:
            low_pts = [p for p in pts if p[2] <= z_min + 0.32 * h_s and abs(p[0]) <= x_low_lim] or [p for p in pts if p[2] <= z_min + 0.32 * h_s]
            cy = _cy_low(low_pts)
            f_l, f_r, b_l, b_r = _quads(low_pts, cy)
    else:
        low_pts = [p for p in pts if p[2] <= z_min + 0.32 * h_s]
        cy = _cy_low(low_pts)
        f_l, f_r, b_l, b_r = _quads(low_pts, cy)

    x_leg_max = max(0.42 * h_s, 0.24 * core_len) if com_asas else max(0.45 * len_y, 0.48 * span_x)
    x_front = _clamped(0.5 * (_mediana([p[0] for p in f_l], 0.14 * h_s) + _mediana([-p[0] for p in f_r], 0.14 * h_s)), 0.06 * h_s, x_leg_max)
    x_back = _clamped(0.5 * (_mediana([p[0] for p in b_l], 0.15 * h_s) + _mediana([-p[0] for p in b_r], 0.15 * h_s)), 0.06 * h_s, x_leg_max)
    leg_offs = sorted([abs(p[0] - x_front) for p in f_l] + [abs(-p[0] - x_front) for p in f_r]
                      + [abs(p[0] - x_back) for p in b_l] + [abs(-p[0] - x_back) for p in b_r])
    leg_r_est = _clamped(leg_offs[min(len(leg_offs) - 1, int(0.85 * (len(leg_offs) - 1)))] if leg_offs else 0.06 * h_s, 0.04 * h_s, 0.14 * h_s)

    y_front_leg = _mediana([p[1] for p in (f_l + f_r)], y_core_min + 0.68 * core_len)
    y_back_leg = _mediana([p[1] for p in (b_l + b_r)], y_core_min + 0.30 * core_len)
    if y_front_leg <= y_back_leg + 0.12 * core_len:
        y_back_leg, y_front_leg = y_core_min + 0.30 * core_len, y_core_min + 0.68 * core_len

    span_y_legs = max(y_front_leg - y_back_leg, 1e-6)
    y_gap_lo, y_gap_hi = y_back_leg + 0.22 * span_y_legs, y_front_leg - 0.22 * span_y_legs
    torso_sag = [p for p in pts if y_gap_lo <= p[1] <= y_gap_hi and abs(p[0]) <= max(0.08 * h_s, 0.06 * core_len)]
    if len(torso_sag) < 6:
        gap_all = sorted([p for p in pts if y_gap_lo <= p[1] <= y_gap_hi], key=lambda p: abs(p[0]))
        torso_sag = gap_all[: max(6, len(gap_all) // 4)] or [p for p in sag_pts if y_back_leg <= p[1] <= y_front_leg] or sag_pts
    zs_ts = sorted(p[2] for p in torso_sag)
    z_belly = max(z_min + 0.08 * h_s, zs_ts[max(0, int(0.02 * (len(zs_ts) - 1)))])
    z_torso_top = zs_ts[min(len(zs_ts) - 1, int(0.95 * (len(zs_ts) - 1)))]
    z_torso_mid = 0.5 * (z_belly + z_torso_top)
    torso_h = max(z_torso_top - z_belly, 0.10 * h_s)
    h_b = min(h, max(z_torso_top - z_min, 1.3 * torso_h)) if com_asas else h

    bnd_idxs = None
    if com_asas and getattr(obj.data, "polygons", None):
        bm_t = bmesh.new()
        try:
            bm_t.from_mesh(obj.data)
            bnd_idxs = [v.index for v in bm_t.verts if v.is_boundary]
        finally:
            bm_t.free()
    torso_island = _ilha_tronco_indices(pts, getattr(obj.data, "edges", None), sag_lim, bnd_idxs=bnd_idxs, tol_coinc=max(1e-7, min(1e-4, 1e-4 * h_b))) if com_asas else set()
    torso_rx = _estimar_torso_rx(pts, y_gap_lo, y_gap_hi, z_belly, z_torso_top, h, len_y, span_x, com_asas, torso_island=torso_island)
    core = [p for p in pts if abs(p[0]) <= max(torso_rx * 1.05, 0.12 * h_b)] or pts

    head_pts = [p for p in core if p[1] >= y_front_leg + 0.08 * core_len] or [p for p in core if p[1] >= cy + 0.25 * core_len] or core
    y_neck_base = y_front_leg + 0.06 * core_len
    z_neck_base = _clamped(z_torso_mid + 0.08 * h_b, z_belly + 0.30 * torso_h, max(z_belly + 0.30 * torso_h, z_torso_top - 0.04 * torso_h)) if com_asas else _clamped(z_torso_mid + 0.08 * h, z_min + 0.35 * h, z_max - 0.15 * h)
    y_snout = max(p[1] for p in head_pts)
    y_head_back = max(y_neck_base + 0.06 * core_len, y_snout - 0.20 * core_len)
    z_head = _mediana([p[2] for p in head_pts], z_min + 0.72 * h_b)

    y_tail_base = y_back_leg - 0.04 * core_len
    y_tail_tip = min(y_core_min + 0.02 * core_len, y_tail_base - 0.14 * core_len)
    tail_pts = [p for p in core if p[1] <= y_tail_base]
    z_tail_tip = _mediana([p[2] for p in tail_pts if p[1] <= y_tail_tip + 0.12 * core_len], z_torso_mid - 0.05 * h_b)

    x_wing_in = max(torso_rx * 1.04, 0.15 * h_b)
    x_low_obs = max((abs(p[0]) for p in low_pts), default=0.0)
    x_leg_out = max(x_wing_in, max(x_front, x_back) + leg_r_est * 2.1, x_low_obs + 0.02 * h_b)
    z_w_min, r_leg_y = max(z_belly + 0.04 * torso_h, z_min + 0.35 * h_b), leg_r_est * 1.6
    wing_pts = [p for p in pts if abs(p[0]) > x_leg_out or (abs(p[0]) > x_wing_in and p[2] >= z_w_min and not (p[2] < z_torso_mid - 0.04 * torso_h and (abs(p[1] - y_front_leg) <= r_leg_y or abs(p[1] - y_back_leg) <= r_leg_y)))] or [p for p in pts if abs(p[0]) > x_leg_out and p[2] >= z_belly]

    wing_span = max((abs(p[0]) for p in wing_pts), default=max(abs(x_min), abs(x_max)))
    if wing_span < 0.35 * core_len:
        wing_span = 0.75 * core_len
    y_w_def = 0.5 * (0.55 * y_back_leg + 0.45 * y_front_leg + y_front_leg)
    if wing_pts:
        outer_w = [p for p in wing_pts if abs(p[0]) > 0.70 * wing_span]
        z_wing_tip = _mediana([p[2] for p in outer_w], z_torso_top + 0.18 * h_b)
        y_wing_tip = _mediana([p[1] for p in outer_w], y_front_leg - 0.18 * core_len)
        x_root_hi = torso_rx + max(0.06 * h_b, 0.04 * span_x)
        root_w = [p for p in wing_pts if torso_rx < abs(p[0]) <= x_root_hi] or sorted(wing_pts, key=lambda p: abs(p[0]))[: max(4, len(wing_pts) // 5)]
        if z_wing_tip > z_torso_mid and len(root_w) >= 4:
            z_w_root_min = min(p[2] for p in root_w)
            root_band = [p for p in root_w if p[2] <= z_w_root_min + 0.20 * torso_h]
            if len(root_band) >= 3:
                root_w = root_band
        z_wing_attach = _mediana([p[2] for p in root_w], z_torso_top - 0.02 * h_b)
        y_wing_attach = _mediana([p[1] for p in root_w], y_w_def)
    else:
        z_wing_tip, y_wing_tip = z_torso_top + 0.18 * h_b, y_front_leg - 0.18 * core_len
        z_wing_attach, y_wing_attach = z_torso_top - 0.02 * h_b, y_w_def

    return {
        "z_min": z_min, "z_max": z_max, "altura": h, "len_y": len_y, "span_x": span_x, "cy": cy, "y_back_leg": y_back_leg,
        "y_front_leg": y_front_leg, "x_front": x_front, "x_back": x_back, "torso_rx": torso_rx, "leg_r_est": leg_r_est,
        "z_belly": z_belly, "z_torso_mid": z_torso_mid, "z_torso_top": z_torso_top, "y_neck_base": y_neck_base,
        "z_neck_base": z_neck_base, "y_head_back": y_head_back, "y_snout": y_snout, "z_head": z_head, "y_tail_base": y_tail_base,
        "y_tail_tip": y_tail_tip, "z_tail_tip": z_tail_tip, "wing_span": wing_span, "y_wing_tip": y_wing_tip,
        "z_wing_tip": z_wing_tip, "y_wing_attach": y_wing_attach, "z_wing_attach": z_wing_attach,
    }


def _construir_ossos_criatura(esqueleto: str, m: dict) -> list[dict]:
    """Constroi esqueleto quadruped@1 ou winged_mount@1 no espaco canonico (+Y frente, +Z cima)."""
    z0, h = m["z_min"], m["altura"]
    yb, yf = m["y_back_leg"], m["y_front_leg"]
    y_spine, zm, zt = 0.55 * yb + 0.45 * yf, m["z_torso_mid"], m["z_torso_top"]
    h_b = min(h, max(zt - z0, 1.3 * max(zt - m.get("z_belly", z0), 1e-6))) if esqueleto == "winged_mount@1" else h
    ml = max(0.01 * h_b, 1e-6)
    xf, xb = m["x_front"], m["x_back"]
    lo_leg = z0 + 0.24 * h_b
    z_leg_top = _clamped(zm - 0.02 * h_b, lo_leg, max(lo_leg, zt - 0.04 * h_b))
    z_knee_f, z_ank_f = z0 + 0.45 * (z_leg_top - z0), z0 + 0.10 * h_b
    z_knee_b, z_ank_b = z0 + 0.52 * (z_leg_top - z0), z0 + 0.14 * h_b
    foot_fwd = 0.07 * m["len_y"]
    yt0, yt3, zt3 = m["y_tail_base"], m["y_tail_tip"], m["z_tail_tip"]

    ossos = [
        _osso("Root", None, (0.0, 0.0, z0), (0.0, 0.0, z0 + 0.06 * h_b), ml),
        _osso("Hips", "Root", (0.0, yb, zm), (0.0, y_spine, zm), ml),
        _osso("Spine", "Hips", (0.0, y_spine, zm), (0.0, 0.5 * (y_spine + yf), zm + 0.02 * h_b), ml),
        _osso("Chest", "Spine", (0.0, 0.5 * (y_spine + yf), zm + 0.02 * h_b), (0.0, m["y_neck_base"], m["z_neck_base"]), ml),
        _osso("Neck", "Chest", (0.0, m["y_neck_base"], m["z_neck_base"]), (0.0, m["y_head_back"], m["z_head"]), ml),
        _osso("Head", "Neck", (0.0, m["y_head_back"], m["z_head"]), (0.0, m["y_snout"], m["z_head"]), ml),
        _osso("Jaw", "Head", (0.0, m["y_head_back"] + 0.01 * m["len_y"], m["z_head"] - 0.06 * h_b), (0.0, m["y_snout"] - 0.01 * m["len_y"], m["z_head"] - 0.08 * h_b), ml),
        _osso("Tail1", "Hips", (0.0, yt0, zm), (0.0, yt0 + (yt3 - yt0) * 0.33, zm + (zt3 - zm) * 0.33), ml),
        _osso("Tail2", "Tail1", (0.0, yt0 + (yt3 - yt0) * 0.33, zm + (zt3 - zm) * 0.33), (0.0, yt0 + (yt3 - yt0) * 0.67, zm + (zt3 - zm) * 0.67), ml),
        _osso("Tail3", "Tail2", (0.0, yt0 + (yt3 - yt0) * 0.67, zm + (zt3 - zm) * 0.67), (0.0, yt3, zt3), ml),
        _osso("MountSeat", "Spine", (0.0, y_spine, zt + 0.01 * h_b), (0.0, y_spine, zt + 0.09 * h_b), ml),
    ]
    for lado, sx in ((".L", -1.0), (".R", 1.0)):
        ossos.extend([
            _osso(f"FrontUpperLeg{lado}", "Chest", (sx * xf, yf, z_leg_top), (sx * xf, yf - 0.02 * m["len_y"], z_knee_f), ml),
            _osso(f"FrontLowerLeg{lado}", f"FrontUpperLeg{lado}", (sx * xf, yf - 0.02 * m["len_y"], z_knee_f), (sx * xf, yf, z_ank_f), ml),
            _osso(f"FrontFoot{lado}", f"FrontLowerLeg{lado}", (sx * xf, yf, z_ank_f), (sx * xf, yf + foot_fwd, z0 + 0.02 * h_b), ml),
            _osso(f"BackUpperLeg{lado}", "Hips", (sx * xb, yb, z_leg_top), (sx * xb, yb + 0.03 * m["len_y"], z_knee_b), ml),
            _osso(f"BackLowerLeg{lado}", f"BackUpperLeg{lado}", (sx * xb, yb + 0.03 * m["len_y"], z_knee_b), (sx * xb, yb - 0.02 * m["len_y"], z_ank_b), ml),
            _osso(f"BackFoot{lado}", f"BackLowerLeg{lado}", (sx * xb, yb - 0.02 * m["len_y"], z_ank_b), (sx * xb, yb + foot_fwd, z0 + 0.02 * h_b), ml),
        ])

    if esqueleto == "winged_mount@1":
        ws, trx = m["wing_span"], m.get("torso_rx", max(xf, xb) * 0.85)
        y_w0 = _clamped(m.get("y_wing_attach", 0.5 * (y_spine + yf)), yb + 0.1 * (yf - yb), yf)
        z_w0 = _clamped(m.get("z_wing_attach", zt - 0.02 * h_b), zm - 0.02 * h_b, zt + 0.04 * h_b)
        y_wt, z_wt = m["y_wing_tip"], m["z_wing_tip"]
        x_r = _clamped(max(trx * 0.75, 0.10 * ws), 0.08 * ws, min(0.25 * ws, max(trx * 0.92, 0.22 * ws)))
        x_p1, x_p2 = max(x_r + 0.04 * ws, 0.25 * ws), max(x_r + 0.10 * ws, 0.52 * ws)
        x_p3, x_p4 = max(x_p2 + 0.06 * ws, 0.78 * ws), max(x_p2 + 0.10 * ws, 0.98 * ws)
        for lado, sx in ((".L", -1.0), (".R", 1.0)):
            ps = [(sx * x_r, y_w0, z_w0), (sx * x_p1, y_w0 + 0.03 * m["len_y"], z_w0 + 0.30 * (z_wt - z_w0)),
                  (sx * x_p2, 0.5 * (y_w0 + y_wt) + 0.05 * m["len_y"], z_w0 + 0.70 * (z_wt - z_w0)),
                  (sx * x_p3, 0.25 * y_w0 + 0.75 * y_wt, z_w0 + 0.90 * (z_wt - z_w0)), (sx * x_p4, y_wt, z_wt)]
            ossos.extend([_osso(f"{n}{lado}", p, ps[i], ps[i + 1], ml) for i, (n, p) in enumerate((
                ("WingShoulder", "Chest"), ("WingArm", f"WingShoulder{lado}"), ("WingForearm", f"WingArm{lado}"), ("WingTip", f"WingForearm{lado}")))])
    return ossos
