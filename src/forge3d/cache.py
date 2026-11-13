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
    """Persiste artefatos finais e metadados em cache com staging e troca atomica."""
    base = _dir_cache(chave)
    base.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    final = base / "final"
    final_tmp = base / f"final.tmp.{pid}"
    final_old = base / f"final.old.{pid}"
    if final_tmp.exists():
        shutil.rmtree(final_tmp)
    final_tmp.mkdir(parents=True, exist_ok=True)
    try:
        for arq in entrada["resultado"].get("arquivos", []):
            dst = final_tmp / arq["caminho"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origem / arq["caminho"], dst)

        tmp = base / f"entrada.json.tmp.{pid}"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(entrada, sort_keys=True, indent=1))
            fh.flush()
            os.fsync(fh.fileno())

        if final_old.exists():
            shutil.rmtree(final_old)
        if final.exists():
            os.replace(final, final_old)
        os.replace(final_tmp, final)
        if final_old.exists():
            shutil.rmtree(final_old, ignore_errors=True)
        os.replace(tmp, base / "entrada.json")
    except Exception:
        shutil.rmtree(final_tmp, ignore_errors=True)
        raise


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
