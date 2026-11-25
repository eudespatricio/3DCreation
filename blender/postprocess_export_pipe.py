"""Camada L3 de postprocess: pos-escala, sockets, medidas LOD0, export de LODs e colisores."""

from __future__ import annotations

import os
import shutil
import sys

import bpy

if __package__:
    from . import autorig, bake_pbr, postprocess_deform
    from .postprocess_lod_col import (
        _tem_normal_map,
        aplicar_lod,
        clonar_malha,
        criar_colisor,
        exportar,
    )
    from .postprocess_normals_uv import (
        _enquadrar_texturas_no_teto,
        aplicar_weighted_normal,
        suavizar_por_angulo,
    )
    from .postprocess_repair import reparar_malha
    from .postprocess_scene import (
        _escrever_concept_sidecar,
        animar,
        bbox_local,
        malha_triangulada,
        medir_geometria,
    )
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import autorig
    import bake_pbr
    import postprocess_deform
    from postprocess_lod_col import (
        _tem_normal_map,
        aplicar_lod,
        clonar_malha,
        criar_colisor,
        exportar,
    )
    from postprocess_normals_uv import (
        _enquadrar_texturas_no_teto,
        aplicar_weighted_normal,
        suavizar_por_angulo,
    )
    from postprocess_repair import reparar_malha
    from postprocess_scene import (
        _escrever_concept_sidecar,
        animar,
        bbox_local,
        malha_triangulada,
        medir_geometria,
    )


def _reparar_e_suavizar_pos_escala(
    obj,
    rig_obj,
    escala: float,
    alpha_cards_ativo: bool,
    smooth_normals_aplicado: bool,
    angulo_smooth_final: float,
    weighted_normals_aplicado: bool,
    info_gerada: dict,
    *,
    rig_pre_existente: bool | None = None,
) -> None:
    geom_pos_escala = medir_geometria(obj, permitir_bordas_abertas=alpha_cards_ativo)
    if (
        geom_pos_escala["nao_manifold"] > 0
        or geom_pos_escala["degeneradas"] > 0
        or escala < 0.999
    ):
        info_gerada["reparo_pos_escala"] = reparar_malha(
            obj, permitir_bordas_abertas=alpha_cards_ativo
        )
        if smooth_normals_aplicado:
            info_gerada["smooth_pos_escala"] = suavizar_por_angulo(
                obj, angulo_graus=angulo_smooth_final
            )
            pode_weighted = (
                (not rig_pre_existente)
                if rig_pre_existente is not None
                else (rig_obj is None)
            )
            if weighted_normals_aplicado and pode_weighted:
                arm_mods = [
                    (m, m.show_viewport, m.show_render)
                    for m in obj.modifiers
                    if m.type == "ARMATURE"
                ]
                for m, _vp, _rn in arm_mods:
                    m.show_viewport = False
                    m.show_render = False
                try:
                    info_gerada["weighted_normal"] = aplicar_weighted_normal(obj)
                finally:
                    for m, vp, rn in arm_mods:
                        m.show_viewport = vp
                        m.show_render = rn


def _pos_escala_rig_e_animacao(
    obj,
    rig_obj,
    grupos: dict,
    job: dict,
    item: dict,
    bruto: dict,
    escala: float,
    alpha_cards_ativo: bool,
    smooth_normals_aplicado: bool,
    angulo_smooth_final: float,
    weighted_normals_aplicado: bool,
    info_gerada: dict,
    *,
    autorig_mod=None,
    pular_reparo_pos_escala: bool = False,
    perfil: dict | None = None,
    saida_dir: str | None = None,
) -> tuple[list[dict], list[dict]]:
    ar = autorig_mod if autorig_mod is not None else autorig
    if not pular_reparo_pos_escala:
        _reparar_e_suavizar_pos_escala(
            obj,
            rig_obj,
            escala,
            alpha_cards_ativo,
            smooth_normals_aplicado,
            angulo_smooth_final,
            weighted_normals_aplicado,
            info_gerada,
        )

    smart_fit_cfg = job.get("smart_fit") or item.get("smart_fit") or bruto.get("smart_fit")
    if smart_fit_cfg:
        try:
            if __package__:
                from . import smart_fit
            else:
                import smart_fit  # type: ignore[import-not-found]
        except ImportError:
            info_gerada["smart_fit"] = {"aplicado": False, "motivo": "modulo_ausente"}
        else:
            fn_sf = getattr(smart_fit, "aplicar_smart_fit_job", None)
            if callable(fn_sf):
                job_sf = dict(job)
                job_sf.setdefault("smart_fit", smart_fit_cfg)
                corpo_obj = None
                if isinstance(smart_fit_cfg, dict):
                    ref_corpo = (
                        smart_fit_cfg.get("corpo")
                        or smart_fit_cfg.get("alvo")
                        or job.get("corpo_obj")
                        or bruto.get("corpo_obj")
                        or bruto.get("corpo")
                    )
                    fn_res = getattr(smart_fit, "_resolver_objeto_cena", None)
                    if ref_corpo is not None and callable(fn_res):
                        corpo_obj = fn_res(ref_corpo)
                if corpo_obj is None:
                    fn_det = getattr(smart_fit, "_detectar_corpo_cena", None)
                    if callable(fn_det):
                        corpo_obj = fn_det(peca_obj=obj, rig_obj=rig_obj)
                if corpo_obj is obj:
                    corpo_obj = None
                info_sf = fn_sf(obj, job_sf, corpo_obj=corpo_obj, rig_obj=rig_obj)
                if isinstance(info_sf, dict):
                    info_gerada["smart_fit"] = info_sf

    if rig_obj is not None and grupos:
        if obj.parent is not rig_obj:
            obj.parent = rig_obj
        if not any(m.type == "ARMATURE" for m in obj.modifiers):
            mod = obj.modifiers.new("armature", "ARMATURE")
            mod.object = rig_obj

    perfil_eff = perfil if perfil is not None else (job.get("perfil") if isinstance(job, dict) else None)
    saida_eff = saida_dir if saida_dir is not None else (job.get("saida_dir") if isinstance(job, dict) else None)
    if rig_obj is not None and bruto.get("schema") != "forge3d/bruto-blocky@1":
        fn_res_post = getattr(ar, "resolver_postura_perfil", None)
        if callable(fn_res_post):
            cfg_post = fn_res_post(perfil_eff, item)
            if cfg_post.get("modo_rest") == "natural_relaxada":
                if saida_eff and (item.get("rota") in ("mesh", "i23d") or bruto.get("concept")):
                    exportar(os.path.join(saida_eff, "_g15_apose_ref.glb"), [obj], False, com_animacao=False, export_tangents=False, export_image_format="NONE")
                    info_gerada["g15_apose_ref"] = "_g15_apose_ref.glb"
                if callable(fn_assar := getattr(ar, "assar_pose_rest_natural", None)):
                    raw_seed = item.get("seed") if "seed" in item else job.get("seed")
                    seed_eff = raw_seed if (raw_seed is not None and cfg_post.get("variacao_seed", True)) else None
                    info_gerada["pose_natural"] = fn_assar(
                        obj, rig_obj,
                        angulo_alvo_graus=float(cfg_post.get("angulo_braco_graus", 14.0)),
                        seed=seed_eff,
                        postura_preset=cfg_post.get("preset"),
                    )

    animacoes_geradas: list[dict] = []
    if rig_obj is not None and job.get("clipes"):
        animacoes_geradas = animar(rig_obj, job["clipes"])

    sockets_extraidos: list[dict] = []
    if rig_obj is not None:
        fn_sockets = getattr(ar, "extrair_sockets", None)
        if callable(fn_sockets):
            solicitados_sockets = job.get("sockets") or item.get("sockets")
            try:
                sockets_extraidos = list(
                    fn_sockets(rig_obj, mesh_obj=obj, solicitados=solicitados_sockets) or []
                )
            except TypeError:
                sockets_extraidos = list(fn_sockets(rig_obj) or [])
        if callable(fn_anc := getattr(ar, "extrair_ancoras", None)):
            if isinstance(ancoras := fn_anc(rig_obj), dict) and ancoras:
                info_gerada["ancoras"] = ancoras

    return animacoes_geradas, sockets_extraidos


def _montar_medidas_lod0(
    obj,
    rig_obj,
    escala_saida: float,
    origem_regra: str,
    escala_preservada: bool,
    animacoes_geradas: list[dict],
    sockets_extraidos: list[dict],
    esqueleto_efetivo: str | None,
    esqueleto_pedido: str | None,
    alpha_cards_ativo: bool,
    sombreamento_meta: dict,
    orientacao_export_meta: dict,
    textura_max_perfil: int,
) -> dict:
    minimo, maximo = bbox_local()
    bbox_export = [maximo.x - minimo.x, maximo.z - minimo.z, maximo.y - minimo.y]
    medidas_base: dict = {
        "triangulos": malha_triangulada(obj),
        "vertices": len(obj.data.vertices),
        "bbox_export": bbox_export,
        "bbox_m": [v / escala_saida for v in bbox_export],
        "escala_saida": escala_saida,
        "materiais": len(obj.data.materials),
        "ossos": len(rig_obj.data.bones) if rig_obj is not None else 0,
        "animacoes": animacoes_geradas,
        "pivo_regra": origem_regra,
        "escala_preservada": escala_preservada,
        "aabb_min": [minimo.x / escala_saida, minimo.z / escala_saida, -maximo.y / escala_saida],
        "aabb_max": [maximo.x / escala_saida, maximo.z / escala_saida, -minimo.y / escala_saida],
        "sombreamento": sombreamento_meta,
        "orientacao_export": orientacao_export_meta,
    }
    if sockets_extraidos:
        medidas_base["sockets"] = sockets_extraidos
    if rig_obj is not None and hasattr(autorig, "extrair_ancoras"):
        if anc_med := autorig.extrair_ancoras(rig_obj):
            medidas_base["ancoras"] = anc_med
    if rig_obj is not None and esqueleto_efetivo:
        medidas_base["esqueleto"] = esqueleto_efetivo
    if esqueleto_pedido:
        medidas_base["esqueleto_pedido"] = esqueleto_pedido
    medidas_base.update(medir_geometria(obj, permitir_bordas_abertas=alpha_cards_ativo))
    deform_anim = postprocess_deform.medir_deformacao_animacao(
        obj, rig_obj, animacoes_geradas
    )
    if deform_anim is not None:
        medidas_base["deformacao_anim"] = deform_anim
    if textura_max_perfil > 0:
        _enquadrar_texturas_no_teto(textura_max_perfil)
    return medidas_base


def _exportar_lods(
    obj,
    rig_obj,
    grupos: dict,
    job: dict,
    item: dict,
    perfil: dict,
    bruto: dict,
    saida_dir: str,
    nome_base: str,
    qualidade_item: str,
    alpha_cards_ativo: bool,
    smooth_normals_aplicado: bool,
    angulo_smooth_final: float,
    animacoes_geradas: list[dict],
    texturas_geradas: list[dict],
    medidas_base: dict,
    reduzir_orcamento_fn,
) -> list[dict]:
    arquivos: list[dict] = []
    lods = item.get("lod") or [100]
    for nivel, pct in enumerate(lods):
        if nivel == 0:
            alvo_obj = obj
        else:
            alvo_obj = clonar_malha(obj, f"{nome_base}_LOD{nivel}")
            if alvo_obj.data is not None:
                alvo_obj.data.name = f"{nome_base}_LOD{nivel}"
            if rig_obj is not None and grupos:
                alvo_obj.parent = rig_obj
                mod_lod = alvo_obj.modifiers.new("armature", "ARMATURE")
                mod_lod.object = rig_obj
            info_lod = aplicar_lod(
                alvo_obj,
                pct,
                blocky=(bruto["schema"] == "forge3d/bruto-blocky@1"),
            )
            reparar_malha(alvo_obj, permitir_bordas_abertas=alpha_cards_ativo)
            if smooth_normals_aplicado:
                suavizar_por_angulo(alvo_obj, angulo_graus=angulo_smooth_final)
            medidas_base.setdefault("lod_modo", {})[str(nivel)] = info_lod
        nome = job["nome_arquivo"] if nivel == 0 else f"{job['nome_base']}_LOD{nivel}.glb"
        caminho = os.path.join(saida_dir, nome)
        selecionados = [alvo_obj] + ([rig_obj] if rig_obj is not None else [])
        usar_tangents = _tem_normal_map(
            [alvo_obj],
            sidecar_dir=saida_dir,
            nome_base=nome_base,
            texturas_geradas=texturas_geradas,
        )
        img_fmt = "AUTO" if nivel == 0 else "NONE"
        exportar(
            caminho,
            selecionados,
            rig_obj is not None,
            com_animacao=bool(animacoes_geradas),
            export_tangents=usar_tangents,
            export_image_format=img_fmt,
        )
        bytes_max_kb = int((perfil.get("validacao") or {}).get("bytes_max_kb") or 0)
        if qualidade_item in ("hero", "ultra") and bytes_max_kb > 0:
            bytes_max_kb = max(bytes_max_kb, 4096)
        if nivel == 0 and bytes_max_kb > 0:
            perfil_nome_low = str(perfil.get("perfil") or item.get("perfil") or "").strip().lower()
            eh_roblox_ultra = perfil_nome_low.startswith("roblox") and str(qualidade_item or "").strip().lower() == "ultra"
            piso_orc = 1024 if eh_roblox_ultra else bake_pbr.PISO_PX_ORCAMENTO
            reexp_cb = lambda c=caminho, s=selecionados, t=usar_tangents, fmt=img_fmt: exportar(  # noqa: E731
                c,
                s,
                rig_obj is not None,
                com_animacao=bool(animacoes_geradas),
                export_tangents=t,
                export_image_format=fmt,
            )
            if texturas_geradas:
                bake_pbr.ajustar_resolucao_orcamento(
                    alvo_obj,
                    saida_dir,
                    texturas_geradas,
                    caminho,
                    bytes_max_kb * 1024,
                    reexp_cb,
                    piso_px=piso_orc,
                )
            if hasattr(reduzir_orcamento_fn, "__code__") and "piso_px" in reduzir_orcamento_fn.__code__.co_varnames:
                reduzir_orcamento_fn(caminho, bytes_max_kb * 1024, reexp_cb, piso_px=piso_orc)
            elif not eh_roblox_ultra:
                reduzir_orcamento_fn(caminho, bytes_max_kb * 1024, reexp_cb)
        arquivos.append(
            {
                "caminho": nome,
                "papel": "mesh" if nivel == 0 else "lod",
                "nivel": nivel,
                "triangulos": malha_triangulada(alvo_obj),
            }
        )
        if nivel > 0:
            bpy.data.objects.remove(alvo_obj, do_unlink=True)
    return arquivos


def _finalizar_colisor_e_resultado(
    obj,
    rig_obj,
    job: dict,
    item: dict,
    perfil: dict,
    bruto: dict,
    bruto_dir: str,
    saida_dir: str,
    nome_base: str,
    escala_saida: float,
    esqueleto_efetivo: str | None,
    info_gerada: dict,
    detalhe_alto_cfg,
    pbr_zonas_cfg,
    texturas_geradas: list[dict],
    sockets_extraidos: list[dict],
    sombreamento_meta: dict,
    orientacao_export_meta: dict,
    medidas_base: dict,
    arquivos: list[dict],
) -> dict:
    colisores = criar_colisor(
        obj, item.get("colisao"), job["nome_base"], perfil["colisao"]["max_partes"]
    )
    if colisores:
        arquivo_colisor = f"{job['nome_base']}_colisao.glb"
        exportar(
            os.path.join(saida_dir, arquivo_colisor),
            colisores,
            False,
            export_image_format="NONE",
        )
        arquivos.append(
            {"caminho": arquivo_colisor, "papel": "colisor", "partes": len(colisores)}
        )

    caminhos_gerados = {t["caminho"] for t in texturas_geradas}
    nome_atlas_saida = f"{job['nome_base']}_baseColor.png"
    if bruto.get("atlas") and nome_atlas_saida not in caminhos_gerados:
        destino_atlas = os.path.join(saida_dir, nome_atlas_saida)
        shutil.copyfile(os.path.join(bruto_dir, bruto["atlas"]), destino_atlas)
        arquivos.append(
            {
                "caminho": nome_atlas_saida,
                "papel": "textura",
                "bytes": os.path.getsize(destino_atlas),
            }
        )

    for tex in texturas_geradas:
        arquivos.append(
            {
                "caminho": tex["caminho"],
                "papel": tex["papel"],
                "bytes": int(
                    tex.get("bytes")
                    or os.path.getsize(os.path.join(saida_dir, tex["caminho"]))
                ),
            }
        )

    if info_gerada:
        medidas_base["gerada"] = info_gerada
    if isinstance(detalhe_alto_cfg, dict) and detalhe_alto_cfg:
        medidas_base["detalhe_alto"] = dict(detalhe_alto_cfg)
    if isinstance(pbr_zonas_cfg, list) and pbr_zonas_cfg:
        medidas_base["pbr_zonas"] = list(pbr_zonas_cfg)
    for chave_info in ("smart_fit", "ancoras", "pose_natural", "g15_apose_ref"):
        val_info = info_gerada.get(chave_info)
        if isinstance(val_info, dict) and val_info:
            medidas_base[chave_info] = dict(val_info)
        elif isinstance(val_info, str) and val_info:
            medidas_base[chave_info] = val_info
    medidas_base["partes_colisao"] = len(colisores)
    medidas_base["esqueleto"] = esqueleto_efetivo if rig_obj is not None else None
    medidas_base["lod"] = [
        {"nivel": a["nivel"], "triangulos": a["triangulos"]}
        for a in arquivos
        if a["papel"] in ("mesh", "lod")
    ]

    if bruto.get("concept"):
        sidecar_concept = _escrever_concept_sidecar(saida_dir, nome_base, bruto["concept"])
        if sidecar_concept is not None:
            arquivos.append(sidecar_concept)

    resultado: dict = {
        "ok": True,
        "medidas": medidas_base,
        "arquivos": arquivos,
        "escala_saida": escala_saida,
        "sombreamento": sombreamento_meta,
        "orientacao_export": orientacao_export_meta,
    }
    if sockets_extraidos:
        resultado["sockets"] = sockets_extraidos
    for chave_med in ("detalhe_alto", "pbr_zonas", "smart_fit", "ancoras", "pose_natural", "g15_apose_ref"):
        if val_med := medidas_base.get(chave_med):
            resultado[chave_med] = val_med
    if bruto.get("concept"):
        resultado["concept"] = bruto["concept"]
    return resultado
