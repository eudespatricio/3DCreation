"""Regressao: meta["modelo"] do RawAsset do mesh tem que ser chave da allowlist (sem GPU).

Bug: o caminho TripoSR gravava ``meta["modelo"] = MODELO_HF`` ("stabilityai/TripoSR"), mas
``pipeline`` chama ``providers.licenca_de(meta["modelo"])``, que espera a chave ``"triposr"`` ->
toda execucao mesh saia com FORGE-E-LICENCA (exit 5).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from forge3d import providers
from forge3d.providers import LICENCAS
from forge3d.providers import mesh as mesh_mod

RAIZ = Path(__file__).resolve().parents[1]
MESH_PY = RAIZ / "src" / "forge3d" / "providers" / "mesh.py"


def _valores_modelo_em_meta() -> list[ast.expr]:
    """Todos os valores da chave "modelo" em dicts passados como meta= a RawAsset(...)."""
    arvore = ast.parse(MESH_PY.read_text(encoding="utf-8"))
    valores: list[ast.expr] = []
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Call) and getattr(no.func, "id", None) == "RawAsset"):
            continue
        for kw in no.keywords:
            if kw.arg == "meta" and isinstance(kw.value, ast.Dict):
                for k, v in zip(kw.value.keys, kw.value.values):
                    if isinstance(k, ast.Constant) and k.value == "modelo":
                        valores.append(v)
    return valores


def test_meta_modelo_nunca_e_repo_hf():
    valores = _valores_modelo_em_meta()
    assert valores, "nenhum RawAsset(meta={'modelo': ...}) encontrado em mesh.py"
    for v in valores:
        assert not (isinstance(v, ast.Name) and v.id == "MODELO_HF"), (
            "meta['modelo'] deve ser a chave da allowlist (modelo_escolhido()), "
            "nao o repo HF; use meta['modelo_hf'] para proveniencia"
        )


def test_meta_modelo_literais_estao_na_allowlist():
    for v in _valores_modelo_em_meta():
        if isinstance(v, ast.Constant):
            assert v.value in LICENCAS, f"meta['modelo']={v.value!r} fora da allowlist"


def test_chave_padrao_triposr_resolve_licenca(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FORGE3D_MODELO_MESH", raising=False)
    chave = mesh_mod.modelo_escolhido()
    assert chave == "triposr"
    licenca = providers.licenca_de(chave)
    assert licenca["uso_comercial"] is True


def test_repo_hf_nao_e_chave_de_licenca():
    from forge3d.errors import ForgeError

    with pytest.raises(ForgeError):
        providers.licenca_de(mesh_mod.MODELO_HF)
