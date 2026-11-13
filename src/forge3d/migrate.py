"""Migracao de lote entre versoes do contrato de entrada (`spec@1`/`@2`/`@3` -> `spec@4`).

A migracao e **textual** de proposito: lote e documento de gente, com comentarios, e um
``yaml.safe_dump`` os apagaria. O que muda entre versoes:

* ``@1 -> @2``: o item aceita ``parte`` (kit corpo/capa/arma) — superset, nada a reescrever;
* ``@2 -> @3``: o item aceita o bloco ``modular`` (D75) — superset, nada a reescrever;
* ``estilo_global`` legado (``minecraft_bedrock``) e canonicalizado no mesmo passo (D19/I14).

O que a migracao **nao** faz: inventar valor. Lote com ``rota: modular`` e sem o bloco ``modular``
nao migra — o B15 exige o bloco, e adivinhar grade/modulos seria pior que falhar (AGENTS: nao
invente numero). O lote migrado e validado com o mesmo ``spec.preparar`` do ``validate``: schema da
versao alvo **e** regras de negocio B1-B17.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import yaml

from . import spec
from .errors import ForgeError, erro_spec

__all__ = ["ALVO", "ORDEM", "planejar", "gravar", "migrar_texto"]

#: cadeia de contratos de entrada, do mais velho ao corrente
ORDEM = ("forge3d/spec@1", "forge3d/spec@2", "forge3d/spec@3", "forge3d/spec@4")
ALVO = ORDEM[-1]

_RE_SCHEMA = re.compile(r"^schema:[ \t]*(forge3d/spec@[0-9]+)[ \t]*$")
_RE_ESTILO = re.compile(r"^estilo_global:[ \t]*(\S+)[ \t]*$")


def _fim_de_linha(linha: str) -> str:
    corpo = linha.rstrip("\r\n")
    return linha[len(corpo) :]


def migrar_texto(texto: str) -> tuple[str, list[dict], str]:
    """Sobe a versao e canonicaliza alias linha a linha, preservando comentarios.

    Devolve ``(texto_novo, mudancas, versao_de_origem)``. Nao valida: quem valida e ``planejar``.
    """
    mudancas: list[dict] = []
    versao: str | None = None
    saida: list[str] = []
    for linha in texto.splitlines(keepends=True):
        corpo = linha.rstrip("\r\n")
        fim = _fim_de_linha(linha)

        achado = _RE_SCHEMA.match(corpo)
        if achado:
            versao = achado.group(1)
            if versao not in ORDEM:
                raise erro_spec(
                    f"schema de lote desconhecido: {versao!r}",
                    schema=versao,
                    aceitos=list(ORDEM),
                )
            if versao != ALVO:
                mudancas.append({"campo": "schema", "de": versao, "para": ALVO})
                corpo = f"schema: {ALVO}"

        estilo = _RE_ESTILO.match(corpo)
        if estilo:
            canonico = spec.ALIASES_ESTILO.get(estilo.group(1))
            if canonico:
                mudancas.append(
                    {"campo": "estilo_global", "de": estilo.group(1), "para": canonico}
                )
                corpo = f"estilo_global: {canonico}"

        saida.append(corpo + fim)

    if versao is None:
        raise erro_spec("lote sem a chave 'schema' no topo", aceitos=list(ORDEM))
    return "".join(saida), mudancas, versao


def _migrar_json(texto: str) -> tuple[str, list[dict], str]:
    try:
        doc = json.loads(texto)
    except ValueError as exc:
        raise erro_spec(f"lote JSON ilegivel: {exc}") from exc
    if not isinstance(doc, dict):
        raise erro_spec("lote precisa ser um objeto no topo")
    versao = doc.get("schema")
    if versao not in ORDEM:
        raise erro_spec(
            f"schema de lote desconhecido: {versao!r}", schema=versao, aceitos=list(ORDEM)
        )
    mudancas: list[dict] = []
    if versao != ALVO:
        mudancas.append({"campo": "schema", "de": versao, "para": ALVO})
        doc["schema"] = ALVO
    estilo = doc.get("estilo_global")
    if estilo in spec.ALIASES_ESTILO:
        canonico = spec.ALIASES_ESTILO[estilo]
        mudancas.append({"campo": "estilo_global", "de": estilo, "para": canonico})
        doc["estilo_global"] = canonico
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n", mudancas, versao


def _validar(texto: str) -> list[str]:
    """Valida o texto migrado com o mesmo caminho do ``validate``. Lista vazia = ok."""
    try:
        doc = yaml.safe_load(texto)
    except yaml.YAMLError as exc:
        return [f"YAML ilegivel apos a migracao: {exc}"]
    if not isinstance(doc, dict):
        return ["lote precisa ser um objeto no topo"]
    try:
        spec.preparar(copy.deepcopy(doc))
    except ForgeError as exc:
        erros = (exc.detalhes or {}).get("erros") or []
        mensagens = [
            f"{e.get('campo') or e.get('id') or '?'}: {e.get('mensagem')}"
            for e in erros[:10]
            if isinstance(e, dict)
        ]
        return mensagens or [exc.mensagem]
    return []


def planejar(caminho: str | Path) -> dict:
    """Le, migra e valida sem escrever nada. ``valido`` diz se o lote migrado passa no contrato."""
    p = Path(caminho).expanduser()
    if not p.is_file():
        raise erro_spec(f"lote nao encontrado: {p}", arquivo=str(p))
    texto = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        novo, mudancas, versao = _migrar_json(texto)
    else:
        novo, mudancas, versao = migrar_texto(texto)
    erros = _validar(novo) if mudancas else _validar(texto)
    return {
        "arquivo": str(p),
        "de": versao,
        "para": ALVO if mudancas else versao,
        "mudancas": mudancas,
        "valido": not erros,
        "erros": erros,
        "texto": novo,
    }


def gravar(plano: dict, saida: str | Path | None = None, em_lugar: bool = False) -> Path:
    """Escreve o lote migrado. Sobrescrever o original exige ``em_lugar=True``."""
    original = Path(plano["arquivo"])
    if em_lugar and saida:
        raise erro_spec("'--em-lugar' e '--saida' sao exclusivos", arquivo=str(original))
    if em_lugar:
        destino = original
    elif saida:
        destino = Path(saida).expanduser()
        if destino.resolve() == original.resolve():
            raise erro_spec(
                "destino igual ao lote de origem: use '--em-lugar' para sobrescrever",
                arquivo=str(original),
                saida=str(destino),
            )
    else:
        raise erro_spec("gravar exige '--saida' ou '--em-lugar'", arquivo=str(original))

    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_text(plano["texto"], encoding="utf-8")
    tmp.replace(destino)
    return destino
