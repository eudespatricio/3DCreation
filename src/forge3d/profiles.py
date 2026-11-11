"""Perfis de export: dado versionado, nunca logica (D4)."""

from __future__ import annotations

from pathlib import Path

import yaml

from . import paths
from .errors import erro_ambiente

__all__ = ["carregar", "caminho_perfil", "perfis_disponiveis", "FRACAO_EMPUNHADURA"]

#: Regra numerica da `empunhadura` (D58): fracao da altura medida a partir da base.
#: Uma regra so, usada pelo blocky (pivo declarado) e pelo QC (G2). Antes havia 10% e 20%.
FRACAO_EMPUNHADURA = 0.20

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


def limite_tri_padrao(perfil: dict, tipo: str) -> int:
    orc = perfil.get("orcamento_triangulos", {})
    return int(orc.get(tipo, 1500))


def colisao_padrao(perfil: dict, tipo: str) -> str:
    if tipo in ("personagem_humanoide", "criatura"):
        return "convex"
    if tipo in ("prop_estatico", "mapa_setor"):
        return "box"
    if tipo == "textura":
        return "none"
    return "convex"


def esqueleto_padrao(perfil: dict) -> str:
    return perfil["rig"]["esqueleto_padrao"]


def mapas_esqueleto(perfil: dict) -> dict:
    return perfil["rig"].get("mapas", {})
