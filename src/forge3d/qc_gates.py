"""Avaliadores individuais dos portoes G1-G5 para manter ``qc.py`` enxuto."""

from __future__ import annotations

import logging
from pathlib import Path

from .errors import erro_qc
from .qc_geom import topologia
from .qc_midia import (
    PAPEIS_TEXTURA,
    TEXTURA_MIN_PX,
    _imagens_embutidas,
    _normal_opengl_valido,
    _pot,
    _uv_status,
    _validar_bytes_imagem,
)
from .qc_orientacao import _desvio_pivo, _g2_orientacao

logger = logging.getLogger(__name__)


def _avaliar_g1(
    gltf: dict,
    binario: bytes,
    medidas: dict,
    v: dict,
    permite_alpha_cards: bool,
    checar_facetamento: bool,
    fac_info: dict,
) -> dict:
    malha_facetada = bool(fac_info.get("facetada", False))
    topo = (
        topologia(gltf, binario)
        if gltf.get("meshes")
        else {
            "nao_manifold": 0,
            "bordas_abertas": 0,
            "arestas_t": 0,
            "degeneradas": 0,
            "invertidas": 0,
        }
    )
    nao_manifold = max(int(medidas.get("nao_manifold", 0)), int(topo.get("nao_manifold", 0)))
    bordas_abertas = int(topo.get("bordas_abertas", 0))
    arestas_t = max(
        int(medidas.get("arestas_t", 0)),
        int(topo.get("arestas_t", max(0, int(topo.get("nao_manifold", 0)) - bordas_abertas))),
    )
    degeneradas = max(int(medidas.get("degeneradas", 0)), int(topo.get("degeneradas", 0)))
    invertidas = int(topo.get("invertidas", 0))
    malha_manifold_ok = (
        arestas_t <= int(v["nao_manifold_max"])
        if permite_alpha_cards
        else nao_manifold <= int(v["nao_manifold_max"])
    )
    g1_ok = (
        malha_manifold_ok
        and degeneradas <= int(v["faces_degeneradas_max"])
        and invertidas == 0
        and not malha_facetada
    )
    medido_g1: dict = {
        "nao_manifold": nao_manifold,
        "bordas_abertas": bordas_abertas,
        "arestas_t": arestas_t,
        "degeneradas": degeneradas,
        "invertidas": invertidas,
    }
    if permite_alpha_cards:
        medido_g1["alpha_cards"] = True
    if checar_facetamento:
        medido_g1["fracao_facetada"] = fac_info["fracao_facetada"]
        medido_g1["malha_organica_facetada"] = malha_facetada
    if malha_facetada:
        medido_g1["motivo"] = "malha_organica_facetada"
        medido_g1["motivos"] = ["malha_organica_facetada"]
    return {
        "id": "G1",
        "status": "ok" if g1_ok else "falhou",
        "medido": medido_g1,
        "limite": {
            "nao_manifold_max": v["nao_manifold_max"],
            "degeneradas_max": v["faces_degeneradas_max"],
            "invertidas_max": 0,
        },
        "codigo": None if g1_ok else "FORGE-E-QC",
    }


def _avaliar_g2(
    gltf: dict,
    binario: bytes,
    item: dict,
    perfil: dict,
    info: dict,
    medidas: dict,
    escala: float,
    exigir_orientacao: bool,
) -> tuple[dict, float]:
    v = perfil["validacao"]
    raw_alt = item.get("altura_metros")
    tipo_item = str(item.get("tipo") or "").strip()
    if raw_alt is None and tipo_item not in ("mapa_setor", "textura"):
        raise erro_qc("item sem altura_metros obrigatoria para G2")
    alvo: float | None = float(raw_alt) if raw_alt is not None else None
    altura_export = info["bbox_m"][1]
    altura = (
        altura_export / escala
        if altura_export > 0
        else float(medidas.get("bbox_m", [0, 0, 0])[1])
    )
    raw_anexo = item.get("anexo")
    anexo_item: dict = raw_anexo if isinstance(raw_anexo, dict) else {}
    escala_preservada = bool(
        item.get("escala_preservada")
        or medidas.get("escala_preservada")
        or (
            bool(anexo_item.get("skinned"))
            and item.get("parte")
            and item.get("parte") != "corpo"
            and alvo is not None
            and alvo >= 1.2
        )
    )
    delta_pct = 0.0 if alvo is None else (abs(altura - alvo) / alvo * 100.0 if alvo else 999.0)
    tolerancia_m = float(v["pivo_delta_mm"]) / 1000.0
    regra = item["pivot"]
    desvio_pivo = _desvio_pivo(regra, info["min"][1] / escala, info["max"][1] / escala)
    desvio_xz: float | None = None
    eh_equipavel = item.get("tipo") == "prop_equipavel" or item.get("parte") in ("arma", "escudo")
    checar_xz = regra == "centro" or (regra in ("base", "topo", "junta") and not eh_equipavel)
    if desvio_pivo is not None and gltf.get("meshes") and checar_xz:
        desvio_xz = max(
            abs((info["min"][0] + info["max"][0]) / 2.0),
            abs((info["min"][2] + info["max"][2]) / 2.0),
        ) / escala
        desvio_pivo = max(desvio_pivo, desvio_xz)
    if escala_preservada:
        escala_ok = (0.02 * alvo) <= altura <= (1.15 * alvo) if alvo is not None else altura > 0.0
        pivo_ok = True
    elif alvo is None:
        escala_ok = altura > 0.0
        pivo_ok = desvio_pivo is None or desvio_pivo <= tolerancia_m
    else:
        escala_ok = delta_pct <= float(v["escala_delta_pct"])
        pivo_ok = desvio_pivo is None or desvio_pivo <= tolerancia_m
    orient_ok, orient_detalhes = _g2_orientacao(gltf, binario, item, perfil, info)
    orient_falhou = (not orient_ok) and exigir_orientacao
    orient_warn = bool(orient_detalhes.get("avisos")) or ((not orient_ok) and not exigir_orientacao)
    g2_ok = escala_ok and pivo_ok and not orient_falhou
    g2_status = "falhou" if not g2_ok else ("warn" if orient_warn else "ok")
    g2_codigo = (
        None
        if g2_status == "ok"
        else ("FORGE-E-QC" if g2_status == "falhou" else "FORGE-W-ORIENTACAO")
    )
    medido_g2: dict = {
        "altura_m": round(altura, 6),
        "altura_export": round(altura_export, 6),
        "esperado_m": alvo,
        "delta_pct": round(delta_pct, 3),
        "desvio_pivo_m": None if desvio_pivo is None else round(desvio_pivo, 6),
        "pivo_regra": regra,
        "escala_saida": escala,
        "orientacao": orient_detalhes,
    }
    if escala_preservada:
        medido_g2["escala_preservada"] = True
    if desvio_xz is not None:
        medido_g2["desvio_xz_m"] = round(desvio_xz, 6)
    gate = {
        "id": "G2",
        "status": g2_status,
        "medido": medido_g2,
        "limite": {"escala_delta_pct": v["escala_delta_pct"], "pivo_delta_mm": v["pivo_delta_mm"]},
        "codigo": g2_codigo,
    }
    return gate, altura


def _avaliar_g3(gltf: dict, binario: bytes, item: dict, perfil: dict, info: dict) -> dict:
    permitir_tiling = bool(
        item.get("permitir_tiling") or (perfil.get("material") or {}).get("permitir_tiling", False)
    )
    tags_item = [str(t) for t in (item.get("tags") or [])]
    eh_blocky = (
        item.get("rota") == "blocky"
        or item.get("estilo") == "blocky_voxel"
        or "blocky_voxel" in tags_item
    )
    uv_info = (
        _uv_status(gltf, binario, permitir_tiling=permitir_tiling, eh_blocky=eh_blocky)
        if gltf.get("meshes")
        else {
            "total_uv": 0,
            "fora_intervalo": 0,
            "uv_colapsada": 0,
            "uv_sobreposta": 0,
            "densidade_extrema": 0,
        }
    )
    uv_ok = (
        info["sem_uv"] == 0
        and info["primitivas"] > 0
        and uv_info["fora_intervalo"] == 0
        and uv_info["uv_colapsada"] == 0
        and uv_info["uv_sobreposta"] == 0
        and uv_info["densidade_extrema"] == 0
    )
    return {
        "id": "G3",
        "status": "ok" if uv_ok else "falhou",
        "medido": {
            "primitivas": info["primitivas"],
            "sem_uv": info["sem_uv"],
            "uv_fora_intervalo": uv_info["fora_intervalo"],
            "uv_colapsada": uv_info["uv_colapsada"],
            "uv_sobreposta": uv_info["uv_sobreposta"],
            "densidade_extrema": uv_info["densidade_extrema"],
            "permitir_tiling": permitir_tiling,
        },
        "limite": {
            "sem_uv_max": 0,
            "fora_intervalo_max": 0,
            "uv_colapsada_max": 0,
            "uv_sobreposta_max": 0,
            "densidade_extrema_max": 0,
        },
        "codigo": None if uv_ok else "FORGE-E-QC",
    }


def _avaliar_g4(
    gltf: dict, binario: bytes, item: dict, perfil: dict, info: dict, pasta: Path, arquivos: list[dict]
) -> dict:
    textura_max = int(perfil["material"]["textura_max"])
    if item.get("qualidade") in ("hero", "ultra"):
        textura_max = max(textura_max, 2048)
    texturas = [a for a in arquivos if a.get("papel") in PAPEIS_TEXTURA]
    detalhes_tex = []
    tex_ok = True
    for arq in texturas:
        caminho_tex = pasta / arq["caminho"]
        dados_tex = caminho_tex.read_bytes() if caminho_tex.is_file() else b""
        dims = _validar_bytes_imagem(dados_tex) if dados_tex else None
        if dims is None:
            tex_ok = False
            detalhes_tex.append(
                {
                    "arquivo": arq["caminho"],
                    "papel": arq["papel"],
                    "px": None,
                    "pot": False,
                    "valida": False,
                }
            )
            continue
        largura, altura_px = dims
        pot = _pot(largura) and _pot(altura_px)
        dentro = min(largura, altura_px) >= TEXTURA_MIN_PX and max(largura, altura_px) <= textura_max
        normal_z_ok = True
        if arq.get("papel") == "normal":
            normal_z_ok = _normal_opengl_valido(dados_tex)
        valida_tex = pot and dentro and normal_z_ok
        tex_ok = tex_ok and valida_tex
        detalhes_tex.append(
            {
                "arquivo": arq["caminho"],
                "papel": arq["papel"],
                "px": [largura, altura_px],
                "pot": pot,
                "valida": valida_tex,
            }
        )
    embutidas = _imagens_embutidas(gltf, binario, textura_max, textura_min=TEXTURA_MIN_PX)
    for emb in embutidas:
        tex_ok = tex_ok and bool(emb["valida"])
    if gltf.get("meshes") and info["com_textura"] > 0 and not texturas and not embutidas:
        tex_ok = False
    return {
        "id": "G4",
        "status": "ok" if tex_ok else "falhou",
        "medido": {"texturas": detalhes_tex, "embutidas": embutidas},
        "limite": {"min_px": TEXTURA_MIN_PX, "ppm_max": textura_max, "pot": True},
        "codigo": None if tex_ok else "FORGE-E-QC",
    }


def _avaliar_g5(
    info: dict,
    v: dict,
    exigir_tangent_normal: bool,
    checar_facetamento: bool,
    fac_info: dict,
    *,
    item: dict | None = None,
) -> dict:
    malha_facetada = bool(fac_info.get("facetada", False))
    materiais_validos = int(info.get("materiais_validos", info["com_textura"]))
    sem_tangent_normal = int(info.get("sem_tangent_normal", 0))
    item_eff = item or {}
    det_alto = item_eff.get("detalhe_alto")
    detalhe_alto_ativo = (
        bool(det_alto.get("ativo", True)) if isinstance(det_alto, dict) else bool(det_alto)
    )
    mat_item = str(item_eff.get("material") or "").strip().lower()
    exige_textura_pbr = (
        mat_item == "pbr"
        or bool(item_eff.get("pbr_zonas"))
        or detalhe_alto_ativo
        or bool(str(item_eff.get("material_procedural") or "").strip())
    )
    materiais_ok = (
        info["com_textura"] == info["materiais"]
        if exige_textura_pbr
        else (materiais_validos == info["materiais"] or info["com_textura"] == info["materiais"])
    )
    mat_ok = (
        info["materiais"] >= 1
        and info["materiais"] <= int(v["materiais_max"])
        and materiais_ok
        and not info["imagens_externas"]
        and (sem_tangent_normal == 0 or not exigir_tangent_normal)
        and not malha_facetada
    )
    medido_g5: dict = {
        "materiais": info["materiais"],
        "com_textura": info["com_textura"],
        "imagens_externas": info["imagens_externas"],
        "sem_tangent_normal": sem_tangent_normal,
        "exige_textura_pbr": exige_textura_pbr,
    }
    if mat_item:
        medido_g5["material"] = mat_item
    if checar_facetamento:
        medido_g5["fracao_facetada"] = fac_info["fracao_facetada"]
        medido_g5["malha_organica_facetada"] = malha_facetada
    motivos_g5: list[str] = []
    if malha_facetada:
        motivos_g5.append("malha_organica_facetada")
    if exige_textura_pbr and not materiais_ok:
        motivos_g5.append("clay_sem_textura_em_pbr")
    if motivos_g5:
        medido_g5["motivo"] = motivos_g5[0]
        medido_g5["motivos"] = motivos_g5
    return {
        "id": "G5",
        "status": "ok" if mat_ok else "falhou",
        "medido": medido_g5,
        "limite": {
            "materiais_max": v["materiais_max"],
            "imagens_externas_max": 0,
            "sem_tangent_normal_max": 0 if exigir_tangent_normal else None,
        },
        "codigo": None if mat_ok else "FORGE-E-QC",
    }
