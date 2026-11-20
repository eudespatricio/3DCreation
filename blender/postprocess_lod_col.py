"""Camada L1 de postprocess: LOD, colisores UCX e exportacao glTF/GLB."""

from __future__ import annotations

import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

if __package__:
    from .postprocess_scene import FACES_CUBO, bbox_local, objetos_colisao_ucx
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from postprocess_scene import FACES_CUBO, bbox_local, objetos_colisao_ucx


def clonar_malha(obj, nome: str):
    novo = bpy.data.objects.new(nome, obj.data.copy())
    bpy.context.collection.objects.link(novo)
    for vg in obj.vertex_groups:
        novo.vertex_groups.new(name=vg.name)
    return novo


def aplicar_decimate(obj, proporcao: float) -> None:
    if proporcao >= 1.0:
        return
    mod = obj.modifiers.new("decimate_lod", "DECIMATE")
    mod.ratio = max(0.01, min(1.0, proporcao))
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


def _componentes_indices(bm) -> list[list[int]]:
    """Componentes conexas por aresta, como indices de vertice."""
    vistos: set[int] = set()
    grupos: list[list[int]] = []
    for vertice in bm.verts:
        if vertice.index in vistos:
            continue
        pilha = [vertice]
        membros: list[int] = []
        vistos.add(vertice.index)
        while pilha:
            atual = pilha.pop()
            membros.append(atual.index)
            for aresta in atual.link_edges:
                outro = aresta.other_vert(atual)
                if outro.index not in vistos:
                    vistos.add(outro.index)
                    pilha.append(outro)
        grupos.append(membros)
    return grupos


def _volume_componente(bm, indices: list[int]) -> float:
    xs = [bm.verts[i].co.x for i in indices]
    ys = [bm.verts[i].co.y for i in indices]
    zs = [bm.verts[i].co.z for i in indices]
    return (max(xs) - min(xs)) * (max(ys) - min(ys)) * (max(zs) - min(zs))


def aplicar_lod(obj, pct: float, *, blocky: bool | None = None) -> dict:
    """LOD: blocky (muitas caixas) perde caixa inteira; malha organica/importada vai de decimate."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    grupos = _componentes_indices(bm)
    total_tris = len(bm.faces)
    usar_decimate = (
        len(grupos) < 8
        or blocky is False
        or (blocky is None and total_tris > 1500)
    )
    if usar_decimate:
        bm.free()
        aplicar_decimate(obj, pct / 100.0)
        return {"modo": "decimate", "ilhas": len(grupos)}

    por_vertice = {}
    medidas = []
    for indice, membros in enumerate(grupos):
        for v in membros:
            por_vertice[v] = indice
        coords = [bm.verts[i].co for i in membros]
        minimo = [min(c[k] for c in coords) for k in range(3)]
        maximo = [max(c[k] for c in coords) for k in range(3)]
        medidas.append(
            {
                "indice": indice,
                "volume": _volume_componente(bm, membros),
                "area": max(
                    (maximo[0] - minimo[0]) * (maximo[1] - minimo[1]),
                    (maximo[2] - minimo[2]) * (maximo[1] - minimo[1]),
                    (maximo[0] - minimo[0]) * (maximo[2] - minimo[2]),
                ),
                "tris": 0,
                "min": minimo,
                "max": maximo,
            }
        )
    for face in bm.faces:
        dono = por_vertice.get(face.verts[0].index)
        if dono is not None:
            medidas[dono]["tris"] += 1

    global_min = [min(m["min"][k] for m in medidas) for k in range(3)]
    global_max = [max(m["max"][k] for m in medidas) for k in range(3)]

    def toca_extremo(m: dict) -> bool:
        for k in range(3):
            if abs(m["min"][k] - global_min[k]) < 1e-6 or abs(m["max"][k] - global_max[k]) < 1e-6:
                return True
        return False

    obrigatorias = [m for m in medidas if toca_extremo(m)]
    opcionais = sorted(
        (m for m in medidas if not toca_extremo(m)), key=lambda m: m["area"], reverse=True
    )
    alvo = max(1, int(round(total_tris * pct / 100.0)))
    mantidas = list(obrigatorias)
    acumulado = sum(m["tris"] for m in mantidas)
    for medida in opcionais:
        if acumulado >= alvo:
            break
        mantidas.append(medida)
        acumulado += medida["tris"]
    remover_indices = {m["indice"] for m in medidas} - {m["indice"] for m in mantidas}
    remover = [bm.verts[i] for g in remover_indices for i in grupos[g]] if remover_indices else []
    if remover_indices:
        bmesh.ops.delete(bm, geom=remover, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return {
        "modo": "ilhas",
        "ilhas": len(grupos),
        "mantidas": len(mantidas),
        "obrigatorias": len(obrigatorias),
        "alvo_pct": pct,
        "triangulos": len(obj.data.polygons),
    }


def _ilhas(bm) -> list:
    vistos = set()
    ilhas = []
    for vertice in bm.verts:
        if vertice.index in vistos:
            continue
        pilha = [vertice]
        membros = []
        vistos.add(vertice.index)
        while pilha:
            atual = pilha.pop()
            membros.append(atual)
            for aresta in atual.link_edges:
                outro = aresta.other_vert(atual)
                if outro.index not in vistos:
                    vistos.add(outro.index)
                    pilha.append(outro)
        ilha = bmesh.new()
        mapa = {}
        for v in membros:
            mapa[v.index] = ilha.verts.new(v.co)
        ilha.verts.ensure_lookup_table()
        for v in membros:
            for f in v.link_faces:
                try:
                    ilha.faces.new([mapa[x.index] for x in f.verts])
                except ValueError:
                    pass
        ilhas.append(ilha)
    return ilhas


def criar_colisor(obj, modo: str, nome_base: str, max_partes: int) -> list:
    """Colisor convexo por peca; prefixo UCX_ (convencao do perfil)."""
    if modo in ("none", None):
        return []
    if modo == "ucx":
        existentes = sorted(objetos_colisao_ucx(), key=lambda o: o.name)
        if existentes:
            preservados = []
            for col in existentes[:max_partes]:
                bm_col = bmesh.new()
                bm_col.from_mesh(col.data)
                if bm_col.faces:
                    bmesh.ops.recalc_face_normals(bm_col, faces=list(bm_col.faces))
                    bm_col.to_mesh(col.data)
                    col.data.update()
                bm_col.free()
                preservados.append(col)
            return preservados
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    resultados = []

    if modo == "box":
        minimo, maximo = bbox_local()
        malha = bpy.data.meshes.new(f"{nome_base}_box")
        v = [
            (minimo.x, minimo.y, minimo.z),
            (maximo.x, minimo.y, minimo.z),
            (maximo.x, maximo.y, minimo.z),
            (minimo.x, maximo.y, minimo.z),
            (minimo.x, minimo.y, maximo.z),
            (maximo.x, minimo.y, maximo.z),
            (maximo.x, maximo.y, maximo.z),
            (minimo.x, maximo.y, maximo.z),
        ]
        malha.from_pydata(v, [], list(FACES_CUBO))
        malha.update()
        col = bpy.data.objects.new(f"UCX_{nome_base}_00", malha)
        bpy.context.collection.objects.link(col)
        resultados.append(col)
    else:
        ilhas = _ilhas(bm)
        if modo == "convex" or len(ilhas) > max_partes:
            ilhas = [bm]
        for indice, ilha in enumerate(ilhas[:max_partes]):
            temp = bmesh.new()
            temp.from_mesh(obj.data) if ilha is bm else None
            if ilha is not bm:
                for vertice in ilha.verts:
                    temp.verts.new(vertice.co)
                temp.verts.ensure_lookup_table()
            nuvem = bmesh.new()
            for vertice in temp.verts:
                nuvem.verts.new(vertice.co)
            nuvem.verts.ensure_lookup_table()
            if nuvem.verts:
                xs_n = [vv.co.x for vv in nuvem.verts]
                ys_n = [vv.co.y for vv in nuvem.verts]
                zs_n = [vv.co.z for vv in nuvem.verts]
                dx_n = max(xs_n) - min(xs_n)
                dy_n = max(ys_n) - min(ys_n)
                dz_n = max(zs_n) - min(zs_n)
                diag_n = math.sqrt(dx_n * dx_n + dy_n * dy_n + dz_n * dz_n)
                esp_min = max(0.01, diag_n * 0.02)
                pts_orig = [vv.co.copy() for vv in nuvem.verts]
                for idx_ax, span_ax in enumerate((dx_n, dy_n, dz_n)):
                    if span_ax < 1e-4:
                        off = Vector((0.0, 0.0, 0.0))
                        off[idx_ax] = esp_min * 0.5
                        for p0 in pts_orig:
                            nuvem.verts.new(p0 + off)
                            nuvem.verts.new(p0 - off)
                nuvem.verts.ensure_lookup_table()
                dist_solda = (
                    max(0.015, min(0.06, diag_n * 0.025))
                    if len(nuvem.verts) > 64
                    else max(0.002, min(0.008, diag_n * 0.0025))
                )
                if len(nuvem.verts) > 16:
                    bmesh.ops.remove_doubles(nuvem, verts=list(nuvem.verts), dist=dist_solda)
                    nuvem.verts.ensure_lookup_table()
            hull = bmesh.ops.convex_hull(nuvem, input=list(nuvem.verts))
            faces_hull = [g for g in hull["geom"] if isinstance(g, bmesh.types.BMFace)]
            limpo = bmesh.new()
            mapa_vert = {}
            for face in faces_hull:
                for vertice in face.verts:
                    if vertice not in mapa_vert:
                        mapa_vert[vertice] = limpo.verts.new(vertice.co)
            limpo.verts.ensure_lookup_table()
            for face in faces_hull:
                try:
                    limpo.faces.new([mapa_vert[v] for v in face.verts])
                except ValueError:
                    continue
            if limpo.faces:
                bmesh.ops.dissolve_degenerate(limpo, dist=1e-3, edges=list(limpo.edges))
                bmesh.ops.triangulate(limpo, faces=list(limpo.faces))
                bmesh.ops.dissolve_degenerate(limpo, dist=1e-3, edges=list(limpo.edges))
            limpo.normal_update()
            if limpo.faces:
                bmesh.ops.recalc_face_normals(limpo, faces=list(limpo.faces))
            malha = bpy.data.meshes.new(f"UCX_{nome_base}_{indice:02d}")
            limpo.to_mesh(malha)
            limpo.free()
            nuvem.free()
            temp.free()
            malha.update()
            col = bpy.data.objects.new(f"UCX_{nome_base}_{indice:02d}", malha)
            bpy.context.collection.objects.link(col)
            resultados.append(col)

    bm.free()
    return resultados


def _tem_normal_map(
    objetos: list,
    *,
    sidecar_dir: str | None = None,
    nome_base: str | None = None,
    texturas_geradas: list[dict] | None = None,
) -> bool:
    if texturas_geradas and any(str(t.get("papel") or "") == "normal" for t in texturas_geradas):
        return True
    if sidecar_dir and nome_base and os.path.isfile(os.path.join(sidecar_dir, f"{nome_base}_normal.png")):
        return True
    for obj in objetos:
        if getattr(obj, "type", None) != "MESH" or not obj.data:
            continue
        for mat in obj.data.materials:
            if mat and mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == "BSDF_PRINCIPLED":
                        inp = node.inputs.get("Normal")
                        if inp is not None and inp.is_linked:
                            return True
    return False


def exportar(
    caminho: str,
    objetos: list,
    com_rig: bool,
    com_animacao: bool = False,
    export_tangents: bool = False,
    export_image_format: str = "AUTO",
) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objetos:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objetos[0]

    kwargs: dict = {
        "filepath": caminho,
        "export_format": "GLB",
        "use_selection": True,
        "export_apply": False,
        "export_yup": True,
        "export_materials": "EXPORT",
        "export_skins": com_rig,
        "export_animations": com_animacao,
        "export_animation_mode": "ACTIONS",
        "export_rest_position_armature": True,
        "export_texcoords": True,
        "export_normals": True,
        "export_draco_mesh_compression_enable": False,
        "export_image_format": export_image_format,
        "export_cameras": False,
        "export_lights": False,
    }
    if export_tangents:
        kwargs["export_tangents"] = True
    props = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    kwargs = {k: v for k, v in kwargs.items() if k in props}
    bpy.ops.export_scene.gltf(**kwargs)
    for obj in objetos:
        obj.select_set(False)
