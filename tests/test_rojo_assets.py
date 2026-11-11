"""Testes de geracao do modulo Luau Rojo (`Assets.lua`) e CLI `sync --rojo-lua`."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from forge3d import index, sync
from forge3d.cli.comandos import despachar
from forge3d.errors import ForgeError
from tests.test_sync import _publicar_valido


def test_gerar_assets_lua_deterministico_de_ledger_e_manifestos(tmp_path):
    man_dir = tmp_path / "manifestos"
    man_dir.mkdir()
    (man_dir / "weapon.sword.01.manifest.json").write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@3",
                "asset_id": "weapon.sword.01",
                "files": [],
                "qc": {"aprovado": True},
                "roblox": {"asset_id": "111222333"},
            }
        ),
        encoding="utf-8",
    )
    # Manifesto sem assetId do Roblox nao entra como rbxassetid invalido
    (man_dir / "prop.sem_upload.01.manifest.json").write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@3",
                "asset_id": "prop.sem_upload.01",
                "files": [],
                "qc": {"aprovado": True},
            }
        ),
        encoding="utf-8",
    )

    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps({"evento": "run", "projeto": "demo", "exit": 0}),
                json.dumps({"evento": "upload", "id": "z.capa.01", "asset_id": "999"}),
                json.dumps({"evento": "upload", "id": "a.escudo.01", "asset_id": "555"}),
                json.dumps({"evento": "upload", "id": "z.capa.01", "asset_id": "1000"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    lua_a = tmp_path / "Assets.lua"
    lua_b = tmp_path / "Assets_ordem_inv.lua"
    res_a = sync.gerar_assets_lua([man_dir, ledger], lua_a)
    # Ordem invertida de fontes gera tabela com chaves ordenadas deterministicamente
    # (exceto quando ledger sobrescreve mesmo id; aqui os ids entre man_dir e ledger sao disjuntos)
    sync.gerar_assets_lua([ledger, man_dir], lua_b)

    texto_a = lua_a.read_text(encoding="utf-8")
    texto_b = lua_b.read_text(encoding="utf-8")
    assert texto_a == texto_b
    assert res_a["total"] == 3
    assert res_a["assets"] == {
        "a.escudo.01": "rbxassetid://555",
        "weapon.sword.01": "rbxassetid://111222333",
        "z.capa.01": "rbxassetid://1000",
    }

    idx_a = texto_a.index('["a.escudo.01"] = "rbxassetid://555",')
    idx_w = texto_a.index('["weapon.sword.01"] = "rbxassetid://111222333",')
    idx_z = texto_a.index('["z.capa.01"] = "rbxassetid://1000",')
    assert idx_a < idx_w < idx_z
    assert "local Assets = {" in texto_a
    assert texto_a.strip().endswith("return Assets")

    # Se `lune` estiver disponivel no PATH, valida execucao real do modulo Luau
    lune = shutil.which("lune")
    if lune:
        probe = tmp_path / "probe.luau"
        probe.write_text(
            'local T = require("./Assets")\n'
            'assert(T["a.escudo.01"] == "rbxassetid://555")\n'
            'assert(T["weapon.sword.01"] == "rbxassetid://111222333")\n'
            'assert(T["z.capa.01"] == "rbxassetid://1000")\n',
            encoding="utf-8",
        )
        proc = subprocess.run(
            [lune, "run", "./probe.luau"],
            cwd=str(tmp_path),
            check=False,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr + proc.stdout


def test_gerar_assets_lua_vazio_e_namespace_customizado(tmp_path):
    lua = tmp_path / "Catalogo.lua"
    res = sync.gerar_assets_lua([], lua, namespace="Catalogo")
    assert res["total"] == 0
    texto = lua.read_text(encoding="utf-8")
    assert "local Catalogo = {}" in texto
    assert "return Catalogo" in texto

    with pytest.raises(ForgeError) as exc:
        sync.gerar_assets_lua([], tmp_path / "Ruim.lua", namespace="123-invalido")
    assert exc.value.codigo == "FORGE-E-SPEC"


def test_cli_sync_com_rojo_lua_e_limpar(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))

    origem = _publicar_valido(tmp_path, asset_id="prop.sync.01")
    index.registrar_ledger(
        {"evento": "upload", "id": "prop.sync.01", "asset_id": "134628989553440"}
    )

    alvo = tmp_path / "rojo_dst"
    (alvo / "velho.txt").parent.mkdir(parents=True, exist_ok=True)
    (alvo / "velho.txt").write_text("lixo", encoding="utf-8")
    assets_lua = alvo / "Assets.lua"

    rc = despachar(
        [
            "sync",
            str(origem),
            "--para",
            str(alvo),
            "--limpar",
            "--rojo-lua",
            str(assets_lua),
            "--json",
        ]
    )
    assert rc == 0
    rel = json.loads(capsys.readouterr().out)
    assert rel["ok"] is True
    assert rel["rojo_lua"] == str(assets_lua.resolve())
    assert rel["rojo_assets"] == 1
    assert assets_lua.is_file()
    conteudo = assets_lua.read_text(encoding="utf-8")
    assert '["prop.sync.01"] = "rbxassetid://134628989553440"' in conteudo
    assert not (alvo / "velho.txt").exists()
