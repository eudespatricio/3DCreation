"""Testes do upload Open Cloud: dry-run e fluxo POST/operation contra servidor local."""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from forge3d import index, upload


class _Servidor(BaseHTTPRequestHandler):
    recebido: dict = {}

    def do_POST(self):  # noqa: N802
        tamanho = int(self.headers.get("Content-Length", "0"))
        corpo = self.rfile.read(tamanho)
        _Servidor.recebido = {
            "path": self.path,
            "key": self.headers.get("x-api-key"),
            "content_type": self.headers.get("Content-Type", ""),
            "body": corpo,
        }
        resposta = json.dumps({"path": "operations/op-1"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resposta)))
        self.end_headers()
        self.wfile.write(resposta)

    def do_GET(self):  # noqa: N802
        resposta = json.dumps(
            {
                "done": True,
                "response": {
                    "assetId": "999",
                    "moderationResult": {"moderationState": "MODERATION_STATE_APPROVED"},
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resposta)))
        self.end_headers()
        self.wfile.write(resposta)

    def log_message(self, *args):  # noqa: D401
        return


def _glb(tmp_path):
    p = tmp_path / "modelo.glb"
    p.write_bytes(b"glTF\x02\x00\x00\x00" + b"x" * 64)
    return p


def test_upload_dry_run_nao_exige_key(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE3D_ROBLOX_API_KEY", raising=False)
    monkeypatch.delenv("FORGE3D_ROBLOX_API_KEY_FILE", raising=False)
    p = _glb(tmp_path)
    rel = upload.executar(p, creator_id="123", dry_run=True, nome="Teste")
    assert rel["dry_run"] is True
    assert rel["bytes"] == p.stat().st_size
    assert rel["content_type"] == "model/gltf-binary"
    assert rel["request"]["assetType"] == "Model"
    assert rel["request"]["creationContext"]["creator"] == {"userId": "123"}
    assert rel["key_presente"] is False


def test_upload_model_contra_servidor_local(tmp_path, monkeypatch):
    p = _glb(tmp_path)
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), _Servidor)
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("FORGE3D_ROBLOX_API_KEY", "test-key-123")
        monkeypatch.setenv("FORGE3D_ROBLOX_CREATOR_ID", "123")
        monkeypatch.setenv("FORGE3D_ROBLOX_API_URL", f"http://127.0.0.1:{servidor.server_port}")
        rel = upload.executar(p, nome="Teste", intervalo=0.01, max_espera=5)
    finally:
        servidor.shutdown()
        servidor.server_close()
        thread.join(timeout=2)

    assert rel["asset_id"] == "999"
    assert rel["moderation"] == "MODERATION_STATE_APPROVED"
    assert rel["operation"] == "op-1"
    assert _Servidor.recebido["path"] == "/assets/v1/assets"
    assert _Servidor.recebido["key"] == "test-key-123"
    assert "multipart/form-data" in _Servidor.recebido["content_type"]
    corpo = _Servidor.recebido["body"]
    assert b'name="request"' in corpo
    assert b'"assetType":"Model"' in corpo
    assert b'name="fileContent"' in corpo
    assert b"model/gltf-binary" in corpo
    assert b"glTF" in corpo

def test_upload_animation_dry_run(tmp_path):
    """Open Cloud aceita Animation como .rbxmx (model/x-rbxm)."""
    p = tmp_path / "idle.rbxmx"
    p.write_text('<?xml version="1.0"?><roblox version="4"></roblox>', encoding="utf-8")
    rel = upload.executar(p, asset_type="Animation", creator_id="123", dry_run=True)
    assert rel["asset_type"] == "Animation"
    assert rel["content_type"] == "model/x-rbxm"
    assert rel["request"]["assetType"] == "Animation"
    assert "Animacao" in rel["request"]["description"]


def test_upload_image_dry_run(tmp_path):
    p = tmp_path / "atlas.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
    rel = upload.executar(p, asset_type="Image", creator_id="123", dry_run=True)
    assert rel["asset_type"] == "Image"
    assert rel["content_type"] == "image/png"
    assert rel["request"]["assetType"] == "Image"
    assert rel["bytes"] == p.stat().st_size


def test_upload_resolver_ledger_por_asset_id_e_role(tmp_path, monkeypatch):
    """upload.resolver_ledger resolve (asset_id, role) -> rbxassetid://<id> do ledger.jsonl."""
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))

    assert upload.formatar_rbxassetid("12345") == "rbxassetid://12345"
    assert upload.formatar_rbxassetid("rbxassetid://12345") == "rbxassetid://12345"
    assert upload.formatar_rbxassetid("") == ""
    assert upload.resolver_ledger() == {}

    index.registrar_ledger({"evento": "run", "projeto": "demo", "exit": 0})
    index.registrar_ledger(
        {"evento": "upload", "id": "sword.01", "role": "mesh", "asset_id": "100"}
    )
    index.registrar_ledger(
        {"evento": "upload", "id": "sword.01", "role": "mesh", "asset_id": "101"}
    )
    index.registrar_ledger(
        {
            "evento": "upload",
            "id": "sword.01",
            "arquivo": "sword.01_baseColor.png",
            "asset_type": "Image",
            "asset_id": "201",
        }
    )
    index.registrar_ledger(
        {"evento": "upload", "id": "sword.01_normal", "asset_id": "202", "asset_type": "Image"}
    )
    index.registrar_ledger(
        {"evento": "upload", "id": "shield.01", "papel": "orm", "asset_id": "301"}
    )

    mapa = upload.resolver_ledger()
    assert mapa[("sword.01", "mesh")] == "rbxassetid://101"
    assert mapa[("sword.01", "ColorMap")] == "rbxassetid://201"
    assert mapa[("sword.01", "NormalMap")] == "rbxassetid://202"
    assert mapa[("shield.01", "orm")] == "rbxassetid://301"

    filtrado = upload.resolver_ledger(asset_id="sword.01")
    assert all(k[0] == "sword.01" for k in filtrado)
    assert upload.asset_ids_do_ledger("sword.01") == {
        "mesh": "rbxassetid://101",
        "ColorMap": "rbxassetid://201",
        "NormalMap": "rbxassetid://202",
    }

    # Explicit ledger path with malformed line ignored
    custom = tmp_path / "custom_ledger.jsonl"
    custom.write_text(
        "{corrompido\n"
        + json.dumps({"evento": "upload", "id": "elmo.01", "canal": "ColorMap", "asset_id": "999"})
        + "\n",
        encoding="utf-8",
    )
    assert upload.resolver_ledger(custom) == {("elmo.01", "ColorMap"): "rbxassetid://999"}


def test_mcp_studio_descoberta_dinamica_por_mtime_e_env(tmp_path, monkeypatch):
    """tools/mcp_studio.py descobre StudioMCP.exe mais recente e preserva FORGE3D_STUDIOMCP."""
    tools_dir = str(Path(__file__).resolve().parents[1] / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import mcp_studio  # noqa: E402

    monkeypatch.delenv("FORGE3D_STUDIOMCP", raising=False)

    # Empty users root -> None / FileNotFoundError
    vazio = tmp_path / "Users"
    vazio.mkdir()
    assert mcp_studio.descobrir_binario(base_users=vazio) is None
    with pytest.raises(FileNotFoundError):
        mcp_studio.binario(base_users=vazio)

    # Two Studio versions across users: newer mtime must win
    antigo = vazio / "dev1" / "AppData/Local/Roblox/Versions/version-aaa111/StudioMCP.exe"
    novo = vazio / "dev2" / "AppData/Local/Roblox/Versions/version-bbb222/StudioMCP.exe"
    antigo.parent.mkdir(parents=True)
    novo.parent.mkdir(parents=True)
    antigo.write_bytes(b"old")
    novo.write_bytes(b"new")
    os.utime(antigo, (1_700_000_000, 1_700_000_000))
    os.utime(novo, (1_800_000_000, 1_800_000_000))

    assert mcp_studio.binario(base_users=vazio) == str(novo)

    # Env override wins over glob discovery
    monkeypatch.setenv("FORGE3D_STUDIOMCP", "/custom/StudioMCP.exe")
    assert mcp_studio.binario(base_users=vazio) == "/custom/StudioMCP.exe"


def test_http_retry_backoff_429_e_503(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    calls = {"n": 0}
    sleeps: list[float] = []

    class _Resp:
        def __init__(self, payload: dict):
            self._payload = json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self._payload

    def fake_urlopen(req, timeout=90):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(
                req.full_url, 429, "Too Many Requests", {"Retry-After": "0.2"}, io.BytesIO(b"rate")
            )
        if calls["n"] == 2:
            raise urllib.error.HTTPError(
                req.full_url, 503, "Unavailable", {}, io.BytesIO(b"busy")
            )
        return _Resp({"ok": True, "assetId": "777"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(upload.time, "sleep", lambda s: sleeps.append(s))

    res = upload._http("https://apis.roblox.com/assets/v1/assets", "k", b"{}", "application/json")
    assert res["assetId"] == "777"
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_upload_rejeita_moderacao_reprovada(tmp_path, monkeypatch):
    from forge3d.errors import ForgeError

    p = _glb(tmp_path)
    monkeypatch.setattr(
        upload,
        "_http",
        lambda url, key, dados=None, content_type=None, **kw: (  # noqa: ARG005
            {"path": "operations/op-rej"}
            if dados is not None
            else {
                "done": True,
                "response": {
                    "assetId": "555",
                    "moderationResult": {"moderationState": "MODERATION_STATE_REJECTED"},
                },
            }
        ),
    )
    with pytest.raises(ForgeError) as exc_info:
        upload.executar(
            p,
            creator_id="123",
            key="test-key-123",
            api_url="https://apis.roblox.com",
            intervalo=0.01,
            max_espera=5,
        )
    assert exc_info.value.codigo == "FORGE-E-UPLOAD"
    assert "moderacao" in str(exc_info.value).lower()


def _empacotar_glb(gltf: dict, bin_raw: bytes) -> bytes:
    import struct

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    pad_j = (4 - (len(json_bytes) % 4)) % 4
    json_padded = json_bytes + (b" " * pad_j)

    chunks = [struct.pack("<II", len(json_padded), 0x4E4F534A) + json_padded]
    if bin_raw:
        pad_b = (4 - (len(bin_raw) % 4)) % 4
        bin_padded = bin_raw + (b"\x00" * pad_b)
        chunks.append(struct.pack("<II", len(bin_padded), 0x004E4942) + bin_padded)
    corpo = b"".join(chunks)
    return struct.pack("<III", 0x46546C67, 2, 12 + len(corpo)) + corpo


def test_remover_imagens_glb_compacta_imagem_antes_de_malha_e_intercalado(tmp_path: Path):
    from forge3d import qc

    img_bytes = b"\x89PNG\r\n\x1a\n" + (b"\xEE" * 2040)
    pos_bytes = b"POS_DATA_123"
    uv_bytes = b"UV_DATA_"
    tan_bytes = b"TANGENT_DATA_XYZ"
    bin_raw = img_bytes + pos_bytes + uv_bytes + tan_bytes
    off_pos = len(img_bytes)
    off_uv = off_pos + len(pos_bytes)

    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(bin_raw)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(img_bytes)},
            {"buffer": 0, "byteOffset": off_pos, "byteLength": len(pos_bytes)},
            {"buffer": 0, "byteOffset": off_uv, "byteLength": len(uv_bytes)},
            {"buffer": 0, "byteOffset": off_pos, "byteLength": len(pos_bytes) + len(uv_bytes) + len(tan_bytes)},
        ],
        "images": [{"bufferView": 0, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "samplers": [{}],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
        "accessors": [
            {"bufferView": 1, "componentType": 5126, "count": 1, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": 1, "type": "VEC2"},
            {"bufferView": 3, "componentType": 5126, "count": 1, "type": "VEC4"},
        ],
        "meshes": [
            {"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1, "TANGENT": 2}}]}
        ],
    }

    glb_out, info = upload.remover_imagens_embutidas_glb(_empacotar_glb(gltf, bin_raw))
    assert info["imagens_removidas"] == 1
    assert info["bytes_depois"] <= info["bytes_antes"] - 2000

    out_path = tmp_path / "compacto.glb"
    out_path.write_bytes(glb_out)
    gltf_out, bin_out = qc.ler_glb_bin(out_path)

    assert "images" not in gltf_out
    assert "textures" not in gltf_out
    assert "samplers" not in gltf_out
    assert gltf_out["buffers"][0]["byteLength"] == len(bin_out)
    assert len(gltf_out["bufferViews"]) == 3
    assert gltf_out["meshes"][0]["primitives"][0]["attributes"] == {
        "POSITION": 0,
        "TEXCOORD_0": 1,
        "TANGENT": 2,
    }
    assert gltf_out["accessors"][0]["bufferView"] == 0
    assert gltf_out["accessors"][1]["bufferView"] == 1
    assert gltf_out["accessors"][2]["bufferView"] == 2

    bv0 = gltf_out["bufferViews"][0]
    bv1 = gltf_out["bufferViews"][1]
    bv2 = gltf_out["bufferViews"][2]
    assert bin_out[bv0["byteOffset"] : bv0["byteOffset"] + bv0["byteLength"]] == pos_bytes
    assert bin_out[bv1["byteOffset"] : bv1["byteOffset"] + bv1["byteLength"]] == uv_bytes
    assert (
        bin_out[bv2["byteOffset"] : bv2["byteOffset"] + bv2["byteLength"]]
        == pos_bytes + uv_bytes + tan_bytes
    )


def test_remover_imagens_glb_preserva_shared_uri_sparse_e_bin_vazio(tmp_path: Path):
    from forge3d import qc

    # 1. Shared bufferView + sparse accessor re-indexing
    img_only = b"\x89PNG" + (b"\xAA" * 1020)
    shared = b"SHARED_BYTES"
    sparse_idx = b"\x01\x00\x02\x00"
    sparse_val = b"SPARSE_VAL12"
    bin_raw = img_only + shared + sparse_idx + sparse_val
    off_shared = len(img_only)
    off_sidx = off_shared + len(shared)
    off_sval = off_sidx + len(sparse_idx)

    gltf_shared = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(bin_raw)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(img_only)},
            {"buffer": 0, "byteOffset": off_shared, "byteLength": len(shared)},
            {"buffer": 0, "byteOffset": off_sidx, "byteLength": len(sparse_idx)},
            {"buffer": 0, "byteOffset": off_sval, "byteLength": len(sparse_val)},
        ],
        "images": [
            {"bufferView": 0, "mimeType": "image/png"},
            {"bufferView": 1, "mimeType": "image/png"},
        ],
        "accessors": [
            {
                "bufferView": 1,
                "componentType": 5126,
                "count": 1,
                "type": "VEC3",
                "sparse": {
                    "count": 1,
                    "indices": {"bufferView": 2, "componentType": 5123},
                    "values": {"bufferView": 3},
                },
            }
        ],
    }
    glb_shared_out, _ = upload.remover_imagens_embutidas_glb(_empacotar_glb(gltf_shared, bin_raw))
    p_shared = tmp_path / "shared.glb"
    p_shared.write_bytes(glb_shared_out)
    g_s, b_s = qc.ler_glb_bin(p_shared)
    assert len(g_s["bufferViews"]) == 3
    assert g_s["accessors"][0]["bufferView"] == 0
    assert g_s["accessors"][0]["sparse"]["indices"]["bufferView"] == 1
    assert g_s["accessors"][0]["sparse"]["values"]["bufferView"] == 2
    assert b_s[g_s["bufferViews"][0]["byteOffset"] : g_s["bufferViews"][0]["byteOffset"] + len(shared)] == shared

    # 2. URI image preserves geometry BIN unchanged
    gltf_uri = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": 12}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 12}],
        "images": [{"uri": "externo.png"}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 1, "type": "VEC3"}],
    }
    glb_uri_out, info_uri = upload.remover_imagens_embutidas_glb(_empacotar_glb(gltf_uri, b"GEOM_12_BYTE"))
    assert info_uri["imagens_removidas"] == 1
    p_uri = tmp_path / "uri.glb"
    p_uri.write_bytes(glb_uri_out)
    g_u, b_u = qc.ler_glb_bin(p_uri)
    assert b_u == b"GEOM_12_BYTE"
    assert g_u["buffers"][0]["byteLength"] == 12

    # 3. Empty remaining BIN omits BIN chunk and sets byteLength=0
    gltf_empty = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(img_only)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(img_only)}],
        "images": [{"bufferView": 0, "mimeType": "image/png"}],
    }
    glb_empty_out, _ = upload.remover_imagens_embutidas_glb(_empacotar_glb(gltf_empty, img_only))
    p_empty = tmp_path / "empty.glb"
    p_empty.write_bytes(glb_empty_out)
    g_e, b_e = qc.ler_glb_bin(p_empty)
    assert b_e == b""
    assert g_e["buffers"][0]["byteLength"] == 0


def test_cli_upload_model_strip_embedded_textures_dry_run(tmp_path, monkeypatch, capsys):
    from forge3d.cli.comandos import despachar

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE3D_ROBLOX_API_KEY", raising=False)
    monkeypatch.delenv("FORGE3D_ROBLOX_API_KEY_FILE", raising=False)

    img_bytes = b"\x89PNG\r\n\x1a\n" + (b"\x99" * 4088)
    geom_bytes = b"VERTEX_BYTES"
    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(img_bytes) + len(geom_bytes)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(img_bytes)},
            {"buffer": 0, "byteOffset": len(img_bytes), "byteLength": len(geom_bytes)},
        ],
        "images": [{"bufferView": 0, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "accessors": [{"bufferView": 1, "componentType": 5126, "count": 1, "type": "VEC3"}],
    }
    glb_path = tmp_path / "modelo_tex.glb"
    glb_path.write_bytes(_empacotar_glb(gltf, img_bytes + geom_bytes))

    rc = despachar(
        [
            "upload-model",
            str(glb_path),
            "--creator-id",
            "123",
            "--strip-embedded-textures",
            "--dry-run",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["strip_embedded_textures"]["imagens_removidas"] == 1
    assert payload["bytes"] == payload["strip_embedded_textures"]["bytes_depois"]
    assert payload["bytes"] <= glb_path.stat().st_size - 4000


def test_remover_imagens_glb_preserva_alinhamento_4b_adjacente_e_sobreposto(tmp_path: Path):
    import struct

    from forge3d import qc

    img_bytes = b"\x89PNG" + (b"\xAA" * 98)  # len=102 (% 4 == 2)
    idx_bytes = struct.pack("<3H", 0, 1, 2)  # len=6, offset=102 (% 2 == 0, ends at 108)
    pos_bytes = struct.pack("<3f", 1.0, 2.0, 3.0)  # len=12, offset=108 (% 4 == 0)
    bin_adj = img_bytes + idx_bytes + pos_bytes

    gltf_adj = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(bin_adj)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(img_bytes)},
            {"buffer": 0, "byteOffset": len(img_bytes), "byteLength": len(idx_bytes)},
            {"buffer": 0, "byteOffset": len(img_bytes) + len(idx_bytes), "byteLength": len(pos_bytes)},
        ],
        "images": [{"bufferView": 0, "mimeType": "image/png"}],
        "accessors": [
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
            {"bufferView": 2, "componentType": 5126, "count": 1, "type": "VEC3"},
        ],
    }
    glb_adj, _ = upload.remover_imagens_embutidas_glb(_empacotar_glb(gltf_adj, bin_adj))
    p_adj = tmp_path / "adj.glb"
    p_adj.write_bytes(glb_adj)
    g_adj, b_adj = qc.ler_glb_bin(p_adj)
    bv_idx_adj = g_adj["bufferViews"][0]
    bv_pos_adj = g_adj["bufferViews"][1]
    assert bv_idx_adj["byteOffset"] % 2 == 0
    assert bv_pos_adj["byteOffset"] % 4 == 0
    assert b_adj[bv_idx_adj["byteOffset"] : bv_idx_adj["byteOffset"] + len(idx_bytes)] == idx_bytes
    assert b_adj[bv_pos_adj["byteOffset"] : bv_pos_adj["byteOffset"] + len(pos_bytes)] == pos_bytes

    # Caso sobreposto com inicio nao-alinhado (offset 102 + len 10 -> [102, 112), e offset 108 + len 12 -> [108, 120))
    # Bytes [108..112) sao compartilhados entre bv_u16[6:10] e bv_f32[0:4]
    shared_ov = b"\x01\x00\x02\x00\x03\x00" + struct.pack("<3f", 4.0, 5.0, 6.0)
    bin_ov = img_bytes + shared_ov
    gltf_ov = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(bin_ov)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(img_bytes)},
            {"buffer": 0, "byteOffset": 102, "byteLength": 10},
            {"buffer": 0, "byteOffset": 108, "byteLength": 12},
        ],
        "images": [{"bufferView": 0, "mimeType": "image/png"}],
        "accessors": [
            {"bufferView": 1, "componentType": 5123, "count": 5, "type": "SCALAR"},
            {"bufferView": 2, "componentType": 5126, "count": 1, "type": "VEC3"},
        ],
    }
    glb_ov, _ = upload.remover_imagens_embutidas_glb(_empacotar_glb(gltf_ov, bin_ov))
    p_ov = tmp_path / "ov.glb"
    p_ov.write_bytes(glb_ov)
    g_ov, b_ov = qc.ler_glb_bin(p_ov)
    bv_u16 = g_ov["bufferViews"][0]
    bv_f32 = g_ov["bufferViews"][1]
    assert bv_u16["byteOffset"] % 2 == 0
    assert bv_f32["byteOffset"] % 4 == 0
    assert b_ov[bv_u16["byteOffset"] : bv_u16["byteOffset"] + 10] == bin_ov[102:112]
    assert b_ov[bv_f32["byteOffset"] : bv_f32["byteOffset"] + 12] == bin_ov[108:120]


def test_remover_imagens_glb_rejeita_glb_truncado_ou_corrompido():
    import struct

    img = b"\x89PNG" + (b"\x11" * 256)
    pos = struct.pack("<3f", 1.0, 2.0, 3.0)
    gltf_img = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(img) + len(pos)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(img)},
            {"buffer": 0, "byteOffset": len(img), "byteLength": len(pos)},
        ],
        "images": [{"bufferView": 0, "mimeType": "image/png"}],
        "accessors": [{"bufferView": 1, "componentType": 5126, "count": 1, "type": "VEC3"}],
    }
    glb_img = _empacotar_glb(gltf_img, img + pos)
    with pytest.raises(ValueError):
        upload.remover_imagens_embutidas_glb(glb_img[: len(glb_img) - 40])

    gltf_no_img = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(pos)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos)}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 1, "type": "VEC3"}],
    }
    glb_no_img = _empacotar_glb(gltf_no_img, pos)
    with pytest.raises(ValueError):
        upload.remover_imagens_embutidas_glb(glb_no_img[:-4])
    with pytest.raises(ValueError):
        upload.remover_imagens_embutidas_glb(glb_no_img + b"\x00\x00\x00\x00")

    # Versao != 2
    bad_ver = bytearray(glb_no_img)
    struct.pack_into("<I", bad_ver, 4, 1)
    with pytest.raises(ValueError):
        upload.remover_imagens_embutidas_glb(bytes(bad_ver))

    # bufferView fora dos limites mesmo sem imagens removiveis
    gltf_oob = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": 4}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 64}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 1, "type": "VEC3"}],
    }
    with pytest.raises(ValueError):
        upload.remover_imagens_embutidas_glb(_empacotar_glb(gltf_oob, b"\x00\x01\x02\x03"))

    # chunk JSON que nao seja objeto JSON (ex: lista) deve falhar com ValueError
    json_lista = b"[]  "
    glb_lista = (
        struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(json_lista))
        + struct.pack("<II", len(json_lista), 0x4E4F534A)
        + json_lista
    )
    with pytest.raises(ValueError, match="objeto"):
        upload.remover_imagens_embutidas_glb(glb_lista)
