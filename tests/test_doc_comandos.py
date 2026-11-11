"""Portão: o comando citado na documentação tem que existir no CLI.

O `tools/check-p0.py` confere caminho de arquivo citado; este teste confere **verbo e flag**. Foi o
que deixou passar `forge3d publish`, `--no-publish` e `verify --only` por meses sem ninguém notar.

Só docs vivos entram: o ledger (`DECISOES.md`), o `CONSELHOS.md`, o guia de delegação (que fala do
`agentapi`, não do Forge3D) e os snapshots de janela ficam de fora.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from forge3d.cli.comandos import construir_parser

RAIZ = Path(__file__).resolve().parents[1]

EXCLUIDOS = {
    "DECISOES.md",
    "CONSELHOS.md",
    "docs/delegacao.md",
    "docs/revisao-janela-2026-11-10.md",
    "docs/avaliacao.md",
    "docs/goal-proxima-janela.md",
}

#: `forge3d <verbo>` no inicio do trecho, em code span (`...`) ou precedido de `$`/`>`
RE_INVOCACAO = re.compile(r"(?:^\s*(?:-\s*)?|[`$>]\s*)forge3d\s+([^\s`]+)([^\n`]*)")
RE_FLAG = re.compile(r"--[a-z][a-z0-9-]+")


def _docs_vivos() -> list[Path]:
    nomes = ("README.md", "AGENTS.md", "MAPA.md", "INVARIANTES.md", "CONTINUAR.md")
    arquivos = [RAIZ / nome for nome in nomes]
    arquivos += sorted((RAIZ / "docs").glob("*.md"))
    vivos = []
    for arquivo in arquivos:
        if not arquivo.is_file():
            continue
        if arquivo.relative_to(RAIZ).as_posix() in EXCLUIDOS:
            continue
        vivos.append(arquivo)
    return vivos


def _superficie() -> dict[str, set[str]]:
    """Subcomandos e flags reais, lidos do próprio argparse."""
    parser = construir_parser()
    acao = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    superficie: dict[str, set[str]] = {}
    for nome, sub in acao.choices.items():
        flags = {"-h", "--help"}
        for opcao in sub._actions:
            flags.update(opcao.option_strings)
        superficie[nome] = flags
    return superficie


def _segmentos(linha: str):
    """Corta em operadores de shell: flag de outro comando não conta."""
    yield from re.split(r"&&|\|\||\||;|#", linha)


def test_comandos_citados_existem_no_cli():
    superficie = _superficie()
    problemas: list[str] = []
    for arquivo in _docs_vivos():
        rel = arquivo.relative_to(RAIZ).as_posix()
        for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), 1):
            for segmento in _segmentos(linha):
                for achado in RE_INVOCACAO.finditer(segmento):
                    verbo = achado.group(1)
                    if verbo.startswith("-"):
                        continue  # forge3d --version
                    if verbo not in superficie:
                        problemas.append(f"{rel}:{numero}: subcomando inexistente: {verbo}")
                        continue
                    for flag in RE_FLAG.findall(achado.group(2)):
                        if flag not in superficie[verbo]:
                            problemas.append(f"{rel}:{numero}: `{verbo}` nao aceita {flag}")
    assert not problemas, "documentacao cita comando que o CLI nao tem:\n" + "\n".join(problemas)


def test_fixtures_citados_existem():
    problemas: list[str] = []
    for arquivo in _docs_vivos():
        rel = arquivo.relative_to(RAIZ).as_posix()
        for citado in sorted(
            set(re.findall(r"tests/fixtures/[a-z0-9_./-]+\.(?:yaml|json|glb)", arquivo.read_text(encoding="utf-8")))
        ):
            if not (RAIZ / citado).is_file():
                problemas.append(f"{rel}: fixture inexistente: {citado}")
    assert not problemas, "\n".join(problemas)
