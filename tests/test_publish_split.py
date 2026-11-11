"""Testes da divisao de publish.py em cache.py, index.py e verify.py + reexportacoes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from forge3d import cache, index, publish, verify
from forge3d.canonical import sha256_arquivo

RAIZ = Path(__file__).resolve().parents[1]
BASE = json.loads((RAIZ / "examples/manifest.exemplo.v3.json").read_text(encoding="utf-8"))


def test_publish_reexporta_todos_os_simbolos_dos_submodulos():
    assert publish._dir_cache is cache._dir_cache
    assert publish.salvar_cache is cache.salvar_cache
    assert publish.ler_cache is cache.ler_cache

    assert publish._conexao is index._conexao
    assert publish._indice_upsert is index._indice_upsert
    assert publish.consultar is index.consultar
    assert publish.registrar_ledger is index.registrar_ledger

    assert publish.VERIFY_ASPECTOS is verify.VERIFY_ASPECTOS
    assert publish.CAMPOS_PROVENIENCIA is verify.CAMPOS_PROVENIENCIA
    assert publish.MANIFEST_SCHEMA_CACHE is verify.MANIFEST_SCHEMA_CACHE
    assert publish._VERSAO_POR_SCHEMA is verify._VERSAO_POR_SCHEMA
    assert publish._schema_manifesto is verify._schema_manifesto
    assert publish._pedidos_verificar is verify._pedidos_verificar
    assert publish._faltando_proveniencia is verify._faltando_proveniencia
    assert publish.verificar is verify.verificar


def test_imports_diretos_sem_ciclo_em_qualquer_ordem():
    codigo = (
        "from forge3d import cache, index, verify; "
        "from forge3d import publish; "
        "assert publish.ler_cache is cache.ler_cache; "
        "assert publish.consultar is index.consultar; "
        "assert publish.verificar is verify.verificar"
    )
    proc = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.returncode == 0


def test_submodulos_funcionam_diretamente(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))

    origem = tmp_path / "orig"
    origem.mkdir()
    arq = origem / "item.glb"
    arq.write_bytes(b"glb-data")
    entrada = {
        "resultado": {
            "arquivos": [
                {"caminho": "item.glb", "papel": "mesh", "sha256": sha256_arquivo(arq)}
            ]
        }
    }
    cache.salvar_cache("k1", origem, entrada)
    lido = cache.ler_cache("k1")
    assert lido is not None and lido[1]["resultado"]["arquivos"][0]["caminho"] == "item.glb"

    man = json.loads(json.dumps(BASE))
    man["asset_id"] = "prop.split.01"
    man["projeto"] = "split"
    index._indice_upsert(man, tmp_path / "destino")
    assert [a["asset_id"] for a in index.consultar(projeto="split")] == ["prop.split.01"]

    index.registrar_ledger({"evento": "teste_split", "ok": True})
    ledger = tmp_path / "state" / "ledger.jsonl"
    assert ledger.is_file()
    assert "teste_split" in ledger.read_text(encoding="utf-8")

    destino = tmp_path / "destino"
    destino.mkdir()
    (destino / "prop.split.01.manifest.json").write_text(
        json.dumps(man), encoding="utf-8"
    )
    rel = verify.verificar(destino, only="manifesto")
    assert rel["ok"] is True and rel["total"] == 1
