"""Camada L3 de postprocess: preparo de esquemas bruto-extrude e bruto-arquivo."""

from __future__ import annotations

import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

if __package__:
    from . import autorig, bake_pbr, extrude_2d, organic_sculpt
    from .postprocess_canon import _alinhar_frente_humanoide, canonicalizar
    from .postprocess_normals_uv import aplicar_weighted_normal, suavizar_por_angulo
    from .postprocess_repair import reparar_malha
    from .postprocess_scene import (
        TIPOS_ORGANICOS, _aplicar_transformes, _detectar_esqueleto_pelos_ossos,
        _resolver_opcional_bruto, criar_armadura, importar_fonte, malha_triangulada,
        objetos_colisao_ucx, unir_malhas,
    )
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import autorig
    import bake_pbr
    import extrude_2d
    import organic_sculpt
    from postprocess_canon import _alinhar_frente_humanoide, canonicalizar
    from postprocess_normals_uv import aplicar_weighted_normal, suavizar_por_angulo
    from postprocess_repair import reparar_malha
    from postprocess_scene import (
        TIPOS_ORGANICOS, _aplicar_transformes, _detectar_esqueleto_pelos_ossos,
        _resolver_opcional_bruto, criar_armadura, importar_fonte, malha_triangulada,
        objetos_colisao_ucx, unir_malhas,
    )


def _inspecionar_ou_podar_ilhas_organicas(obj) -> tuple[bool, int]:
    """Retorna ``(deve_soldar_voxel, faces_ruido_removidas)`` via BFS de faces em bmesh."""
    if obj is None or obj.type != "MESH" or not obj.data or not obj.data.polygons:
        return False, 0
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        total = len(bm.faces)
        if total <= 1:
            return False, 0
        vistos: set[int] = set()
        comps: list[list] = []
        for f0 in bm.faces:
            if f0.index in vistos:
                continue
            comp, pilha = [f0], [f0]
            vistos.add(f0.index)
            while pilha:
                fc = pilha.pop()
                for v in fc.verts:
                    for fn in v.link_faces:
                        if fn.index not in vistos:
                            vistos.add(fn.index)
                            comp.append(fn)
                            pilha.append(fn)
            comps.append(comp)
        if len(comps) <= 1:
            return False, 0
        maior_frac = max(len(c) for c in comps) / float(total)
        substanciais = sum(1 for c in comps if len(c) >= 0.05 * total)
        if substanciais >= 2 and maior_frac < 0.90:
            return True, 0
        ruido = [f for c in comps if len(c) < 0.02 * total for f in c]
        if ruido:
            bmesh.ops.delete(bm, geom=ruido, context="FACES")
            soltos = [v for v in bm.verts if not v.link_faces]
            if soltos:
                bmesh.ops.delete(bm, geom=soltos, context="VERTS")
            bm.normal_update()
            bm.to_mesh(obj.data)
            obj.data.update()
        return False, len(ruido)
    finally:
        bm.free()


def _processar_bruto_extrude(
    bruto: dict, bruto_dir: str, saida_dir: str, nome_base: str, item: dict, perfil: dict,
    cfg_suav: dict, qualidade_item: str, alpha_cards_ativo: bool, textura_max_perfil: int,
    info_gerada: dict, texturas_geradas: list[dict], decimar_fn,
) -> tuple:
    imagem_path = _resolver_opcional_bruto(
        bruto_dir, bruto.get("origem_textura")
    ) or os.path.join(bruto_dir, bruto["imagem"])
    modo = str(bruto.get("modo", "arma"))
    obj = extrude_2d.construir_malha_2d(
        imagem_path, modo=modo, nome=nome_base, saida_dir=saida_dir,
        pivot=str(item.get("pivot") or "empunhadura"),
    )
    base_tex_path = os.path.join(saida_dir, f"{nome_base}_baseColor.png")
    if os.path.isfile(base_tex_path):
        texturas_geradas.append(
            {"caminho": f"{nome_base}_baseColor.png", "papel": "textura", "bytes": os.path.getsize(base_tex_path)}
        )
    info_gerada["extrude_2d"] = {"modo": modo, "triangulos_iniciais": malha_triangulada(obj)}
    info_gerada["reparo_inicial"] = reparar_malha(obj, permitir_bordas_abertas=alpha_cards_ativo)
    limite_tris = int(item["limite_triangulos"])
    if malha_triangulada(obj) > limite_tris:
        decimar_fn(obj, limite_tris)
        info_gerada["reparo_pos_decimate"] = reparar_malha(obj, permitir_bordas_abertas=alpha_cards_ativo)
    angulo_smooth = float(cfg_suav["angulo_graus"])
    info_gerada["smooth"] = suavizar_por_angulo(obj, angulo_graus=angulo_smooth)
    weighted = False
    if cfg_suav["weighted_normals"]:
        info_gerada["weighted_normal"] = aplicar_weighted_normal(obj)
        weighted = True
    met_hint = _resolver_opcional_bruto(bruto_dir, bruto.get("metallic_hint"))
    rough_hint = _resolver_opcional_bruto(bruto_dir, bruto.get("roughness_hint"))
    if met_hint or rough_hint:
        px_ext, _ = bake_pbr.px_bake_recomendado(
            qualidade_item, bruto.get("textura_px"), teto_perfil=textura_max_perfil or None
        )
        res_hints = bake_pbr.aplicar_hints_orm_em_material(
            obj, saida_dir, nome_base, px_ext,
            metallic_hint_png=met_hint, roughness_hint_png=rough_hint,
            perfil_nome=str(perfil.get("perfil") or item.get("perfil") or ""),
        )
        if res_hints:
            texturas_geradas.extend(res_hints["arquivos_textura"])
    return obj, {}, True, angulo_smooth, weighted


def _preparar_bruto_arquivo(
    job: dict, bruto: dict, bruto_dir: str, item: dict, cfg_suav: dict, qualidade_item: str,
    alpha_cards_ativo: bool, textura_max_perfil: int, detalhe_alto_cfg, pbr_zonas_cfg,
    info_gerada: dict,
) -> dict:
    importar_fonte(os.path.join(bruto_dir, bruto["arquivo"]))
    obj = unir_malhas()
    colisao_modo = str(item.get("colisao") or "none").strip().lower()
    for ucx_obj in objetos_colisao_ucx():
        if colisao_modo == "ucx":
            _aplicar_transformes(ucx_obj)
        else:
            bpy.data.objects.remove(ucx_obj, do_unlink=True)
    rig_obj = None
    grupos: dict = {}
    armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if armatures:
        rig_obj = armatures[0]
        _aplicar_transformes(rig_obj)
        grupos = {vg.name: vg for vg in obj.vertex_groups}
    if bruto.get("canonicalizar"):
        info_gerada["canonicalizacao"] = canonicalizar(
            obj, item.get("tipo"), frente_origem=bruto.get("frente_origem")
        )

    mat_proc = str(job.get("material_procedural") or item.get("material_procedural") or bruto.get("material_procedural") or "").strip()
    if bruto.get("arquivo") == "template_body.glb" and mat_proc == "pele_humana":
        mat_proc = ""
    retopologia_pedida = str(item.get("retopologia") or bruto.get("retopologia") or "padrao").strip().lower()
    quadriflow_faces = int(item.get("quadriflow_faces") or bruto.get("quadriflow_faces") or 0)
    eh_template_ou_armadura = bruto.get("arquivo") == "template_body.glb" or bool(bruto.get("armadura_modular"))
    item_bake_check = dict(item)
    if mat_proc:
        item_bake_check["material_procedural"] = mat_proc
    if detalhe_alto_cfg:
        item_bake_check["detalhe_alto"] = detalhe_alto_cfg
    if pbr_zonas_cfg:
        item_bake_check["pbr_zonas"] = pbr_zonas_cfg
    if retopologia_pedida:
        item_bake_check["retopologia"] = retopologia_pedida
    if eh_template_ou_armadura and not (mat_proc or pbr_zonas_cfg or detalhe_alto_cfg):
        item_bake_check.pop("material", None)
    tem_pbr_nativo = bake_pbr.objeto_tem_pbr_nativo(obj)
    frente_neg_y = str(bruto.get("frente_origem") or "").strip().upper() == "-Y"
    usar_bake_high_low = bake_pbr.deve_ativar_bake_high_low(
        item_bake_check,
        tem_cor_vertice=bool(obj.data.color_attributes),
        tem_uv=bool(obj.data.uv_layers),
        tem_materiais=bool(obj.data.materials),
    )
    if (
        not usar_bake_high_low
        and tem_pbr_nativo
        and frente_neg_y
        and not eh_template_ou_armadura
        and malha_triangulada(obj) > int(item["limite_triangulos"])
    ):
        usar_bake_high_low = True
    adiar_reparo_high = (malha_triangulada(obj) > 60_000 or frente_neg_y) and tem_pbr_nativo and usar_bake_high_low
    if adiar_reparo_high:
        info_gerada["reparo_inicial"] = {"adiado_high_pbr_nativo": True, "faces_antes": len(obj.data.polygons)}
    else:
        info_gerada["reparo_inicial"] = reparar_malha(obj, permitir_bordas_abertas=alpha_cards_ativo)

    deve_soldar = bool(cfg_suav["soldar_componentes_organicos"]) or bool(
        bruto.get("soldar_componentes_organicos")
    )
    if (
        not deve_soldar
        and not adiar_reparo_high
        and cfg_suav["eh_organico"]
        and rig_obj is None
        and item.get("tipo") in ("criatura", "criatura_quadrupede", "criatura_alada", "montaria")
        and (bool(mat_proc) or bool(obj.data.color_attributes))
        and organic_sculpt.contar_componentes(obj) > 1
    ):
        if bool(obj.data.color_attributes):
            deve_soldar, ruido_rem = _inspecionar_ou_podar_ilhas_organicas(obj)
            if ruido_rem > 0:
                info_gerada["ilhas_ruido_removidas"] = ruido_rem
        else:
            deve_soldar = True
    if deve_soldar and not adiar_reparo_high and rig_obj is None and bruto.get("arquivo") != "template_body.glb":
        info_solda = organic_sculpt.soldar_componentes_organicos(obj)
        info_gerada["soldagem_organica"] = info_solda
        if info_solda.get("soldado"):
            info_gerada["reparo_pos_solda"] = reparar_malha(
                obj, permitir_bordas_abertas=alpha_cards_ativo
            )

    proteger = bool(bruto.get("proteger_decimate", False)) or cfg_suav["eh_organico"]
    angulo_smooth = float(cfg_suav["angulo_graus"])
    limite_tris = int(item["limite_triangulos"])
    px, px_sub = bake_pbr.px_bake_recomendado(
        qualidade_item,
        bruto.get("textura_px"),
        teto_perfil=textura_max_perfil or None,
    )
    return {
        "obj": obj,
        "rig_obj": rig_obj,
        "grupos": grupos,
        "mat_proc": mat_proc,
        "retopologia_pedida": retopologia_pedida,
        "quadriflow_faces": quadriflow_faces,
        "proteger": proteger,
        "angulo_smooth": angulo_smooth,
        "limite_tris": limite_tris,
        "px": px,
        "px_sub": px_sub,
        "qualidade_item": str(qualidade_item or "").strip().lower(),
        "item_bake_check": item_bake_check,
        "usar_bake_high_low": usar_bake_high_low,
    }


def _reduzir_low(
    alvo_o, lim_t: int, ctx: dict, cfg_suav: dict, info_gerada: dict, retopo_fn, decimar_fn
) -> tuple[int, bool]:
    qf_aplicado = False
    retopo = ctx["retopologia_pedida"]
    qf_faces = ctx["quadriflow_faces"]
    proteger = ctx["proteger"]
    if retopo == "quadriflow":
        if retopo_fn(alvo_o, lim_t, alvo_faces=qf_faces):
            qf_aplicado = True
            info_gerada["retopologia"] = "quadriflow"
            if malha_triangulada(alvo_o) > lim_t:
                decimar_fn(alvo_o, lim_t, proteger_cabeca_maos=proteger)
        elif malha_triangulada(alvo_o) > lim_t:
            decimar_fn(alvo_o, lim_t, proteger_cabeca_maos=proteger)
    elif malha_triangulada(alvo_o) > lim_t:
        decimar_fn(alvo_o, lim_t, proteger_cabeca_maos=proteger)
    if cfg_suav["corrective_smooth"] and malha_triangulada(alvo_o) >= 120:
        if ctx.get("usar_bake_high_low"):
            qual_low = str(ctx.get("qualidade_item") or "").strip().lower()
            if qual_low not in ("hero", "ultra"):
                info_gerada["corrective_smooth"] = organic_sculpt.aplicar_corrective_smooth(
                    alvo_o, iteracoes=1, fator=0.10
                )
        else:
            info_gerada["corrective_smooth"] = organic_sculpt.aplicar_corrective_smooth(
                alvo_o, iteracoes=2, fator=0.35
            )
    return malha_triangulada(alvo_o), qf_aplicado


def _reduzir_e_suavizar_sem_bake(
    obj,
    rig_obj,
    bruto: dict,
    ctx: dict,
    cfg_suav: dict,
    alpha_cards_ativo: bool,
    info_gerada: dict,
    retopo_fn,
    decimar_fn,
    uv_fn,
) -> tuple[bool, bool, bool]:
    if not obj.data.uv_layers:
        raise RuntimeError(
            "malha importada sem UV e sem cor por vertice: nao ha como assar textura"
        )
    limite_tris = ctx["limite_tris"]
    proteger = ctx["proteger"]
    angulo_smooth = ctx["angulo_smooth"]
    qf_aplicado = False
    info_gerada["triangulos_antes_decimate"] = malha_triangulada(obj)
    if ctx["retopologia_pedida"] == "quadriflow":
        if retopo_fn(obj, limite_tris, alvo_faces=ctx["quadriflow_faces"]):
            qf_aplicado = True
            info_gerada["retopologia"] = "quadriflow"
            uv_fn(obj)
    if malha_triangulada(obj) > limite_tris:
        decimar_fn(obj, limite_tris, proteger_cabeca_maos=proteger)
        info_gerada["reparo_pos_decimate"] = reparar_malha(
            obj, permitir_bordas_abertas=alpha_cards_ativo
        )
        if not obj.data.uv_layers:
            info_gerada["uv"] = uv_fn(obj)
        if cfg_suav["corrective_smooth"] and malha_triangulada(obj) >= 120:
            info_gerada["corrective_smooth"] = organic_sculpt.aplicar_corrective_smooth(
                obj, iteracoes=2, fator=0.35
            )
    elif bruto.get("armadura_modular"):
        info_gerada["reparo_pos_decimate"] = reparar_malha(
            obj, permitir_bordas_abertas=alpha_cards_ativo
        )
    info_gerada["smooth"] = suavizar_por_angulo(obj, angulo_graus=angulo_smooth)
    weighted = False
    if rig_obj is None and cfg_suav["weighted_normals"] and not bruto.get("armadura_modular"):
        info_gerada["weighted_normal"] = aplicar_weighted_normal(obj)
        weighted = True
    info_gerada["triangulos_pos_decimate"] = malha_triangulada(obj)
    return True, weighted, qf_aplicado


def _resolver_esqueleto_auto_rig(job: dict, item: dict, perfil: dict) -> tuple[str, str] | None:
    if not (bool(item.get("auto_rig")) and item.get("tipo") in TIPOS_ORGANICOS):
        return None
    tipo_item = str(job.get("tipo") or item.get("tipo") or "personagem_humanoide")
    esq_padrao = (perfil.get("rig") or {}).get("esqueleto_padrao") or "godot-humanoid@1"
    if not item.get("esqueleto"):
        mapas_rig = (perfil.get("rig") or {}).get("mapas") or {}
        if tipo_item == "criatura_quadrupede" and (
            "quadruped@1" in mapas_rig or str(perfil.get("perfil", "")).startswith("godot")
        ):
            esq_padrao = "quadruped@1"
        elif tipo_item in ("criatura_alada", "montaria") and (
            "winged_mount@1" in mapas_rig or str(perfil.get("perfil", "")).startswith("godot")
        ):
            esq_padrao = "winged_mount@1"
    return tipo_item, str(item.get("esqueleto") or esq_padrao)


def _prealinhar_se_criatura_rig(
    obj,
    job: dict,
    item: dict,
    perfil: dict,
    *,
    autorig_mod=None,
) -> None:
    ar = autorig_mod if autorig_mod is not None else autorig
    res = _resolver_esqueleto_auto_rig(job, item, perfil)
    if res is None:
        return
    tipo_item, esq = res
    humanos = set(
        getattr(ar, "_ESQUELETOS_HUMANOS", ("godot-humanoid@1", "godot-humanoid-aa@1", "r15@1"))
    )
    criaturas = set(getattr(ar, "_ESQUELETOS_CRIATURA", ("quadruped@1", "winged_mount@1")))
    if esq in humanos:
        return
    if esq in criaturas or tipo_item in (
        "criatura",
        "criatura_quadrupede",
        "criatura_alada",
        "montaria",
    ):
        fn_align = getattr(ar, "_alinhar_orientacao_criatura", None)
        if callable(fn_align):
            com_asas = esq == "winged_mount@1" or tipo_item == "criatura_alada"
            fn_align(obj, com_asas=com_asas)


def _clonar_high_nao_linkado(obj, nome_base: str):
    high_mesh = obj.data.copy()
    high_mesh.name = f"{nome_base}_high_src_mesh"
    high_obj = bpy.data.objects.new(f"{nome_base}_high_src", high_mesh)
    high_obj.matrix_world = obj.matrix_world.copy()
    return high_obj


def _preparar_low_antes_escala(
    obj,
    ctx: dict,
    info_gerada: dict,
    alpha_cards_ativo: bool,
    bruto: dict,
    rig_obj,
    cfg_suav: dict,
    retopo_fn,
    decimar_fn,
    uv_fn,
) -> tuple[bool, bool, bool]:
    info_gerada["triangulos_antes_decimate"] = malha_triangulada(obj)
    lim_t = int(ctx["limite_tris"])
    _, qf_ok = _reduzir_low(obj, lim_t, ctx, cfg_suav, info_gerada, retopo_fn, decimar_fn)
    info_reparo = reparar_malha(obj, permitir_bordas_abertas=alpha_cards_ativo)
    if malha_triangulada(obj) > lim_t:
        _, qf2 = _reduzir_low(
            obj, max(50, int(lim_t * 0.97)), ctx, cfg_suav, info_gerada, retopo_fn, decimar_fn
        )
        qf_ok = qf_ok or qf2
        info_reparo = reparar_malha(obj, permitir_bordas_abertas=alpha_cards_ativo)
    info_gerada["reparo_pos_decimate"] = info_reparo
    info_gerada["triangulos_pos_decimate"] = malha_triangulada(obj)
    info_gerada["smooth"] = suavizar_por_angulo(obj, angulo_graus=ctx["angulo_smooth"])
    info_gerada["uv"] = uv_fn(obj)
    weighted = False
    if cfg_suav["weighted_normals"] and rig_obj is None and not bruto.get("armadura_modular"):
        info_gerada["weighted_normal"] = aplicar_weighted_normal(obj)
        weighted = True
    return True, weighted, qf_ok


def _sincronizar_high_pos_rig(
    high_obj_src,
    obj,
    info_gerada: dict,
    rig_criado_agora: bool,
) -> None:
    alinh = info_gerada.get("alinhamento_frente_pos_decimate")
    girado = isinstance(alinh, dict) and bool(alinh.get("girado_frente"))
    if girado:
        rot_z = Matrix.Rotation(math.pi, 4, "Z")
        for v in high_obj_src.data.vertices:
            v.co = rot_z @ v.co
        high_obj_src.data.update()
    if (girado or rig_criado_agora) and high_obj_src.data.vertices and obj.data.vertices:
        xs_o = [v.co.x for v in obj.data.vertices]
        ys_o = [v.co.y for v in obj.data.vertices]
        zs_o = [v.co.z for v in obj.data.vertices]
        xs_h = [v.co.x for v in high_obj_src.data.vertices]
        ys_h = [v.co.y for v in high_obj_src.data.vertices]
        zs_h = [v.co.z for v in high_obj_src.data.vertices]
        dx = 0.5 * (min(xs_o) + max(xs_o)) - 0.5 * (min(xs_h) + max(xs_h))
        dy = 0.5 * (min(ys_o) + max(ys_o)) - 0.5 * (min(ys_h) + max(ys_h))
        dz = min(zs_o) - min(zs_h)
        if abs(dx) > 1e-6 or abs(dy) > 1e-6 or abs(dz) > 1e-6:
            delta = Vector((dx, dy, dz))
            for v in high_obj_src.data.vertices:
                v.co += delta
            high_obj_src.data.update()


def _transformar_high_escala(high_obj_src, escala: float, deslocamento: Vector) -> None:
    for v in high_obj_src.data.vertices:
        v.co = (v.co * escala) + deslocamento
    high_obj_src.data.update()


def _aplicar_rig_bruto_arquivo(
    obj,
    rig_obj,
    grupos: dict,
    job: dict,
    item: dict,
    perfil: dict,
    bruto: dict,
    info_gerada: dict,
    esqueleto_pedido: str | None,
    esqueleto_efetivo: str | None,
    *,
    autorig_mod=None,
) -> tuple:
    ar = autorig_mod if autorig_mod is not None else autorig
    if (
        bruto.get("canonicalizar")
        and item.get("tipo") == "personagem_humanoide"
        and str(bruto.get("frente_origem") or "").strip().upper() != "-Y"
    ):
        info_gerada["alinhamento_frente_pos_decimate"] = _alinhar_frente_humanoide(obj)
    res_esq = _resolver_esqueleto_auto_rig(job, item, perfil)
    if res_esq is not None:
        tipo_item, esq = res_esq
        esqueleto_pedido = esq
        esqueleto_efetivo = esq
        fn_rig_tipo = getattr(ar, "auto_rigar_por_tipo", None)
        if callable(fn_rig_tipo):
            rig_obj, grupos = fn_rig_tipo(obj, esq, criar_armadura, tipo=tipo_item)
        else:
            rig_obj, grupos = ar.auto_rigar_humanoide(obj, esq, criar_armadura)
        if rig_obj is not None:
            detectado = _detectar_esqueleto_pelos_ossos(rig_obj)
            if detectado is not None:
                esqueleto_efetivo = detectado
    return rig_obj, grupos, esqueleto_pedido, esqueleto_efetivo
