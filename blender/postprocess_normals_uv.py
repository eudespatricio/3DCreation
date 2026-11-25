"""Camada L2 de postprocess: normais, UV/lightmap, bake de cor de vertice e imagens."""

from __future__ import annotations

import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

if __package__:
    from .postprocess_repair import _colapsar_faces_degeneradas, reparar_malha
    from .postprocess_scene import (
        PARTES_RIGIDAS, TIPOS_ORGANICOS, _selecionar, malha_triangulada,
    )
    from .postprocess_uv_boost import aplicar_prioridade_uv_cabeca, tem_uv_sobreposta
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from postprocess_repair import _colapsar_faces_degeneradas, reparar_malha
    from postprocess_scene import (
        PARTES_RIGIDAS, TIPOS_ORGANICOS, _selecionar, malha_triangulada,
    )
    from postprocess_uv_boost import aplicar_prioridade_uv_cabeca, tem_uv_sobreposta


def _resolver_config_suavizacao(job: dict, bruto: dict) -> dict:
    """Resolve parametros de suavizacao de normais (organico 65 deg vs hard-surface 38 deg)."""
    item = job.get("item") if isinstance(job.get("item"), dict) else {}
    cfg_raw = job.get("suavizacao_normais") or item.get("suavizacao_normais") or {}
    cfg = cfg_raw if isinstance(cfg_raw, dict) else {}
    modo = str(cfg.get("modo") or "auto").strip().lower()
    tipo = str(job.get("tipo") or item.get("tipo") or "").strip()
    parte = str(item.get("parte") or "").strip().lower()
    eh_armadura = bool(bruto.get("armadura_modular")) or (parte in PARTES_RIGIDAS)

    if modo == "organico":
        eh_organico = True
    elif modo == "hard_surface":
        eh_organico = False
    else:
        eh_organico = (tipo in TIPOS_ORGANICOS) and not eh_armadura

    if "angulo_graus" in cfg and cfg["angulo_graus"] is not None:
        angulo_graus = float(cfg["angulo_graus"])
    elif eh_organico:
        angulo_graus = 65.0
    elif item.get("rota") == "import" and bruto.get("origem_nome") == "malha_colorida.glb" and not cfg:
        angulo_graus = 45.0
    else:
        angulo_graus = 38.0

    if "weighted_normals" in cfg and cfg["weighted_normals"] is not None:
        weighted_normals = bool(cfg["weighted_normals"])
    else:
        weighted_normals = (not eh_organico) and (
            tipo in ("prop_equipavel", "prop_estatico", "modulo_cenario")
            or eh_armadura
            or bruto.get("schema") == "forge3d/bruto-extrude@1"
        )

    if "corrective_smooth" in cfg and cfg["corrective_smooth"] is not None:
        corrective_smooth = bool(cfg["corrective_smooth"])
    else:
        corrective_smooth = eh_organico

    return {
        "modo": "organico" if eh_organico else "hard_surface",
        "eh_organico": eh_organico,
        "angulo_graus": angulo_graus,
        "weighted_normals": weighted_normals,
        "corrective_smooth": corrective_smooth,
        "soldar_componentes_organicos": bool(cfg.get("soldar_componentes_organicos", False)),
    }


def suavizar_por_angulo(obj, angulo_graus: float = 65.0) -> dict:
    """Smooth shading real por angulo diedro + custom split normals ponderadas por angulo."""
    if obj is None or obj.type != "MESH" or obj.data is None:
        return {"angulo_graus": float(angulo_graus), "arestas_vivas": 0, "custom_normals": False}
    me = obj.data
    _selecionar(obj)
    if getattr(me, "has_custom_normals", False):
        try:
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
        except RuntimeError as exc:
            print(f"[postprocess] aviso ao limpar split normals de {obj.name}: {exc}", file=sys.stderr)
    for poly in me.polygons:
        poly.use_smooth = True
    me.shade_smooth()
    rad = math.radians(float(angulo_graus))
    me.set_sharp_from_angle(angle=rad)
    me.update()

    sharp_attr = me.attributes.get("sharp_edge")
    sharp_indices = (
        {i for i, d in enumerate(sharp_attr.data) if d.value}
        if sharp_attr is not None
        else set()
    )

    if len(me.loops) > 0 and len(me.polygons) > 0:
        bm = bmesh.new()
        try:
            bm.from_mesh(me)
            bm.faces.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.verts.ensure_lookup_table()
            bm.normal_update()
            for e in bm.edges:
                if e.index in sharp_indices:
                    e.smooth = False
                elif len(e.link_faces) == 2:
                    n0 = e.link_faces[0].normal
                    n1 = e.link_faces[1].normal
                    if n0.length > 1e-8 and n1.length > 1e-8:
                        cos_a = max(-1.0, min(1.0, n0.dot(n1)))
                        if math.acos(cos_a) >= rad:
                            e.smooth = False
                            sharp_indices.add(e.index)
                        else:
                            e.smooth = True
                    else:
                        e.smooth = True
                else:
                    e.smooth = False
                    sharp_indices.add(e.index)

            loop_normals = [Vector((0.0, 0.0, 1.0))] * len(me.loops)
            for v in bm.verts:
                visitados: set = set()
                for lp_ini in v.link_loops:
                    if lp_ini in visitados:
                        continue
                    grupo = []
                    fila = [lp_ini]
                    visitados.add(lp_ini)
                    while fila:
                        atual = fila.pop()
                        grupo.append(atual)
                        for e_adj in (atual.edge, atual.link_loop_prev.edge):
                            if e_adj.index in sharp_indices or not e_adj.smooth:
                                continue
                            for l_adj in e_adj.link_loops:
                                for cand in (l_adj, l_adj.link_loop_next):
                                    if cand.vert == v and cand not in visitados:
                                        visitados.add(cand)
                                        fila.append(cand)
                    acum = Vector((0.0, 0.0, 0.0))
                    for lp in grupo:
                        peso = max(1e-6, lp.calc_angle())
                        acum += lp.face.normal * peso
                    if acum.length > 1e-8:
                        n_final = acum.normalized()
                    elif v.normal.length > 1e-8:
                        n_final = v.normal.normalized()
                    else:
                        n_final = Vector((0.0, 0.0, 1.0))
                    for lp in grupo:
                        loop_normals[lp.index] = n_final
        finally:
            bm.free()
        me.normals_split_custom_set(loop_normals)
        me.update()

    arestas_vivas = len(sharp_indices)
    return {
        "angulo_graus": float(angulo_graus),
        "arestas_vivas": arestas_vivas,
        "custom_normals": bool(getattr(me, "has_custom_normals", False)),
    }


def aplicar_weighted_normal(obj) -> dict:
    """Aplica normais ponderadas por area/angulo em pecas hard-surface."""
    _selecionar(obj)
    mod = obj.modifiers.new(name="WeightedNormal", type="WEIGHTED_NORMAL")
    mod.mode = "FACE_AREA_WITH_ANGLE"
    mod.keep_sharp = True
    bpy.ops.object.modifier_apply(modifier=mod.name)
    obj.data.update()
    return {"weighted_normal": True}


def desdobrar_uv(
    obj, margem: float = 0.004, angle_limit_graus: float = 66.0, *, eh_organico: bool = True
) -> str:
    if obj is not None and obj.type == "MESH" and obj.data and len(obj.data.polygons) > 4:
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            colapsadas = _colapsar_faces_degeneradas(bm, area_min=1e-9)
            if colapsadas > 0:
                bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
                bm.to_mesh(obj.data)
                obj.data.update()
        finally:
            bm.free()
    n_polys = len(obj.data.polygons)
    if n_polys >= 400:
        smart_margin = max(0.003, min(0.004, float(margem)))
        pack_margin = max(0.0035, min(0.004, float(margem)))
    else:
        smart_margin = max(0.0015, min(0.02, float(margem)))
        pack_margin = max(0.0015, min(0.01, float(margem)))
    rna_props = bpy.ops.uv.pack_islands.get_rna_type().properties
    pack_props = set(rna_props.keys())
    pack_raw: dict[str, object] = {
        "rotate": True, "scale": True, "margin": pack_margin, "margin_method": "FRACTION", "shape_method": "CONCAVE"
    }
    if "rotate_method" in pack_props and "ANY" in {it.identifier for it in rna_props["rotate_method"].enum_items}:
        pack_raw["rotate_method"] = "ANY"
    pack_kwargs = {k: v for k, v in pack_raw.items() if k in pack_props}
    angulos = [float(angle_limit_graus)] + [a for a in (52.0, 45.0, 38.0) if a < float(angle_limit_graus) - 0.5]
    _selecionar(obj)
    uv_sobreposta = False
    for ang in angulos:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(
            angle_limit=math.radians(ang), island_margin=smart_margin,
            area_weight=0.0, correct_aspect=True, scale_to_bounds=False,
        )
        bpy.ops.uv.select_all(action="SELECT")
        bpy.ops.uv.average_islands_scale()
        bpy.ops.object.mode_set(mode="OBJECT")
        if not obj.data.uv_layers or n_polys <= 0:
            break
        if eh_organico:
            aplicar_prioridade_uv_cabeca(obj, fator=1.50)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.select_all(action="SELECT")
        bpy.ops.uv.pack_islands(**pack_kwargs)
        bpy.ops.object.mode_set(mode="OBJECT")
        uv_sobreposta = tem_uv_sobreposta(obj)
        if not uv_sobreposta:
            break
    if uv_sobreposta:
        print(f"[postprocess] aviso: UV0 ainda sobreposta em {obj.name} apos fallback angular", file=sys.stderr)
    if not obj.data.uv_layers:
        raise RuntimeError("smart_project nao criou camada UV")
    return obj.data.uv_layers.active.name


def gerar_uv_lightmap(obj) -> str:
    """Gera UVMap_Lightmap (TEXCOORD_1) sem substituir o UV principal (TEXCOORD_0)."""
    if not obj.data.uv_layers:
        desdobrar_uv(obj, eh_organico=False)
    nome_primario = obj.data.uv_layers[0].name
    lm = obj.data.uv_layers.get("UVMap_Lightmap") or obj.data.uv_layers.new(name="UVMap_Lightmap")
    nome_lm = lm.name
    obj.data.uv_layers.active = lm
    _selecionar(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(
        angle_limit=1.15192,
        island_margin=0.03,
        area_weight=0.5,
        correct_aspect=True,
        scale_to_bounds=False,
    )
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.data.uv_layers.active = obj.data.uv_layers[nome_primario]
    obj.data.uv_layers[nome_primario].active_render = True
    return nome_lm


def assar_cor_vertices(obj, png: str, px: int) -> dict:
    """Bake DIFFUSE/COLOR da cor por vertice para PNG e troca o material por textura."""
    if not obj.data.color_attributes:
        raise RuntimeError("malha sem atributo de cor por vertice para assar")
    nome_cor = obj.data.color_attributes[0].name
    obj.data.materials.clear()
    mat = bpy.data.materials.new("forge3d_bake")
    mat.use_nodes = True
    mat.use_backface_culling = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.85
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = nome_cor
    nt.links.new(vc.outputs["Color"], bsdf.inputs["Base Color"])
    img = bpy.data.images.new("forge3d_baseColor", width=px, height=px, alpha=False)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.select = True
    nt.nodes.active = tex
    obj.data.materials.append(mat)

    cena = bpy.context.scene
    cena.render.engine = "CYCLES"
    cena.cycles.device = "CPU"
    cena.cycles.samples = 1
    cena.cycles.use_denoising = False
    cena.render.bake.use_pass_direct = False
    cena.render.bake.use_pass_indirect = False
    cena.render.bake.use_pass_color = True
    cena.render.bake.margin = max(4, px // 128)
    cena.render.bake.use_clear = True
    _selecionar(obj)
    bpy.ops.object.bake(type="DIFFUSE")

    img.filepath_raw = png
    img.file_format = "PNG"
    img.save()
    img.pack()
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.nodes.remove(vc)
    for atributo in list(obj.data.color_attributes):
        obj.data.color_attributes.remove(atributo)
    return {
        "textura_px": px,
        "cor_atributo": nome_cor,
        "png_bytes": os.path.getsize(png),
    }


def _imagens_exportaveis() -> list:
    """Lista todas as imagens exportaveis carregadas na cena (exclui render targets)."""
    imgs = []
    for img in bpy.data.images:
        if getattr(img, "type", "IMAGE") == "RENDER_TARGET":
            continue
        if img.name in ("Render Result", "Viewer Node"):
            continue
        w, h = int(img.size[0]), int(img.size[1])
        if w <= 0 or h <= 0:
            continue
        imgs.append(img)
    return imgs


def _redimensionar_imagem(img, nw: int, nh: int) -> None:
    """Redimensiona imagem para (nw, nh) substituindo buffer empacotado via user_remap."""
    nome_orig = img.name
    cs = img.colorspace_settings.name if hasattr(img, "colorspace_settings") else "sRGB"
    img.scale(nw, nh)
    px = list(img.pixels)
    dst = bpy.data.images.new(name=f"{nome_orig}_r", width=nw, height=nh, alpha=True)
    try:
        dst.colorspace_settings.name = cs
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        print(f"[postprocess] aviso ao definir colorspace {cs!r} em {nome_orig}: {exc}", file=sys.stderr)
    dst.pixels.foreach_set(px)
    dst.pack()
    img.user_remap(dst)
    bpy.data.images.remove(img)
    dst.name = nome_orig


def _pot_abaixo(valor: int) -> int:
    """Maior potencia de 2 menor ou igual a valor (minimo 4px) para G4."""
    v = max(4, int(valor))
    if (v & (v - 1)) == 0:
        return v
    return 1 << (v.bit_length() - 1)


def _enquadrar_texturas_no_teto(textura_max: int) -> None:
    """Redimensiona qualquer imagem em cena maior que textura_max preservando POT (G4)."""
    if textura_max <= 0:
        return
    for img in _imagens_exportaveis():
        w, h = int(img.size[0]), int(img.size[1])
        maior = max(w, h)
        if maior > textura_max:
            fator = float(textura_max) / float(maior)
            nw = _pot_abaixo(max(4, int(round(w * fator))))
            nh = _pot_abaixo(max(4, int(round(h * fator))))
            _redimensionar_imagem(img, nw, nh)


def _propagar_deslocamento_zonas_uv(
    high_mesh_src,
    obj,
    pbr_zonas_cfg,
    pre_bake_high_max_x: float,
    fn_shift=None,
    passo_zona_x: float = 6.0,
) -> None:
    """Propaga deslocamento X de ``pbr_zonas`` do high-poly para o low-poly antes do Cycles bake."""
    passo = float(passo_zona_x or 6.0)
    if abs(pre_bake_high_max_x) < passo * 0.5 and high_mesh_src.vertices and obj.data.vertices:
        from mathutils.kdtree import KDTree

        kd = KDTree(len(high_mesh_src.vertices))
        kzs: list[int] = []
        for idx, v in enumerate(high_mesh_src.vertices):
            kz = max(0, int(round(v.co.x / passo)))
            kzs.append(kz)
            kd.insert(Vector((v.co.x - float(kz) * passo, v.co.y, v.co.z)), idx)
        kd.balance()
        moveu = False
        for lv in obj.data.vertices:
            _co, idx_h, _dist = kd.find(lv.co)
            kz = kzs[idx_h]
            if kz > 0:
                lv.co.x += float(kz) * passo
                moveu = True
        if moveu:
            obj.data.update()
        return
    if callable(fn_shift) and pbr_zonas_cfg:
        fn_shift(obj, list(pbr_zonas_cfg), passo)


def _preparar_contexto_bake_pos_escala(
    obj, high_obj_src, pbr_zonas_cfg, info_gerada: dict, alpha_cards_ativo: bool,
    angulo_smooth_final: float, desdobrar_uv_fn, bake_pbr_mod,
) -> tuple[dict, object, object, object, object]:
    """Prepara troca high/low pos-escala e callbacks preservando vertex_groups, UVs e weighted_normal."""
    low_mesh_pronto, high_mesh_src = obj.data, high_obj_src.data
    pre_bake_high_max_x = max((v.co.x for v in high_mesh_src.vertices), default=0.0)
    arm_states = [(m, m.show_viewport, m.show_render) for m in obj.modifiers if m.type == "ARMATURE"]
    for m, _vp, _rn in arm_states:
        m.show_viewport, m.show_render = False, False
    obj.data = high_mesh_src
    estado = {
        "obj": obj, "high_obj_src": high_obj_src, "high_mesh_src": high_mesh_src,
        "low_mesh_pronto": low_mesh_pronto, "arm_states": arm_states, "swapped_to_low": False,
    }

    def _decimar_cb(alvo_o, _lim_t: int) -> int:
        if alvo_o is obj and not estado["swapped_to_low"]:
            zonas_shifted = bool(
                pbr_zonas_cfg
                and any(v.co.x > pre_bake_high_max_x + 3.0 for v in obj.data.vertices)
            )
            obj.data = low_mesh_pronto
            estado["swapped_to_low"] = True
            if zonas_shifted:
                passes_mod = getattr(getattr(bake_pbr_mod, "_exec", None), "_passes", None)
                fn_shift = getattr(passes_mod, "_deslocar_zonas_uv", None)
                passo_obj = float(obj.get("forge3d_passo_zona_x", 6.0))
                _propagar_deslocamento_zonas_uv(
                    high_mesh_src, obj, pbr_zonas_cfg, pre_bake_high_max_x, fn_shift, passo_obj
                )
        return malha_triangulada(alvo_o)

    def _reparo_cb(alvo_o) -> dict:
        if alvo_o is obj:
            return (
                info_gerada.get("reparo_pos_escala")
                or info_gerada.get("reparo_pos_decimate")
                or info_gerada.get("reparo_inicial")
                or {}
            )
        return reparar_malha(alvo_o, permitir_bordas_abertas=alpha_cards_ativo)

    def _suavizar_cb(alvo_o, a: float = angulo_smooth_final) -> dict:
        if alvo_o is obj:
            return (
                info_gerada.get("smooth_pos_escala")
                or info_gerada.get("smooth")
                or {"angulo_graus": float(a), "arestas_vivas": 0, "custom_normals": True}
            )
        return suavizar_por_angulo(alvo_o, angulo_graus=a)

    def _uv_cb(alvo_o) -> str:
        if alvo_o is obj and alvo_o.data.uv_layers:
            alvo_o.data.uv_layers.active = alvo_o.data.uv_layers[0]
            alvo_o.data.uv_layers[0].active_render = True
            return alvo_o.data.uv_layers[0].name
        return desdobrar_uv_fn(alvo_o)

    return estado, _decimar_cb, _reparo_cb, _suavizar_cb, _uv_cb


def _finalizar_contexto_bake_pos_escala(estado: dict) -> None:
    """Restaura malha/modificadores ARMATURE e remove clone high_obj_src temporario."""
    obj = estado["obj"]
    if not estado["swapped_to_low"]:
        obj.data = estado["low_mesh_pronto"]
    for m, vp, rn in estado["arm_states"]:
        m.show_viewport = vp
        m.show_render = rn
    high_obj_src = estado["high_obj_src"]
    high_mesh_src = estado["high_mesh_src"]
    if high_obj_src.name in bpy.data.objects:
        bpy.data.objects.remove(high_obj_src, do_unlink=True)
    if high_mesh_src.name in bpy.data.meshes and high_mesh_src.users == 0:
        bpy.data.meshes.remove(high_mesh_src)
