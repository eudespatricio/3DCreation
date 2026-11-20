"""Testes de geracao do modulo Luau Rojo (`Assets.lua`) e CLI `sync --rojo-lua`."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from forge3d import index, paths, rbx, sync, upload
from forge3d.canonical import sha256_arquivo
from forge3d.cli.comandos import despachar
from forge3d.errors import ForgeError
from tests.test_sync import _publicar_valido


def _png_pot_32x32(cor: tuple[int, int, int, int] = (200, 100, 50, 255)) -> bytes:
    import struct
    import zlib

    def _chunk(tipo: bytes, dados: bytes) -> bytes:
        return (
            struct.pack(">I", len(dados))
            + tipo
            + dados
            + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)
        )

    linha = b"\x00" + (bytes(cor) * 32)
    idat = zlib.compress(linha * 32)
    ihdr = struct.pack(">IIBBBBB", 32, 32, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _rodar_uploads_com_mock(monkeypatch, ids_retorno: list[str], fn):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    ids_fila = iter(ids_retorno)

    class _MockOpenCloud(BaseHTTPRequestHandler):
        asset_atual = ids_retorno[0] if ids_retorno else "1"

        def do_POST(self):  # noqa: N802
            _MockOpenCloud.asset_atual = next(ids_fila)
            tamanho = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(tamanho)
            resp = json.dumps({"path": "operations/op-1"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        def do_GET(self):  # noqa: N802
            resp = json.dumps(
                {
                    "done": True,
                    "response": {
                        "assetId": _MockOpenCloud.asset_atual,
                        "moderationResult": {"moderationState": "MODERATION_STATE_APPROVED"},
                    },
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        def log_message(self, *args):  # noqa: D401
            return

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenCloud)
    thr = threading.Thread(target=srv.serve_forever, daemon=True)
    thr.start()
    try:
        monkeypatch.setenv("FORGE3D_ROBLOX_API_KEY", "test-key")
        monkeypatch.setenv("FORGE3D_ROBLOX_CREATOR_ID", "123")
        monkeypatch.setenv("FORGE3D_ROBLOX_API_URL", f"http://127.0.0.1:{srv.server_port}")
        return fn()
    finally:
        srv.shutdown()
        srv.server_close()
        thr.join(timeout=2)


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


def test_ledger_upload_alimenta_rojo_assets_e_surface_appearance(tmp_path):
    """Ledger com uploads por (asset_id, role) alimenta Assets.lua, SurfaceAppearance e Accessory."""
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps({"evento": "upload", "id": "armadura.ombreira.01", "role": "mesh", "asset_id": "5001"}),
                json.dumps({"evento": "upload", "id": "armadura.ombreira.01", "role": "ColorMap", "asset_id": "5002"}),
                json.dumps({"evento": "upload", "id": "armadura.ombreira.01", "role": "NormalMap", "asset_id": "5003"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    pares = upload.resolver_ledger(ledger)
    assert pares[("armadura.ombreira.01", "mesh")] == "rbxassetid://5001"
    assert pares[("armadura.ombreira.01", "ColorMap")] == "rbxassetid://5002"

    sa_rel = rbx.exportar_surface_appearance(
        {"ColorMap": "omb_baseColor.png", "NormalMap": "omb_normal.png"},
        item_id="armadura.ombreira.01",
        ledger=ledger,
    )
    assert sa_rel["mapas"] == {
        "ColorMap": "rbxassetid://5002",
        "NormalMap": "rbxassetid://5003",
    }

    lua = tmp_path / "Assets.lua"
    res_lua = sync.gerar_assets_lua(ledger, lua)
    assert res_lua["assets"]["armadura.ombreira.01"] == {
        "ColorMap": "rbxassetid://5002",
        "NormalMap": "rbxassetid://5003",
        "mesh": "rbxassetid://5001",
    }
    lua_txt = lua.read_text(encoding="utf-8")
    assert '["ColorMap"] = "rbxassetid://5002"' in lua_txt
    assert '["mesh"] = "rbxassetid://5001"' in lua_txt


def test_sync_rojo_lua_isola_colisao_mesmo_id_e_multi_role_entre_projetos(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))

    # Origem A (projeto proj_a) com asset_id compartilhado "sword.01" e item multi-role "armor.a.01"
    origem_a = _publicar_valido(tmp_path / "a", asset_id="sword.01")
    man_a = json.loads((origem_a / "sword.01.manifest.json").read_text(encoding="utf-8"))
    man_a["projeto"] = "proj_a"
    (origem_a / "sword.01.manifest.json").write_text(json.dumps(man_a), encoding="utf-8")
    # Atualiza hash do manifesto? publish.verificar re-lê files, nao manifesto sha, entao ok!

    # Ledger global com entradas conflitantes de outro projeto e outro destino de publicacao
    index.registrar_ledger(
        {"evento": "upload", "id": "sword.01", "projeto": "proj_a", "role": "mesh", "asset_id": "111"}
    )
    index.registrar_ledger(
        {"evento": "upload", "id": "sword.01", "projeto": "proj_b", "role": "mesh", "asset_id": "999"}
    )
    index.registrar_ledger(
        {
            "evento": "upload",
            "id": "sword.01",
            "role": "mesh",
            "asset_id": "888",
            "arquivo": str(tmp_path / "b" / "ext4_saida" / "sword.01.glb"),
        }
    )
    index.registrar_ledger(
        {
            "evento": "upload",
            "id": "other.armor.01",
            "projeto": "proj_b",
            "role": "mesh",
            "asset_id": "701",
        }
    )
    index.registrar_ledger(
        {
            "evento": "upload",
            "id": "other.armor.01",
            "projeto": "proj_b",
            "role": "ColorMap",
            "asset_id": "702",
        }
    )

    lua_a = tmp_path / "rojo_a" / "Assets.lua"
    res = sync.executar(origem_a, tmp_path / "sync_a", rojo_lua=lua_a)
    assert res["ok"] is True
    assert res["rojo_assets"] == 1
    conteudo = lua_a.read_text(encoding="utf-8")
    assert '["sword.01"] = "rbxassetid://111"' in conteudo
    assert "999" not in conteudo
    assert "888" not in conteudo
    assert "other.armor.01" not in conteudo


def test_sync_rojo_lua_origem_vazia_nao_vaza_ledger_global(tmp_path):
    origem_vazia = tmp_path / "pub_vazio"
    origem_vazia.mkdir()
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps({"evento": "upload", "id": "vazado.01", "role": "mesh", "asset_id": "123456"}) + "\n",
        encoding="utf-8",
    )
    lua_out = tmp_path / "Assets.lua"
    res = sync.gerar_assets_lua([origem_vazia, ledger], lua_out, origem_escopo=origem_vazia)
    assert res["total"] == 0
    assert res["assets"] == {}
    assert "vazado.01" not in lua_out.read_text(encoding="utf-8")


def test_cli_upload_model_json_registra_ledger_e_isola_path_relativo(tmp_path, monkeypatch, capsys):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from forge3d import paths

    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))

    pub_a = _publicar_valido(tmp_path / "a", asset_id="sword.01")
    pub_b = _publicar_valido(tmp_path / "b", asset_id="sword.01")
    for pasta, proj in ((pub_a, "proj_a"), (pub_b, "proj_b")):
        man_p = pasta / "sword.01.manifest.json"
        man = json.loads(man_p.read_text(encoding="utf-8"))
        man["projeto"] = proj
        man_p.write_text(json.dumps(man), encoding="utf-8")

    ids_fila = iter(["111111", "999999"])

    class _MockOpenCloud(BaseHTTPRequestHandler):
        asset_atual = "111111"

        def do_POST(self):  # noqa: N802
            _MockOpenCloud.asset_atual = next(ids_fila)
            tamanho = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(tamanho)
            resp = json.dumps({"path": "operations/op-1"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        def do_GET(self):  # noqa: N802
            resp = json.dumps(
                {
                    "done": True,
                    "response": {
                        "assetId": _MockOpenCloud.asset_atual,
                        "moderationResult": {"moderationState": "MODERATION_STATE_APPROVED"},
                    },
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        def log_message(self, *args):  # noqa: D401
            return

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockOpenCloud)
    thr = threading.Thread(target=srv.serve_forever, daemon=True)
    thr.start()
    try:
        monkeypatch.setenv("FORGE3D_ROBLOX_API_KEY", "test-key")
        monkeypatch.setenv("FORGE3D_ROBLOX_CREATOR_ID", "123")
        monkeypatch.setenv("FORGE3D_ROBLOX_API_URL", f"http://127.0.0.1:{srv.server_port}")

        rc_a = despachar(
            ["upload-model", str(pub_a / "sword.01.glb"), "--intervalo", "0.01", "--json"]
        )
        assert rc_a == 0
        out_a = json.loads(capsys.readouterr().out)
        assert out_a["asset_id"] == "111111"

        monkeypatch.chdir(pub_b)
        rc_b = despachar(["upload-model", "sword.01.glb", "--intervalo", "0.01", "--json"])
        assert rc_b == 0
        out_b = json.loads(capsys.readouterr().out)
        assert out_b["asset_id"] == "999999"
    finally:
        srv.shutdown()
        srv.server_close()
        thr.join(timeout=2)

    ledger_p = paths.arquivo_ledger()
    assert ledger_p.is_file()
    linhas = [json.loads(line) for line in ledger_p.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(linhas) == 2
    assert linhas[0]["arquivo"] == str((pub_a / "sword.01.glb").resolve())
    assert linhas[0]["projeto"] == "proj_a"
    assert linhas[0]["origem"] == str(pub_a.resolve())
    assert linhas[1]["arquivo"] == str((pub_b / "sword.01.glb").resolve())
    assert linhas[1]["projeto"] == "proj_b"
    assert linhas[1]["origem"] == str(pub_b.resolve())

    lua_a = tmp_path / "sync_a" / "Assets.lua"
    rc_sync = despachar(
        [
            "sync",
            str(pub_a),
            "--para",
            str(tmp_path / "sync_a"),
            "--rojo-lua",
            str(lua_a),
            "--json",
        ]
    )
    assert rc_sync == 0
    capsys.readouterr()
    lua_txt = lua_a.read_text(encoding="utf-8")
    assert '["sword.01"] = "rbxassetid://111111"' in lua_txt
    assert "999999" not in lua_txt


def test_sync_rojo_rejeita_projetos_vazio_arquivo_relativo_dir_externo_e_por_id_obsoleto(tmp_path):
    # E1 + E2: origem sem "projeto" deve rejeitar registro com projeto="proj_b" e arquivo relativo
    orig_a = tmp_path / "orig_a"
    orig_a.mkdir()
    (orig_a / "sword.01.manifest.json").write_text(
        json.dumps({"schema": "forge3d/manifest@3", "asset_id": "sword.01", "files": [], "qc": {"aprovado": True}}),
        encoding="utf-8",
    )
    ledger_e12 = tmp_path / "ledger_e12.jsonl"
    ledger_e12.write_text(
        "\n".join(
            [
                json.dumps({"evento": "upload", "id": "sword.01", "asset_id": "111111", "origem": str(orig_a)}),
                json.dumps({"evento": "upload", "id": "sword.01", "projeto": "proj_b", "asset_id": "999999"}),
                json.dumps({"evento": "upload", "id": "sword.01", "arquivo": "sword.01.glb", "asset_id": "888888"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    res_e12 = sync.gerar_assets_lua([orig_a, ledger_e12], tmp_path / "e12.lua", origem_escopo=orig_a)
    assert res_e12["assets"] == {"sword.01": "rbxassetid://111111"}

    # E5: fonte diretorio diferente de origem_escopo nao pode vazar manifestos
    orig_b = tmp_path / "orig_b"
    orig_b.mkdir()
    (orig_b / "dragon.99.manifest.json").write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@3",
                "asset_id": "dragon.99",
                "files": [],
                "qc": {"aprovado": True},
                "roblox": {"asset_id": "777777"},
            }
        ),
        encoding="utf-8",
    )
    res_e5 = sync.gerar_assets_lua([orig_b], tmp_path / "e5.lua", origem_escopo=orig_a)
    assert res_e5["total"] == 0
    assert res_e5["assets"] == {}

    # E4: upload single-ID mais novo sem role sobrescreve por_id multi-role antigo
    ledger_e4 = tmp_path / "ledger_e4.jsonl"
    ledger_e4.write_text(
        "\n".join(
            [
                json.dumps({"evento": "upload", "id": "sword.01", "role": "mesh", "asset_id": "111"}),
                json.dumps({"evento": "upload", "id": "sword.01", "role": "ColorMap", "asset_id": "112"}),
                json.dumps({"evento": "upload", "id": "sword.01", "asset_id": "222"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    res_e4 = sync.gerar_assets_lua([orig_a, ledger_e4], tmp_path / "e4.lua", origem_escopo=orig_a)
    assert res_e4["assets"] == {"sword.01": "rbxassetid://222"}


def test_cli_upload_tolera_manifestos_vizinhos_malformados_e_registra_ledger(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))

    pub = _publicar_valido(tmp_path / "pub", asset_id="sword.01")
    tex = pub / "sword.01_baseColor.png"
    tex.write_bytes(_png_pot_32x32())
    man_p = pub / "sword.01.manifest.json"
    man = json.loads(man_p.read_text(encoding="utf-8"))
    man["projeto"] = "proj_ok"
    man["files"].append(
        {
            "caminho": "sword.01_baseColor.png",
            "papel": "textura",
            "sha256": sha256_arquivo(tex),
            "bytes": tex.stat().st_size,
        }
    )
    man_p.write_text(json.dumps(man), encoding="utf-8")

    # Manifestos vizinhos corrompidos ou com campo "files" nao-lista nao devem abortar o registro
    (pub / "00_corrupt.manifest.json").write_text("{not valid json", encoding="utf-8")
    (pub / "01_list.manifest.json").write_text("[]", encoding="utf-8")
    (pub / "02_files_int.manifest.json").write_text(
        json.dumps({"asset_id": "other", "files": 123}), encoding="utf-8"
    )
    (pub / "03_files_bool.manifest.json").write_text(
        json.dumps({"asset_id": "sword.01_baseColor", "files": True}), encoding="utf-8"
    )
    (pub / "04_files_str.manifest.json").write_text(
        json.dumps({"asset_id": "other2", "files": "bad", "projeto": "proj_bad"}),
        encoding="utf-8",
    )

    def _exec():
        rc_img = despachar(
            ["upload-image", str(tex), "--intervalo", "0.01", "--json"]
        )
        assert rc_img == 0
        out_img = json.loads(capsys.readouterr().out)
        rc_mod = despachar(
            ["upload-model", str(pub / "sword.01.glb"), "--intervalo", "0.01", "--json"]
        )
        assert rc_mod == 0
        out_mod = json.loads(capsys.readouterr().out)
        return out_img, out_mod

    out_img, out_mod = _rodar_uploads_com_mock(monkeypatch, ["333444", "333555"], _exec)
    assert out_img["asset_id"] == "333444"
    assert out_mod["asset_id"] == "333555"

    ledger_p = paths.arquivo_ledger()
    assert ledger_p.is_file()
    linhas = [json.loads(ln) for ln in ledger_p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(linhas) == 2
    assert linhas[0]["asset_id"] == "333444"
    assert linhas[0]["origem"] == str(pub.resolve())
    assert linhas[0]["projeto"] == "proj_ok"
    assert linhas[1]["asset_id"] == "333555"
    assert linhas[1]["origem"] == str(pub.resolve())
    assert linhas[1]["projeto"] == "proj_ok"


def test_upload_image_desambigua_basename_e_subdiretorio_para_sync_rojo_lua(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))

    pub = _publicar_valido(tmp_path / "pub", asset_id="sword.01")
    tex_root = pub / "sword.01_baseColor.png"
    tex_root.write_bytes(_png_pot_32x32((210, 120, 60, 255)))
    tex_sub = pub / "textures" / "sword.01_normal.png"
    tex_sub.parent.mkdir(parents=True, exist_ok=True)
    tex_sub.write_bytes(_png_pot_32x32((128, 128, 255, 255)))

    man_p = pub / "sword.01.manifest.json"
    man = json.loads(man_p.read_text(encoding="utf-8"))
    man["projeto"] = "proj_right"
    man["files"].extend(
        [
            {
                "caminho": "sword.01_baseColor.png",
                "papel": "textura",
                "sha256": sha256_arquivo(tex_root),
                "bytes": tex_root.stat().st_size,
            },
            {
                "caminho": "textures/sword.01_normal.png",
                "papel": "normal",
                "sha256": sha256_arquivo(tex_sub),
                "bytes": tex_sub.stat().st_size,
            },
        ]
    )
    man_p.write_text(json.dumps(man), encoding="utf-8")

    # Manifesto concorrente em ordem alfabetica anterior referenciando mesmo basename em subpasta
    aaa_man = pub / "aaa.manifest.json"
    aaa_man.write_text(
        json.dumps(
            {
                "asset_id": "aaa",
                "projeto": "proj_wrong",
                "files": [{"caminho": "nested/sword.01_baseColor.png"}],
            }
        ),
        encoding="utf-8",
    )

    def _exec():
        assert (
            despachar(
                ["upload-model", str(pub / "sword.01.glb"), "--intervalo", "0.01", "--json"]
            )
            == 0
        )
        capsys.readouterr()
        assert despachar(["upload-image", str(tex_root), "--intervalo", "0.01", "--json"]) == 0
        capsys.readouterr()
        assert despachar(["upload-image", str(tex_sub), "--intervalo", "0.01", "--json"]) == 0
        capsys.readouterr()

    _rodar_uploads_com_mock(monkeypatch, ["555001", "555002", "555003"], _exec)

    linhas = [
        json.loads(ln)
        for ln in paths.arquivo_ledger().read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(linhas) == 3
    for reg in linhas:
        assert reg["origem"] == str(pub.resolve())
        assert reg["projeto"] == "proj_right"

    aaa_man.unlink()
    lua_out = tmp_path / "sync_dst" / "Assets.lua"
    rc_sync = despachar(
        [
            "sync",
            str(pub),
            "--para",
            str(tmp_path / "sync_dst"),
            "--rojo-lua",
            str(lua_out),
            "--json",
        ]
    )
    assert rc_sync == 0
    capsys.readouterr()
    lua_txt = lua_out.read_text(encoding="utf-8")
    assert '["ColorMap"] = "rbxassetid://555002"' in lua_txt
    assert '["NormalMap"] = "rbxassetid://555003"' in lua_txt
    assert '["mesh"] = "rbxassetid://555001"' in lua_txt
