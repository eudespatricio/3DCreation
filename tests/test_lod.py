"""Testes da metrica de LOD por silhueta (GAP-013, `tools/lod_qualidade.py`)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _ferramenta():
    spec = importlib.util.spec_from_file_location(
        "lod_qualidade", RAIZ / "tools" / "lod_qualidade.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_iou_de_mascara_com_ela_mesma_e_um():
    lq = _ferramenta()
    quadrado = [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)]
    triangulos = [(0, 1, 2), (0, 2, 3)]
    caixa = [(-1.0, 1.0), (-1.0, 1.0), (-1.0, 1.0)]
    mascara = lq._mascara(quadrado, triangulos, "frente", caixa, 64)
    assert lq._iou(mascara, mascara) == 1.0


def test_iou_de_mascara_deslocada_e_menor():
    lq = _ferramenta()
    caixa = [(-1.0, 1.0), (-1.0, 1.0), (-1.0, 1.0)]
    triangulos = [(0, 1, 2), (0, 2, 3)]
    quadrado = [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)]
    metade = [(-1.0, -1.0, 0.0), (0.0, -1.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 1.0, 0.0)]
    a = lq._mascara(quadrado, triangulos, "frente", caixa, 64)
    b = lq._mascara(metade, triangulos, "frente", caixa, 64)
    assert 0.4 < lq._iou(a, b) < 0.6


def test_pares_usa_o_manifesto_quando_existe(tmp_path):
    """Arquivo que saiu do manifesto nao entra na conta (sobra de publish antigo)."""
    lq = _ferramenta()
    for nome in ("a.glb", "a_LOD1.glb", "a_LOD2.glb"):
        (tmp_path / nome).write_bytes(b"glb")
    (tmp_path / "a.manifest.json").write_text(
        json.dumps(
            {
                "asset_id": "a",
                "files": [
                    {"caminho": "a.glb", "papel": "mesh"},
                    {"caminho": "a_LOD1.glb", "papel": "lod"},
                ],
            }
        ),
        encoding="utf-8",
    )
    pares = lq._pares([tmp_path])
    assert set(pares["a"]) == {"LOD0", "LOD1"}
