"""Empacotamento ORM, normal repair, material glTF occlusion, hints e controle de resolucao."""

from __future__ import annotations

import math
import os
import sys
from array import array

try:
    import bpy
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bpy = None  # type: ignore[assignment]

if __package__:
    from . import bake_pbr_config as _cfg
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import bake_pbr_config as _cfg

PISO_PX_ORCAMENTO = 512


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
    estado_anterior = _cfg._capturar_estado_cena(cena)

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
        _cfg._configurar_render_png_linear(cena)

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
        _cfg._executar_bake_seguro(cena, type="AO")

        img_hints_tmp = bpy.data.images.new(f"{nome_base}_ext_ht", width=px_sub, height=px_sub, alpha=False)
        img_hints_tmp.colorspace_settings.name = "Non-Color"
        tex_bake.image = img_hints_tmp
        tex_bake.select = True
        nt.nodes.active = tex_bake
        cena.cycles.samples = 1
        _cfg._executar_bake_seguro(cena, type="EMIT")

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
        _cfg._restaurar_estado_cena(cena, estado_anterior)

    bytes_orm = os.path.getsize(path_orm)
    return {
        "orm_px": px_sub,
        "arquivos_textura": [{"caminho": nome_orm, "papel": "orm", "bytes": bytes_orm}, *extras_roblox],
    }


def _redimensionar_png_no_material(
    obj,
    caminho: str,
    px_novo: int,
    colorspace: str,
) -> tuple[int, bool]:
    """Redimensiona um mapa PNG ligado ao material de ``obj`` respeitando ``PISO_PX_ORCAMENTO``."""
    px_alvo = max(PISO_PX_ORCAMENTO, int(px_novo))
    cena = bpy.context.scene
    anterior = _cfg._capturar_estado_cena(cena)
    alvo_nome = os.path.basename(caminho)
    try:
        _cfg._configurar_render_png_linear(cena)

        for mat in obj.data.materials:
            if not mat or not mat.use_nodes:
                continue
            for node in mat.node_tree.nodes:
                if node.type != "TEX_IMAGE" or node.image is None:
                    continue
                img = node.image
                if os.path.basename(img.filepath or "") != alvo_nome and img.name != alvo_nome:
                    continue
                w_cur, h_cur = int(img.size[0]), int(img.size[1])
                if max(w_cur, h_cur) <= px_alvo:
                    return os.path.getsize(caminho), False
                img.scale(px_alvo, px_alvo)
                img.save_render(filepath=caminho, scene=cena)
                nova = bpy.data.images.load(caminho, check_existing=False)
                nova.colorspace_settings.name = colorspace
                node.image = nova
                if img.users == 0:
                    bpy.data.images.remove(img)
                return os.path.getsize(caminho), True
    finally:
        _cfg._restaurar_estado_cena(cena, anterior)
    return os.path.getsize(caminho), False


def ajustar_resolucao_orcamento(
    obj,
    saida_dir: str,
    texturas_geradas: list[dict],
    glb_caminho: str,
    limite_bytes: int,
    reexportar_fn,
) -> None:
    """Encolhe mapas acima de ``PISO_PX_ORCAMENTO`` (512px) ate caber no teto sem cair abaixo de 512px."""
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
                novo_bytes, mudou = _redimensionar_png_no_material(
                    obj, cam, PISO_PX_ORCAMENTO, cs_por_papel[tex["papel"]]
                )
                tex["bytes"] = novo_bytes
                alterou = alterou or mudou
    if alterou:
        reexportar_fn()

    if os.path.getsize(glb_caminho) > limite_bytes:
        for tex in texturas_geradas:
            if tex.get("papel") == "textura":
                cam = os.path.join(saida_dir, tex["caminho"])
                if os.path.isfile(cam):
                    novo_bytes, mudou = _redimensionar_png_no_material(
                        obj, cam, PISO_PX_ORCAMENTO, "sRGB"
                    )
                    tex["bytes"] = novo_bytes
                    if mudou:
                        reexportar_fn()
                break
