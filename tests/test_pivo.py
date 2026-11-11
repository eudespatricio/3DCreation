"""D58: a regra `empunhadura` e numerica e o G2 mede as quatro regras de pivo."""

from __future__ import annotations

import pytest

from forge3d.profiles import FRACAO_EMPUNHADURA
from forge3d.providers.blocky import _pivos
from forge3d.qc import _desvio_pivo


def test_base_mede_a_distancia_do_minimo():
    assert _desvio_pivo("base", 0.0, 1.0) == pytest.approx(0.0)
    assert _desvio_pivo("base", 0.25, 1.25) == pytest.approx(0.25)


def test_centro_mede_o_meio_da_caixa():
    assert _desvio_pivo("centro", -0.5, 0.5) == pytest.approx(0.0)
    assert _desvio_pivo("centro", 0.0, 1.0) == pytest.approx(0.5)


def test_topo_mede_a_distancia_do_maximo():
    assert _desvio_pivo("topo", -1.0, 0.0) == pytest.approx(0.0)
    assert _desvio_pivo("topo", -1.0, 0.2) == pytest.approx(0.2)


def test_empunhadura_mede_a_fracao_do_contrato():
    altura = 1.0
    deslocado = -FRACAO_EMPUNHADURA * altura
    assert _desvio_pivo("empunhadura", deslocado, deslocado + altura) == pytest.approx(0.0)


def test_empunhadura_desalinhada_reprova():
    """Pivo na base (min_y = 0) quando a regra pede 20% tem que acusar o desvio."""
    desvio = _desvio_pivo("empunhadura", 0.0, 1.0)
    assert desvio == pytest.approx(0.20)


def test_regra_desconhecida_nao_mede():
    assert _desvio_pivo("qualquer", 0.0, 1.0) is None


def test_blocky_declara_a_mesma_fracao():
    """D58: o pivo declarado pelo blocky tem que ser a fracao unica, nao 10% nem o cabo."""
    caixas = [{"nome": "corpo", "min": [0.0, 0.0, 0.0], "max": [1.0, 1.0, 2.0]}]
    pivos = _pivos(caixas, "prop_equipavel")
    assert pivos["empunhadura"][2] == pytest.approx(FRACAO_EMPUNHADURA * 2.0, abs=1e-6)
