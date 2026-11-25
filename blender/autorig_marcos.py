"""Estimativa de marcos anatomicos humanoides (camada L1)."""

from __future__ import annotations

import math
import os
import sys

from mathutils import Vector

if __package__:
    from .autorig_const import _centroide, _clamped, _mediana
    from .autorig_marcos_tronco import (
        _FRACS_PERFIL,
        _bfs_mascara,
        _largura_em_z,
        _perfil_tronco_fatias,
        _torso_meia_largura,
        _trim_slab_braco,
    )
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import _centroide, _clamped, _mediana
    from autorig_marcos_tronco import (
        _FRACS_PERFIL,
        _bfs_mascara,
        _largura_em_z,
        _perfil_tronco_fatias,
        _torso_meia_largura,
        _trim_slab_braco,
    )

__all__ = [
    "_FRACS_PERFIL",
    "_bfs_mascara",
    "_trim_slab_braco",
    "_perfil_tronco_fatias",
    "_largura_em_z",
    "_torso_meia_largura",
    "_componentes_braco",
    "_estimar_lado_braco",
    "estimar_marcos",
]


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
    """Detecta ombro, cotovelo, pulso e ponta da mao para -X (L) ou +X (R)."""
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
        cands_pescoco = [idx for idx, (zc, _) in enumerate(fatias_pescoco) if zc >= z_min + 0.78 * altura] or list(range(len(fatias_pescoco)))
        idx_min = max(cands_pescoco, key=lambda idx: (-round(fatias_pescoco[idx][1], 5), fatias_pescoco[idx][0]))
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

    torax_x_lim = max(0.08 * altura, 0.70 * torso_hw)
    torax_ys = sorted(v.y for v in coords if chest_z <= v.z <= chest_top_z and abs(v.x) <= torax_x_lim)
    if not torax_ys:
        torax_ys = sorted(v.y for v in coords if spine1_z <= v.z <= chest_top_z + 0.02 * altura and abs(v.x) <= torax_x_lim)
    if torax_ys:
        torso_back_y = float(torax_ys[int(0.05 * (len(torax_ys) - 1))])
        torso_front_y = float(torax_ys[int(0.95 * (len(torax_ys) - 1))])
    else:
        prof_fb = max(0.055 * altura, 0.55 * torso_hw)
        torso_back_y = float(cy - prof_fb)
        torso_front_y = float(cy + prof_fb)

    foot_x_cap = max(0.24 * altura, torso_hw * 1.15)
    leg_x_fb = max(0.065 * altura, 0.55 * torso_hw)
    xs_foot_L = [-v.x for v in coords if v.z <= z_min + 0.12 * altura and -foot_x_cap <= v.x < -0.01 * altura]
    xs_foot_R = [v.x for v in coords if v.z <= z_min + 0.12 * altura and 0.01 * altura < v.x <= foot_x_cap]
    foot_x_L = _mediana(xs_foot_L, leg_x_fb)
    foot_x_R = _mediana(xs_foot_R, leg_x_fb)
    corridor_L = min(0.26 * altura, max(0.14 * altura, torso_hw * 1.10, foot_x_L + 0.08 * altura))
    corridor_R = min(0.26 * altura, max(0.14 * altura, torso_hw * 1.10, foot_x_R + 0.08 * altura))
    leg_x_max = min(0.24 * altura, max(0.13 * altura, torso_hw * 1.05))
    xs_leg_L = (
        [v.x for v in coords if z_min + 0.10 * altura <= v.z <= leg_top_z - 0.03 * altura and -corridor_L <= v.x < -0.01 * altura]
        or [v.x for v in coords if z_min <= v.z <= leg_top_z - 0.01 * altura and -corridor_L <= v.x < -0.01 * altura]
    )
    xs_leg_R = (
        [v.x for v in coords if z_min + 0.10 * altura <= v.z <= leg_top_z - 0.03 * altura and 0.01 * altura < v.x <= corridor_R]
        or [v.x for v in coords if z_min <= v.z <= leg_top_z - 0.01 * altura and 0.01 * altura < v.x <= corridor_R]
    )
    leg_x_L = _clamped(_mediana(xs_leg_L, -leg_x_fb), -leg_x_max, -0.045 * altura)
    leg_x_R = _clamped(_mediana(xs_leg_R, leg_x_fb), 0.045 * altura, leg_x_max)

    pes_y = sorted(v.y for v in coords if v.z <= ankle_z + 0.01 * altura and v.y > 0.0)
    foot_y = _clamped((pes_y[int(0.9 * (len(pes_y) - 1))] if pes_y else 0.12 * altura) * 0.85, 0.08 * altura, 0.15 * altura)
    toe_y = foot_y + 0.04 * altura

    braco_L = _estimar_lado_braco(all_coords, z_min, altura, cy, chest_top_z, torso_hw, -1.0, leg_top_z=leg_top_z, leg_x=leg_x_L, perfil_tronco=perfil, edges=edges, ignorar=verts_cabelo)
    braco_R = _estimar_lado_braco(all_coords, z_min, altura, cy, chest_top_z, torso_hw, 1.0, leg_top_z=leg_top_z, leg_x=leg_x_R, perfil_tronco=perfil, edges=edges, ignorar=verts_cabelo)
    if abs(abs(braco_L["elbow"].x) - abs(braco_R["elbow"].x)) <= 0.06 * altura:
        clav_sym = 0.5 * (abs(braco_L["clav_x"]) + abs(braco_R["clav_x"]))
        braco_L["clav_x"], braco_R["clav_x"] = -clav_sym, clav_sym
        for chave in ("shoulder", "elbow", "wrist", "tip"):
            pL, pR = braco_L[chave], braco_R[chave]
            sx, sy, sz = 0.5 * (abs(pL.x) + abs(pR.x)), 0.5 * (pL.y + pR.y), 0.5 * (pL.z + pR.z)
            braco_L[chave], braco_R[chave] = Vector((-sx, sy, sz)), Vector((sx, sy, sz))

    return {
        "z_min": z_min, "z_max": z_max, "altura": altura, "cy": cy, "torso_hw": torso_hw, "neck_hw": neck_hw,
        "torso_back_y": torso_back_y, "torso_front_y": torso_front_y,
        "leg_top_z": leg_top_z, "hip_z": hip_z, "spine_z": spine_z, "spine1_z": spine1_z, "chest_z": chest_z,
        "chest_top_z": chest_top_z, "neck_z": neck_z, "head_top_z": head_top_z, "knee_z": knee_z, "ankle_z": ankle_z,
        "leg_x_L": leg_x_L, "leg_x_R": leg_x_R, "foot_y": foot_y, "toe_y": toe_y,
        "braco_L": braco_L, "braco_R": braco_R,
        "shoulder_z": 0.5 * (braco_L["shoulder"].z + braco_R["shoulder"].z),
        "shoulder_x_L": braco_L["shoulder"].x, "shoulder_x_R": braco_R["shoulder"].x,
        "elbow_x_L": braco_L["elbow"].x, "elbow_x_R": braco_R["elbow"].x,
        "wrist_x_L": braco_L["wrist"].x, "wrist_x_R": braco_R["wrist"].x,
    }
