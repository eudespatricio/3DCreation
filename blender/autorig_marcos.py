"""Estimativa de marcos anatomicos humanoides (camada L1)."""

from __future__ import annotations

import math
import os
import sys

from mathutils import Vector

if __package__:
    from .autorig_const import _centroide, _clamped, _mediana
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import _centroide, _clamped, _mediana

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
            largo = [abs(p.x) for p in cc_pts if abs(p.x) <= x_cand + 1e-4 and abs(p.y - y_mid) >= min(0.038 * altura, 0.35 * dy_core)]
            return min(w_raw, max(largo) if largo else x_cand)
    return w_raw


def _perfil_tronco_fatias(
    coords: list[Vector], edges: list[tuple[int, int]] | None, z_min: float, altura: float, ignorar: set[int] | None = None,
) -> tuple[float, list[tuple[float, float]]]:
    """Calcula meia-largura base (0.55..0.63h) e contorno Z->largura do tronco por CC central."""
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
            cc_pts = [coords[i] for i in fila]
            xs = sorted(abs(p.x) for p in cc_pts)
        else:
            xs_all = sorted(abs(coords[i].x) for i in slab_idx if abs(coords[i].x) <= 0.45 * altura)
            xs = [x for x in xs_all if x <= 0.055 * altura]
            prev_x = xs[-1] if xs else 0.0
            for x in xs_all:
                if x <= 0.055 * altura:
                    continue
                if x - prev_x > 0.025 * altura:
                    break
                xs.append(x)
                prev_x = x
            cc_pts = [coords[i] for i in slab_idx if abs(coords[i].x) <= prev_x + 1e-6]

        if len(xs) < 4:
            continue
        w_raw = xs[-2] if len(xs) >= 16 else xs[-1]
        w_clean = _trim_slab_braco(cc_pts, w_raw, altura)
        raw_slices.append((f, zc, _clamped(w_clean, 0.065 * altura, 0.45 * altura), cc_pts, w_raw))

    base_pts = [(f, z, w, wr) for f, z, w, _, wr in raw_slices if 0.55 <= f <= 0.63] or [
        (f, z, w, wr) for f, z, w, _, wr in raw_slices if 0.48 <= f <= 0.63
    ]
    upper_base = [(f, z, w, wr) for f, z, w, wr in base_pts if f >= 0.58]
    if upper_base:
        w_up = max(w for _, _, w, _ in upper_base)
        base_pts = [(f, z, w, wr) for f, z, w, wr in base_pts if f >= 0.58 or wr <= w_up + 0.028 * altura] or upper_base
    if base_pts:
        torso_hw = _clamped(max(w for _, _, w, _ in base_pts), 0.065 * altura, 0.45 * altura)
        z_ref, w_ref = base_pts[-1][1], base_pts[-1][2]
        slope = _clamped((w_ref - base_pts[0][2]) / max(z_ref - base_pts[0][1], 0.03 * altura), 0.0, 0.22) if len(base_pts) >= 2 else 0.0
    else:
        torso_hw = _clamped(max((w for _, _, w, _, _ in raw_slices), default=0.12 * altura), 0.065 * altura, 0.45 * altura)
        z_ref, w_ref, slope = z_min + 0.62 * altura, torso_hw, 0.0

    perfil: list[tuple[float, float]] = []
    jumped, z_trk, w_trk, slp_trk = False, z_ref, w_ref, slope
    for f, z, w, cc_pts, _wr in raw_slices:
        if f < 0.55:
            perfil.append((z, min(w, torso_hw * 1.15)))
        elif f <= 0.63:
            perfil.append((z, min(w, torso_hw * 1.05) if f < 0.58 else w))
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


def _componentes_braco(
    coords: list[Vector], cands_idx: list[int], edges: list[tuple[int, int]] | None, altura: float,
) -> list[list[int]]:
    """Agrupa candidatos laterais em componentes conexos (arestas ou grade espacial)."""
    if not cands_idx:
        return []
    if edges:
        cand_set = set(cands_idx)
        adj: dict[int, list[int]] = {}
        for a, b in edges:
            if a in cand_set and b in cand_set:
                adj.setdefault(a, []).append(b)
                adj.setdefault(b, []).append(a)
        vis: set[int] = set()
        comps: list[list[int]] = []
        for s in cands_idx:
            if s in vis:
                continue
            vis.add(s)
            comp, pos = [s], 0
            while pos < len(comp):
                u = comp[pos]
                pos += 1
                for w in adj.get(u, ()):
                    if w not in vis:
                        vis.add(w)
                        comp.append(w)
            comps.append(comp)
        return comps

    cxy, cz = max(0.028 * altura, 1e-4), max(0.12 * altura, 1e-4)
    cxy2 = cxy * cxy
    cells: dict[tuple[int, int, int], list[int]] = {}
    for i in cands_idx:
        v = coords[i]
        cells.setdefault((math.floor(v.x / cxy), math.floor(v.y / cxy), math.floor(v.z / cz)), []).append(i)
    vis_v: set[int] = set()
    comps_g: list[list[int]] = []
    for i0 in cands_idx:
        if i0 in vis_v:
            continue
        vis_v.add(i0)
        q, comp_i, pos = [i0], [i0], 0
        while pos < len(q):
            u = q[pos]
            pos += 1
            vu = coords[u]
            ku = (math.floor(vu.x / cxy), math.floor(vu.y / cxy), math.floor(vu.z / cz))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for w in cells.get((ku[0] + dx, ku[1] + dy, ku[2] + dz), ()):
                            if w not in vis_v:
                                vw = coords[w]
                                if (vu.x - vw.x) ** 2 + (vu.y - vw.y) ** 2 <= cxy2 and abs(vu.z - vw.z) <= cz:
                                    vis_v.add(w)
                                    q.append(w)
                                    comp_i.append(w)
        comps_g.append(comp_i)
    return comps_g


def _estimar_lado_braco(
    coords: list[Vector],
    z0: float,
    altura: float,
    cy: float,
    chest_top_z: float,
    torso_hw: float,
    sinal: float,
    leg_top_z: float = 0.0,
    leg_x: float = 0.0,
    upper_torso_hw: float | None = None,
    perfil_tronco: list[tuple[float, float]] | None = None,
    edges: list[tuple[int, int]] | None = None,
    ignorar: set[int] | None = None,
) -> dict:
    """Detecta ombro, cotovelo, pulso e ponta da mao para +X (L) ou -X (R)."""
    del leg_top_z, leg_x
    ign = ignorar or set()
    ref_hw = max(torso_hw, upper_torso_hw or torso_hw)
    perfil = _perfil_tronco_fatias(coords, edges or [], z0, altura, ignorar=ign)[1] if perfil_tronco is None else perfil_tronco

    shoulder_z_default = _clamped(chest_top_z - 0.02 * altura, z0 + 0.72 * altura, z0 + 0.79 * altura)
    w_chest = _largura_em_z(perfil, ref_hw, shoulder_z_default)
    shoulder_x_default = sinal * _clamped(w_chest + min(0.014 * altura, 0.08 * w_chest), 0.08 * altura, 0.48 * altura)

    ombro_verts = [
        v for i, v in enumerate(coords)
        if i not in ign and z0 + 0.70 * altura <= v.z <= z0 + 0.83 * altura
        and abs(shoulder_x_default) * 0.85 <= v.x * sinal <= abs(shoulder_x_default) * 1.35
    ]
    if ombro_verts:
        zs_ombro = sorted(v.z for v in ombro_verts)
        shoulder_z = _clamped(
            zs_ombro[int(0.60 * (len(zs_ombro) - 1))],
            max(z0 + 0.70 * altura, chest_top_z - 0.055 * altura),
            min(z0 + 0.80 * altura, chest_top_z - 0.005 * altura),
        )
    else:
        shoulder_z = shoulder_z_default

    w_chest = _largura_em_z(perfil, ref_hw, shoulder_z)
    shoulder_x_default = sinal * _clamped(w_chest + min(0.014 * altura, 0.08 * w_chest), 0.08 * altura, 0.48 * altura)
    clav_x_default = sinal * min(max(0.10 * altura, w_chest * 0.55), 0.65 * abs(shoulder_x_default))
    x_arm_fb = max(0.17 * altura, abs(shoulder_x_default) + 0.02 * altura)
    shoulder_pos = Vector((shoulder_x_default, cy, shoulder_z))

    def _fallback() -> dict:
        return {
            "clav_x": clav_x_default,
            "shoulder": shoulder_pos,
            "elbow": Vector((sinal * x_arm_fb, cy, z0 + 0.60 * altura)),
            "wrist": Vector((sinal * x_arm_fb, cy, z0 + 0.44 * altura)),
            "tip": Vector((sinal * x_arm_fb, cy, z0 + 0.36 * altura)),
        }

    z_cand_lo, z_cand_hi = z0 + 0.28 * altura, z0 + 0.86 * altura
    cands_idx = [
        i for i, v in enumerate(coords)
        if i not in ign and z_cand_lo <= v.z <= z_cand_hi
        and v.x * sinal > (wz := _largura_em_z(perfil, ref_hw, v.z)) + max(0.012 * altura, 0.03 * wz)
    ]
    comps = _componentes_braco(coords, cands_idx, edges, altura)
    valid_comps = [c for c in comps if max(coords[i].z for i in c) >= shoulder_z - 0.16 * altura]
    if not valid_comps:
        return _fallback()
    best = max(valid_comps, key=lambda c: (max(coords[i].x * sinal for i in c), len(c)))
    braco_verts = [coords[i] for i in best]
    if len(braco_verts) < 6:
        return _fallback()

    fb_tip = Vector((sinal * x_arm_fb, cy, z0 + 0.36 * altura))
    if max(shoulder_pos.z - v.z for v in braco_verts) < 0.15 * altura:
        max_x_b = max(v.x * sinal for v in braco_verts)
        ponta = [v for v in braco_verts if v.x * sinal >= max_x_b - 0.012 * altura]
        if len(ponta) < 3:
            ponta = sorted(braco_verts, key=lambda v: v.x * sinal, reverse=True)[: max(3, min(20, len(braco_verts) // 20))]
        tip = _centroide(ponta, fb_tip)
    else:
        ordenados = sorted(braco_verts, key=lambda v: (v - shoulder_pos).length, reverse=True)
        tip = _centroide(ordenados[: max(3, min(20, len(ordenados) // 20))], fb_tip)

    braco_proeminente = (tip.x * sinal - w_chest) >= 0.035 * altura
    arm_vec = tip - shoulder_pos
    arm_len = arm_vec.length
    if arm_len < 0.14 * altura and not braco_proeminente:
        return _fallback()

    if tip.x * sinal < abs(shoulder_x_default) * 0.9:
        tip.x = sinal * max(0.11 * altura, abs(shoulder_x_default) * 1.05)
        arm_vec = tip - shoulder_pos
        arm_len = arm_vec.length

    eixo = arm_vec / max(arm_len, 1e-6)
    faixa_cotovelo = [v for v in braco_verts if 0.32 <= (v - shoulder_pos).dot(eixo) / arm_len <= 0.48]
    faixa_pulso = [v for v in braco_verts if 0.72 <= (v - shoulder_pos).dot(eixo) / arm_len <= 0.86]
    elbow_padrao, wrist_padrao = shoulder_pos + arm_vec * 0.40, shoulder_pos + arm_vec * 0.80
    elbow = _centroide(faixa_cotovelo, elbow_padrao)
    wrist = _centroide(faixa_pulso, wrist_padrao)
    if elbow.x * sinal < w_chest * 0.85 or (tip.x * sinal > abs(shoulder_pos.x) and elbow.x * sinal < abs(shoulder_pos.x)):
        elbow.x = elbow_padrao.x
    if wrist.x * sinal < w_chest * 0.85 or (tip.x * sinal > abs(shoulder_pos.x) and wrist.x * sinal < abs(shoulder_pos.x)):
        wrist.x = wrist_padrao.x

    return {"clav_x": clav_x_default, "shoulder": shoulder_pos, "elbow": elbow, "wrist": wrist, "tip": tip}


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
                    sementes = [i for i, v in enumerate(coords) if dentro[i] and abs(v.x) <= max(0.08 * altura, min(xs_d) + 1e-4)]
            if not sementes:
                continue
            xs = sorted(abs(coords[i].x) for i in _bfs_mascara(edges_list, dentro, sementes))
            if len(xs) >= 4:
                return _clamped(xs[-2] if len(xs) >= 16 else xs[-1], 0.065 * altura, x_cap_frac * altura)
    cintura_x = sorted(
        abs(v.x) for i, v in enumerate(coords)
        if i not in ign and z_min + z_lo_fracs[0] * altura <= v.z <= z_min + z_hi_frac * altura and abs(v.x) <= x_cap_frac * altura
    )
    return _clamped(cintura_x[-1] if cintura_x else 0.12 * altura, 0.065 * altura, x_cap_frac * altura)


def estimar_marcos(obj) -> dict:
    """Estima marcos anatomicos a partir da nuvem de vertices canonica (+Z cima, X=0 centro)."""
    cabelo_slots = {
        idx for idx, mat in enumerate(obj.data.materials)
        if mat is not None and str(mat.name).startswith("makehuman_cabelo")
    }
    verts_cabelo = (
        {vi for poly in obj.data.polygons if poly.material_index in cabelo_slots for vi in poly.vertices}
        if cabelo_slots else set()
    )
    all_coords = [obj.matrix_world @ v.co for v in obj.data.vertices]
    coords = [all_coords[i] for i in range(len(all_coords)) if i not in verts_cabelo] or all_coords
    if len(coords) == len(all_coords):
        verts_cabelo = set() if len(coords) == len(all_coords) and not cabelo_slots else verts_cabelo
    if not coords:
        raise RuntimeError("malha sem vertices para auto-rig")

    z_min, z_max = min(v.z for v in coords), max(v.z for v in coords)
    altura = z_max - z_min
    if altura <= 1e-6:
        raise RuntimeError("malha com altura zero para auto-rig")

    edges = [(e.vertices[0], e.vertices[1]) for e in getattr(obj.data, "edges", ())]
    torso_hw, perfil = _perfil_tronco_fatias(all_coords, edges, z_min, altura, ignorar=verts_cabelo)

    cy = _clamped(
        _mediana([v.y for v in coords if z_min + 0.45 * altura <= v.z <= z_min + 0.78 * altura and abs(v.x) <= max(0.12 * altura, torso_hw * 0.80)], 0.0),
        -0.04 * altura, 0.04 * altura,
    )

    fatias_pescoco: list[tuple[float, float]] = []
    for i in range(15):
        za = z_min + (0.74 + 0.01 * i) * altura
        xs = [v.x for v in coords if za <= v.z <= za + 0.025 * altura and abs(v.x) <= max(0.15 * altura, torso_hw * 1.10)]
        if len(xs) >= 3:
            fatias_pescoco.append((za + 0.0125 * altura, max(xs) - min(xs)))

    if fatias_pescoco:
        idx_min = max(range(len(fatias_pescoco)), key=lambda idx: (-round(fatias_pescoco[idx][1], 5), fatias_pescoco[idx][0]))
        melhor_z, melhor_largura = fatias_pescoco[idx_min]
        j = idx_min
        while j > 0 and fatias_pescoco[j - 1][1] <= melhor_largura * 1.45:
            j -= 1
        if j > 0 and fatias_pescoco[j - 1][1] >= melhor_largura * 1.65:
            razao_salto = (fatias_pescoco[j - 1][1] - fatias_pescoco[j][1]) / max(melhor_largura, 1e-4)
            est_chest_top = (0.5 * (fatias_pescoco[j - 1][0] + fatias_pescoco[j][0])) if razao_salto >= 0.75 else (fatias_pescoco[j - 1][0] - 0.035 * altura)
        else:
            est_chest_top = melhor_z - 0.055 * altura
    else:
        melhor_z, melhor_largura, est_chest_top = z_min + 0.80 * altura, float("inf"), z_min + 0.745 * altura

    neck_hw_max = max(0.075 * altura, min(torso_hw * 0.90, 0.30 * altura))
    neck_hw = _clamped(0.5 * melhor_largura if melhor_largura < float("inf") else 0.038 * altura, 0.025 * altura, neck_hw_max)
    chest_top_z = _clamped(est_chest_top, z_min + 0.74 * altura, z_min + 0.79 * altura)
    neck_z = _clamped(chest_top_z + 0.065 * altura, z_min + 0.805 * altura, z_min + 0.86 * altura)
    head_top_z = z_max

    leg_top_z = z_min + 0.44 * altura
    for i in range(14):
        za = z_min + (0.36 + 0.012 * i) * altura
        fatia = [v for v in coords if za <= v.z <= za + 0.02 * altura and abs(v.x) <= max(0.14 * altura, torso_hw * 1.10)]
        if len(fatia) >= 4 and sum(1 for v in fatia if abs(v.x) <= 0.022 * altura) >= 2 and any(v.x > 0.03 * altura for v in fatia) and any(v.x < -0.03 * altura for v in fatia):
            leg_top_z = _clamped(za + 0.01 * altura, z_min + 0.40 * altura, z_min + 0.48 * altura)
            break

    hip_z = _clamped(leg_top_z + 0.04 * altura, z_min + 0.465 * altura, z_min + 0.52 * altura)
    spine_z = hip_z + 0.05 * altura
    spine1_z = _clamped(spine_z + 0.05 * altura, z_min + 0.56 * altura, chest_top_z - 0.16 * altura)
    chest_z = _clamped(spine1_z + 0.075 * altura, z_min + 0.64 * altura, chest_top_z - 0.085 * altura)
    ankle_z = z_min + 0.065 * altura
    knee_z = _clamped(0.5 * (ankle_z + leg_top_z), z_min + 0.21 * altura, z_min + 0.28 * altura)

    leg_x_max = min(0.45 * altura, max(0.13 * altura, torso_hw * 1.35))
    xs_leg_L = [v.x for v in coords if z_min + 0.10 * altura <= v.z <= leg_top_z - 0.03 * altura and v.x > 0.01 * altura] or [v.x for v in coords if z_min <= v.z <= leg_top_z - 0.01 * altura and v.x > 0.01 * altura]
    xs_leg_R = [v.x for v in coords if z_min + 0.10 * altura <= v.z <= leg_top_z - 0.03 * altura and v.x < -0.01 * altura] or [v.x for v in coords if z_min <= v.z <= leg_top_z - 0.01 * altura and v.x < -0.01 * altura]
    leg_x_fb = max(0.065 * altura, 0.55 * torso_hw)
    leg_x_L = _clamped(_mediana(xs_leg_L, leg_x_fb), 0.045 * altura, leg_x_max)
    leg_x_R = _clamped(_mediana(xs_leg_R, -leg_x_fb), -leg_x_max, -0.045 * altura)

    pes_y = sorted(v.y for v in coords if v.z <= ankle_z + 0.01 * altura and v.y > 0.0)
    foot_y = _clamped((pes_y[int(0.9 * (len(pes_y) - 1))] if pes_y else 0.12 * altura) * 0.85, 0.08 * altura, 0.15 * altura)
    toe_y = foot_y + 0.04 * altura

    braco_L = _estimar_lado_braco(all_coords, z_min, altura, cy, chest_top_z, torso_hw, 1.0, leg_top_z=leg_top_z, leg_x=leg_x_L, perfil_tronco=perfil, edges=edges, ignorar=verts_cabelo)
    braco_R = _estimar_lado_braco(all_coords, z_min, altura, cy, chest_top_z, torso_hw, -1.0, leg_top_z=leg_top_z, leg_x=leg_x_R, perfil_tronco=perfil, edges=edges, ignorar=verts_cabelo)
    if abs(abs(braco_L["elbow"].x) - abs(braco_R["elbow"].x)) <= 0.06 * altura:
        clav_sym = 0.5 * (abs(braco_L["clav_x"]) + abs(braco_R["clav_x"]))
        braco_L["clav_x"], braco_R["clav_x"] = clav_sym, -clav_sym
        for chave in ("shoulder", "elbow", "wrist", "tip"):
            pL, pR = braco_L[chave], braco_R[chave]
            sx, sy, sz = 0.5 * (abs(pL.x) + abs(pR.x)), 0.5 * (pL.y + pR.y), 0.5 * (pL.z + pR.z)
            braco_L[chave], braco_R[chave] = Vector((sx, sy, sz)), Vector((-sx, sy, sz))

    return {
        "z_min": z_min, "z_max": z_max, "altura": altura, "cy": cy, "torso_hw": torso_hw, "neck_hw": neck_hw,
        "leg_top_z": leg_top_z, "hip_z": hip_z, "spine_z": spine_z, "spine1_z": spine1_z, "chest_z": chest_z,
        "chest_top_z": chest_top_z, "neck_z": neck_z, "head_top_z": head_top_z, "knee_z": knee_z, "ankle_z": ankle_z,
        "leg_x_L": leg_x_L, "leg_x_R": leg_x_R, "foot_y": foot_y, "toe_y": toe_y,
        "braco_L": braco_L, "braco_R": braco_R,
        "shoulder_z": 0.5 * (braco_L["shoulder"].z + braco_R["shoulder"].z),
        "shoulder_x_L": braco_L["shoulder"].x, "shoulder_x_R": braco_R["shoulder"].x,
        "elbow_x_L": braco_L["elbow"].x, "elbow_x_R": braco_R["elbow"].x,
        "wrist_x_L": braco_L["wrist"].x, "wrist_x_R": braco_R["wrist"].x,
    }
