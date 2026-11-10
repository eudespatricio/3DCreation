"""Lock de GPU (D11, I6).

Em 6 GB de VRAM, dois jobs concorrentes nao coexistem: o segundo recebe ``FORGE-E-RECURSO`` em vez
de ``CUDA OOM`` no meio da geracao. Lock de arquivo com ``flock``; ``pid`` e ``run_id`` ficam no
conteudo para diagnostico de lock orfao.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from . import paths
from .errors import erro_recurso

__all__ = ["caminho_lock", "estado", "lock_gpu"]

try:  # pragma: no cover - plataforma
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


def caminho_lock() -> Path:
    return paths.dir_locks() / "gpu.lock"


def estado() -> dict:
    arq = caminho_lock()
    if not arq.is_file():
        return {"ocupado": False}
    try:
        conteudo = json.loads(arq.read_text(encoding="utf-8") or "{}")
    except ValueError:
        return {"ocupado": True, "detalhe": "conteudo ilegivel"}
    return {"ocupado": True, **conteudo}


@contextmanager
def lock_gpu(run_id: str, esperar: bool = True, timeout_s: int = 900):
    """Context manager de exclusividade. Sem ``esperar``, falha na hora com exit 6."""
    paths.dir_locks().mkdir(parents=True, exist_ok=True)
    arq = caminho_lock()
    fh = open(arq, "a+", encoding="utf-8")
    iniciado = time.monotonic()
    try:
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fh.seek(0)
                fh.truncate()
                fh.write(json.dumps({"pid": os.getpid(), "run_id": run_id, "desde": time.time()}))
                fh.flush()
                break
            except (BlockingIOError, OSError):
                if not esperar:
                    raise erro_recurso(
                        f"lock de GPU ocupado por {estado()}",
                        lock=str(arq),
                    ) from None
                if time.monotonic() - iniciado > timeout_s:
                    raise erro_recurso(
                        f"timeout de {timeout_s}s esperando o lock de GPU",
                        lock=str(arq),
                    ) from None
                time.sleep(0.25)
        yield {"ocupado": False, "run_id": run_id}
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.seek(0)
            fh.truncate()
        finally:
            fh.close()
