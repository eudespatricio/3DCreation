"""Teste de GPU do estagio concept (roda so com FORGE3D_CONCEPT_E2E=1).

O teste normal da suite nao baixa modelo nem ocupa GPU; este e o oraculo manual do provider.
"""

from __future__ import annotations

import os

import pytest

from forge3d.providers.concept import ConceptProvider

pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.environ.get("FORGE3D_CONCEPT_E2E") != "1",
        reason="defina FORGE3D_CONCEPT_E2E=1 para rodar o concept na GPU",
    ),
]


def test_concept_gera_png_com_seed_e_proveniencia(tmp_path):
    item = {
        "id": "concept.teste.01",
        "prompt": (
            "full body front view of an original humanoid robot sentinel, T-pose, "
            "arms extended, white and black armor with an orange core"
        ),
        "seed": 20261110,
    }
    resultado = ConceptProvider().gerar(item, tmp_path)
    png = resultado["png"]
    meta = resultado["meta"]
    assert png.is_file()
    assert meta["ok"] is True
    assert meta["png_bytes"] > 10_000
    assert meta["seed"] == 20261110
    assert meta["licenca"]["uso_comercial"] is True
    assert "Stable Diffusion" in meta["licenca"]["modelo"]
    assert meta["png_sha256"].startswith("sha256:")
