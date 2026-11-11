#!/usr/bin/env python3
"""Linter de conformidade do repositorio (GAP-004, docs/gaps.md).

Verifica:
(a) Tetos de linhas de CONTINUAR.md (200), MAPA.md (60), AGENTS.md (80), INVARIANTES.md (200);
(b) Nomes de franquia proibidos em examples/, profiles/ e schemas/ (I14);
(c) Que nenhum caminho /mnt ou UNC aparece em examples/, profiles/, schemas/ e docs/ (I12).

Stdlib apenas.
Saida: exit 0 se limpo, exit 1 com uma linha por violacao.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Tetos maximos de linhas por arquivo de contexto
TETOS_LINHAS = {
    "CONTINUAR.md": 200,
    "MAPA.md": 60,
    "AGENTS.md": 80,
    "INVARIANTES.md": 200,
}

# I14: Franquias proibidas em contratos/exemplos/perfis/schemas
RE_FRANQUIA = re.compile(
    r"minecraft|fortnite|zelda|mario|pokemon|call of duty",
    re.IGNORECASE,
)

# I12: Caminhos proibidos (/mnt/<letra>/ ou UNC / \\wsl)
RE_CAMINHO_PROIBIDO = re.compile(
    r"/mnt/[a-zA-Z]/|\\\\wsl|\\\\\\\\[a-zA-Z0-9_.-]+",
    re.IGNORECASE,
)

EXTENSOES_TEXTO = {".yaml", ".yml", ".json", ".md", ".txt", ".toml", ".py", ".sh"}


def _arquivos_no_diretorio(diretorio: Path) -> list[Path]:
    if not diretorio.is_dir():
        return []
    arquivos = []
    for raiz, _, filenames in os.walk(diretorio):
        for f in filenames:
            p = Path(raiz) / f
            if p.suffix.lower() in EXTENSOES_TEXTO or p.suffix == "":
                arquivos.append(p)
    return sorted(arquivos)


def verificar_conformidade(raiz: Path) -> list[str]:
    """Executa todas as verificacoes de conformidade contra o diretorio raiz.

    Devolve a lista de strings com uma linha descritiva por violacao.
    """
    violacoes: list[str] = []

    # (a) Tetos de linhas
    for nome_arq, limite in TETOS_LINHAS.items():
        caminho = raiz / nome_arq
        if caminho.is_file():
            try:
                linhas = len(caminho.read_text(encoding="utf-8", errors="replace").splitlines())
                if linhas > limite:
                    violacoes.append(
                        f"TETO: {nome_arq} excede limite de {limite} linhas (atual: {linhas})"
                    )
            except OSError as err:
                violacoes.append(f"TETO: erro ao ler {nome_arq}: {err}")

    # (b) Franquias proibidas em examples/, profiles/ e schemas/
    dirs_franquia = ["examples", "profiles", "schemas"]
    for d_nome in dirs_franquia:
        dir_path = raiz / d_nome
        for arq in _arquivos_no_diretorio(dir_path):
            try:
                linhas = arq.read_text(encoding="utf-8", errors="replace").splitlines()
                rel = arq.relative_to(raiz)
                for num_l, linha in enumerate(linhas, 1):
                    match = RE_FRANQUIA.search(linha)
                    if match:
                        violacoes.append(
                            f"I14: franquia proibida '{match.group(0)}' encontrada em {rel}:{num_l}"
                        )
            except OSError:
                continue

    # (c) Caminhos proibidos (/mnt ou UNC) em examples/, profiles/, schemas/ e docs/
    dirs_caminho = ["examples", "profiles", "schemas", "docs"]
    for d_nome in dirs_caminho:
        dir_path = raiz / d_nome
        for arq in _arquivos_no_diretorio(dir_path):
            try:
                linhas = arq.read_text(encoding="utf-8", errors="replace").splitlines()
                rel = arq.relative_to(raiz)
                for num_l, linha in enumerate(linhas, 1):
                    match = RE_CAMINHO_PROIBIDO.search(linha)
                    if match:
                        violacoes.append(
                            f"I12: caminho proibido '{match.group(0)}' encontrado em {rel}:{num_l}"
                        )
            except OSError:
                continue

    return violacoes


def main() -> int:
    parser = argparse.ArgumentParser(description="Linter de conformidade do repositorio (GAP-004)")
    parser.add_argument(
        "raiz",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1]),
        help="Diretorio raiz do repositorio a verificar (default: raiz do repo)",
    )
    args = parser.parse_args()

    raiz = Path(args.raiz).resolve()
    violacoes = verificar_conformidade(raiz)

    if violacoes:
        for v in violacoes:
            print(v)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
