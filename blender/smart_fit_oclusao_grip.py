"""Corte de oclusao interna e auto-grip cilindrico para punho/arma (camada L2)."""

from __future__ import annotations

import math
import os
import sys
from typing import Any

if __package__:
    from .smart_fit_contato import (
        Euler,
        Matrix,
        Vector,
        _bvh_mundo,
        _exigir_bpy,
        _nao_manifold_bmesh,
        bmesh,
        bpy,
    )
    from .smart_fit_math import calcular_angulos_punho_cilindrico, calcular_pca_cilindro
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from smart_fit_contato import (
        Euler,
        Matrix,
        Vector,
        _bvh_mundo,
        _exigir_bpy,
        _nao_manifold_bmesh,
        bmesh,
        bpy,
    )
    from smart_fit_math import calcular_angulos_punho_cilindrico, calcular_pca_cilindro


def _extrair_loops_borda(bm) -> list[list[Any]]:
    """Agrupa arestas de borda em loops fechados ordenados."""
    arestas_borda = {e for e in bm.edges if e.is_boundary}
    loops: list[list[Any]] = []
    while arestas_borda:
        e_ini = min(arestas_borda, key=lambda e: e.index)
        arestas_borda.remove(e_ini)
        loop = [e_ini]
        v_atual = e_ini.verts[1]
        v_fim = e_ini.verts[0]
        guard = 0
        while v_atual != v_fim and guard < len(bm.edges) + 4:
            guard += 1
            prox = None
            for e in v_atual.link_edges:
                if e in arestas_borda:
                    prox = e
                    break
            if prox is None:
                break
            arestas_borda.remove(prox)
            loop.append(prox)
            v_atual = prox.other_vert(v_atual)
        loops.append(loop)
    return loops


def _preencher_loop_fan(bm, loop_edges: list[Any]) -> int:
    verts_loop: list[Any] = []
    seen = set()
    for e in loop_edges:
        for v in e.verts:
            if v not in seen:
                seen.add(v)
                verts_loop.append(v)
    if len(verts_loop) < 3:
        return 0
    centro_co = sum((v.co for v in verts_loop), Vector((0.0, 0.0, 0.0))) / float(len(verts_loop))
    v_centro = bm.verts.new(centro_co)
    criadas = 0
    for e in loop_edges:
        v0, v1 = e.verts[0], e.verts[1]
        try:
            bm.faces.new((v0, v1, v_centro))
            criadas += 1
        except ValueError:
            pass
    return criadas


def recortar_oclusao_interna(
    corpo_obj,
    pecas_cobertura,
    dist_max_m: float = 0.035,
    limiar_cobertura: float = 0.85,
) -> dict[str, Any]:
    """Remove poligonos internos do corpo ocluidos sob botas/luvas/armaduras e fecha bordas."""
    _exigir_bpy()
    if corpo_obj is None or not corpo_obj.data.vertices:
        return {"faces_antes": 0, "faces_removidas": 0, "faces_depois": 0, "loops_fechados": 0, "nao_manifold": 0}

    if isinstance(pecas_cobertura, (list, tuple)):
        coberturas = [p for p in pecas_cobertura if p is not None and p is not corpo_obj and getattr(p, "data", None)]
    elif pecas_cobertura is not None and pecas_cobertura is not corpo_obj:
        coberturas = [pecas_cobertura]
    else:
        coberturas = []

    if not coberturas:
        n_f = len(corpo_obj.data.polygons)
        return {
            "faces_antes": n_f,
            "faces_removidas": 0,
            "faces_depois": n_f,
            "loops_fechados": 0,
            "nao_manifold": _nao_manifold_bmesh(corpo_obj),
        }

    bpy.context.view_layer.update()
    bvhs: list[tuple[Any, Any]] = [_bvh_mundo(p) for p in coberturas]
    bm = bmesh.new()
    try:
        bm.from_mesh(corpo_obj.data)
        bmesh.ops.transform(bm, matrix=corpo_obj.matrix_world, verts=bm.verts)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.normal_update()

        faces_antes = len(bm.faces)
        faces_ocultas = []
        d_max = max(0.002, float(dist_max_m))
        limiar = max(0.0, min(1.0, float(limiar_cobertura)))

        for f in bm.faces:
            n = f.normal
            if n.length < 1e-8:
                continue
            n_dir = n.normalized()
            amostras = [f.calc_center_median()]
            amostras.extend(v.co for v in f.verts)
            amostras.extend((e.verts[0].co + e.verts[1].co) * 0.5 for e in f.edges)

            hits = 0
            for pt in amostras:
                ocluido = False
                for bvh, _bm_c in bvhs:
                    if bvh.ray_cast(pt + n_dir * 1e-4, n_dir, d_max)[0] is not None:
                        ocluido = True
                        break
                    if bvh.ray_cast(pt - n_dir * 0.002, n_dir, d_max + 0.002)[0] is not None:
                        ocluido = True
                        break
                if ocluido:
                    hits += 1
            if (hits / float(len(amostras))) >= limiar:
                faces_ocultas.append(f)

        # Nunca apaga 100% da malha para nao gerar objeto vazio
        if not faces_ocultas or len(faces_ocultas) >= len(bm.faces):
            bmesh.ops.transform(bm, matrix=corpo_obj.matrix_world.inverted_safe(), verts=bm.verts)
            nao_m = sum(1 for e in bm.edges if len(e.link_faces) != 2)
            return {
                "faces_antes": faces_antes,
                "faces_removidas": 0,
                "faces_depois": faces_antes,
                "loops_fechados": 0,
                "nao_manifold": nao_m,
            }

        bmesh.ops.delete(bm, geom=faces_ocultas, context="FACES")
        soltas_e = [e for e in bm.edges if not e.link_faces]
        if soltas_e:
            bmesh.ops.delete(bm, geom=soltas_e, context="EDGES")
        soltos_v = [v for v in bm.verts if not v.link_faces]
        if soltos_v:
            bmesh.ops.delete(bm, geom=soltos_v, context="VERTS")

        # Remove triangulos isolados com 3 arestas de borda e desfaz eventuais bow-ties antes do fill
        for _ in range(3):
            peninsulas = [f for f in bm.faces if sum(1 for e in f.edges if e.is_boundary) >= 2]
            if not peninsulas or len(peninsulas) >= len(bm.faces):
                break
            bmesh.ops.delete(bm, geom=peninsulas, context="FACES")
            soltas_e = [e for e in bm.edges if not e.link_faces]
            if soltas_e:
                bmesh.ops.delete(bm, geom=soltas_e, context="EDGES")
            soltos_v = [v for v in bm.verts if not v.link_faces]
            if soltos_v:
                bmesh.ops.delete(bm, geom=soltos_v, context="VERTS")

        loops_antes = _extrair_loops_borda(bm)
        loops_fechados = 0
        edges_borda = [e for e in bm.edges if e.is_boundary]
        if edges_borda:
            res_fill = bmesh.ops.holes_fill(bm, edges=edges_borda, sides=0)
            faces_novas = list(res_fill.get("faces", []))
            loops_fechados = len(loops_antes)
            restantes = _extrair_loops_borda(bm)
            for loop in restantes:
                try:
                    res_el = bmesh.ops.edgeloop_fill(bm, edges=loop)
                    novas_el = list(res_el.get("faces", []))
                    if novas_el:
                        faces_novas.extend(novas_el)
                        loops_fechados += 1
                    elif _preencher_loop_fan(bm, loop) > 0:
                        loops_fechados += 1
                except (RuntimeError, ValueError) as exc:
                    print(f"[smart_fit] aviso edgeloop_fill falhou, usando fan fill: {exc}", file=sys.stderr)
                    if _preencher_loop_fan(bm, loop) > 0:
                        loops_fechados += 1
            ngons = [f for f in bm.faces if len(f.verts) > 3]
            if ngons:
                bmesh.ops.triangulate(bm, faces=ngons)

        bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        nao_manifold = sum(1 for e in bm.edges if len(e.link_faces) != 2)
        faces_depois = len(bm.faces)

        bmesh.ops.transform(bm, matrix=corpo_obj.matrix_world.inverted_safe(), verts=bm.verts)
        bm.to_mesh(corpo_obj.data)
        corpo_obj.data.update()
        return {
            "faces_antes": faces_antes,
            "faces_removidas": len(faces_ocultas),
            "faces_depois": faces_depois,
            "loops_fechados": loops_fechados,
            "nao_manifold": int(nao_manifold),
        }
    finally:
        bm.free()
        for _bvh, bm_c in bvhs:
            bm_c.free()


def auto_grip_cilindrico(
    arma_obj,
    fracao_cabo: tuple[float, float] = (0.05, 0.35),
) -> dict[str, Any]:
    """Detecta eixo PCA, centro e raio radial do cabo de uma arma para empunhadura."""
    _exigir_bpy()
    if arma_obj is None or not getattr(arma_obj, "data", None) or not arma_obj.data.vertices:
        return calcular_pca_cilindro([], fracao_cabo=fracao_cabo)
    mw = arma_obj.matrix_world
    pts = [tuple(mw @ v.co) for v in arma_obj.data.vertices]
    return calcular_pca_cilindro(pts, fracao_cabo=fracao_cabo)


def conformar_punho_ao_cabo(
    rig_obj,
    lado: str = "R",
    grip_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aplica curvatura das falanges das maos no rig ao redor do raio de empunhadura."""
    _exigir_bpy()
    if rig_obj is None or getattr(rig_obj, "pose", None) is None:
        return {"lado": lado, "ossos_posados": 0, "raio_m": 0.016}

    raio_m = float((grip_info or {}).get("raio_m") or 0.016)
    lados_alvo = ("L", "R") if str(lado).strip().upper() == "BOTH" else (str(lado).strip().upper() or "R",)

    # Estima comprimento total do dedo medio quando existir no rig
    comp_mao = 0.085
    for ld in lados_alvo:
        segs = [rig_obj.data.bones.get(f"Middle{i}.{ld}") for i in (1, 2, 3)]
        if all(s is not None for s in segs):
            comp_mao = sum(float(s.length) for s in segs if s is not None)
            break

    angulos = calcular_angulos_punho_cilindrico(raio_m, comprimento_mao_m=comp_mao)
    pbones = rig_obj.pose.bones
    ossos_posados: list[str] = []

    bpy.context.view_layer.objects.active = rig_obj
    bpy.ops.object.mode_set(mode="POSE")
    try:
        for ld in lados_alvo:
            if ld not in ("L", "R"):
                continue
            sinal = 1.0 if ld == "R" else -1.0
            for dedo, graus_3 in angulos["dedos"].items():
                for idx, deg in enumerate(graus_3, 1):
                    for cand in (f"{dedo}{idx}.{ld}", f"{dedo.lower()}_0{idx}_{ld.lower()}"):
                        pb = pbones.get(cand)
                        if pb is not None:
                            pb.rotation_mode = "QUATERNION"
                            pb.rotation_quaternion = Matrix.Rotation(math.radians(deg), 4, "X").to_quaternion()
                            ossos_posados.append(pb.name)
                            break
            for idx, (rx, rz) in enumerate(angulos["thumb"], 1):
                for cand in (f"Thumb{idx}.{ld}", f"thumb_0{idx}_{ld.lower()}"):
                    pb = pbones.get(cand)
                    if pb is not None:
                        pb.rotation_mode = "QUATERNION"
                        pb.rotation_quaternion = Euler(
                            (math.radians(rx), 0.0, math.radians(rz * sinal)), "XYZ"
                        ).to_quaternion()
                        ossos_posados.append(pb.name)
                        break
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.update()

    return {
        "lado": str(lado),
        "raio_m": angulos["raio_m"],
        "media_graus": angulos["media_graus"],
        "soma_graus": angulos["soma_graus"],
        "ossos_posados": len(ossos_posados),
        "ossos": ossos_posados,
    }
