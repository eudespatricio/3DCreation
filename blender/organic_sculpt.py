"""Soldagem organica por voxel (``REMESH VOXEL``) e ``CORRECTIVE_SMOOTH`` no Blender 4.2+.

Funde primitivas/capsulas organicas disjuntas (ex.: corpo + cabeca + membros de criatura/montaria)
em uma unica malha continua watertight antes do auto-rig e do bake PBR, preservando atributos de
cor por vertice (``COLOR_0``) por amostragem espacial ``KDTree`` quando presentes.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

__all__ = [
    "aplicar_corrective_smooth",
    "contar_componentes",
    "gerar_criatura_anatomica",
    "soldar_componentes_organicos",
]


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
    """Fallback deterministico de suavizacao Taubin preservando volume em bmesh."""
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
    """Aplica ``CORRECTIVE_SMOOTH`` preservando volume (com fallback Taubin em bmesh)."""
    if obj is None or obj.type != "MESH" or not obj.data or not obj.data.vertices:
        return {"aplicado": False, "iteracoes": 0}
    iters = max(1, min(int(iteracoes), 12))
    _selecionar(obj)
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
    except Exception:
        antiga = obj.data
        obj.data = backup
        if antiga.users == 0:
            bpy.data.meshes.remove(antiga)
        _suavizar_taubin_fallback(obj, iteracoes=iters, fator=0.42)
        return {"aplicado": True, "modo": "taubin_fallback", "iteracoes": iters}


def _capturar_cores_vertices(obj) -> tuple[str | None, KDTree | None, list[tuple[float, float, float, float]]]:
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
    except Exception as exc:
        antiga = obj.data
        obj.data = backup
        if antiga.users == 0:
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


def _adicionar_tubo_anatomico(
    bm: bmesh.types.BMesh,
    marcos: list[tuple[float, float, float, float, float]],
    *,
    lados: int = 16,
    fechar_pontas: bool = True,
) -> None:
    """Cria tubo organico com secoes elipticas (x, y, z, rx, rz) ao longo de uma curva."""
    if len(marcos) < 2:
        return
    aneis: list[list[bmesh.types.BMVert]] = []
    n = len(marcos)
    for idx, (cx, cy, cz, rx, rz) in enumerate(marcos):
        if idx == 0:
            p_next = Vector(marcos[1][:3])
            tang = p_next - Vector((cx, cy, cz))
        elif idx == n - 1:
            p_prev = Vector(marcos[idx - 1][:3])
            tang = Vector((cx, cy, cz)) - p_prev
        else:
            p_prev = Vector(marcos[idx - 1][:3])
            p_next = Vector(marcos[idx + 1][:3])
            tang = p_next - p_prev
        if tang.length <= 1e-6:
            tang = Vector((0.0, 1.0, 0.0))
        else:
            tang.normalize()

        up_ref = Vector((0.0, 0.0, 1.0))
        if abs(tang.dot(up_ref)) > 0.94:
            up_ref = Vector((0.0, 1.0, 0.0))
        eixo_x = tang.cross(up_ref)
        if eixo_x.length <= 1e-6:
            eixo_x = Vector((1.0, 0.0, 0.0))
        else:
            eixo_x.normalize()
        eixo_z = eixo_x.cross(tang).normalized()

        anel: list[bmesh.types.BMVert] = []
        centro = Vector((cx, cy, cz))
        for k in range(lados):
            ang = (2.0 * math.pi * k) / float(lados)
            offset = eixo_x * (math.cos(ang) * rx) + eixo_z * (math.sin(ang) * rz)
            anel.append(bm.verts.new(centro + offset))
        aneis.append(anel)

    for i in range(len(aneis) - 1):
        a0 = aneis[i]
        a1 = aneis[i + 1]
        for k in range(lados):
            kn = (k + 1) % lados
            try:
                bm.faces.new((a0[k], a0[kn], a1[kn], a1[k]))
            except ValueError:
                pass

    if fechar_pontas and aneis:
        c_ini = Vector(marcos[0][:3])
        v_ini = bm.verts.new(c_ini)
        a_ini = aneis[0]
        for k in range(lados):
            kn = (k + 1) % lados
            try:
                bm.faces.new((v_ini, a_ini[kn], a_ini[k]))
            except ValueError:
                pass

        c_fim = Vector(marcos[-1][:3])
        v_fim = bm.verts.new(c_fim)
        a_fim = aneis[-1]
        for k in range(lados):
            kn = (k + 1) % lados
            try:
                bm.faces.new((v_fim, a_fim[k], a_fim[kn]))
            except ValueError:
                pass


def _adicionar_membrana_asa(
    bm: bmesh.types.BMesh,
    borda_superior: list[tuple[float, float, float]],
    borda_inferior: list[tuple[float, float, float]],
    *,
    espessura: float = 0.042,
) -> None:
    """Constroi membrana alar com espessura solida entre borda superior (spar) e borda posterior."""
    n = min(len(borda_superior), len(borda_inferior))
    if n < 2:
        return
    passos_u = 7
    malha_top: list[list[bmesh.types.BMVert]] = []
    malha_bot: list[list[bmesh.types.BMVert]] = []
    meia_esp = max(espessura * 0.5, 0.018)

    for i in range(n):
        p_sup = Vector(borda_superior[i])
        p_inf = Vector(borda_inferior[i])
        arco = math.sin(math.pi * (i / float(max(n - 1, 1))))
        col_top: list[bmesh.types.BMVert] = []
        col_bot: list[bmesh.types.BMVert] = []
        for j in range(passos_u + 1):
            t = j / float(passos_u)
            p = p_sup.lerp(p_inf, t)
            camber = 0.025 * math.sin(math.pi * t) * arco
            esp_local = meia_esp * (1.0 - 0.25 * t)
            col_top.append(bm.verts.new(Vector((p.x, p.y, p.z + camber + esp_local))))
            col_bot.append(bm.verts.new(Vector((p.x, p.y, p.z + camber - esp_local))))
        malha_top.append(col_top)
        malha_bot.append(col_bot)

    for i in range(n - 1):
        for j in range(passos_u):
            try:
                bm.faces.new((malha_top[i][j], malha_top[i + 1][j], malha_top[i + 1][j + 1], malha_top[i][j + 1]))
            except ValueError:
                pass
            try:
                bm.faces.new((malha_bot[i][j], malha_bot[i][j + 1], malha_bot[i + 1][j + 1], malha_bot[i + 1][j]))
            except ValueError:
                pass

    # Fecha bordas da membrana para garantir volume fechado no Voxel Remesh
    for i in range(n - 1):
        try:
            bm.faces.new((malha_top[i][0], malha_bot[i][0], malha_bot[i + 1][0], malha_top[i + 1][0]))
        except ValueError:
            pass
        try:
            bm.faces.new((malha_top[i][passos_u], malha_top[i + 1][passos_u], malha_bot[i + 1][passos_u], malha_bot[i][passos_u]))
        except ValueError:
            pass
    for j in range(passos_u):
        try:
            bm.faces.new((malha_top[0][j], malha_top[0][j + 1], malha_bot[0][j + 1], malha_bot[0][j]))
        except ValueError:
            pass
        try:
            bm.faces.new((malha_top[n - 1][j], malha_bot[n - 1][j], malha_bot[n - 1][j + 1], malha_top[n - 1][j + 1]))
        except ValueError:
            pass


def _construir_bm_criatura_anatomica(*, com_asas: bool = True) -> bmesh.types.BMesh:
    """Constroi BMesh anatomico 4-patas simetrico (+Y focinho, -Y cauda, +Z cima, patas em Z=0)."""
    bm = bmesh.new()

    # 1. Tronco horizontal musculoso (pelve -> cintura -> caixa toracica -> peito) + pescoco em S + cabeca/focinho
    coluna_pescoco_cabeca = [
        (0.0, -0.64, 0.75, 0.14, 0.14),   # Base pelvica posterior
        (0.0, -0.46, 0.78, 0.23, 0.21),   # Quadril / pelve (ancoragem das patas traseiras)
        (0.0, -0.22, 0.77, 0.21, 0.19),   # Abdome / flanco
        (0.0, 0.04, 0.80, 0.25, 0.23),    # Regiao dorsal (sela / MountSeat)
        (0.0, 0.30, 0.83, 0.29, 0.26),    # Caixa toracica / peito largo
        (0.0, 0.48, 0.86, 0.26, 0.24),    # Ombros / base anterior do torax
        (0.0, 0.64, 0.96, 0.18, 0.19),    # Base do pescoco musculoso
        (0.0, 0.76, 1.12, 0.15, 0.16),    # Meio do pescoco (curva em S ascendente)
        (0.0, 0.86, 1.27, 0.14, 0.15),    # Pescoco superior / nuca
        (0.0, 0.98, 1.34, 0.16, 0.14),    # Cranio posterior
        (0.0, 1.14, 1.32, 0.13, 0.11),    # Focinho medio
        (0.0, 1.32, 1.27, 0.09, 0.08),    # Ponta do focinho / narinas (+Y_bl)
        (0.0, 1.39, 1.25, 0.05, 0.05),    # Extremidade rostral
    ]
    _adicionar_tubo_anatomico(bm, coluna_pescoco_cabeca, lados=20)

    # 2. Mandibula inferior esculpida + cristas supraorbitais + chifres + crista dorsal
    mandibula = [
        (0.0, 0.92, 1.22, 0.12, 0.07),
        (0.0, 1.08, 1.18, 0.10, 0.06),
        (0.0, 1.24, 1.17, 0.07, 0.05),
        (0.0, 1.33, 1.18, 0.04, 0.035),
    ]
    _adicionar_tubo_anatomico(bm, mandibula, lados=14)

    # Cauda longa afilada (-Y_bl), mantida acima de Z=0.56 para separar perfeitamente das 4 patas no solo
    cauda = [
        (0.0, -0.58, 0.75, 0.15, 0.14),
        (0.0, -0.82, 0.70, 0.12, 0.11),
        (0.0, -1.08, 0.66, 0.095, 0.09),
        (0.0, -1.34, 0.63, 0.075, 0.07),
        (0.0, -1.58, 0.61, 0.055, 0.05),
        (0.0, -1.76, 0.62, 0.085, 0.035),  # Leme caudal / spade
        (0.0, -1.88, 0.63, 0.025, 0.02),
    ]
    _adicionar_tubo_anatomico(bm, cauda, lados=16)

    # Placas/cristas dorsais marcadas ao longo do cranio, pescoco, dorso e cauda (com vão de sela em Y=0.04..0.28)
    for y_sp, z_sp, h_sp, r_x, r_z in (
        (1.22, 1.33, 0.08, 0.028, 0.046),  # Crista rostral / nasal
        (0.88, 1.31, 0.19, 0.036, 0.068),  # Crista nucal alta
        (0.75, 1.17, 0.21, 0.038, 0.072),  # Pescoco superior
        (0.61, 1.03, 0.20, 0.040, 0.072),  # Pescoco medio
        (0.45, 0.96, 0.17, 0.040, 0.068),  # Cernelha anterior (frente da sela)
        (-0.08, 0.93, 0.15, 0.038, 0.064), # Lombar (atras da sela)
        (-0.28, 0.92, 0.17, 0.038, 0.066), # Dorso posterior
        (-0.48, 0.91, 0.16, 0.036, 0.062), # Sacral
        (-0.72, 0.78, 0.14, 0.032, 0.056), # Base caudal
        (-0.98, 0.72, 0.13, 0.030, 0.052), # Cauda media
        (-1.24, 0.67, 0.11, 0.026, 0.046), # Cauda posterior
        (-1.48, 0.64, 0.09, 0.024, 0.040), # Antes do leme caudal
    ):
        _adicionar_tubo_anatomico(
            bm,
            [
                (0.0, y_sp + 0.04, z_sp - 0.04, r_x, r_z),
                (0.0, y_sp - 0.03, z_sp + h_sp * 0.58, r_x * 0.80, r_z * 0.85),
                (0.0, y_sp - 0.09, z_sp + h_sp, max(0.022, r_x * 0.52), max(0.028, r_z * 0.55)),
            ],
            lados=10,
        )

    # 3. Membros simetricos (esquerdo +X, direito -X): cristas orbitais pronunciadas, chifres, 4 patas e asas
    for sx in (1.0, -1.0):
        # Arcada supraorbital / sobrancelha reptiliana proeminente + zigomatico
        _adicionar_tubo_anatomico(
            bm,
            [
                (sx * 0.075, 1.22, 1.35, 0.046, 0.044),
                (sx * 0.128, 1.08, 1.40, 0.062, 0.056),
                (sx * 0.138, 0.96, 1.41, 0.058, 0.052),
                (sx * 0.118, 0.87, 1.38, 0.046, 0.044),
            ],
            lados=12,
        )
        # Borda orbital inferior / maca do rosto escamosa
        _adicionar_tubo_anatomico(
            bm,
            [
                (sx * 0.105, 1.18, 1.26, 0.040, 0.036),
                (sx * 0.132, 1.05, 1.27, 0.046, 0.040),
                (sx * 0.125, 0.94, 1.28, 0.042, 0.038),
            ],
            lados=10,
        )
        # Chifre principal curvado para tras e para o alto (garante topo anterior elevado em +Z)
        _adicionar_tubo_anatomico(
            bm,
            [
                (sx * 0.10, 0.94, 1.36, 0.055, 0.055),
                (sx * 0.15, 0.80, 1.47, 0.045, 0.045),
                (sx * 0.19, 0.66, 1.56, 0.034, 0.034),
                (sx * 0.22, 0.54, 1.63, 0.020, 0.020),
            ],
            lados=12,
        )
        # Chifre malar / mandibular secundario
        _adicionar_tubo_anatomico(
            bm,
            [
                (sx * 0.11, 0.92, 1.25, 0.038, 0.038),
                (sx * 0.16, 0.81, 1.27, 0.028, 0.028),
                (sx * 0.20, 0.72, 1.30, 0.016, 0.016),
            ],
            lados=10,
        )

        # PATA DIANTEIRA (ombro -> braco -> antebraco -> pata plantada em Z=0 com 3 garras em +Y)
        pata_dianteira = [
            (sx * 0.22, 0.44, 0.80, 0.14, 0.14),    # Escapula / ombro musculoso
            (sx * 0.27, 0.36, 0.55, 0.115, 0.115),  # Cotovelo
            (sx * 0.26, 0.43, 0.28, 0.095, 0.095),  # Antebraco
            (sx * 0.26, 0.45, 0.10, 0.095, 0.090),  # Pulso / tornozelo anterior
            (sx * 0.26, 0.49, 0.045, 0.120, 0.068), # Base plantar larga no solo
            (sx * 0.26, 0.59, 0.040, 0.110, 0.058), # Dorso da pata dianteira
        ]
        _adicionar_tubo_anatomico(bm, pata_dianteira, lados=14)
        for dx_garra, dy_garra in ((-0.065, 0.14), (0.0, 0.16), (0.065, 0.14)):
            _adicionar_tubo_anatomico(
                bm,
                [
                    (sx * 0.26 + dx_garra, 0.55, 0.045, 0.044, 0.040),
                    (sx * 0.26 + dx_garra * 1.15, 0.55 + dy_garra * 0.65, 0.034, 0.034, 0.032),
                    (sx * 0.26 + dx_garra * 1.25, 0.55 + dy_garra, 0.022, 0.024, 0.022),
                ],
                lados=10,
            )

        # PATA TRASEIRA (coxa musculosa -> joelho -> jarrete -> canela -> pata plantada em Z=0 com 3 garras)
        pata_traseira = [
            (sx * 0.21, -0.44, 0.76, 0.155, 0.155), # Coxa superior / pelve
            (sx * 0.28, -0.33, 0.51, 0.125, 0.125), # Joelho anteriorizado
            (sx * 0.28, -0.52, 0.29, 0.098, 0.098), # Jarrete / hock posterior
            (sx * 0.27, -0.47, 0.10, 0.096, 0.090), # Tornozelo posterior
            (sx * 0.27, -0.43, 0.045, 0.122, 0.068), # Base plantar traseira larga no solo
            (sx * 0.27, -0.33, 0.040, 0.112, 0.058), # Dorso da pata traseira
        ]
        _adicionar_tubo_anatomico(bm, pata_traseira, lados=14)
        for dx_garra, dy_garra in ((-0.065, 0.14), (0.0, 0.16), (0.065, 0.14)):
            _adicionar_tubo_anatomico(
                bm,
                [
                    (sx * 0.27 + dx_garra, -0.36, 0.045, 0.044, 0.040),
                    (sx * 0.27 + dx_garra * 1.15, -0.36 + dy_garra * 0.65, 0.034, 0.034, 0.032),
                    (sx * 0.27 + dx_garra * 1.25, -0.36 + dy_garra, 0.022, 0.024, 0.022),
                ],
                lados=10,
            )

        # ASAS DE DRAGAO / WYVERN QUADRUPEDE (4 segmentos: ombro -> cotovelo -> pulso -> ponta + dedos e membranas)
        if com_asas:
            w0 = (sx * 0.18, 0.28, 0.90)
            w1 = (sx * 0.54, 0.40, 1.18)
            w2 = (sx * 1.06, 0.32, 1.36)
            w3 = (sx * 1.56, 0.14, 1.32)
            w4 = (sx * 1.92, -0.06, 1.20)
            borda_ataque = [
                (*w0, 0.085, 0.085),
                (*w1, 0.070, 0.070),
                (*w2, 0.058, 0.058),
                (*w3, 0.044, 0.044),
                (*w4, 0.030, 0.030),
            ]
            _adicionar_tubo_anatomico(bm, borda_ataque, lados=12)

            # Garra do polegar alar no pulso (w2)
            _adicionar_tubo_anatomico(
                bm,
                [
                    (sx * 1.06, 0.34, 1.37, 0.035, 0.035),
                    (sx * 1.10, 0.45, 1.42, 0.022, 0.022),
                    (sx * 1.12, 0.52, 1.45, 0.012, 0.012),
                ],
                lados=8,
            )

            # Falanges / dedos da asa irradiando do pulso (w2) para a borda posterior
            t_outer = (sx * 1.66, -0.44, 0.96)
            t_mid = (sx * 1.24, -0.52, 0.88)
            t_inner = (sx * 0.76, -0.46, 0.84)
            t_body = (sx * 0.21, -0.26, 0.80)

            for p_fim in (t_outer, t_mid, t_inner):
                p_meio = (
                    0.5 * (w2[0] + p_fim[0]),
                    0.5 * (w2[1] + p_fim[1]) + 0.03,
                    0.5 * (w2[2] + p_fim[2]) + 0.04,
                )
                _adicionar_tubo_anatomico(
                    bm,
                    [
                        (*w2, 0.042, 0.042),
                        (*p_meio, 0.032, 0.032),
                        (*p_fim, 0.022, 0.022),
                    ],
                    lados=10,
                )

            # Membrana alar continua com espessura solida entre a borda de ataque e a borda de fuga
            borda_sup = [w0, w1, w2, w3, w4]
            borda_inf = [t_body, t_inner, t_mid, t_outer, w4]
            _adicionar_membrana_asa(bm, borda_sup, borda_inf, espessura=0.046)

    bm.verts.ensure_lookup_table()
    # Garante que a sola das 4 patas toque exatamente Z = 0.0
    zs = [v.co.z for v in bm.verts]
    if zs:
        z_min = min(zs)
        for v in bm.verts:
            v.co.z = max(0.0, v.co.z - z_min)
            if v.co.z < 0.018:
                v.co.z = 0.0

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def _pintar_cores_vertice_criatura(mesh: bpy.types.Mesh) -> None:
    """Atribui COLOR_0 organico (dorso esmeralda escuro, ventre jade claro, chifres/garras osso)."""
    if not mesh.vertices:
        return
    if "COLOR_0" in mesh.color_attributes:
        attr = mesh.color_attributes["COLOR_0"]
    else:
        attr = mesh.color_attributes.new(name="COLOR_0", type="BYTE_COLOR", domain="CORNER")

    zs = [v.co.z for v in mesh.vertices]
    z_min, z_max = min(zs), max(zs)
    h = max(z_max - z_min, 1e-4)

    cores_v: list[tuple[float, float, float, float]] = []
    for v in mesh.vertices:
        zn = (v.co.z - z_min) / h
        # Ventre e garganta mais claros, dorso e cristas esmeralda profundo, chifres/garras marfim escuro
        if v.co.z > 1.36 and v.co.y < 0.96:
            cor = (0.72, 0.68, 0.56, 1.0)
        elif v.co.z < 0.055 and abs(v.co.x) > 0.16:
            cor = (0.68, 0.64, 0.52, 1.0)
        elif abs(v.co.x) > 0.42:
            cor = (0.16, 0.42, 0.28, 1.0)
        elif v.co.z < 0.62 and abs(v.co.x) < 0.18 and -0.45 < v.co.y < 0.55:
            cor = (0.46, 0.64, 0.42, 1.0)
        else:
            t = max(0.0, min(1.0, zn))
            cor = (
                0.12 + 0.10 * (1.0 - t),
                0.36 + 0.16 * t,
                0.22 + 0.08 * t,
                1.0,
            )
        cores_v.append(cor)

    for poly in mesh.polygons:
        for li in poly.loop_indices:
            vi = mesh.loops[li].vertex_index
            attr.data[li].color = cores_v[vi]


def _gerar_uv_criatura(obj: bpy.types.Object) -> None:
    """Gera UV map limpo via smart_project para bake PBR 3D sem costuras degeneradas."""
    mesh = obj.data
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    mesh.uv_layers.active = mesh.uv_layers[0]
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")


def gerar_criatura_anatomica(job: dict) -> dict:
    """Gera criatura quadrupede ou montaria alada 4-patas anatomica em espaco Blender (+Y frente, +Z cima).

    Exporta ``bruto.glb`` e ``modelo.json`` (``frente="+Y"``, ``canonicalizar=False``) prontos
    para o estagio de pos-processamento, bake PBR 3D (``escamas_dragao``) e auto-rigging.
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)

    tipo = str(job.get("tipo", "criatura_alada"))
    esqueleto = str(job.get("esqueleto", ""))
    com_asas = bool(
        job.get(
            "asas",
            tipo == "criatura_alada" or esqueleto == "winged_mount@1",
        )
    )
    voxel_ratio = float(job.get("voxel_ratio", 1.0 / 138.0))
    iteracoes_smooth = int(job.get("iteracoes_smooth", 2))

    bm = _construir_bm_criatura_anatomica(com_asas=com_asas)
    mesh = bpy.data.meshes.new("CriaturaAnatomicaMesh")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new("CriaturaAnatomica", mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # Solda todos os membros em uma unica malha manifold via Voxel Remesh + Corrective Smooth
    info_solda = soldar_componentes_organicos(
        obj,
        voxel_ratio=voxel_ratio,
        iteracoes_smooth=iteracoes_smooth,
    )

    # Re-nivela as 4 patas exatamente em Z = 0.0 apos a suavizacao e garante apoio plantar firme
    verts = obj.data.vertices
    if verts:
        xs = [v.co.x for v in verts]
        zs = [v.co.z for v in verts]
        cx = 0.5 * (min(xs) + max(xs))
        z_min = min(zs)
        for v in verts:
            v.co.x -= cx
            z_rel = max(0.0, v.co.z - z_min)
            if z_rel < 0.032:
                v.co.z = 0.0
            else:
                v.co.z = z_rel - 0.032
        obj.data.update()

    for poly in obj.data.polygons:
        poly.use_smooth = True

    _gerar_uv_criatura(obj)
    _pintar_cores_vertice_criatura(obj.data)

    # Material base compativel com glTF + vertex color / bake PBR posterior
    mat = bpy.data.materials.new(name="CriaturaBaseMat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        vcol_node = mat.node_tree.nodes.new(type="ShaderNodeVertexColor")
        vcol_node.layer_name = "COLOR_0"
        mat.node_tree.links.new(vcol_node.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.45
        bsdf.inputs["Metallic"].default_value = 0.0
    obj.data.materials.clear()
    obj.data.materials.append(mat)

    saida_dir_str = job.get("saida_dir")
    if saida_dir_str:
        saida_dir = Path(str(saida_dir_str))
    elif job.get("saida_glb"):
        saida_dir = Path(str(job["saida_glb"])).parent
    else:
        saida_dir = Path(".")
    saida_dir.mkdir(parents=True, exist_ok=True)

    nome_glb = Path(str(job.get("saida_glb", saida_dir / "bruto.glb"))).name
    caminho_glb = Path(str(job.get("saida_glb", saida_dir / nome_glb)))
    caminho_meta = Path(str(job.get("saida_meta", saida_dir / "modelo.json")))

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    export_kwargs = {
        "filepath": str(caminho_glb),
        "export_format": "GLB",
        "use_selection": True,
        "export_yup": True,
        "export_apply": True,
        "export_normals": True,
        "export_colors": True,
        "export_vertex_color": "MATERIAL",
        "export_materials": "EXPORT",
    }
    props_gltf = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    export_kwargs = {k: v for k, v in export_kwargs.items() if k in props_gltf}
    bpy.ops.export_scene.gltf(**export_kwargs)

    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    zs = [v.co.z for v in obj.data.vertices]
    meta = {
        "schema": "forge3d/bruto-arquivo@1",
        "provider": "anatomical_creature_sculpt",
        "arquivo": caminho_glb.name,
        "frente": "+Y",
        "canonicalizar": False,
        "proteger_decimate": True,
        "tipo": tipo,
        "asas": com_asas,
        "solda": info_solda,
        "vertices": len(obj.data.vertices),
        "triangulos": sum(max(0, len(p.vertices) - 2) for p in obj.data.polygons),
        "dimensoes_bl": {
            "largura_x": round(max(xs) - min(xs), 4) if xs else 0.0,
            "comprimento_y": round(max(ys) - min(ys), 4) if ys else 0.0,
            "altura_z": round(max(zs) - min(zs), 4) if zs else 0.0,
        },
    }
    caminho_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def _cli() -> None:
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("uso: blender -b --factory-startup --python blender/organic_sculpt.py -- <job.json>")
    args = argv[argv.index("--") + 1 :]
    caminho_job: Path | None = None
    i = 0
    while i < len(args):
        if args[i] == "--modo" and i + 1 < len(args):
            i += 2
            continue
        caminho_job = Path(args[i])
        i += 1
    if caminho_job is None:
        raise SystemExit("job.json nao informado")
    job = json.loads(caminho_job.read_text(encoding="utf-8"))
    gerar_criatura_anatomica(job)


if __name__ == "__main__":
    _cli()

