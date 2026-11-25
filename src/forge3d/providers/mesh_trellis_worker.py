"""Cliente persistente em subprocesso para worker residente TRELLIS.2-4B (I9)."""

from __future__ import annotations

import atexit
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

_DEFAULT_MAX_JOBS = 20


def max_jobs_worker() -> int:
    """Retorna o limite de jobs antes de reciclar o worker TRELLIS.2."""
    raw = os.environ.get("FORGE3D_TRELLIS2_WORKER_MAX_JOBS", "").strip()
    if not raw:
        return _DEFAULT_MAX_JOBS
    val = int(raw)
    if val <= 0:
        raise ValueError(f"FORGE3D_TRELLIS2_WORKER_MAX_JOBS deve ser >= 1: {raw!r}")
    return val


def _config_chave(req: dict[str, Any]) -> tuple[str, str, str, str, bool]:
    raw_models = str(req.get("models_dir") or "").strip()
    raw_repo = str(req.get("repo_dir") or "").strip()
    return (
        str(Path(raw_models).expanduser().resolve()) if raw_models else "",
        str(Path(raw_repo).expanduser().resolve()) if raw_repo else "",
        str(req.get("quant", "BF16")).strip().upper() or "BF16",
        str(req.get("pipeline_type", "512")).strip().lower() or "512",
        bool(req.get("tiled_tex", False)),
    )


def _spec_chave(venv_py: Path, worker_script: Path, env: dict[str, str]) -> tuple[str, str, str, str]:
    return (str(venv_py), str(worker_script), env.get("FORGE3D_TRELLIS2_DIR", ""), env.get("LD_LIBRARY_PATH", ""))


def _iniciar_leitor(proc: subprocess.Popen[str]) -> queue.Queue[str | Exception | None]:
    q: queue.Queue[str | Exception | None] = queue.Queue()

    def _run() -> None:
        try:
            for linha in proc.stdout or ():
                q.put(linha)
        except (OSError, ValueError) as exc:
            q.put(exc)
        finally:
            q.put(None)

    threading.Thread(target=_run, name="trellis2-worker-stdout", daemon=True).start()
    return q


class Trellis2WorkerClient:
    """Gerencia um subprocesso residente de ``tools/trellis2_worker.py`` via JSON-lines."""

    def __init__(self, venv_py: Path | None = None, worker_script: Path | None = None, env: dict[str, str] | None = None) -> None:
        self._lock = threading.RLock()
        self.active_proc: subprocess.Popen[str] | None = None
        self.jobs_executados: int = 0
        self.config_chave: tuple[str, str, str, str, bool] | None = None
        self.worker_spec_key: tuple[str, str, str, str] | None = None
        self._reader_q: queue.Queue[str | Exception | None] | None = None
        self._last_launch: tuple[Path, Path, dict[str, str]] | None = (
            (Path(venv_py), Path(worker_script), dict(os.environ if env is None else env))
            if venv_py is not None and worker_script is not None
            else None
        )

    def _kill_proc(self) -> None:
        proc = self.active_proc
        if proc is None:
            return
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except (subprocess.TimeoutExpired, OSError) as exc:
                    sys.stderr.write(f"[mesh_trellis_worker] aviso worker nao encerrou apos kill: {exc}\n")
            except OSError as exc:
                sys.stderr.write(f"[mesh_trellis_worker] aviso ao encerrar worker: {exc}\n")
        for stream in (proc.stdin, proc.stdout):
            if stream is not None:
                try:
                    stream.close()
                except (OSError, ValueError) as exc:
                    sys.stderr.write(f"[mesh_trellis_worker] aviso fechando stream: {exc}\n")
        self.active_proc = self._reader_q = self.config_chave = self.worker_spec_key = None
        self.jobs_executados = 0

    def _spawn(
        self, venv_py: Path, worker_script: Path, env: dict[str, str],
        cfg_key: tuple[str, str, str, str, bool] | None, spec_key: tuple[str, str, str, str],
    ) -> None:
        env_copia = dict(env)
        proc = subprocess.Popen(
            [str(venv_py), str(worker_script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, text=True, bufsize=1, env=env_copia,
        )
        self.active_proc, self._reader_q = proc, _iniciar_leitor(proc)
        self.jobs_executados, self.config_chave, self.worker_spec_key = 0, cfg_key, spec_key
        self._last_launch = (Path(venv_py), Path(worker_script), env_copia)

    def _ler_linha(self, timeout_s: float) -> str:
        if self._reader_q is None:
            raise RuntimeError("leitor stdout do worker nao inicializado")
        deadline = time.monotonic() + max(0.001, float(timeout_s))
        while True:
            restante = deadline - time.monotonic()
            if restante <= 0.0:
                raise TimeoutError(f"timeout de {timeout_s}s aguardando worker TRELLIS.2")
            try:
                item = self._reader_q.get(timeout=restante)
            except queue.Empty as exc:
                raise TimeoutError(f"timeout de {timeout_s}s aguardando worker TRELLIS.2") from exc
            if item is None:
                raise EOFError("worker TRELLIS.2 encerrou stdout inesperadamente")
            if isinstance(item, Exception):
                raise RuntimeError(f"erro de leitura stdout do worker TRELLIS.2: {item}") from item
            if item.strip():
                return item

    def _enviar_comando(self, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        proc = self.active_proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("worker TRELLIS.2 indisponivel")
        proc.stdin.write(json.dumps(payload, sort_keys=True) + "\n")
        proc.stdin.flush()
        linha = self._ler_linha(timeout_s)
        try:
            resp = json.loads(linha)
        except ValueError as exc:
            raise RuntimeError(f"resposta JSON invalida do worker TRELLIS.2: {linha[:200]!r}") from exc
        if not isinstance(resp, dict):
            raise RuntimeError(f"resposta nao-objeto do worker TRELLIS.2: {type(resp).__name__}")
        return resp

    def shutdown(self, timeout_s: float = 5.0) -> None:
        """Encerra graciosamente o worker ativo (ou mata apos ``timeout_s``)."""
        with self._lock:
            self._last_launch = None
            proc = self.active_proc
            if proc is None:
                return
            if proc.poll() is None and proc.stdin is not None:
                try:
                    proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                    proc.stdin.flush()
                    proc.wait(timeout=max(0.1, float(timeout_s)))
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                    sys.stderr.write(f"[mesh_trellis_worker] aviso shutdown gracioso falhou ({exc}); matando\n")
            self._kill_proc()

    def ping(
        self, timeout_s: float = 15.0, *, venv_py: Path | None = None,
        worker_script: Path | None = None, env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Verifica saude do worker; recria uma vez se o processo morreu."""
        with self._lock:
            if venv_py is not None and worker_script is not None:
                env_eff = dict(os.environ if env is None else env)
                spec_key = _spec_chave(venv_py, worker_script, env_eff)
                if self.active_proc is not None and (self.active_proc.poll() is not None or self.worker_spec_key != spec_key):
                    self._kill_proc()
                if self.active_proc is None:
                    self._spawn(venv_py, worker_script, env_eff, None, spec_key)
            elif self.active_proc is None or self.active_proc.poll() is not None:
                self._kill_proc()
                if self._last_launch is None:
                    raise RuntimeError("worker TRELLIS.2 nao iniciado")
                vp, ws, ev = self._last_launch
                self._spawn(vp, ws, ev, None, _spec_chave(vp, ws, ev))

            for tentativa in range(2):
                try:
                    resp = self._enviar_comando({"cmd": "ping"}, timeout_s)
                    if not resp.get("ok"):
                        raise RuntimeError(f"worker TRELLIS.2 nao saudavel: {resp}")
                    return resp
                except (TimeoutError, RuntimeError):
                    self._kill_proc()
                    raise
                except (BrokenPipeError, EOFError, OSError) as exc:
                    self._kill_proc()
                    if tentativa == 0 and self._last_launch is not None:
                        vp, ws, ev = self._last_launch
                        self._spawn(vp, ws, ev, None, _spec_chave(vp, ws, ev))
                        continue
                    raise RuntimeError(f"worker TRELLIS.2 falhou no ping: {exc}") from exc
            raise RuntimeError("worker TRELLIS.2 falhou no ping")

    def infer(
        self, req: dict[str, Any], *, venv_py: Path, worker_script: Path, env: dict[str, str], timeout_s: int,
    ) -> dict[str, Any]:
        """Executa um job de inferencia no worker residente, reciclando quando necessario."""
        with self._lock:
            max_jobs = max_jobs_worker()
            spec_key, cfg_key = _spec_chave(venv_py, worker_script, env), _config_chave(req)
            if self.active_proc is not None:
                if self.active_proc.poll() is not None:
                    self._kill_proc()
                elif (
                    self.worker_spec_key != spec_key
                    or (self.config_chave is not None and self.config_chave != cfg_key)
                    or self.jobs_executados >= max_jobs
                ):
                    saved_launch = self._last_launch
                    self.shutdown()
                    self._last_launch = saved_launch

            if self.active_proc is None:
                self._spawn(venv_py, worker_script, env, cfg_key, spec_key)
            elif self.config_chave is None:
                self.config_chave = cfg_key

            base_res = Path(str(req.get("resultado") or (Path(str(req["saida_dir"])) / "i23d_resultado.json"))).resolve()
            req_path = base_res.with_name("_trellis2_req.json")
            req_path.parent.mkdir(parents=True, exist_ok=True)
            req_path.write_text(json.dumps(req, sort_keys=True, indent=1) + "\n", encoding="utf-8")

            try:
                resp = self._enviar_comando({"cmd": "infer", "req_path": str(req_path)}, float(timeout_s))
            except (TimeoutError, BrokenPipeError, EOFError, OSError, RuntimeError):
                self._kill_proc()
                raise

            self.jobs_executados += 1
            return resp


_CLIENT = Trellis2WorkerClient()


def executar_via_worker(
    req: dict[str, Any], *, venv_py: Path, worker_script: Path, env: dict[str, str], timeout_s: int
) -> dict[str, Any]:
    """Executa inferencia TRELLIS.2 usando o cliente residente singleton."""
    return _CLIENT.infer(req, venv_py=venv_py, worker_script=worker_script, env=env, timeout_s=timeout_s)


def encerrar_worker_trellis2() -> None:
    """Encerra o worker residente singleton de TRELLIS.2."""
    _CLIENT.shutdown()


atexit.register(encerrar_worker_trellis2)
