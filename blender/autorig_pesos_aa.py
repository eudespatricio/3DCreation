"""Refino AA (56 ossos), acessorios desconexos e atribuicao de pesos (camada L3)."""

from __future__ import annotations

import os
import sys

import bmesh
from mathutils import Vector

if __package__:
    from .autorig_const import _DEDOS_NOMES, _OSSOS_AA_EXTRAS, _OSSOS_DEDOS, _RAIZES, _centroide, _clamped, _dist_ponto_segmento, _lado_osso
    from .autorig_grafo import _grafo_superficie, _ilhas_vertices, _limites_anatomicos, _normalizar_top4, _osso_permitido, _osso_permitido_semente, _suavizar_aneis_juntas
    from .autorig_ossos import _quadro_mao
    from .autorig_pesos_coerencia import MAX_INFLUENCIAS_VERTICE, construir_hierarquia_ossos, filtrar_pesos_coerentes
    from .autorig_pesos_geo import _pesos_ilha_geodesicos
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import _DEDOS_NOMES, _OSSOS_AA_EXTRAS, _OSSOS_DEDOS, _RAIZES, _centroide, _clamped, _dist_ponto_segmento, _lado_osso
    from autorig_grafo import _grafo_superficie, _ilhas_vertices, _limites_anatomicos, _normalizar_top4, _osso_permitido, _osso_permitido_semente, _suavizar_aneis_juntas
    from autorig_ossos import _quadro_mao
    from autorig_pesos_coerencia import MAX_INFLUENCIAS_VERTICE, construir_hierarquia_ossos, filtrar_pesos_coerentes
    from autorig_pesos_geo import _pesos_ilha_geodesicos


def _osso_acessorio_ilha(
    ilha: list[int],
    coords: list[Vector],
    coords_xyz: list[tuple[float, float, float]],
    ossos: list[dict],
    m: dict,
    bracos_baixos: bool,
    ilha_principal: list[int] | None,
    pesos_principais: dict[int, list[tuple[str, float]]],
) -> str:
    """Escolhe um único osso coerente para ilha desconexa pequena (armadura/pouch/acessório)."""
    c = _centroide([coords[vi] for vi in ilha], Vector((0.0, 0.0, 0.0)))
    cx, cy, cz = c.x, c.y, c.z
    tem_neck = any(o["nome"] == "Neck" for o in ossos)
    b = _limites_anatomicos(m, tem_neck=tem_neck)
    h = b["h"]
    if ilha_principal and pesos_principais:
        d2_min = float("inf")
        vi_main = ilha_principal[0]
        for vj in ilha_principal:
            vx, vy, vz = coords_xyz[vj]
            dx, dy, dz = vx - cx, vy - cy, vz - cz
            d2 = dx * dx + dy * dy + dz * dz
            if d2 < d2_min:
                d2_min = d2
                vi_main = vj
        if d2_min <= (0.12 * h) ** 2:
            for nome, _peso in pesos_principais.get(vi_main, ()):
                if _osso_permitido(nome, c, m, bracos_baixos, tem_neck=tem_neck, lim=b):
                    return nome

    validos = [o for o in ossos if o["nome"] not in _RAIZES and _osso_permitido(o["nome"], c, m, bracos_baixos, tem_neck=tem_neck, lim=b)]
    if not validos:
        validos = [o for o in ossos if o["nome"] not in _RAIZES]
    melhor = min(validos, key=lambda o: _dist_ponto_segmento(c, Vector(o["cabeca"]), Vector(o["cauda"])))
    return melhor["nome"]


def _refinar_pesos_aa_56(
    obj,
    ossos: list[dict],
    m: dict,
    coords: list[Vector],
    coords_xyz: list[tuple[float, float, float]],
    ilhas: list[list[int]],
    pesos_por_vertice: dict[int, list[tuple[str, float]]],
    adj: list[list[tuple[int, float]]] | None = None,
) -> None:
    """Distribui pesos para falanges (30 ossos), olhos, mandibula e capa no rig godot-humanoid-aa@1."""
    ossos_por_nome = {o["nome"]: o for o in ossos}
    h = float(m["altura"])
    cy = float(m["cy"])
    n_total = len(coords)

    if "Cape" in ossos_por_nome:
        cape_slots = {
            idx
            for idx, mat in enumerate(obj.data.materials)
            if mat is not None and any(k in str(mat.name).lower() for k in ("cape", "capa"))
        }
        verts_capa: set[int] = set()
        if cape_slots:
            for poly in obj.data.polygons:
                if poly.material_index in cape_slots:
                    verts_capa.update(poly.vertices)
        for idx_ilha, ilha in enumerate(ilhas):
            if idx_ilha == 0:
                continue
            ys = [coords_xyz[vi][1] for vi in ilha]
            zs = [coords_xyz[vi][2] for vi in ilha]
            xs = [coords_xyz[vi][0] for vi in ilha]
            if (
                max(ys) < cy - 0.02 * h
                and min(zs) < m["chest_z"]
                and max(zs) >= m["chest_z"] - 0.03 * h
                and max(xs) < 0.35 * h
                and min(xs) > -0.35 * h
            ):
                verts_capa.update(ilha)
        for vi in verts_capa:
            vz = coords_xyz[vi][2]
            if vz >= m["chest_top_z"] - 0.03 * h and "Chest" in ossos_por_nome:
                pesos_por_vertice[vi] = [("Cape", 0.65), ("Chest", 0.35)]
            else:
                pesos_por_vertice[vi] = [("Cape", 1.0)]

    verts_olho: set[int] = set()
    if "Eye.L" in ossos_por_nome and "Eye.R" in ossos_por_nome:
        eye_slots = {
            idx
            for idx, mat in enumerate(obj.data.materials)
            if mat is not None and str(mat.name).lower().startswith("eye")
        }
        if eye_slots:
            for poly in obj.data.polygons:
                if poly.material_index in eye_slots:
                    for vi in poly.vertices:
                        verts_olho.add(vi)
                        alvo_e = "Eye.R" if coords_xyz[vi][0] >= 0.0 else "Eye.L"
                        pesos_por_vertice[vi] = [(alvo_e, 1.0)]
        eye_l_h = Vector(ossos_por_nome["Eye.L"]["cabeca"])
        eye_r_h = Vector(ossos_por_nome["Eye.R"]["cabeca"])
        for idx_ilha, ilha in enumerate(ilhas):
            if idx_ilha == 0 or len(ilha) >= 0.08 * n_total:
                continue
            c_i = _centroide([coords[vi] for vi in ilha], Vector((0.0, 0.0, 0.0)))
            if (c_i - eye_l_h).length <= 0.035 * h:
                for vi in ilha:
                    verts_olho.add(vi)
                    pesos_por_vertice[vi] = [("Eye.L", 1.0)]
            elif (c_i - eye_r_h).length <= 0.035 * h:
                for vi in ilha:
                    verts_olho.add(vi)
                    pesos_por_vertice[vi] = [("Eye.R", 1.0)]

    if "Jaw" in ossos_por_nome:
        jaw_h = Vector(ossos_por_nome["Jaw"]["cabeca"])
        jaw_t = Vector(ossos_por_nome["Jaw"]["cauda"])
        head_h = max(m["head_top_z"] - m["neck_z"], 0.10 * h)
        z_j_lo = m["neck_z"] + 0.02 * head_h
        z_j_hi = m["neck_z"] + 0.40 * head_h
        raio_jaw = 0.055 * h
        for vi in range(n_total):
            if vi in verts_olho:
                continue
            vx, vy, vz = coords_xyz[vi]
            if vy <= cy + 0.015 * h or vz < z_j_lo or vz > z_j_hi or abs(vx) > 0.058 * h:
                continue
            cur = pesos_por_vertice.get(vi) or []
            w_head = sum(w for n, w in cur if n == "Head")
            if w_head < 0.15:
                continue
            d_jaw = _dist_ponto_segmento(coords[vi], jaw_h, jaw_t)
            if d_jaw >= raio_jaw:
                continue
            alpha = _clamped(0.85 * (1.0 - d_jaw / raio_jaw), 0.0, 0.80)
            novos_w = [(w, n) for n, w in cur if n != "Head"]
            novos_w.append((w_head * (1.0 - alpha), "Head"))
            novos_w.append((w_head * alpha, "Jaw"))
            pesos_por_vertice[vi] = _normalizar_top4(novos_w)

    eps_f = max(0.0025 * h, 1e-4)
    vert_ilha_id = {vi: iid for iid, il in enumerate(ilhas) for vi in il}
    vert_ilha_tam = {vi: len(il) for il in ilhas for vi in il}
    for lado, sinal in (("L", -1.0), ("R", 1.0)):
        hand_name = f"Hand.{lado}"
        hand_osso = ossos_por_nome.get(hand_name)
        dedos_lado = [ossos_por_nome[f"{d}{idx}.{lado}"] for d in _DEDOS_NOMES for idx in (1, 2, 3) if f"{d}{idx}.{lado}" in ossos_por_nome]
        if hand_osso is None or not dedos_lado:
            continue
        wrist = Vector(m[f"braco_{lado}"]["wrist"])
        tip = Vector(m[f"braco_{lado}"]["tip"])
        u_hand, _u_thumb, _u_palm, len_hand = _quadro_mao(wrist, tip, h, sinal)
        hand_head = Vector(hand_osso["cabeca"])
        hand_tail = Vector(hand_osso["cauda"])
        thumb1_h = Vector(ossos_por_nome[f"Thumb1.{lado}"]["cabeca"])
        thumb3_t = Vector(ossos_por_nome[f"Thumb3.{lado}"]["cauda"])
        arm_name = f"LowerArm.{lado}"
        ilhas_dedos: list[tuple[float, int]] = []
        thumb_ilhas: set[int] = set()
        for iid, il in enumerate(ilhas):
            if not il or len(il) >= 80:
                continue
            tem_mao_ou_antebraco = any(any(n in (hand_name, arm_name) and w >= 0.05 for n, w in pesos_por_vertice.get(vi, ())) for vi in il)
            if not tem_mao_ou_antebraco:
                continue
            c_il = _centroide([coords[vi] for vi in il], Vector((0.0, 0.0, 0.0)))
            if (c_il - wrist).dot(u_hand) / max(len_hand, 1e-5) >= 0.25:
                if any(any(n == hand_name and w >= 0.05 for n, w in pesos_por_vertice.get(vi, ())) for vi in il):
                    ilhas_dedos.append((c_il.dot(_u_thumb), iid))
            elif (c_il - wrist).dot(_u_thumb) > 0.005 * h and _dist_ponto_segmento(c_il, thumb1_h, thumb3_t) <= 0.040 * h:
                thumb_ilhas.add(iid)
        fam_por_ilha: dict[int, list[dict]] = {}
        thumb_bones = [ossos_por_nome[f"Thumb{idx}.{lado}"] for idx in (1, 2, 3) if f"Thumb{idx}.{lado}" in ossos_por_nome]
        for tid in thumb_ilhas:
            fam_por_ilha[tid] = thumb_bones
        if 2 <= len(ilhas_dedos) <= 5:
            ilhas_dedos.sort(reverse=True)
            fams_ord = ("Thumb", "Index", "Middle", "Ring", "Little") if len(ilhas_dedos) == 5 else ("Index", "Middle", "Ring", "Little")
            for (_, iid), fam in zip(ilhas_dedos, fams_ord):
                fam_por_ilha[iid] = [ossos_por_nome[f"{fam}{idx}.{lado}"] for idx in (1, 2, 3) if f"{fam}{idx}.{lado}" in ossos_por_nome]

        for vi in range(n_total):
            cur = pesos_por_vertice.get(vi) or []
            eh_thumb_il = vert_ilha_id.get(vi, -1) in thumb_ilhas
            w_hand = sum(w for n, w in cur if n == hand_name)
            w_src = w_hand if w_hand >= 0.05 else (sum(w for n, w in cur if n == arm_name) if eh_thumb_il else 0.0)
            if w_src < 0.05:
                continue
            v = coords[vi]
            t_along = (v - wrist).dot(u_hand) / max(len_hand, 1e-5)
            d_thumb_zone = _dist_ponto_segmento(v, thumb1_h, thumb3_t)
            blend = 1.0 if eh_thumb_il else max(
                _clamped((t_along - 0.18) / 0.22, 0.0, 1.0),
                _clamped(1.0 - d_thumb_zone / (0.045 * h), 0.0, 1.0),
            )
            if blend <= 0.01:
                continue
            d_palm = _dist_ponto_segmento(v, hand_head, hand_tail) + (0.014 * h if t_along > 0.48 else 0.0)
            cands_w: list[tuple[float, str]] = [(1.0 / ((d_palm + eps_f) ** 5), hand_name)]
            for fo in fam_por_ilha.get(vert_ilha_id.get(vi, -1), dedos_lado):
                df = _dist_ponto_segmento(v, Vector(fo["cabeca"]), Vector(fo["cauda"]))
                cands_w.append((1.0 / ((df + eps_f) ** 5), fo["nome"]))
            dist_mao = _normalizar_top4(cands_w, max_k=3)
            skip_key = arm_name if (eh_thumb_il and w_hand < 0.05) else hand_name
            acum_m: dict[str, float] = {n: w for n, w in cur if n != skip_key}
            w_rem = (1.0 - blend) * w_src
            if w_rem > 1e-6:
                acum_m[hand_name] = acum_m.get(hand_name, 0.0) + w_rem
            for n_sub, w_sub in dist_mao:
                acum_m[n_sub] = acum_m.get(n_sub, 0.0) + blend * w_src * w_sub
            pesos_por_vertice[vi] = _normalizar_top4([(w, n) for n, w in acum_m.items()], max_k=3)

    _, dist_hier_aa, _ = construir_hierarquia_ossos(ossos)
    if adj is not None:
        dom_aa = {vi: ws[0][0] for vi, ws in pesos_por_vertice.items() if ws}
        mitten_lados: set[str] = set()
        for vi, di in dom_aa.items():
            if di not in _OSSOS_DEDOS or vert_ilha_tam.get(vi, 0) < 80:
                continue
            for vj, _ in adj[vi]:
                dj = dom_aa.get(vj)
                if dj and dj in _OSSOS_DEDOS and vert_ilha_tam.get(vj, 0) >= 80 and dist_hier_aa.get(di, {}).get(dj, 99) >= 3:
                    mitten_lados.add(_lado_osso(di))
        if mitten_lados:
            for vi, ws in list(pesos_por_vertice.items()):
                if ws and vert_ilha_tam.get(vi, 0) >= 80 and ws[0][0] in _OSSOS_DEDOS and _lado_osso(ws[0][0]) in mitten_lados:
                    lado_m = _lado_osso(ws[0][0])
                    hand_m = f"Hand.{lado_m}"
                    dedo1 = f"{ws[0][0].rstrip('.LR123')}1.{lado_m}"
                    if hand_m in ossos_por_nome and dedo1 in ossos_por_nome:
                        pesos_por_vertice[vi] = [(hand_m, 0.70), (dedo1, 0.30)]
    for vi, ws in list(pesos_por_vertice.items()):
        if len(ws) > 1:
            pesos_por_vertice[vi] = filtrar_pesos_coerentes(
                [(w, n) for n, w in ws], dist_hier_aa, max_k=MAX_INFLUENCIAS_VERTICE
            )


def _atribuir_pesos_inverso(
    obj,
    ossos: list[dict],
    m: dict,
    indices: list[int] | None = None,
) -> None:
    bracos_baixos = (
        m["braco_L"]["tip"].z < m["shoulder_z"] - 0.12 * m["altura"]
        or m["braco_R"]["tip"].z < m["shoulder_z"] - 0.12 * m["altura"]
    )
    grupos_obj = {}
    for o in ossos:
        if o["nome"] in _RAIZES:
            continue
        vg = obj.vertex_groups.get(o["nome"]) or obj.vertex_groups.new(name=o["nome"])
        grupos_obj[o["nome"]] = vg

    eh_aa = any(o["nome"] in _OSSOS_AA_EXTRAS for o in ossos)
    if eh_aa:
        base_ossos = []
        for o in ossos:
            if o["nome"] in _OSSOS_AA_EXTRAS:
                continue
            if o["nome"] == "Hand.L":
                base_ossos.append(dict(o, cauda=tuple(m["braco_L"]["tip"])))
            elif o["nome"] == "Hand.R":
                base_ossos.append(dict(o, cauda=tuple(m["braco_R"]["tip"])))
            else:
                base_ossos.append(o)
    else:
        base_ossos = ossos

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.index_update()
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        coords = [v.co.copy() for v in bm.verts]
        ilhas = _ilhas_vertices(bm)
        adj = _grafo_superficie(bm)
    finally:
        bm.free()

    n_total = len(coords)
    if n_total == 0:
        return
    coords_xyz = [(v.x, v.y, v.z) for v in coords]

    h = m["altura"]
    tem_neck = any(o["nome"] == "Neck" for o in base_ossos)
    lim_anat = _limites_anatomicos(m, tem_neck=tem_neck)
    tem_ilha_principal = len(ilhas[0]) > 0.40 * n_total
    globais_min: dict[str, float] | None = None
    if len(ilhas) > 1 and not tem_ilha_principal:
        globais_min = {}
        for o in base_ossos:
            nome = o["nome"]
            if nome in _RAIZES:
                continue
            a = Vector(o["cabeca"])
            b = Vector(o["cauda"])
            d_best = float("inf")
            for v in coords:
                if _osso_permitido_semente(nome, v, m, bracos_baixos, tem_neck=tem_neck, lim=lim_anat):
                    d_v = _dist_ponto_segmento(v, a, b)
                    if d_v < d_best:
                        d_best = d_v
            if d_best < float("inf"):
                globais_min[nome] = d_best

    pesos_por_vertice: dict[int, list[tuple[str, float]]] = {}
    ossos_por_nome = {o["nome"]: o for o in base_ossos}
    hands_pos = [
        (hn, Vector(ossos_por_nome[hn]["cabeca"]))
        for hn in ("Hand.L", "Hand.R", "LeftHand", "RightHand")
        if hn in ossos_por_nome
    ]

    for idx_ilha, ilha in enumerate(ilhas):
        xs = [coords_xyz[vi][0] for vi in ilha]
        ys = [coords_xyz[vi][1] for vi in ilha]
        zs = [coords_xyz[vi][2] for vi in ilha]
        diag = Vector((max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))).length

        eh_roupa_bilateral = (
            tem_ilha_principal
            and idx_ilha > 0
            and min(xs) < -0.045 * h
            and max(xs) > 0.045 * h
            and diag >= 0.22 * h
        )
        arma_mao_osso: str | None = None
        if idx_ilha == 0:
            e_acessorio = False
        elif tem_ilha_principal:
            e_acessorio = (not eh_roupa_bilateral) and (
                (len(ilha) < 0.12 * n_total) or (diag < 0.22 * h)
            )
            if not e_acessorio and diag < 0.90 * h and hands_pos:
                unilateral = min(xs) > 0.14 * h or max(xs) < -0.14 * h
                if unilateral:
                    d_hand = min(
                        (hn, min((coords[vi] - hp).length for vi in ilha))
                        for hn, hp in hands_pos
                    )
                    if d_hand[1] < 0.14 * h:
                        e_acessorio = True
                        arma_mao_osso = d_hand[0]
        else:
            e_acessorio = diag < 0.18 * h

        calculados = None if e_acessorio else _pesos_ilha_geodesicos(
            ilha, adj, coords, coords_xyz, base_ossos, m, bracos_baixos, globais_min=globais_min
        )
        if calculados is not None:
            pesos_por_vertice.update(calculados)
        elif eh_roupa_bilateral and ilhas[0]:
            passo_ref = max(1, len(ilhas[0]) // 800)
            amostra_corpo = ilhas[0][::passo_ref]
            for vi in ilha:
                cx, cy_v, cz = coords_xyz[vi]
                melhor_vb = amostra_corpo[0]
                melhor_d2 = float("inf")
                for vb in amostra_corpo:
                    bx, by_v, bz = coords_xyz[vb]
                    d2 = (cx - bx) ** 2 + (cy_v - by_v) ** 2 + (cz - bz) ** 2
                    if d2 < melhor_d2:
                        melhor_d2 = d2
                        melhor_vb = vb
                pesos_por_vertice[vi] = list(
                    pesos_por_vertice.get(melhor_vb, [(base_ossos[0]["nome"], 1.0)])
                )
        else:
            osso_unico = arma_mao_osso or _osso_acessorio_ilha(
                ilha,
                coords,
                coords_xyz,
                base_ossos,
                m,
                bracos_baixos,
                ilhas[0] if tem_ilha_principal and idx_ilha > 0 else None,
                pesos_por_vertice,
            )
            for vi in ilha:
                pesos_por_vertice[vi] = [(osso_unico, 1.0)]

    crotch_z = float(m.get("crotch_z", m["hip_z"]))
    z0_m = float(m.get("z_min", 0.0))
    tem_saia_central = any(
        (z0_m + 0.12 * h < coords_xyz[vi][2] < crotch_z - 0.02 * h)
        and abs(coords_xyz[vi][0]) < 0.022 * h
        for vi in ilhas[0]
    )
    if tem_saia_central:
        banda_costura = [
            vi
            for vi in ilhas[0]
            if (z0_m + 0.08 * h < coords_xyz[vi][2] < crotch_z)
            and abs(coords_xyz[vi][0]) <= 0.042 * h
        ]
        for _ in range(2):
            novos_pesos: dict[int, list[tuple[str, float]]] = {}
            for vi in banda_costura:
                acum: dict[str, float] = {n: w * 0.5 for n, w in pesos_por_vertice.get(vi, ())}
                viz = adj[vi]
                if viz:
                    peso_v = 0.5 / float(len(viz))
                    for vj in viz:
                        for n, w in pesos_por_vertice.get(vj, ()):
                            acum[n] = acum.get(n, 0.0) + w * peso_v
                novos_pesos[vi] = _normalizar_top4([(w, n) for n, w in acum.items()])
            pesos_por_vertice.update(novos_pesos)
        for vi in range(n_total):
            vx = coords_xyz[vi][0]
            if abs(vx) > 0.042 * h:
                lado_opp = "L" if vx > 0.0 else "R"
                filtrados = [
                    (n, min(w, 0.045) if _lado_osso(n) == lado_opp else w)
                    for n, w in pesos_por_vertice.get(vi, ())
                ]
                if filtrados:
                    pesos_por_vertice[vi] = _normalizar_top4([(w, n) for n, w in filtrados])

    def _perm_humano(nome_osso: str, vi_idx: int) -> bool:
        return _osso_permitido(nome_osso, coords[vi_idx], m, bracos_baixos, tem_neck=tem_neck, lim=lim_anat)

    _suavizar_aneis_juntas(
        adj, pesos_por_vertice, base_ossos, permitido_fn=_perm_humano, passos=2, alpha=0.25,
        pares_bloqueados={frozenset(("Chest", "Head")), frozenset(("UpperTorso", "Head")), frozenset(("Chest", "Neck"))},
    )
    _, dist_hier_base, _ = construir_hierarquia_ossos(base_ossos)
    for vi, ws in list(pesos_por_vertice.items()):
        if len(ws) > 1:
            pesos_por_vertice[vi] = filtrar_pesos_coerentes([(w, n) for n, w in ws], dist_hier_base, max_k=MAX_INFLUENCIAS_VERTICE)

    cabelo_slots = {idx for idx, mat in enumerate(obj.data.materials) if mat is not None and str(mat.name).startswith("makehuman_cabelo")}
    if cabelo_slots and "Head" in grupos_obj:
        verts_cabelo = {vi for poly in obj.data.polygons if poly.material_index in cabelo_slots for vi in poly.vertices}
        for vi in verts_cabelo:
            pesos_por_vertice[vi] = [("Head", 1.0)]

    if eh_aa:
        _refinar_pesos_aa_56(obj, ossos, m, coords, coords_xyz, ilhas, pesos_por_vertice, adj=adj)

    alvo = indices if indices is not None else range(n_total)
    for vi in alvo:
        for nome, peso in pesos_por_vertice.get(vi, ()):
            grupos_obj[nome].add([vi], peso, "REPLACE")
