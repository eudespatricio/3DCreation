"""Configuracao de resolucao, Cycles, estado de cena e preparo de high-mesh para bake PBR."""

from __future__ import annotations

import math
import os
import sys

try:
    import bmesh
    import bpy
    from mathutils import Vector
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bmesh = None  # type: ignore[assignment]
    bpy = None  # type: ignore[assignment]
    Vector = None  # type: ignore[assignment,misc]


def px_bake_recomendado(
    qualidade: str,
    solicitado: int | None = None,
    teto_perfil: int | None = None,
) -> tuple[int, int]:
    """Calcula ``(px_basecolor, px_submapas)`` para 1K/2K/4K sem rebaixar 1K para 512px."""
    q = str(qualidade or "standard").strip().lower()
    permite_4k = (teto_perfil is not None and int(teto_perfil) >= 4096) or (
        solicitado is not None
        and int(solicitado) >= 4096
        and (teto_perfil is None or int(teto_perfil) >= 4096)
    )
    teto_max = 4096 if permite_4k else 2048
    if teto_perfil is not None and int(teto_perfil) > 0:
        teto_max = max(64, min(teto_max, int(teto_perfil)))

    if solicitado is not None and int(solicitado) > 0:
        px = max(64, min(int(solicitado), teto_max))
    elif q == "ultra" and teto_perfil is not None and int(teto_perfil) >= 4096:
        px = 4096
    elif q in ("hero", "ultra"):
        px = min(2048, teto_max)
    else:
        px = min(1024, teto_max)

    if px >= 4096:
        px_sub = 4096 if q == "ultra" else 2048
    elif px >= 2048:
        px_sub = 2048 if (q == "ultra" or (q == "hero" and teto_perfil is not None and int(teto_perfil) >= 4096)) else 1024
    elif px >= 1024:
        px_sub = 1024
    else:
        px_sub = max(64, px)
    return px, px_sub


def deve_ativar_bake_high_low(
    item: dict,
    *,
    tem_cor_vertice: bool,
    tem_uv: bool,
    tem_materiais: bool,
) -> bool:
    """Dispara bake Cycles PBR sempre que material=pbr, detalhe_alto, pbr_zonas ou procedural existir."""
    if not isinstance(item, dict):
        return bool(tem_cor_vertice)
    if tem_cor_vertice or bool(item.get("material_procedural")) or bool(item.get("pbr_zonas")):
        return True
    if str(item.get("material") or "").strip().lower() == "pbr" and (tem_uv or tem_materiais):
        return True
    det = item.get("detalhe_alto")
    if isinstance(det, dict) and det.get("ativo", True) and (tem_uv or tem_materiais):
        return True
    retopologia = str(item.get("retopologia") or "padrao").strip().lower()
    return retopologia == "quadriflow" and tem_uv and tem_materiais


def preparar_high_mesh_detalhe_alto(high_obj, cfg: dict | None) -> dict:
    """Enriquece ``high_obj`` no Blender com crease + Bevel seguro + Subsurf antes do bake Cycles."""
    if not isinstance(cfg, dict) or not cfg.get("ativo", True):
        return {"aplicado": False}
    if high_obj is None or getattr(high_obj, "data", None) is None:
        return {"aplicado": False}

    chanfro = max(0.0, min(0.05, float(cfg.get("chanfro_bevel_m", 0.008))))
    subdiv = max(0, min(3, int(cfg.get("subdiv_niveis", 2))))
    crease_deg = max(15.0, min(85.0, float(cfg.get("crease_angulo_graus", 38.0))))
    crease_rad = math.radians(crease_deg)

    tris_inicial = _contar_triangulos(high_obj)
    if tris_inicial > 60_000:
        return {
            "aplicado": False,
            "motivo": "malha_i23d_ja_densa",
            "tris_high_inicial": tris_inicial,
        }

    bm = bmesh.new()
    bm.from_mesh(high_obj.data)
    crease_layer = bm.edges.layers.float.get("crease_edge") or bm.edges.layers.float.new("crease_edge")
    vivas = 0
    for edge in bm.edges:
        if len(edge.link_faces) == 2:
            ang = edge.link_faces[0].normal.angle(edge.link_faces[1].normal, 0.0)
            if ang >= crease_rad:
                edge[crease_layer] = 0.85
                vivas += 1
        elif len(edge.link_faces) == 1:
            edge[crease_layer] = 1.0
    bm.to_mesh(high_obj.data)
    bm.free()
    high_obj.data.update()

    bpy.ops.object.select_all(action="DESELECT")
    high_obj.select_set(True)
    bpy.context.view_layer.objects.active = high_obj

    if chanfro > 0.0:
        mod_bev = high_obj.modifiers.new("forge3d_high_bevel", "BEVEL")
        mod_bev.offset_type = "OFFSET"
        mod_bev.width = chanfro
        mod_bev.segments = 2
        mod_bev.limit_method = "ANGLE"
        mod_bev.angle_limit = crease_rad
        mod_bev.use_clamp_overlap = True
        if hasattr(mod_bev, "harden_normals"):
            mod_bev.harden_normals = False
        bpy.ops.object.modifier_apply(modifier=mod_bev.name)

    if subdiv > 0:
        mod_sub = high_obj.modifiers.new("forge3d_high_subdiv", "SUBSURF")
        mod_sub.levels = subdiv
        mod_sub.render_levels = subdiv
        mod_sub.use_creases = True
        bpy.ops.object.modifier_apply(modifier=mod_sub.name)

    tris_final = _contar_triangulos(high_obj)
    return {
        "aplicado": True,
        "arestas_marcadas": vivas,
        "chanfro_m": chanfro,
        "subdiv_niveis": subdiv,
        "tris_high_inicial": tris_inicial,
        "tris_high_enriquecido": tris_final,
    }


def construir_shader_pbr_zonas_blender(
    nome_mat: str,
    zonas: list[dict],
    *,
    presets_pbr: dict | None = None,
    img_paleta=None,
    nome_cor_vertice: str | None = None,
    ao_cavidade_forca: float = 0.35,
):
    """Encaminha construcao do grafo multi-zona Cycles para ``procedural_pbr``."""
    proc_mod = __import__("procedural_pbr")
    return proc_mod.construir_shader_pbr_zonas_blender(
        nome_mat,
        zonas,
        presets_pbr=presets_pbr,
        img_paleta=img_paleta,
        nome_cor_vertice=nome_cor_vertice,
        ao_cavidade_forca=ao_cavidade_forca,
    )


def _contar_triangulos(obj) -> int:
    return sum(max(len(p.vertices) - 2, 0) for p in obj.data.polygons)


def _bbox_diag(obj) -> float:
    """Diagonal da AABB do objeto em espaco de mundo."""
    if not obj.data.vertices:
        return 0.0
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    mw = obj.matrix_world
    for v in obj.data.vertices:
        co = mw @ v.co
        xs.append(co.x)
        ys.append(co.y)
        zs.append(co.z)
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _selecionar_high_para_low(high_obj, low_obj) -> None:
    """Seleciona apenas ``high_obj`` e ``low_obj``, deixando ``low_obj`` ativo."""
    bpy.ops.object.select_all(action="DESELECT")
    high_obj.hide_render = False
    low_obj.hide_render = False
    high_obj.hide_set(False)
    low_obj.hide_set(False)
    high_obj.select_set(True)
    low_obj.select_set(True)
    bpy.context.view_layer.objects.active = low_obj


def _calcular_bbox_mundo(obj) -> tuple[Vector, Vector]:
    """Calcula AABB ``(minimo, maximo)`` em espaco de mundo."""
    if not obj.data.vertices:
        return Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 0.0))
    mw = obj.matrix_world
    min_x = min_y = min_z = float("inf")
    max_x = max_y = max_z = float("-inf")
    for v in obj.data.vertices:
        co = mw @ v.co
        if co.x < min_x:
            min_x = co.x
        if co.x > max_x:
            max_x = co.x
        if co.y < min_y:
            min_y = co.y
        if co.y > max_y:
            max_y = co.y
        if co.z < min_z:
            min_z = co.z
        if co.z > max_z:
            max_z = co.z
    return Vector((min_x, min_y, min_z)), Vector((max_x, max_y, max_z))


def _capturar_estado_cena(cena) -> dict:
    return {
        "view_transform": cena.view_settings.view_transform,
        "look": cena.view_settings.look,
        "exposure": cena.view_settings.exposure,
        "gamma": cena.view_settings.gamma,
        "display_device": cena.display_settings.display_device,
        "file_format": cena.render.image_settings.file_format,
        "color_mode": cena.render.image_settings.color_mode,
        "color_depth": cena.render.image_settings.color_depth,
        "compression": cena.render.image_settings.compression,
    }


def _configurar_render_png_linear(cena) -> None:
    # Standard + None preserva exatamente os canais sRGB/Non-Color ao salvar via save_render.
    cena.view_settings.view_transform = "Standard"
    cena.view_settings.look = "None"
    cena.view_settings.exposure = 0.0
    cena.view_settings.gamma = 1.0
    cena.display_settings.display_device = "sRGB"
    cena.render.image_settings.file_format = "PNG"
    cena.render.image_settings.color_mode = "RGB"
    cena.render.image_settings.color_depth = "8"
    cena.render.image_settings.compression = 90


def _restaurar_estado_cena(cena, anterior: dict) -> None:
    cena.view_settings.view_transform = anterior["view_transform"]
    cena.view_settings.look = anterior["look"]
    cena.view_settings.exposure = anterior["exposure"]
    cena.view_settings.gamma = anterior["gamma"]
    cena.display_settings.display_device = anterior["display_device"]
    cena.render.image_settings.file_format = anterior["file_format"]
    cena.render.image_settings.color_mode = anterior["color_mode"]
    cena.render.image_settings.color_depth = anterior["color_depth"]
    cena.render.image_settings.compression = anterior["compression"]


def _suavizar_high_taubin(obj, iteracoes: int = 3, fator: float = 0.45) -> None:
    """Alisa ondas de Marching Cubes em malhas organicas sem encolher volume (mantido para compat)."""
    if not obj.data.vertices or iteracoes <= 0:
        return
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        for _ in range(iteracoes):
            for peso in (fator, -1.04 * fator):
                deslocs: list[Vector] = []
                for v in bm.verts:
                    edges = v.link_edges
                    if not edges:
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
    finally:
        bm.free()


def _configurar_dispositivo_cycles(cena, preferir_gpu: bool = True) -> str:
    """Ativa Cycles GPU (OPTIX/CUDA) se disponivel no subprocesso, com fallback limpo para CPU."""
    cena.render.engine = "CYCLES"
    env_dev = os.environ.get("FORGE3D_CYCLES_DEVICE", "").strip().upper()
    if not preferir_gpu or env_dev == "CPU":
        cena.cycles.device = "CPU"
        return "CPU"
    addon = bpy.context.preferences.addons.get("cycles")
    if addon is not None:
        cprefs = addon.preferences
        tipos = (env_dev,) if env_dev in ("OPTIX", "CUDA") else ("OPTIX", "CUDA")
        for tipo in tipos:
            try:
                cprefs.compute_device_type = tipo
                if hasattr(cprefs, "get_devices"):
                    cprefs.get_devices()
                elif hasattr(cprefs, "refresh_devices"):
                    cprefs.refresh_devices()
                gpus = [d for d in cprefs.devices if getattr(d, "type", "") == tipo]
                if gpus:
                    for d in cprefs.devices:
                        d.use = getattr(d, "type", "") in (tipo, "CPU")
                    cena.cycles.device = "GPU"
                    return f"GPU:{tipo}"
            except (RuntimeError, AttributeError, TypeError) as exc:
                sys.stderr.write(f"[forge3d.bake_pbr] Cycles {tipo} indisponivel: {exc}\n")
                continue
    cena.cycles.device = "CPU"
    return "CPU"


def _executar_bake_seguro(cena, **kwargs) -> None:
    """Roda ``bpy.ops.object.bake`` caindo automaticamente em CPU se o bake na GPU falhar."""
    try:
        bpy.ops.object.bake(**kwargs)
    except RuntimeError:
        if getattr(cena.cycles, "device", "CPU") == "GPU":
            cena.cycles.device = "CPU"
            bpy.ops.object.bake(**kwargs)
        else:
            raise


def _diag_bmesh_verts(bm) -> float:
    if not bm.verts:
        return 0.0
    xs, ys, zs = [v.co.x for v in bm.verts], [v.co.y for v in bm.verts], [v.co.z for v in bm.verts]
    return math.sqrt((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2 + (max(zs) - min(zs)) ** 2)


def _deletar_faces_e_orfaos(bm, faces: list) -> None:
    bmesh.ops.delete(bm, geom=faces, context="FACES")
    soltas_e = [e for e in bm.edges if not e.link_faces]
    if soltas_e:
        bmesh.ops.delete(bm, geom=soltas_e, context="EDGES")
    soltos_v = [v for v in bm.verts if not v.link_faces]
    if soltos_v:
        bmesh.ops.delete(bm, geom=soltos_v, context="VERTS")


def filtrar_casca_interna_high(
    high_obj, low_obj, suavizar_fn=None, *, eh_organico: bool = True
) -> dict:
    """Remove casca interna invertida coplanar de dual-contouring preservando paredes finas."""
    vazio = {"aplicado": False, "faces_removidas": 0, "faces_restantes": 0}
    if (
        bmesh is None or high_obj is None or low_obj is None
        or getattr(high_obj, "type", None) != "MESH" or getattr(low_obj, "type", None) != "MESH"
        or getattr(high_obj, "data", None) is None or getattr(low_obj, "data", None) is None
        or not high_obj.data.polygons or not low_obj.data.polygons
    ):
        return vazio

    from mathutils.bvhtree import BVHTree

    bm_low, bm_high = bmesh.new(), bmesh.new()
    try:
        bm_low.from_mesh(low_obj.data)
        bmesh.ops.transform(bm_low, matrix=high_obj.matrix_world.inverted_safe() @ low_obj.matrix_world, verts=list(bm_low.verts))
        bm_low.normal_update()
        diag = _diag_bmesh_verts(bm_low)
        if diag <= 1e-6:
            return {"aplicado": False, "faces_removidas": 0, "faces_restantes": len(high_obj.data.polygons)}
        bvh_low = BVHTree.FromBMesh(bm_low)

        bm_high.from_mesh(high_obj.data)
        bm_high.normal_update()
        bvh_high = BVHTree.FromBMesh(bm_high)
        total = len(bm_high.faces)
        max_dist = (0.005 if eh_organico else 0.002) * diag
        dot_lim = -0.55 if eh_organico else -0.85
        ray_eps = 1e-5 * diag
        neg_faces, pos_count = [], 0
        for f in bm_high.faces:
            centro_f = f.calc_center_median()
            loc, n_low, _idx, dist = bvh_low.find_nearest(centro_f)
            if loc is None:
                continue
            d = f.normal.dot(n_low)
            if d < dot_lim and dist <= max_dist and f.normal.length > 1e-8:
                hit_loc, hit_n, hit_idx, _hit_d = bvh_high.ray_cast(centro_f - f.normal * ray_eps, -f.normal, max_dist)
                if hit_loc is not None and hit_idx != f.index and hit_n.dot(f.normal) < -0.50:
                    neg_faces.append(f)
            elif d > 0.15:
                pos_count += 1

        if total < 200 or len(neg_faces) < 100 or (len(neg_faces) / float(total)) < 0.15 or (pos_count / float(total)) < 0.20:
            return {"aplicado": False, "faces_removidas": 0, "faces_restantes": total}

        _deletar_faces_e_orfaos(bm_high, neg_faces)
        weld_dist = max(1e-5, min(1e-4, 1.5e-5 * diag))
        if bm_high.verts:
            bmesh.ops.remove_doubles(bm_high, verts=list(bm_high.verts), dist=weld_dist)
        bm_high.normal_update()
        bm_high.to_mesh(high_obj.data)
        high_obj.data.update()
        n_removidas = len(neg_faces)
    finally:
        bm_high.free()
        bm_low.free()

    if callable(suavizar_fn):
        suavizar_fn(high_obj)
    return {"aplicado": True, "faces_removidas": n_removidas, "faces_restantes": len(high_obj.data.polygons)}


def remover_espuma_interna_malha(obj, suavizar_fn=None) -> dict:
    """Remove espuma/casca interna presa por visibilidade de 9 raios hemisfericos em espaco local."""
    if (
        bmesh is None or obj is None or getattr(obj, "type", None) != "MESH"
        or getattr(obj, "data", None) is None or not obj.data.polygons
    ):
        return {"aplicado": False, "faces_removidas": 0, "faces_restantes": 0}

    from mathutils.bvhtree import BVHTree

    bm = bmesh.new()
    aplicado, rem, total = False, 0, len(obj.data.polygons)
    try:
        bm.from_mesh(obj.data)
        bm.normal_update()
        bm.faces.ensure_lookup_table()
        total = len(bm.faces)
        diag = _diag_bmesh_verts(bm)
        if total < 200 or diag <= 1e-6:
            return {"aplicado": False, "faces_removidas": 0, "faces_restantes": total}

        vol_before = bm.calc_volume(signed=True)
        bvh = BVHTree.FromBMesh(bm)
        eps = 1e-4 * diag
        ref_x, ref_y = Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0))
        presas = []
        for f in bm.faces:
            if f.normal.length <= 1e-8:
                continue
            n = f.normal.normalized()
            t1 = n.cross(ref_x if abs(n.x) < 0.9 else ref_y).normalized()
            t2 = n.cross(t1).normalized()
            d1, d2 = (t1 + t2).normalized(), (t1 - t2).normalized()
            orig = f.calc_center_median() + n * eps
            raios = (
                n, (n + t1).normalized(), (n - t1).normalized(), (n + t2).normalized(), (n - t2).normalized(),
                (0.45 * n + d1).normalized(), (0.45 * n - d1).normalized(),
                (0.45 * n + d2).normalized(), (0.45 * n - d2).normalized(),
            )
            if all(bvh.ray_cast(orig, d)[0] is not None for d in raios):
                presas.append(f)

        rem = len(presas)
        if rem < 100 or not (0.15 <= (rem / float(total)) <= 0.85):
            return {"aplicado": False, "faces_removidas": 0, "faces_restantes": total}

        _deletar_faces_e_orfaos(bm, presas)
        bm.normal_update()
        vol_after = bm.calc_volume(signed=True)
        if abs(vol_after) < max(abs(vol_before) * 0.70, 1e-6):
            return {"aplicado": False, "faces_removidas": 0, "faces_restantes": total}

        bm.to_mesh(obj.data)
        obj.data.update()
        aplicado = True
    finally:
        bm.free()

    if aplicado and callable(suavizar_fn):
        suavizar_fn(obj)
    return {"aplicado": True, "faces_removidas": rem, "faces_restantes": total - rem, "modo": "espuma_interna_9raios"}
