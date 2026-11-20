"""Helpers compartilhados de caminho, validacao de destino e E/S atomica para ``sync``."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from . import config, paths
from .errors import erro_destino, erro_path

_IDENTIFICADOR_LUAU = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _raiz_repo() -> Path | None:
    """Detecta a raiz do repositorio Forge3D sem caminho pessoal fixo (I15)."""
    for cand in Path(__file__).resolve().parents:
        if (cand / "pyproject.toml").is_file() and (cand / "src" / "forge3d").is_dir():
            return cand.resolve(strict=False)
    return None


def _sobrepoe(a: Path, b: Path) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _checar_destino_externo(alvo_raw: str | os.PathLike, campo: str = "para") -> Path:
    bruto = str(alvo_raw)
    if "\\\\wsl" in bruto or bruto.startswith("//"):
        raise erro_path(
            f"destino de sync aponta para caminho UNC de rede: {bruto}. "
            "Use caminho montado (/mnt/<letra>/...) ou ext4.",
            campo=campo,
        )
    alvo = config.normalizar(alvo_raw)
    repo = _raiz_repo()
    if repo is not None and _sobrepoe(alvo, repo):
        raise erro_destino(
            f"destino de sync nao pode apontar para o repositorio do Forge3D: {alvo}",
            destino=str(alvo),
        )
    internos = (
        paths.raiz_config(),
        paths.dir_cache(),
        paths.dir_runs(),
        paths.dir_staging(),
        paths.dir_locks(),
    )
    if alvo == paths.raiz_estado() or any(_sobrepoe(alvo, raiz) for raiz in internos):
        raise erro_destino(
            f"destino de sync nao pode apontar para estado/config interno do Forge3D: {alvo}",
            destino=str(alvo),
        )
    return alvo


def _validar_alvo(alvo_raw: str | os.PathLike, origem: Path) -> Path:
    alvo = _checar_destino_externo(alvo_raw, campo="para")
    if _sobrepoe(alvo, origem):
        raise erro_destino(
            f"destino de sync ({alvo}) nao pode coincidir nem sobrepor a origem ({origem})",
            origem=str(origem),
            destino=str(alvo),
        )
    return alvo


def _copiar_atomico(src: Path, dst: Path, tag: str) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{dst.name}.{tag}.tmp"
    try:
        with open(src, "rb") as fent, open(tmp, "wb") as fsai:
            shutil.copyfileobj(fent, fsai)
            fsai.flush()
            try:
                os.fsync(fsai.fileno())
            except OSError:
                # Alguns mounts (/mnt/<letra>/) nao suportam fsync em arquivo comum.
                pass
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dst.stat().st_size


def _escrever_atomico(dst: Path, conteudo: str, tag: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{dst.name}.{tag}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fsai:
            fsai.write(conteudo)
            fsai.flush()
            try:
                os.fsync(fsai.fileno())
            except OSError:
                # Alguns mounts (/mnt/<letra>/) nao suportam fsync em arquivo comum.
                pass
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _escapar_literal(texto: str) -> str:
    return (
        texto.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
