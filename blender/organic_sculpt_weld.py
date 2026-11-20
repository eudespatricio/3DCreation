"""Soldagem organica por voxel (``REMESH VOXEL``) e ``CORRECTIVE_SMOOTH`` (camada L0)."""

from __future__ import annotations

import math
import sys

import bmesh
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree


def _selecionar(obj) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.hide_viewport = False
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def contar_componentes(obj) -> int:
    """Conta componentes conexas de vertices na malha de ``obj``."""
    if obj is None or obj.type != "MESH" or not obj.data or not obj.data.vertices:
        return 0
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        vistos: set[int] = set()
        componentes = 0
        for v in bm.verts:
            if not v.link_faces or v.index in vistos:
                continue
            componentes += 1
            pilha = [v]
            vistos.add(v.index)
            while pilha:
                atual = pilha.pop()
                for e in atual.link_edges:
                    outro = e.other_vert(atual)
                    if outro.index not in vistos:
                        vistos.add(outro.index)
                        pilha.append(outro)
        return max(1, componentes) if bm.verts else 0
    finally:
        bm.free()


def _suavizar_taubin_fallback(obj, iteracoes: int = 3, fator: float = 0.45) -> int:
    """Mantido apenas para compatibilidade de simbolo; nao usar no pipeline."""
    if obj is None or obj.type != "MESH" or not obj.data or not obj.data.vertices:
        return 0
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        for _ in range(max(1, int(iteracoes))):
            for peso in (fator, -1.04 * fator):
                deslocs: list[Vector] = []
                for v in bm.verts:
                    edges = v.link_edges
                    if not edges or any(len(e.link_faces) < 2 for e in edges):
                        deslocs.append(Vector((0.0, 0.0, 0.0)))
                        continue
                    soma = Vector((0.0, 0.0, 0.0))
                    for e in edges:
                        soma += e.other_vert(v).co
                    deslocs.append(((soma / len(edges)) - v.co) * peso)
                for v, d in zip(bm.verts, deslocs):
                    v.co += d
        bm.normal_update()
        bm.to_mesh(obj.data)
        obj.data.update()
        return len(obj.data.vertices)
    finally:
        bm.free()


def aplicar_corrective_smooth(
    obj,
    iteracoes: int = 3,
    fator: float = 0.5,
) -> dict:
    """Aplica ``CORRECTIVE_SMOOTH`` preservando volume sem fallback Taubin cumulativo."""
    if obj is None or obj.type != "MESH" or not obj.data or not obj.data.vertices:
        return {"aplicado": False, "iteracoes": 0}
    iters = max(1, min(int(iteracoes), 12))
    _selecionar(obj)
    if getattr(obj, "mode", "OBJECT") != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    backup = obj.data.copy()
    try:
        mod = obj.modifiers.new(name="Forge3DCorrectiveSmooth", type="CORRECTIVE_SMOOTH")
        mod.iterations = iters
        mod.factor = max(0.05, min(float(fator), 1.0))
        mod.smooth_type = "SIMPLE"
        mod.use_only_smooth = True
        mod.use_pin_boundary = True
        bpy.ops.object.modifier_apply(modifier=mod.name)
        if len(obj.data.vertices) < 4 or len(obj.data.polygons) < 4:
            raise RuntimeError("corrective_smooth zerou malha")
        obj.data.update()
        bpy.data.meshes.remove(backup)
        return {"aplicado": True, "modo": "corrective_smooth", "iteracoes": iters}
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        print(
            f"[organic_sculpt] aviso corrective_smooth em {obj.name}: {exc}",
            file=sys.stderr,
        )
        antiga = obj.data
        obj.data = backup
        if antiga is not None and antiga.users == 0:
            bpy.data.meshes.remove(antiga)
        return {
            "aplicado": False,
            "modo": "corrective_smooth_falhou",
            "iteracoes": 0,
            "erro": str(exc),
        }


def _capturar_cores_vertices(
    obj,
) -> tuple[str | None, KDTree | None, list[tuple[float, float, float, float]]]:
    """Captura ``color_attributes`` ativos em KDTree para transferencia pos-remesh."""
    if obj is None or obj.data is None or not obj.data.color_attributes or not obj.data.vertices:
        return None, None, []
    ativo = obj.data.color_attributes.active_color or obj.data.color_attributes[0]
    nome_cor = ativo.name
    n_verts = len(obj.data.vertices)
    kd = KDTree(n_verts)
    cores: list[tuple[float, float, float, float]] = []
    if ativo.domain == "POINT" and len(ativo.data) >= n_verts:
        for i, v in enumerate(obj.data.vertices):
            kd.insert(v.co, i)
            c = ativo.data[i].color
            cores.append((float(c[0]), float(c[1]), float(c[2]), float(c[3])))
    else:
        acum = [[0.0, 0.0, 0.0, 0.0, 0.0] for _ in range(n_verts)]
        for li, lp in enumerate(obj.data.loops):
            if li < len(ativo.data):
                c = ativo.data[li].color
                slot = acum[lp.vertex_index]
                slot[0] += float(c[0])
                slot[1] += float(c[1])
                slot[2] += float(c[2])
                slot[3] += float(c[3])
                slot[4] += 1.0
        for i, v in enumerate(obj.data.vertices):
            kd.insert(v.co, i)
            slot = acum[i]
            cnt = max(1.0, slot[4])
            cores.append((slot[0] / cnt, slot[1] / cnt, slot[2] / cnt, slot[3] / cnt))
    kd.balance()
    return nome_cor, kd, cores


def _restaurar_cores_vertices(
    obj,
    nome_cor: str | None,
    kd: KDTree | None,
    cores: list[tuple[float, float, float, float]],
) -> None:
    if not nome_cor or kd is None or not cores or not obj.data.vertices:
        return
    for attr in list(obj.data.color_attributes):
        obj.data.color_attributes.remove(attr)
    novo = obj.data.color_attributes.new(name=nome_cor, type="FLOAT_COLOR", domain="POINT")
    obj.data.color_attributes.active_color = novo
    for i, v in enumerate(obj.data.vertices):
        _co, idx, _dist = kd.find(v.co)
        novo.data[i].color = cores[idx]


def _remover_ilhas_menores(obj, frac_min: float = 0.05) -> int:
    """Remove ilhas conexas pequenas residuais do Voxel Remesh, mantendo o corpo principal."""
    if obj is None or obj.type != "MESH" or not obj.data or not obj.data.vertices:
        return 0
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        vistos: set[int] = set()
        grupos: list[list[bmesh.types.BMVert]] = []
        for v in bm.verts:
            if v.index in vistos:
                continue
            comp: list[bmesh.types.BMVert] = [v]
            vistos.add(v.index)
            pilha = [v]
            while pilha:
                atual = pilha.pop()
                for e in atual.link_edges:
                    outro = e.other_vert(atual)
                    if outro.index not in vistos:
                        vistos.add(outro.index)
                        comp.append(outro)
                        pilha.append(outro)
            grupos.append(comp)
        if len(grupos) <= 1:
            return 0
        maior = max(len(g) for g in grupos)
        limiar = max(4, int(maior * frac_min))
        apagar = [v for g in grupos if len(g) < limiar for v in g]
        if not apagar:
            return 0
        bmesh.ops.delete(bm, geom=apagar, context="VERTS")
        bm.normal_update()
        bm.to_mesh(obj.data)
        obj.data.update()
        return len(apagar)
    finally:
        bm.free()


def soldar_componentes_organicos(
    obj,
    voxel_ratio: float = 1.0 / 128.0,
    iteracoes_smooth: int = 3,
) -> dict:
    """Funde componentes organicos disjuntos via ``REMESH (VOXEL)`` + ``CORRECTIVE_SMOOTH``."""
    if obj is None or obj.type != "MESH" or not obj.data or not obj.data.vertices:
        return {"soldado": False, "razao": "malha_vazia"}

    _selecionar(obj)
    if getattr(obj, "mode", "OBJECT") != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    comp_antes = contar_componentes(obj)
    v_antes = len(obj.data.vertices)
    f_antes = len(obj.data.polygons)

    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    zs = [v.co.z for v in obj.data.vertices]
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    extensao = max(dx, dy, dz, math.sqrt(dx * dx + dy * dy + dz * dz) * 0.65)
    if extensao <= 1e-5:
        return {"soldado": False, "razao": "extensao_zero"}

    ratio = max(1.0 / 256.0, min(float(voxel_ratio), 1.0 / 24.0))
    voxel_size = max(0.004, extensao * ratio)

    nome_cor, kd_cores, lista_cores = _capturar_cores_vertices(obj)
    backup = obj.data.copy()

    try:
        mod_remesh = obj.modifiers.new(name="Forge3DVoxelWeld", type="REMESH")
        mod_remesh.mode = "VOXEL"
        mod_remesh.voxel_size = voxel_size
        mod_remesh.adaptivity = 0.002
        mod_remesh.use_smooth_shade = True
        bpy.ops.object.modifier_apply(modifier=mod_remesh.name)
        _remover_ilhas_menores(obj, frac_min=0.05)
        if len(obj.data.vertices) < 8 or len(obj.data.polygons) < 6:
            raise RuntimeError("remesh voxel produziu malha insuficiente")
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        print(
            f"[organic_sculpt] aviso voxel_remesh em {obj.name}: {exc}",
            file=sys.stderr,
        )
        antiga = obj.data
        obj.data = backup
        if antiga is not None and antiga.users == 0:
            bpy.data.meshes.remove(antiga)
        return {"soldado": False, "razao": f"remesh_falhou: {exc}"}

    bpy.data.meshes.remove(backup)
    info_cs = aplicar_corrective_smooth(obj, iteracoes=iteracoes_smooth, fator=0.5)
    _restaurar_cores_vertices(obj, nome_cor, kd_cores, lista_cores)

    for poly in obj.data.polygons:
        poly.use_smooth = True
    obj.data.update()

    comp_depois = contar_componentes(obj)
    return {
        "soldado": True,
        "executado": True,
        "voxel_size": round(voxel_size, 6),
        "voxel_ratio": round(ratio, 6),
        "componentes_antes": comp_antes,
        "componentes_depois": comp_depois,
        "vertices_antes": v_antes,
        "faces_antes": f_antes,
        "vertices_depois": len(obj.data.vertices),
        "faces_depois": len(obj.data.polygons),
        "corrective_smooth": info_cs,
        "cor_preservada": bool(nome_cor),
    }
