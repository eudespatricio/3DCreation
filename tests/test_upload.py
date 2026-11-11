"""Testes do upload Open Cloud: dry-run e fluxo POST/operation contra servidor local."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from forge3d import upload


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
