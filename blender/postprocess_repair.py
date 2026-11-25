"""Camada L1 de postprocess: reparo de malha, suavizacao bmesh e decimate."""

from __future__ import annotations

import math
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


def _limpar_soltos_bm(bm) -> None:
    if (se := [e for e in bm.edges if not e.link_faces]):
        bmesh.ops.delete(bm, geom=se, context="EDGES")
    if (sv := [v for v in bm.verts if not v.link_faces]):
        bmesh.ops.delete(bm, geom=sv, context="VERTS")


def _componentes_faces_bm(bm) -> list[list]:
    bm.faces.ensure_lookup_table()
    vistos: set[int] = set()
    comps: list[list] = []
    for face in bm.faces:
        if face.index in vistos:
            continue
        comp, pilha = [], [face]
        vistos.add(face.index)
        while pilha:
            atual = pilha.pop()
            comp.append(atual)
            for aresta in atual.edges:
                for vizinha in aresta.link_faces:
                    if vizinha.index not in vistos:
                        vistos.add(vizinha.index)
                        pilha.append(vizinha)
        comps.append(comp)
    return comps


def _remover_ilhas_de_uma_face(bm, *, permitir_bordas_abertas: bool = False) -> int:
    """Ilha de uma face minuscula (sobra de decimate) vira borda aberta no G1."""
    remover = [
        c[0]
        for c in _componentes_faces_bm(bm)
        if len(c) == 1 and (not permitir_bordas_abertas or c[0].calc_area() < 1e-6)
    ]
    if remover:
        bmesh.ops.delete(bm, geom=remover, context="FACES")
        _limpar_soltos_bm(bm)
    return len(remover)


def _fechar_ciclos_borda_fan(bm) -> int:
    """Fecha ciclos simples de borda nao-planares via leque ao centroide preservando pesos e UV."""
    restantes = [e for e in bm.edges if len(e.link_faces) == 1]
    if not restantes:
        return 0
    dvert_lay = bm.verts.layers.deform.active
    uv_lays = list(bm.loops.layers.uv.values())
    criadas, visitadas = 0, set()
    for e0 in restantes:
        if e0 in visitadas or len(e0.link_faces) != 1:
            continue
        comp_e, fila, adj = [], [e0], {}
        visitadas.add(e0)
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
        va, vb = next(
            ((lp.link_loop_next.vert, lp.vert) for lp in f_adj.loops if lp.edge == comp_e[0]),
            (comp_e[0].verts[0], comp_e[0].verts[1]),
        )
        ciclo, usadas = [va, vb], {comp_e[0]}
        while len(ciclo) < len(comp_e):
            prox_e = next((e for e in adj[ciclo[-1]] if e not in usadas), None)
            if prox_e is None:
                break
            usadas.add(prox_e)
            ciclo.append(prox_e.other_vert(ciclo[-1]))
        if len(ciclo) != len(comp_e):
            continue
        vc = bm.verts.new(sum((v.co for v in ciclo), Vector((0.0, 0.0, 0.0))) / len(ciclo))
        if dvert_lay is not None:
            pesos: dict[int, float] = {}
            for v in ciclo:
                for grp, w in v[dvert_lay].items():
                    pesos[grp] = pesos.get(grp, 0.0) + w / len(ciclo)
            tot = sum(pesos.values())
            if tot > 1e-8:
                for grp, w in pesos.items():
                    vc[dvert_lay][grp] = w / tot
        uv_map = {
            uvl: {v: next((lp[uvl].uv.copy() for lp in v.link_loops), Vector((0.5, 0.5))) for v in ciclo}
            for uvl in uv_lays
        }
        for i in range(len(ciclo)):
            v1, v2 = ciclo[i], ciclo[(i + 1) % len(ciclo)]
            try:
                nf = bm.faces.new((v1, v2, vc))
            except ValueError:
                continue
            nf.material_index = f_adj.material_index
            criadas += 1
            for uvl in uv_lays:
                uvc = sum(uv_map[uvl].values(), Vector((0.0, 0.0))) / len(ciclo)
                for lp in nf.loops:
                    lp[uvl].uv = uv_map[uvl].get(lp.vert, uvc)
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
        arestas_validas = [
            e for e in {min(f.edges, key=lambda ed: ed.calc_length()) for f in degs if f.is_valid and f.edges}
            if e.is_valid
        ]
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
    _limpar_soltos_bm(bm)
    ilhas = _remover_ilhas_de_uma_face(bm, permitir_bordas_abertas=permitir_bordas_abertas)
    bordas_iniciais = _preencher_bordas_e_triangular(bm, permitir_bordas_abertas=permitir_bordas_abertas)
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
        bm.normal_update()
        centro = sum((v.co for v in bm.verts), Vector((0.0, 0.0, 0.0))) / float(len(bm.verts)) if bm.verts else Vector((0.0, 0.0, 0.0))
        excedentes_nm: set = set()
        for e in bm.edges:
            if len(e.link_faces) > 2:
                ordenadas = sorted(e.link_faces, key=lambda f: (f.normal.dot(f.calc_center_median() - centro) >= 0.0, f.calc_area()))
                excedentes_nm.update(ordenadas[: len(ordenadas) - 2])
        if excedentes_nm:
            bmesh.ops.delete(bm, geom=list(excedentes_nm), context="FACES")
        _remover_ilhas_de_uma_face(bm, permitir_bordas_abertas=permitir_bordas_abertas)
        bordas_pos = _preencher_bordas_e_triangular(bm, permitir_bordas_abertas=permitir_bordas_abertas)
        if not dups and not excedentes_nm and bordas_pos == 0:
            break
    _colapsar_faces_degeneradas(bm, area_min=1e-12)
    _limpar_soltos_bm(bm)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return {
        "vertices_antes": antes[0], "faces_antes": antes[1],
        "vertices_depois": len(obj.data.vertices), "faces_depois": len(obj.data.polygons),
        "ilhas_removidas": ilhas, "slivers_removidos": len(slivers), "bordas_preenchidas": bordas_iniciais,
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
        marcados = {
            v.index for e in bm.edges
            if len(e.link_faces) == 2 and e.link_faces[0].normal.dot(e.link_faces[1].normal) < -0.15
            for v in e.verts
        }
        if not marcados:
            break
        bm.verts.ensure_lookup_table()
        for idx, destino in {idx: _media_vizinhos(bm.verts[idx]) for idx in marcados}.items():
            bm.verts[idx].co = bm.verts[idx].co.lerp(destino, 0.55)
        total_movidos += len(marcados)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    return total_movidos


def _contar_nao_manifold(obj, weld_dist: float = 0.0) -> tuple[int, int]:
    """Retorna ``(nm_edges, nm_verts)`` em bmesh temporario (com solda opcional)."""
    if obj is None or getattr(obj, "type", None) != "MESH" or getattr(obj, "data", None) is None:
        return 0, 0
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        if weld_dist > 0.0 and bm.verts:
            bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=weld_dist)
        nm_e = sum(1 for e in bm.edges if not e.is_manifold)
        nm_v = sum(1 for v in bm.verts if not v.is_manifold)
        return nm_e, nm_v
    finally:
        bm.free()


def _aplicar_mod(obj, mod) -> None:
    _selecionar(obj)
    if len(obj.modifiers) > 1:
        bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def _extensoes_mesh(mesh) -> tuple[float, float, float]:
    if not mesh or not mesh.vertices:
        return (0.0, 0.0, 0.0)
    coords = [v.co for v in mesh.vertices]
    return tuple(max(c[i] for c in coords) - min(c[i] for c in coords) for i in range(3))  # type: ignore[return-value]


def _rodar_tentativa_voxel(obj, sw_ref, voxel_size: float) -> None:
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-6)
        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()

    mod_sol = obj.modifiers.new("forge3d_voxel_solidify", "SOLIDIFY")
    mod_sol.thickness, mod_sol.offset = voxel_size * 1.8, 0.0
    _aplicar_mod(obj, mod_sol)

    mod = obj.modifiers.new("forge3d_voxel_remesh", "REMESH")
    mod.mode, mod.voxel_size = "VOXEL", voxel_size
    if hasattr(mod, "use_smooth_shade"):
        mod.use_smooth_shade = True
    _aplicar_mod(obj, mod)

    mod_sw = obj.modifiers.new("forge3d_voxel_shrinkwrap", "SHRINKWRAP")
    mod_sw.target, mod_sw.wrap_method = sw_ref, "NEAREST_SURFACEPOINT"
    mod_sw.offset = min(0.001, voxel_size * 0.2)
    _aplicar_mod(obj, mod_sw)

    bm_p = bmesh.new()
    try:
        bm_p.from_mesh(obj.data)
        bm_p.faces.ensure_lookup_table()
        total_faces = len(bm_p.faces)
        if total_faces > 0:
            comps = _componentes_faces_bm(bm_p)
            lixo = [f for c in comps if len(c) < 0.005 * float(total_faces) for f in c]
            if lixo and len(lixo) < total_faces:
                bmesh.ops.delete(bm_p, geom=lixo, context="FACES")
                _limpar_soltos_bm(bm_p)
            bmesh.ops.recalc_face_normals(bm_p, faces=list(bm_p.faces))
            bm_p.to_mesh(obj.data)
            obj.data.update()
    finally:
        bm_p.free()


def _trocar_mesh_seguro(obj, nova_mesh) -> None:
    antiga = obj.data
    obj.data = nova_mesh
    if antiga is not nova_mesh and antiga.users == 0:
        bpy.data.meshes.remove(antiga)


def _remesh_voxel_preservando_partes(
    obj, *, eh_organico: bool = True, max_encolhimento_h: float = 0.10
) -> bool:
    """Limpa nao-manifold via Solidify+Voxel+Shrinkwrap preservando partes e guardando encolhimento."""
    if not eh_organico or not (
        obj and getattr(obj, "type", None) == "MESH" and obj.data and obj.data.vertices and obj.data.polygons
    ):
        return False
    backup_mesh = obj.data.copy()
    orig_exts = _extensoes_mesh(backup_mesh)
    diag = math.sqrt(sum(e * e for e in orig_exts))
    voxel_base = max(0.004, min(0.008, diag * 0.0045))
    sw_ref = bpy.data.objects.new("forge3d_voxel_sw_ref", backup_mesh)
    sw_ref.matrix_world = obj.matrix_world.copy()
    bpy.context.collection.objects.link(sw_ref)
    sucesso = False
    try:
        for idx, vs in enumerate((voxel_base, voxel_base * 0.6)):
            if idx > 0:
                _trocar_mesh_seguro(obj, backup_mesh.copy())
            _rodar_tentativa_voxel(obj, sw_ref, vs)
            cur_exts = _extensoes_mesh(obj.data)
            encolheu = (not obj.data.polygons) or any(
                cur < (1.0 - max_encolhimento_h) * orig for cur, orig in zip(cur_exts, orig_exts) if orig > 1e-4
            )
            if not encolheu:
                sucesso = True
                break
        if not sucesso:
            _trocar_mesh_seguro(obj, backup_mesh)
            return False
    finally:
        bpy.data.objects.remove(sw_ref, do_unlink=True)
        if not sucesso and obj.data is not backup_mesh:
            _trocar_mesh_seguro(obj, backup_mesh)
        elif sucesso and backup_mesh.users == 0:
            bpy.data.meshes.remove(backup_mesh)

    if eh_organico and obj.data.polygons:
        mod_cs = obj.modifiers.new("forge3d_voxel_csmooth", "CORRECTIVE_SMOOTH")
        mod_cs.factor, mod_cs.iterations = 0.25, 2
        _aplicar_mod(obj, mod_cs)
    return True


def _criar_vg_protecao(obj) -> str | None:
    if not obj.data.vertices:
        return None
    mw = obj.matrix_world
    coords = [mw @ v.co for v in obj.data.vertices]
    z_min = min(c.z for c in coords)
    h = max(c.z for c in coords) - z_min
    if h <= 0.0:
        return None
    cx = 0.5 * (min(c.x for c in coords) + max(c.x for c in coords))
    vg_name = "forge3d_decimate_peso"
    vg_temp = obj.vertex_groups.new(name=vg_name)
    cabeca, pes, maos, resto = [], [], [], []
    z_cabeca, z_pes = z_min + 0.76 * h, z_min + 0.14 * h
    z_mao_min, z_mao_max, x_mao = z_min + 0.30 * h, z_min + 0.70 * h, 0.25 * h
    for v, co in zip(obj.data.vertices, coords):
        if co.z >= z_cabeca:
            cabeca.append(v.index)
        elif co.z <= z_pes:
            pes.append(v.index)
        elif z_mao_min <= co.z <= z_mao_max and abs(co.x - cx) >= x_mao:
            maos.append(v.index)
        else:
            resto.append(v.index)
    for grupo, peso in ((cabeca, 0.45), (pes, 0.55), (maos, 0.60), (resto, 1.0)):
        if grupo:
            vg_temp.add(grupo, peso, "REPLACE")
    return vg_name


def _marcar_arestas_sharp(obj, angulo_graus: float) -> None:
    if obj is None or getattr(obj, "data", None) is None:
        return
    _selecionar(obj)
    if getattr(obj, "mode", "OBJECT") != "OBJECT" and hasattr(bpy.ops.object, "mode_set"):
        bpy.ops.object.mode_set(mode="OBJECT")
    if hasattr(obj.data, "set_sharp_from_angle"):
        obj.data.set_sharp_from_angle(angle=math.radians(float(angulo_graus)))
        obj.data.update()


def _aplicar_decimate_passo(
    obj, ratio: float, vg_name: str | None = None, vg_factor: float = 0.30, *, preservar_arestas: bool = False
) -> None:
    mod = obj.modifiers.new("forge3d_decimate", "DECIMATE")
    mod.ratio = max(0.01, min(1.0, float(ratio)))
    if preservar_arestas and hasattr(mod, "delimit"):
        mod.delimit = {"SHARP", "SEAM"}
    if vg_name is not None:
        mod.vertex_group, mod.invert_vertex_group = vg_name, False
        if hasattr(mod, "vertex_group_factor"):
            mod.vertex_group_factor = vg_factor
    _aplicar_mod(obj, mod)


def _decimar_progressivo(
    obj, alvo_tris: int, proteger_cabeca_maos: bool, *, preservar_arestas: bool = False
) -> int:
    for _passo in range(10):
        cur = malha_triangulada(obj)
        if cur <= alvo_tris or cur <= 4:
            break
        if (alvo_tris / float(cur)) < 0.35:
            ratio, vg_name = max(0.45, (alvo_tris * 0.985) / float(cur)), None
        else:
            ratio = (alvo_tris * 0.985) / float(cur)
            vg_name = _criar_vg_protecao(obj) if (proteger_cabeca_maos and cur <= alvo_tris * 2.5) else None
        try:
            _aplicar_decimate_passo(obj, ratio, vg_name=vg_name, vg_factor=0.30, preservar_arestas=preservar_arestas)
        finally:
            if vg_name is not None and (vg_ref := obj.vertex_groups.get(vg_name)) is not None:
                obj.vertex_groups.remove(vg_ref)
        if malha_triangulada(obj) >= cur:
            break

    tris_pos = malha_triangulada(obj)
    for _passo_fb in range(3):
        if tris_pos <= alvo_tris or tris_pos <= 4:
            break
        _aplicar_decimate_passo(obj, (alvo_tris * 0.985) / float(tris_pos), preservar_arestas=preservar_arestas)
        novo_tris = malha_triangulada(obj)
        if novo_tris >= tris_pos:
            break
        tris_pos = novo_tris
    return tris_pos


def decimar(
    obj, alvo_tris: int, proteger_cabeca_maos: bool = False, *,
    taubin_fn=None, eh_organico: bool | None = None, angulo_sharp_graus: float = 38.0,
) -> int:
    _ = taubin_fn
    tris = malha_triangulada(obj)
    if alvo_tris <= 0 or tris <= alvo_tris:
        return tris
    organico = bool(proteger_cabeca_maos) if eh_organico is None else bool(eh_organico)
    if not organico:
        _marcar_arestas_sharp(obj, angulo_sharp_graus)
        _decimar_progressivo(obj, alvo_tris, False, preservar_arestas=True)
        return malha_triangulada(obj)

    voxel_tentado = False
    if tris > max(alvo_tris * 2, 40_000) and _contar_nao_manifold(obj, weld_dist=1e-6)[0] >= 20:
        voxel_tentado = True
        _remesh_voxel_preservando_partes(obj)

    tris_pos = _decimar_progressivo(obj, alvo_tris, proteger_cabeca_maos)
    if proteger_cabeca_maos and not voxel_tentado:
        if (tris_pos > alvo_tris or _contar_nao_manifold(obj)[0] >= 20) and _remesh_voxel_preservando_partes(obj):
            _decimar_progressivo(obj, alvo_tris, proteger_cabeca_maos)

    if proteger_cabeca_maos and obj.data.vertices:
        bm_pos = bmesh.new()
        bm_pos.from_mesh(obj.data)
        _relaxar_arestas_dobradas_bm(bm_pos, passadas=4)
        bm_pos.to_mesh(obj.data)
        bm_pos.free()
        obj.data.update()
    return malha_triangulada(obj)
