"""Cache de artefatos ja pos-processados e aprovados no QC."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from . import paths
from .canonical import sha256_arquivo
from .errors import ForgeError

__all__ = ["ler_cache", "salvar_cache"]


def _dir_cache(chave: str) -> Path:
    return paths.dir_cache() / chave


def salvar_cache(chave: str, origem: Path, entrada: dict) -> None:
    """Persiste artefatos finais e metadados em cache usando escrita atomica do JSON."""
    base = _dir_cache(chave)
    final = base / "final"
    if final.exists():
        shutil.rmtree(final)
    final.mkdir(parents=True, exist_ok=True)
    for arq in entrada["resultado"].get("arquivos", []):
        shutil.copyfile(origem / arq["caminho"], final / arq["caminho"])
    tmp = base / "entrada.json.tmp"
    tmp.write_text(json.dumps(entrada, sort_keys=True, indent=1), encoding="utf-8")
    os.replace(tmp, base / "entrada.json")


def ler_cache(chave: str) -> tuple[Path, dict] | None:
    """Le entrada do cache validando existencia, traversal e integridade SHA-256."""
    from .publish import _caminho_seguro

    base = _dir_cache(chave)
    entrada = base / "entrada.json"
    final = base / "final"
    if not entrada.is_file() or not final.is_dir():
        return None
    try:
        dados = json.loads(entrada.read_text(encoding="utf-8"))
    except ValueError:
        return None
    for arq in dados.get("resultado", {}).get("arquivos", []):
        try:
            alvo = _caminho_seguro(final, arq["caminho"])
        except ForgeError:
            return None
        if not alvo.is_file():
            return None
        esperado = arq.get("sha256")
        if esperado and sha256_arquivo(alvo) != esperado:
            return None
    return final, dados
