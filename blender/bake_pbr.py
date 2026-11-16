"""High->Low PBR bake no Cycles (BaseColor, Normal, ORM) para o pipeline Forge3D.

Roda dentro do Python embutido do Blender 4.2+ usando apenas ``bpy``, ``bmesh``, ``mathutils``
e a biblioteca padrao (sem Pillow nem numpy).
"""

from __future__ import annotations

import math
import os
from array import array

try:
    import bmesh
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bmesh = None  # type: ignore[assignment]
    bpy = None  # type: ignore[assignment]
    Vector = None  # type: ignore[assignment,misc]
    BVHTree = None  # type: ignore[assignment,misc]


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
        px_sub = 2048 if q == "ultra" else 1024
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
    if tris_inicial > 80_000:
        subdiv = min(subdiv, 1)

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


def _detectar_bbox_uv_foreground(img) -> tuple[float, float, float, float]:
    """Detecta bbox normalizado ``(u0, u1, v0, v1)`` do primeiro plano se houver margem uniforme."""
    w, h = int(img.size[0]), int(img.size[1])
    if w <= 0 or h <= 0:
        return (0.0, 1.0, 0.0, 1.0)
    buf = array("f", [0.0]) * (w * h * 4)
    img.pixels.foreach_get(buf)

    gw = min(w, 128)
    gh = min(h, 128)
    min_alpha = 1.0
    grade_rgb: list[tuple[float, float, float]] = []
    grade_a: list[float] = []
    for gy in range(gh):
        py = min(h - 1, int((gy + 0.5) * h / gh))
        row_off = py * w * 4
        for gx in range(gw):
            px_i = min(w - 1, int((gx + 0.5) * w / gw))
            idx = row_off + px_i * 4
            a = buf[idx + 3]
            if a < min_alpha:
                min_alpha = a
            grade_rgb.append((buf[idx], buf[idx + 1], buf[idx + 2]))
            grade_a.append(a)

    if min_alpha < 0.98:
        min_x, max_x = gw, -1
        min_y, max_y = gh, -1
        for gy in range(gh):
            for gx in range(gw):
                if grade_a[gy * gw + gx] >= 0.45:
                    if gx < min_x:
                        min_x = gx
                    if gx > max_x:
                        max_x = gx
                    if gy < min_y:
                        min_y = gy
                    if gy > max_y:
                        max_y = gy
        if max_x > min_x and max_y > min_y:
            return (min_x / gw, (max_x + 1) / gw, min_y / gh, (max_y + 1) / gh)
        return (0.0, 1.0, 0.0, 1.0)

    cantos = [
        grade_rgb[0],
        grade_rgb[gw - 1],
        grade_rgb[(gh - 1) * gw],
        grade_rgb[gh * gw - 1],
    ]
    bg = tuple(sum(c[k] for c in cantos) * 0.25 for k in range(3))
    canto_spread = max(
        math.sqrt((c[0] - bg[0]) ** 2 + (c[1] - bg[1]) ** 2 + (c[2] - bg[2]) ** 2)
        for c in cantos
    )
    if canto_spread < 0.08:
        limiar_sq = 0.09 * 0.09
        fg_count = 0
        min_x, max_x = gw, -1
        min_y, max_y = gh, -1
        for gy in range(gh):
            for gx in range(gw):
                r, g, b = grade_rgb[gy * gw + gx]
                if (r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2 > limiar_sq:
                    fg_count += 1
                    if gx < min_x:
                        min_x = gx
                    if gx > max_x:
                        max_x = gx
                    if gy < min_y:
                        min_y = gy
                    if gy > max_y:
                        max_y = gy
        total = gw * gh
        if 0.05 * total <= fg_count <= 0.90 * total and max_x > min_x and max_y > min_y:
            return (min_x / gw, (max_x + 1) / gw, min_y / gh, (max_y + 1) / gh)

    return (0.0, 1.0, 0.0, 1.0)


def _criar_camera_ortografica_frontal(
    nome: str, min_v: Vector, max_v: Vector, colecao
):
    """Cria camera ortografica alinhada a frente ``+Y`` (convencao canonical/render_preview)."""
    cx = 0.5 * (min_v.x + max_v.x)
    cz = 0.5 * (min_v.z + max_v.z)
    dx = max(max_v.x - min_v.x, 1e-4)
    dy = max(max_v.y - min_v.y, 1e-4)
    dz = max(max_v.z - min_v.z, 1e-4)

    cam_data = bpy.data.cameras.new(nome)
    cam_data.type = "ORTHO"
    cam_data.sensor_fit = "HORIZONTAL" if dx >= dz else "VERTICAL"
    cam_data.ortho_scale = max(dx, dz)

    cam_obj = bpy.data.objects.new(nome, cam_data)
    colecao.objects.link(cam_obj)
    cam_obj.location = Vector((cx, max_v.y + max(dx, dy, dz) * 2.0 + 1.0, cz))
    cam_obj.rotation_euler = Vector((0.0, -1.0, 0.0)).to_track_quat("-Z", "Y").to_euler()
    return cam_obj, cam_data


def _projetar_uv_frontal_bmesh(
    obj,
    min_v: Vector,
    max_v: Vector,
    uv_bbox: tuple[float, float, float, float],
    nome_uv: str = "UV_Camera_Front",
) -> None:
    """Projeta UVs ortograficas frontais (+Y olhando -Y) diretamente em ``bmesh``."""
    u0, u1, v0, v1 = uv_bbox
    dx = max(max_v.x - min_v.x, 1e-6)
    dz = max(max_v.z - min_v.z, 1e-6)
    mw = obj.matrix_world

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.get(nome_uv) or bm.loops.layers.uv.new(nome_uv)
        for face in bm.faces:
            for loop in face.loops:
                co = mw @ loop.vert.co
                tx = (max_v.x - co.x) / dx
                tz = (co.z - min_v.z) / dz
                u = max(0.0, min(1.0, u0 + tx * (u1 - u0)))
                v = max(0.0, min(1.0, v0 + tz * (v1 - v0)))
                loop[uv_layer].uv = (u, v)
        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()


def _calcular_oclusao_frontal_bmesh(obj, nome_attr: str = "visivel_frente") -> str | None:
    """Marca vertices visiveis ao longo da direcao frontal (+Y) via raycast BVHTree."""
    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        return None
    mw = obj.matrix_world
    inv_rot = mw.to_3x3().inverted_safe()
    dir_local = (inv_rot @ Vector((0.0, 1.0, 0.0))).normalized()
    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    zs = [v.co.z for v in obj.data.vertices]
    diag = math.sqrt((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2 + (max(zs) - min(zs)) ** 2)
    eps = max(1e-4, diag * 0.004)
    if diag <= 1e-6:
        return None

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bvh = BVHTree.FromBMesh(bm)
        attr = obj.data.color_attributes.get(nome_attr)
        if attr is not None:
            obj.data.color_attributes.remove(attr)
        attr = obj.data.color_attributes.new(name=nome_attr, type="BYTE_COLOR", domain="POINT")
        for idx, v in enumerate(bm.verts):
            hit, _loc, _norm, _fidx = bvh.ray_cast(v.co + dir_local * eps, dir_local, diag * 2.0)
            val = 0.0 if hit is not None else 1.0
            attr.data[idx].color = (val, val, val, 1.0)
        obj.data.update()
        return nome_attr
    finally:
        bm.free()


def _criar_nodos_fator_frontal(nt, nome_uv: str, nome_visivel: str | None = None):
    """Cria nodos Dot-Product entre Normal de mundo e direcao frontal (+Y) com oclusao BVH."""
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    dot = nt.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = (0.0, 1.0, 0.0)
    nt.links.new(geom.outputs["Normal"], dot.inputs[0])

    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.clamp = True
    mr.inputs["From Min"].default_value = 0.02
    mr.inputs["From Max"].default_value = 0.26
    mr.inputs["To Min"].default_value = 0.0
    mr.inputs["To Max"].default_value = 1.0
    nt.links.new(dot.outputs["Value"], mr.inputs["Value"])

    fator_out = mr.outputs["Result"]
    if nome_visivel:
        vis_node = nt.nodes.new("ShaderNodeVertexColor")
        vis_node.layer_name = nome_visivel
        mul_vis = nt.nodes.new("ShaderNodeMath")
        mul_vis.operation = "MULTIPLY"
        mul_vis.use_clamp = True
        nt.links.new(fator_out, mul_vis.inputs[0])
        nt.links.new(vis_node.outputs["Color"], mul_vis.inputs[1])
        fator_out = mul_vis.outputs["Value"]

    uv_node = nt.nodes.new("ShaderNodeUVMap")
    uv_node.uv_map = nome_uv
    return uv_node, fator_out


def _criar_material_high_vc(
    nome_mat: str,
    nome_cor: str,
    img_origem=None,
    nome_uv: str = "UV_Camera_Front",
    calibrar_vc: bool = False,
    nome_visivel: str | None = None,
):
    """Material temporario para transferir ``color_attributes`` (e blend frontal 2D) no bake DIFFUSE."""
    mat = bpy.data.materials.new(nome_mat)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is not None:
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.78
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.0
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.18
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = nome_cor
    vc_out = vc.outputs["Color"]
    if calibrar_vc and img_origem is not None:
        # TripoSR gera COLOR_0 desaturado/claro em flancos; gamma+leve ajuste evita anel palido nas bordas.
        gamma = nt.nodes.new("ShaderNodeGamma")
        gamma.inputs["Gamma"].default_value = 1.45
        nt.links.new(vc_out, gamma.inputs["Color"])
        hsv = nt.nodes.new("ShaderNodeHueSaturation")
        hsv.inputs["Saturation"].default_value = 1.15
        hsv.inputs["Value"].default_value = 0.88
        nt.links.new(gamma.outputs["Color"], hsv.inputs["Color"])
        vc_out = hsv.outputs["Color"]

    if img_origem is None:
        nt.links.new(vc_out, bsdf.inputs["Base Color"])
        return mat

    uv_node, fator_frente = _criar_nodos_fator_frontal(nt, nome_uv, nome_visivel=nome_visivel)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img_origem
    tex.extension = "EXTEND"
    nt.links.new(uv_node.outputs["UV"], tex.inputs["Vector"])

    mul_alpha = nt.nodes.new("ShaderNodeMath")
    mul_alpha.operation = "MULTIPLY"
    mul_alpha.use_clamp = True
    nt.links.new(fator_frente, mul_alpha.inputs[0])
    nt.links.new(tex.outputs["Alpha"], mul_alpha.inputs[1])

    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    nt.links.new(mul_alpha.outputs["Value"], mix.inputs[0])
    nt.links.new(vc_out, mix.inputs[6])
    nt.links.new(tex.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    return mat


def _criar_material_high_hints_emit(
    nome_mat: str,
    img_met,
    img_rough,
    nome_uv: str = "UV_Camera_Front",
    nome_cor: str | None = None,
    img_origem=None,
    nome_visivel: str | None = None,
):
    """Shader EMIT temporario que empacota R=metallic, G=roughness, B=peso_pbr."""
    mat = bpy.data.materials.new(nome_mat)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is not None:
        nt.nodes.remove(bsdf)
    out = nt.nodes.get("Material Output")

    uv_node, fator_frente = _criar_nodos_fator_frontal(nt, nome_uv, nome_visivel=nome_visivel)
    fator_pbr = fator_frente
    if nome_cor and img_origem is not None:
        # Propaga hints PBR para flancos/traseira apenas onde COLOR_0 combina com o concept frontal
        vc_hint = nt.nodes.new("ShaderNodeVertexColor")
        vc_hint.layer_name = nome_cor
        tex_orig = nt.nodes.new("ShaderNodeTexImage")
        tex_orig.image = img_origem
        tex_orig.extension = "EXTEND"
        nt.links.new(uv_node.outputs["UV"], tex_orig.inputs["Vector"])

        dist_cor = nt.nodes.new("ShaderNodeVectorMath")
        dist_cor.operation = "DISTANCE"
        nt.links.new(vc_hint.outputs["Color"], dist_cor.inputs[0])
        nt.links.new(tex_orig.outputs["Color"], dist_cor.inputs[1])

        mr_sim = nt.nodes.new("ShaderNodeMapRange")
        mr_sim.clamp = True
        mr_sim.inputs["From Min"].default_value = 0.22
        mr_sim.inputs["From Max"].default_value = 0.50
        mr_sim.inputs["To Min"].default_value = 1.0
        mr_sim.inputs["To Max"].default_value = 0.0
        nt.links.new(dist_cor.outputs["Value"], mr_sim.inputs["Value"])

        max_pbr = nt.nodes.new("ShaderNodeMath")
        max_pbr.operation = "MAXIMUM"
        max_pbr.use_clamp = True
        nt.links.new(fator_frente, max_pbr.inputs[0])
        nt.links.new(mr_sim.outputs["Result"], max_pbr.inputs[1])
        fator_pbr = max_pbr.outputs["Value"]

    comb = nt.nodes.new("ShaderNodeCombineColor")
    comb.mode = "RGB"

    if img_met is not None:
        tex_m = nt.nodes.new("ShaderNodeTexImage")
        tex_m.image = img_met
        tex_m.extension = "EXTEND"
        nt.links.new(uv_node.outputs["UV"], tex_m.inputs["Vector"])

        mul_fa = nt.nodes.new("ShaderNodeMath")
        mul_fa.operation = "MULTIPLY"
        mul_fa.use_clamp = True
        nt.links.new(fator_pbr, mul_fa.inputs[0])
        nt.links.new(tex_m.outputs["Alpha"], mul_fa.inputs[1])

        mul_m = nt.nodes.new("ShaderNodeMath")
        mul_m.operation = "MULTIPLY"
        mul_m.use_clamp = True
        nt.links.new(tex_m.outputs["Color"], mul_m.inputs[0])
        nt.links.new(mul_fa.outputs["Value"], mul_m.inputs[1])
        nt.links.new(mul_m.outputs["Value"], comb.inputs[0])
    else:
        comb.inputs[0].default_value = 0.0

    if img_rough is not None:
        tex_r = nt.nodes.new("ShaderNodeTexImage")
        tex_r.image = img_rough
        tex_r.extension = "EXTEND"
        nt.links.new(uv_node.outputs["UV"], tex_r.inputs["Vector"])
        nt.links.new(tex_r.outputs["Color"], comb.inputs[1])

        mul_r = nt.nodes.new("ShaderNodeMath")
        mul_r.operation = "MULTIPLY"
        mul_r.use_clamp = True
        nt.links.new(fator_pbr, mul_r.inputs[0])
        nt.links.new(tex_r.outputs["Alpha"], mul_r.inputs[1])
        nt.links.new(mul_r.outputs["Value"], comb.inputs[2])
    else:
        comb.inputs[1].default_value = 0.0
        comb.inputs[2].default_value = 0.0

    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 1.0
    nt.links.new(comb.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


def _criar_material_alvo_bake(nome_mat: str):
    """Material temporario no objeto low-poly com o ``ShaderNodeTexImage`` alvo ativo."""
    mat = bpy.data.materials.new(nome_mat)
    mat.use_nodes = True
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.select = True
    nt.nodes.active = tex
    return mat, tex


def _salvar_e_recarregar_png(img, caminho: str, colorspace: str, cena):
    """Salva PNG RGB 8-bit com compressao 100 e recarrega do disco para embutir comprimido no GLB."""
    img.save_render(filepath=caminho, scene=cena)
    bpy.data.images.remove(img)
    recarregada = bpy.data.images.load(caminho, check_existing=False)
    recarregada.colorspace_settings.name = colorspace
    return recarregada


def _empacotar_orm(
    img_ao,
    nome_img: str,
    px: int,
    img_hints=None,
    piso_dieletrico_rough: float = 0.0,
    metallic_base: float = 0.0,
    roughness_base: float | None = None,
):
    """Empacota R=AO, G=Roughness, B=Metallic via ``array('f')``."""
    total_floats = px * px * 4
    ao_buf = array("f", [0.0]) * total_floats
    img_ao.pixels.foreach_get(ao_buf)

    hints_buf = None
    if img_hints is not None:
        hints_buf = array("f", [0.0]) * total_floats
        img_hints.pixels.foreach_get(hints_buf)

    met_padrao = max(0.0, min(1.0, float(metallic_base)))
    orm_buf = array("f", [0.0]) * total_floats
    for i in range(0, total_floats, 4):
        ao = ao_buf[i]
        if ao < 0.0:
            ao = 0.0
        elif ao > 1.0:
            ao = 1.0
        rough_ao = 0.85 - 0.25 * (1.0 - ao)
        if rough_ao < 0.50:
            rough_ao = 0.50
        elif rough_ao > 0.90:
            rough_ao = 0.90
        if roughness_base is not None:
            rb = max(0.04, min(1.0, float(roughness_base)))
            rough_ao = 0.65 * rb + 0.35 * rough_ao

        if hints_buf is not None:
            met = hints_buf[i]
            if met < 0.0:
                met = 0.0
            elif met > 1.0:
                met = 1.0
            rough_hint = hints_buf[i + 1]
            if rough_hint < 0.04:
                rough_hint = 0.04
            elif rough_hint > 1.0:
                rough_hint = 1.0
            front_w = hints_buf[i + 2]
            if front_w < 0.0:
                front_w = 0.0
            elif front_w > 1.0:
                front_w = 1.0
            rough = rough_ao * (1.0 - front_w) + rough_hint * front_w
            if piso_dieletrico_rough > 0.0 and met < 0.1 and rough < piso_dieletrico_rough:
                rough = piso_dieletrico_rough
            if rough < 0.04:
                rough = 0.04
            elif rough > 1.0:
                rough = 1.0
        else:
            rough = rough_ao
            met = met_padrao

        orm_buf[i] = ao
        orm_buf[i + 1] = rough
        orm_buf[i + 2] = met
        orm_buf[i + 3] = 1.0

    img_orm = bpy.data.images.new(nome_img, width=px, height=px, alpha=False)
    img_orm.colorspace_settings.name = "Non-Color"
    img_orm.pixels.foreach_set(orm_buf)
    return img_orm


def _extrair_canais_roblox(img_orm, saida_dir: str, nome_base: str, px: int, cena) -> list[dict]:
    """Salva PNGs individuais Non-Color de Roughness (G) e Metallic (B) para Roblox SurfaceAppearance."""
    total_floats = px * px * 4
    orm_buf = array("f", [0.0]) * total_floats
    img_orm.pixels.foreach_get(orm_buf)
    r_buf = array("f", [0.0]) * total_floats
    m_buf = array("f", [0.0]) * total_floats
    for i in range(0, total_floats, 4):
        rv = orm_buf[i + 1]
        mv = orm_buf[i + 2]
        r_buf[i] = r_buf[i + 1] = r_buf[i + 2] = rv
        r_buf[i + 3] = 1.0
        m_buf[i] = m_buf[i + 1] = m_buf[i + 2] = mv
        m_buf[i + 3] = 1.0

    saidas: list[dict] = []
    for sufixo, papel, buf in (
        ("roughness", "roughness", r_buf),
        ("metallic", "metallic", m_buf),
    ):
        nome = f"{nome_base}_{sufixo}.png"
        caminho = os.path.join(saida_dir, nome)
        img_tmp = bpy.data.images.new(f"{nome_base}_{sufixo}_tmp", width=px, height=px, alpha=False)
        img_tmp.colorspace_settings.name = "Non-Color"
        img_tmp.pixels.foreach_set(buf)
        img_tmp.save_render(filepath=caminho, scene=cena)
        bpy.data.images.remove(img_tmp)
        saidas.append({"caminho": nome, "papel": papel, "bytes": os.path.getsize(caminho)})
    return saidas


def _obter_grupo_gltf_occlusion():
    """Obtem ou cria o node group ``glTF Material Output`` com socket ``Occlusion``."""
    ng = bpy.data.node_groups.get("glTF Material Output")
    if ng is None:
        ng = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
    existe = any(
        getattr(item, "in_out", None) == "INPUT" and item.name == "Occlusion"
        for item in ng.interface.items_tree
    )
    if not existe:
        sock = ng.interface.new_socket(
            name="Occlusion", in_out="INPUT", socket_type="NodeSocketFloat"
        )
        sock.default_value = 1.0
    return ng


def _criar_material_pbr_gltf(nome_mat: str, img_bc, img_nm, img_orm):
    """Cria o material PBR final compativel com o exportador glTF 2.0 do Blender 4.2."""
    mat = bpy.data.materials.new(nome_mat)
    mat.use_nodes = True
    mat.use_backface_culling = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is not None:
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.78
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.18

    tex_bc = nt.nodes.new("ShaderNodeTexImage")
    tex_bc.image = img_bc
    tex_bc.location = (-440, 300)
    nt.links.new(tex_bc.outputs["Color"], bsdf.inputs["Base Color"])

    tex_nm = nt.nodes.new("ShaderNodeTexImage")
    tex_nm.image = img_nm
    tex_nm.location = (-700, -300)
    normal_map = nt.nodes.new("ShaderNodeNormalMap")
    normal_map.space = "TANGENT"
    normal_map.location = (-380, -300)
    nt.links.new(tex_nm.outputs["Color"], normal_map.inputs["Color"])
    nt.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])

    tex_orm = nt.nodes.new("ShaderNodeTexImage")
    tex_orm.image = img_orm
    tex_orm.location = (-700, 0)
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    sep.mode = "RGB"
    sep.location = (-380, 0)
    nt.links.new(tex_orm.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])

    ng = _obter_grupo_gltf_occlusion()
    gltf_out = nt.nodes.new("ShaderNodeGroup")
    gltf_out.node_tree = ng
    gltf_out.location = (220, -160)
    nt.links.new(sep.outputs["Red"], gltf_out.inputs["Occlusion"])

    return mat


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
    cena.render.image_settings.compression = 100


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
    """Alisa ondas de Marching Cubes em malhas organicas sem encolher volume."""
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


def _corrigir_normais_invertidas(img_nm, px: int) -> int:
    """Corrige texels com normal Z tangente invertida (B <= 0.505) de ray-miss."""
    total_floats = px * px * 4
    buf = array("f", [0.0]) * total_floats
    img_nm.pixels.foreach_get(buf)
    corrigidos = 0
    for i in range(0, total_floats, 4):
        if buf[i + 2] <= 0.505:
            nx = (buf[i] - 0.5) * 2.0
            ny = (buf[i + 1] - 0.5) * 2.0
            nz = max(0.35, 0.5 - buf[i + 2])
            comp = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            buf[i] = 0.5 + 0.5 * (nx / comp)
            buf[i + 1] = 0.5 + 0.5 * (ny / comp)
            buf[i + 2] = 0.5 + 0.5 * (nz / comp)
            corrigidos += 1
    if corrigidos:
        img_nm.pixels.foreach_set(buf)
    return corrigidos


def _adicionar_detalhe_sobel_normal(
    img_nm, img_bc, px_nm: int, px_bc: int, forca: float = 0.16
) -> None:
    """Injeta micro-relevo sutil de luminancia Sobel do BaseColor no normal map tangente."""
    if px_nm < 16 or px_bc < 16:
        return
    bc_buf = array("f", [0.0]) * (px_bc * px_bc * 4)
    img_bc.pixels.foreach_get(bc_buf)
    lum = [0.0] * (px_nm * px_nm)
    escala = float(px_bc) / float(px_nm)
    for y in range(px_nm):
        sy = min(px_bc - 1, int(y * escala))
        row_off = sy * px_bc
        dst_off = y * px_nm
        for x in range(px_nm):
            sx = min(px_bc - 1, int(x * escala))
            off = (row_off + sx) * 4
            lum[dst_off + x] = 0.2126 * bc_buf[off] + 0.7152 * bc_buf[off + 1] + 0.0722 * bc_buf[off + 2]

    nm_buf = array("f", [0.0]) * (px_nm * px_nm * 4)
    img_nm.pixels.foreach_get(nm_buf)
    for y in range(1, px_nm - 1):
        rm = (y - 1) * px_nm
        rc = y * px_nm
        rp = (y + 1) * px_nm
        for x in range(1, px_nm - 1):
            gx = (
                (lum[rm + x + 1] + 2.0 * lum[rc + x + 1] + lum[rp + x + 1])
                - (lum[rm + x - 1] + 2.0 * lum[rc + x - 1] + lum[rp + x - 1])
            )
            gy = (
                (lum[rp + x - 1] + 2.0 * lum[rp + x] + lum[rp + x + 1])
                - (lum[rm + x - 1] + 2.0 * lum[rm + x] + lum[rm + x + 1])
            )
            off = (rc + x) * 4
            nx = (nm_buf[off] - 0.5) * 2.0 - gx * forca
            ny = (nm_buf[off + 1] - 0.5) * 2.0 - gy * forca
            nz = max(0.25, (nm_buf[off + 2] - 0.5) * 2.0)
            comp = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            nm_buf[off] = 0.5 + 0.5 * (nx / comp)
            nm_buf[off + 1] = 0.5 + 0.5 * (ny / comp)
            nm_buf[off + 2] = 0.5 + 0.5 * (nz / comp)
    img_nm.pixels.foreach_set(nm_buf)


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
            except Exception:
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


def _extrair_escalares_pbr_material(mat) -> tuple[float, float | None]:
    """Le defaults de Metallic e Roughness de um material existente sem grampear Metallic=0."""
    if mat is None or not getattr(mat, "use_nodes", False) or mat.node_tree is None:
        return 0.0, None
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return 0.0, None
    met = 0.0
    rough = None
    if "Metallic" in bsdf.inputs:
        met = float(bsdf.inputs["Metallic"].default_value)
    if "Roughness" in bsdf.inputs:
        rough = float(bsdf.inputs["Roughness"].default_value)
    return max(0.0, min(1.0, met)), rough


def _aplicar_opcoes_especiais_bsdf(mat, cfg_p: dict) -> None:
    """Propaga propriedades PBR estendidas (transmissao, IOR, alpha, emissao) ao Principled BSDF."""
    if mat is None or not cfg_p:
        return
    if cfg_p.get("blend_method") and hasattr(mat, "blend_method"):
        mat.blend_method = str(cfg_p["blend_method"])
    nt = getattr(mat, "node_tree", None)
    if nt is None:
        return
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = float(
            0.5 * (cfg_p.get("metallic_min", 0.0) + cfg_p.get("metallic_max", 0.0))
        )
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = float(
            0.5 * (cfg_p.get("roughness_min", 0.5) + cfg_p.get("roughness_max", 0.7))
        )
    if "transmission" in cfg_p and "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = float(cfg_p["transmission"])
    if "ior" in cfg_p and "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = float(cfg_p["ior"])
    if "alpha" in cfg_p and "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = float(cfg_p["alpha"])
    if "emission_color" in cfg_p and "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = tuple(cfg_p["emission_color"])
    if "emission_strength" in cfg_p and "Emission Strength" in bsdf.inputs:
        bsdf.inputs["Emission Strength"].default_value = float(cfg_p["emission_strength"])


def executar_bake_high_low(
    obj,
    saida_dir: str,
    nome_base: str,
    px: int,
    limite_triangulos: int,
    reparo_fn,
    decimar_fn,
    suavizar_fn,
    uv_fn,
    origem_textura: str | None = None,
    metallic_hint_png: str | None = None,
    roughness_hint_png: str | None = None,
    proteger_superficie: bool = False,
    perfil_nome: str | None = None,
    material_procedural: str | None = None,
    permitir_sem_cor_vertice: bool = False,
    detalhe_alto: dict | None = None,
    pbr_zonas: list[dict] | None = None,
    px_sub: int | None = None,
    qualidade: str | None = None,
) -> dict:
    """Executa bake PBR High->Low (BaseColor, Normal, ORM) e atribui material glTF PBR em ``obj``."""
    tem_cor_vertice = bool(
        obj is not None and obj.data is not None and len(obj.data.color_attributes) > 0
    )
    preset_proc = str(material_procedural or "").strip().lower()
    tem_procedural = bool(preset_proc)
    tem_zonas = bool(pbr_zonas)
    tem_detalhe_alto = bool(isinstance(detalhe_alto, dict) and detalhe_alto.get("ativo", True))
    tem_mat_uv = bool(
        (permitir_sem_cor_vertice or tem_zonas or tem_detalhe_alto)
        and obj is not None
        and obj.data is not None
        and (
            len(obj.data.uv_layers) > 0
            or len(obj.data.materials) > 0
            or tem_zonas
            or tem_detalhe_alto
        )
    )
    if obj is None or obj.data is None or (
        not tem_cor_vertice and not tem_procedural and not tem_zonas and not tem_mat_uv
    ):
        raise RuntimeError("malha sem atributo de cor por vertice para assar PBR")

    os.makedirs(saida_dir, exist_ok=True)
    px = max(64, min(int(px), 4096))
    if px_sub is not None and int(px_sub) > 0:
        px_sub = max(64, min(int(px_sub), px))
        if px >= 1024 and px_sub < 1024:
            px_sub = 1024
    else:
        q_low = str(qualidade or "").strip().lower()
        if px >= 4096:
            px_sub = 4096 if q_low == "ultra" else 2048
        elif px >= 2048:
            px_sub = 2048 if q_low == "ultra" else 1024
        elif px >= 1024:
            px_sub = 1024
        else:
            px_sub = px

    if (
        len(obj.data.materials) > 1
        and not tem_cor_vertice
        and not tem_zonas
        and not str(perfil_nome or "").startswith("roblox")
    ):
        tris_high = _contar_triangulos(obj)
        decimar_fn(obj, int(limite_triangulos))
        info_reparo = reparo_fn(obj)
        if _contar_triangulos(obj) > int(limite_triangulos):
            decimar_fn(obj, max(50, int(int(limite_triangulos) * 0.97)))
            info_reparo = reparo_fn(obj)
        info_smooth = suavizar_fn(obj)
        info_uv = uv_fn(obj)
        if not obj.data.uv_layers:
            raise RuntimeError("malha low-poly sem camada UV apos uv_fn")
        tris_low = _contar_triangulos(obj)
        bpy.context.view_layer.update()
        diag = _bbox_diag(obj)
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        return {
            "textura_px": px,
            "normal_px": px_sub,
            "orm_px": px_sub,
            "bake": {
                "textura_px": px,
                "normal_px": px_sub,
                "orm_px": px_sub,
                "cor_atributo": "multimaterial",
                "material_procedural": preset_proc or None,
                "dispositivo_cycles": "PRESERVADO_MULTIMATERIAL",
                "samples": 0,
                "bbox_diag": round(diag, 6),
                "cage_extrusion": 0.0,
                "triangulos_high": tris_high,
                "triangulos_low": tris_low,
                "reparo": info_reparo,
                "smooth": info_smooth,
                "uv": info_uv,
                "origem_textura_aplicada": False,
                "metallic_hint_aplicado": False,
                "roughness_hint_aplicado": False,
                "multimaterial_preservado": True,
                "materiais": len(obj.data.materials),
                "png_bytes": 0,
                "baseColor_bytes": 0,
                "normal_bytes": 0,
                "orm_bytes": 0,
            },
            "arquivos_textura": [],
        }

    if tem_cor_vertice:
        ativo_cor = obj.data.color_attributes.active_color
        nome_cor = (
            ativo_cor.name if ativo_cor is not None else obj.data.color_attributes[0].name
        )
    elif tem_zonas:
        nome_cor = f"pbr_zonas:{len(pbr_zonas or [])}"
    elif tem_procedural:
        nome_cor = f"procedural:{preset_proc}"
    else:
        nome_cor = "uv_material"
    tris_high = _contar_triangulos(obj)

    high_mesh = obj.data.copy()
    high_mesh.name = f"{nome_base}_high_mesh"
    high_obj = bpy.data.objects.new(f"{nome_base}_high", high_mesh)
    high_obj.matrix_world = obj.matrix_world.copy()
    colecao = obj.users_collection[0] if obj.users_collection else bpy.context.scene.collection
    colecao.objects.link(high_obj)

    high_mat = None
    high_hints_mat = None
    low_bake_mat = None
    cam_obj = None
    cam_data = None
    img_origem = None
    img_met = None
    img_rough = None
    img_hints_tmp = None
    info_detalhe_alto: dict = {"aplicado": False}
    cena = bpy.context.scene

    # Guarda estado de render/cor para restaurar ao sair (evita side-effects na cena).
    estado_anterior = _capturar_estado_cena(cena)

    try:
        if tem_detalhe_alto:
            info_detalhe_alto = preparar_high_mesh_detalhe_alto(high_obj, detalhe_alto)
            tris_high = int(info_detalhe_alto.get("tris_high_enriquecido") or _contar_triangulos(high_obj))
        if proteger_superficie and tris_high >= 4000 and not tem_detalhe_alto:
            _suavizar_high_taubin(high_obj, iteracoes=3, fator=0.45)
        suavizar_fn(high_obj)

        if not tem_procedural:
            if origem_textura and os.path.isfile(origem_textura):
                img_origem = bpy.data.images.load(origem_textura, check_existing=False)
                img_origem.colorspace_settings.name = "sRGB"
            if metallic_hint_png and os.path.isfile(metallic_hint_png):
                img_met = bpy.data.images.load(metallic_hint_png, check_existing=False)
                img_met.colorspace_settings.name = "Non-Color"
            if roughness_hint_png and os.path.isfile(roughness_hint_png):
                img_rough = bpy.data.images.load(roughness_hint_png, check_existing=False)
                img_rough.colorspace_settings.name = "Non-Color"

        nome_visivel = None
        if not tem_zonas and (img_origem is not None or img_met is not None or img_rough is not None):
            min_v, max_v = _calcular_bbox_mundo(high_obj)
            cam_obj, cam_data = _criar_camera_ortografica_frontal(
                f"{nome_base}_cam_proj_tmp", min_v, max_v, colecao
            )
            img_ref = img_origem or img_met or img_rough
            uv_bbox = _detectar_bbox_uv_foreground(img_ref)
            _projetar_uv_frontal_bmesh(high_obj, min_v, max_v, uv_bbox, "UV_Camera_Front")
            nome_visivel = _calcular_oclusao_frontal_bmesh(high_obj)

        decimar_fn(obj, int(limite_triangulos))
        info_reparo = reparo_fn(obj)
        if _contar_triangulos(obj) > int(limite_triangulos):
            decimar_fn(obj, max(50, int(int(limite_triangulos) * 0.97)))
            info_reparo = reparo_fn(obj)
        info_smooth = suavizar_fn(obj)
        info_uv = uv_fn(obj)
        if not obj.data.uv_layers:
            raise RuntimeError("malha low-poly sem camada UV apos uv_fn")
        if tem_zonas and not high_obj.data.uv_layers:
            uv_fn(high_obj)
        tris_low = _contar_triangulos(obj)

        bpy.context.view_layer.update()
        diag = _bbox_diag(obj)
        if proteger_superficie:
            cage_extrusion = max(0.010, 0.014 * diag)
            max_ray_dist = max(0.025, 0.036 * diag)
        else:
            cage_extrusion = max(0.02, 0.03 * diag)
            max_ray_dist = max(0.025, 0.06 * diag)

        proc_mod = None
        usar_emit_proc = False
        met_escalar_orig = 0.0
        rough_escalar_orig: float | None = None
        if tem_zonas:
            proc_mod = __import__("procedural_pbr")
            usar_emit_proc = True
            ao_forca = float(
                (detalhe_alto or {}).get("ao_cavidade_forca", 0.35)
                if isinstance(detalhe_alto, dict)
                else 0.35
            )
            high_mat = proc_mod.construir_shader_pbr_zonas_blender(
                f"{nome_base}_high_zonas_tmp",
                list(pbr_zonas or []),
                presets_pbr=proc_mod.PRESETS_PBR,
                img_paleta=img_origem,
                nome_cor_vertice=nome_cor if tem_cor_vertice else None,
                ao_cavidade_forca=ao_forca,
            )
            high_obj.data.materials.clear()
            high_obj.data.materials.append(high_mat)
        elif tem_procedural:
            proc_mod = __import__("procedural_pbr")
            usar_emit_proc = True
            high_mat = proc_mod.criar_material_procedural(
                preset_proc, nome_mat=f"{nome_base}_high_proc_tmp"
            )
            high_obj.data.materials.clear()
            high_obj.data.materials.append(high_mat)
        elif tem_cor_vertice:
            high_mat = _criar_material_high_vc(
                f"{nome_base}_high_bake_tmp",
                nome_cor,
                img_origem=img_origem,
                nome_uv="UV_Camera_Front",
                calibrar_vc=proteger_superficie,
                nome_visivel=nome_visivel,
            )
            high_obj.data.materials.clear()
            high_obj.data.materials.append(high_mat)
        else:
            mat_src = high_obj.data.materials[0] if high_obj.data.materials else None
            met_escalar_orig, rough_escalar_orig = _extrair_escalares_pbr_material(mat_src)
            if mat_src is not None:
                high_mat = mat_src.copy()
                high_mat.name = f"{nome_base}_high_mat_tmp"
                high_obj.data.materials.clear()
                high_obj.data.materials.append(high_mat)
            elif img_origem is not None:
                high_mat = bpy.data.materials.new(f"{nome_base}_high_tex_tmp")
                high_mat.use_nodes = True
                nt_h = high_mat.node_tree
                bsdf_h = nt_h.nodes.get("Principled BSDF")
                tex_h = nt_h.nodes.new("ShaderNodeTexImage")
                tex_h.image = img_origem
                nt_h.links.new(tex_h.outputs["Color"], bsdf_h.inputs["Base Color"])
                high_obj.data.materials.clear()
                high_obj.data.materials.append(high_mat)
            else:
                high_mat = bpy.data.materials.new(f"{nome_base}_high_def_tmp")
                high_mat.use_nodes = True
                high_obj.data.materials.clear()
                high_obj.data.materials.append(high_mat)

        low_bake_mat, tex_bake = _criar_material_alvo_bake(f"{nome_base}_low_bake_tmp")
        obj.data.materials.clear()
        obj.data.materials.append(low_bake_mat)

        dispositivo_cycles = _configurar_dispositivo_cycles(cena, preferir_gpu=True)
        samples_bake = 8 if (usar_emit_proc or permitir_sem_cor_vertice) else 1
        samples_ao = 8 if (usar_emit_proc or permitir_sem_cor_vertice) else 4
        cena.cycles.use_denoising = False
        cena.render.bake.use_selected_to_active = True
        cena.render.bake.use_cage = False
        cena.render.bake.cage_extrusion = cage_extrusion
        cena.render.bake.max_ray_distance = max_ray_dist
        cena.render.bake.use_clear = True
        _configurar_render_png_linear(cena)

        # 1. BaseColor em `px`
        nome_bc = f"{nome_base}_baseColor.png"
        path_bc = os.path.join(saida_dir, nome_bc)
        img_bc_tmp = bpy.data.images.new(f"{nome_base}_bc_tmp", width=px, height=px, alpha=False)
        img_bc_tmp.colorspace_settings.name = "sRGB"
        tex_bake.image = img_bc_tmp
        tex_bake.select = True
        low_bake_mat.node_tree.nodes.active = tex_bake

        cena.cycles.samples = samples_bake
        cena.render.bake.margin = max(4, px // 128)
        _selecionar_high_para_low(high_obj, obj)
        if usar_emit_proc and proc_mod is not None:
            proc_mod.configurar_saida_albedo_emit(high_mat)
            _executar_bake_seguro(cena, type="EMIT")
            proc_mod.configurar_saida_pbr_bsdf(high_mat)
        else:
            bsdf_h = high_mat.node_tree.nodes.get("Principled BSDF") if high_mat else None
            met_ant = None
            if bsdf_h is not None and "Metallic" in bsdf_h.inputs:
                met_ant = float(bsdf_h.inputs["Metallic"].default_value)
                bsdf_h.inputs["Metallic"].default_value = 0.0
            cena.render.bake.use_pass_direct = False
            cena.render.bake.use_pass_indirect = False
            cena.render.bake.use_pass_color = True
            _executar_bake_seguro(cena, type="DIFFUSE")
            if bsdf_h is not None and met_ant is not None:
                bsdf_h.inputs["Metallic"].default_value = met_ant
        img_bc = _salvar_e_recarregar_png(img_bc_tmp, path_bc, "sRGB", cena)

        # 2. Normal (TANGENT) em `px_sub`
        nome_nm = f"{nome_base}_normal.png"
        path_nm = os.path.join(saida_dir, nome_nm)
        img_nm_tmp = bpy.data.images.new(
            f"{nome_base}_nm_tmp", width=px_sub, height=px_sub, alpha=False
        )
        img_nm_tmp.colorspace_settings.name = "Non-Color"
        tex_bake.image = img_nm_tmp
        tex_bake.select = True
        low_bake_mat.node_tree.nodes.active = tex_bake

        cena.cycles.samples = samples_bake
        cena.render.bake.normal_space = "TANGENT"
        cena.render.bake.normal_r = "POS_X"
        cena.render.bake.normal_g = "POS_Y"
        cena.render.bake.normal_b = "POS_Z"
        cena.render.bake.margin = max(4, px_sub // 128)
        _selecionar_high_para_low(high_obj, obj)
        _executar_bake_seguro(cena, type="NORMAL")
        _corrigir_normais_invertidas(img_nm_tmp, px_sub)
        if not usar_emit_proc:
            _adicionar_detalhe_sobel_normal(img_nm_tmp, img_bc, px_sub, px)
        img_nm = _salvar_e_recarregar_png(img_nm_tmp, path_nm, "Non-Color", cena)

        # 3. ORM via AO + hints opcionais/procedurais em `px_sub`
        nome_orm = f"{nome_base}_orm.png"
        path_orm = os.path.join(saida_dir, nome_orm)
        img_ao_tmp = bpy.data.images.new(
            f"{nome_base}_ao_tmp", width=px_sub, height=px_sub, alpha=False
        )
        img_ao_tmp.colorspace_settings.name = "Non-Color"
        tex_bake.image = img_ao_tmp
        tex_bake.select = True
        low_bake_mat.node_tree.nodes.active = tex_bake

        cena.cycles.samples = samples_ao
        cena.render.bake.margin = max(4, px_sub // 128)
        _selecionar_high_para_low(high_obj, obj)
        _executar_bake_seguro(cena, type="AO")

        if usar_emit_proc and proc_mod is not None:
            proc_mod.configurar_saida_orm_hints_emit(high_mat)
            img_hints_tmp = bpy.data.images.new(
                f"{nome_base}_hints_tmp", width=px_sub, height=px_sub, alpha=False
            )
            img_hints_tmp.colorspace_settings.name = "Non-Color"
            tex_bake.image = img_hints_tmp
            tex_bake.select = True
            low_bake_mat.node_tree.nodes.active = tex_bake
            cena.cycles.samples = samples_bake
            cena.render.bake.margin = max(4, px_sub // 128)
            _selecionar_high_para_low(high_obj, obj)
            _executar_bake_seguro(cena, type="EMIT")
            proc_mod.configurar_saida_pbr_bsdf(high_mat)
        elif img_met is not None or img_rough is not None:
            high_hints_mat = _criar_material_high_hints_emit(
                f"{nome_base}_high_hints_tmp",
                img_met,
                img_rough,
                nome_uv="UV_Camera_Front",
                nome_cor=nome_cor if tem_cor_vertice else None,
                img_origem=img_origem,
                nome_visivel=nome_visivel,
            )
            high_obj.data.materials.clear()
            high_obj.data.materials.append(high_hints_mat)

            img_hints_tmp = bpy.data.images.new(
                f"{nome_base}_hints_tmp", width=px_sub, height=px_sub, alpha=False
            )
            img_hints_tmp.colorspace_settings.name = "Non-Color"
            tex_bake.image = img_hints_tmp
            tex_bake.select = True
            low_bake_mat.node_tree.nodes.active = tex_bake

            cena.cycles.samples = 1
            cena.render.bake.margin = max(4, px_sub // 128)
            _selecionar_high_para_low(high_obj, obj)
            _executar_bake_seguro(cena, type="EMIT")

        img_orm_tmp = _empacotar_orm(
            img_ao_tmp,
            f"{nome_base}_orm_tmp",
            px_sub,
            img_hints=img_hints_tmp,
            piso_dieletrico_rough=0.68 if (proteger_superficie and not usar_emit_proc) else 0.0,
            metallic_base=met_escalar_orig,
            roughness_base=rough_escalar_orig,
        )
        bpy.data.images.remove(img_ao_tmp)
        canais_separados = _extrair_canais_roblox(img_orm_tmp, saida_dir, nome_base, px_sub, cena)
        extras_roblox = (
            canais_separados
            if (str(perfil_nome or "").startswith("roblox") or tem_zonas or tem_detalhe_alto)
            else []
        )
        img_orm = _salvar_e_recarregar_png(img_orm_tmp, path_orm, "Non-Color", cena)

        for atributo in list(obj.data.color_attributes):
            obj.data.color_attributes.remove(atributo)

        obj.data.materials.clear()
        mat_final = _criar_material_pbr_gltf(f"{nome_base}_pbr", img_bc, img_nm, img_orm)
        if tem_procedural and proc_mod is not None:
            cfg_p = proc_mod.PRESETS_PBR.get(preset_proc, {})
            _aplicar_opcoes_especiais_bsdf(mat_final, cfg_p)
        elif met_escalar_orig > 0.0:
            bsdf_f = mat_final.node_tree.nodes.get("Principled BSDF")
            if bsdf_f is not None and "Metallic" in bsdf_f.inputs:
                bsdf_f.inputs["Metallic"].default_value = met_escalar_orig
        obj.data.materials.append(mat_final)

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    finally:
        if cam_obj is not None and cam_obj.name in bpy.data.objects:
            bpy.data.objects.remove(cam_obj, do_unlink=True)
        if cam_data is not None and cam_data.name in bpy.data.cameras and cam_data.users == 0:
            bpy.data.cameras.remove(cam_data)
        if high_obj is not None and high_obj.name in bpy.data.objects:
            bpy.data.objects.remove(high_obj, do_unlink=True)
        if high_mesh is not None and high_mesh.name in bpy.data.meshes and high_mesh.users == 0:
            bpy.data.meshes.remove(high_mesh)
        for mat_tmp in (high_mat, high_hints_mat, low_bake_mat):
            if mat_tmp is not None and mat_tmp.name in bpy.data.materials and mat_tmp.users == 0:
                bpy.data.materials.remove(mat_tmp)
        for img_tmp in (img_origem, img_met, img_rough, img_hints_tmp):
            if img_tmp is not None and img_tmp.name in bpy.data.images and img_tmp.users == 0:
                bpy.data.images.remove(img_tmp)

        _restaurar_estado_cena(cena, estado_anterior)

    bytes_bc = os.path.getsize(path_bc)
    bytes_nm = os.path.getsize(path_nm)
    bytes_orm = os.path.getsize(path_orm)

    return {
        "textura_px": px,
        "normal_px": px_sub,
        "orm_px": px_sub,
        "bake": {
            "textura_px": px,
            "normal_px": px_sub,
            "orm_px": px_sub,
            "cor_atributo": nome_cor,
            "material_procedural": preset_proc or None,
            "pbr_zonas": len(pbr_zonas) if tem_zonas else 0,
            "detalhe_alto": info_detalhe_alto,
            "dispositivo_cycles": dispositivo_cycles,
            "samples": samples_bake,
            "bbox_diag": round(diag, 6),
            "cage_extrusion": round(cage_extrusion, 6),
            "triangulos_high": tris_high,
            "triangulos_low": tris_low,
            "reparo": info_reparo,
            "smooth": info_smooth,
            "uv": info_uv,
            "origem_textura_aplicada": bool(img_origem is not None),
            "metallic_hint_aplicado": bool(img_met is not None or usar_emit_proc),
            "roughness_hint_aplicado": bool(img_rough is not None or usar_emit_proc),
            "png_bytes": bytes_bc,
            "baseColor_bytes": bytes_bc,
            "normal_bytes": bytes_nm,
            "orm_bytes": bytes_orm,
        },
        "arquivos_textura": [
            {"caminho": nome_bc, "papel": "textura", "bytes": bytes_bc},
            {"caminho": nome_nm, "papel": "normal", "bytes": bytes_nm},
            {"caminho": nome_orm, "papel": "orm", "bytes": bytes_orm},
            *extras_roblox,
        ],
    }


def aplicar_hints_orm_em_material(
    obj,
    saida_dir: str,
    nome_base: str,
    px: int,
    metallic_hint_png: str | None = None,
    roughness_hint_png: str | None = None,
    perfil_nome: str | None = None,
) -> dict | None:
    """Assa hints opcionais de ORM em objeto que ja tem UVMap e material (ex.: extrude_2d)."""
    tem_met = bool(metallic_hint_png and os.path.isfile(metallic_hint_png))
    tem_rough = bool(roughness_hint_png and os.path.isfile(roughness_hint_png))
    if not tem_met and not tem_rough:
        return None
    if obj is None or not obj.data.materials or not obj.data.uv_layers:
        return None

    os.makedirs(saida_dir, exist_ok=True)
    px_sub = max(64, min(int(px), 1024 if int(px) >= 1024 else int(px)))
    cena = bpy.context.scene
    estado_anterior = _capturar_estado_cena(cena)

    mat_orig = obj.data.materials[0]
    uv_orig = obj.data.uv_layers[0].name
    img_met = None
    img_rough = None
    img_ao_tmp = None
    img_hints_tmp = None
    bake_mat = None

    try:
        if tem_met:
            img_met = bpy.data.images.load(metallic_hint_png, check_existing=False)
            img_met.colorspace_settings.name = "Non-Color"
        if tem_rough:
            img_rough = bpy.data.images.load(roughness_hint_png, check_existing=False)
            img_rough.colorspace_settings.name = "Non-Color"

        bake_mat, tex_bake = _criar_material_alvo_bake(f"{nome_base}_ext_hints_tmp")
        nt = bake_mat.node_tree
        out = nt.nodes.get("Material Output")
        uv_node = nt.nodes.new("ShaderNodeUVMap")
        uv_node.uv_map = uv_orig
        comb = nt.nodes.new("ShaderNodeCombineColor")
        comb.mode = "RGB"
        if img_met is not None:
            tex_m = nt.nodes.new("ShaderNodeTexImage")
            tex_m.image = img_met
            tex_m.extension = "EXTEND"
            nt.links.new(uv_node.outputs["UV"], tex_m.inputs["Vector"])
            nt.links.new(tex_m.outputs["Color"], comb.inputs[0])
        else:
            comb.inputs[0].default_value = 0.0
        if img_rough is not None:
            tex_r = nt.nodes.new("ShaderNodeTexImage")
            tex_r.image = img_rough
            tex_r.extension = "EXTEND"
            nt.links.new(uv_node.outputs["UV"], tex_r.inputs["Vector"])
            nt.links.new(tex_r.outputs["Color"], comb.inputs[1])
            comb.inputs[2].default_value = 1.0
        else:
            comb.inputs[1].default_value = 0.0
            comb.inputs[2].default_value = 0.0
        emit = nt.nodes.new("ShaderNodeEmission")
        emit.inputs["Strength"].default_value = 1.0
        nt.links.new(comb.outputs["Color"], emit.inputs["Color"])
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])

        obj.data.materials[0] = bake_mat
        cena.render.engine = "CYCLES"
        cena.cycles.device = "CPU"
        cena.cycles.use_denoising = False
        cena.render.bake.use_selected_to_active = False
        cena.render.bake.use_clear = True
        _configurar_render_png_linear(cena)

        img_ao_tmp = bpy.data.images.new(f"{nome_base}_ext_ao", width=px_sub, height=px_sub, alpha=False)
        img_ao_tmp.colorspace_settings.name = "Non-Color"
        tex_bake.image = img_ao_tmp
        tex_bake.select = True
        nt.nodes.active = tex_bake
        cena.cycles.samples = 4
        cena.render.bake.margin = max(4, px_sub // 128)
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.bake(type="AO")

        img_hints_tmp = bpy.data.images.new(f"{nome_base}_ext_ht", width=px_sub, height=px_sub, alpha=False)
        img_hints_tmp.colorspace_settings.name = "Non-Color"
        tex_bake.image = img_hints_tmp
        tex_bake.select = True
        nt.nodes.active = tex_bake
        cena.cycles.samples = 1
        bpy.ops.object.bake(type="EMIT")

        nome_orm = f"{nome_base}_orm.png"
        path_orm = os.path.join(saida_dir, nome_orm)
        img_orm_tmp = _empacotar_orm(img_ao_tmp, f"{nome_base}_orm_tmp", px_sub, img_hints=img_hints_tmp)
        extras_roblox = (
            _extrair_canais_roblox(img_orm_tmp, saida_dir, nome_base, px_sub, cena)
            if str(perfil_nome or "").startswith("roblox")
            else []
        )
        img_orm = _salvar_e_recarregar_png(img_orm_tmp, path_orm, "Non-Color", cena)

        obj.data.materials[0] = mat_orig
        nt_orig = mat_orig.node_tree
        bsdf = nt_orig.nodes.get("Principled BSDF")
        if bsdf is not None:
            if "Roughness" in bsdf.inputs:
                bsdf.inputs["Roughness"].default_value = 0.78
            if "Specular IOR Level" in bsdf.inputs:
                bsdf.inputs["Specular IOR Level"].default_value = 0.18
        tex_orm = nt_orig.nodes.new("ShaderNodeTexImage")
        tex_orm.image = img_orm
        sep = nt_orig.nodes.new("ShaderNodeSeparateColor")
        sep.mode = "RGB"
        nt_orig.links.new(tex_orm.outputs["Color"], sep.inputs["Color"])
        nt_orig.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nt_orig.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
        ng = _obter_grupo_gltf_occlusion()
        gltf_out = nt_orig.nodes.new("ShaderNodeGroup")
        gltf_out.node_tree = ng
        nt_orig.links.new(sep.outputs["Red"], gltf_out.inputs["Occlusion"])
    finally:
        if obj.data.materials and obj.data.materials[0] != mat_orig:
            obj.data.materials[0] = mat_orig
        if bake_mat is not None and bake_mat.name in bpy.data.materials and bake_mat.users == 0:
            bpy.data.materials.remove(bake_mat)
        for img_tmp in (img_met, img_rough, img_ao_tmp, img_hints_tmp):
            if img_tmp is not None and img_tmp.name in bpy.data.images and img_tmp.users == 0:
                bpy.data.images.remove(img_tmp)
        _restaurar_estado_cena(cena, estado_anterior)

    bytes_orm = os.path.getsize(path_orm)
    return {
        "orm_px": px_sub,
        "arquivos_textura": [{"caminho": nome_orm, "papel": "orm", "bytes": bytes_orm}, *extras_roblox],
    }


def _redimensionar_png_no_material(obj, caminho: str, px_novo: int, colorspace: str) -> int:
    """Redimensiona um mapa PNG ligado ao material de ``obj`` preservando compressao maxima."""
    cena = bpy.context.scene
    anterior = _capturar_estado_cena(cena)
    alvo_nome = os.path.basename(caminho)
    try:
        _configurar_render_png_linear(cena)

        for mat in obj.data.materials:
            if not mat or not mat.use_nodes:
                continue
            for node in mat.node_tree.nodes:
                if node.type != "TEX_IMAGE" or node.image is None:
                    continue
                img = node.image
                if os.path.basename(img.filepath or "") != alvo_nome and img.name != alvo_nome:
                    continue
                img.scale(px_novo, px_novo)
                img.save_render(filepath=caminho, scene=cena)
                nova = bpy.data.images.load(caminho, check_existing=False)
                nova.colorspace_settings.name = colorspace
                node.image = nova
                if img.users == 0:
                    bpy.data.images.remove(img)
                return os.path.getsize(caminho)
    finally:
        _restaurar_estado_cena(cena, anterior)
    return os.path.getsize(caminho)


def ajustar_resolucao_orcamento(
    obj,
    saida_dir: str,
    texturas_geradas: list[dict],
    glb_caminho: str,
    limite_bytes: int,
    reexportar_fn,
) -> None:
    """Encolhe submapas POT (512->256; e baseColor 1024->512 se necessario) ate caber no teto G9."""
    if limite_bytes <= 0 or not os.path.isfile(glb_caminho):
        return
    if os.path.getsize(glb_caminho) <= limite_bytes:
        return

    cs_por_papel = {"textura": "sRGB", "normal": "Non-Color", "orm": "Non-Color"}
    alterou = False
    for tex in texturas_geradas:
        if tex.get("papel") in ("normal", "orm"):
            cam = os.path.join(saida_dir, tex["caminho"])
            if os.path.isfile(cam):
                tex["bytes"] = _redimensionar_png_no_material(obj, cam, 256, cs_por_papel[tex["papel"]])
                alterou = True
    if alterou:
        reexportar_fn()

    if os.path.getsize(glb_caminho) > limite_bytes:
        for tex in texturas_geradas:
            if tex.get("papel") == "textura":
                cam = os.path.join(saida_dir, tex["caminho"])
                if os.path.isfile(cam):
                    tex["bytes"] = _redimensionar_png_no_material(obj, cam, 512, "sRGB")
                    reexportar_fn()
                break
