"""Provider `modular`: setor do WFC vira bruto do blocky (D74/D75)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge3d import modular, providers
from forge3d.providers.modular import ModularProvider


def _item(setor: list[int] | None = None, seed: int = 20261111) -> dict:
    return {
        "id": "dungeon.setor.teste",
        "tipo": "mapa_setor",
        "rota": "modular",
        "seed": seed,
        "altura_metros": 2.4,
        "pivot": "centro",
        "limite_triangulos": 20000,
        "material": "opaque",
        "colisao": "box",
        "lod": [100],
        "modular": {
            "grade": [2, 2],
            "modulos": ["reto_ns", "quatro_bocas", "curva_ne"],
            "setor": setor or [0, 0],
            "tamanho_modulo": 4.0,
        },
        "_paleta": ["#7d858f", "#3b4048", "#1d2024"],
    }


def test_gerar_escreve_o_setor_no_bruto_do_blocky(tmp_path: Path):
    bruto = ModularProvider().gerar(_item(), {}, tmp_path)
    modelo = json.loads((tmp_path / "modelo.json").read_text(encoding="utf-8"))
    assert bruto.schema == "forge3d/bruto-blocky@1"
    assert modelo["schema"] == "forge3d/bruto-blocky@1"
    assert modelo["modular"]["setor"] == [0, 0]
    assert modelo["modular"]["modulo"] in modular.CATALOGO
    assert len(modelo["modular"]["layout"]) == 2
    assert modelo["altura_m"] == pytest.approx(2.4)
    assert (tmp_path / modelo["atlas"]).is_file()
    # placa + piso sempre; parede so nos lados fechados (o modulo do setor (0,0) e aberto)
    nomes = [c["nome"] for c in modelo["caixas"]]
    assert nomes[:2] == ["placa", "piso"]
    assert len(nomes) <= 8  # max_partes do perfil: ucx per-peça
    for caixa in modelo["caixas"]:
        assert caixa["uv"] and caixa["uv_topo"]  # o atlas preencheu
        assert caixa["cor"].startswith("#")
        assert caixa["osso"] is None  # setor nao tem rig


def test_gerar_e_deterministico(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    ModularProvider().gerar(_item(), {}, a)
    ModularProvider().gerar(_item(), {}, b)
    assert (a / "modelo.json").read_bytes() == (b / "modelo.json").read_bytes()


def test_setores_diferentes_dao_modulos_do_layout(tmp_path: Path):
    layout = modular.gerar_layout((2, 2), ["reto_ns", "quatro_bocas", "curva_ne"], 20261111)
    for y in range(2):
        for x in range(2):
            bruto = ModularProvider().gerar(_item([x, y]), {}, tmp_path / f"{x}{y}")
            assert bruto.meta["modular"]["modulo"] == layout[y][x]


def test_setor_fora_da_grade_falha(tmp_path: Path):
    with pytest.raises(ValueError):
        ModularProvider().gerar(_item([5, 5]), {}, tmp_path)


def test_rota_modular_aparece_pronta_no_doctor():
    assert providers.registrados()["modular"] == "pronto"
