"""Sementes geodesicas e calculo de pesos intra-ilha por Dijkstra (camada L2)."""

from __future__ import annotations

import math
import os
import sys

from mathutils import Vector

if __package__:
    from .autorig_const import (
        _OSSOS_BRACO, _OSSOS_BRACO_DISTAL, _OSSOS_BRACO_PROXIMAL_R15, _OSSOS_CABECA,
        _OSSOS_CANELA, _OSSOS_MEMBROS_CORE, _OSSOS_OMBROS, _OSSOS_PE,
        _OSSOS_PERNA, _OSSOS_PESCOCO, _OSSOS_TRONCO, _RAIZES, _dist_ponto_segmento, _lado_osso,
    )
    from .autorig_grafo import _dijkstra_osso, _limites_anatomicos, _osso_permitido, _pesos_vertice_inverso
    from .autorig_pesos_coerencia import (
        _OSSOS_EXTREMIDADE_BRACO, MAX_INFLUENCIAS_VERTICE, construir_hierarquia_ossos,
        filtrar_pesos_coerentes, mediar_costuras_distantes,
    )
    from .autorig_pesos_limites import _construir_meta
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import (
        _OSSOS_BRACO, _OSSOS_BRACO_DISTAL, _OSSOS_BRACO_PROXIMAL_R15, _OSSOS_CABECA,
        _OSSOS_CANELA, _OSSOS_MEMBROS_CORE, _OSSOS_OMBROS, _OSSOS_PE,
        _OSSOS_PERNA, _OSSOS_PESCOCO, _OSSOS_TRONCO, _RAIZES, _dist_ponto_segmento, _lado_osso,
    )
    from autorig_grafo import _dijkstra_osso, _limites_anatomicos, _osso_permitido, _pesos_vertice_inverso
    from autorig_pesos_coerencia import (
        _OSSOS_EXTREMIDADE_BRACO, MAX_INFLUENCIAS_VERTICE, construir_hierarquia_ossos,
        filtrar_pesos_coerentes, mediar_costuras_distantes,
    )
    from autorig_pesos_limites import _construir_meta


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
    tem_ombro: bool = True,
) -> dict[int, float]:
    """Seleciona sementes anatômicas multi-quadrante na superfície da ilha para um osso."""
    nome = o["nome"]
    if nome in _RAIZES or (nome in _OSSOS_TRONCO and not e_ilha_central):
        return {}
    lado = _lado_osso(nome)
    if (lado == "L" and not tem_lado_l) or (lado == "R" and not tem_lado_r):
        return {}

    b = lim if lim is not None else _limites_anatomicos(m, tem_neck=tem_neck)
    h = b["h"]
    x_tol = b["x_tol_leg"] if nome in _OSSOS_PERNA else b["x_tol"]
    prox_r15 = (not tem_ombro) and (nome in _OSSOS_BRACO_PROXIMAL_R15)
    arm_z_cut = b["arm_z_cut_lo"] if prox_r15 else b["arm_z_cut"]
    arm_z_min = b["arm_z_min"]
    leg_top_lim = m["leg_top_z"] + 0.02 * h
    perna_max_x = b["perna_max_x"]
    braco_min_x = b["ombro_min_x"] if prox_r15 else b["arm_root_x"]
    ombro_min_x, ombro_max_x = b["ombro_min_x"], b["ombro_max_x"]
    ombro_z_lo = max(b["arm_z_cut_lo"], m["shoulder_z"] - 0.08 * h)
    ombro_z_hi = m["chest_top_z"] + 0.025 * h
    tronco_seed_max_x = max(b["torso_hw"] * 1.25, 0.12 * h)
    neck_max_x = b["neck_max_x"]

    z_lim_perna = z_lo_perna = z_tr_lo = z_tr_hi = 0.0
    if nome in _OSSOS_PERNA:
        cat = 1
        if nome in _OSSOS_PE:
            z_lim_perna, z_lo_perna = min(leg_top_lim, m["ankle_z"] + 0.06 * h), b["z_min_floor"]
        elif nome in _OSSOS_CANELA:
            z_lim_perna, z_lo_perna = min(leg_top_lim, m["knee_z"] + 0.04 * h), b["z_min_floor"]
        else:
            z_lim_perna, z_lo_perna = leg_top_lim, m["knee_z"] - 0.04 * h
    elif nome in _OSSOS_OMBROS:
        cat = 2
    elif nome in _OSSOS_BRACO_DISTAL:
        cat = 3
    elif nome in _OSSOS_CABECA:
        cat, z_tr_lo, z_tr_hi = 5, b["head_z_min"], m["z_max"] + 0.01 * h
    elif nome in _OSSOS_PESCOCO:
        cat, z_tr_lo, z_tr_hi = 6, b["neck_z_min"], b["neck_z_max"]
    elif nome in _OSSOS_TRONCO:
        cat = 4
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

    ax, ay, az = o["cabeca"]
    bx, by, bz = o["cauda"]
    abx, aby, abz = bx - ax, by - ay, bz - az
    comp2 = abx * abx + aby * aby + abz * abz
    inv_comp2 = (1.0 / comp2) if comp2 > 1e-12 else 0.0
    lado_id = 1 if lado == "L" else (-1 if lado == "R" else 0)

    cands: list[tuple[float, float, int, int]] = []
    for vi in ilha:
        vx, vy, vz = coords_xyz[vi]
        if (vx > x_tol and lado_id == -1) or (vx < -x_tol and lado_id == 1):
            continue
        abs_x = vx if vx >= 0.0 else -vx
        if cat == 1:
            if vz < z_lo_perna or vz > z_lim_perna or abs_x > perna_max_x:
                continue
        elif cat == 2:
            if vz < ombro_z_lo or vz > ombro_z_hi or abs_x < ombro_min_x or abs_x > ombro_max_x:
                continue
        elif cat == 3:
            if abs_x < braco_min_x or vz > b["arm_z_hi"]:
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

        t_proj = max(0.0, min(1.0, ((vx - ax) * abx + (vy - ay) * aby + (vz - az) * abz) * inv_comp2)) if inv_comp2 > 0.0 else 0.5
        dx, dy, dz = vx - (ax + abx * t_proj), vy - (ay + aby * t_proj), vz - (az + abz * t_proj)
        d2 = dx * dx + dy * dy + dz * dz
        quad = (0 if dx >= 0.0 else 1) if abs(dx) >= abs(dy) else (2 if dy >= 0.0 else 3)
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
    limite_fatia2 = min(max_seed_d, max(d_min * 1.9 + 0.02 * h, d_min + 0.09 * h)) ** 2
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
            if not _osso_permitido(nome, vj_co, m, bracos_baixos, tem_neck=tem_neck, lim=b):
                continue
            d_j = _dist_ponto_segmento(vj_co, a, b_seg)
            if d_j <= limite_anel and (vj not in sementes or d_j < sementes[vj]):
                sementes[vj] = d_j
    return sementes


def _fallback_sementes_membro(
    ilha: list[int],
    coords: list[Vector],
    coords_xyz: list[tuple[float, float, float]],
    o: dict,
    b: dict[str, float],
    tem_lado_l: bool,
    tem_lado_r: bool,
    d_global_min: float | None,
) -> dict[int, float]:
    """Garante k=8 sementes travadas por lado para ossos de membro core com <3 sementes."""
    nome = o["nome"]
    lado = _lado_osso(nome)
    if (lado == "L" and not tem_lado_l) or (lado == "R" and not tem_lado_r):
        return {}
    h = b["h"]
    x_tol = b["x_tol_leg"] if nome in _OSSOS_PERNA else b["x_tol"]
    lado_id = 1 if lado == "L" else (-1 if lado == "R" else 0)
    a, b_seg = Vector(o["cabeca"]), Vector(o["cauda"])
    eh_braco = nome in _OSSOS_BRACO
    estrito: list[tuple[float, int]] = []
    amplo: list[tuple[float, int]] = []
    for vi in ilha:
        vx, _vy, vz = coords_xyz[vi]
        if (lado_id == 1 and vx <= x_tol) or (lado_id == -1 and vx >= -x_tol):
            continue
        d = _dist_ponto_segmento(coords[vi], a, b_seg)
        amplo.append((d, vi))
        abs_x = vx if vx >= 0.0 else -vx
        if eh_braco:
            if abs_x >= b["ombro_min_x"] and b["arm_z_min"] <= vz <= b["arm_z_hi"]:
                estrito.append((d, vi))
        elif abs_x <= b["perna_max_x"] + 0.04 * h and vz <= b["leg_z_max"]:
            estrito.append((d, vi))
    pool = estrito if len(estrito) >= 3 else amplo
    if not pool:
        return {}
    pool.sort(key=lambda item: item[0])
    d_min = pool[0][0]
    if d_min > 0.40 * h:
        return {}
    if d_global_min is not None and d_min > max(d_global_min * 1.45, d_global_min + 0.02 * h):
        return {}
    return {vi: d for d, vi in pool[:8]}


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
    tem_ombro = any(o["nome"] in _OSSOS_OMBROS for o in ossos)
    b = _limites_anatomicos(m, tem_neck=tem_neck)
    h = b["h"]
    x_tol, x_tol_leg = b["x_tol"], b["x_tol_leg"]
    e_ilha_central = any(abs(coords[vi].x) <= 0.05 * h for vi in ilha)
    tem_lado_l = any(coords[vi].x > x_tol for vi in ilha)
    tem_lado_r = any(coords[vi].x < -x_tol for vi in ilha)
    xs_ilha = [coords_xyz[vi][0] for vi in ilha]
    zs_ilha = [coords_xyz[vi][2] for vi in ilha]
    n_verts = len(coords)
    is_belt_like = bool(
        ilha
        and (len(ilha) < 0.30 * n_verts or not e_ilha_central)
        and max(zs_ilha) < m["shoulder_z"] - 0.14 * h
        and min(xs_ilha) < -0.045 * h
        and max(xs_ilha) > 0.045 * h
    )

    sementes_por_osso: list[tuple[str, dict[int, float]]] = []
    for o in ossos:
        nome = o["nome"]
        if is_belt_like and nome in _OSSOS_BRACO:
            continue
        d_glob = globais_min.get(nome) if globais_min else None
        sem = _sementes_osso_ilha(
            ilha, adj, coords, coords_xyz, o, m, bracos_baixos,
            e_ilha_central, tem_lado_l, tem_lado_r,
            d_global_min=d_glob, tem_neck=tem_neck, lim=b, tem_ombro=tem_ombro,
        )
        if nome in _OSSOS_MEMBROS_CORE and len(sem) < 3 and len(ilha) >= 200:
            fb_sem = _fallback_sementes_membro(ilha, coords, coords_xyz, o, b, tem_lado_l, tem_lado_r, d_glob)
            for vi_fb, d_fb in fb_sem.items():
                if vi_fb not in sem or d_fb < sem[vi_fb]:
                    sem[vi_fb] = d_fb
        if sem:
            sementes_por_osso.append((nome, sem))

    if not sementes_por_osso:
        return None

    limite = 0.48 * h
    _, dist_hier, lca_fn = construir_hierarquia_ossos(ossos)
    dist_mapas = [(nome, _dijkstra_osso(n_verts, adj, sem, limite)) for nome, sem in sementes_por_osso]
    inf = float("inf")
    arm_z_cut, arm_z_cut_lo, arm_z_min, ombro_min_x, ombro_z_hi, arm_z_hi = b["arm_z_cut"], b["arm_z_cut_lo"], b["arm_z_min"], b["ombro_min_x"], b["ombro_z_hi"], b["arm_z_hi"]
    arm_z_hi_medial, arm_ext_z_hi = b.get("arm_z_hi_medial", arm_z_hi), b.get("arm_ext_z_hi", arm_z_hi)
    arm_ext_z_soft, x_med_arm = b.get("arm_ext_z_soft", arm_ext_z_hi), (0.30 if not tem_neck else 0.245) * h
    cy, shoulder_z_hi, sh_x_eff = float(m.get("cy", 0.0)), m["shoulder_z"] + 0.025 * h, 0.5 * (abs(m["shoulder_x_L"]) + abs(m["shoulder_x_R"]))
    arm_ext_z_max, arm_ext_x_min, arm_root_x, arm_deltoid_x = b["arm_ext_z_max"], b["arm_ext_x_min"], b["arm_root_x"], b["arm_deltoid_x"]
    braco_baixo_min_x, tronco_max_x, neck_max_x = b["braco_baixo_min_x"], b["tronco_max_x"], b["neck_max_x"]
    perna_max_x, hips_max_x, arm_hip_block_z = b["perna_max_x"], b.get("hips_max_x", b["perna_max_x"] + 0.03 * h), b.get("arm_hip_block_z", -1e9)
    arms_abducted = b.get("arms_abducted", 0.0) > 0.5
    head_z_min, head_max_x, head_horn_z, head_x_horn = b["head_z_min"], b["head_max_x"], m["neck_z"] + 0.015 * h, max(b["head_max_x"] + 0.04 * h, 0.24 * h)
    head_z_soft = (head_z_min - 0.03 * h) if tem_neck else head_z_min
    prox_arm_geral = _OSSOS_BRACO_PROXIMAL_R15 | {"UpperArm.L", "UpperArm.R"}
    neck_z_min, neck_z_max, chest_z_min, upper_torso_z_min, chest_z_max, chest_z_max_collar = b["neck_z_min"], b["neck_z_max"], b["chest_z_min"], b["upper_torso_z_min"], b["chest_z_max"], b["chest_z_max_collar"]
    spine1_z_min, spine1_z_max, spine_z_min, spine_z_max, hips_z_max = b["spine1_z_min"], b["spine1_z_max"], b["spine_z_min"], b["spine_z_max"], b["hips_z_max"]
    leg_z_max, upper_leg_z_min, lower_leg_z_max, foot_z_max, z_min_floor = b["leg_z_max"], b["upper_leg_z_min"], b["lower_leg_z_max"], b["foot_z_max"], b["z_min_floor"]

    bones_meta = _construir_meta(dist_mapas)
    eps = max(0.015 * h, 1e-4)
    saida: dict[int, list[tuple[str, float]]] = {}
    sem_alcance: list[int] = []

    for vi in ilha:
        vx, vy, vz = coords_xyz[vi]
        abs_x = vx if vx >= 0.0 else -vx
        brutos_wn: list[tuple[float, str]] = []
        for nome, dist_v, lado_id, cat_id in bones_meta:
            d = dist_v[vi]
            if d >= inf:
                continue
            lat_tol = x_tol_leg if 1 <= cat_id <= 3 else x_tol
            if (vx > lat_tol and lado_id == -1) or (vx < -lat_tol and lado_id == 1):
                continue
            leg_x_cap = perna_max_x + (0.055 if vz < m["knee_z"] + 0.06 * h else 0.03) * h
            if 1 <= cat_id <= 3 and arms_abducted and abs_x > leg_x_cap:
                continue
            if cat_id == 1:
                if vz < upper_leg_z_min - 0.06 * h or vz > leg_z_max:
                    continue
                if vz < upper_leg_z_min:
                    d += (upper_leg_z_min - vz) * 6.0
            if cat_id == 2 and (vz < z_min_floor or vz > lower_leg_z_max):
                continue
            if cat_id == 3 and vz > foot_z_max:
                continue
            if cat_id == 4:
                min_x_sh = max(x_tol, 0.55 * ombro_min_x)
                z_cut_sh = (arm_z_cut_lo - 0.05 * h) if bracos_baixos else arm_z_cut_lo
                if is_belt_like or vz < z_cut_sh or vz > ombro_z_hi or abs_x < min_x_sh or (abs_x <= x_med_arm and vz > arm_z_hi_medial):
                    continue
                if vz < arm_z_cut_lo:
                    d += (arm_z_cut_lo - vz) * 6.0
                if abs_x < ombro_min_x:
                    d += (ombro_min_x - abs_x) * 8.0
                if e_ilha_central and abs_x < arm_deltoid_x:
                    d += (arm_deltoid_x - abs_x) * 3.0
            elif cat_id == 5:
                if is_belt_like or abs_x <= x_tol or vz > arm_z_hi or (abs_x <= x_med_arm and vz > arm_z_hi_medial):
                    continue
                if nome in _OSSOS_EXTREMIDADE_BRACO and (vz > arm_ext_z_hi or (vz > arm_ext_z_max and abs_x < arm_ext_x_min)):
                    continue
                if nome in _OSSOS_EXTREMIDADE_BRACO and vz > arm_ext_z_soft:
                    d += (vz - arm_ext_z_soft) * 12.0
                if tem_ombro and arms_abducted and bracos_baixos and nome in _OSSOS_EXTREMIDADE_BRACO and abs_x < arm_ext_x_min and vz >= arm_z_cut_lo - 0.02 * h:
                    d += (arm_ext_x_min - abs_x) * 10.0
                prox_r15 = (not tem_ombro) and (nome in _OSSOS_BRACO_PROXIMAL_R15)
                z_cut_a = arm_z_cut_lo if prox_r15 else arm_z_cut
                min_x_a = ombro_min_x if prox_r15 else arm_root_x
                min_x_soft = max(x_tol, 0.55 * min_x_a) if nome in prox_arm_geral else min_x_a
                if vz >= z_cut_a:
                    if abs_x < min_x_soft:
                        continue
                    if abs_x < min_x_a:
                        d += (min_x_a - abs_x) * 8.0
                    if tem_ombro and arms_abducted and nome in ("UpperArm.L", "UpperArm.R") and abs_x < sh_x_eff:
                        d += (sh_x_eff - abs_x) * 8.0
                    if e_ilha_central and abs_x < arm_deltoid_x:
                        d += (arm_deltoid_x - abs_x) * (2.0 if prox_r15 else 4.5)
                    z_hi_a = m["shoulder_z"] if prox_r15 else shoulder_z_hi
                    if vz > z_hi_a:
                        d += (vz - z_hi_a) * (14.0 if prox_r15 else 3.5)
                elif (arms_abducted and vz <= arm_hip_block_z and abs_x < hips_max_x) or not (bracos_baixos and abs_x > braco_baixo_min_x and vz >= arm_z_min):
                    continue
            elif cat_id == 6:
                acima_pescoco = vz >= head_horn_z
                chifre_lat = (not tem_neck) and e_ilha_central and vz >= arm_z_hi_medial and abs_x > head_max_x + 0.04 * h
                x_horn_lim = (0.34 * h if chifre_lat else (head_x_horn if acima_pescoco else head_max_x + 0.04 * h))
                if vz < head_z_soft or abs_x > x_horn_lim:
                    continue
                if vz < head_z_min:
                    d += (head_z_min - vz) * 6.0
                if acima_pescoco and e_ilha_central and abs_x > 0.24 * h:
                    d += (abs_x - 0.24 * h) * 4.0
                elif not acima_pescoco and abs_x > head_max_x * 0.85:
                    d += (abs_x - head_max_x * 0.85) * 6.0
                if vz < m["neck_z"] + 0.03 * h and abs_x > arm_root_x * 0.96:
                    continue
            elif cat_id == 7:
                if vz < neck_z_min or vz > neck_z_max + 0.04 * h or abs_x > neck_max_x + 0.04 * h:
                    continue
                if vz > neck_z_max:
                    d += (vz - neck_z_max) * 5.0
                if abs_x > neck_max_x:
                    d += (abs_x - neck_max_x) * 5.0
            elif cat_id >= 8:
                z_cut_tr = (spine_z_min if cat_id == 11 else upper_torso_z_min) if (arms_abducted and cat_id <= 11) else arm_z_cut_lo
                if abs_x > tronco_max_x and vz >= z_cut_tr:
                    continue
                if cat_id in (8, 9):
                    z_lo = chest_z_min if cat_id == 8 else upper_torso_z_min
                    z_hi = chest_z_max_collar if abs_x > head_max_x * 0.9 else chest_z_max + 0.06 * h
                    if vz < z_lo or vz > z_hi:
                        continue
                    # Rampa lateral suave na axila/deltoide para evitar degrau brusco em tronco_max_x.
                    if arms_abducted and arm_root_x < abs_x <= tronco_max_x:
                        d += (abs_x - arm_root_x) * 8.0
                    if cat_id == 8 and vz > chest_z_max and abs_x <= head_max_x * 0.9:
                        d += (vz - chest_z_max) * 4.0
                elif cat_id == 10 and (vz < spine1_z_min or vz > spine1_z_max):
                    continue
                elif cat_id == 11 and (vz < spine_z_min or vz > spine_z_max):
                    continue
                elif cat_id == 12:
                    if vz > hips_z_max or (arms_abducted and abs_x > hips_max_x):
                        continue
                    if abs_x > tronco_max_x:
                        d += (abs_x - tronco_max_x) * 6.0
                    if e_ilha_central and abs_x > x_tol_leg and vy >= cy - 0.055 * h:
                        if vz < m["knee_z"] + 0.02 * h:
                            continue
                        if vz < m["knee_z"] + 0.12 * h:
                            d += (m["knee_z"] + 0.12 * h - vz) * 8.0
            de = d + eps
            de2 = de * de
            brutos_wn.append((1.0 / (de2 * de2), nome))
        if brutos_wn:
            saida[vi] = filtrar_pesos_coerentes(brutos_wn, dist_hier, max_k=MAX_INFLUENCIAS_VERTICE)
        else:
            sem_alcance.append(vi)

    if sem_alcance:
        sem_map = dict(sementes_por_osso)
        fronteira = {vj for vi in sem_alcance for vj, _comp in adj[vi]}
        ossos_tronco_base = {"Hips", "LowerTorso", "Spine", "Spine1", "Chest", "UpperTorso"}
        recalcular = {
            nome
            for nome, dist_v, _lado_id, _cat_id in bones_meta
            if not (is_belt_like and nome in _OSSOS_BRACO)
            and (nome in ossos_tronco_base or any(dist_v[vj] < inf for vj in fronteira))
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

        ossos_fb = [o for o in ossos if not (is_belt_like and o["nome"] in _OSSOS_BRACO)]
        for vi in sem_alcance:
            vx, _vy, _vz = coords_xyz[vi]
            abs_x = vx if vx >= 0.0 else -vx
            brutos_wn = []
            for nome, dist_v, _lado_id, cat_id in bones_meta:
                if is_belt_like and nome in _OSSOS_BRACO:
                    continue
                d = dist_v[vi]
                if d >= inf or not _osso_permitido(nome, coords[vi], m, bracos_baixos, tem_neck=tem_neck, lim=b):
                    continue
                if cat_id in (4, 5) and e_ilha_central and abs_x < arm_deltoid_x:
                    prox_r15 = (not tem_ombro) and (nome in _OSSOS_BRACO_PROXIMAL_R15)
                    fator_d = 3.0 if cat_id == 4 else (2.0 if prox_r15 else 4.5)
                    d += (arm_deltoid_x - abs_x) * fator_d
                elif cat_id in (8, 9) and arms_abducted and arm_root_x < abs_x <= tronco_max_x:
                    d += (abs_x - arm_root_x) * 8.0
                de = d + eps
                de2 = de * de
                brutos_wn.append((1.0 / (de2 * de2), nome))
            if brutos_wn:
                saida[vi] = filtrar_pesos_coerentes(brutos_wn, dist_hier, max_k=MAX_INFLUENCIAS_VERTICE)
            else:
                fb = _pesos_vertice_inverso(coords[vi], ossos_fb or ossos, m, bracos_baixos, tem_neck=tem_neck, lim=b)
                saida[vi] = filtrar_pesos_coerentes([(w, n) for n, w in fb], dist_hier, max_k=MAX_INFLUENCIAS_VERTICE)
    mediar_costuras_distantes(ilha, adj, saida, dist_hier, lca_fn, max_k=MAX_INFLUENCIAS_VERTICE)
    return saida
