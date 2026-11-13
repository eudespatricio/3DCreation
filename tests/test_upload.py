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
