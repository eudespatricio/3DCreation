"""Boost de densidade texel UV para regiao superior/cabeca de personagens eretos (camada L2)."""

from __future__ import annotations

from array import array
import heapq
import math

import bmesh

_UV_GRID = 64


def _area_tri_2d(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float:
    return 0.5 * abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))


def _clip_tri_2d(
    sujeito: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    recorte: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
) -> float:
    """Area de intersecao 2D de dois triangulos via Sutherland-Hodgman."""
    def _ccw(t):
        a, b, c = t
        return (a, c, b) if ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 0.0 else t

    poly = list(_ccw(sujeito))
    clip = _ccw(recorte)
    for k in range(3):
        if not poly:
            return 0.0
        p, q = clip[k], clip[(k + 1) % 3]
        ex, ey = q[0] - p[0], q[1] - p[1]
        saida = []
        s_pt = poly[-1]
        for e_pt in poly:
            in_e = ex * (e_pt[1] - p[1]) - ey * (e_pt[0] - p[0]) >= -1e-11
            in_s = ex * (s_pt[1] - p[1]) - ey * (s_pt[0] - p[0]) >= -1e-11
            if in_e != in_s:
                dx, dy = e_pt[0] - s_pt[0], e_pt[1] - s_pt[1]
                denom = ex * dy - ey * dx
                if abs(denom) > 1e-15:
                    t = (ex * (p[1] - s_pt[1]) - ey * (p[0] - s_pt[0])) / denom
                    saida.append((s_pt[0] + t * dx, s_pt[1] + t * dy))
                else:
                    saida.append(s_pt)
            if in_e:
                saida.append(e_pt)
            s_pt = e_pt
        poly = saida
    n = len(poly)
    if n < 3:
        return 0.0
    return 0.5 * abs(sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n)))


def _tris_uv_sobrepostas(obj, face_indices: set[int] | None = None) -> bool:
    """Detecta auto-sobreposicao de UV0 em OBJECT mode (total ou restrita a ``face_indices``)."""
    if obj is None or getattr(obj, "type", None) != "MESH" or getattr(obj, "data", None) is None:
        return False
    me = obj.data
    if not me.uv_layers or not me.uv_layers.active or not me.polygons:
        return False
    me.calc_loop_triangles()
    uvl = me.uv_layers.active.data
    tris = []
    area_total = 0.0
    for lt in me.loop_triangles:
        if face_indices is not None and lt.polygon_index not in face_indices:
            continue
        a = (float(uvl[lt.loops[0]].uv[0]), float(uvl[lt.loops[0]].uv[1]))
        b = (float(uvl[lt.loops[1]].uv[0]), float(uvl[lt.loops[1]].uv[1]))
        c = (float(uvl[lt.loops[2]].uv[0]), float(uvl[lt.loops[2]].uv[1]))
        ar = _area_tri_2d(a, b, c)
        if ar > 1e-10:
            area_total += ar
            tris.append((a, b, c, ar, min(a[0], b[0], c[0]), min(a[1], b[1], c[1]), max(a[0], b[0], c[0]), max(a[1], b[1], c[1])))
    n = len(tris)
    if n < 2:
        return False
    if face_indices is None:
        limiar_ov = 0.0 if n <= 64 else max(8e-5, 0.0008 * area_total)
    else:
        limiar_ov = 0.0 if n <= 64 else max(1e-6, 0.0002 * area_total)
    area_ov = 0.0
    grade: dict[tuple[int, int], list[int]] = {}
    vistos: set[tuple[int, int]] = set()
    for idx, t in enumerate(tris):
        gx0 = max(0, min(_UV_GRID - 1, int(math.floor(t[4] * _UV_GRID))))
        gx1 = max(0, min(_UV_GRID - 1, int(math.floor(t[6] * _UV_GRID))))
        gy0 = max(0, min(_UV_GRID - 1, int(math.floor(t[5] * _UV_GRID))))
        gy1 = max(0, min(_UV_GRID - 1, int(math.floor(t[7] * _UV_GRID))))
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                cel = grade.setdefault((gx, gy), [])
                for outro in cel:
                    par = (outro, idx)
                    if par in vistos:
                        continue
                    vistos.add(par)
                    o = tris[outro]
                    if max(o[4], t[4]) + 1e-6 >= min(o[6], t[6]) or max(o[5], t[5]) + 1e-6 >= min(o[7], t[7]):
                        continue
                    inter = _clip_tri_2d(o[:3], t[:3])
                    if inter > 1e-8 and inter > 1e-4 * min(o[3], t[3]):
                        area_ov += inter
                        if area_ov > limiar_ov:
                            return True
                cel.append(idx)
    return False


def tem_uv_sobreposta(obj) -> bool:
    """Detecta auto-sobreposicao de UV0 em OBJECT mode (espelha G3 com folga anti-quantizacao)."""
    return _tris_uv_sobrepostas(obj, None)


def _subset_tem_uv_sobreposta(obj, face_indices: set[int]) -> bool:
    """Detecta sobreposicao interna dentro de um subconjunto de faces recem-desdobradas."""
    return _tris_uv_sobrepostas(obj, set(face_indices))


def _ilhas_uv_subset(bm, uv_layer, face_set: set[int] | None = None) -> list[list]:
    """Agrupa faces de ``bm`` (ou ``face_set``) em ilhas UV topologicamente conectadas."""
    f_uv = {
        f.index: {lp.vert.index: lp[uv_layer].uv for lp in f.loops}
        for f in bm.faces
        if face_set is None or f.index in face_set
    }
    visitadas: set[int] = set()
    ilhas: list[list] = []
    for f0 in bm.faces:
        if f0.index not in f_uv or f0.index in visitadas:
            continue
        ilha, pilha = [f0], [f0]
        visitadas.add(f0.index)
        while pilha:
            fc = pilha.pop()
            uv_c = f_uv[fc.index]
            for e in fc.edges:
                v0, v1 = e.verts[0].index, e.verts[1].index
                ua0, ua1 = uv_c.get(v0), uv_c.get(v1)
                if ua0 is None or ua1 is None:
                    continue
                for fn in e.link_faces:
                    if fn.index not in f_uv or fn.index in visitadas:
                        continue
                    uv_n = f_uv[fn.index]
                    ub0, ub1 = uv_n.get(v0), uv_n.get(v1)
                    if ub0 is not None and ub1 is not None and (ua0 - ub0).length < 1e-4 and (ua1 - ub1).length < 1e-4:
                        visitadas.add(fn.index)
                        ilha.append(fn)
                        pilha.append(fn)
        ilhas.append(ilha)
    return ilhas


def _maior_componente_geom(bm, candidate_set: set[int]) -> set[int]:
    """Retorna o maior componente geométrico conexo entre as faces de ``candidate_set``."""
    visitadas: set[int] = set()
    melhor: set[int] = set()
    for f0 in bm.faces:
        if f0.index not in candidate_set or f0.index in visitadas:
            continue
        comp: set[int] = {f0.index}
        pilha = [f0]
        visitadas.add(f0.index)
        while pilha:
            fc = pilha.pop()
            for e in fc.edges:
                for fn in e.link_faces:
                    if fn.index in candidate_set and fn.index not in visitadas:
                        visitadas.add(fn.index)
                        comp.add(fn.index)
                        pilha.append(fn)
        if len(comp) > len(melhor):
            melhor = comp
    return melhor


def _marcar_costura_nuca_dijkstra(bm, target_set: set[int], cx_h: float, cy_h: float, h: float) -> int:
    """Marca costura unica na nuca (-Y) do pescoco ao topo da cabeca via menor caminho."""
    main_set = _maior_componente_geom(bm, target_set)
    comp_faces = [bm.faces[idx] for idx in main_set]
    if not comp_faces:
        return 0
    adj: dict[int, list[tuple[object, object]]] = {}
    neck_verts: list[object] = []
    comp_verts_set: dict[int, object] = {}
    for f in comp_faces:
        for v in f.verts:
            comp_verts_set[v.index] = v
        for e in f.edges:
            in_t = sum(1 for lf in e.link_faces if lf.index in main_set)
            if in_t < len(e.link_faces):
                neck_verts.extend(e.verts)
            elif in_t == 2:
                v0, v1 = e.verts[0], e.verts[1]
                adj.setdefault(v0.index, []).append((e, v1))
                adj.setdefault(v1.index, []).append((e, v0))
    if not comp_verts_set:
        return 0
    z_max_c = max(v.co.z for v in comp_verts_set.values())
    cand_crown = [v for v in comp_verts_set.values() if v.co.z >= z_max_c - 0.03 * h] or list(comp_verts_set.values())
    v_crown = min(cand_crown, key=lambda v: abs(v.co.x - cx_h) + 0.5 * abs(v.co.y - cy_h) - v.co.z)
    neck_back = [v for v in neck_verts if v.co.y <= cy_h]
    pool_neck = neck_back or neck_verts or [v for v in comp_verts_set.values() if v.co.y <= cy_h]
    if not pool_neck:
        return 0
    v_neck = min(pool_neck, key=lambda v: (abs(v.co.x - cx_h) * 3.0 + max(0.0, v.co.y - cy_h) * 2.0 + v.co.z))
    if v_neck.index == v_crown.index:
        return 0

    dist: dict[int, float] = {v_neck.index: 0.0}
    prev: dict[int, tuple[int, object]] = {}
    fila: list[tuple[float, int]] = [(0.0, v_neck.index)]
    y_lim = cy_h + 0.05 * h
    denom_h = max(h, 1e-4)
    while fila:
        d_cur, vi = heapq.heappop(fila)
        if vi == v_crown.index:
            break
        if d_cur > dist.get(vi, 1e18):
            continue
        for e, vn in adj.get(vi, ()):
            mid = 0.5 * (e.verts[0].co + e.verts[1].co)
            pen_frente = 0.0 if mid.y <= y_lim else 50.0 * ((mid.y - y_lim) / denom_h)
            custo = max(e.calc_length(), 1e-6) * (1.0 + 16.0 * abs(mid.x - cx_h) / denom_h + pen_frente)
            nd = d_cur + custo
            if nd < dist.get(vn.index, 1e18):
                dist[vn.index] = nd
                prev[vn.index] = (vi, e)
                heapq.heappush(fila, (nd, vn.index))

    marcadas = 0
    cur_idx = v_crown.index
    while cur_idx in prev:
        p_idx, edge = prev[cur_idx]
        edge.seam = True
        marcadas += 1
        cur_idx = p_idx
    if marcadas == 0:
        for e in bm.edges:
            if len(e.link_faces) == 2 and all(lf.index in main_set for lf in e.link_faces):
                mid = 0.5 * (e.verts[0].co + e.verts[1].co)
                if mid.y < cy_h and (e.verts[0].co.x - cx_h) * (e.verts[1].co.x - cx_h) <= 0.0:
                    e.seam = True
                    marcadas += 1
    return marcadas


def _area_uv_subset_buf(mesh, uv_buf, face_set: set[int]) -> tuple[float, bool]:
    """Calcula a area UV 2D de ``face_set`` a partir de um buffer plano ``array('f')``."""
    mesh.calc_loop_triangles()
    area = 0.0
    for lt in mesh.loop_triangles:
        if lt.polygon_index not in face_set:
            continue
        i0, i1, i2 = lt.loops[0] * 2, lt.loops[1] * 2, lt.loops[2] * 2
        a = (uv_buf[i0], uv_buf[i0 + 1])
        b = (uv_buf[i1], uv_buf[i1 + 1])
        c = (uv_buf[i2], uv_buf[i2 + 1])
        if any(math.isnan(v) or math.isinf(v) for pt in (a, b, c) for v in pt):
            return 0.0, False
        area += _area_tri_2d(a, b, c)
    return area, True


def unificar_ilha_uv_rosto_cabeca(
    obj,
    *,
    margem: float = 0.004,
    z_frac_pescoco: float = 0.835,
    min_poligonos: int = 400,
) -> dict:
    """Desdobra a cabeca/rosto de humanoides em ilha UV continua sem micro-fragmentos."""
    skip = {"aplicado": False, "motivo": "nao_aplicavel"}
    try:
        import bpy
    except ImportError:
        return {**skip, "motivo": "sem_bpy"}

    if obj is None or getattr(obj, "type", None) != "MESH" or getattr(obj, "data", None) is None:
        return skip
    mesh = obj.data
    n_polys = len(mesh.polygons)
    if not mesh.uv_layers or n_polys < min_poligonos or not mesh.vertices:
        return skip

    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    w, d = max(xs) - min(xs), max(ys) - min(ys)
    z_min, h = min(zs), max(zs) - min(zs)
    if h <= 1e-6 or h < 0.80 * max(w, d) or d > 0.72 * h:
        return {**skip, "motivo": "nao_ereto"}

    z_pescoco = z_min + float(z_frac_pescoco) * h
    vs_cab = [v.co for v in mesh.vertices if v.co.z >= z_pescoco]
    if len(vs_cab) < 12:
        return {**skip, "motivo": "poucos_vertices_cabeca"}
    sx_c = sorted(c.x for c in vs_cab)
    sy_c = sorted(c.y for c in vs_cab)
    cx_h, cy_h = sx_c[len(sx_c) // 2], sy_c[len(sy_c) // 2]

    head_set = {
        p.index for p in mesh.polygons
        if p.center.z >= z_pescoco and abs(p.center.x - cx_h) <= 0.22 * h
    }
    if len(head_set) < 12 or len(head_set) >= 0.45 * float(n_polys):
        return {**skip, "motivo": "cabeca_fora_faixa"}

    frontal_cand = {
        idx for idx in head_set
        if mesh.polygons[idx].center.z >= z_min + 0.84 * h
        and abs(mesh.polygons[idx].center.x - cx_h) <= 0.14 * h
        and (mesh.polygons[idx].normal.y > 0.05 or mesh.polygons[idx].center.y >= cy_h)
    }

    uv_act = mesh.uv_layers.active or mesh.uv_layers[0]
    mesh.uv_layers.active = uv_act
    uv0_nome = str(uv_act.name)
    n_loops = len(mesh.loops)
    if n_loops <= 0:
        return skip
    backup_uv = array("f", [0.0] * (n_loops * 2))
    uv_act.data.foreach_get("uv", backup_uv)
    active_ant = bpy.context.view_layer.objects.active
    selecionados_ant = [o for o in bpy.context.view_layer.objects if o.select_get()]

    def _restaurar_uv_backup() -> None:
        me = obj.data
        if uv0_nome in me.uv_layers:
            ul = me.uv_layers[uv0_nome]
            me.uv_layers.active = ul
            ul.data.foreach_set("uv", backup_uv)
            me.update()

    def _tentar_unwrap(target_set: set[int], cortar_nuca: bool) -> dict | None:
        if len(target_set) < 8:
            return None
        _restaurar_uv_backup()
        area_alvo, _ = _area_uv_subset_buf(obj.data, backup_uv, target_set)
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            for e in bm.edges:
                in_t = sum(1 for lf in e.link_faces if lf.index in target_set)
                if 0 < in_t < len(e.link_faces):
                    e.seam = True
                elif in_t == len(e.link_faces) and in_t > 0:
                    e.seam = False
            if cortar_nuca:
                _marcar_costura_nuca_dijkstra(bm, target_set, cx_h, cy_h, h)
            for v in bm.verts:
                v.select_set(False)
            for e in bm.edges:
                e.select_set(False)
            for f in bm.faces:
                f.select_set(False)
            for idx in target_set:
                bm.faces[idx].select_set(True)
            bm.to_mesh(obj.data)
            obj.data.update()
        finally:
            bm.free()

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        me_obj = obj.data
        me_obj.uv_layers.active = me_obj.uv_layers[uv0_nome]
        cur_uv = array("f", [0.0] * (n_loops * 2))
        area_cur, finita, ok_unwrap = 0.0, False, False
        for meth in ("ANGLE_BASED", "CONFORMAL"):
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_mode(type="FACE")
            bpy.ops.uv.unwrap(method=meth, margin=float(margem))
            bpy.ops.object.mode_set(mode="OBJECT")
            me_obj = obj.data
            ul_now = me_obj.uv_layers[uv0_nome]
            me_obj.uv_layers.active = ul_now
            ul_now.data.foreach_get("uv", cur_uv)
            area_cur, finita = _area_uv_subset_buf(me_obj, cur_uv, target_set)
            if finita and area_cur > 1e-8 and not _subset_tem_uv_sobreposta(obj, target_set):
                ok_unwrap = True
                break
        if not ok_unwrap:
            return None
        ul_now = me_obj.uv_layers[uv0_nome]
        if area_alvo > 1e-8:
            loops_sub = {li for pid in target_set for li in me_obj.polygons[pid].loop_indices}
            if loops_sub:
                inv_n = 1.0 / float(len(loops_sub))
                uc = sum(cur_uv[2 * li] for li in loops_sub) * inv_n
                vc = sum(cur_uv[2 * li + 1] for li in loops_sub) * inv_n
                s = math.sqrt(area_alvo / area_cur)
                for li in loops_sub:
                    cur_uv[2 * li] = uc + (cur_uv[2 * li] - uc) * s
                    cur_uv[2 * li + 1] = vc + (cur_uv[2 * li + 1] - vc) * s
                ul_now.data.foreach_set("uv", cur_uv)
                me_obj.update()
        bm_cnt = bmesh.new()
        try:
            bm_cnt.from_mesh(me_obj)
            uv_bm = bm_cnt.loops.layers.uv.active
            ilhas_lista = _ilhas_uv_subset(bm_cnt, uv_bm, target_set) if uv_bm is not None else []
            ilhas = len(ilhas_lista)
            rosto_sub = target_set & frontal_cand if frontal_cand else target_set
            ilha_por_face = {f.index: iid for iid, il in enumerate(ilhas_lista) for f in il}
            ilhas_r = len({ilha_por_face[fid] for fid in rosto_sub if fid in ilha_por_face}) if (ilhas_lista and rosto_sub) else ilhas
        finally:
            bm_cnt.free()
        return {"aplicado": True, "faces_unwrap": len(target_set), "ilhas_sub": ilhas, "ilhas_rosto": ilhas_r}

    try:
        res1 = _tentar_unwrap(head_set, cortar_nuca=True)
        if res1 is not None and res1.get("ilhas_rosto", 99) <= 2:
            return {**res1, "modo": "cabeca_nuca"}

        if len(frontal_cand) >= 8:
            bm_f = bmesh.new()
            try:
                bm_f.from_mesh(obj.data)
                frontal_main = _maior_componente_geom(bm_f, frontal_cand)
            finally:
                bm_f.free()
            res2 = _tentar_unwrap(frontal_main, cortar_nuca=False)
            if res2 is not None:
                return {**res2, "modo": "rosto_frontal"}

        _restaurar_uv_backup()
        return {**skip, "motivo": "rollback_sobreposicao"}
    finally:
        bpy.ops.object.select_all(action="DESELECT")
        for o in selecionados_ant:
            if o.name in bpy.data.objects:
                o.select_set(True)
        if active_ant is not None and active_ant.name in bpy.data.objects:
            bpy.context.view_layer.objects.active = active_ant


def aplicar_prioridade_uv_cabeca(
    obj,
    *,
    fator: float = 1.35,
    z_frac_inicio: float = 0.78,
    min_poligonos: int = 400,
    razao_ereto_min: float = 0.8,
) -> int:
    """Escala UVs de faces com centroide ``z >= z_min + z_frac_inicio * h`` em OBJECT mode.

    Deve ser chamada em ``OBJECT`` mode antes de ``bpy.ops.uv.pack_islands`` para preservar
    seguranca de ponteiros RNA e permitir que o empacotador encaixe tudo em ``[0, 1]^2``
    mantendo ~1.8x de densidade texel relativa na cabeca/rosto.
    """
    if obj is None or getattr(obj, "type", None) != "MESH" or getattr(obj, "data", None) is None:
        return 0
    mesh = obj.data
    if not mesh.uv_layers or len(mesh.polygons) < min_poligonos or not mesh.vertices:
        return 0

    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    w = max(xs) - min(xs)
    d = max(ys) - min(ys)
    z_min = min(zs)
    h = max(zs) - z_min
    if h <= 1e-6 or h < razao_ereto_min * max(w, d):
        return 0

    z_corte = z_min + float(z_frac_inicio) * h
    escala = float(fator)
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            return 0
        total_faces = len(bm.faces)
        if total_faces == 0:
            return 0
        total_escaladas = 0
        for ilha in _ilhas_uv_subset(bm, uv_layer):
            n_cabeca = sum(1 for f in ilha if f.calc_center_median().z >= z_corte)
            if (n_cabeca / float(len(ilha))) >= 0.60 and len(ilha) < 0.45 * float(total_faces):
                loops_ilha = [lp for f in ilha for lp in f.loops]
                if not loops_ilha:
                    continue
                inv_n = 1.0 / float(len(loops_ilha))
                uc = sum(lp[uv_layer].uv.x for lp in loops_ilha) * inv_n
                vc = sum(lp[uv_layer].uv.y for lp in loops_ilha) * inv_n
                for lp in loops_ilha:
                    uv = lp[uv_layer].uv
                    lp[uv_layer].uv = (uc + (uv.x - uc) * escala, vc + (uv.y - vc) * escala)
                total_escaladas += len(ilha)
        if total_escaladas > 0:
            bm.to_mesh(mesh)
            mesh.update()
        return total_escaladas
    finally:
        bm.free()
