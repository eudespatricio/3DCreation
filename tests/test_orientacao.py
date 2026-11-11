"""Regressao do GAP-048: personagem de cabeca para baixo tem que ser corrigido.

O caso real (conceito externo, 11/11/2026) saiu de cabeca para baixo com G1-G10 verdes: com uma
arma grande ao lado, `razao_topo_base` deu 0,988 e `centro_area` 6,18/12 — os dois sinais antigos
ficaram neutros. A fixture sintetica reproduz o padrao:
  * `personagem_upright.glb` — sola chata embaixo, cabeca estreita em cima, arma lateral e gola
    larga (para as regras antigas ficarem neutras); `invertido` tem que dar False.
  * `personagem_invertido.glb` — o mesmo mesh girado 180 no X; tem que ser espelhado, com
    `invertido_contato` True (o sinal novo e o do contato chato da sola).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
DRIVER = RAIZ / "tests" / "fixtures" / "checa_orientacao.py"
POSTPROCESS = RAIZ / "blender" / "postprocess.py"
BLENDER = shutil.which("blender") or str(Path.home() / ".local" / "bin" / "blender")


def _canonicalizar(glb: Path) -> dict:
    proc = subprocess.run(
        [
            BLENDER,
            "--background",
            "--factory-startup",
            "--python",
            str(DRIVER),
            "--",
            str(glb),
            str(POSTPROCESS),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    linha = next(
        (l for l in proc.stdout.splitlines() if l.startswith("RESULTADO ")),
        None,
    )
    assert linha is not None, (proc.stdout[-2000:], proc.stderr[-2000:])
    return json.loads(linha[len("RESULTADO ") :])


@pytest.mark.blender
@pytest.mark.lento
def test_personagem_upright_nao_e_invertido():
    info = _canonicalizar(RAIZ / "tests" / "fixtures" / "personagem_upright.glb")
    assert info["invertido"] is False, info
    # as regras antigas ficam neutras de proposito (e a nova tambem nao dispara)
    assert info["razao_topo_base"] <= 1.5, info
    assert info["centro_area"] >= 5.76, info
    assert info["invertido_contato"] is False, info


@pytest.mark.blender
@pytest.mark.lento
def test_personagem_invertido_com_prop_grande_e_corrigido():
    info = _canonicalizar(RAIZ / "tests" / "fixtures" / "personagem_invertido.glb")
    assert info["invertido"] is True, info
    assert info["invertido_contato"] is True, info
    assert info["contato_topo"] > 3.0 * info["contato_base"], info
