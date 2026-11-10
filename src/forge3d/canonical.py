"""Forma canonica, hash e chave de cache (D6).

A chave nunca depende de mtime, ordem de ditado ou relogio: apenas conteudo.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = ["canon", "sha256_bytes", "sha256_arquivo", "hash_curto", "chave_cache"]


def canon(obj: Any) -> bytes:
    """JSON canonico: chaves ordenadas, sem espaco, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(dados: bytes) -> str:
    return "sha256:" + hashlib.sha256(dados).hexdigest()


def sha256_arquivo(caminho) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return "sha256:" + h.hexdigest()


def hash_curto(valor: str | bytes, n: int = 16) -> str:
    dados = valor.encode("utf-8") if isinstance(valor, str) else valor
    return hashlib.sha256(dados).hexdigest()[:n]


def chave_cache(
    item_resolvido: dict,
    pipeline_version: str,
    provider_versoes: dict[str, str],
    perfil_resolvido: dict,
) -> str:
    """Conteudo do item + versao da pipeline + versoes de provider + perfil.

    Qualquer mudanca em qualquer um dos quatro invalida o cache — de proposito.
    """
    material = {
        "item": item_resolvido,
        "pipeline": pipeline_version,
        "providers": provider_versoes,
        "perfil": perfil_resolvido,
    }
    return hashlib.sha256(canon(material)).hexdigest()
