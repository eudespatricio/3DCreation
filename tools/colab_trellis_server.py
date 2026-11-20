#!/usr/bin/env python3
"""Servidor HTTP stdlib para TRELLIS.2-4B / Pixal3D (MIT) no Google Colab."""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import io
import json
import os
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import colab_trellis_worker as _worker  # noqa: E402

LIMITE_BODY_BYTES = 64 * 1024 * 1024
ORDEM_VISTAS = ("front", "back", "left", "right")


class _EstadoTrellisServer:
    def __init__(
        self,
        modelo: str,
        token: str = "",
        pipeline: Any = None,
        pipeline_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.modelo_padrao = _worker.validar_modelo_trellis(modelo)
        self.token = (token or "").strip()
        self._factory = pipeline_factory or _worker.carregar_pipeline_trellis
        self._pipelines: dict[str, Any] = {}
        if pipeline is not None:
            self._pipelines[self.modelo_padrao] = pipeline
        self.gpu_lock = threading.Lock()

    def obter_pipeline(self, modelo_id: str) -> Any:
        if modelo_id not in self._pipelines:
            self._pipelines[modelo_id] = self._factory(modelo_id)
        return self._pipelines[modelo_id]


def _decodificar_imagens(imagens_raw: Any) -> list[Any]:
    from PIL import Image

    if not isinstance(imagens_raw, dict) or not imagens_raw:
        raise ValueError("campo 'images' deve ser objeto JSON nao vazio")
    chaves = [k for k in ORDEM_VISTAS if k in imagens_raw]
    if not chaves:
        chaves = sorted(str(k) for k in imagens_raw)
    saida: list[Any] = []
    for k in chaves:
        b64 = imagens_raw.get(k)
        if not isinstance(b64, str) or not b64.strip():
            raise ValueError(f"imagem '{k}' vazia ou invalida")
        raw = base64.b64decode(b64)
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            saida.append(im.convert("RGBA"))
    return saida


def _extrair_glb_e_faces(glb_obj: Any) -> tuple[bytes, int | None]:
    faces: int | None = None
    raw_faces = getattr(glb_obj, "faces", None)
    if raw_faces is not None and hasattr(raw_faces, "__len__"):
        faces = len(raw_faces)
    if isinstance(glb_obj, (bytes, bytearray)):
        return bytes(glb_obj), faces
    with tempfile.TemporaryDirectory(prefix="trellis_glb_") as tmp_dir:
        out_glb = Path(tmp_dir) / "modelo.glb"
        glb_obj.export(str(out_glb))
        return out_glb.read_bytes(), faces


def _validar_decimation_target(valor: Any) -> int | None:
    """Valida e limita ``decimation_target`` ao intervalo seguro ``[8000, 300000]``."""
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValueError(f"decimation_target deve ser inteiro positivo: {valor!r}")
    if valor <= 0:
        raise ValueError(f"decimation_target deve ser positivo (> 0): {valor}")
    return max(8_000, min(300_000, valor))


def _validar_texture_size(valor: Any) -> int:
    """Valida e limita ``texture_size`` a ``[256, 4096]`` evitando OOM por requisicao."""
    if valor is None:
        return 1024
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValueError(f"texture_size deve ser inteiro positivo: {valor!r}")
    if valor <= 0:
        raise ValueError(f"texture_size deve ser positivo (> 0): {valor}")
    return max(256, min(4096, valor))


def _validar_simplify(valor: Any) -> float:
    """Valida ``simplify`` finito em ``(0.0, 1.0]``."""
    if valor is None:
        return 0.95
    if isinstance(valor, bool):
        raise ValueError(f"simplify invalido: {valor!r}")
    num = float(valor)
    if not (0.0 < num <= 1.0):
        raise ValueError(f"simplify fora do intervalo (0.0, 1.0]: {valor!r}")
    return num


class TrellisHTTPHandler(BaseHTTPRequestHandler):
    server_version = "Forge3DTrellis/0.9.8"

    @property
    def _estado(self) -> _EstadoTrellisServer:
        return self.server.estado_trellis  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"[colab_trellis_server] {fmt % args}\n")

    def _responder_json(self, status: int, corpo: dict[str, Any]) -> None:
        dados = (json.dumps(corpo) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _autenticado(self) -> bool:
        esperado = self._estado.token
        if not esperado:
            return True
        cab = str(self.headers.get("Authorization") or "").strip()
        if not cab.lower().startswith("bearer "):
            return False
        recebido = cab[7:].strip()
        return hmac.compare_digest(recebido.encode("utf-8"), esperado.encode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        rota = self.path.split("?", 1)[0].rstrip("/") or "/"
        if rota == "/health":
            self._responder_json(200, {"ok": True, "modelo": self._estado.modelo_padrao, "pronto": True})
            return
        self._responder_json(404, {"ok": False, "erro": f"rota inexistente: {rota}"})

    def do_POST(self) -> None:  # noqa: N802
        rota = self.path.split("?", 1)[0].rstrip("/") or "/"
        if rota != "/generate":
            self._responder_json(404, {"ok": False, "erro": f"rota inexistente: {rota}"})
            return
        if not self._autenticado():
            self._responder_json(401, {"ok": False, "erro": "token Bearer ausente ou invalido"})
            return

        try:
            comp = int(self.headers.get("Content-Length") or "0")
            if comp <= 0 or comp > LIMITE_BODY_BYTES:
                raise ValueError(f"Content-Length invalido: {comp}")
            corpo = json.loads(self.rfile.read(comp).decode("utf-8"))
            if not isinstance(corpo, dict):
                raise ValueError("corpo JSON deve ser objeto")
            modelo_id = _worker.validar_modelo_trellis(str(corpo.get("model") or self._estado.modelo_padrao))
            seed = _worker._validar_seed(corpo.get("seed", 1))
            simplify = _validar_simplify(corpo.get("simplify", 0.95))
            texture_size = _validar_texture_size(corpo.get("texture_size", 1024))
            decimation_target = _validar_decimation_target(corpo.get("decimation_target"))
            imagens = _decodificar_imagens(corpo.get("images"))
        except ImportError as exc:
            sys.stderr.write(f"[colab_trellis_server] dependencia ausente: {exc}\n")
            self._responder_json(500, {"ok": False, "erro": f"dependencia ausente: {exc}"})
            return
        except (ValueError, TypeError, KeyError, binascii.Error, OSError) as exc:
            codigo = 403 if "allowlist" in str(exc) else 400
            sys.stderr.write(f"[colab_trellis_server] requisicao rejeitada ({codigo}): {exc}\n")
            self._responder_json(codigo, {"ok": False, "erro": str(exc)})
            return

        t0 = time.monotonic()
        try:
            with self._estado.gpu_lock:
                pipe = self._estado.obter_pipeline(modelo_id)
                outputs = _worker.executar_pipeline_trellis(
                    pipe, imagens, seed=seed, preferir_single_sem_multi=True
                )
                glb_obj = _worker._exportar_saida_pipeline(
                    outputs,
                    modelo_id,
                    simplify=simplify,
                    texture_size=texture_size,
                    decimation_target=decimation_target,
                )
                glb_bytes, faces = _extrair_glb_e_faces(glb_obj)
        except (RuntimeError, OSError, ValueError) as exc:
            sys.stderr.write(f"[colab_trellis_server] falha na inferencia: {exc}\n")
            self._responder_json(500, {"ok": False, "erro": str(exc)})
            return

        self._responder_json(200, {"ok": True, "modelo": modelo_id, "faces": faces, "tempo_s": round(time.monotonic() - t0, 3), "glb_base64": base64.b64encode(glb_bytes).decode("ascii")})


def criar_servidor(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    modelo: str = _worker.MODELO_TRELLIS_PADRAO,
    token: str = "",
    pipeline: Any = None,
    pipeline_factory: Callable[[str], Any] | None = None,
) -> ThreadingHTTPServer:
    estado = _EstadoTrellisServer(
        modelo=modelo, token=token, pipeline=pipeline, pipeline_factory=pipeline_factory
    )
    srv = ThreadingHTTPServer((host, int(port)), TrellisHTTPHandler)
    srv.estado_trellis = estado  # type: ignore[attr-defined]
    return srv


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Servidor HTTP Colab TRELLIS.2-4B / Pixal3D (MIT)")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--model", default=_worker.MODELO_TRELLIS_PADRAO)
    p.add_argument("--token", default=os.environ.get("FORGE3D_I23D_TOKEN", ""))
    p.add_argument("--eager", action="store_true", help="Carrega pesos na inicializacao")
    args = p.parse_args(argv)
    try:
        pipe = _worker.carregar_pipeline_trellis(args.model) if args.eager else None
        srv = criar_servidor(args.host, args.port, modelo=args.model, token=args.token, pipeline=pipe)
    except (ValueError, RuntimeError, OSError) as exc:
        sys.stderr.write(f"ERRO: {exc}\n")
        return 2
    sys.stderr.write(f"TRELLIS HTTP ouvindo em http://{args.host}:{srv.server_port} ({srv.estado_trellis.modelo_padrao})\n")  # type: ignore[attr-defined]
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
