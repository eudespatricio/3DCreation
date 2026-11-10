"""Contrato de provider (docs/rotas-e-providers.md §6).

Provider e a **unica** superficie que pode trazer dependencia pesada. Ele gera em staging, declara
determinismo e custo, e nunca exporta, aprova ou publica.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class RawAsset:
    """Bruto produzido pelo provider. Vive so em staging."""

    dir: Path
    schema: str
    determinism: str
    arquivos: list[Path] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


class Provider(Protocol):
    nome: str
    versao: str
    determinism: str
    usa_gpu: bool
    licenca: dict

    def capabilities(self) -> set[str]: ...

    def custo(self, item: dict, perfil: dict) -> dict: ...

    def preflight(self) -> tuple[bool, str]: ...

    def gerar(self, item: dict, perfil: dict, destino: Path) -> RawAsset: ...
