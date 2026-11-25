"""Onda 9 (v0.9.12): steps TRELLIS.2 por qualidade e warm worker (IPC offline com worker falso).

Escrito so a partir do contrato (sem ler a implementacao): processos reais com workers falsos, nada do SUT e stubado.
"""

from __future__ import annotations

import importlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from forge3d import config
from forge3d.errors import ForgeError
from forge3d.providers import mesh, mesh_trellis

RAIZ = Path(__file__).resolve().parents[1]
_ENV = (
    "FORGE3D_MODELO_MESH", "FORGE3D_I23D_DEVICE", "FORGE3D_TRELLIS2_DIR", "FORGE3D_TRELLIS2_SCRIPT", "FORGE3D_TRELLIS2_STEPS",
    "FORGE3D_TRELLIS2_QUANT", "FORGE3D_TRELLIS2_PIPELINE_TYPE", "FORGE3D_TRELLIS2_WARM_WORKER", "FORGE3D_TRELLIS2_WORKER_SCRIPT",
    "FORGE3D_TRELLIS2_WORKER_MAX_JOBS", "FORGE3D_OVERLAP", "FORGE3D_REMBG_MODELO", "FORGE3D_QUALIDADE", "FORGE3D_I23D_TIMEOUT",
    "FORGE3D_CYCLES_DEVICE", "FORGE3D_I23D_TRELLIS_MODEL", "FORGE3D_I23D_DECIMATION_TARGET", "FORGE3D_DELIGHT", "FAKE_WORKER_MODE",
)


@pytest.fixture(autouse=True)
def _ambiente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "cfg" / "config.yaml"))
    for var in _ENV:
        monkeypatch.delenv(var, raising=False)
    mesh_trellis._DIAGNOSTICO_TRELLIS2.clear()
    config.adicionar(tmp_path)


# ---------------------------------------------------------------- 1. steps por qualidade
@pytest.mark.parametrize(("item", "esperado"), [
    (None, 12), ({}, 12), ({"qualidade": "draft"}, 12), ({"qualidade": "standard"}, 12),
    ({"qualidade": "hero"}, 25), ({"qualidade": "ultra"}, 25), ({"qualidade": " HERO "}, 25),
])
def test_steps_default_por_qualidade(item, esperado):
    assert mesh_trellis.steps_trellis2(item) == esperado


def test_steps_env_vence_qualidade_e_bounds(monkeypatch):
    monkeypatch.setenv("FORGE3D_TRELLIS2_STEPS", "18")
    assert mesh_trellis.steps_trellis2() == 18 and mesh_trellis.steps_trellis2({"qualidade": "hero"}) == 18
    for ok in ("1", "200"):
        monkeypatch.setenv("FORGE3D_TRELLIS2_STEPS", ok)
        assert mesh_trellis.steps_trellis2() == int(ok)
    for ruim in ("0", "201", "-3", "abc"):
        monkeypatch.setenv("FORGE3D_TRELLIS2_STEPS", ruim)
        with pytest.raises(ValueError):
            mesh_trellis.steps_trellis2()
    monkeypatch.setenv("FORGE3D_TRELLIS2_STEPS", "   ")  # vazio = nao definido
    assert mesh_trellis.steps_trellis2({"qualidade": "hero"}) == 25


def test_cache_tag_distingue_unset_de_12_25_40(monkeypatch):
    tags = {"unset": mesh_trellis.cache_tag_trellis2()}
    for val in ("12", "25", "40"):
        monkeypatch.setenv("FORGE3D_TRELLIS2_STEPS", val)
        tags[val] = mesh_trellis.cache_tag_trellis2()
        assert tags[val] == mesh_trellis.cache_tag_trellis2()  # deterministico
    assert len(set(tags.values())) == 4 and all(t.startswith("tr2") for t in tags.values())


def test_custo_standard_menor_que_hero_sob_trellis(monkeypatch):
    monkeypatch.setenv("FORGE3D_MODELO_MESH", "trellis2")
    prov = mesh.MeshProvider()
    std, hero = prov._custo_i23d({"qualidade": "standard"}), prov._custo_i23d({"qualidade": "hero"})
    assert std["segundos_estimados"] == 200.0 and hero["segundos_estimados"] == 320.0
    com_origem = prov._custo_i23d({"qualidade": "standard", "origem": "x.png"})
    assert com_origem["segundos_estimados"] == 180.0 < prov._custo_i23d({"qualidade": "hero", "origem": "x.png"})["segundos_estimados"]
    assert std["vram_mb"] == hero["vram_mb"] == 4500


# ---------------------------------------------------------------- 2. warm worker (IPC offline)
_FAKE_WORKER = r'''
import json, os, sys, time
from pathlib import Path
proto, sys.stdout = sys.stdout, sys.stderr
jobs, cfg, mode = 0, None, os.environ.get("FAKE_WORKER_MODE", "ok")
def send(d): proto.write(json.dumps(d) + "\n"); proto.flush()
for linha in sys.stdin:
    msg = json.loads(linha)
    if msg["cmd"] == "ping":
        send({"ok": True, "pid": os.getpid(), "jobs": jobs, "config": cfg})
    elif msg["cmd"] == "shutdown":
        send({"ok": True, "bye": True}); break
    elif msg["cmd"] == "infer":
        req = json.loads(Path(msg["req_path"]).read_text())
        out = Path(req["saida_dir"]); out.mkdir(parents=True, exist_ok=True)
        (out / "worker.pid").write_text(str(os.getpid()))
        if mode == "crash": sys.stderr.write("fake worker morreu\n"); os._exit(3)
        if mode == "hang": time.sleep(300)
        jobs += 1; cfg = [req.get("quant"), req.get("pipeline_type"), bool(req.get("tiled_tex"))]
        ok = mode != "erro"
        if ok: (out / "modelo.glb").write_bytes(b"glTF" + b"\0" * 32)
        res = {"ok": ok, "modelo": req.get("modelo"), "pid": os.getpid(), "jobs": jobs, "via": "worker", "faces": 10,
               "texture_size": int(req.get("texture_size") or 0), "steps": req.get("steps")}
        if not ok: res["erro"] = "CUDA falhou (fake)"
        Path(req["resultado"]).write_text(json.dumps(res))
        send({"ok": ok, "resultado": req["resultado"], "jobs": jobs, "erro": None if ok else res["erro"]})
'''
_SHIM = r'''
import argparse, json, os
from pathlib import Path
p = argparse.ArgumentParser()
for f in ("--imagem", "--saida-dir", "--resultado", "--modelo", "--steps", "--quant", "--pipeline-type"):
    p.add_argument(f)
a, _ = p.parse_known_args()
Path(os.environ["SHIM_LOG"]).open("a").write("single\n")
out = Path(a.saida_dir); out.mkdir(parents=True, exist_ok=True)
(out / "modelo.glb").write_bytes(b"glTF" + b"\0" * 32)
Path(a.resultado).write_text(json.dumps({"ok": True, "modelo": a.modelo, "via": "single_shot", "pid": os.getpid(), "faces": 10}))
'''


def _instalar_trellis2(raiz: Path) -> dict[str, Path]:
    venv_py = raiz / "venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text(
        f"#!{sys.executable}\nimport os, sys\n"
        "if len(sys.argv) >= 3 and sys.argv[1] == '-c' and 'o_voxel' in sys.argv[2]:\n"
        "    print('{\"torch\": \"2.6\", \"cuda\": true}'); raise SystemExit(0)\n"
        "os.execv(sys.executable, [sys.executable, *sys.argv[1:]])\n", encoding="utf-8")
    venv_py.chmod(venv_py.stat().st_mode | stat.S_IXUSR)
    (raiz / "repo" / "trellis2_gguf").mkdir(parents=True)
    m = raiz / "models"
    base = [m / "Trellis2" / "pipeline.json", *(m / "Trellis2" / "decoders" / s / n for s, n in (
        ("Stage1", "ss_dec_conv3d_16l8_fp16.safetensors"), ("Stage2", "shape_dec_next_dc_f16c32_fp16.safetensors"),
        ("Stage2", "tex_dec_next_dc_f16c32_fp16.safetensors")))]
    for q in ("BF16", "Q8_0", "Q4_K_M"):
        ext = ".safetensors" if q == "BF16" else f"_{q}.gguf"
        base += [m / "Trellis2" / "refiner" / f"ss_flow_img_dit_1_3B_64_bf16{ext}"]
        for res in ("512", "1024"):
            base += [m / "Trellis2" / "shape" / f"slat_flow_img2shape_dit_1_3B_{res}_bf16{ext}",
                     m / "Trellis2" / "texture" / f"slat_flow_imgshape2tex_dit_1_3B_{res}_bf16{ext}"]
    for arq in base:
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_bytes(b"stub")
    (m / "facebook" / "dinov3-vitl16-pretrain-lvd1689m").mkdir(parents=True)
    return {"venv_py": venv_py, "models": m, "repo": raiz / "repo"}


@pytest.fixture()
def wk(tmp_path, monkeypatch):
    mod = importlib.import_module("forge3d.providers.mesh_trellis_worker")
    script, shim = tmp_path / "fake_worker.py", tmp_path / "shim_infer.py"
    script.write_text(_FAKE_WORKER, encoding="utf-8")
    shim.write_text(_SHIM, encoding="utf-8")
    info = _instalar_trellis2(tmp_path / "tr2")
    for k, v in {"FORGE3D_MODELO_MESH": "trellis2", "FORGE3D_TRELLIS2_DIR": str(tmp_path / "tr2"), "FORGE3D_TRELLIS2_SCRIPT": str(shim),
                 "FORGE3D_TRELLIS2_WORKER_SCRIPT": str(script), "FORGE3D_I23D_DEVICE": "cuda:0", "FORGE3D_DELIGHT": "0",
                 "SHIM_LOG": str(tmp_path / "shim.log"), "FORGE3D_I23D_TIMEOUT": "30"}.items():
        monkeypatch.setenv(k, v)
    yield SimpleNamespace(mod=mod, script=script, tmp=tmp_path, log=tmp_path / "shim.log", **info)
    mod.encerrar_worker_trellis2()


def _vivo(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _esperar_morte(pid: int, limite: float = 5.0) -> bool:
    fim = time.monotonic() + limite
    while _vivo(pid) and time.monotonic() < fim:
        time.sleep(0.05)
    return not _vivo(pid)


def _req(wk, n: int, **over) -> dict:
    out = wk.tmp / f"job{n}"
    out.mkdir(exist_ok=True)
    base = {"imagem": str(wk.tmp / "in.png"), "saida_dir": str(out), "resultado": str(out / "i23d_resultado.json"),
            "models_dir": str(wk.models), "repo_dir": str(wk.repo), "modelo": "microsoft/TRELLIS.2-4B", "seed": 1,
            "quant": "BF16", "pipeline_type": "512", "steps": 12, "shape_guidance": 7.5, "tex_guidance": 3.0,
            "texture_size": 1024, "decimation_target": 48000, "remesh_project": 0.9, "tiled_tex": False}
    return {**base, **over}


def _infer(wk, client, n: int, timeout_s: int = 30, **over) -> int:
    resp = client.infer(_req(wk, n, **over), venv_py=wk.venv_py, worker_script=wk.script, env=dict(os.environ), timeout_s=timeout_s)
    assert resp["ok"] is True
    return json.loads(Path(resp["resultado"]).read_text())["pid"]


@pytest.mark.parametrize(("env", "esperado"), [
    (None, False), ("", False), ("0", False), ("off", False), ("1", True), ("true", True), ("sim", True), ("on", True), (" TRUE ", True),
])
def test_warm_worker_ativo_env(monkeypatch, env, esperado):
    if env is not None:
        monkeypatch.setenv("FORGE3D_TRELLIS2_WARM_WORKER", env)
    assert mesh_trellis.warm_worker_ativo() is esperado


def test_usar_warm_worker_override_restaura(monkeypatch):
    assert mesh_trellis.warm_worker_ativo() is False
    with mesh_trellis.usar_warm_worker(True):
        assert mesh_trellis.warm_worker_ativo() is True
        with mesh_trellis.usar_warm_worker(False):
            assert mesh_trellis.warm_worker_ativo() is False
        assert mesh_trellis.warm_worker_ativo() is True
    assert mesh_trellis.warm_worker_ativo() is False
    monkeypatch.setenv("FORGE3D_TRELLIS2_WARM_WORKER", "1")
    with pytest.raises(RuntimeError, match="x"), mesh_trellis.usar_warm_worker(False):
        raise RuntimeError("x")
    assert mesh_trellis.warm_worker_ativo() is True  # restaura mesmo com excecao


def test_script_worker_resolve_repo_e_override(tmp_path, monkeypatch):
    alvo = mesh_trellis.script_trellis2_worker()
    assert alvo.name == "trellis2_worker.py" and alvo.is_file()
    outro = tmp_path / "meu_worker.py"
    monkeypatch.setenv("FORGE3D_TRELLIS2_WORKER_SCRIPT", str(outro))
    assert mesh_trellis.script_trellis2_worker() == outro.resolve()


def test_worker_real_help_sem_gpu():
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "PYTHONPATH": str(RAIZ / "src")}
    proc = subprocess.run([sys.executable, str(RAIZ / "tools" / "trellis2_worker.py"), "--help"], env=env,
                          capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0 and "usage" in proc.stdout.lower()


def test_max_jobs_worker_default_e_invalidos(monkeypatch):
    mod = importlib.import_module("forge3d.providers.mesh_trellis_worker")
    assert mod.max_jobs_worker() == 20
    monkeypatch.setenv("FORGE3D_TRELLIS2_WORKER_MAX_JOBS", "3")
    assert mod.max_jobs_worker() == 3
    for ruim in ("0", "-1", "abc"):
        monkeypatch.setenv("FORGE3D_TRELLIS2_WORKER_MAX_JOBS", ruim)
        with pytest.raises(ValueError):
            mod.max_jobs_worker()


def test_client_reusa_pid_e_ping(wk):
    client = wk.mod.Trellis2WorkerClient()
    pids = [_infer(wk, client, n) for n in range(3)]
    assert len(set(pids)) == 1 and _vivo(pids[0])
    pong = client.ping()
    assert pong["ok"] is True and pong["pid"] == pids[0] and pong["jobs"] == 3 and "config" in pong
    client.shutdown()
    assert _esperar_morte(pids[0])


def test_client_worker_morto_recupera_no_proximo_infer(wk):
    client = wk.mod.Trellis2WorkerClient()
    pid = _infer(wk, client, 0)
    os.kill(pid, 9)
    assert _esperar_morte(pid)
    novo = _infer(wk, client, 1)
    assert novo != pid and _vivo(novo)
    client.shutdown()


def test_client_recicla_apos_max_jobs(wk, monkeypatch):
    monkeypatch.setenv("FORGE3D_TRELLIS2_WORKER_MAX_JOBS", "2")
    client = wk.mod.Trellis2WorkerClient()
    pids = [_infer(wk, client, n) for n in range(5)]
    assert pids[0] == pids[1] and pids[2] == pids[3] and len({pids[0], pids[2], pids[4]}) == 3
    assert _esperar_morte(pids[0]) and _esperar_morte(pids[2])  # reciclados de verdade, sem zumbi
    client.shutdown()


@pytest.mark.parametrize("mudanca", [{"quant": "Q8_0"}, {"pipeline_type": "1024_cascade"}, {"tiled_tex": True}])
def test_client_recicla_quando_config_muda(wk, mudanca):
    client = wk.mod.Trellis2WorkerClient()
    a, b = _infer(wk, client, 0), _infer(wk, client, 1, **mudanca)
    c = _infer(wk, client, 2, **mudanca)
    assert a != b and b == c  # muda uma vez e estabiliza
    assert _esperar_morte(a)
    client.shutdown()


def test_client_timeout_mata_worker_sem_travar(wk, monkeypatch):
    monkeypatch.setenv("FAKE_WORKER_MODE", "hang")
    client = wk.mod.Trellis2WorkerClient()
    t0 = time.monotonic()
    with pytest.raises((TimeoutError, ForgeError)):
        client.infer(_req(wk, 0), venv_py=wk.venv_py, worker_script=wk.script, env=dict(os.environ), timeout_s=1)
    assert time.monotonic() - t0 < 20
    assert _esperar_morte(int((wk.tmp / "job0" / "worker.pid").read_text()))


def _local(wk, n: int, **item):
    img = wk.tmp / "in.png"
    if not img.exists():
        im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        im.putpixel((8, 8), (220, 40, 40, 255))
        im.save(img)
    return mesh_trellis.executar_i23d_trellis2_local({"id": f"i{n}", **item}, wk.tmp / f"out{n}", img, dict(os.environ))


def test_local_warm_reusa_worker_e_recicla_por_config(wk, monkeypatch):
    monkeypatch.setenv("FORGE3D_TRELLIS2_WARM_WORKER", "1")
    r0, r1 = _local(wk, 0), _local(wk, 1, qualidade="hero")
    assert r0["via"] == r1["via"] == "worker" and r0["pid"] == r1["pid"] and r0["jobs"] == 1 and r1["jobs"] == 2
    assert (r0["steps"], r1["steps"]) == (12, 25) and not wk.log.exists()
    monkeypatch.setenv("FORGE3D_TRELLIS2_QUANT", "Q8_0")
    r2 = _local(wk, 2)
    assert r2["pid"] != r1["pid"] and r2["jobs"] == 1


def test_local_sem_warm_usa_single_shot(wk):
    assert _local(wk, 0)["via"] == "single_shot" and wk.log.read_text() == "single\n"


def test_local_crash_do_worker_avisa_stderr_e_cai_uma_vez(wk, monkeypatch, capsys):
    monkeypatch.setenv("FORGE3D_TRELLIS2_WARM_WORKER", "1")
    monkeypatch.setenv("FAKE_WORKER_MODE", "crash")
    res = _local(wk, 0)
    err = capsys.readouterr().err.lower()
    assert res["via"] == "single_shot" and wk.log.read_text() == "single\n"  # exatamente 1 fallback
    assert any(p in err for p in ("worker", "aviso", "warn"))
    assert _esperar_morte(int((wk.tmp / "out0" / "worker.pid").read_text()))


def test_local_erro_de_inferencia_nao_faz_fallback(wk, monkeypatch):
    monkeypatch.setenv("FORGE3D_TRELLIS2_WARM_WORKER", "1")
    monkeypatch.setenv("FAKE_WORKER_MODE", "erro")
    with pytest.raises(ForgeError) as exc:
        _local(wk, 0)
    assert exc.value.codigo == "FORGE-E-PROVIDER-RUN" and "CUDA falhou" in exc.value.mensagem
    assert not wk.log.exists()
    assert json.loads((wk.tmp / "out0" / "i23d_resultado.json").read_text())["ok"] is False


def test_local_timeout_vira_forgeerror_sem_fallback(wk, monkeypatch):
    monkeypatch.setenv("FORGE3D_TRELLIS2_WARM_WORKER", "1")
    monkeypatch.setenv("FAKE_WORKER_MODE", "hang")
    monkeypatch.setenv("FORGE3D_I23D_TIMEOUT", "1")
    t0 = time.monotonic()
    with pytest.raises(ForgeError) as exc:
        _local(wk, 0)
    assert "timeout" in exc.value.mensagem.lower() and time.monotonic() - t0 < 20 and not wk.log.exists()
    assert _esperar_morte(int((wk.tmp / "out0" / "worker.pid").read_text()))


def test_encerrar_worker_termina_filho_e_e_idempotente(wk, monkeypatch):
    monkeypatch.setenv("FORGE3D_TRELLIS2_WARM_WORKER", "1")
    pid = _local(wk, 0)["pid"]
    assert _vivo(pid)
    wk.mod.encerrar_worker_trellis2()
    assert _esperar_morte(pid)
    wk.mod.encerrar_worker_trellis2()  # sem worker: no-op
    assert _local(wk, 1)["pid"] != pid  # e o singleton sobe de novo sob demanda


def test_ping_timeout_levanta_timeouterror_direto(wk):
    hang_ping = wk.tmp / "hang_ping.py"
    hang_ping.write_text("import sys, time\nsys.stdin.readline()\ntime.sleep(30)\n", encoding="utf-8")
    c = wk.mod.Trellis2WorkerClient()
    try:
        with pytest.raises(TimeoutError):
            c.ping(timeout_s=0.1, venv_py=wk.venv_py, worker_script=hang_ping, env={})
    finally:
        c.shutdown()


