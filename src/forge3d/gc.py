"""``gc`` — retencao de cache, runs e staging por idade.

Nao toca no que foi publicado (``saida/``), no indice SQLite nem no ledger append-only. O cache e
content-addressed; apagar uma entrada so faz o proximo run recalcular aquele conteudo.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import locks, paths

__all__ = ["executar"]


def _esta_travado(p: Path) -> bool:
    if locks.fcntl is None:
        return False
    for cand in p.glob("*.lock"):
        if cand.is_symlink() or not cand.is_file():
            continue
        try:
            with open(cand, "r", encoding="utf-8") as fh:
                try:
                    locks.fcntl.flock(fh.fileno(), locks.fcntl.LOCK_EX | locks.fcntl.LOCK_NB)
                    locks.fcntl.flock(fh.fileno(), locks.fcntl.LOCK_UN)
                except (BlockingIOError, OSError):
                    return True
        except OSError:
            continue
    return False


def _tamanho(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for arq in p.rglob("*"):
        try:
            if arq.is_file():
                total += arq.stat().st_size
        except OSError:
            continue
    return total


def executar(manter_dias: int = 30, aplicar: bool = False) -> dict:
    """Lista (e opcionalmente remove) cache/runs/staging mais velhos que ``manter_dias``."""
    if int(manter_dias) < 1:
        from .errors import erro_spec

        raise erro_spec(f"gc: manter_dias precisa ser >= 1 (recebido {manter_dias})")

    agora = time.time()
    alvos: list[dict] = []
    for base, tipo in (
        (paths.dir_cache(), "cache"),
        (paths.dir_runs(), "runs"),
        (paths.dir_staging(), "staging"),
    ):
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            if p.is_symlink() or not p.is_dir() or p.name.startswith("."):
                continue
            if _esta_travado(p):
                continue
            try:
                idade = (agora - p.stat().st_mtime) / 86400.0
            except OSError:
                continue
            if idade < float(manter_dias):
                continue
            alvos.append(
                {
                    "tipo": tipo,
                    "caminho": str(p),
                    "dias": round(idade, 1),
                    "bytes": _tamanho(p),
                    "removido": False,
                }
            )

    alvos.sort(key=lambda a: a["dias"], reverse=True)
    if aplicar:
        for alvo in alvos:
            try:
                shutil.rmtree(alvo["caminho"])
                alvo["removido"] = True
            except OSError:
                alvo["removido"] = False

    return {
        "ok": True,
        "aplicado": bool(aplicar),
        "manter_dias": int(manter_dias),
        "total": len(alvos),
        "bytes": sum(a["bytes"] for a in alvos),
        "alvos": alvos,
    }
