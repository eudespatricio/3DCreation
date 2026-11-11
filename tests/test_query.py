"""Indice consultavel (`query`) — P6: o "by demand" do roadmap.

O indice e estado do utilitario (D24), alimentado pelo `publish`; aqui o teste usa o mesmo
`_indice_upsert` do publish para nao testar um SQL paralelo que ninguem roda.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge3d import publish
from forge3d.cli.main import main

RAIZ = Path(__file__).resolve().parents[1]
BASE = json.loads((RAIZ / "examples/manifest.exemplo.v3.json").read_text(encoding="utf-8"))


def _manifesto(asset_id: str, projeto: str, perfil: str, tris: int, tags: list[str]) -> dict:
    m = json.loads(json.dumps(BASE))
    m["asset_id"] = asset_id
    m["projeto"] = projeto
    m["perfil"] = perfil
    m["tags"] = tags
    m["geometry"]["triangulos"] = tris
    return m


@pytest.fixture()
def indice(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("FORGE3D_HOME", raising=False)
    monkeypatch.delenv("FORGE3D_CONFIG", raising=False)
    for manifesto in (
        _manifesto("dungeon.setor.x0y0", "demo", "godot4", 48, ["dungeon", "setor"]),
        _manifesto("personagem.heroi.01", "jogo_a", "roblox-r15", 1200, ["heroi"]),
        _manifesto("prop.bule.01", "jogo_a", "godot4", 7960, ["prop", "heroi"]),
    ):
        publish._indice_upsert(manifesto, tmp_path / "destino")
    return tmp_path


def test_indice_devolve_tudo_em_ordem_estavel(indice):
    linhas = publish.consultar()
    assert len(linhas) == 3
    assert [linha["asset_id"] for linha in linhas] == sorted(linha["asset_id"] for linha in linhas)


def test_filtro_por_projeto(indice):
    ids = [linha["asset_id"] for linha in publish.consultar(projeto="jogo_a")]
    assert ids == ["personagem.heroi.01", "prop.bule.01"]


def test_filtro_por_perfil(indice):
    ids = [linha["asset_id"] for linha in publish.consultar(perfil="roblox-r15")]
    assert ids == ["personagem.heroi.01"]


def test_filtro_por_teto_de_triangulos(indice):
    ids = [linha["asset_id"] for linha in publish.consultar(max_tris=1000)]
    assert ids == ["dungeon.setor.x0y0"]


def test_filtro_por_tag(indice):
    ids = [linha["asset_id"] for linha in publish.consultar(tag="heroi")]
    assert ids == ["personagem.heroi.01", "prop.bule.01"]


def test_cli_query_json_tem_contrato(indice, capsys):
    assert main(["query", "--json"]) == 0
    relatorio = json.loads(capsys.readouterr().out)
    assert relatorio["schema"] == "forge3d/query@1"
    assert relatorio["total"] == 3
    assert len(relatorio["assets"]) == 3


def test_cli_query_combina_filtros(indice, capsys):
    assert main(["query", "--projeto", "jogo_a", "--max-tris", "2000", "--json"]) == 0
    relatorio = json.loads(capsys.readouterr().out)
    assert relatorio["total"] == 1
    assert relatorio["assets"][0]["asset_id"] == "personagem.heroi.01"


def test_indice_vazio_responde_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home2"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state2"))
    monkeypatch.delenv("FORGE3D_HOME", raising=False)
    assert publish.consultar() == []
    assert main(["query", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 0
