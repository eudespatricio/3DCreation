"""Perfis de export: dado versionado, nunca logica (D4)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from . import paths
from .errors import erro_ambiente

__all__ = [
    "ANIMACOES_SUPORTADAS",
    "FRACAO_EMPUNHADURA",
    "ORCAMENTO_CENA_PADRAO",
    "TIER_TRIANGULOS_BLOCO",
    "caminho_perfil",
    "carregar",
    "escala_saida",
    "esqueleto_padrao",
    "esqueleto_para_item",
    "limite_tri_hero",
    "limite_tri_qualidade",
    "orcamento_cena_perfil",
    "perfis_disponiveis",
    "retarget",
]

TIER_TRIANGULOS_BLOCO: dict[str, str] = {
    "standard": "orcamento_triangulos",
    "hero": "orcamento_triangulos_hero",
    "ultra": "orcamento_triangulos_ultra",
}

ORCAMENTO_CENA_PADRAO: dict[str, Any] = {
    "capacidade_referencia_tris": 500_000,
    "fator_alvo": 0.80,
    "triangulos_cena_max": 400_000,
    "draw_calls_cena_max": 400,
    "vram_texturas_mb_max": 200.0,
}

#: Regra numerica da `empunhadura` (D58): fracao da altura medida a partir da base.
#: Uma regra so, usada pelo blocky (pivo declarado) e pelo QC (G2). Antes havia 10% e 20%.
FRACAO_EMPUNHADURA = 0.20

#: Clipes base procedurais e determinísticos suportados pelo pipeline (D66 / Fase B).
#: Pedir clipe fora desta lista não é erro: vira aviso `FORGE-W-ANIM`.
ANIMACOES_SUPORTADAS = ("idle", "walk", "run", "jump", "attack", "block", "hit", "death")

_BLOCOS_OBRIGATORIOS = ("unidades", "eixos", "pivot", "colisao", "rig", "material", "validacao")


def perfis_disponiveis() -> list[str]:
    d = paths.raiz_dados() / "profiles"
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


def caminho_perfil(nome: str) -> Path:
    p = Path(nome).expanduser()
    if p.is_file():
        return p
    alvo = paths.raiz_dados() / "profiles" / f"{nome}.yaml"
    if alvo.is_file():
        return alvo
    raise erro_ambiente(
        f"perfil desconhecido: {nome}. Disponiveis: {', '.join(perfis_disponiveis())}",
        perfil=nome,
    )


def carregar(nome: str) -> dict:
    arq = caminho_perfil(nome)
    try:
        doc = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise erro_ambiente(f"perfil ilegivel ({arq}): {exc}", perfil=nome) from exc
    if doc.get("schema") != "forge3d/profile@1":
        raise erro_ambiente(f"perfil {arq} sem schema 'forge3d/profile@1'", perfil=nome)
    faltando = [b for b in _BLOCOS_OBRIGATORIOS if b not in doc]
    if faltando:
        raise erro_ambiente(
            f"perfil {arq} sem blocos obrigatorios: {', '.join(faltando)}", perfil=nome
        )
    doc["_arquivo"] = str(arq)
    doc["_nome"] = nome
    return doc


# ---- consultas usadas pela normalizacao ----


def pivot_padrao(perfil: dict, tipo: str) -> str:
    return perfil["pivot"].get(tipo, "base")


def limite_tri_padrao(perfil: Mapping[str, Any], tipo: str) -> int:
    orc = perfil.get("orcamento_triangulos") or {}
    return int(orc.get(tipo, 1500))


def limite_tri_qualidade(
    perfil: Mapping[str, Any],
    tipo: str,
    qualidade: str = "standard",
) -> int:
    """Resolve limite de triangulos por perfil + qualidade (standard/hero/ultra)."""
    q = str(qualidade or "standard").strip().lower()
    if q not in TIER_TRIANGULOS_BLOCO:
        q = "standard"

    bloco = perfil.get(TIER_TRIANGULOS_BLOCO[q]) or {}
    if tipo in bloco:
        alvo = int(bloco[tipo])
    elif q == "ultra":
        hero_bloco = perfil.get("orcamento_triangulos_hero") or {}
        alvo = int(hero_bloco.get(tipo, round(limite_tri_padrao(perfil, tipo) * 2.0)))
    elif q == "hero":
        base = limite_tri_padrao(perfil, tipo)
        if tipo in (
            "personagem_humanoide",
            "criatura",
            "criatura_quadrupede",
            "criatura_alada",
            "montaria",
        ):
            if perfil.get("perfil") == "roblox-r15":
                alvo = min(10000, max(base, 10000))
            else:
                alvo = max(base, 12000)
        else:
            alvo = base
    else:
        alvo = limite_tri_padrao(perfil, tipo)

    val = perfil.get("validacao") or {}
    if tipo != "mapa_setor":
        teto_parte = (
            val.get("triangulos_por_parte_max_ultra")
            if q == "ultra" and val.get("triangulos_por_parte_max_ultra") is not None
            else val.get("triangulos_por_parte_max")
        )
        if teto_parte is not None:
            alvo = min(alvo, int(teto_parte))
    return max(50, alvo)


def limite_tri_hero(perfil: Mapping[str, Any], tipo: str) -> int:
    """Orcamento de triangulos no modo hero, delegando para ``limite_tri_qualidade``."""
    return limite_tri_qualidade(perfil, tipo, qualidade="hero")


def orcamento_cena_perfil(
    perfil: Mapping[str, Any],
    lote_spec: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Combina metas de cena do perfil e override opcional do lote para o Gate G11."""
    cfg = dict(ORCAMENTO_CENA_PADRAO)
    if isinstance(perfil.get("orcamento_cena"), Mapping):
        for k, v in perfil["orcamento_cena"].items():
            if v is not None:
                cfg[k] = v
    override = (lote_spec or {}).get("orcamento_cena")
    if isinstance(override, Mapping):
        if override.get("triangulos_max") is not None:
            cfg["triangulos_cena_max"] = int(override["triangulos_max"])
        if override.get("draw_calls_max") is not None:
            cfg["draw_calls_cena_max"] = int(override["draw_calls_max"])
        if override.get("vram_mb_max") is not None:
            cfg["vram_texturas_mb_max"] = float(override["vram_mb_max"])
    return {
        "triangulos_cena_max": int(cfg["triangulos_cena_max"]),
        "draw_calls_cena_max": int(cfg["draw_calls_cena_max"]),
        "vram_texturas_mb_max": float(cfg["vram_texturas_mb_max"]),
        "capacidade_referencia_tris": int(cfg["capacidade_referencia_tris"]),
        "fator_alvo": float(cfg["fator_alvo"]),
    }


def colisao_padrao(perfil: dict, tipo: str) -> str:
    if tipo in (
        "personagem_humanoide",
        "criatura",
        "criatura_quadrupede",
        "criatura_alada",
        "montaria",
    ):
        return "convex"
    if tipo in ("prop_estatico", "mapa_setor"):
        return "box"
    if tipo == "textura":
        return "none"
    return "convex"


def esqueleto_padrao(perfil: dict) -> str:
    return perfil["rig"]["esqueleto_padrao"]


def esqueleto_para_item(perfil: dict, item: dict) -> str:
    """Resolve esqueleto efetivo do item respeitando criaturas/montarias de spec@5."""
    explicito = str(item.get("esqueleto") or "").strip()
    if explicito:
        return explicito
    tipo = str(item.get("tipo") or "").strip()
    mapas = mapas_esqueleto(perfil)
    if tipo == "criatura_quadrupede" and "quadruped@1" in mapas:
        return "quadruped@1"
    if tipo == "criatura_alada" and "winged_mount@1" in mapas:
        return "winged_mount@1"
    if tipo == "montaria":
        pedidos = {
            str(c)
            for c in [*(item.get("clipes") or []), *(item.get("animacoes_base") or [])]
        }
        if pedidos & {"wing_flap", "glide", "ride_fly"} and "winged_mount@1" in mapas:
            return "winged_mount@1"
        if "quadruped@1" in mapas:
            return "quadruped@1"
        if "winged_mount@1" in mapas:
            return "winged_mount@1"
    return esqueleto_padrao(perfil)


def mapas_esqueleto(perfil: dict) -> dict:
    return perfil["rig"].get("mapas", {})


def escala_saida(perfil: dict) -> float:
    """Fator entre metro e unidade do arquivo exportado (D62). Perfil sem o campo = 1.0."""
    valor = float((perfil.get("unidades") or {}).get("escala_saida", 1.0))
    if valor <= 0:
        raise erro_ambiente(f"perfil com escala_saida invalida: {valor}")
    return valor


def retarget(perfil: dict, esqueleto: str) -> dict:
    """Osso semantico -> nome do osso do esqueleto (D66). Perfil antigo devolve ``{}``."""
    mapas = (perfil.get("rig") or {}).get("retarget") or {}
    return dict(mapas.get(esqueleto) or {})
