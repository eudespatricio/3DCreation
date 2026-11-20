"""Estado, sandbox de leitura, uploads de entrada e gerenciador de jobs da UI."""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import signal
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from .. import config, paths
from ..errors import EXIT_QC, EXIT_RECURSO, EXIT_SPEC, ForgeError

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_B64_CHARS = ((MAX_UPLOAD_BYTES + 2) // 3) * 4 + 4096
MAX_SPEC_CHARS = 2 * 1024 * 1024
MAX_LOG_LINES = 2000

EXTS_UPLOAD_PERMITIDAS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".glb", ".gltf", ".obj"})
HOSTS_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
_CODIGOS_422 = frozenset(
    {
        "FORGE-E-SPEC",
        "FORGE-E-DESTINO",
        "FORGE-E-PATH",
        "FORGE-E-INPUT-TAMPERED",
        "FORGE-E-MANIFEST",
        "FORGE-E-QC",
        "FORGE-E-QC-SCENE",
        "FORGE-E-UPLOAD",
    }
)
_RE_NOME_SEGURO = re.compile(r"[^A-Za-z0-9._-]+")
_RE_ID_SIMPLES = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class UIHTTPError(ForgeError):
    """Erro estruturado da camada HTTP com status explicito e payload de contrato."""

    def __init__(
        self,
        http_status: int,
        codigo: str,
        mensagem: str,
        exit_code: int = EXIT_SPEC,
        detalhes: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(codigo, mensagem, exit_code, detalhes)
        self.http_status = int(http_status)


def erro_requisicao(msg: str, **det: Any) -> UIHTTPError:
    return UIHTTPError(400, "FORGE-E-REQUISICAO", msg, EXIT_SPEC, det)


def erro_proibido(msg: str, **det: Any) -> UIHTTPError:
    return UIHTTPError(403, "FORGE-E-FORBIDDEN", msg, EXIT_SPEC, det)


def erro_nao_encontrado(msg: str, **det: Any) -> UIHTTPError:
    return UIHTTPError(404, "FORGE-E-NAO-ENCONTRADO", msg, EXIT_SPEC, det)


def status_para_erro(exc: ForgeError) -> int:
    if isinstance(exc, UIHTTPError):
        return exc.http_status
    if exc.codigo == "FORGE-E-FORBIDDEN":
        return 403
    if exc.codigo == "FORGE-E-NAO-ENCONTRADO":
        return 404
    if exc.codigo == "FORGE-E-REQUISICAO":
        return 400
    if exc.codigo == "FORGE-E-RECURSO" or exc.exit_code == EXIT_RECURSO:
        return 409
    if exc.codigo in _CODIGOS_422 or exc.exit_code in (EXIT_SPEC, EXIT_QC):
        return 422
    return 500


def payload_erro(exc: ForgeError) -> tuple[int, dict[str, Any]]:
    return status_para_erro(exc), {
        "ok": False,
        "codigo": exc.codigo,
        "exit": exc.exit_code,
        "mensagem": exc.mensagem,
        "detalhes": dict(exc.detalhes or {}),
    }


def agora_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def eh_host_loopback(host: str) -> bool:
    limpo = host.strip().lower().strip("[]")
    if limpo in HOSTS_LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(limpo).is_loopback
    except ValueError:
        return False


def validar_origem_csrf(origin_header: str | None, referer_header: str | None = None) -> None:
    if origin_header is not None and origin_header.strip():
        bruto = origin_header.strip()
        hostname = (urlparse(bruto).hostname or "").strip().lower()
        if hostname not in HOSTS_LOOPBACK:
            raise erro_proibido(f"Origem HTTP recusada por protecao CSRF local: {bruto!r}", origin=bruto)
        return
    if referer_header is not None and referer_header.strip():
        bruto_ref = referer_header.strip()
        hostname_ref = (urlparse(bruto_ref).hostname or "").strip().lower()
        if hostname_ref not in HOSTS_LOOPBACK:
            raise erro_proibido(f"Referer HTTP recusado por protecao CSRF local: {bruto_ref!r}", referer=bruto_ref)


def raizes_leitura_permitidas() -> list[Path]:
    raizes: list[Path] = [
        paths.raiz_estado().resolve(strict=False),
        paths.dir_saida().resolve(strict=False),
        (paths.raiz_dados() / "examples").resolve(strict=False),
    ]
    try:
        for p in config.carregar():
            res = p.resolve(strict=False)
            if res not in raizes:
                raizes.append(res)
    except ForgeError as exc:
        print(f"[ui] aviso ao carregar allowlist: {exc}", file=sys.stderr)
    return raizes


def resolver_caminho_leitura(path_raw: str | os.PathLike[str]) -> Path:
    """Resolve caminho de leitura garantindo confinamento estrito e negando raiz_config()."""
    texto = str(path_raw or "").strip()
    if not texto or "\x00" in texto:
        raise erro_requisicao("caminho ausente ou invalido")
    cand = Path(texto).expanduser()
    if not cand.is_absolute():
        cand_dados = paths.raiz_dados() / cand
        cand = cand_dados if cand_dados.exists() else (Path.cwd() / cand)
    try:
        alvo = cand.resolve(strict=False)
    except OSError as exc:
        raise erro_proibido(f"falha ao resolver caminho: {exc}", caminho=texto) from exc

    raiz_cfg = paths.raiz_config().resolve(strict=False)
    if alvo == raiz_cfg or alvo.is_relative_to(raiz_cfg):
        raise erro_proibido("acesso negado ao diretorio de configuracao/credenciais do Forge3D", caminho=str(alvo))
    for raiz in raizes_leitura_permitidas():
        if alvo == raiz or alvo.is_relative_to(raiz):
            return alvo
    raise erro_proibido(f"caminho fora das raizes de leitura permitidas: {alvo}", caminho=str(alvo))


def validar_identificador_segmento(valor: str, campo: str = "id") -> str:
    limpo = (valor or "").strip()
    if not limpo:
        raise erro_requisicao(f"parametro obrigatorio ausente: {campo}")
    if "/" in limpo or "\\" in limpo or ".." in limpo or "\x00" in limpo or not _RE_ID_SIMPLES.match(limpo):
        raise erro_proibido(f"identificador invalido em {campo}: {limpo!r}", campo=campo)
    return limpo


def sanitizar_nome_arquivo(nome: str) -> tuple[str, str]:
    base = Path(str(nome or "").strip()).name
    if not base or base in (".", ".."):
        raise erro_requisicao("nome de arquivo ausente ou invalido")
    ext = Path(base).suffix.lower()
    stem = (_RE_NOME_SEGURO.sub("_", Path(base).stem).strip("._-") or "input")[:80]
    return f"{stem}{ext}", ext


def sanitizar_slug_spec(nome: str) -> str:
    bruto = str(nome or "").strip()
    if not bruto:
        raise erro_requisicao("informe o nome do lote para salvar")
    if "/" in bruto or "\\" in bruto or ".." in bruto or "\x00" in bruto:
        raise erro_proibido("nome de lote contem separador de caminho proibido", nome=bruto)
    for sufixo in (".yaml", ".yml"):
        if bruto.lower().endswith(sufixo):
            bruto = bruto[: -len(sufixo)]
            break
    slug = _RE_NOME_SEGURO.sub("_", bruto).strip("._-")[:96]
    if not slug:
        raise erro_requisicao("nome de lote invalido apos sanitizacao")
    return slug


def _validar_magic_bytes(dados: bytes, ext: str) -> None:
    if ext == ".png" and not dados.startswith(b"\x89PNG\r\n\x1a\n"):
        raise erro_requisicao("assinatura binaria invalida para arquivo .png")
    if ext in (".jpg", ".jpeg") and not dados.startswith(b"\xff\xd8\xff"):
        raise erro_requisicao("assinatura binaria invalida para arquivo JPEG")
    if ext == ".webp" and (len(dados) < 12 or dados[:4] != b"RIFF" or dados[8:12] != b"WEBP"):
        raise erro_requisicao("assinatura binaria invalida para arquivo .webp")
    if ext == ".glb" and (len(dados) < 12 or dados[:4] != b"glTF"):
        raise erro_requisicao("assinatura binaria invalida para arquivo .glb")
    if ext == ".gltf":
        if b"\x00" in dados:
            raise erro_requisicao("arquivo .gltf nao pode conter bytes nulos")
        try:
            obj = json.loads(dados.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise erro_requisicao(f"arquivo .gltf precisa ser JSON valido: {exc}") from exc
        if not isinstance(obj, dict):
            raise erro_requisicao("arquivo .gltf precisa ter objeto JSON na raiz")
    if ext == ".obj" and b"\x00" in dados:
        raise erro_requisicao("arquivo .obj invalido (binario detectado)")


def salvar_upload_input(nome: str, conteudo_b64: str, categoria: str = "input") -> dict[str, Any]:
    safe_name, ext = sanitizar_nome_arquivo(nome)
    if ext not in EXTS_UPLOAD_PERMITIDAS:
        raise erro_requisicao(f"extensao nao permitida: {ext!r}", extensao=ext)
    if not isinstance(conteudo_b64, str) or not conteudo_b64.strip():
        raise erro_requisicao("conteudo_b64 ausente ou vazio")
    payload_b64 = conteudo_b64.strip()
    if payload_b64.startswith("data:") and "," in payload_b64:
        payload_b64 = payload_b64.split(",", 1)[1].strip()
    if len(payload_b64) > MAX_B64_CHARS:
        raise erro_requisicao(f"upload excede o limite maximo de {MAX_UPLOAD_BYTES} bytes")
    try:
        dados = base64.b64decode(payload_b64, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise erro_requisicao(f"base64 invalido no upload: {exc}") from exc
    if not dados or len(dados) > MAX_UPLOAD_BYTES:
        raise erro_requisicao(f"tamanho de upload invalido ({len(dados)} B; max {MAX_UPLOAD_BYTES} B)")
    _validar_magic_bytes(dados, ext)

    digest = hashlib.sha256(dados).hexdigest()
    pasta = paths.raiz_estado() / "inputs" / "ui_uploads"
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = (pasta / f"{digest[:12]}_{safe_name}").resolve(strict=False)
    if not alvo.is_relative_to(pasta.resolve(strict=False)):
        raise erro_proibido("destino de upload escapou do diretorio seguro")
    tmp = alvo.with_name(f".{alvo.name}.{os.getpid()}.tmp")
    tmp.write_bytes(dados)
    os.replace(tmp, alvo)
    caminho_str = str(alvo)
    return {
        "ok": True,
        "nome": safe_name,
        "categoria": str(categoria or "input"),
        "caminho": caminho_str,
        "sha256": f"sha256:{digest}",
        "bytes": len(dados),
        "url": f"/api/file?path={quote(caminho_str, safe='')}",
    }


def salvar_spec_ui(nome: str, yaml_text: str) -> Path:
    slug = sanitizar_slug_spec(nome)
    if not isinstance(yaml_text, str) or not yaml_text.strip():
        raise erro_requisicao("conteudo YAML ausente ou vazio")
    if len(yaml_text) > MAX_SPEC_CHARS:
        raise erro_requisicao("conteudo YAML excede o tamanho maximo permitido (2 MB)")
    pasta = paths.raiz_estado() / "inputs" / "ui_specs"
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = (pasta / f"{slug}.yaml").resolve(strict=False)
    if not alvo.is_relative_to(pasta.resolve(strict=False)):
        raise erro_proibido("caminho do lote escapou de ui_specs")
    tmp = alvo.with_name(f".{alvo.name}.{os.getpid()}.tmp")
    tmp.write_text(yaml_text if yaml_text.endswith("\n") else yaml_text + "\n", encoding="utf-8")
    os.replace(tmp, alvo)
    return alvo


class JobManager:
    """Gerencia subprocessos assincronos do CLI (run / upload Open Cloud) com logs e cancelamento."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._procs: dict[str, subprocess.Popen[str]] = {}

    def iniciar(self, tipo: str, cli_args: list[str], *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        job_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{os.urandom(3).hex()}"
        job_dir = paths.raiz_estado() / "ui_jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        report_path = job_dir / "report.json"
        env = dict(os.environ, FORGE3D_JSON_OUT=str(report_path), PYTHONUNBUFFERED="1")
        src_root = Path(__file__).resolve().parents[2]
        if (src_root / "forge3d").is_dir():
            partes = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
            if str(src_root) not in partes:
                env["PYTHONPATH"] = os.pathsep.join([str(src_root), *partes])

        cwd = str(paths.raiz_dados()) if paths.raiz_dados().is_dir() else None
        proc = subprocess.Popen(
            [sys.executable, "-m", "forge3d.cli.main", *cli_args],
            cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            start_new_session=(os.name == "posix"),
        )
        registro: dict[str, Any] = {
            "job_id": job_id, "tipo": tipo, "status": "running", "started_at": agora_iso(),
            "finished_at": None, "exit_code": None, "resultado": None, "erro": None,
            "logs": [f"[{agora_iso()}] iniciando: forge3d {' '.join(cli_args)}"], **(extra or {}),
        }
        with self._lock:
            self._jobs[job_id] = registro
            self._procs[job_id] = proc
        threading.Thread(target=self._monitorar, args=(job_id, proc, report_path, job_dir), daemon=True).start()
        return {**registro, "logs": list(registro["logs"])}

    def _anexar_log(self, job_id: str, linha: str) -> None:
        texto = linha.rstrip("\r\n")
        if not texto:
            return
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and len(job["logs"]) < MAX_LOG_LINES:
                job["logs"].append(texto)

    def _monitorar(self, job_id: str, proc: subprocess.Popen[str], report_path: Path, job_dir: Path) -> None:
        stdout_chunks: list[str] = []

        def _ler_err() -> None:
            for ln in proc.stderr or ():
                self._anexar_log(job_id, ln)

        def _ler_out() -> None:
            for ch in proc.stdout or ():
                stdout_chunks.append(ch)

        t_err = threading.Thread(target=_ler_err, daemon=True)
        t_out = threading.Thread(target=_ler_out, daemon=True)
        t_err.start()
        t_out.start()
        rc = proc.wait()
        t_err.join(timeout=2.0)
        t_out.join(timeout=2.0)
        resultado = self._extrair_resultado(job_id, report_path, "".join(stdout_chunks).strip())

        with self._lock:
            self._procs.pop(job_id, None)
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.update(exit_code=int(rc), finished_at=agora_iso(), resultado=resultado)
            if resultado and isinstance(resultado.get("itens"), list):
                for it in resultado["itens"]:
                    if isinstance(it, dict):
                        job["logs"].append(f"  [{it.get('estado', '?')}] {it.get('id', '?')} {it.get('codigo') or it.get('rota') or ''}".strip())
            if job["status"] == "cancelled":
                job["erro"] = job.get("erro") or {"codigo": "FORGE-E-CANCELADO", "mensagem": "Job cancelado pelo operador"}
            elif rc == 0:
                job["status"] = "done"
            else:
                job["status"] = "failed"
                erro_rel = resultado.get("erro") if isinstance(resultado, dict) else None
                job["erro"] = erro_rel or {"codigo": "FORGE-E-JOB", "mensagem": f"Processo terminou com exit code {rc}"}
            job["logs"].append(f"[{job['finished_at']}] finalizado: status={job['status']} exit={rc}")
            snapshot = {**job, "logs": list(job["logs"])}
        try:
            (job_dir / "job.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except OSError as exc:
            print(f"[ui] aviso ao persistir job.json ({job_id}): {exc}", file=sys.stderr)

    def _extrair_resultado(self, job_id: str, report_path: Path, bruto_out: str) -> dict[str, Any] | None:
        if report_path.is_file():
            try:
                lido = json.loads(report_path.read_text(encoding="utf-8"))
                if isinstance(lido, dict):
                    return lido
            except (OSError, json.JSONDecodeError) as exc:
                self._anexar_log(job_id, f"[aviso] falha ao ler report.json: {exc}")
        if bruto_out.startswith("{"):
            try:
                lido_out = json.loads(bruto_out)
                if isinstance(lido_out, dict):
                    return lido_out
            except json.JSONDecodeError:
                self._anexar_log(job_id, bruto_out[:400])
        elif bruto_out:
            for ln in bruto_out.splitlines()[:50]:
                self._anexar_log(job_id, ln)
        return None

    def listar(self) -> list[dict[str, Any]]:
        with self._lock:
            em_mem = {jid: {**j, "logs": list(j.get("logs") or [])} for jid, j in self._jobs.items()}
        pasta = paths.raiz_estado() / "ui_jobs"
        if pasta.is_dir():
            for sub in sorted(pasta.iterdir(), reverse=True)[:50]:
                arq = sub / "job.json"
                if sub.name not in em_mem and arq.is_file():
                    try:
                        dados = json.loads(arq.read_text(encoding="utf-8"))
                        if isinstance(dados, dict) and "job_id" in dados:
                            em_mem[sub.name] = dados
                    except (OSError, json.JSONDecodeError) as exc:
                        print(f"[ui] aviso ao ler {arq}: {exc}", file=sys.stderr)
        return sorted(em_mem.values(), key=lambda j: str(j.get("started_at") or ""), reverse=True)

    def obter(self, job_id: str) -> dict[str, Any]:
        jid = validar_identificador_segmento(job_id, "job_id")
        with self._lock:
            if jid in self._jobs:
                j = self._jobs[jid]
                return {**j, "logs": list(j.get("logs") or [])}
        arq = paths.raiz_estado() / "ui_jobs" / jid / "job.json"
        if arq.is_file():
            try:
                dados = json.loads(arq.read_text(encoding="utf-8"))
                if isinstance(dados, dict):
                    return dados
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[ui] aviso ao ler job persistido {jid}: {exc}", file=sys.stderr)
        raise erro_nao_encontrado(f"job nao encontrado: {jid}", job_id=jid)

    def cancelar(self, job_id: str) -> dict[str, Any]:
        jid = validar_identificador_segmento(job_id, "job_id")
        with self._lock:
            job, proc = self._jobs.get(jid), self._procs.get(jid)
            if job is None:
                raise erro_nao_encontrado(f"job nao encontrado: {jid}", job_id=jid)
            if proc is None or job["status"] != "running":
                return {**job, "logs": list(job.get("logs") or [])}
            job["status"] = "cancelled"
            job["logs"].append(f"[{agora_iso()}] cancelamento solicitado (SIGTERM)")
        self._sinalizar_processo(proc, sig_kill=False)
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            self._anexar_log(jid, f"[{agora_iso()}] enviando SIGKILL apos timeout")
            self._sinalizar_processo(proc, sig_kill=True)
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired as exc:
                print(f"[ui] aviso ao aguardar SIGKILL ({jid}): {exc}", file=sys.stderr)
        return self.obter(jid)

    @staticmethod
    def _sinalizar_processo(proc: subprocess.Popen[str], *, sig_kill: bool) -> None:
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL if sig_kill else signal.SIGTERM)
            elif sig_kill:
                proc.kill()
            else:
                proc.terminate()
        except OSError as exc:
            print(f"[ui] diagnostico sinalizando pid={proc.pid}: {exc}", file=sys.stderr)

    def encerrar_todos(self) -> None:
        with self._lock:
            ativos = [jid for jid, j in self._jobs.items() if j.get("status") == "running"]
        for jid in ativos:
            try:
                self.cancelar(jid)
            except ForgeError as exc:
                print(f"[ui] aviso ao encerrar job {jid}: {exc}", file=sys.stderr)
