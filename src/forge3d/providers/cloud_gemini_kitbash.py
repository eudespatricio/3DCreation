"""Embeddings Gemini-2 e planejador Kitbash 3D — stdlib pura (D26)."""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any

from ..errors import erro_provider_run


def _resolver_modelo_embedding_gemini(model: str | None = None) -> str:
    from . import cloud_ai

    bruto = (
        (model or "").strip()
        or os.environ.get("FORGE3D_GEMINI_EMBEDDING_MODEL", "").strip()
        or cloud_ai.MODELO_GEMINI_EMBEDDING_PADRAO
    )
    if bruto.startswith("models/"):
        bruto = bruto[len("models/") :]
    return cloud_ai.ALIASES_GEMINI_EMBEDDING.get(bruto, bruto)


def _extrair_vetor_embedding_gemini(dados: dict[str, Any]) -> list[float]:
    emb = dados.get("embedding")
    if isinstance(emb, dict):
        vals = emb.get("values")
        if isinstance(vals, list) and vals:
            return [float(x) for x in vals]

    embs = dados.get("embeddings")
    if isinstance(embs, list) and embs:
        e0 = embs[0]
        if isinstance(e0, dict):
            vals = e0.get("values")
            if isinstance(vals, list) and vals:
                return [float(x) for x in vals]

    vals_diretos = dados.get("values")
    if isinstance(vals_diretos, list) and vals_diretos:
        return [float(x) for x in vals_diretos]

    raise ValueError("resposta Gemini embedContent nao contem embedding.values")


def _normalizar_l2_floats(vetor: list[float]) -> list[float]:
    norma = math.sqrt(sum(float(x) * float(x) for x in vetor))
    if norma <= 1e-12:
        return [float(x) for x in vetor]
    return [float(x) / norma for x in vetor]


def gerar_embedding_gemini(
    texto: str,
    *,
    task_type: str = "RETRIEVAL_DOCUMENT",
    output_dimensionality: int = 768,
    model: str | None = None,
    timeout: int = 30,
) -> list[float]:
    """Gera vetor de embedding L2-normalizado via endpoint REST ``:embedContent`` do Gemini."""
    from . import cloud_ai

    cloud_ai.registrar_licencas_cloud()
    try:
        chave, _fonte = cloud_ai._ler_chave_gemini()
    except OSError as exc:
        raise erro_provider_run(
            f"falha ao ler chave Gemini Embedding: {exc}", modelo="gemini_embedding"
        ) from exc
    if not chave:
        raise erro_provider_run(
            "conector Gemini Embedding sem chave configurada "
            "(FORGE3D_GEMINI_API_KEY ou ~/.config/forge3d/gemini.key)",
            modelo="gemini_embedding",
        )

    modelo_resolvido = _resolver_modelo_embedding_gemini(model)
    url_custom = os.environ.get("FORGE3D_GEMINI_EMBEDDING_URL", "").strip()
    endpoint = url_custom or f"{cloud_ai.URL_GEMINI_BASE}/{modelo_resolvido}:embedContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": chave,
    }
    payload: dict[str, Any] = {
        "model": f"models/{modelo_resolvido}",
        "content": {"parts": [{"text": str(texto or "")}]},
        "taskType": str(task_type),
        "outputDimensionality": int(output_dimensionality),
    }

    dados = cloud_ai._post_json_seguro(
        endpoint,
        payload,
        headers,
        timeout_s=int(timeout),
        segredos=[chave],
        provedor="Gemini",
        modelo=modelo_resolvido,
    )
    try:
        vetor = _extrair_vetor_embedding_gemini(dados)
        if not vetor:
            raise ValueError("vetor vazio")
        return _normalizar_l2_floats(vetor)
    except (TypeError, ValueError) as exc:
        msg_limpa = cloud_ai._sanitizar_texto_erro(str(exc), [chave])
        raise erro_provider_run(
            f"falha ao interpretar vetor Gemini Embedding ({modelo_resolvido}): {msg_limpa}",
            modelo="gemini_embedding",
        ) from None


def _inferir_estilo_kitbash(prompt: str) -> str:
    p = (prompt or "").lower()
    if any(k in p for k in ("dark", "grim", "gothic", "ancient", "ancestral", "forged", "forjado")):
        return "dark_fantasy_pbr"
    if any(k in p for k in ("realistic", "realista", "aa", "photoreal")):
        return "realistic_pbr"
    return "stylized_pbr"


def _inferir_papel_peca(item: dict[str, Any], indice: int) -> tuple[str, str]:
    texto = " ".join(
        [
            str(item.get("asset_id") or item.get("id") or ""),
            str(item.get("nome") or ""),
            str(item.get("categoria") or ""),
            " ".join(str(t) for t in (item.get("tags") or [])),
            str(item.get("descricao") or ""),
        ]
    ).lower()
    if indice == 0 or any(k in texto for k in ("grip", "handle", "cabo", "punho", "torso", "core", "base")):
        papel = "base" if indice == 0 else "grip"
    elif any(k in texto for k in ("blade", "lamina", "head", "spearhead", "axe")):
        papel = "blade"
    elif any(k in texto for k in ("guard", "crossguard", "guarda", "pauldron", "shoulder")):
        papel = "guard"
    elif any(k in texto for k in ("pommel", "pomo", "cap", "gem", "boss")):
        papel = "pommel"
    else:
        papel = "attachment"

    if any(k in texto for k in ("leather", "couro", "grip", "cabo", "strap")):
        zona = "couro_gasto"
    elif any(k in texto for k in ("bronze", "gold", "ouro", "filigree", "guard", "guarda", "pommel", "pomo")):
        zona = "ouro_ornamentado"
    elif any(k in texto for k in ("linen", "cloth", "tecido", "tunic")):
        zona = "tecido_nobre"
    elif any(k in texto for k in ("wood", "madeira", "oak", "staff")):
        zona = "madeira_ancestral"
    elif any(k in texto for k in ("stone", "pedra", "moss", "musgo")):
        zona = "pedra_musgo"
    else:
        zona = "aco_forjado"
    return papel, zona


def _construir_pbr_zonas_padrao(zonas_usadas: list[str]) -> list[dict[str, Any]]:
    catalogo_zonas: dict[str, dict[str, Any]] = {
        "aco_forjado": {
            "nome": "aco_forjado",
            "preset": "aco_forjado",
            "cor_hex": "#9AA2AC",
            "roughness_escala": 0.38,
            "metallic_override": 0.88,
            "normal_forca": 1.0,
        },
        "couro_gasto": {
            "nome": "couro_gasto",
            "preset": "couro_gasto",
            "cor_hex": "#6E472B",
            "roughness_escala": 0.78,
            "metallic_override": 0.0,
            "normal_forca": 0.9,
        },
        "ouro_ornamentado": {
            "nome": "ouro_ornamentado",
            "preset": "ouro_ornamentado",
            "cor_hex": "#C89D46",
            "roughness_escala": 0.30,
            "metallic_override": 0.94,
            "normal_forca": 1.0,
        },
        "tecido_nobre": {
            "nome": "tecido_nobre",
            "preset": "tecido_nobre",
            "cor_hex": "#7E8288",
            "roughness_escala": 0.86,
            "metallic_override": 0.0,
            "normal_forca": 0.75,
        },
        "madeira_ancestral": {
            "nome": "madeira_ancestral",
            "preset": "madeira_ancestral",
            "cor_hex": "#5C4028",
            "roughness_escala": 0.80,
            "metallic_override": 0.0,
            "normal_forca": 1.0,
        },
        "pedra_musgo": {
            "nome": "pedra_musgo",
            "preset": "pedra_musgo",
            "cor_hex": "#6D736E",
            "roughness_escala": 0.88,
            "metallic_override": 0.0,
            "normal_forca": 1.1,
        },
    }
    saida: list[dict[str, Any]] = []
    vistas: set[str] = set()
    for z in zonas_usadas:
        zn = (z or "aco_forjado").strip()
        if zn in vistas:
            continue
        vistas.add(zn)
        saida.append(
            dict(
                catalogo_zonas.get(
                    zn,
                    {
                        "nome": zn,
                        "preset": "aco_forjado",
                        "cor_hex": "#9AA2AC",
                        "roughness_escala": 0.45,
                        "metallic_override": 0.8,
                        "normal_forca": 1.0,
                    },
                )
            )
        )
    if not saida:
        saida.append(dict(catalogo_zonas["aco_forjado"]))
    return saida


def _planejar_kitbash_offline(
    prompt: str,
    pecas_catalogo: list[dict[str, Any]],
) -> dict[str, Any]:
    from . import cloud_ai

    cloud_ai.registrar_licencas_cloud()
    malhas: list[dict[str, Any]] = []
    for item in pecas_catalogo or []:
        if not isinstance(item, dict):
            continue
        tipo = str(item.get("tipo") or "mesh").lower()
        if tipo in ("mesh", "kitbash_part", "glb", ""):
            malhas.append(item)
    if not malhas:
        malhas = [dict(x) for x in (pecas_catalogo or []) if isinstance(x, dict)]

    # Ordena priorizando cabo/base na raiz para que guarda, lamina e pomo encaixem nela
    def _prioridade_raiz(it: dict[str, Any]) -> tuple[int, str]:
        papel, _ = _inferir_papel_peca(it, 1)
        ordem = {"grip": 0, "base": 1, "guard": 2, "blade": 3, "pommel": 4, "attachment": 5}
        aid = str(it.get("asset_id") or it.get("id") or "")
        return (ordem.get(papel, 9), aid)

    selecionadas = sorted(malhas, key=_prioridade_raiz)[:4]
    if not selecionadas:
        selecionadas = [
            {"asset_id": "kb.cylindrical_grip", "nome": "cylindrical_grip", "tags": ["grip", "leather"]},
            {"asset_id": "kb.crossguard", "nome": "crossguard", "tags": ["guard", "bronze"]},
            {"asset_id": "kb.sword_blade", "nome": "sword_blade", "tags": ["blade", "steel"]},
            {"asset_id": "kb.pommel_stone", "nome": "pommel_stone", "tags": ["pommel", "bronze"]},
        ]

    pecas_plano: list[dict[str, Any]] = []
    zonas_usadas: list[str] = []
    id_raiz = str(selecionadas[0].get("asset_id") or selecionadas[0].get("id") or "kb.base")

    for idx, item in enumerate(selecionadas):
        pid = str(item.get("asset_id") or item.get("id") or f"kb.part_{idx}")
        papel, zona = _inferir_papel_peca(item, idx)
        if idx == 0:
            papel = "base"
            snap_para = None
            direcao = [0.0, 0.0, 1.0]
        else:
            snap_para = id_raiz
            if papel == "pommel":
                direcao = [0.0, 0.0, -1.0]
            elif papel in ("blade", "guard"):
                direcao = [0.0, 0.0, 1.0]
            else:
                direcao = [0.0, 0.0, 1.0 if idx % 2 == 1 else -1.0]

        zonas_usadas.append(zona)
        pecas_plano.append(
            {
                "id": pid,
                "papel": papel,
                "snap_para": snap_para,
                "escala": 1.0,
                "pbr_zona": zona,
                "direcao_snap": direcao,
                "folga_m": 0.0015,
            }
        )

    return {
        "ok": True,
        "modo": "offline_fallback",
        "modelo": "offline_kitbash_planner",
        "prompt": prompt,
        "estilo": _inferir_estilo_kitbash(prompt),
        "pecas": pecas_plano,
        "pbr_zonas": _construir_pbr_zonas_padrao(zonas_usadas),
        "licenca": dict(cloud_ai.LICENCAS_CLOUD["gemini_kitbash"]),
    }


def _parsear_plano_kitbash_json(
    texto: str,
    prompt: str,
    pecas_catalogo: list[dict[str, Any]],
) -> dict[str, Any]:
    limpo = (texto or "").strip()
    if limpo.startswith("```"):
        limpo = re.sub(r"^```(?:json)?\s*", "", limpo)
        limpo = re.sub(r"\s*```$", "", limpo)
    try:
        bruto = json.loads(limpo)
    except ValueError:
        m = re.search(r"\{.*\}", limpo, flags=re.DOTALL)
        if not m:
            raise ValueError("resposta Gemini Kitbash sem JSON valido") from None
        bruto = json.loads(m.group(0))

    if not isinstance(bruto, dict):
        raise ValueError("resposta Gemini Kitbash JSON nao e um objeto")

    pecas_raw = bruto.get("pecas")
    if not isinstance(pecas_raw, list) or not pecas_raw:
        raise ValueError("plano Gemini Kitbash sem lista 'pecas'")

    pecas_norm: list[dict[str, Any]] = []
    zonas_usadas: list[str] = []
    id_base: str | None = None
    for idx, p in enumerate(pecas_raw):
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or p.get("asset_id") or f"kb.part_{idx}").strip()
        if idx == 0:
            id_base = pid
        papel = str(p.get("papel") or ("base" if idx == 0 else "attachment")).strip()
        snap_raw = p.get("snap_para")
        snap_para = None if idx == 0 or not snap_raw else str(snap_raw).strip()
        if idx > 0 and not snap_para:
            snap_para = id_base
        escala_raw = p.get("escala", 1.0)
        if isinstance(escala_raw, (int, float)):
            escala: float | list[float] = float(escala_raw)
        elif isinstance(escala_raw, list) and len(escala_raw) == 3:
            escala = [float(x) for x in escala_raw]
        else:
            escala = 1.0
        zona = str(p.get("pbr_zona") or "aco_forjado").strip()
        zonas_usadas.append(zona)
        direcao = p.get("direcao_snap")
        if not (isinstance(direcao, list) and len(direcao) == 3):
            direcao = [0.0, 0.0, -1.0 if papel == "pommel" else 1.0]
        pecas_norm.append(
            {
                "id": pid,
                "papel": papel,
                "snap_para": snap_para,
                "escala": escala,
                "pbr_zona": zona,
                "direcao_snap": [float(x) for x in direcao],
                "folga_m": float(p.get("folga_m", 0.0015)),
            }
        )

    if not pecas_norm:
        return _planejar_kitbash_offline(prompt, pecas_catalogo)

    pbr_zonas_raw = bruto.get("pbr_zonas")
    if isinstance(pbr_zonas_raw, list) and pbr_zonas_raw:
        pbr_zonas = [dict(z) for z in pbr_zonas_raw if isinstance(z, dict)]
    else:
        pbr_zonas = _construir_pbr_zonas_padrao(zonas_usadas)

    estilo = str(bruto.get("estilo") or _inferir_estilo_kitbash(prompt)).strip()
    return {
        "pecas": pecas_norm,
        "pbr_zonas": pbr_zonas,
        "estilo": estilo,
    }


def planejar_kitbash_gemini(
    prompt: str,
    pecas_catalogo: list[dict[str, Any]],
    *,
    timeout: int = 45,
) -> dict[str, Any]:
    """Planeja montagem kitbash 3D via Gemini ``/v1beta/interactions`` com fallback offline."""
    from . import cloud_ai
    from .cloud_gemini_media import _extrair_texto_gemini

    cloud_ai.registrar_licencas_cloud()
    try:
        chave, _fonte = cloud_ai._ler_chave_gemini()
    except OSError as exc:
        raise erro_provider_run(
            f"falha ao ler chave Gemini Kitbash: {exc}", modelo="gemini_kitbash"
        ) from exc
    if not chave:
        return _planejar_kitbash_offline(prompt, pecas_catalogo)

    modelo_kb = (
        os.environ.get("FORGE3D_GEMINI_KITBASH_MODEL", "").strip()
        or cloud_ai.MODELO_GEMINI_KITBASH_PADRAO
    )
    endpoint = os.environ.get("FORGE3D_GEMINI_API_URL", "").strip() or cloud_ai.URL_GEMINI_INTERACTIONS

    resumo_catalogo = [
        {
            "id": str(p.get("asset_id") or p.get("id") or ""),
            "nome": str(p.get("nome") or ""),
            "tipo": str(p.get("tipo") or "mesh"),
            "categoria": str(p.get("categoria") or "prop"),
            "tags": list(p.get("tags") or []),
        }
        for p in (pecas_catalogo or [])
        if isinstance(p, dict)
    ]

    instrucao = (
        "You are a 3D kitbash assembly planner for a commercial game asset pipeline.\n"
        f"User prompt: {prompt}\n"
        f"Available CC0 parts catalog: {json.dumps(resumo_catalogo, ensure_ascii=False)}\n"
        "Return ONLY valid JSON with exact structure:\n"
        '{"pecas": [{"id": string, "papel": string, "snap_para": string|null, '
        '"escala": number, "pbr_zona": string}], '
        '"pbr_zonas": [{"nome": string, "preset": string, "cor_hex": string}], '
        '"estilo": string}'
    )

    payload: dict[str, Any] = {
        "model": modelo_kb,
        "input": [{"type": "text", "text": instrucao}],
    }
    headers = {
        "x-goog-api-key": chave,
        "Content-Type": "application/json",
        "Api-Revision": cloud_ai.API_REVISION_GEMINI,
    }

    dados = cloud_ai._post_json_seguro(
        endpoint,
        payload,
        headers,
        timeout_s=int(timeout),
        segredos=[chave],
        provedor="Gemini",
        modelo=modelo_kb,
    )
    try:
        texto = _extrair_texto_gemini(dados)
        plano = _parsear_plano_kitbash_json(texto, prompt, pecas_catalogo)
    except ValueError as exc:
        msg_limpa = cloud_ai._sanitizar_texto_erro(str(exc), [chave])
        raise erro_provider_run(
            f"falha ao interpretar plano Kitbash Gemini ({modelo_kb}): {msg_limpa}",
            modelo="gemini_kitbash",
        ) from None

    return {
        "ok": True,
        "modo": "gemini_interactions",
        "modelo": modelo_kb,
        "prompt": prompt,
        "estilo": plano["estilo"],
        "pecas": plano["pecas"],
        "pbr_zonas": plano["pbr_zonas"],
        "licenca": dict(cloud_ai.LICENCAS_CLOUD["gemini_kitbash"]),
    }
