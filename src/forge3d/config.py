"""Allowlist de destino e guarda de caminho (D23, I12, I13).

Regra: **deny by default**. O unico destino gravavel sem configuracao e o sandbox do proprio
Forge3D (``raiz_estado()/saida``). Projeto de jogo so vira destino depois de autorizacao explicita
e registrada em ``~/.config/forge3d/allowlist.yaml``.

Por que tao duro: o utilitario roda por demanda, muitas vezes de dentro do repositorio de um jogo.
Um destino errado publica asset no projeto errado, e isso nao tem desfazer barato.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from . import paths
from .errors import erro_destino, erro_path

__all__ = [
    "carregar",
    "normalizar",
    "validar_caminho",
    "destino_permitido",
    "adicionar",
    "remover",
    "listar",
]


def normalizar(caminho: str | os.PathLike) -> Path:
    """Expande ``~``, resolve symlinks e devolve absoluto (sem exigir existencia)."""
    p = Path(str(caminho)).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    # resolve sem strict para nao exigir que o destino exista ainda
    try:
        return p.resolve(strict=False)
    except OSError:  # pragma: no cover - filesystem exoticos
        return p.absolute()


def validar_caminho(caminho: Path, campo: str = "destino") -> None:
    """Recusa filesystem cruzado e caminho de terceiro (I12)."""
    bruto = str(caminho)
    if "\\\\wsl" in bruto or bruto.startswith("//"):
        raise erro_path(
            f"{campo} aponta para caminho UNC de rede: {bruto}. Rode sobre ext4 sob /home.",
            campo=campo,
        )
    if bruto.startswith("/mnt/") or "/mnt/" in bruto:
        raise erro_path(
            f"{campo} aponta para /mnt (drvfs): {bruto}. I/O lento e hash instavel; use ext4 sob /home.",
            campo=campo,
        )


def _ler_documento() -> dict:
    arq = paths.arquivo_allowlist()
    if not arq.is_file():
        return {"schema": "forge3d/allowlist@1", "raizes": []}
    doc = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
    if doc.get("schema") != "forge3d/allowlist@1":
        raise erro_destino(
            f"allowlist em {arq} sem schema 'forge3d/allowlist@1'",
            arquivo=str(arq),
        )
    if not isinstance(doc.get("raizes"), list):
        raise erro_destino(f"allowlist em {arq} sem lista 'raizes'", arquivo=str(arq))
    return doc


def carregar() -> list[Path]:
    """Raizes autorizadas: as do arquivo + o sandbox do proprio utilitario."""
    raizes = [paths.dir_saida(), paths.raiz_estado()]
    for bruta in _ler_documento().get("raizes", []):
        try:
            raizes.append(normalizar(bruta))
        except (TypeError, ValueError):
            continue
    return raizes


def listar() -> list[str]:
    return [str(p) for p in carregar()]


def destino_permitido(destino: str | os.PathLike) -> bool:
    alvo = normalizar(destino)
    for raiz in carregar():
        try:
            alvo.relative_to(raiz)
            return True
        except ValueError:
            continue
    return False


def validar_destino(destino: str | os.PathLike) -> Path:
    """Guarda completa: caminho proibido + allowlist. Devolve o absoluto normalizado."""
    alvo = normalizar(destino)
    validar_caminho(alvo)
    if not destino_permitido(alvo):
        raise erro_destino(
            f"destino fora da allowlist: {alvo}. "
            f"Autorize com: forge3d allowlist add {alvo}",
            destino=str(alvo),
            allowlist=listar(),
        )
    return alvo


def adicionar(caminho: str | os.PathLike) -> Path:
    alvo = normalizar(caminho)
    validar_caminho(alvo)
    doc = _ler_documento()
    atuais = [str(normalizar(p)) for p in doc.get("raizes", [])]
    if str(alvo) in atuais:
        return alvo
    doc["raizes"] = sorted(set(atuais + [str(alvo)]))
    _gravar(doc)
    return alvo


def remover(caminho: str | os.PathLike) -> bool:
    alvo = str(normalizar(caminho))
    doc = _ler_documento()
    atuais = [str(normalizar(p)) for p in doc.get("raizes", [])]
    if alvo not in atuais:
        return False
    doc["raizes"] = [p for p in atuais if p != alvo]
    _gravar(doc)
    return True


def _gravar(doc: dict) -> None:
    arq = paths.arquivo_allowlist()
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(doc, sort_keys=True, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    os.replace(tmp, arq)
