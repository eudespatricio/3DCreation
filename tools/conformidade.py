#!/usr/bin/env python3
"""Linter de conformidade do repositorio (GAP-004, docs/gaps.md).

Verifica:
(a) Tetos de linhas de CONTINUAR.md (200), MAPA.md (60), AGENTS.md (80), INVARIANTES.md (200);
(b) Nomes de franquia proibidos em examples/, profiles/ e schemas/ (I14);
(c) Que nenhum caminho /mnt ou UNC aparece em examples/, profiles/, schemas/ e docs/ (I12);
(d) Que pyproject.toml e __init__.py dizem a mesma versao;
(e) Que nome de projeto de jogo e caminho /home/<user>/ fixo nao entram em src/,
    profiles/, examples/ e schemas/ (I15): o pipeline e do utilitario, o projeto e consumidor.

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

# I15: nome de projeto de jogo nao entra no pipeline (o projeto e consumidor, nao preset)
RE_PROJETO = re.compile(r"gamezero|game-zero|jogo-roblox|jogo_roblox|jogoroblox", re.IGNORECASE)

# I15: caminho pessoal fixo em codigo/perfil/exemplo/schema (usa raiz de estado ou variavel)
RE_HOME_FIXO = re.compile(r"/home/[a-z0-9_.-]+/", re.IGNORECASE)

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

    # (e) nome de projeto de jogo e caminho /home fixo em src/ e nos contratos
    dirs_projeto = ["src", "profiles", "examples", "schemas"]
    for d_nome in dirs_projeto:
        dir_path = raiz / d_nome
        for arq in _arquivos_no_diretorio(dir_path):
            if "__pycache__" in arq.parts:
                continue
            try:
                linhas = arq.read_text(encoding="utf-8", errors="replace").splitlines()
                rel = arq.relative_to(raiz)
                for num_l, linha in enumerate(linhas, 1):
                    achado = RE_PROJETO.search(linha)
                    if achado:
                        violacoes.append(
                            f"I15: nome de projeto '{achado.group(0)}' em {rel}:{num_l} "
                            "(projeto e consumidor; entra por perfil/spec/allowlist)"
                        )
                    achado = RE_HOME_FIXO.search(linha)
                    if achado:
                        violacoes.append(
                            f"I15: caminho pessoal fixo '{achado.group(0)}' em {rel}:{num_l} "
                            "(use ~ ou a raiz de estado)"
                        )
            except OSError:
                continue

    # (d) versao do pacote: pyproject e __init__ tem que dizer a mesma coisa
    try:
        pyproject = (raiz / "pyproject.toml").read_text(encoding="utf-8")
        init = (raiz / "src" / "forge3d" / "__init__.py").read_text(encoding="utf-8")
        re_pyproject = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        re_init = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.MULTILINE)
        if re_pyproject and re_init and re_pyproject.group(1) != re_init.group(1):
            violacoes.append(
                f"VERSAO: pyproject {re_pyproject.group(1)} != __init__ {re_init.group(1)}"
            )
    except OSError:
        pass

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
