"""Rota ``mesh`` — text-to-image → image-to-3D local. **Slot de P3, sem inferência ainda.**

O contrato já existe desde P0 e esta é a razão de o slot existir agora: quando o ambiente de GPU
não está pronto, o item tem que sair `bloqueado` com **razão acionável** ("torch ausente"), não com
"não implementado". Um sistema que sabe dizer o que falta é plugável; um que só falha, não.

Cadeia prevista (duas etapas, um provider):

    prompt ──► concept (text-to-image) ──► image-to-3D ──► malha + textura

Ver docs/rotas-e-providers.md §4 e docs/riscos-e-licencas.md §1.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .base import RawAsset

VERSAO = "0.0.1-slot"
MODELO_PADRAO = "triposr"
VRAM_MINIMA_MB = 5500


def modelo_escolhido() -> str:
    """Modelo de image-to-3D. Env permite trocar sem tocar em código; licença é gate (D18)."""
    return os.environ.get("FORGE3D_MODELO_MESH", MODELO_PADRAO).strip().lower()


def dir_modelos() -> Path:
    env = os.environ.get("FORGE3D_MODELOS")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".cache" / "forge3d" / "modelos"


def _vram_livre_mb() -> int | None:
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
        return int(saida.splitlines()[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class MeshProvider:
    nome = "mesh"
    versao = VERSAO
    determinism = "D2"  # diffusion nunca e D1 (D7)
    usa_gpu = True

    def _licenca(self) -> dict:
        from . import LICENCAS

        modelo = modelo_escolhido()
        if modelo not in LICENCAS:
            from ..errors import erro_licenca

            raise erro_licenca(
                f"FORGE3D_MODELO_MESH='{modelo}' fora da allowlist comercial. "
                f"Permitidos: {', '.join(sorted(LICENCAS))}",
                modelo=modelo,
            )
        return dict(LICENCAS[modelo])

    @property
    def licenca(self) -> dict:
        return self._licenca()

    def capabilities(self) -> set[str]:
        return {"organic", "riggable", "pbr", "detail"}

    def custo(self, item: dict, perfil: dict) -> dict:
        # concept (text-to-image) + image-to-3D, ambos medidos so em P3
        return {"segundos_estimados": 35.0, "vram_mb": VRAM_MINIMA_MB, "disco_mb": 250}

    def preflight(self) -> tuple[bool, str]:
        """Diagnóstico nomeado: cada falta vira uma frase que diz o que instalar."""
        from ..errors import ForgeError

        try:
            self._licenca()
        except ForgeError as exc:
            return False, exc.mensagem

        try:
            import torch  # noqa: F401
        except Exception:  # noqa: BLE001 - ausencia e o caso normal hoje
            return False, (
                "P3: torch ausente — instale o extra GPU (docs/dependencias.md §4) e rode de novo"
            )

        if not getattr(torch, "cuda", None) or not torch.cuda.is_available():
            return False, "P3: torch instalado sem CUDA disponivel"

        livre = _vram_livre_mb()
        if livre is not None and livre < VRAM_MINIMA_MB:
            return False, f"P3: VRAM livre {livre} MiB < {VRAM_MINIMA_MB} MiB exigidos"

        pesos = dir_modelos() / modelo_escolhido()
        if not pesos.is_dir():
            return False, f"P3: pesos de '{modelo_escolhido()}' ausentes em {pesos}"

        return False, (
            "P3: ambiente pronto, inferencia ainda nao implementada (proximo passo do roadmap)"
        )

    def gerar(self, item: dict, perfil: dict, destino: Path) -> RawAsset:
        from ..errors import erro_provider_run

        pronto, razao = self.preflight()
        raise erro_provider_run(
            f"rota mesh nao gera nesta fase: {razao}",
            id=item.get("id"),
            modelo=modelo_escolhido(),
            pronto=pronto,
        )
