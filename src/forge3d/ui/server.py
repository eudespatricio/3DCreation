"""Servidor HTTP multithread stdlib e roteador REST para o Forge3D Studio."""

from __future__ import annotations

import json
import os
import shutil
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from ..errors import ForgeError, erro_interno, erro_spec
from . import actions, catalog
from .state import (
    JobManager,
    eh_host_loopback,
    erro_nao_encontrado,
    erro_proibido,
    erro_requisicao,
    payload_erro,
    resolver_caminho_leitura,
    salvar_spec_ui,
    salvar_upload_input,
    validar_origem_csrf,
)

MAX_JSON_BODY = 72 * 1024 * 1024

MIME_POR_EXT: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".obj": "text/plain; charset=utf-8",
    ".rbxlx": "application/xml; charset=utf-8",
    ".rbxmx": "application/xml; charset=utf-8",
    ".gd": "text/plain; charset=utf-8",
    ".lua": "text/plain; charset=utf-8",
    ".yaml": "text/plain; charset=utf-8",
    ".yml": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


class Forge3DHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer com JobManager isolado e raiz estatica ui_web."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[BaseHTTPRequestHandler],
        *,
        job_manager: JobManager | None = None,
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.job_manager = job_manager or JobManager()
        self.ui_web_dir = (Path(__file__).resolve().parents[1] / "ui_web").resolve(strict=False)


def _q(qs: dict[str, list[str]], chave: str, padrao: str = "") -> str:
    vals = qs.get(chave)
    return vals[0] if vals else padrao


def _q_int(qs: dict[str, list[str]], chave: str, padrao: int) -> int:
    bruto = _q(qs, chave, "")
    if not bruto.strip():
        return padrao
    try:
        return int(bruto)
    except ValueError as exc:
        raise erro_requisicao(f"parametro inteiro invalido em {chave}: {bruto!r}") from exc


def _q_int_opt(qs: dict[str, list[str]], chave: str) -> int | None:
    bruto = _q(qs, chave, "")
    if not bruto.strip():
        return None
    try:
        return int(bruto)
    except ValueError as exc:
        raise erro_requisicao(f"parametro inteiro invalido em {chave}: {bruto!r}") from exc


class Forge3DRequestHandler(BaseHTTPRequestHandler):
    """Handler HTTP da API /api/* e dos assets estaticos do SPA em ui_web/."""

    server_version = "Forge3DUI/0.9.5"

    @property
    def _srv(self) -> Forge3DHTTPServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("FORGE3D_UI_LOG") == "1":
            super().log_message(fmt, *args)

    def _enviar_bytes(
        self,
        status: int,
        corpo: bytes,
        content_type: str,
        *,
        headers_extra: dict[str, str] | None = None,
        somente_head: bool = False,
    ) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (headers_extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if not somente_head and corpo:
                self.wfile.write(corpo)
        except OSError as exc:
            if os.environ.get("FORGE3D_UI_LOG") == "1":
                print(f"[ui] conexao encerrada pelo cliente: {exc}", file=sys.stderr)

    def _enviar_json(self, status: int, obj: dict[str, Any], *, somente_head: bool = False) -> None:
        dados = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self._enviar_bytes(status, dados, "application/json; charset=utf-8", somente_head=somente_head)

    def _enviar_erro_forge(self, exc: ForgeError, *, somente_head: bool = False) -> None:
        status, obj = payload_erro(exc)
        self._enviar_json(status, obj, somente_head=somente_head)

    def _ler_json_body(self) -> dict[str, Any]:
        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            return {}
        try:
            tamanho = int(raw_len)
        except ValueError as exc:
            raise erro_requisicao("Content-Length invalido") from exc
        if tamanho < 0 or tamanho > MAX_JSON_BODY:
            raise erro_requisicao(f"corpo HTTP excede o limite de {MAX_JSON_BODY} bytes")
        if tamanho == 0:
            return {}
        bruto = self.rfile.read(tamanho)
        try:
            doc = json.loads(bruto.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise erro_requisicao(f"JSON invalido no corpo da requisicao: {exc}") from exc
        if not isinstance(doc, dict):
            raise erro_requisicao("corpo JSON precisa ser um objeto")
        return doc

    def _servir_estatico(self, rel_raw: str, *, somente_head: bool = False) -> None:
        limpo = rel_raw.strip("/")
        if not limpo or "\\" in limpo or "\x00" in limpo:
            raise erro_proibido("caminho estatico invalido")
        partes = Path(limpo).parts
        if any(p in ("", ".", "..") or p.startswith(".") for p in partes):
            raise erro_proibido("tentativa de travessia em arquivo estatico", caminho=rel_raw)

        ui_dir = self._srv.ui_web_dir
        alvo = (ui_dir / limpo).resolve(strict=False)
        if not alvo.is_relative_to(ui_dir):
            raise erro_proibido("escape fora de ui_web bloqueado", caminho=rel_raw)
        if not alvo.is_file():
            raise erro_nao_encontrado(f"arquivo estatico nao encontrado: {limpo}")

        mime = MIME_POR_EXT.get(alvo.suffix.lower(), "application/octet-stream")
        self._enviar_bytes(200, alvo.read_bytes(), mime, somente_head=somente_head)

    def _servir_arquivo_sandbox(self, qs: dict[str, list[str]], *, somente_head: bool = False) -> None:
        raw_path = _q(qs, "path", "")
        alvo = resolver_caminho_leitura(raw_path)
        if not alvo.is_file():
            raise erro_nao_encontrado(f"arquivo nao encontrado: {alvo}", caminho=str(alvo))

        mime = MIME_POR_EXT.get(alvo.suffix.lower(), "application/octet-stream")
        tamanho = alvo.stat().st_size
        try:
            with alvo.open("rb") as fh:
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(tamanho))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                if _q(qs, "download", "").strip().lower() in ("1", "true", "yes"):
                    nome_dl = alvo.name.replace('"', "_")
                    self.send_header("Content-Disposition", f'attachment; filename="{nome_dl}"')
                self.end_headers()
                if not somente_head and tamanho > 0:
                    shutil.copyfileobj(fh, self.wfile, length=65536)
        except OSError as exc:
            if os.environ.get("FORGE3D_UI_LOG") == "1":
                print(f"[ui] falha E/S ao transmitir {alvo}: {exc}", file=sys.stderr)

    def _despachar_get(self, *, somente_head: bool = False) -> None:
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if "\x00" in path:
            raise erro_proibido("caminho contem byte nulo")
        qs = parse_qs(parsed.query, keep_blank_values=False)

        if path != "/api/file" and ("\\" in path or ".." in Path(path).parts):
            raise erro_proibido("travessia de caminho bloqueada", path=path)

        if path in ("/", "/index.html"):
            self._servir_estatico("index.html", somente_head=somente_head)
            return
        if path == "/favicon.ico":
            self._enviar_bytes(204, b"", "image/x-icon", somente_head=True)
            return
        if path.startswith("/static/"):
            self._servir_estatico(path[len("/static/") :], somente_head=somente_head)
            return
        if not path.startswith("/api/"):
            if path.count("/") == 1:
                self._servir_estatico(path.lstrip("/"), somente_head=somente_head)
                return
            raise erro_nao_encontrado(f"rota nao encontrada: {path}")

        if path == "/api/health":
            self._enviar_json(200, catalog.obter_health(), somente_head=somente_head)
        elif path == "/api/doctor":
            self._enviar_json(200, catalog.obter_doctor(), somente_head=somente_head)
        elif path == "/api/meta":
            self._enviar_json(200, catalog.obter_meta(), somente_head=somente_head)
        elif path.startswith("/api/examples/"):
            nome_ex = path[len("/api/examples/") :]
            self._enviar_json(200, catalog.obter_exemplo(nome_ex), somente_head=somente_head)
        elif path == "/api/destinations":
            self._enviar_json(200, catalog.listar_destinos(), somente_head=somente_head)
        elif path == "/api/assets":
            resp = catalog.listar_ativos(
                q=_q(qs, "q"),
                projeto=_q(qs, "projeto"),
                perfil=_q(qs, "perfil"),
                rota=_q(qs, "rota"),
                destino=_q(qs, "destino"),
                tag=_q(qs, "tag"),
                max_tris=_q_int_opt(qs, "max_tris"),
                limit=_q_int(qs, "limit", 200),
                offset=_q_int(qs, "offset", 0),
            )
            self._enviar_json(200, resp, somente_head=somente_head)
        elif path == "/api/asset":
            self._enviar_json(
                200,
                catalog.obter_ativo(_q(qs, "destino"), _q(qs, "id")),
                somente_head=somente_head,
            )
        elif path == "/api/asset/bundle.zip":
            nome_zip, bytes_zip = catalog.gerar_bundle_zip(_q(qs, "destino"), _q(qs, "id"))
            self._enviar_bytes(
                200,
                bytes_zip,
                "application/zip",
                headers_extra={"Content-Disposition": f'attachment; filename="{nome_zip}"'},
                somente_head=somente_head,
            )
        elif path == "/api/file":
            self._servir_arquivo_sandbox(qs, somente_head=somente_head)
        elif path == "/api/runs":
            self._enviar_json(200, catalog.listar_runs(limit=_q_int(qs, "limit", 50)), somente_head=somente_head)
        elif path.startswith("/api/runs/"):
            rid = path[len("/api/runs/") :]
            self._enviar_json(200, catalog.obter_run(rid), somente_head=somente_head)
        elif path == "/api/ledger":
            self._enviar_json(200, catalog.listar_ledger(limit=_q_int(qs, "limit", 100)), somente_head=somente_head)
        elif path == "/api/jobs":
            self._enviar_json(200, {"ok": True, "jobs": self._srv.job_manager.listar()}, somente_head=somente_head)
        elif path.startswith("/api/jobs/"):
            jid = path[len("/api/jobs/") :]
            job = self._srv.job_manager.obter(jid)
            self._enviar_json(200, {"ok": True, "job": job, **job}, somente_head=somente_head)
        else:
            raise erro_nao_encontrado(f"endpoint GET inexistente: {path}")

    def _despachar_post(self) -> None:
        validar_origem_csrf(self.headers.get("Origin"), self.headers.get("Referer"))
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if "\x00" in path or "\\" in path or ".." in Path(path).parts:
            raise erro_proibido("caminho POST invalido", path=path)

        body = self._ler_json_body()
        jobs = self._srv.job_manager

        if path == "/api/upload-input":
            resp = salvar_upload_input(
                nome=str(body.get("nome") or ""),
                conteudo_b64=str(body.get("conteudo_b64") or ""),
                categoria=str(body.get("categoria") or "input"),
            )
            self._enviar_json(200, resp)
        elif path == "/api/spec/save":
            alvo = salvar_spec_ui(str(body.get("nome") or ""), str(body.get("yaml") or ""))
            self._enviar_json(200, {"ok": True, "nome": alvo.name, "caminho": str(alvo)})
        elif path == "/api/validate":
            self._enviar_json(200, actions.validar_spec(body))
        elif path == "/api/plan":
            self._enviar_json(200, actions.planejar_spec(body))
        elif path == "/api/run":
            self._enviar_json(202, actions.iniciar_run(body, jobs))
        elif path.startswith("/api/jobs/") and path.endswith("/cancel"):
            jid = path[len("/api/jobs/") : -len("/cancel")].strip("/")
            job = jobs.cancelar(jid)
            self._enviar_json(200, {"ok": True, "job_id": job["job_id"], "status": job["status"], "job": job})
        elif path == "/api/verify":
            self._enviar_json(200, actions.verificar_destino(body))
        elif path == "/api/migrate":
            self._enviar_json(200, actions.migrar_spec(body))
        elif path == "/api/export":
            self._enviar_json(200, actions.exportar_asset(body))
        elif path == "/api/sync":
            self._enviar_json(200, actions.sincronizar_destino(body))
        elif path == "/api/upload-cloud":
            status, resp = actions.upload_cloud(body, jobs)
            self._enviar_json(status, resp)
        elif path == "/api/allowlist":
            self._enviar_json(200, actions.gerenciar_allowlist(body))
        elif path == "/api/gc":
            self._enviar_json(200, actions.executar_gc(body))
        else:
            raise erro_nao_encontrado(f"endpoint POST inexistente: {path}")

    def do_GET(self) -> None:  # noqa: N802
        try:
            self._despachar_get(somente_head=False)
        except ForgeError as exc:
            self._enviar_erro_forge(exc)
        except Exception as exc:  # noqa: BLE001
            print(f"[ui] erro interno em GET {self.path}: {type(exc).__name__}: {exc}", file=sys.stderr)
            self._enviar_erro_forge(erro_interno(f"{type(exc).__name__}: {exc}"))

    def do_HEAD(self) -> None:  # noqa: N802
        try:
            self._despachar_get(somente_head=True)
        except ForgeError as exc:
            self._enviar_erro_forge(exc, somente_head=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[ui] erro interno em HEAD {self.path}: {type(exc).__name__}: {exc}", file=sys.stderr)
            self._enviar_erro_forge(erro_interno(f"{type(exc).__name__}: {exc}"), somente_head=True)

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._despachar_post()
        except ForgeError as exc:
            self._enviar_erro_forge(exc)
        except Exception as exc:  # noqa: BLE001
            print(f"[ui] erro interno em POST {self.path}: {type(exc).__name__}: {exc}", file=sys.stderr)
            self._enviar_erro_forge(erro_interno(f"{type(exc).__name__}: {exc}"))

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            validar_origem_csrf(self.headers.get("Origin"), self.headers.get("Referer"))
            raise erro_nao_encontrado(f"endpoint DELETE inexistente: {self.path}")
        except ForgeError as exc:
            self._enviar_erro_forge(exc)
        except Exception as exc:  # noqa: BLE001
            print(f"[ui] erro interno em DELETE {self.path}: {type(exc).__name__}: {exc}", file=sys.stderr)
            self._enviar_erro_forge(erro_interno(f"{type(exc).__name__}: {exc}"))


def criar_servidor(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    job_manager: JobManager | None = None,
) -> Forge3DHTTPServer:
    porta = int(port)
    if porta < 0 or porta > 65535:
        raise erro_spec(f"ui: porta TCP invalida ({port}); use 0..65535")
    if not eh_host_loopback(host):
        print(
            f"aviso [seguranca]: Forge3D Studio escutando fora de loopback ({host}:{porta}); "
            "use apenas em rede local confiavel.",
            file=sys.stderr,
        )
    return Forge3DHTTPServer((host, porta), Forge3DRequestHandler, job_manager=job_manager)


def servir(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    no_browser: bool = False,
    abrir_navegador: bool | None = None,
) -> int:
    deve_abrir = (not no_browser) if abrir_navegador is None else (bool(abrir_navegador) and not no_browser)
    srv = criar_servidor(host=host, port=port)
    porta_real = int(srv.server_address[1])
    host_url = f"[{host}]" if (":" in host and not host.startswith("[")) else host
    url = f"http://{host_url}:{porta_real}/"
    print(f"Forge3D Studio ativo em {url}", flush=True)
    if deve_abrir:
        try:
            webbrowser.open(url)
        except (OSError, webbrowser.Error) as exc:
            print(f"[ui] aviso ao abrir navegador automaticamente: {exc}", file=sys.stderr)

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nForge3D Studio encerrado.", file=sys.stderr)
    finally:
        srv.job_manager.encerrar_todos()
        srv.server_close()
    return 0
