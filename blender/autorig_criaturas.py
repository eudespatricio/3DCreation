"""Skinning geodesico topologico para quadrupedes e montarias aladas (camada L3)."""

from __future__ import annotations

import math
import os
import sys

import bmesh
from mathutils import Vector

if __package__:
    from .autorig_const import (_OSSOS_ASA, _OSSOS_CAUDA, _OSSOS_PATA, _RAIZES, _clamped, _lado_osso)
    from .autorig_criaturas_marcos import (_alinhar_orientacao_criatura, _construir_ossos_criatura, _estimar_marcos_criatura, _pares_coincidentes, _wall_x_band)
    from .autorig_grafo import (_dijkstra_osso, _grafo_superficie, _normalizar_top4, _suavizar_aneis_juntas)
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import (_OSSOS_ASA, _OSSOS_CAUDA, _OSSOS_PATA, _RAIZES, _clamped, _lado_osso)
    from autorig_criaturas_marcos import (_alinhar_orientacao_criatura, _construir_ossos_criatura, _estimar_marcos_criatura, _pares_coincidentes, _wall_x_band)
    from autorig_grafo import (_dijkstra_osso, _grafo_superficie, _normalizar_top4, _suavizar_aneis_juntas)

__all__ = ["_alinhar_orientacao_criatura", "_estimar_marcos_criatura", "_construir_ossos_criatura", "_atribuir_pesos_criatura"]


def _seg_d2(xyz: tuple[float, float, float], seg: tuple[float, float, float, float, float, float, float]) -> float:
    px, py, pz = xyz
    ax, ay, az, abx, aby, abz, inv_ab2 = seg
    dx, dy, dz = px - ax, py - ay, pz - az
    if inv_ab2 <= 0.0:
        return dx * dx + dy * dy + dz * dz
    t = (dx * abx + dy * aby + dz * abz) * inv_ab2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    rx, ry, rz = dx - abx * t, dy - aby * t, dz - abz * t
    return rx * rx + ry * ry + rz * rz


def _ilhas_por_adj(n_total: int, adj: list[list[tuple[int, float]]]) -> list[list[int]]:
    """Particiona vertices em ilhas conexas a partir do grafo de adjacencia ponteado."""
    vis = bytearray(n_total)
    ilhas: list[list[int]] = []
    for i in range(n_total):
        if vis[i]:
            continue
        vis[i] = 1
        ilha, fila, pos = [i], [i], 0
        while pos < len(fila):
            u = fila[pos]
            pos += 1
            for w, _d in adj[u]:
                if not vis[w]:
                    vis[w] = 1
                    fila.append(w)
                    ilha.append(w)
        ilhas.append(ilha)
    ilhas.sort(key=len, reverse=True)
    return ilhas


def _atribuir_pesos_criatura(obj, ossos: list[dict], m: dict) -> None:
    """Skinning geodesico topologico para quadrupedes e montarias aladas."""
    deformaveis = [o for o in ossos if o["nome"] not in (_RAIZES | {"MountSeat"})]
    grupos_obj = {o["nome"]: (obj.vertex_groups.get(o["nome"]) or obj.vertex_groups.new(name=o["nome"])) for o in deformaveis}

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.index_update()
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        cxyz = [(v.co[0], v.co[1], v.co[2]) for v in bm.verts]
        adj = _grafo_superficie(bm)
    finally:
        bm.free()

    n_total = len(cxyz)
    if n_total == 0:
        return
    h, inf = max(m["altura"], 1e-6), float("inf")
    yb, yf = m["y_back_leg"], m["y_front_leg"]
    span_y_legs = max(yf - yb, 1e-6)
    zb, zm, zt = m["z_belly"], m["z_torso_mid"], m["z_torso_top"]
    tem_asas = any(o["nome"] in _OSSOS_ASA for o in deformaveis)
    h_b = min(h, max(zt - m["z_min"], 1.3 * max(zt - zb, 1e-6))) if tem_asas else h
    inv_h = 1.0 / h_b
    cx_mid_tol = max(1e-8, min(1e-5, 1e-5 * h_b))
    pares_coinc = _pares_coincidentes(cxyz, tol=max(1e-7, min(1e-4, 1e-4 * h_b)))
    adj_raw = [list(viz) for viz in adj] if pares_coinc else adj
    coinc_grupo: dict[int, list[int]] = {}
    coinc_rep: dict[int, int] = {}
    if pares_coinc:
        adj_c: dict[int, list[int]] = {}
        for i, j, d in pares_coinc:
            adj[i].append((j, d))
            adj[j].append((i, d))
            adj_c.setdefault(i, []).append(j)
            adj_c.setdefault(j, []).append(i)
        ilhas = _ilhas_por_adj(n_total, adj)
        vis_c: set[int] = set()
        for start in adj_c:
            if start in vis_c:
                continue
            grp = [start]
            vis_c.add(start)
            for u in grp:
                for w in adj_c[u]:
                    if w not in vis_c:
                        vis_c.add(w)
                        grp.append(w)
            coinc_grupo[(rep := min(grp))] = grp
            for vi in grp:
                coinc_rep[vi] = rep
    else:
        ilhas = _ilhas_por_adj(n_total, adj)

    adj_sm = adj_raw
    if coinc_rep:
        adj_sm = [[] for _ in range(n_total)]
        for vi in range(n_total):
            if vi == (rep := coinc_rep.get(vi, vi)):
                viz_m: dict[int, float] = {}
                for u in coinc_grupo.get(rep, (rep,)):
                    for w, comp in adj_raw[u]:
                        if (rw := coinc_rep.get(w, w)) != rep and (rw not in viz_m or comp < viz_m[rw]):
                            viz_m[rw] = comp
                adj_sm[rep] = list(viz_m.items())

    y_mid_lo, y_mid_hi = yb + 0.16 * span_y_legs, yf - 0.16 * span_y_legs
    y_pen_lo, y_pen_hi = yb + 0.04 * span_y_legs, yf - 0.04 * span_y_legs
    eps = 0.015 * h_b
    torso_rx = m.get("torso_rx", max(m["x_front"], m["x_back"]) * 0.85)
    leg_r_est = m.get("leg_r_est", 0.06 * h_b)
    lo_leg = m["z_min"] + 0.24 * h_b
    z_leg_top = _clamped(zm - 0.02 * h_b, lo_leg, max(lo_leg, zt - 0.04 * h_b))
    z_w_att = m.get("z_wing_attach", zt - 0.02 * h_b)
    y_w_att = m.get("y_wing_attach", 0.5 * (0.55 * yb + 0.45 * yf + yf))
    z_w_hi = max(z_w_att, m.get("z_wing_tip", zt))
    x_leg_min = min(m["x_front"], m["x_back"])
    tol_lado = min(0.018 * h_b, 0.22 * x_leg_min)
    center_max_x = torso_rx + 0.05 * h_b
    x_leg_outer_lim = max(torso_rx * 1.15, max(m["x_front"], m["x_back"]) + leg_r_est * 2.3)
    leg_y_band = max(leg_r_est * 2.3, 0.16 * span_y_legs)
    ossos_tronco_c, ossos_cabeca_c = {"Hips", "Spine", "Chest"}, {"Neck", "Head", "Jaw"}

    n_ybins, y_prof_lo, y_prof_hi = 8, yb - 0.16 * span_y_legs, yf + 0.16 * span_y_legs
    dy_prof = max(y_prof_hi - y_prof_lo, 1e-7) / float(n_ybins)
    rx_bins: list[float] = []
    if tem_asas:
        torso_il = next((il for il in ilhas if min(cxyz[vi][0] for vi in il) < -0.05 * torso_rx and max(cxyz[vi][0] for vi in il) > 0.05 * torso_rx
                         and (max(cxyz[vi][2] for vi in il) - min(cxyz[vi][2] for vi in il)) > 0.22 * h_b and (min(cxyz[vi][2] for vi in il) <= zm <= max(cxyz[vi][2] for vi in il))
                         and (max(cxyz[vi][1] for vi in il) - min(cxyz[vi][1] for vi in il)) > 0.55 * span_y_legs), None)
        ti_pts = [cxyz[vi] for vi in torso_il] if torso_il else cxyz
        x_cap_bin = max(torso_rx, 0.50 * m["span_x"], 0.08 * h_b)
        for bi in range(n_ybins):
            by0, by1 = y_prof_lo + bi * dy_prof, y_prof_lo + (bi + 1) * dy_prof
            ym = 0.5 * (by0 + by1)
            near_leg = abs(ym - yf) <= 0.20 * span_y_legs or abs(ym - yb) <= 0.20 * span_y_legs
            rx_b = _wall_x_band(ti_pts, by0, by1, zb, zt, h_b, m["len_y"], m["span_x"], leg_safe=near_leg)
            rx_bins.append(_clamped(rx_b, 0.08 * h_b, x_cap_bin) if rx_b is not None else torso_rx)

    def _rx_y(vy: float) -> float:
        if not rx_bins:
            return torso_rx
        b0 = min(n_ybins - 1, max(0, int((vy - 0.08 * span_y_legs - y_prof_lo) / dy_prof)))
        b1 = min(n_ybins - 1, max(0, int((vy + 0.08 * span_y_legs - y_prof_lo) / dy_prof)))
        return max(rx_bins[b0: b1 + 1])

    rx_vert = [_rx_y(cxyz[vi][1]) for vi in range(n_total)] if rx_bins else None

    bones_info = []
    for o in deformaveis:
        nome = o["nome"]
        lado_i = -1 if (ls := _lado_osso(nome)) == "L" else (1 if ls == "R" else 0)
        cat = 0 if nome in ossos_tronco_c else (1 if nome in ossos_cabeca_c else (2 if nome in _OSSOS_CAUDA else (3 if nome in _OSSOS_PATA else (4 if nome in _OSSOS_ASA else 5))))
        extra = None
        if cat == 3:
            is_front = nome.startswith("Front")
            y_leg, x_leg = (yf, m["x_front"]) if is_front else (yb, m["x_back"])
            extra = (y_leg, max(0.24 * span_y_legs, leg_r_est * 2.2), max(torso_rx * 0.88, x_leg - leg_r_est * 1.25),
                     max(torso_rx * 1.18, x_leg + leg_r_est * 2.3), max(0.35 * x_leg_min, min(x_leg - leg_r_est * 1.35, torso_rx * 0.80)),
                     max(torso_rx * 1.15, x_leg + leg_r_est * 2.3), x_leg + leg_r_est * 2.3, max(0.24 * span_y_legs, leg_r_est * 2.4))
        elif cat == 4:
            extra = nome.startswith("WingShoulder")
        va, vb = Vector(o["cabeca"]), Vector(o["cauda"])
        abx, aby, abz = vb.x - va.x, vb.y - va.y, vb.z - va.z
        comp2 = abx * abx + aby * aby + abz * abz
        bones_info.append((nome, cat, lado_i, va, vb, extra, (va.x, va.y, va.z, abx, aby, abz, (1.0 / comp2) if comp2 > 1e-14 else 0.0)))
    b_map = {b[0]: b for b in bones_info}

    def _lado_ok_i(lado_i: int, x: float) -> bool:
        return (x >= -tol_lado) if lado_i == 1 else ((x <= tol_lado) if lado_i == -1 else (abs(x) <= center_max_x))

    def _semente_ok_b(b_info, xyz: tuple[float, float, float], rx_c: float, ilha_tronco: bool, ilha_tem_asa: bool, ilha_so_asa: bool) -> bool:
        _nome, cat, lado_i, _a, _b, extra, _seg = b_info
        cx, cy, cz = xyz
        if not _lado_ok_i(lado_i, cx):
            return False
        if ilha_so_asa:
            return cat == 4
        if not ilha_tronco:
            return cat != 4
        abs_x = abs(cx)
        if cat == 0:
            return abs_x <= rx_c + 0.015 * h_b and cz >= zb - 0.015 * h_b
        if cat == 2:
            return cy <= yb + 0.06 * span_y_legs and cz >= zb - 0.04 * h_b
        if cat == 1:
            return cy >= yf - 0.04 * span_y_legs and cz >= zb - 0.03 * h_b
        if cat == 3:
            y_leg, y_lim_seed, x_seed_in, x_seed_out, *_ = extra
            return (cz <= z_leg_top + 0.08 * h_b and abs(cy - y_leg) <= y_lim_seed
                    and (cz <= zb + 0.04 * h_b or abs_x >= x_seed_in) and (not ilha_tem_asa or abs_x <= x_seed_out))
        if cat == 4:
            if not ilha_tem_asa:
                return False
            if extra:
                return abs_x >= rx_c * 0.78 and cz >= z_w_att - 0.16 * h_b
            return abs_x > rx_c + 0.01 * h_b or (cz >= zt - 0.01 * h_b and abs_x >= rx_c * 0.45)
        return True

    def _vert_ok_b(b_info, xyz: tuple[float, float, float], rx_c: float, ilha_tronco: bool, ilha_tem_asa: bool, ilha_so_asa: bool, chk_lado: bool = True) -> bool:
        _nome, cat, lado_i, _a, _b, extra, _seg = b_info
        cx, cy, cz = xyz
        if chk_lado and not _lado_ok_i(lado_i, cx):
            return False
        if ilha_so_asa:
            return cat == 4
        if not ilha_tronco:
            return cat != 4
        abs_x = abs(cx)
        if abs_x < 1e-5 * h_b and cat in (3, 4):
            return False
        if cat == 0:
            return not (cz < zb - 0.03 * h_b and abs_x >= 0.35 * x_leg_min)
        if cat == 1:
            return cz >= zb - 0.03 * h_b
        if cat == 2:
            return not (cz < zb - 0.05 * h_b and cy > yb - leg_r_est)
        if cat == 3:
            y_leg, _yls, _xsi, _xso, inner_lim, x_vert_out, x_leg_band, y_lim_vert = extra
            if (cz > z_leg_top + 0.04 * h_b and abs_x < rx_c * 0.5) or (y_mid_lo <= cy <= y_mid_hi and cz >= zb - 0.02 * h_b and abs_x < inner_lim):
                return False
            if ilha_tem_asa and (abs_x > x_vert_out or (cz > z_leg_top + 0.08 * h_b and abs_x > rx_c * 0.90)
                                 or (abs_x > x_leg_band and (cz > z_leg_top + 0.06 * h_b or (abs(cy - y_leg) > y_lim_vert and cz >= zb - 0.02 * h_b)))):
                return False
        return (ilha_tem_asa and (bool(extra) or abs_x >= rx_c * 0.85)) if cat == 4 else True

    pesos_por_vertice: dict[int, list[tuple[str, float]]] = {}
    tronco_flags, tronco_asa_flags, so_asa_flags = bytearray(n_total), bytearray(n_total), bytearray(n_total)
    z_gnd = m["z_min"] + 0.08 * h_b
    inner_gnd_x: dict[tuple[int, str], float] = {}
    for ilha in ilhas:
        xs_i, ys_i, zs_i = [cxyz[vi][0] for vi in ilha], [cxyz[vi][1] for vi in ilha], [cxyz[vi][2] for vi in ilha]
        if not xs_i or min(zs_i) > z_gnd:
            continue
        is_tr = min(xs_i) < -0.05 * torso_rx and max(xs_i) > 0.05 * torso_rx and (max(zs_i) - min(zs_i) > 0.22 * h_b) and (min(zs_i) <= zm <= max(zs_i)) and ((max(ys_i) - min(ys_i)) > 0.55 * span_y_legs)
        for sgn in (1, -1):
            for yk, y_ref in (("F", yf), ("B", yb)):
                gxs = sorted(abs(cxyz[vi][0]) for vi in ilha if cxyz[vi][2] <= z_gnd and cxyz[vi][0] * sgn > 0.02 * h_b and abs(cxyz[vi][1] - y_ref) <= leg_y_band)
                if gxs and (is_tr or gxs[len(gxs) // 2] <= x_leg_outer_lim):
                    mx_g = gxs[len(gxs) // 2]
                    if (sgn, yk) not in inner_gnd_x or mx_g < inner_gnd_x[(sgn, yk)]:
                        inner_gnd_x[(sgn, yk)] = mx_g

    for ilha in ilhas:
        xs_ilha, ys_ilha, zs_ilha = [cxyz[vi][0] for vi in ilha], [cxyz[vi][1] for vi in ilha], [cxyz[vi][2] for vi in ilha]
        e_central = bool(xs_ilha) and min(xs_ilha) < -0.05 * torso_rx and max(xs_ilha) > 0.05 * torso_rx
        min_z_ilha, max_z_ilha = (min(zs_ilha), max(zs_ilha)) if zs_ilha else (0.0, 0.0)
        ilha_tronco = e_central and (max_z_ilha - min_z_ilha > 0.22 * h_b) and (min_z_ilha <= zm <= max_z_ilha) and ((max(ys_ilha) - min(ys_ilha)) > 0.55 * span_y_legs)
        max_ilha_x, min_ilha_x = max((abs(x) for x in xs_ilha), default=0.0), min((abs(x) for x in xs_ilha), default=0.0)
        max_ilha_excess = max((
            abs(cxyz[vi][0]) - (rx_vert[vi] if rx_vert else torso_rx) for vi in ilha
            if cxyz[vi][2] >= zb + 0.02 * h_b and (cxyz[vi][2] >= z_leg_top + 0.06 * h_b or abs(cxyz[vi][0]) > x_leg_outer_lim + 0.08 * h_b
                                                   or (abs(cxyz[vi][1] - yf) > leg_y_band and abs(cxyz[vi][1] - yb) > leg_y_band))
        ), default=-1.0)
        ilha_tem_asa = ilha_tronco and tem_asas and max_ilha_excess > 0.06 * h_b
        x_span_ilha = max(max_ilha_x - min_ilha_x, 1e-7)
        root_zs = [cxyz[vi][2] for vi in ilha if abs(cxyz[vi][0]) <= min_ilha_x + 0.25 * x_span_ilha]
        max_z_root = max(root_zs) if root_zs else max_z_ilha
        med_y_ilha = sorted(ys_ilha)[len(ys_ilha) // 2] if ys_ilha else 0.0
        sgn_il = 1 if (sorted(xs_ilha)[len(xs_ilha) // 2] if xs_ilha else 0.0) >= 0.0 else -1
        yk_il = "F" if abs(med_y_ilha - yf) <= leg_y_band else ("B" if abs(med_y_ilha - yb) <= leg_y_band else None)
        low_xs_il = sorted(abs(cxyz[vi][0]) for vi in ilha if cxyz[vi][2] <= z_gnd)
        med_low_x_il = low_xs_il[len(low_xs_il) // 2] if low_xs_il else min_ilha_x
        has_inner_leg = (yk_il is not None) and ((sgn_il, yk_il) in inner_gnd_x) and (inner_gnd_x[(sgn_il, yk_il)] < med_low_x_il - 0.05 * h_b)
        is_disjoint_thigh = (yk_il is not None) and (max_ilha_x <= x_leg_outer_lim) and (max_z_ilha <= z_leg_top + 0.08 * h_b) and ((sgn_il, yk_il) in inner_gnd_x) and (min_z_ilha > z_gnd)
        na_coluna_pata = (min_z_ilha <= m["z_min"] + 0.05 * h_b and yk_il is not None and min_ilha_x <= x_leg_outer_lim + 0.04 * h_b
                          and not has_inner_leg and max_z_ilha <= zt + 0.08 * h_b)
        one_side = bool(xs_ilha) and (min(xs_ilha) > 0.01 * h_b or max(xs_ilha) < -0.01 * h_b)
        high_wing_ok = max_z_ilha >= z_leg_top - 0.04 * h_b and max_z_root >= z_leg_top - 0.04 * h_b
        rx_il = _rx_y(med_y_ilha)
        bridged_wing_ok = (not one_side) and (not ilha_tronco) and min_z_ilha >= z_leg_top - 0.04 * h_b and min_z_ilha > z_gnd and max_ilha_x > torso_rx + 0.06 * h_b
        ilha_so_asa = (not ilha_tronco) and tem_asas and (not na_coluna_pata) and (not is_disjoint_thigh) and (
            bridged_wing_ok
            or (
                one_side and max_ilha_x > rx_il * 0.95
                and (
                    (max_ilha_x > x_leg_outer_lim and (min_z_ilha >= m["z_min"] + 0.20 * h_b or max_ilha_x > x_leg_outer_lim + 0.04 * h_b
                                                       or max_z_ilha >= m["z_min"] + 0.22 * h_b or high_wing_ok))
                    or min_z_ilha >= z_leg_top + 0.04 * h_b
                    or (has_inner_leg and (high_wing_ok or max_z_ilha >= max(zb, m["z_min"] + 0.35 * h_b)))
                    or (yk_il is None and max_ilha_x > rx_il + 0.05 * h_b and max_z_ilha >= z_leg_top - 0.04 * h_b)
                    or (min_z_ilha > max(z_gnd, m["z_min"] + 0.06 * h_b) and high_wing_ok and max_z_ilha >= z_leg_top + 0.04 * h_b and max_ilha_x > rx_il + 0.04 * h_b)
                )
            )
        )
        if ilha_tronco:
            for vi in ilha:
                tronco_flags[vi] = 1
                if ilha_tem_asa:
                    tronco_asa_flags[vi] = 1
        elif ilha_so_asa:
            for vi in ilha:
                so_asa_flags[vi] = 1

        def _top_dedup(src_c: list[tuple[float, int]], k_lim: int, is_sq: bool = True) -> list[tuple[float, int]]:
            inv_d = (inv_h * inv_h) if is_sq else inv_h
            d_eps = (1e-5 * h_b * h_b + 1e-14) if is_sq else (1e-5 * h_b + 1e-8)

            def _sort_key_c(item: tuple[float, int]) -> tuple[float, float, float, float, int]:
                px, py, pz = cxyz[item[1]]
                return (round(item[0] * inv_d, 10), round(abs(px) * inv_h, 6), round(py * inv_h, 6), round(pz * inv_h, 6), 0 if px >= 0.0 else 1)

            src_c.sort()
            if not coinc_rep:
                d_cut = src_c[min(len(src_c), k_lim) - 1][0] + d_eps
                pref = [it for it in src_c if it[0] <= d_cut]
                pref.sort(key=_sort_key_c)
                return pref
            seen_t, cnt_u, d_cut = set(), 0, src_c[-1][0]
            for d0, vi in src_c:
                if (rep := coinc_rep.get(vi, vi)) not in seen_t:
                    seen_t.add(rep)
                    cnt_u += 1
                    if cnt_u == k_lim:
                        d_cut = d0 + d_eps
                if d0 > d_cut:
                    break
            pref = [it for it in src_c if it[0] <= d_cut]
            pref.sort(key=_sort_key_c)
            seen_r, out_c = set(), []
            for d0, vi in pref:
                if (rep := coinc_rep.get(vi, vi)) not in seen_r:
                    seen_r.add(rep)
                    out_c.append((d0, vi))
            return out_c

        ilha_rep = [vi for vi in ilha if vi == coinc_rep.get(vi, vi)] if coinc_rep else ilha
        dist_mapas: list[tuple[tuple, list[float]]] = []
        for b_info in bones_info:
            nome, cat, lado_i, a, b_pt, _extra, seg = b_info
            if (ilha_so_asa and cat != 4) or (not ilha_so_asa and not ilha_tem_asa and cat == 4):
                continue
            cand = [(_seg_d2(cxyz[vi], seg), vi) for vi in ilha_rep if _semente_ok_b(b_info, cxyz[vi], rx_vert[vi] if rx_vert else torso_rx, ilha_tronco, ilha_tem_asa, ilha_so_asa)]
            if not cand and not ilha_tronco and not ilha_so_asa:
                cand = [(_seg_d2(cxyz[vi], seg), vi) for vi in ilha_rep if _lado_ok_i(lado_i, cxyz[vi][0]) and cat != 4] or [(_seg_d2(cxyz[vi], seg), vi) for vi in ilha_rep if cat != 4]
            if not cand:
                continue
            k_seed = max(1, min(6, len(cand) // 8 or 1))
            cand_u = _top_dedup(cand, k_seed, is_sq=True)
            d_lim = cand_u[min(len(cand_u), k_seed) - 1][0] + 1e-5 * h_b * h_b
            sementes: dict[int, float] = {}
            for d0, vi in cand_u:
                if d0 > d_lim:
                    break
                sementes[vi] = math.sqrt(d0)
            if cat == 0 and ilha_tronco:
                y_lo, y_hi = min(a.y, b_pt.y) - 0.12 * span_y_legs, max(a.y, b_pt.y) + 0.12 * span_y_legs
                aby_z, abz_z = b_pt.y - a.y, b_pt.z - a.z
                c2_yz = aby_z * aby_z + abz_z * abz_z
                seg_yz = (0.0, a.y, a.z, 0.0, aby_z, abz_z, (1.0 / c2_yz) if c2_yz > 1e-14 else 0.0)
                x_seed_max = torso_rx + 0.01 * h_b
                melhores_faixa: dict[tuple[int, int, int], list[tuple[float, int]]] = {}
                for vi in ilha_rep:
                    cx, cy, cz = cxyz[vi]
                    rx_c = rx_vert[vi] if rx_vert else torso_rx
                    if abs(cx) > rx_c + 0.01 * h_b or not (y_lo <= cy <= y_hi):
                        continue
                    if cz < ((zb - 0.015 * h_b) if (y_mid_lo <= cy <= y_mid_hi or abs(cx) <= 0.35 * rx_c) else (zm - 0.02 * h_b)):
                        continue
                    d_yz = math.sqrt(_seg_d2((0.0, cy, cz), seg_yz))
                    sgn_cx = 1 if cx > cx_mid_tol else (-1 if cx < -cx_mid_tol else 0)
                    faixa_idx = min(4, int((abs(cx) / max(x_seed_max, 1e-7)) * 5))
                    melhores_faixa.setdefault((sgn_cx, faixa_idx, 0 if cz < zm else 1), []).append((d_yz, vi))
                for lista in melhores_faixa.values():
                    lu = _top_dedup(lista, 2, is_sq=False)
                    d_lim_f = lu[min(len(lu), 2) - 1][0] + 1e-5 * h_b
                    for d0, vi in lu:
                        if d0 > d_lim_f:
                            break
                        if vi not in sementes or d0 < sementes[vi]:
                            sementes[vi] = d0
            dist_mapas.append((b_info, _dijkstra_osso(n_total, adj_sm, sementes, inf)))

        for vi in ilha_rep:
            xyz = cxyz[vi]
            vx, vy, vz = xyz
            abs_vx, rx_v = abs(vx), (rx_vert[vi] if rx_vert else torso_rx)
            pen_perna = pen_asa = 0.0
            if ilha_tronco:
                t_y = _clamped((vy - y_pen_lo) / max(y_mid_lo - y_pen_lo, 1e-7), 0.0, 1.0) if vy < y_mid_lo else _clamped((y_pen_hi - vy) / max(y_pen_hi - y_mid_hi, 1e-7), 0.0, 1.0)
                t_x = _clamped((rx_v + 0.03 * h_b - abs_vx) / max(0.06 * h_b, 0.15 * rx_v, 1e-7), 0.0, 1.0)
                pen_perna = t_y * t_x * _clamped((vz - (zb - 0.06 * h_b)) / max(0.06 * h_b, 1e-7), 0.0, 1.0)
                if tem_asas:
                    pen_asa = t_x * max(
                        _clamped((z_w_att - 0.03 * h_b - vz) / max(0.08 * h_b, 1e-7), 0.0, 1.0),
                        _clamped((vz - (z_w_hi + 0.05 * h_b)) / max(0.08 * h_b, 1e-7), 0.0, 1.0),
                        t_y * _clamped((abs(vy - y_w_att) - 0.18 * span_y_legs) / max(0.10 * span_y_legs, 1e-7), 0.0, 1.0),
                    )

            brutos: list[tuple[float, str]] = []
            for b_info, dist_v in dist_mapas:
                lado_i = b_info[2]
                if (lado_i == 1 and vx < -tol_lado) or (lado_i == -1 and vx > tol_lado) or (lado_i == 0 and abs_vx > center_max_x):
                    continue
                if not _vert_ok_b(b_info, xyz, rx_v, ilha_tronco, ilha_tem_asa, ilha_so_asa, False) or (d := dist_v[vi]) >= inf:
                    continue
                nome, cat = b_info[0], b_info[1]
                if cat == 0 and abs_vx > rx_v:
                    d += (abs_vx - rx_v) * 3.5
                if pen_perna > 0.0 and cat == 3:
                    d += 0.55 * h_b * pen_perna
                elif cat == 4:
                    if ilha_tronco and abs_vx < rx_v:
                        d += (rx_v - abs_vx) * 2.5
                    if pen_asa > 0.0:
                        d += 0.32 * h_b * pen_asa
                de = d + eps
                de2 = de * de
                brutos.append((1.0 / (de2 * de2), nome))
            if not brutos:
                brutos = [(1.0 / (((math.sqrt(_seg_d2(xyz, b_info[6])) + eps) ** 2) ** 2), b_info[0]) for b_info in bones_info if _vert_ok_b(b_info, xyz, rx_v, ilha_tronco, ilha_tem_asa, ilha_so_asa)]
            if not brutos:
                brutos = [(1.0 / (((math.sqrt(_seg_d2(xyz, b_info[6])) + eps) ** 2) ** 2), b_info[0]) for b_info in bones_info if _lado_ok_i(b_info[2], vx)]
            pesos_por_vertice[vi] = _normalizar_top4(brutos)

    def _perm_criatura(nome_osso: str, vi_idx: int) -> bool:
        return _vert_ok_b(b_map[nome_osso], cxyz[vi_idx], rx_vert[vi_idx] if rx_vert else torso_rx, bool(tronco_flags[vi_idx]), bool(tronco_asa_flags[vi_idx]), bool(so_asa_flags[vi_idx]))

    _suavizar_aneis_juntas(adj_sm, pesos_por_vertice, deformaveis, permitido_fn=_perm_criatura, passos=2, alpha=0.32, pares_bloqueados={frozenset(("Chest", "Head"))})
    for rep, grp in coinc_grupo.items():
        if (ws_rep := pesos_por_vertice.get(rep)):
            for vi in grp:
                pesos_por_vertice[vi] = ws_rep
    for vi in range(n_total):
        for nome, peso in pesos_por_vertice.get(vi, ()):
            grupos_obj[nome].add((vi,), peso, "REPLACE")
