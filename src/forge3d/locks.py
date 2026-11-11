"""Lock de GPU (D11, I6).

Em 6 GB de VRAM, dois jobs concorrentes nao coexistem: o segundo recebe ``FORGE-E-RECURSO`` em vez
de ``CUDA OOM`` no meio da geracao. Lock de arquivo com ``flock``; ``pid`` e ``run_id`` ficam no
conteudo para diagnostico de lock orfao.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from . import paths
from .errors import erro_recurso

__all__ = [
    "caminho_lock",
    "caminho_lock_destino",
    "estado",
    "lock_gpu",
    "lock_destino",
    "pid_ativo",
    "vram_livre_mb",
]

try:  # pragma: no cover - plataforma
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


def caminho_lock() -> Path:
    return paths.dir_locks() / "gpu.lock"


def caminho_lock_destino(destino: Path) -> Path:
    chave = hashlib.sha256(str(destino.resolve(strict=False)).encode("utf-8")).hexdigest()[:16]
    return paths.dir_locks() / f"destino-{chave}.lock"


def pid_ativo(pid: int) -> bool:
    """O processo ainda existe? Diagnostico de lock orfao — NAO decide posse do lock."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def vram_livre_mb() -> int | None:
    """VRAM livre em MiB via ``nvidia-smi``; None quando nao ha GPU nem ferramenta."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        saida = subprocess.run(
            [exe, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
        linhas = saida.splitlines()
        if not linhas:
            return None
        return int(linhas[0].strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def estado() -> dict:
    arq = caminho_lock()
    if not arq.is_file():
        return {"ocupado": False}
    if fcntl is None:
        return {"ocupado": True, "detalhe": "fcntl indisponivel nesta plataforma"}
    with open(arq, "a+", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            return {"ocupado": False}
        except (BlockingIOError, OSError):
            pass
    try:
        conteudo = json.loads(arq.read_text(encoding="utf-8") or "{}")
    except ValueError:
        return {"ocupado": True, "detalhe": "conteudo ilegivel"}
    return {"ocupado": True, **conteudo}


@contextmanager
def _lock_arquivo(arq: Path, run_id: str, nome: str, esperar: bool = True, timeout_s: int = 900):
    if fcntl is None:
        raise erro_recurso(f"lock de {nome} indisponivel nesta plataforma (fcntl ausente)")
    arq.parent.mkdir(parents=True, exist_ok=True)
    fh = open(arq, "a+", encoding="utf-8")
    iniciado = time.monotonic()
    try:
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fh.seek(0)
                fh.truncate()
                fh.write(json.dumps({"pid": os.getpid(), "run_id": run_id, "desde": time.time()}))
                fh.flush()
                break
            except (BlockingIOError, OSError):
                if not esperar:
                    raise erro_recurso(
                        f"lock de {nome} ocupado por {estado() if nome == 'GPU' else arq.name}",
                        lock=str(arq),
                    ) from None
                if time.monotonic() - iniciado > timeout_s:
                    raise erro_recurso(
                        f"timeout de {timeout_s}s esperando o lock de {nome}",
                        lock=str(arq),
                    ) from None
                time.sleep(0.25)
        yield {"ocupado": False, "run_id": run_id}
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.seek(0)
            fh.truncate()
        finally:
            fh.close()


@contextmanager
def lock_gpu(run_id: str, esperar: bool = True, timeout_s: int = 900):
    """Context manager de exclusividade. Sem ``esperar``, falha na hora com exit 6."""
    with _lock_arquivo(caminho_lock(), run_id, "GPU", esperar=esperar, timeout_s=timeout_s) as info:
        yield info


@contextmanager
def lock_destino(destino: Path, run_id: str, esperar: bool = True, timeout_s: int = 120):
    """Serializa publicacao e limpeza de orfaos no mesmo destino."""
    with _lock_arquivo(
        caminho_lock_destino(destino), run_id, "destino", esperar=esperar, timeout_s=timeout_s
    ) as info:
        yield info
