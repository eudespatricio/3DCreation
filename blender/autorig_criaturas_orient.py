"""Alinhamento de orientacao canonica (+Y frente, +Z cima) para quadrupedes e montarias aladas (camada L1)."""

from __future__ import annotations

import math
import os
import sys

from mathutils import Vector

if __package__:
    from .autorig_const import _aplicar_identidade, _mediana
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import _aplicar_identidade, _mediana


def _dedup_cel_passo(src: list[tuple[float, float, float]], cel: float, lim: int = 0) -> tuple[list[tuple[float, float, float]], float]:
    """Deduplica pontos por centroide em grade simetrica (round) e retorna (pontos, passo_final)."""
    pts_c = src
    cel_cur = max(cel, 1e-4)
    while True:
        inv = 1.0 / max(cel_cur, 1e-4)
        acc: dict[tuple[int, int, int], list[float]] = {}
        for p in pts_c:
            px, py, pz = p[0], p[1], p[2]
            key = (round(px * inv), round(py * inv), round(pz * inv))
            g = acc.get(key)
            if g is None:
                acc[key] = [px, py, pz, 1.0]
            else:
                g[0] += px
                g[1] += py
                g[2] += pz
                g[3] += 1.0
        pts_c = [(sx / c, sy / c, sz / c) for sx, sy, sz, c in acc.values()]
        if lim <= 0 or len(pts_c) <= lim:
            pts_c.sort()
            return pts_c, cel_cur
        cel_cur *= 1.5 if len(pts_c) > 4 * lim else 1.25


def _dedup_cel(src: list[tuple[float, float, float]], cel: float, lim: int = 0) -> list[tuple[float, float, float]]:
    """Deduplica pontos por centroide em grade simetrica (round), reduzindo ate lim se > 0."""
    return _dedup_cel_passo(src, cel, lim)[0]


def _alinhar_orientacao_criatura(obj, com_asas: bool = False) -> None:
    """Orienta criatura/montaria via simetria bilateral no nucleo e assimetria cranio-caudal (+Y_bl)."""
    _aplicar_identidade(obj)
    pts_raw = [(v.co[0], v.co[1], v.co[2]) for v in obj.data.vertices]
    if not pts_raw:
        return
    xs_0 = [p[0] for p in pts_raw]
    ys_0 = [p[1] for p in pts_raw]
    zs_0 = [p[2] for p in pts_raw]
    x0, x1, y0, y1, z0_all, z1_all = min(xs_0), max(xs_0), min(ys_0), max(ys_0), min(zs_0), max(zs_0)
    ox, oy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
    h_all = max(z1_all - z0_all, 1e-3)
    span_xy = max(math.hypot(x1 - x0, y1 - y0), 1e-3)
    # Centraliza antes do _dedup_cel para garantir invariancia a translacao no espaco mundo.
    pts = [(px - ox, py - oy, pz - z0_all) for px, py, pz in pts_raw]

    cel0 = max(0.01 * span_xy, 1e-4)
    u_pts = _dedup_cel(pts, cel0, 500)
    u_z = sorted(u_pts, key=lambda p: p[2])
    gnd0 = [p for p in u_z if p[2] <= 0.04 * span_xy]
    if len(gnd0) < min(len(u_z), 12):
        gnd0 = u_z[: min(len(u_z), max(12, len(u_z) // 10))]
    if gnd0:
        gxs = [p[0] for p in gnd0]
        gys = [p[1] for p in gnd0]
        gx0, gy0 = 0.5 * (min(gxs) + max(gxs)), 0.5 * (min(gys) + max(gys))
    else:
        gx0, gy0 = 0.0, 0.0
    rs_g = sorted(math.hypot(p[0] - gx0, p[1] - gy0) for p in gnd0)
    r_feet = max(rs_g[len(rs_g) // 2], 0.08 * span_xy)

    h_ref = min(h_all, max(2.4 * r_feet, 0.25 * r_feet, 1e-3)) if com_asas else h_all
    dz_low = min(0.22 * r_feet, 0.25 * h_all)
    cel_l = max(0.015 * r_feet, 1e-4)
    low_raw = [p for p in pts if p[2] <= dz_low]
    if len(low_raw) < min(len(pts), 8):
        low_raw = [p for p in pts if p[2] <= min(0.38 * r_feet, 0.30 * h_all)] or gnd0
    low_pts = _dedup_cel(low_raw, cel_l, 90)
    if low_pts:
        lxs = [p[0] for p in low_pts]
        lys = [p[1] for p in low_pts]
        mx0, my0 = 0.5 * (min(lxs) + max(lxs)), 0.5 * (min(lys) + max(lys))
    else:
        mx0, my0 = gx0, gy0

    z_cap = 1.20 * h_ref if com_asas else h_all
    cel_s = max(0.025 * h_ref, 1e-4)
    sub_body, cel_s_used = _dedup_cel_passo([p for p in pts if p[2] <= z_cap] or pts, cel_s, 180)
    inv_sig2 = 1.0 / (max(0.045 * h_ref, 0.035 * r_feet, 0.85 * cel_s_used) ** 2)
    f_win, h_tol = max(0.18 * h_ref, 0.14 * r_feet), max(0.08 * h_ref, 0.05 * r_feet)
    sag_w = max(0.28 * r_feet, 0.14 * h_ref) if com_asas else max(0.30 * r_feet, 0.20 * h_ref)
    z_dead, bin_m = 0.02 * h_ref, max(0.05 * r_feet, 0.035 * r_feet)

    def _refl_sym_sorted(pts_s: list[tuple[float, float, float]]) -> float:
        n_f = len(pts_s)
        if n_f < 4:
            return 0.0
        soma, start = 0.0, 0
        for fi, li, zi in pts_s:
            while start < n_f and pts_s[start][0] < fi - f_win:
                start += 1
            best_d2 = 1e18
            for j in range(start, n_f):
                fj, lj, zj = pts_s[j]
                df = fj - fi
                if df > f_win or (df > 0.0 and df * df >= best_d2):
                    break
                dl = li + lj
                d2 = df * df + dl * dl
                if d2 < best_d2:
                    dz = zi - zj
                    d2 += dz * dz
                    if d2 < best_d2:
                        best_d2 = d2
            if best_d2 < 1e17:
                soma += 1.0 / (1.0 + best_d2 * inv_sig2)
        return soma / float(n_f)

    def _score_one(flz_low_s: list[tuple[float, float, float]], flz_b_s: list[tuple[float, float, float]], l_off: float, full_sym: bool = True) -> float:
        flz_low = [(f, lat - l_off, z) for f, lat, z in flz_low_s]
        flz_b = [(f, lat - l_off, z) for f, lat, z in flz_b_s]
        lats_l = sorted(abs(t[1]) for t in flz_low)
        w_core = max(min(lats_l[int(0.85 * (len(lats_l) - 1))], 1.65 * max(lats_l[len(lats_l) // 2], 0.25 * r_feet)) + 0.12 * r_feet, 0.45 * r_feet) if lats_l else 0.8 * r_feet
        lc = [t for t in flz_low if abs(t[1]) <= w_core] or flz_low
        sag = [t for t in flz_b if abs(t[1]) <= sag_w]
        in_core = [t for t in flz_b if abs(t[1]) <= w_core]
        f_leg_mid = _mediana([t[0] for t in lc], 0.0)
        ext_sag = min(2.2, (sag[-1][0] - sag[0][0]) / max(r_feet, 1e-3)) if sag else 0.0
        bal_sag = min(1.0, (min(dh := max(sag[-1][0] - f_leg_mid, 0.0), dl := max(f_leg_mid - sag[0][0], 0.0)) / max(dh, dl, 1e-3)) / 0.70) if sag else 0.0
        n_pos, n_neg = sum(1 for t in lc if t[1] > z_dead), sum(1 for t in lc if t[1] < -z_dead)
        bc_low = (1.0 - abs(n_pos - n_neg) / max(1, len(lc))) if (n_pos and n_neg) else 0.0
        sym_low, sym_sag, sym_in = _refl_sym_sorted(lc), _refl_sym_sorted(sag), _refl_sym_sorted(in_core)
        if com_asas:
            sym_all = _refl_sym_sorted(flz_b) if full_sym else 0.0
            sag_low = [t[0] for t in sag if t[2] <= 0.65 * h_ref]
            bal_core = min(1.0, (min(ch := max(max(sag_low) - f_leg_mid, 0.0), cl := max(f_leg_mid - min(sag_low), 0.0)) / max(ch, cl, 1e-3)) / 0.65) if sag_low else bal_sag
            return 2.4 * sym_low + 2.2 * sym_sag + 2.4 * sym_in + 1.4 * sym_all + 0.8 * bc_low + 0.4 * ext_sag + 0.5 * bal_core
        return 2.4 * sym_low + 2.2 * sym_sag + 2.2 * sym_in + 0.8 * bc_low + 0.6 * ext_sag + 0.6 * bal_sag

    def _best_l_mid(flz_low_0: list[tuple[float, float, float]], flz_b_0: list[tuple[float, float, float]], use_hough: bool, min_sep: float) -> tuple[float, float]:
        lats_l = [t[1] for t in flz_low_0]
        if not lats_l:
            return -1e9, 0.0
        flz_low_0.sort()
        flz_b_0.sort()
        m_mid = 0.5 * (min(lats_l) + max(lats_l))
        m_med = _mediana(lats_l, m_mid)
        hough: list[float] = []
        if use_hough and len(flz_b_0) >= 4:
            hist: dict[int, list[float]] = {}
            inv_b, start = 1.0 / bin_m, 0
            for i, (fi, li, zi) in enumerate(flz_b_0):
                while start < i and flz_b_0[start][0] < fi - h_tol:
                    start += 1
                for j in range(start, i):
                    _fj, lj, zj = flz_b_0[j]
                    if abs(zi - zj) <= h_tol:
                        mid = 0.5 * (li + lj)
                        g = hist.setdefault(round(mid * inv_b), [0.0, 0.0])
                        g[0] += 1.0
                        g[1] += mid
            hough = [g[1] / g[0] for _bk, g in sorted(hist.items(), key=lambda kv: kv[1][0], reverse=True)[:2]]
        cands_m: list[float] = []
        base_m = [m_mid, m_med, _mediana([t[1] for t in flz_b_0], m_med)] if use_hough else [m_mid, m_med]
        for cm in base_m + hough:
            if all(abs(cm - x) > min_sep for x in cands_m):
                cands_m.append(cm)
        return max(((_score_one(flz_low_0, flz_b_0, lm, use_hough), lm) for lm in cands_m), key=lambda x: x[0])

    ang_cache: dict[tuple[float, bool], tuple[float, float]] = {}

    def _score_ang(ang_deg: float, use_hough: bool = True) -> tuple[float, float]:
        key = (round(ang_deg % 180.0, 4), use_hough)
        if key in ang_cache:
            return ang_cache[key]
        rad = math.radians(ang_deg)
        efx, efy = math.cos(rad), math.sin(rad)
        elx, ely = -efy, efx
        fl = [((x - mx0) * efx + (y - my0) * efy, (x - mx0) * elx + (y - my0) * ely, z) for x, y, z in low_pts]
        fb = [((x - mx0) * efx + (y - my0) * efy, (x - mx0) * elx + (y - my0) * ely, z) for x, y, z in sub_body]
        res = _best_l_mid(fl, fb, use_hough, 0.02 * r_feet)
        ang_cache[key] = res
        return res

    pca_angs: list[float] = []
    for src in (low_pts, u_pts):
        sxx = sum((p[0] - mx0) ** 2 for p in src)
        syy = sum((p[1] - my0) ** 2 for p in src)
        sxy = sum((p[0] - mx0) * (p[1] - my0) for p in src)
        th = math.degrees(0.5 * math.atan2(2.0 * sxy, sxx - syy)) % 180.0
        pca_angs.extend((th, (th + 90.0) % 180.0))
    grid_angs = pca_angs + [float(a) for a in range(0, 180, 10 if com_asas else 15)]
    scored = sorted(((_score_ang(a, False)[0], a) for a in grid_angs), key=lambda x: x[0], reverse=True)
    peaks: list[float] = []
    n_peaks = 2 if com_asas else 1
    for _sc, ang in scored:
        if all(min(abs(ang - p), 180.0 - abs(ang - p)) > 8.0 for p in peaks) and not peaks.append(ang) and len(peaks) >= n_peaks:
            break
    d_rng = range(-5, 6) if com_asas else range(-7, 8)
    ref_angs = [p + o + d for p in peaks for o in (0.0, 90.0) for d in d_rng]
    bdeg = max(ref_angs, key=lambda a: _score_ang(a, True)[0])
    bdeg = max([bdeg + d for d in (-0.5, -0.25, 0.0, 0.25, 0.5)], key=lambda a: _score_ang(a, True)[0])
    _, l_mid_all = _score_ang(bdeg, True)
    rad = math.radians(bdeg)
    efx, efy = math.cos(rad), math.sin(rad)
    elx, ely = -efy, efx

    flz_all = [((x - mx0) * efx + (y - my0) * efy, (x - mx0) * elx + (y - my0) * ely - l_mid_all, z) for x, y, z in pts]
    lats_abs = sorted(abs(t[1]) for t in flz_all)
    inner_f = sorted(t[0] for t in flz_all if abs(t[1]) <= lats_abs[min(len(lats_abs) - 1, max(15, len(flz_all) // 4))])
    core_len = max(inner_f[int(0.98 * (len(inner_f) - 1))] - inner_f[int(0.02 * (len(inner_f) - 1))], 1e-3)
    core_flz = [t for t in flz_all if abs(t[1]) <= 0.07 * core_len]
    if len(core_flz) < max(12, len(flz_all) // 25):
        core_flz = [t for t in flz_all if abs(t[1]) <= min(0.20 * core_len, lats_abs[min(len(lats_abs) - 1, max(11, len(flz_all) // 12))])] or flz_all

    pv = sorted(f for f, _l, _z in core_flz)
    lo, hi = pv[int(0.02 * len(pv))], pv[int(0.98 * len(pv))]
    meio, meia = 0.5 * (lo + hi), max(0.5 * (hi - lo), 1e-4)
    ant_zs = sorted(z for f, _l, z in core_flz if (f - meio) > 0.35 * meia) or sorted(z for f, _l, z in flz_all if (f - meio) > 0.35 * meia)
    post_zs = sorted(z for f, _l, z in core_flz if (f - meio) < -0.35 * meia) or sorted(z for f, _l, z in flz_all if (f - meio) < -0.35 * meia)
    if ant_zs and post_zs:
        top_a = sum(ant_zs[max(0, int(0.8 * len(ant_zs))):]) / max(1, len(ant_zs) - int(0.8 * len(ant_zs)))
        top_p = sum(post_zs[max(0, int(0.8 * len(post_zs))):]) / max(1, len(post_zs) - int(0.8 * len(post_zs)))
        if (top_p + 0.35 * (sum(post_zs) / len(post_zs))) > (top_a + 0.35 * (sum(ant_zs) / len(ant_zs))) + 1e-3 * h_ref:
            efx, efy = -efx, -efy

    rot_z = ((math.pi * 0.5) - math.atan2(efy, efx) + math.pi) % (2.0 * math.pi) - math.pi
    did_rot = abs(rot_z) > math.radians(0.5)
    if did_rot:
        if obj.rotation_mode != "XYZ":
            obj.rotation_mode = "XYZ"
        obj.rotation_euler.z += rot_z
        _aplicar_identidade(obj)

    pts_r = [(v.co[0], v.co[1], v.co[2]) for v in obj.data.vertices]
    xs_r = [p[0] for p in pts_r]
    ys_r = [p[1] for p in pts_r]
    zs_r = [p[2] for p in pts_r]
    ox_r, oy_r, z0_r = 0.5 * (min(xs_r) + max(xs_r)), 0.5 * (min(ys_r) + max(ys_r)), min(zs_r)
    if com_asas or abs(ox_r) > 0.01 * h_ref:
        c_rz, s_rz = (math.cos(rot_z), math.sin(rot_z)) if did_rot else (1.0, 0.0)
        low_r = [(yr, xr - ox_r, z) for x, y, z in low_pts for xr, yr in (((x + ox) * c_rz - (y + oy) * s_rz, (x + ox) * s_rz + (y + oy) * c_rz),)]
        sub_r = [(yr, xr - ox_r, z) for x, y, z in sub_body for xr, yr in (((x + ox) * c_rz - (y + oy) * s_rz, (x + ox) * s_rz + (y + oy) * c_rz),)]
        _, dx_center = _best_l_mid(low_r, sub_r, True, 0.01 * r_feet)
        x_center = ox_r + dx_center
    else:
        x_center = ox_r
    shift = Vector((-x_center, -oy_r, -z0_r))
    if shift.length > 1e-5:
        for v in obj.data.vertices:
            v.co += shift
        obj.data.update()
