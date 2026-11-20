"""Sementes geodesicas e calculo de pesos intra-ilha por Dijkstra (camada L2)."""

from __future__ import annotations

import math
import os
import sys

from mathutils import Vector

if __package__:
    from .autorig_const import (
        _OSSOS_BRACO_DISTAL,
        _OSSOS_CABECA,
        _OSSOS_CANELA,
        _OSSOS_COXA,
        _OSSOS_OMBROS,
        _OSSOS_PE,
        _OSSOS_PERNA,
        _OSSOS_PESCOCO,
        _OSSOS_TRONCO,
        _RAIZES,
        _dist_ponto_segmento,
        _lado_osso,
    )
    from .autorig_grafo import (
        _dijkstra_osso,
        _limites_anatomicos,
        _normalizar_top4,
        _osso_permitido,
        _pesos_vertice_inverso,
    )
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import (
        _OSSOS_BRACO_DISTAL,
        _OSSOS_CABECA,
        _OSSOS_CANELA,
        _OSSOS_COXA,
        _OSSOS_OMBROS,
        _OSSOS_PE,
        _OSSOS_PERNA,
        _OSSOS_PESCOCO,
        _OSSOS_TRONCO,
        _RAIZES,
        _dist_ponto_segmento,
        _lado_osso,
    )
    from autorig_grafo import (
        _dijkstra_osso,
        _limites_anatomicos,
        _normalizar_top4,
        _osso_permitido,
        _pesos_vertice_inverso,
    )


def _sementes_osso_ilha(
    ilha: list[int],
    adj: list[list[tuple[int, float]]],
    coords: list[Vector],
    coords_xyz: list[tuple[float, float, float]],
    o: dict,
    m: dict,
    bracos_baixos: bool,
    e_ilha_central: bool,
    tem_lado_l: bool,
    tem_lado_r: bool,
    d_global_min: float | None = None,
    tem_neck: bool = True,
    lim: dict[str, float] | None = None,
) -> dict[int, float]:
    """Seleciona sementes anatômicas multi-quadrante na superfície da ilha para um osso."""
    nome = o["nome"]
    if nome in _RAIZES:
        return {}
    if nome in _OSSOS_TRONCO and not e_ilha_central:
        return {}
    lado = _lado_osso(nome)
    if lado == "L" and not tem_lado_l:
        return {}
    if lado == "R" and not tem_lado_r:
        return {}

    b = lim if lim is not None else _limites_anatomicos(m, tem_neck=tem_neck)
    h = b["h"]
    x_tol = b["x_tol_leg"] if nome in _OSSOS_PERNA else b["x_tol"]
    arm_z_cut = b["arm_z_cut"]
    arm_z_min = b["arm_z_min"]
    leg_top_lim = m["leg_top_z"] + 0.02 * h
    perna_max_x = b["perna_max_x"]
    braco_min_x = b["arm_root_x"]
    ombro_min_x = b["ombro_min_x"]
    ombro_max_x = b["ombro_max_x"]
    ombro_z_lo = max(b["arm_z_cut_lo"], m["shoulder_z"] - 0.08 * h)
    ombro_z_hi = m["chest_top_z"] + 0.025 * h
    tronco_seed_max_x = max(b["torso_hw"] * 1.25, 0.12 * h)
    neck_max_x = b["neck_max_x"]

    if nome in _OSSOS_PERNA:
        cat = 1
        if nome in _OSSOS_PE:
            z_lim_perna = min(leg_top_lim, m["ankle_z"] + 0.06 * h)
            z_lo_perna = b["z_min_floor"]
        elif nome in _OSSOS_CANELA:
            z_lim_perna = min(leg_top_lim, m["knee_z"] + 0.04 * h)
            z_lo_perna = b["z_min_floor"]
        else:
            z_lim_perna = leg_top_lim
            z_lo_perna = m["knee_z"] - 0.04 * h
    elif nome in _OSSOS_OMBROS:
        cat = 2
        z_lim_perna = z_lo_perna = 0.0
    elif nome in _OSSOS_BRACO_DISTAL:
        cat = 3
        z_lim_perna = z_lo_perna = 0.0
    elif nome in _OSSOS_CABECA:
        cat = 5
        z_tr_lo, z_tr_hi = b["head_z_min"], m["z_max"] + 0.01 * h
        z_lim_perna = z_lo_perna = 0.0
    elif nome in _OSSOS_PESCOCO:
        cat = 6
        z_tr_lo, z_tr_hi = b["neck_z_min"], b["neck_z_max"]
        z_lim_perna = z_lo_perna = 0.0
    elif nome in _OSSOS_TRONCO:
        cat = 4
        z_lim_perna = z_lo_perna = 0.0
        if nome == "Chest":
            z_tr_lo, z_tr_hi = b["chest_z_min"], m["chest_top_z"] + 0.03 * h
        elif nome == "UpperTorso":
            z_tr_lo, z_tr_hi = b["upper_torso_z_min"], m["chest_top_z"] + 0.03 * h
        elif nome == "Spine1":
            z_tr_lo, z_tr_hi = b["spine1_z_min"], b["spine1_z_max"]
        elif nome == "Spine":
            z_tr_lo, z_tr_hi = b["spine_z_min"], b["spine_z_max"]
        else:
            z_tr_lo, z_tr_hi = m["leg_top_z"] - 0.02 * h, b["hips_z_max"]
    else:
        cat = 0
        z_lim_perna = z_lo_perna = 0.0

    ax, ay, az = o["cabeca"]
    bx, by, bz = o["cauda"]
    abx, aby, abz = bx - ax, by - ay, bz - az
    comp2 = abx * abx + aby * aby + abz * abz
    inv_comp2 = (1.0 / comp2) if comp2 > 1e-12 else 0.0
    lado_id = 1 if lado == "L" else (-1 if lado == "R" else 0)

    cands: list[tuple[float, float, int, int]] = []
    for vi in ilha:
        vx, vy, vz = coords_xyz[vi]
        if vx > x_tol and lado_id == -1:
            continue
        if vx < -x_tol and lado_id == 1:
            continue
        abs_x = vx if vx >= 0.0 else -vx
        if cat == 1:
            if vz < z_lo_perna or vz > z_lim_perna or abs_x > perna_max_x:
                continue
        elif cat == 2:
            if vz < ombro_z_lo or vz > ombro_z_hi or abs_x < ombro_min_x or abs_x > ombro_max_x:
                continue
        elif cat == 3:
            if abs_x < braco_min_x:
                continue
            if vz < arm_z_cut and not (bracos_baixos and vz >= arm_z_min):
                continue
        elif cat == 4:
            if abs_x > tronco_seed_max_x or vz < z_tr_lo or vz > z_tr_hi:
                continue
        elif cat == 5:
            if vz < z_tr_lo or vz > z_tr_hi or abs_x > max(neck_max_x, 0.12 * h):
                continue
        elif cat == 6:
            if vz < z_tr_lo or vz > z_tr_hi or abs_x > neck_max_x:
                continue

        if inv_comp2 > 0.0:
            t_proj = ((vx - ax) * abx + (vy - ay) * aby + (vz - az) * abz) * inv_comp2
            t_proj = max(0.0, min(1.0, t_proj))
        else:
            t_proj = 0.5
        px, py, pz = ax + abx * t_proj, ay + aby * t_proj, az + abz * t_proj
        dx, dy, dz = vx - px, vy - py, vz - pz
        d2 = dx * dx + dy * dy + dz * dz
        adx = dx if dx >= 0.0 else -dx
        ady = dy if dy >= 0.0 else -dy
        if adx >= ady:
            quad = 0 if dx >= 0.0 else 1
        else:
            quad = 2 if dy >= 0.0 else 3
        cands.append((d2, t_proj, quad, vi))

    if not cands:
        return {}

    d2_min, _, _, vi_best = min(cands)
    d_min = math.sqrt(d2_min)
    max_seed_d = 0.25 * h
    if d_min > max_seed_d:
        return {}
    if d_global_min is not None and d_min > max(d_global_min * 1.45, d_global_min + 0.02 * h):
        return {}

    n_fatias = 5
    melhores_quad: list[list[tuple[float, int] | None]] = [[None, None, None, None] for _ in range(n_fatias)]
    for d2, t_proj, quad, vi in cands:
        k = min(n_fatias - 1, int(t_proj * n_fatias))
        atual = melhores_quad[k][quad]
        if atual is None or d2 < atual[0]:
            melhores_quad[k][quad] = (d2, vi)

    escolhidos: list[tuple[float, int]] = []
    limite_fatia = min(max_seed_d, max(d_min * 1.9 + 0.02 * h, d_min + 0.09 * h))
    limite_fatia2 = limite_fatia * limite_fatia
    for fatia in melhores_quad:
        for item in fatia:
            if item is not None and item[0] <= limite_fatia2:
                escolhidos.append((math.sqrt(item[0]), item[1]))
    if not escolhidos:
        escolhidos.append((d_min, vi_best))

    a, b_seg = Vector(o["cabeca"]), Vector(o["cauda"])
    sementes: dict[int, float] = {}
    for d_s, vi_s in escolhidos:
        if vi_s not in sementes or d_s < sementes[vi_s]:
            sementes[vi_s] = d_s
        limite_anel = d_s * 1.45 + 0.025 * h
        for vj, _comp in adj[vi_s]:
            vj_co = coords[vj]
            if not _osso_permitido(nome, vj_co, m, bracos_baixos):
                continue
            d_j = _dist_ponto_segmento(vj_co, a, b_seg)
            if d_j <= limite_anel and (vj not in sementes or d_j < sementes[vj]):
                sementes[vj] = d_j
    return sementes


def _construir_meta(mapas: list[tuple[str, list[float]]]) -> list[tuple[str, list[float], int, int]]:
    meta: list[tuple[str, list[float], int, int]] = []
    for nome, dist_v in mapas:
        lado = _lado_osso(nome)
        lado_id = 1 if lado == "L" else (-1 if lado == "R" else 0)
        if nome in _OSSOS_COXA:
            cat_id = 1
        elif nome in _OSSOS_CANELA:
            cat_id = 2
        elif nome in _OSSOS_PE:
            cat_id = 3
        elif nome in _OSSOS_OMBROS:
            cat_id = 4
        elif nome in _OSSOS_BRACO_DISTAL:
            cat_id = 5
        elif nome in _OSSOS_CABECA:
            cat_id = 6
        elif nome in _OSSOS_PESCOCO:
            cat_id = 7
        elif nome == "Chest":
            cat_id = 8
        elif nome == "UpperTorso":
            cat_id = 9
        elif nome == "Spine1":
            cat_id = 10
        elif nome == "Spine":
            cat_id = 11
        elif nome in ("Hips", "LowerTorso"):
            cat_id = 12
        else:
            cat_id = 0
        meta.append((nome, dist_v, lado_id, cat_id))
    return meta


def _pesos_ilha_geodesicos(
    ilha: list[int],
    adj: list[list[tuple[int, float]]],
    coords: list[Vector],
    coords_xyz: list[tuple[float, float, float]],
    ossos: list[dict],
    m: dict,
    bracos_baixos: bool,
    globais_min: dict[str, float] | None = None,
) -> dict[int, list[tuple[str, float]]] | None:
    """Calcula pesos geodésicos intra-ilha via Dijkstra; devolve None se nenhum osso existir na ilha."""
    tem_neck = any(o["nome"] == "Neck" for o in ossos)
    b = _limites_anatomicos(m, tem_neck=tem_neck)
    h = b["h"]
    x_tol, x_tol_leg = b["x_tol"], b["x_tol_leg"]
    e_ilha_central = any(abs(coords[vi].x) <= 0.05 * h for vi in ilha)
    tem_lado_l = any(coords[vi].x > x_tol for vi in ilha)
    tem_lado_r = any(coords[vi].x < -x_tol for vi in ilha)

    sementes_por_osso: list[tuple[str, dict[int, float]]] = []
    for o in ossos:
        nome = o["nome"]
        sem = _sementes_osso_ilha(
            ilha, adj, coords, coords_xyz, o, m, bracos_baixos,
            e_ilha_central, tem_lado_l, tem_lado_r,
            d_global_min=globais_min.get(nome) if globais_min else None,
            tem_neck=tem_neck, lim=b,
        )
        if sem:
            sementes_por_osso.append((nome, sem))

    if not sementes_por_osso:
        return None

    n_verts = len(coords)
    limite = 0.48 * h
    dist_mapas = [(nome, _dijkstra_osso(n_verts, adj, sem, limite)) for nome, sem in sementes_por_osso]
    inf = float("inf")
    arm_z_cut, arm_z_cut_lo, arm_z_min = b["arm_z_cut"], b["arm_z_cut_lo"], b["arm_z_min"]
    ombro_min_x, ombro_z_hi = b["ombro_min_x"], m["chest_top_z"] + 0.025 * h
    arm_root_x, arm_deltoid_x = b["arm_root_x"], b["arm_deltoid_x"]
    braco_baixo_min_x, tronco_max_x, neck_max_x = b["braco_baixo_min_x"], b["tronco_max_x"], b["neck_max_x"]
    head_z_min, neck_z_min, neck_z_max = b["head_z_min"], b["neck_z_min"], b["neck_z_max"]
    chest_z_min, upper_torso_z_min, chest_z_max = b["chest_z_min"], b["upper_torso_z_min"], b["chest_z_max"]
    spine1_z_min, spine1_z_max = b["spine1_z_min"], b["spine1_z_max"]
    spine_z_min, spine_z_max, hips_z_max = b["spine_z_min"], b["spine_z_max"], b["hips_z_max"]
    leg_z_max, upper_leg_z_min = b["leg_z_max"], b["upper_leg_z_min"]
    lower_leg_z_max, foot_z_max, z_min_floor = b["lower_leg_z_max"], b["foot_z_max"], b["z_min_floor"]

    bones_meta = _construir_meta(dist_mapas)
    eps = max(0.015 * h, 1e-4)
    saida: dict[int, list[tuple[str, float]]] = {}
    sem_alcance: list[int] = []

    for vi in ilha:
        vx, _vy, vz = coords_xyz[vi]
        abs_x = vx if vx >= 0.0 else -vx
        brutos_wn: list[tuple[float, str]] = []
        for nome, dist_v, lado_id, cat_id in bones_meta:
            d = dist_v[vi]
            if d >= inf:
                continue
            lat_tol = x_tol_leg if 1 <= cat_id <= 3 else x_tol
            if (vx > lat_tol and lado_id == -1) or (vx < -lat_tol and lado_id == 1):
                continue
            if cat_id == 1 and (vz < upper_leg_z_min or vz > leg_z_max):
                continue
            if cat_id == 2 and (vz < z_min_floor or vz > lower_leg_z_max):
                continue
            if cat_id == 3 and vz > foot_z_max:
                continue
            if cat_id == 4:
                if vz < arm_z_cut_lo or vz > ombro_z_hi or abs_x < ombro_min_x:
                    continue
                if e_ilha_central and abs_x < arm_deltoid_x:
                    d += (arm_deltoid_x - abs_x) * 3.0
            elif cat_id == 5:
                if abs_x <= x_tol:
                    continue
                if vz >= arm_z_cut:
                    if abs_x < arm_root_x:
                        continue
                    if e_ilha_central and abs_x < arm_deltoid_x:
                        d += (arm_deltoid_x - abs_x) * 4.5
                elif not (bracos_baixos and abs_x > braco_baixo_min_x and vz >= arm_z_min):
                    continue
            elif cat_id == 6 and vz < head_z_min:
                continue
            elif cat_id == 7 and (vz < neck_z_min or vz > neck_z_max or abs_x > neck_max_x):
                continue
            elif cat_id >= 8:
                if abs_x > tronco_max_x and vz >= arm_z_cut_lo:
                    continue
                if cat_id == 8 and (vz < chest_z_min or vz > chest_z_max):
                    continue
                if cat_id == 9 and (vz < upper_torso_z_min or vz > chest_z_max):
                    continue
                if cat_id == 10 and (vz < spine1_z_min or vz > spine1_z_max):
                    continue
                if cat_id == 11 and (vz < spine_z_min or vz > spine_z_max):
                    continue
                if cat_id == 12 and vz > hips_z_max:
                    continue
            de = d + eps
            de2 = de * de
            brutos_wn.append((1.0 / (de2 * de2), nome))
        if brutos_wn:
            saida[vi] = _normalizar_top4(brutos_wn)
        else:
            sem_alcance.append(vi)

    if sem_alcance:
        sem_map = dict(sementes_por_osso)
        fronteira = {vj for vi in sem_alcance for vj, _comp in adj[vi]}
        ossos_tronco_base = {"Hips", "LowerTorso", "Spine", "Spine1", "Chest", "UpperTorso"}
        recalcular = {
            nome
            for nome, dist_v, _lado_id, _cat_id in bones_meta
            if (nome in ossos_tronco_base or any(dist_v[vj] < inf for vj in fronteira))
            and any(_osso_permitido(nome, coords[vi], m, bracos_baixos, tem_neck=tem_neck, lim=b) for vi in sem_alcance)
        }
        tronco_recalc = recalcular & ossos_tronco_base
        if tronco_recalc:
            recalcular = {
                nome
                for nome in recalcular
                if nome in ossos_tronco_base
                or any(
                    _osso_permitido(nome, coords[vi], m, bracos_baixos, tem_neck=tem_neck, lim=b)
                    and not any(_osso_permitido(tb, coords[vi], m, bracos_baixos, tem_neck=tem_neck, lim=b) for tb in tronco_recalc)
                    for vi in sem_alcance
                )
            }
        if recalcular:
            dist_mapas = [
                (nome, _dijkstra_osso(n_verts, adj, sem_map[nome], inf) if nome in recalcular else dist_v)
                for nome, dist_v in dist_mapas
            ]
            bones_meta = _construir_meta(dist_mapas)

        for vi in sem_alcance:
            vx, _vy, _vz = coords_xyz[vi]
            abs_x = vx if vx >= 0.0 else -vx
            brutos_wn = []
            for nome, dist_v, _lado_id, cat_id in bones_meta:
                d = dist_v[vi]
                if d >= inf or not _osso_permitido(nome, coords[vi], m, bracos_baixos, tem_neck=tem_neck, lim=b):
                    continue
                if cat_id in (4, 5) and e_ilha_central and abs_x < arm_deltoid_x:
                    d += (arm_deltoid_x - abs_x) * (3.0 if cat_id == 4 else 4.5)
                de = d + eps
                de2 = de * de
                brutos_wn.append((1.0 / (de2 * de2), nome))
            saida[vi] = (
                _normalizar_top4(brutos_wn)
                if brutos_wn
                else _pesos_vertice_inverso(coords[vi], ossos, m, bracos_baixos, tem_neck=tem_neck, lim=b)
            )
    return saida
