"""Cache de artefatos ja pos-processados e aprovados no QC."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from . import paths
from .canonical import hash_curto, sha256_arquivo
from .errors import ForgeError

__all__ = ["ler_cache", "ler_ultimo_registro_item", "salvar_cache"]


def _dir_cache(chave: str) -> Path:
    return paths.dir_cache() / chave


def _ponteiro_item(item_id: str) -> Path:
    # ``.por_id`` comeca com ponto: o gc (gc.py) pula diretorios ocultos, o ponteiro sobrevive.
    return paths.dir_cache() / ".por_id" / f"{hash_curto(str(item_id), 16)}.json"


def _gravar_ponteiro_item(chave: str, entrada: dict) -> None:
    """Ultima chave gravada por item: base do diagnostico de miss (cache_diag)."""
    item = entrada.get("item")
    if not isinstance(item, dict) or not item.get("id"):
        return
    item_id = str(item["id"])
    alvo = _ponteiro_item(item_id)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    registro = {
        "item_id": item_id,
        "chave": chave,
        "chave_material": entrada.get("chave_material"),
        "provider": entrada.get("provider"),
        "item": item,
    }
    tmp = alvo.with_name(f"{alvo.name}.tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(registro, sort_keys=True, indent=1))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, alvo)


def ler_ultimo_registro_item(item_id: str) -> dict | None:
    """Ponteiro do ultimo cache salvo para ``item_id``; None se ausente ou ilegivel."""
    alvo = _ponteiro_item(item_id)
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dados if isinstance(dados, dict) else None


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
    _gravar_ponteiro_item(chave, entrada)


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
