"""High->Low PBR bake no Cycles (BaseColor, Normal, ORM) para o pipeline Forge3D.

Roda dentro do Python embutido do Blender 4.2+ usando apenas ``bpy``, ``bmesh``, ``mathutils``
e a biblioteca padrao (sem Pillow nem numpy).
"""

from __future__ import annotations

import math
import os
from array import array

import bmesh  # noqa: F401 - reservado para utilidades de malha no bpy
import bpy
from mathutils import Vector  # noqa: F401


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


def _criar_material_high_vc(nome_mat: str, nome_cor: str):
    """Material temporario para transferir ``color_attributes`` no bake DIFFUSE."""
    mat = bpy.data.materials.new(nome_mat)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.85
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = nome_cor
    nt.links.new(vc.outputs["Color"], bsdf.inputs["Base Color"])
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


def _empacotar_orm(img_ao, nome_img: str, px: int):
    """Empacota R=AO, G=Roughness(0.50..0.90), B=0.0(Metallic) via ``array('f')``."""
    total_floats = px * px * 4
    ao_buf = array("f", [0.0]) * total_floats
    img_ao.pixels.foreach_get(ao_buf)

    orm_buf = array("f", [0.0]) * total_floats
    for i in range(0, total_floats, 4):
        ao = ao_buf[i]
        if ao < 0.0:
            ao = 0.0
        elif ao > 1.0:
            ao = 1.0
        rough = 0.85 - 0.25 * (1.0 - ao)
        if rough < 0.50:
            rough = 0.50
        elif rough > 0.90:
            rough = 0.90
        orm_buf[i] = ao
        orm_buf[i + 1] = rough
        orm_buf[i + 2] = 0.0
        orm_buf[i + 3] = 1.0

    img_orm = bpy.data.images.new(nome_img, width=px, height=px, alpha=False)
    img_orm.colorspace_settings.name = "Non-Color"
    img_orm.pixels.foreach_set(orm_buf)
    return img_orm


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
) -> dict:
    """Executa bake PBR High->Low (BaseColor, Normal, ORM) e atribui material glTF PBR em ``obj``."""
    if obj is None or obj.data is None or not obj.data.color_attributes:
        raise RuntimeError("malha sem atributo de cor por vertice para assar PBR")

    os.makedirs(saida_dir, exist_ok=True)
    px = max(64, min(int(px), 1024))
    px_sub = min(px, 512)

    ativo_cor = obj.data.color_attributes.active_color
    nome_cor = ativo_cor.name if ativo_cor is not None else obj.data.color_attributes[0].name
    tris_high = _contar_triangulos(obj)

    high_mesh = obj.data.copy()
    high_mesh.name = f"{nome_base}_high_mesh"
    high_obj = bpy.data.objects.new(f"{nome_base}_high", high_mesh)
    high_obj.matrix_world = obj.matrix_world.copy()
    colecao = obj.users_collection[0] if obj.users_collection else bpy.context.scene.collection
    colecao.objects.link(high_obj)

    high_mat = None
    low_bake_mat = None
    cena = bpy.context.scene

    # Guarda estado de render/cor para restaurar ao sair (evita side-effects na cena).
    estado_anterior = {
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

    try:
        suavizar_fn(high_obj, 45.0)

        decimar_fn(obj, int(limite_triangulos))
        info_reparo = reparo_fn(obj)
        info_smooth = suavizar_fn(obj, 45.0)
        info_uv = uv_fn(obj)
        if not obj.data.uv_layers:
            raise RuntimeError("malha low-poly sem camada UV apos uv_fn")
        tris_low = _contar_triangulos(obj)

        bpy.context.view_layer.update()
        diag = _bbox_diag(obj)
        cage_extrusion = max(0.02, 0.03 * diag)

        high_mat = _criar_material_high_vc(f"{nome_base}_high_bake_tmp", nome_cor)
        high_obj.data.materials.clear()
        high_obj.data.materials.append(high_mat)

        low_bake_mat, tex_bake = _criar_material_alvo_bake(f"{nome_base}_low_bake_tmp")
        obj.data.materials.clear()
        obj.data.materials.append(low_bake_mat)

        cena.render.engine = "CYCLES"
        cena.cycles.device = "CPU"
        cena.cycles.use_denoising = False
        cena.render.bake.use_selected_to_active = True
        cena.render.bake.use_cage = False
        cena.render.bake.cage_extrusion = cage_extrusion
        cena.render.bake.max_ray_distance = 0.0
        cena.render.bake.use_clear = True

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

        # 1. BaseColor (DIFFUSE color pass) em `px`
        nome_bc = f"{nome_base}_baseColor.png"
        path_bc = os.path.join(saida_dir, nome_bc)
        img_bc_tmp = bpy.data.images.new(f"{nome_base}_bc_tmp", width=px, height=px, alpha=False)
        img_bc_tmp.colorspace_settings.name = "sRGB"
        tex_bake.image = img_bc_tmp
        tex_bake.select = True
        low_bake_mat.node_tree.nodes.active = tex_bake

        cena.cycles.samples = 1
        cena.render.bake.use_pass_direct = False
        cena.render.bake.use_pass_indirect = False
        cena.render.bake.use_pass_color = True
        cena.render.bake.margin = max(4, px // 128)
        _selecionar_high_para_low(high_obj, obj)
        bpy.ops.object.bake(type="DIFFUSE")
        img_bc = _salvar_e_recarregar_png(img_bc_tmp, path_bc, "sRGB", cena)

        # 2. Normal (TANGENT) em `min(px, 512)`
        nome_nm = f"{nome_base}_normal.png"
        path_nm = os.path.join(saida_dir, nome_nm)
        img_nm_tmp = bpy.data.images.new(
            f"{nome_base}_nm_tmp", width=px_sub, height=px_sub, alpha=False
        )
        img_nm_tmp.colorspace_settings.name = "Non-Color"
        tex_bake.image = img_nm_tmp
        tex_bake.select = True
        low_bake_mat.node_tree.nodes.active = tex_bake

        cena.cycles.samples = 1
        cena.render.bake.normal_space = "TANGENT"
        cena.render.bake.normal_r = "POS_X"
        cena.render.bake.normal_g = "POS_Y"
        cena.render.bake.normal_b = "POS_Z"
        cena.render.bake.margin = max(4, px_sub // 128)
        _selecionar_high_para_low(high_obj, obj)
        bpy.ops.object.bake(type="NORMAL")
        img_nm = _salvar_e_recarregar_png(img_nm_tmp, path_nm, "Non-Color", cena)

        # 3. ORM via AO (4 samples) em `min(px, 512)`
        nome_orm = f"{nome_base}_orm.png"
        path_orm = os.path.join(saida_dir, nome_orm)
        img_ao_tmp = bpy.data.images.new(
            f"{nome_base}_ao_tmp", width=px_sub, height=px_sub, alpha=False
        )
        img_ao_tmp.colorspace_settings.name = "Non-Color"
        tex_bake.image = img_ao_tmp
        tex_bake.select = True
        low_bake_mat.node_tree.nodes.active = tex_bake

        cena.cycles.samples = 4
        cena.render.bake.margin = max(4, px_sub // 128)
        _selecionar_high_para_low(high_obj, obj)
        bpy.ops.object.bake(type="AO")

        img_orm_tmp = _empacotar_orm(img_ao_tmp, f"{nome_base}_orm_tmp", px_sub)
        bpy.data.images.remove(img_ao_tmp)
        img_orm = _salvar_e_recarregar_png(img_orm_tmp, path_orm, "Non-Color", cena)

        for atributo in list(obj.data.color_attributes):
            obj.data.color_attributes.remove(atributo)

        obj.data.materials.clear()
        mat_final = _criar_material_pbr_gltf(f"{nome_base}_pbr", img_bc, img_nm, img_orm)
        obj.data.materials.append(mat_final)

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    finally:
        if high_obj is not None and high_obj.name in bpy.data.objects:
            bpy.data.objects.remove(high_obj, do_unlink=True)
        if high_mesh is not None and high_mesh.name in bpy.data.meshes and high_mesh.users == 0:
            bpy.data.meshes.remove(high_mesh)
        for mat_tmp in (high_mat, low_bake_mat):
            if mat_tmp is not None and mat_tmp.name in bpy.data.materials and mat_tmp.users == 0:
                bpy.data.materials.remove(mat_tmp)

        cena.view_settings.view_transform = estado_anterior["view_transform"]
        cena.view_settings.look = estado_anterior["look"]
        cena.view_settings.exposure = estado_anterior["exposure"]
        cena.view_settings.gamma = estado_anterior["gamma"]
        cena.display_settings.display_device = estado_anterior["display_device"]
        cena.render.image_settings.file_format = estado_anterior["file_format"]
        cena.render.image_settings.color_mode = estado_anterior["color_mode"]
        cena.render.image_settings.color_depth = estado_anterior["color_depth"]
        cena.render.image_settings.compression = estado_anterior["compression"]

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
            "bbox_diag": round(diag, 6),
            "cage_extrusion": round(cage_extrusion, 6),
            "triangulos_high": tris_high,
            "triangulos_low": tris_low,
            "reparo": info_reparo,
            "smooth": info_smooth,
            "uv": info_uv,
            "png_bytes": bytes_bc,
            "baseColor_bytes": bytes_bc,
            "normal_bytes": bytes_nm,
            "orm_bytes": bytes_orm,
        },
        "arquivos_textura": [
            {"caminho": nome_bc, "papel": "textura", "bytes": bytes_bc},
            {"caminho": nome_nm, "papel": "normal", "bytes": bytes_nm},
            {"caminho": nome_orm, "papel": "orm", "bytes": bytes_orm},
        ],
    }


def _redimensionar_png_no_material(obj, caminho: str, px_novo: int, colorspace: str) -> int:
    """Redimensiona um mapa PNG ligado ao material de ``obj`` preservando compressao maxima."""
    cena = bpy.context.scene
    anterior = {
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
    alvo_nome = os.path.basename(caminho)
    try:
        cena.view_settings.view_transform = "Standard"
        cena.view_settings.look = "None"
        cena.view_settings.exposure = 0.0
        cena.view_settings.gamma = 1.0
        cena.display_settings.display_device = "sRGB"
        cena.render.image_settings.file_format = "PNG"
        cena.render.image_settings.color_mode = "RGB"
        cena.render.image_settings.color_depth = "8"
        cena.render.image_settings.compression = 100

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
        cena.view_settings.view_transform = anterior["view_transform"]
        cena.view_settings.look = anterior["look"]
        cena.view_settings.exposure = anterior["exposure"]
        cena.view_settings.gamma = anterior["gamma"]
        cena.display_settings.display_device = anterior["display_device"]
        cena.render.image_settings.file_format = anterior["file_format"]
        cena.render.image_settings.color_mode = anterior["color_mode"]
        cena.render.image_settings.color_depth = anterior["color_depth"]
        cena.render.image_settings.compression = anterior["compression"]
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
