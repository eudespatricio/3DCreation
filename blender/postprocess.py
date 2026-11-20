"""Script bpy do Forge3D — roda com ``blender --background --python``.

Canal unico: arquivo JSON de entrada e arquivo JSON de saida (I9). Nada de parse de stdout.
"""

from __future__ import annotations

import os
import sys
import traceback

import bpy
from mathutils import Vector

if __package__:
    from . import autorig, bake_pbr, extrude_2d, organic_sculpt  # noqa: F401
    from . import postprocess_bruto as _br
    from . import postprocess_canon as _ca
    from . import postprocess_export_pipe as _ep
    from . import postprocess_lod_col as _lc
    from . import postprocess_normals_uv as _nuv
    from . import postprocess_repair as _rp
    from . import postprocess_scene as _sc
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import autorig  # noqa: F401
    import bake_pbr  # noqa: F401
    import extrude_2d  # noqa: F401
    import organic_sculpt  # noqa: F401
    import postprocess_bruto as _br
    import postprocess_canon as _ca
    import postprocess_export_pipe as _ep
    import postprocess_lod_col as _lc
    import postprocess_normals_uv as _nuv
    import postprocess_repair as _rp
    import postprocess_scene as _sc

TIPOS_ORGANICOS = _sc.TIPOS_ORGANICOS
PARTES_RIGIDAS = _sc.PARTES_RIGIDAS
LIMIAR_SCORE_FRENTE = _sc.LIMIAR_SCORE_FRENTE
FACES_CUBO = _sc.FACES_CUBO
TEX_PX_GERADA = _sc.TEX_PX_GERADA

jload = _sc.jload
jsave = _sc.jsave
limpar_cena = _sc.limpar_cena
objetos_malha = _sc.objetos_malha
objetos_colisao_ucx = _sc.objetos_colisao_ucx
material_atlas = _sc.material_atlas
construir_blocky = _sc.construir_blocky
criar_armadura = _sc.criar_armadura
_limpar_objetos_gltf_internos = _sc._limpar_objetos_gltf_internos
importar_fonte = _sc.importar_fonte
_selecionar = _sc._selecionar
_aplicar_transformes = _sc._aplicar_transformes
unir_malhas = _sc.unir_malhas
transformar_armadura = _sc.transformar_armadura
bbox_local = _sc.bbox_local
transformar = _sc.transformar
transformar_colisores_ucx = _sc.transformar_colisores_ucx
calcular_pivo = _sc.calcular_pivo
malha_triangulada = _sc.malha_triangulada
medir_geometria = _sc.medir_geometria
animar = _sc.animar
_resolver_opcional_bruto = _sc._resolver_opcional_bruto
_escrever_concept_sidecar = _sc._escrever_concept_sidecar
_detectar_esqueleto_pelos_ossos = _sc._detectar_esqueleto_pelos_ossos

_remover_ilhas_de_uma_face = _rp._remover_ilhas_de_uma_face
_fechar_ciclos_borda_fan = _rp._fechar_ciclos_borda_fan
_preencher_bordas_e_triangular = _rp._preencher_bordas_e_triangular
_colapsar_faces_degeneradas = _rp._colapsar_faces_degeneradas
reparar_malha = _rp.reparar_malha
_media_vizinhos = _rp._media_vizinhos
_suavizar_taubin_bm = _rp._suavizar_taubin_bm
_relaxar_arestas_dobradas_bm = _rp._relaxar_arestas_dobradas_bm

_extensao_faixa = _ca._extensao_faixa
canonicalizar = _ca.canonicalizar
_medir_score_frente_humanoide = _ca._medir_score_frente_humanoide
_alinhar_frente_humanoide = _ca._alinhar_frente_humanoide

_resolver_config_suavizacao = _nuv._resolver_config_suavizacao
suavizar_por_angulo = _nuv.suavizar_por_angulo
aplicar_weighted_normal = _nuv.aplicar_weighted_normal
gerar_uv_lightmap = _nuv.gerar_uv_lightmap
assar_cor_vertices = _nuv.assar_cor_vertices
_imagens_exportaveis = _nuv._imagens_exportaveis
_redimensionar_imagem = _nuv._redimensionar_imagem
_pot_abaixo = _nuv._pot_abaixo
_enquadrar_texturas_no_teto = _nuv._enquadrar_texturas_no_teto

clonar_malha = _lc.clonar_malha
aplicar_decimate = _lc.aplicar_decimate
_componentes_indices = _lc._componentes_indices
_volume_componente = _lc._volume_componente
aplicar_lod = _lc.aplicar_lod
criar_colisor = _lc.criar_colisor
_ilhas = _lc._ilhas
_tem_normal_map = _lc._tem_normal_map
exportar = _lc.exportar


def decimar(obj, alvo_tris: int, proteger_cabeca_maos: bool = False) -> int:
    return _rp.decimar(
        obj,
        alvo_tris,
        proteger_cabeca_maos=proteger_cabeca_maos,
        taubin_fn=_suavizar_taubin_bm,
    )


def retopologizar_quadriflow(obj, alvo_tris: int, alvo_faces: int = 0) -> bool:
    """Retopologia Quadriflow deterministica; devolve False e restaura malha se falhar ou zerar faces."""
    if obj is None or obj.type != "MESH" or not obj.data or len(obj.data.polygons) < 4:
        return False
    _selecionar(obj)
    alvos_quads = int(alvo_faces) if int(alvo_faces or 0) >= 100 else max(250, int(alvo_tris) // 2)
    backup = obj.data.copy()
    try:
        nm_edges, nm_verts = _rp._contar_nao_manifold(obj)
        tris = malha_triangulada(obj)
        remeshed = False
        if nm_edges > 0 or nm_verts > 0 or tris > 60_000:
            _rp._remesh_voxel_preservando_partes(obj)
            alvo_pre = max(alvos_quads * 3, 24_000)
            if malha_triangulada(obj) > alvo_pre:
                decimar(obj, alvo_pre)
            reparar_malha(obj)
            remeshed = True
            _selecionar(obj)
        props = set(bpy.ops.object.quadriflow_remesh.get_rna_type().properties.keys())
        kw = {
            "use_mesh_symmetry": False,
            "use_preserve_sharp": not remeshed,
            "use_preserve_boundary": True,
            "preserve_attributes": True,
            "smooth_normals": True,
            "target_faces": alvos_quads,
            "seed": 0,
        }
        kw = {k: v for k, v in kw.items() if k in props}
        bpy.ops.object.quadriflow_remesh(**kw)
        if len(obj.data.polygons) < 4 or len(obj.data.vertices) < 4:
            raise RuntimeError("quadriflow retornou 0 faces")
        bpy.data.meshes.remove(backup)
        return True
    except (RuntimeError, TypeError, ValueError, AttributeError) as exc:
        print(f"[postprocess] aviso quadriflow em {obj.name}: {exc}", file=sys.stderr)
        antiga = obj.data
        obj.data = backup
        if antiga.users == 0:
            bpy.data.meshes.remove(antiga)
        return False


def desdobrar_uv(obj, margem: float = 0.02) -> str:
    return _nuv.desdobrar_uv(obj, margem=margem)


def _reduzir_imagens_embutidas_orcamento(
    caminho_glb: str,
    bytes_max: int,
    exportar_fn,
) -> None:
    """Encolhe texturas embutidas (incluindo .mhclo) preservando POT e piso de 512px (G9)."""
    if bytes_max <= 0 or not os.path.isfile(caminho_glb):
        return
    if os.path.getsize(caminho_glb) <= bytes_max:
        return
    piso_px = 512
    for teto in (1024, piso_px):
        mudou = False
        for img in _imagens_exportaveis():
            w, h = int(img.size[0]), int(img.size[1])
            maior = max(w, h)
            if maior > teto:
                fator = float(teto) / float(maior)
                min_w = piso_px if w >= piso_px else w
                min_h = piso_px if h >= piso_px else h
                nw = _pot_abaixo(max(min_w, int(round(w * fator))))
                nh = _pot_abaixo(max(min_h, int(round(h * fator))))
                if nw != w or nh != h:
                    _redimensionar_imagem(img, nw, nh)
                    mudou = True
        if mudou:
            exportar_fn()
            if os.path.getsize(caminho_glb) <= bytes_max:
                return


def processar(job: dict) -> dict:
    saida_dir = job["saida_dir"]
    os.makedirs(saida_dir, exist_ok=True)
    bruto_dir = job["bruto_dir"]
    bruto = jload(os.path.join(bruto_dir, job["bruto_arquivo"]))
    perfil = job["perfil"]
    item = job["item"]
    limpar_cena()

    rig_obj = None
    info_gerada: dict = {}
    texturas_geradas: list[dict] = []
    nome_base = str(job["nome_base"])
    qualidade_item = str(item.get("qualidade") or "").strip().lower()
    alpha_cards_ativo = bool(item.get("alpha_cards") or job.get("alpha_cards"))
    detalhe_alto_cfg = (
        job.get("detalhe_alto") or item.get("detalhe_alto") or bruto.get("detalhe_alto")
    )
    pbr_zonas_cfg = job.get("pbr_zonas") or item.get("pbr_zonas") or bruto.get("pbr_zonas")
    textura_max_perfil = int(
        (perfil.get("material") or {}).get("textura_max")
        or (perfil.get("validacao") or {}).get("textura_max")
        or 0
    )
    if qualidade_item in ("hero", "ultra") and textura_max_perfil > 0:
        textura_max_perfil = max(textura_max_perfil, 2048)
    cfg_suav = _resolver_config_suavizacao(job, bruto)
    smooth_normals_aplicado = False
    angulo_smooth_final = 0.0
    weighted_normals_aplicado = False
    quadriflow_aplicado = False
    esq_raw = item.get("esqueleto") or (perfil.get("rig") or {}).get("esqueleto_padrao")
    esqueleto_efetivo: str | None = str(esq_raw) if esq_raw else None
    esqueleto_pedido: str | None = esqueleto_efetivo

    high_obj_src = None
    usar_bake_pendente = False
    ctx_bruto: dict | None = None
    rig_pre_existente = False

    if bruto["schema"] == "forge3d/bruto-blocky@1":
        obj, grupos = construir_blocky(bruto, bruto_dir)
        if bruto.get("ossos"):
            rig_obj = criar_armadura(bruto["ossos"])
    elif bruto["schema"] == "forge3d/bruto-extrude@1":
        obj, grupos, smooth_normals_aplicado, angulo_smooth_final, weighted_normals_aplicado = (
            _br._processar_bruto_extrude(
                bruto, bruto_dir, saida_dir, nome_base, item, perfil, cfg_suav,
                qualidade_item, alpha_cards_ativo, textura_max_perfil, info_gerada,
                texturas_geradas, decimar,
            )
        )
    elif bruto["schema"] == "forge3d/bruto-arquivo@1":
        ctx_bruto = _br._preparar_bruto_arquivo(
            job, bruto, bruto_dir, item, cfg_suav, qualidade_item, alpha_cards_ativo,
            textura_max_perfil, detalhe_alto_cfg, pbr_zonas_cfg, info_gerada,
        )
        obj, rig_obj, grupos = ctx_bruto["obj"], ctx_bruto["rig_obj"], ctx_bruto["grupos"]
        rig_pre_existente = rig_obj is not None
        angulo_smooth_final = ctx_bruto["angulo_smooth"]

        if ctx_bruto["usar_bake_high_low"]:
            if not rig_pre_existente:
                _br._prealinhar_se_criatura_rig(obj, job, item, perfil, autorig_mod=autorig)
            high_obj_src = _br._clonar_high_nao_linkado(obj, nome_base)
            smooth_normals_aplicado, weighted_normals_aplicado, qf_ok = (
                _br._preparar_low_antes_escala(
                    obj,
                    ctx_bruto,
                    info_gerada,
                    alpha_cards_ativo,
                    bruto,
                    rig_obj,
                    cfg_suav,
                    retopologizar_quadriflow,
                    decimar,
                    desdobrar_uv,
                )
            )
            if qf_ok:
                quadriflow_aplicado = True
            usar_bake_pendente = True
        else:
            smooth_normals_aplicado, weighted_normals_aplicado, qf_ok = (
                _br._reduzir_e_suavizar_sem_bake(
                    obj, rig_obj, bruto, ctx_bruto, cfg_suav, alpha_cards_ativo, info_gerada,
                    retopologizar_quadriflow, decimar, desdobrar_uv,
                )
            )
            if qf_ok:
                quadriflow_aplicado = True

        rig_obj, grupos, esqueleto_pedido, esqueleto_efetivo = _br._aplicar_rig_bruto_arquivo(
            obj, rig_obj, grupos, job, item, perfil, bruto, info_gerada,
            esqueleto_pedido, esqueleto_efetivo, autorig_mod=autorig,
        )
        if high_obj_src is not None:
            _br._sincronizar_high_pos_rig(
                high_obj_src,
                obj,
                info_gerada,
                rig_criado_agora=(not rig_pre_existente and rig_obj is not None),
            )
    else:
        raise RuntimeError(f"bruto desconhecido: {bruto['schema']}")

    obj.name = nome_base
    if obj.data is not None:
        obj.data.name = nome_base

    escala_saida = float((perfil.get("unidades") or {}).get("escala_saida", 1.0))
    if escala_saida <= 0:
        raise RuntimeError(f"escala_saida invalida no perfil: {escala_saida}")
    minimo, maximo = bbox_local()
    altura_atual = maximo.z - minimo.z
    if altura_atual <= 0:
        raise RuntimeError("geometria com altura zero")
    escala_preservada = bool(bruto.get("escala_preservada"))
    if escala_preservada:
        escala = 1.0 * escala_saida
        pivo = Vector((0.0, 0.0, 0.0))
        origem_regra = "preservada"
    else:
        raw_alt = item.get("altura_metros")
        alvo = float(raw_alt) if raw_alt is not None else altura_atual
        escala = (alvo / altura_atual) * escala_saida
        pivot_nome = item.get("pivot", "base")
        pivo_declarado = (bruto.get("pivos") or {}).get(pivot_nome)
        pivo, origem_regra = calcular_pivo(
            pivot_nome, minimo * escala, maximo * escala, pivo_declarado
        )
        if pivo_declarado:
            pivo = Vector(pivo_declarado) * escala

    transformar(escala, -pivo)
    if str(item.get("colisao") or "none").strip().lower() == "ucx":
        transformar_colisores_ucx(escala, -pivo)
    if rig_obj is not None:
        transformar_armadura(rig_obj, escala, -pivo)
    if high_obj_src is not None:
        _br._transformar_high_escala(high_obj_src, escala, -pivo)

    if usar_bake_pendente and ctx_bruto is not None and high_obj_src is not None:
        _ep._reparar_e_suavizar_pos_escala(
            obj,
            rig_obj,
            escala,
            alpha_cards_ativo,
            smooth_normals_aplicado,
            angulo_smooth_final,
            weighted_normals_aplicado,
            info_gerada,
            rig_pre_existente=rig_pre_existente,
        )
        origem_tex = _resolver_opcional_bruto(bruto_dir, bruto.get("origem_textura"))
        met_hint = _resolver_opcional_bruto(bruto_dir, bruto.get("metallic_hint"))
        rough_hint = _resolver_opcional_bruto(bruto_dir, bruto.get("roughness_hint"))
        vistas_orto = _sc._resolver_vistas_ortograficas(bruto_dir, bruto, job, item)
        mat_proc = ctx_bruto["mat_proc"]
        bake_ctx, decimar_cb, reparo_cb, suavizar_cb, uv_cb = (
            _nuv._preparar_contexto_bake_pos_escala(
                obj,
                high_obj_src,
                pbr_zonas_cfg,
                info_gerada,
                alpha_cards_ativo,
                angulo_smooth_final,
                desdobrar_uv,
                bake_pbr,
            )
        )
        try:
            res_bake = bake_pbr.executar_bake_high_low(
                obj,
                saida_dir,
                nome_base,
                ctx_bruto["px"],
                ctx_bruto["limite_tris"],
                reparo_cb,
                decimar_cb,
                suavizar_cb,
                uv_cb,
                origem_textura=origem_tex,
                metallic_hint_png=met_hint,
                roughness_hint_png=rough_hint,
                proteger_superficie=ctx_bruto["proteger"],
                perfil_nome=str(perfil.get("perfil") or item.get("perfil") or ""),
                material_procedural=mat_proc or None,
                permitir_sem_cor_vertice=bool(
                    mat_proc
                    or pbr_zonas_cfg
                    or detalhe_alto_cfg
                    or str(ctx_bruto["item_bake_check"].get("material") or "").strip().lower() == "pbr"
                    or ctx_bruto["retopologia_pedida"] == "quadriflow"
                ),
                detalhe_alto=detalhe_alto_cfg if isinstance(detalhe_alto_cfg, dict) else None,
                pbr_zonas=list(pbr_zonas_cfg) if isinstance(pbr_zonas_cfg, list) else None,
                px_sub=ctx_bruto["px_sub"],
                qualidade=qualidade_item or None,
                vistas_ortograficas=vistas_orto,
            )
        finally:
            _nuv._finalizar_contexto_bake_pos_escala(bake_ctx)

        bake_meta = res_bake["bake"]
        info_gerada["triangulos_antes_decimate"] = bake_meta["triangulos_high"]
        info_gerada["triangulos_pos_decimate"] = bake_meta["triangulos_low"]
        info_gerada["reparo_pos_decimate"] = bake_meta["reparo"]
        info_gerada["smooth"] = bake_meta["smooth"]
        info_gerada["uv"] = bake_meta["uv"]
        info_gerada["bake"] = bake_meta
        if mat_proc:
            info_gerada["material_procedural"] = mat_proc
        smooth_normals_aplicado = True
        texturas_geradas.extend(res_bake["arquivos_textura"])

    if bruto["schema"] != "forge3d/bruto-blocky@1" and item.get("tipo") in (
        "modulo_cenario",
        "prop_estatico",
        "mapa_setor",
    ):
        gerar_uv_lightmap(obj)

    animacoes_geradas, sockets_extraidos = _ep._pos_escala_rig_e_animacao(
        obj, rig_obj, grupos, job, item, bruto, escala, alpha_cards_ativo,
        smooth_normals_aplicado, angulo_smooth_final, weighted_normals_aplicado,
        info_gerada, autorig_mod=autorig, pular_reparo_pos_escala=usar_bake_pendente,
    )
    sombreamento_meta = {
        "smooth_normals": bool(smooth_normals_aplicado),
        "angulo_graus": round(float(angulo_smooth_final), 2),
        "weighted_normals": bool(weighted_normals_aplicado),
        "quadriflow_aplicado": bool(quadriflow_aplicado),
    }
    orientacao_export_meta = {
        "frente_gltf": "-Z",
        "cima_gltf": "+Y",
        "direita_gltf": "+X",
        "det_matriz": 1,
    }
    medidas_base = _ep._montar_medidas_lod0(
        obj, rig_obj, escala_saida, origem_regra, escala_preservada,
        animacoes_geradas, sockets_extraidos, esqueleto_efetivo, esqueleto_pedido,
        alpha_cards_ativo, sombreamento_meta, orientacao_export_meta, textura_max_perfil,
    )
    arquivos = _ep._exportar_lods(
        obj, rig_obj, grupos, job, item, perfil, bruto, saida_dir, nome_base,
        qualidade_item, alpha_cards_ativo, smooth_normals_aplicado, angulo_smooth_final,
        animacoes_geradas, texturas_geradas, medidas_base,
        _reduzir_imagens_embutidas_orcamento,
    )
    return _ep._finalizar_colisor_e_resultado(
        obj, rig_obj, job, item, perfil, bruto, bruto_dir, saida_dir, nome_base,
        escala_saida, esqueleto_efetivo, info_gerada, detalhe_alto_cfg, pbr_zonas_cfg,
        texturas_geradas, sockets_extraidos, sombreamento_meta, orientacao_export_meta,
        medidas_base, arquivos,
    )


def main() -> int:
    argv = sys.argv
    if "--" not in argv:
        print("uso: blender -b -P postprocess.py -- <job.json>", file=sys.stderr)
        return 2
    job_path = argv[argv.index("--") + 1]
    job = jload(job_path)
    try:
        resultado = processar(job)
    except Exception as exc:  # noqa: BLE001 - o erro precisa sair como arquivo
        jsave(
            job["saida_resultado"],
            {
                "ok": False,
                "erro": str(exc),
                "traceback": traceback.format_exc(limit=8),
            },
        )
        print(f"FORGE3D_BPY_FALHOU: {exc}", file=sys.stderr)
        return 1
    jsave(job["saida_resultado"], resultado)
    print("FORGE3D_BPY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
