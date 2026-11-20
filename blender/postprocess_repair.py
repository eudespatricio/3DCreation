"""Camada L1 de postprocess: reparo de malha, suavizacao bmesh e decimate."""

from __future__ import annotations

import os
import sys

import bmesh
import bpy
from mathutils import Vector

if __package__:
    from .postprocess_scene import _selecionar, malha_triangulada
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from postprocess_scene import _selecionar, malha_triangulada


def _remover_ilhas_de_uma_face(bm, *, permitir_bordas_abertas: bool = False) -> int:
    """Ilha de uma face minuscula (sobra de decimate) vira borda aberta no G1."""
    vistos = set()
    remover = []
    for face in bm.faces:
        if face.index in vistos:
            continue
        pilha = [face]
        componente = []
        vistos.add(face.index)
        while pilha:
            atual = pilha.pop()
            componente.append(atual)
            for aresta in atual.edges:
                for vizinha in aresta.link_faces:
                    if vizinha.index not in vistos:
                        vistos.add(vizinha.index)
                        pilha.append(vizinha)
        if len(componente) == 1 and (
            not permitir_bordas_abertas or componente[0].calc_area() < 1e-6
        ):
            remover.append(componente[0])
    if remover:
        bmesh.ops.delete(bm, geom=remover, context="FACES")
        soltos = [v for v in bm.verts if not v.link_faces]
        if soltos:
            bmesh.ops.delete(bm, geom=soltos, context="VERTS")
    return len(remover)


def _fechar_ciclos_borda_fan(bm) -> int:
    """Fecha ciclos simples de borda nao-planares via leque ao centroide preservando pesos e UV."""
    restantes = [e for e in bm.edges if len(e.link_faces) == 1]
    if not restantes:
        return 0
    dvert_lay = bm.verts.layers.deform.active
    uv_lays = list(bm.loops.layers.uv.values())
    criadas = 0
    visitadas: set = set()
    for e0 in restantes:
        if e0 in visitadas or len(e0.link_faces) != 1:
            continue
        comp_e = []
        fila = [e0]
        visitadas.add(e0)
        adj: dict = {}
        while fila:
            ec = fila.pop()
            comp_e.append(ec)
            for v in ec.verts:
                adj.setdefault(v, []).append(ec)
                for en in v.link_edges:
                    if len(en.link_faces) == 1 and en not in visitadas:
                        visitadas.add(en)
                        fila.append(en)
        if len(comp_e) < 3 or any(len(es) != 2 for es in adj.values()):
            continue
        f_adj = comp_e[0].link_faces[0]
        va, vb = comp_e[0].verts[0], comp_e[0].verts[1]
        for lp in f_adj.loops:
            if lp.edge == comp_e[0]:
                va, vb = lp.link_loop_next.vert, lp.vert
                break
        ciclo = [va, vb]
        usadas = {comp_e[0]}
        while len(ciclo) < len(comp_e):
            atual = ciclo[-1]
            prox_e = next((e for e in adj[atual] if e not in usadas), None)
            if prox_e is None:
                break
            usadas.add(prox_e)
            ciclo.append(prox_e.other_vert(atual))
        if len(ciclo) != len(comp_e):
            continue
        centro = sum((v.co for v in ciclo), Vector((0.0, 0.0, 0.0))) / len(ciclo)
        vc = bm.verts.new(centro)
        if dvert_lay is not None:
            pesos: dict[int, float] = {}
            for v in ciclo:
                for grp, w in v[dvert_lay].items():
                    pesos[grp] = pesos.get(grp, 0.0) + w / len(ciclo)
            tot = sum(pesos.values())
            if tot > 1e-8:
                for grp, w in pesos.items():
                    vc[dvert_lay][grp] = w / tot
        uv_map: dict = {}
        for uvl in uv_lays:
            uv_map[uvl] = {
                v: next((lp[uvl].uv.copy() for lp in v.link_loops), Vector((0.5, 0.5)))
                for v in ciclo
            }
        mat_idx = f_adj.material_index
        for i in range(len(ciclo)):
            v1 = ciclo[i]
            v2 = ciclo[(i + 1) % len(ciclo)]
            try:
                nf = bm.faces.new((v1, v2, vc))
            except ValueError:
                continue
            nf.material_index = mat_idx
            criadas += 1
            for uvl in uv_lays:
                uv1 = uv_map[uvl][v1]
                uv2 = uv_map[uvl][v2]
                uvc = sum(uv_map[uvl].values(), Vector((0.0, 0.0))) / len(ciclo)
                for lp in nf.loops:
                    if lp.vert == v1:
                        lp[uvl].uv = uv1
                    elif lp.vert == v2:
                        lp[uvl].uv = uv2
                    else:
                        lp[uvl].uv = uvc
    return criadas


def _preencher_bordas_e_triangular(bm, *, permitir_bordas_abertas: bool = False) -> int:
    """Fecha bordas abertas (holes_fill + fallback fan), remove ilhas e triangula."""
    bordas = [e for e in bm.edges if len(e.link_faces) == 1]
    if bordas and not permitir_bordas_abertas:
        bmesh.ops.holes_fill(bm, edges=bordas, sides=0)
        if any(len(e.link_faces) == 1 for e in bm.edges):
            _fechar_ciclos_borda_fan(bm)
        _remover_ilhas_de_uma_face(bm, permitir_bordas_abertas=permitir_bordas_abertas)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    return 0 if permitir_bordas_abertas else len(bordas)


def _colapsar_faces_degeneradas(bm, area_min: float = 1e-12) -> int:
    """Colapsa aresta mais curta de faces < area_min sem reabrir buracos na malha."""
    colapsadas = 0
    for _ in range(4):
        degs = [f for f in bm.faces if f.is_valid and f.calc_area() < area_min]
        if not degs:
            break
        arestas_alvo = set()
        for f in degs:
            if not f.is_valid or not f.edges:
                continue
            arestas_alvo.add(min(f.edges, key=lambda e: e.calc_length()))
        arestas_validas = [e for e in arestas_alvo if e.is_valid]
        if not arestas_validas:
            break
        bmesh.ops.collapse(bm, edges=arestas_validas)
        colapsadas += len(arestas_validas)
    return colapsadas


def reparar_malha(obj, permitir_bordas_abertas: bool = False) -> dict:
    """Solda, remove ilha solta e fecha buraco antes do export."""
    antes = (len(obj.data.vertices), len(obj.data.polygons))
    obj.data.validate(verbose=False)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    # 1.8e-5m > sqrt(3)*1e-5m: garante que vertices soldados no grid 1e-5m do QC saiam ja soldados.
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1.8e-5)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
    slivers = [f for f in bm.faces if f.calc_area() < 1e-12]
    if slivers:
        bmesh.ops.delete(bm, geom=slivers, context="FACES")
    soltas_e = [e for e in bm.edges if not e.link_faces]
    if soltas_e:
        bmesh.ops.delete(bm, geom=soltas_e, context="EDGES")
    soltos = [v for v in bm.verts if not v.link_faces]
    if soltos:
        bmesh.ops.delete(bm, geom=soltos, context="VERTS")
    ilhas = _remover_ilhas_de_uma_face(bm, permitir_bordas_abertas=permitir_bordas_abertas)
    bordas_iniciais = _preencher_bordas_e_triangular(
        bm, permitir_bordas_abertas=permitir_bordas_abertas
    )
    for _ in range(3):
        vistos_faces: set[frozenset] = set()
        dups = []
        for f in bm.faces:
            chave = frozenset(f.verts)
            if len(chave) < 3 or chave in vistos_faces:
                dups.append(f)
            else:
                vistos_faces.add(chave)
        if dups:
            bmesh.ops.delete(bm, geom=dups, context="FACES")
        _colapsar_faces_degeneradas(bm, area_min=1e-12)
        excedentes_nm = set()
        for e in bm.edges:
            if len(e.link_faces) > 2:
                ordenadas = sorted(e.link_faces, key=lambda f: f.calc_area(), reverse=True)
                for f in ordenadas[2:]:
                    excedentes_nm.add(f)
        if excedentes_nm:
            bmesh.ops.delete(bm, geom=list(excedentes_nm), context="FACES")
        _remover_ilhas_de_uma_face(bm, permitir_bordas_abertas=permitir_bordas_abertas)
        bordas_pos = _preencher_bordas_e_triangular(
            bm, permitir_bordas_abertas=permitir_bordas_abertas
        )
        if not dups and not excedentes_nm and bordas_pos == 0:
            break
    _colapsar_faces_degeneradas(bm, area_min=1e-12)
    soltas_e_pos = [e for e in bm.edges if not e.link_faces]
    if soltas_e_pos:
        bmesh.ops.delete(bm, geom=soltas_e_pos, context="EDGES")
    soltos_pos = [v for v in bm.verts if not v.link_faces]
    if soltos_pos:
        bmesh.ops.delete(bm, geom=soltos_pos, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return {
        "vertices_antes": antes[0],
        "faces_antes": antes[1],
        "vertices_depois": len(obj.data.vertices),
        "faces_depois": len(obj.data.polygons),
        "ilhas_removidas": ilhas,
        "slivers_removidos": len(slivers),
        "bordas_preenchidas": bordas_iniciais,
    }


def _media_vizinhos(v):
    edges = v.link_edges
    if not edges:
        return v.co.copy()
    soma = Vector((0.0, 0.0, 0.0))
    for e in edges:
        soma += e.other_vert(v).co
    return soma / len(edges)


def _suavizar_taubin_bm(bm, iteracoes: int = 2, fator: float = 0.45) -> int:
    """Suavizacao Taubin sem encolher volume (reduz ondas de Marching Cubes no bmesh)."""
    if not bm.verts or iteracoes <= 0:
        return 0
    for _ in range(iteracoes):
        for peso in (fator, -1.04 * fator):
            deslocs = [(_media_vizinhos(v) - v.co) * peso for v in bm.verts]
            for v, d in zip(bm.verts, deslocs):
                v.co += d
    bm.normal_update()
    return len(bm.verts)


def _relaxar_arestas_dobradas_bm(bm, passadas: int = 3) -> int:
    """Desdobra arestas internas/invertidas apos decimate para zerar rasgos e normais."""
    total_movidos = 0
    for _ in range(passadas):
        bm.normal_update()
        marcados: set[int] = set()
        for e in bm.edges:
            if len(e.link_faces) == 2 and e.link_faces[0].normal.dot(e.link_faces[1].normal) < -0.15:
                marcados.add(e.verts[0].index)
                marcados.add(e.verts[1].index)
        if not marcados:
            break
        bm.verts.ensure_lookup_table()
        novos = {idx: _media_vizinhos(bm.verts[idx]) for idx in marcados}
        for idx, destino in novos.items():
            v = bm.verts[idx]
            v.co = v.co.lerp(destino, 0.55)
        total_movidos += len(marcados)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    return total_movidos


def decimar(
    obj,
    alvo_tris: int,
    proteger_cabeca_maos: bool = False,
    *,
    taubin_fn=None,
) -> int:
    _ = taubin_fn
    tris = malha_triangulada(obj)
    if alvo_tris <= 0 or tris <= alvo_tris:
        return tris

    vg_name: str | None = None
    if proteger_cabeca_maos and obj.data.vertices:
        mw = obj.matrix_world
        coords = [mw @ v.co for v in obj.data.vertices]
        z_min = min(c.z for c in coords)
        z_max = max(c.z for c in coords)
        h = z_max - z_min
        if h > 0.0:
            cx = 0.5 * (min(c.x for c in coords) + max(c.x for c in coords))
            vg_name = "forge3d_decimate_peso"
            vg_temp = obj.vertex_groups.new(name=vg_name)
            cabeca_verts: list[int] = []
            maos_verts: list[int] = []
            resto_verts: list[int] = []
            z_cabeca = z_min + 0.76 * h
            z_mao_min = z_min + 0.30 * h
            z_mao_max = z_min + 0.70 * h
            x_mao = 0.25 * h
            for v, co in zip(obj.data.vertices, coords):
                if co.z >= z_cabeca:
                    cabeca_verts.append(v.index)
                elif z_mao_min <= co.z <= z_mao_max and abs(co.x - cx) >= x_mao:
                    maos_verts.append(v.index)
                else:
                    resto_verts.append(v.index)
            if cabeca_verts:
                vg_temp.add(cabeca_verts, 0.15, "REPLACE")
            if maos_verts:
                vg_temp.add(maos_verts, 0.40, "REPLACE")
            if resto_verts:
                vg_temp.add(resto_verts, 1.0, "REPLACE")

    try:
        mod = obj.modifiers.new("forge3d_decimate", "DECIMATE")
        mod.ratio = max(0.01, min(1.0, (alvo_tris * 0.995) / tris))
        if vg_name is not None:
            mod.vertex_group = vg_name
            mod.invert_vertex_group = False
            if hasattr(mod, "vertex_group_factor"):
                mod.vertex_group_factor = 0.80
        _selecionar(obj)
        if len(obj.modifiers) > 1:
            bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
        bpy.ops.object.modifier_apply(modifier=mod.name)
    finally:
        if vg_name is not None:
            vg_ref = obj.vertex_groups.get(vg_name)
            if vg_ref is not None:
                obj.vertex_groups.remove(vg_ref)

    tris_pos = malha_triangulada(obj)
    for passo_fb in range(2):
        if tris_pos <= alvo_tris or tris_pos <= 4:
            break
        mod_fb = obj.modifiers.new(f"forge3d_decimate_fb_{passo_fb}", "DECIMATE")
        mod_fb.ratio = max(0.01, min(0.99, (alvo_tris * 0.985) / tris_pos))
        _selecionar(obj)
        if len(obj.modifiers) > 1:
            bpy.ops.object.modifier_move_to_index(modifier=mod_fb.name, index=0)
        bpy.ops.object.modifier_apply(modifier=mod_fb.name)
        novo_tris = malha_triangulada(obj)
        if novo_tris >= tris_pos:
            break
        tris_pos = novo_tris

    if proteger_cabeca_maos and obj.data.vertices:
        bm_pos = bmesh.new()
        bm_pos.from_mesh(obj.data)
        _relaxar_arestas_dobradas_bm(bm_pos, passadas=3)
        bm_pos.to_mesh(obj.data)
        bm_pos.free()
        obj.data.update()
    return tris_pos
