"""Contrato de entrada: carregar, normalizar, validar (spec@1 a spec@6).

Ordem obrigatoria — e ela que o contrato promete:

    carregar -> normalizar (aliases + defaults por perfil) -> validar schema -> regras de negocio

Normalizar antes de validar e o que permite aceitar ``minecraft_bedrock`` como alias legado sem
que o valor canonico apareca em manifesto publicado (I14).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

from . import paths, profiles
from .errors import erro_spec
from .spec_canon import (
    ALIASES_ESTILO,
    CAMPOS_CANONICOS_ITEM,
    ROTEAMENTO,
    normalizar as _normalizar_impl,
    resolver_defaults as _resolver_defaults_impl,
    resolver_item,
)
from .spec_regras import RE_I14, regras_negocio as _regras_negocio_impl

__all__ = [
    "ALIASES_ESTILO",
    "CAMPOS_CANONICOS_ITEM",
    "ROTEAMENTO",
    "SPEC_SCHEMA",
    "SPEC_SCHEMAS",
    "carregar_arquivo",
    "preparar",
    "resolver_item",
]

_RE_I14 = RE_I14

#: contratos de entrada aceitos. spec@2..@6 sao supersets retrocompativeis de spec@1.
SPEC_SCHEMAS = {
    "forge3d/spec@1": "spec.v1.schema.json",
    "forge3d/spec@2": "spec.v2.schema.json",
    "forge3d/spec@3": "spec.v3.schema.json",
    "forge3d/spec@4": "spec.v4.schema.json",
    "forge3d/spec@5": "spec.v5.schema.json",
    "forge3d/spec@6": "spec.v6.schema.json",
}
_SPEC_SCHEMA_CACHE: dict[str, dict] = {}


def SPEC_SCHEMA(versao: str | None = "forge3d/spec@1") -> dict:  # noqa: N802
    if versao is None or versao not in SPEC_SCHEMAS:
        raise erro_spec(
            f"schema de lote desconhecido: {versao!r} (aceitos: {', '.join(SPEC_SCHEMAS)})",
            schema=versao,
        )
    if versao not in _SPEC_SCHEMA_CACHE:
        arq = paths.raiz_dados() / "schemas" / SPEC_SCHEMAS[versao]
        _SPEC_SCHEMA_CACHE[versao] = json.loads(arq.read_text(encoding="utf-8"))
    return _SPEC_SCHEMA_CACHE[versao]


def carregar_arquivo(caminho: str | Path) -> dict:
    p = Path(caminho).expanduser()
    if not p.is_file():
        raise erro_spec(f"lote nao encontrado: {p}", arquivo=str(p))
    try:
        if p.suffix.lower() in (".json",):
            doc = json.loads(p.read_text(encoding="utf-8"))
        else:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (yaml.YAMLError, ValueError) as exc:
        raise erro_spec(f"lote ilegivel ({p}): {exc}", arquivo=str(p)) from exc
    if not isinstance(doc, dict):
        raise erro_spec(f"lote precisa ser um objeto no topo ({p})", arquivo=str(p))
    doc["_arquivo"] = str(p)
    return doc


def _normalizar(doc: dict, avisos: list[dict]) -> None:
    _normalizar_impl(doc, avisos)


def _resolver_defaults(doc: dict, perfil: dict, avisos: list[dict]) -> None:
    _resolver_defaults_impl(doc, perfil, avisos)


def _validar_schema(doc: dict) -> None:
    limpo = {k: v for k, v in doc.items() if not k.startswith("_")}
    validador = jsonschema.Draft202012Validator(SPEC_SCHEMA(limpo.get("schema")))
    erros = sorted(validador.iter_errors(limpo), key=lambda e: list(e.path))
    if erros:
        detalhes = [
            {"campo": "/".join(str(p) for p in e.path) or "(raiz)", "mensagem": e.message}
            for e in erros[:10]
        ]
        raise erro_spec(
            f"spec invalida: {detalhes[0]['campo']}: {detalhes[0]['mensagem']}",
            erros=detalhes,
            total=len(erros),
        )


def _regras_negocio(doc: dict, perfil: dict) -> None:
    _regras_negocio_impl(doc, perfil)


def preparar(doc: dict) -> tuple[dict, dict, list[dict]]:
    """Normaliza e valida. Devolve ``(spec, perfil, avisos)``."""
    avisos: list[dict] = []
    _normalizar(doc, avisos)
    _validar_schema(doc)
    perfil = profiles.carregar(doc["perfil"])
    _resolver_defaults(doc, perfil, avisos)
    _validar_schema(doc)  # de novo: defaults nao podem quebrar o contrato
    _regras_negocio(doc, perfil)
    return doc, perfil, avisos
