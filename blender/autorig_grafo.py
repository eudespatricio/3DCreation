"""Grafo topologico de superficie, limites anatomicos e Dijkstra para skinning (camada L1)."""

from __future__ import annotations

import heapq
import os
import sys

from mathutils import Vector

if __package__:
    from .autorig_const import (
        _OSSOS_BRACO,
        _OSSOS_BRACO_DISTAL,
        _OSSOS_BRACO_PROXIMAL_R15,
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
    from .autorig_pesos_coerencia import (
        _OSSOS_EXTREMIDADE_BRACO,
        MAX_INFLUENCIAS_VERTICE,
        normalizar_top_k,
    )
    from .autorig_pesos_limites import _limites_anatomicos
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import (
        _OSSOS_BRACO,
        _OSSOS_BRACO_DISTAL,
        _OSSOS_BRACO_PROXIMAL_R15,
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
    from autorig_pesos_coerencia import (
        _OSSOS_EXTREMIDADE_BRACO,
        MAX_INFLUENCIAS_VERTICE,
        normalizar_top_k,
    )
    from autorig_pesos_limites import _limites_anatomicos


def _osso_permitido(
    nome: str,
    v: Vector,
    m: dict,
    bracos_baixos: bool,
    tem_neck: bool = True,
    lim: dict[str, float] | None = None,
) -> bool:
    if nome in _RAIZES:
        return False
    b = lim if lim is not None else _limites_anatomicos(m, tem_neck=tem_neck)
    h = b["h"]
    lado = _lado_osso(nome)
    vx, vz = v.x, v.z
    abs_x = vx if vx >= 0.0 else -vx
    x_tol = b["x_tol_leg"] if nome in _OSSOS_PERNA else b["x_tol"]
    if vx > x_tol and lado == "R":
        return False
    if vx < -x_tol and lado == "L":
        return False
    if abs_x <= b["x_tol"] and nome in _OSSOS_BRACO:
        return False

    arms_abducted = b.get("arms_abducted", 0.0) > 0.5
    if nome in _OSSOS_PERNA and arms_abducted and abs_x > b["perna_max_x"] + 0.03 * h:
        return False
    if nome in _OSSOS_PE:
        return vz <= b["foot_z_max"]
    if nome in _OSSOS_CANELA:
        return b["z_min_floor"] <= vz <= b["lower_leg_z_max"]
    if nome in _OSSOS_COXA:
        return b["upper_leg_z_min"] <= vz <= b["leg_z_max"]
    x_med_arm = (0.30 if not tem_neck else 0.245) * h
    if nome in _OSSOS_OMBROS:
        if abs_x <= x_med_arm and vz > b["arm_z_hi_medial"]:
            return False
        return b["arm_z_cut_lo"] <= vz <= b["ombro_z_hi"] and abs_x >= b["ombro_min_x"]
    if nome in _OSSOS_BRACO_DISTAL:
        if vz > b["arm_z_hi"] or (abs_x <= x_med_arm and vz > b["arm_z_hi_medial"]):
            return False
        if nome in _OSSOS_EXTREMIDADE_BRACO and (vz > b["arm_ext_z_hi"] or (vz > b["arm_ext_z_max"] and abs_x < b["arm_ext_x_min"])):
            return False
        z_cut_a = b["arm_z_cut_lo"] if nome in _OSSOS_BRACO_PROXIMAL_R15 else b["arm_z_cut"]
        min_x_a = b["ombro_min_x"] if nome in _OSSOS_BRACO_PROXIMAL_R15 else b["arm_root_x"]
        if vz >= z_cut_a and abs_x >= min_x_a:
            return True
        if arms_abducted and vz <= b.get("arm_hip_block_z", -1e9) and abs_x < b.get("hips_max_x", b["perna_max_x"] + 0.03 * h):
            return False
        return bracos_baixos and abs_x > b["braco_baixo_min_x"] and vz >= b["arm_z_min"]
    if nome in _OSSOS_CABECA:
        z_lo_head = (b["head_z_min"] - 0.03 * h) if tem_neck else b["head_z_min"]
        chifre_lat = (not tem_neck) and vz >= b["arm_z_hi_medial"] and abs_x > b["head_max_x"] + 0.04 * h
        head_x_hi = 0.34 * h if chifre_lat else max(b["head_max_x"] + 0.04 * h, 0.24 * h)
        head_x_lim = head_x_hi if (chifre_lat or vz >= m["neck_z"] + 0.015 * h) else (b["head_max_x"] + 0.04 * h)
        return vz >= z_lo_head and abs_x <= head_x_lim
    if nome in _OSSOS_PESCOCO:
        return b["neck_z_min"] <= vz <= b["neck_z_max"] + 0.04 * h and abs_x <= b["neck_max_x"] + 0.04 * h
    if nome in _OSSOS_TRONCO:
        if nome in ("Hips", "LowerTorso"):
            if abs_x > b["tronco_max_x"] and vz >= b["arm_z_cut_lo"]:
                return False
            if arms_abducted and abs_x > b.get("hips_max_x", b["perna_max_x"] + 0.03 * h):
                return False
            return vz <= b["hips_z_max"]
        # Em A-pose abduzida, fecha a brecha abaixo de arm_z_cut_lo para impedir vazamento de tronco no cotovelo/antebraco.
        z_cut_tronco = (b["spine_z_min"] if nome == "Spine" else b["upper_torso_z_min"]) if arms_abducted else b["arm_z_cut_lo"]
        if abs_x > b["tronco_max_x"] and vz >= z_cut_tronco:
            return False
        if nome in ("Chest", "UpperTorso"):
            z_lo = b["chest_z_min"] if nome == "Chest" else b["upper_torso_z_min"]
            z_hi = b["chest_z_max_collar"] if abs_x > b["head_max_x"] * 0.9 else b["chest_z_max"] + 0.06 * h
            return z_lo <= vz <= z_hi
        if nome == "Spine1":
            return b["spine1_z_min"] <= vz <= b["spine1_z_max"]
        if nome == "Spine":
            return b["spine_z_min"] <= vz <= b["spine_z_max"]
    return True


def _osso_permitido_semente(
    nome: str,
    v: Vector,
    m: dict,
    bracos_baixos: bool,
    tem_neck: bool = True,
    lim: dict[str, float] | None = None,
) -> bool:
    """Filtro anatômico estrito para impedir sementes geodésicas de cruzar vão aéreo."""
    b = lim if lim is not None else _limites_anatomicos(m, tem_neck=tem_neck)
    if not _osso_permitido(nome, v, m, bracos_baixos, tem_neck=tem_neck, lim=b):
        return False
    h = b["h"]
    abs_x = abs(v.x)

    if nome in _OSSOS_PERNA:
        if v.z > m["leg_top_z"] + 0.02 * h or abs_x > b["perna_max_x"]:
            return False
        if nome in _OSSOS_PE:
            return v.z <= m["ankle_z"] + 0.06 * h
        if nome in _OSSOS_CANELA:
            return v.z <= m["knee_z"] + 0.04 * h
        return True

    x_med_arm = (0.30 if not tem_neck else 0.245) * h
    if nome in _OSSOS_OMBROS:
        if abs_x <= x_med_arm and v.z > b["arm_z_hi_medial"]:
            return False
        return m["shoulder_z"] - 0.08 * h <= v.z <= b["ombro_z_hi"] and b["ombro_min_x"] <= abs_x <= b["ombro_max_x"]
    if nome in _OSSOS_BRACO_DISTAL:
        min_x = b["ombro_min_x"] if nome in _OSSOS_BRACO_PROXIMAL_R15 else b["arm_root_x"]
        if nome in _OSSOS_EXTREMIDADE_BRACO and v.z > b["arm_ext_z_hi"]:
            return False
        if abs_x <= x_med_arm and v.z > min(b["arm_z_hi"], m["shoulder_z"] + 0.06 * h):
            return False
        if abs_x <= x_med_arm and v.z > b["arm_z_hi_medial"]:
            return False
        return v.z <= b["arm_z_hi"] and abs_x >= min_x

    if nome in _OSSOS_CABECA:
        return abs_x <= max(b["neck_max_x"], 0.12 * h)
    if nome in _OSSOS_PESCOCO:
        return abs_x <= b["neck_max_x"]
    if nome in _OSSOS_TRONCO:
        if abs_x > max(b["torso_hw"] * 1.25, 0.12 * h):
            return False
        return m["leg_top_z"] - 0.02 * h <= v.z <= m["chest_top_z"] + 0.03 * h

    return True


def _ilhas_vertices(bm) -> list[list[int]]:
    """Particiona vértices da malha em ilhas conexas via travessia de arestas bmesh."""
    bm.verts.index_update()
    bm.verts.ensure_lookup_table()
    n = len(bm.verts)
    visitado = bytearray(n)
    ilhas: list[list[int]] = []
    for i in range(n):
        if visitado[i]:
            continue
        visitado[i] = 1
        ilha = [i]
        fila = [i]
        pos = 0
        while pos < len(fila):
            vi = fila[pos]
            pos += 1
            v = bm.verts[vi]
            for e in v.link_edges:
                vj = e.other_vert(v).index
                if not visitado[vj]:
                    visitado[vj] = 1
                    fila.append(vj)
                    ilha.append(vj)
        ilhas.append(ilha)
    ilhas.sort(key=len, reverse=True)
    return ilhas


def _grafo_superficie(bm) -> list[list[tuple[int, float]]]:
    """Constrói grafo de adjacência de superfície em espaço de objeto: adj[vi] = [(vj, comp), ...]."""
    bm.verts.index_update()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    adj: list[list[tuple[int, float]]] = [[] for _ in range(len(bm.verts))]
    for e in bm.edges:
        v0, v1 = e.verts[0], e.verts[1]
        i, j = v0.index, v1.index
        if i == j:
            continue
        comp = (v0.co - v1.co).length
        adj[i].append((j, comp))
        adj[j].append((i, comp))
    return adj


def _projecao_segmento(p: Vector, a: Vector, b: Vector) -> tuple[float, float]:
    ab = b - a
    comp2 = ab.length_squared
    if comp2 <= 1e-12:
        return (p - a).length, 0.5
    t = max(0.0, min(1.0, (p - a).dot(ab) / comp2))
    return (p - (a + ab * t)).length, t


def _dijkstra_osso(
    n_verts: int,
    adj: list[list[tuple[int, float]]],
    sementes: dict[int, float],
    limite_dist: float,
) -> list[float]:
    """Executa Dijkstra multi-semente em grafo de superfície com teto opcional de distância."""
    inf = float("inf")
    dist = [inf] * n_verts
    pq: list[tuple[float, int]] = []
    heappush = heapq.heappush
    heappop = heapq.heappop

    for vi, d0 in sementes.items():
        if d0 < dist[vi]:
            dist[vi] = d0
            heappush(pq, (d0, vi))

    while pq:
        d, u = heappop(pq)
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd <= limite_dist and nd < dist[v]:
                dist[v] = nd
                heappush(pq, (nd, v))
    return dist


def _normalizar_top4(
    brutos_wn: list[tuple[float, str]],
    max_k: int = MAX_INFLUENCIAS_VERTICE,
) -> list[tuple[str, float]]:
    return normalizar_top_k(brutos_wn, max_k=max_k)


def _pesos_vertice_inverso(
    v: Vector,
    ossos: list[dict],
    m: dict,
    bracos_baixos: bool,
    tem_neck: bool = True,
    lim: dict[str, float] | None = None,
) -> list[tuple[str, float]]:
    b = lim if lim is not None else _limites_anatomicos(m, tem_neck=tem_neck)
    h = b["h"]
    eps = max(0.015 * h, 1e-4)
    brutos_wn: list[tuple[float, str]] = []
    for o in ossos:
        nome = o["nome"]
        if not _osso_permitido(nome, v, m, bracos_baixos, tem_neck=tem_neck, lim=b):
            continue
        d = _dist_ponto_segmento(v, Vector(o["cabeca"]), Vector(o["cauda"]))
        if nome in _OSSOS_OMBROS and abs(v.x) < b["arm_root_x"]:
            d += (b["arm_root_x"] - abs(v.x)) * 1.8
        brutos_wn.append((1.0 / ((d + eps) ** 4), nome))

    if not brutos_wn:
        melhor = min(
            (o for o in ossos if o["nome"] not in _RAIZES),
            key=lambda o: _dist_ponto_segmento(v, Vector(o["cabeca"]), Vector(o["cauda"])),
        )
        return [(melhor["nome"], 1.0)]

    return _normalizar_top4(brutos_wn)


def _normalizar_grupos_e_mapear(
    obj,
    max_influencias: int = MAX_INFLUENCIAS_VERTICE,
) -> dict[str, list[int]]:
    """Limita a max_influencias por vértice, normaliza soma = 1.0 e devolve osso -> índices."""
    for vg in list(obj.vertex_groups):
        if vg.name in _RAIZES:
            obj.vertex_groups.remove(vg)
    vgs = {vg.index: vg for vg in obj.vertex_groups}
    mapa: dict[str, list[int]] = {}
    for v in obj.data.vertices:
        pares = []
        zerados = []
        for g in v.groups:
            vg = vgs.get(g.group)
            if vg is None:
                continue
            if g.weight <= 1e-6:
                zerados.append(vg)
            else:
                pares.append((vg, float(g.weight)))
        for vg in zerados:
            vg.remove([v.index])
        if not pares:
            continue
        if len(pares) > max_influencias:
            pares.sort(key=lambda item: item[1], reverse=True)
            manter = pares[:max_influencias]
            for vg, _w in pares[max_influencias:]:
                vg.remove([v.index])
        else:
            manter = pares
        soma = sum(w for _, w in manter)
        if soma > 0.0:
            if abs(soma - 1.0) > 1e-5:
                for vg, w in manter:
                    wn = w / soma
                    vg.add([v.index], wn, "REPLACE")
            for vg, _w in manter:
                mapa.setdefault(vg.name, []).append(v.index)
    return {k: sorted(v) for k, v in mapa.items() if v}


def _suavizar_aneis_juntas(
    adj: list[list[tuple[int, float]]],
    pesos_por_vertice: dict[int, list[tuple[str, float]]],
    ossos: list[dict],
    permitido_fn=None,
    passos: int = 2,
    alpha: float = 0.25,
    pares_bloqueados: set[frozenset[str]] | None = None,
    max_k: int = MAX_INFLUENCIAS_VERTICE,
) -> None:
    """Suaviza pesos apenas nos aneis de fronteira entre ossos pai-filho adjacentes."""
    if not pesos_por_vertice:
        return
    pai_map = {o["nome"]: o["pai"] for o in ossos if o.get("pai")}
    bloqueados = pares_bloqueados or set()

    def _junta_valida(a: str, b: str) -> bool:
        if a == b:
            return True
        if frozenset((a, b)) in bloqueados:
            return False
        return pai_map.get(a) == b or pai_map.get(b) == a

    dom = {vi: ws[0][0] for vi, ws in pesos_por_vertice.items() if ws}
    fronteira: set[int] = set()
    for vi, d_i in dom.items():
        for vj, _c in adj[vi]:
            d_j = dom.get(vj)
            if d_j and d_j != d_i and _junta_valida(d_i, d_j):
                fronteira.add(vi)
                break
    if not fronteira:
        return

    anel: set[int] = set(fronteira)
    for vi in fronteira:
        d_i = dom.get(vi)
        if not d_i:
            continue
        for vj, _c in adj[vi]:
            d_j = dom.get(vj)
            if d_j and _junta_valida(d_i, d_j):
                anel.add(vj)

    for _ in range(passos):
        novos: dict[int, list[tuple[str, float]]] = {}
        for vi in anel:
            ws_i = pesos_por_vertice.get(vi)
            if not ws_i:
                continue
            d_i = ws_i[0][0]
            viz_list = adj[vi]
            if not viz_list:
                continue
            acum: dict[str, float] = {n: w * (1.0 - alpha) for n, w in ws_i}
            fator = alpha / float(len(viz_list))
            for vj, _c in viz_list:
                for n, w in pesos_por_vertice.get(vj, ()):
                    if not _junta_valida(d_i, n):
                        continue
                    if permitido_fn is not None and not permitido_fn(n, vi):
                        continue
                    acum[n] = acum.get(n, 0.0) + w * fator
            novos[vi] = _normalizar_top4([(w, n) for n, w in acum.items() if w > 1e-6], max_k=max_k)
        for vi, ws_novo in novos.items():
            if ws_novo:
                pesos_por_vertice[vi] = ws_novo
