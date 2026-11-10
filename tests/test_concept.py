"""Testes do estagio concept e da proveniencia no manifesto (sem GPU)."""

from __future__ import annotations

import pytest

from forge3d import publish
from forge3d.providers import LICENCAS
from forge3d.providers.concept import ConceptProvider
from forge3d.providers.mesh import MeshProvider


def test_sd15_esta_na_allowlist_comercial():
    assert "sd15" in LICENCAS
    assert LICENCAS["sd15"]["uso_comercial"] is True
    assert "OpenRAIL" in LICENCAS["sd15"]["notice"]


def test_concept_preflight_sem_venv_da_razao_acionavel(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE3D_VENV_CONCEPT", str(tmp_path / "sem-venv"))
    pronto, razao = ConceptProvider().preflight()
    assert pronto is False
    assert "venv" in razao.lower(), razao


def test_mesh_com_origem_nao_checa_concept(monkeypatch):
    monkeypatch.setattr(MeshProvider, "preflight", lambda self: (True, "mesh ok"))

    def nao_deveria(self):
        raise AssertionError("concept nao deveria ser checado quando ha origem")

    monkeypatch.setattr(ConceptProvider, "preflight", nao_deveria)
    pronto, razao = MeshProvider().preflight_item({"origem": "concept.png"})
    assert pronto is True
    assert razao == "mesh ok"


def test_mesh_sem_origem_checa_concept(monkeypatch):
    monkeypatch.setattr(MeshProvider, "preflight", lambda self: (True, "mesh ok"))
    monkeypatch.setattr(
        ConceptProvider, "preflight", lambda self: (False, "P3.5: venv ausente")
    )
    pronto, razao = MeshProvider().preflight_item({"prompt": "corpo", "seed": 1})
    assert pronto is False
    assert "P3.5" in razao


def test_manifesto_grava_providers_texture_e_licenca_combinada():
    resultado = {
        "arquivos": [
            {
                "caminho": "a.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 1,
                "sha256": "sha256:" + "0" * 64,
                "bytes": 10,
            }
        ],
        "concept": {
            "modelo": "stable-diffusion-v1-5/stable-diffusion-v1-5",
            "versao": "0.1.0",
            "revisao": "451f4fe16113bff5a5d2269ed5ad43b0592e9a14",
            "seed": 7,
            "licenca": {
                "modelo": "Stable Diffusion 1.5",
                "uso_comercial": True,
                "notice": "Stable Diffusion 1.5 sob CreativeML OpenRAIL-M.",
            },
        },
    }
    relatorio = {
        "aprovado": True,
        "gates": [{"id": "G1", "status": "ok"}],
        "medidas": {
            "triangulos": 1,
            "vertices": 1,
            "bbox_m": [0.1, 0.1, 0.1],
            "materiais": 1,
            "ossos": 0,
            "partes_colisao": 0,
        },
    }
    manifesto = publish.montar_manifesto(
        item={"id": "a.b", "rota": "mesh", "seed": 7},
        spec_doc={"projeto": "demo", "perfil": "godot4", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4",
        provider={"nome": "mesh", "versao": "x", "determinism": "D2"},
        resultado=resultado,
        relatorio_qc=relatorio,
        licenca={"modelo": "TripoSR", "uso_comercial": True, "notice": "TripoSR (MIT)."},
        run_id="run-teste",
    )
    textura = manifesto["providers"]["texture"]
    assert textura["name"] == "concept/stable-diffusion-v1-5"
    assert textura["version"].startswith("0.1.0+451f4fe")
    assert textura["seed"] == 7
    assert "Concept:" in manifesto["licenca"]["notice"]
    assert "OpenRAIL" in manifesto["licenca"]["notice"]


def test_manifesto_sem_concept_nao_cria_provider_texture():
    resultado = {
        "arquivos": [
            {
                "caminho": "a.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 1,
                "sha256": "sha256:" + "0" * 64,
                "bytes": 10,
            }
        ]
    }
    relatorio = {
        "aprovado": True,
        "gates": [{"id": "G1", "status": "ok"}],
        "medidas": {
            "triangulos": 1,
            "vertices": 1,
            "bbox_m": [0.1, 0.1, 0.1],
            "materiais": 1,
            "ossos": 0,
            "partes_colisao": 0,
        },
    }
    manifesto = publish.montar_manifesto(
        item={"id": "a.b", "rota": "mesh", "seed": 7},
        spec_doc={"projeto": "demo", "perfil": "godot4", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4",
        provider={"nome": "mesh", "versao": "x", "determinism": "D2"},
        resultado=resultado,
        relatorio_qc=relatorio,
        licenca={"modelo": "TripoSR", "uso_comercial": True, "notice": "TripoSR (MIT)."},
        run_id="run-teste",
    )
    assert "texture" not in manifesto["providers"]
    assert "Concept:" not in manifesto["licenca"]["notice"]
