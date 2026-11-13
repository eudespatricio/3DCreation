"""Testes do Pacote 5 (`forge3d sync --para`): ponte pos-verify entre ext4 (I12) e pasta externa."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge3d import config, publish, sync
from forge3d.canonical import sha256_arquivo
from forge3d.cli.comandos import despachar
from forge3d.errors import ForgeError
from tests.test_seguranca_e_qc import _glb_bytes


def _publicar_valido(base: Path, asset_id: str = "prop.sync.01") -> Path:
    origem = base / "ext4_saida"
    staging = base / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    glb = _glb_bytes(no_nome=asset_id)
    (staging / f"{asset_id}.glb").write_bytes(glb)
    man = {
        "schema": "forge3d/manifest@3",
        "asset_id": asset_id,
        "projeto": "demo",
        "perfil": "godot4",
        "rota": "blocky",
        "tags": ["sync"],
        "spec_hash": "sha256:" + "a" * 64,
        "pipeline_version": "0.4.0",
        "determinism": "D1",
        "providers": {
            "geometry": {"name": "blocky", "version": "0.2.3", "license": "CC0-1.0"}
        },
        "geometry": {"triangulos": 12, "vertices": 8, "bbox_m": [1.0, 1.0, 1.0], "materiais": 1},
        "unidades_export": {"metros_por_unidade": 1.0, "escala_saida": 1.0},
        "animacoes": [],
        "rig": None,
        "lod": [{"nivel": 0, "triangulos": 12, "arquivo": f"{asset_id}.glb"}],
        "colisao": {"tipo": "none", "partes": 0},
        "files": [
            {
                "caminho": f"{asset_id}.glb",
                "papel": "mesh",
                "sha256": sha256_arquivo(staging / f"{asset_id}.glb"),
                "bytes": len(glb),
            }
        ],
        "qc": {
            "aprovado": True,
            "gates": [
                {"id": "G2", "status": "ok", "medido": {"esperado_m": 1.0, "pivo_regra": "base"}},
                {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 500}},
            ],
        },
        "licenca": {"modelo": "CC0-1.0", "uso_comercial": True, "notice": "fixture"},
        "origem_spec": {"arquivo": "lote.yaml", "hash": "sha256:" + "a" * 64},
        "run_id": "run-sync-1",
        "created_at": "2026-11-11T00:00:00Z",
    }
    publish.publicar(staging, origem, man, "run-sync-1")
    return origem


def test_sync_copia_apenas_arquivos_do_manifesto_e_limpa_orfaos(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))
    origem = _publicar_valido(tmp_path)
    # Arquivo extra fora dos manifestos na origem NAO deve ir para o destino
    (origem / "rascunho.tmp").write_text("lixo", encoding="utf-8")

    alvo = tmp_path / "destino_windows"
    (alvo / "antigo").mkdir(parents=True)
    (alvo / "antigo" / "velho.glb").write_bytes(b"obsoleto")
    (alvo / "sobra.txt").write_text("apagar", encoding="utf-8")

    rel = sync.executar(origem, alvo, limpar=True)
    assert rel["ok"] is True
    assert rel["ativos"] == 1
    assert set(rel["copiados"]) == {"prop.sync.01.glb", "prop.sync.01.manifest.json"}
    assert set(rel["removidos"]) == {"antigo/velho.glb", "sobra.txt"}
    assert (alvo / "prop.sync.01.glb").is_file()
    assert (alvo / "prop.sync.01.manifest.json").is_file()
    assert not (alvo / "rascunho.tmp").exists()
    assert not (alvo / "sobra.txt").exists()
    assert not (alvo / "antigo").exists()


def test_sync_recusa_origem_corrompida_com_exit_3(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))
    origem = _publicar_valido(tmp_path)
    (origem / "prop.sync.01.glb").write_bytes(b"corrompido")
    alvo = tmp_path / "destino_win"

    rc = despachar(["sync", str(origem), "--para", str(alvo), "--json"])
    assert rc == 3
    out = json.loads(capsys.readouterr().out)
    assert out["erro"]["codigo"] in ("FORGE-E-MANIFEST", "FORGE-E-QC")
    assert not alvo.exists()


def test_sync_valida_alvo_e_permite_mnt_sem_afetar_i12(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))
    origem = _publicar_valido(tmp_path)

    # Mesmo caminho ou subcaminho -> FORGE-E-DESTINO (exit 2)
    with pytest.raises(ForgeError) as exc:
        sync.executar(origem, origem)
    assert exc.value.codigo == "FORGE-E-DESTINO"

    with pytest.raises(ForgeError) as exc:
        sync.executar(origem, origem / "sub")
    assert exc.value.codigo == "FORGE-E-DESTINO"

    # Repo do Forge3D -> FORGE-E-DESTINO (exit 2)
    repo = Path(__file__).resolve().parents[1]
    with pytest.raises(ForgeError) as exc:
        sync.executar(origem, repo / "saida_teste")
    assert exc.value.codigo == "FORGE-E-DESTINO"

    # /mnt/<letra>/... e aceito explicitamente no alvo de sync (sem quebrar I12 em config)
    with pytest.raises(ForgeError) as exc_cfg:
        config.validar_caminho(Path("/mnt/c/Users/demo/assets"))
    assert exc_cfg.value.codigo == "FORGE-E-PATH"

    alvo_mnt = sync._validar_alvo("/mnt/c/Users/demo/assets", origem)
    assert str(alvo_mnt) == "/mnt/c/Users/demo/assets"

    # Origem continua recusando /mnt/ (I12)
    with pytest.raises(ForgeError) as exc_orig:
        sync.executar("/mnt/c/Users/demo/origem", tmp_path / "out")
    assert exc_orig.value.codigo == "FORGE-E-PATH"

    # UNC no destino continua recusado
    with pytest.raises(ForgeError) as exc_unc:
        sync.executar(origem, "\\\\wsl.localhost\\Ubuntu\\tmp\\out")
    assert exc_unc.value.codigo == "FORGE-E-PATH"


def test_sync_recusa_qc_reprovado_com_forge_e_qc(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))
    origem = _publicar_valido(tmp_path)
    man_path = origem / "prop.sync.01.manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    man["qc"]["gates"][0]["medido"]["esperado_m"] = 9.99
    man_path.write_text(json.dumps(man, indent=1), encoding="utf-8")

    alvo = tmp_path / "destino_qc_fail"
    rc = despachar(["sync", str(origem), "--para", str(alvo), "--json"])
    assert rc == 3
    out = json.loads(capsys.readouterr().out)
    assert out["erro"]["codigo"] == "FORGE-E-QC"
    assert not alvo.exists()


def test_sync_copia_texturas_pbr_e_gera_assets_lua(tmp_path, monkeypatch):
    """Sync pos-verify copia texturas PBR (_baseColor/_normal/_orm) e gera Assets.lua valido."""
    from PIL import Image

    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))

    asset_id = "prop.pbr.01"
    origem = tmp_path / "ext4_pbr"
    staging = tmp_path / "staging_pbr"
    staging.mkdir(parents=True, exist_ok=True)
    glb = _glb_bytes(no_nome=asset_id)
    (staging / f"{asset_id}.glb").write_bytes(glb)

    arquivos = [
        {
            "caminho": f"{asset_id}.glb",
            "papel": "mesh",
            "sha256": sha256_arquivo(staging / f"{asset_id}.glb"),
            "bytes": len(glb),
        }
    ]
    for sufixo, papel in (("baseColor", "textura"), ("normal", "normal"), ("orm", "orm")):
        nome = f"{asset_id}_{sufixo}.png"
        arq = staging / nome
        Image.new("RGB", (64, 64), (128, 128, 128)).save(arq)
        arquivos.append(
            {
                "caminho": nome,
                "papel": papel,
                "sha256": sha256_arquivo(arq),
                "bytes": arq.stat().st_size,
            }
        )

    man = {
        "schema": "forge3d/manifest@3",
        "asset_id": asset_id,
        "projeto": "demo",
        "perfil": "godot4",
        "rota": "mesh",
        "tags": ["pbr"],
        "spec_hash": "sha256:" + "a" * 64,
        "pipeline_version": "0.4.0",
        "determinism": "D2",
        "providers": {
            "geometry": {"name": "mesh", "version": "0.1.8", "license": "MIT", "seed": 42}
        },
        "geometry": {"triangulos": 12, "vertices": 8, "bbox_m": [1.0, 1.0, 1.0], "materiais": 1},
        "unidades_export": {"metros_por_unidade": 1.0, "escala_saida": 1.0},
        "animacoes": [],
        "rig": None,
        "lod": [{"nivel": 0, "triangulos": 12, "arquivo": f"{asset_id}.glb"}],
        "colisao": {"tipo": "none", "partes": 0},
        "files": arquivos,
        "qc": {
            "aprovado": True,
            "gates": [
                {"id": "G2", "status": "ok", "medido": {"esperado_m": 1.0, "pivo_regra": "base"}},
                {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 500}},
            ],
        },
        "licenca": {"modelo": "MIT", "uso_comercial": True, "notice": "fixture"},
        "origem_spec": {"arquivo": "lote.yaml", "hash": "sha256:" + "a" * 64},
        "run_id": "run-sync-pbr",
        "created_at": "2026-11-11T00:00:00Z",
    }
    publish.publicar(staging, origem, man, "run-sync-pbr")
    publish.registrar_ledger({"evento": "upload", "id": asset_id, "asset_id": "987654321"})

    alvo = tmp_path / "rojo_pbr"
    lua_path = alvo / "Assets.lua"
    rel = sync.executar(origem, alvo, limpar=True, rojo_lua=lua_path)
    assert rel["ok"] is True
    assert rel["rojo_assets"] == 1
    assert set(rel["copiados"]) == {
        f"{asset_id}.glb",
        f"{asset_id}_baseColor.png",
        f"{asset_id}_normal.png",
        f"{asset_id}_orm.png",
        f"{asset_id}.manifest.json",
    }
    for nome in rel["copiados"]:
        assert (alvo / nome).is_file()
    assert '["prop.pbr.01"] = "rbxassetid://987654321"' in lua_path.read_text(encoding="utf-8")


def test_sync_limpar_preserva_metadados_godot(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))
    origem = _publicar_valido(tmp_path)

    alvo = tmp_path / "godot_dst"
    (alvo / ".godot" / "imported").mkdir(parents=True)
    (alvo / ".godot" / "uid_cache.bin").write_bytes(b"cache")
    (alvo / ".godot" / "imported" / "prop.sync.01.scn").write_bytes(b"scn")
    (alvo / "prop.sync.01.glb.import").write_text("[remap]\n", encoding="utf-8")
    (alvo / "prop.sync.01.glb.uid").write_text("uid://abc123\n", encoding="utf-8")
    (alvo / "sub").mkdir()
    (alvo / "sub" / "tex.png.import").write_text("[remap]\n", encoding="utf-8")
    (alvo / "orfao.txt").write_text("remover", encoding="utf-8")
    (alvo / "antigo").mkdir()
    (alvo / "antigo" / "obsoleto.glb").write_bytes(b"velho")

    rel = sync.executar(origem, alvo, limpar=True)
    assert rel["ok"] is True
    assert set(rel["removidos"]) == {"antigo/obsoleto.glb", "orfao.txt"}
    assert (alvo / ".godot" / "uid_cache.bin").is_file()
    assert (alvo / ".godot" / "imported" / "prop.sync.01.scn").is_file()
    assert (alvo / "prop.sync.01.glb.import").is_file()
    assert (alvo / "prop.sync.01.glb.uid").is_file()
    assert (alvo / "sub" / "tex.png.import").is_file()
    assert not (alvo / "orfao.txt").exists()
    assert not (alvo / "antigo").exists()


def test_gerar_assets_gd_deterministico_e_sync_godot(tmp_path, monkeypatch):
    import shutil
    import subprocess

    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))
    origem = _publicar_valido(tmp_path, asset_id="prop.gd.01")

    gd_a = tmp_path / "out_gd" / "Forge3DAssets.gd"
    gd_b = tmp_path / "out_gd" / "Forge3DAssets_dup.gd"
    res_a = sync.gerar_assets_gd(origem, gd_a, res_prefix="res://assets/forge3d")
    res_b = sync.gerar_assets_gd([origem / "prop.gd.01.manifest.json"], gd_b, res_prefix="res://assets/forge3d")

    texto_a = gd_a.read_text(encoding="utf-8")
    assert texto_a == gd_b.read_text(encoding="utf-8")
    assert res_a["ok"] is True
    assert res_a["total"] == 1
    assert res_b["total"] == 1
    assert "class_name Forge3DAssets" in texto_a
    assert "extends RefCounted" in texto_a
    assert "const ASSETS: Dictionary = {" in texto_a
    assert '"mesh": "res://assets/forge3d/prop.gd.01.glb"' in texto_a
    assert "static func get_mesh_path(asset_id: String) -> String:" in texto_a

    with pytest.raises(ForgeError) as exc:
        sync.gerar_assets_gd(origem, tmp_path / "Ruim.gd", class_name="123-invalido")
    assert exc.value.codigo == "FORGE-E-SPEC"

    alvo_proj = tmp_path / "godot_proj"
    alvo_proj.mkdir()
    (alvo_proj / "project.godot").write_text('[application]\nconfig/name="test"\n', encoding="utf-8")
    rel = sync.executar(origem, alvo_proj, limpar=True)
    assert rel["ok"] is True
    assert rel["godot_assets"] == 1
    gd_auto = alvo_proj / "forge3d_assets.gd"
    assert rel["godot_gd"] == str(gd_auto.resolve())
    assert gd_auto.is_file()
    assert (alvo_proj / "project.godot").is_file()

    godot = shutil.which("godot")
    if not godot:
        cand = Path.home() / ".gemini" / "antigravity" / "bin" / "godot"
        if cand.is_file():
            godot = str(cand)
    if godot:
        proj_repo = Path(__file__).resolve().parents[1] / "tools" / "godot_project"
        chk = subprocess.run(
            [godot, "--headless", "--path", str(proj_repo), "--check-only", "--quit", "--script", str(gd_auto)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert chk.returncode == 0, chk.stdout + chk.stderr
