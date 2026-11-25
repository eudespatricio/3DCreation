"""Onda 9 (v0.9.12): overlap GPU/CPU, diagnostico de cache/plan e release.

Escrito so a partir do contrato (sem ler a implementacao): processos reais com workers falsos, nada do SUT e stubado.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import threading
import time
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import forge3d
from forge3d import cache, cache_diag, config, doctor, mcp_server, paths, pipeline, pipeline_item, plan, post, publish, qc, spec
from forge3d import gc as forge_gc
from forge3d.cli import parsers
from forge3d.cli.main import main
from forge3d.canonical import sha256_arquivo
from forge3d.errors import EXIT_QC, erro_bpy, erro_provider_run
from forge3d.providers import mesh, mesh_trellis
from tests.test_spec_v6_g11 import _cubo_fechado_glb

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


# ---------------------------------------------------------------- 3. overlap / pipelining
class _Rec:
    """Linha do tempo thread-safe compartilhada por provider falso, post falso e spies."""

    def __init__(self, ids, espera=10.0):
        self.ids, self.espera, self.lock, self.ev, self.envs = list(ids), espera, threading.Lock(), [], {}
        self.iniciou = {i: threading.Event() for i in ids}
        self.ativo = {"g": 0, "p": 0}
        self.maximo = {"g": 0, "p": 0}
        self.viu_overlap = None
        self.delay_g, self.delay_p, self.falha_g, self.falha_p = {}, {}, None, None

    def log(self, *x):
        with self.lock:
            self.ev.append(x)

    def entrar(self, k):
        with self.lock:
            self.ativo[k] += 1
            self.maximo[k] = max(self.maximo[k], self.ativo[k])

    def sair(self, k):
        with self.lock:
            self.ativo[k] -= 1

    def idx(self, *marca):
        return self.ev.index(marca)

    def ids_de(self, tipo):
        return [i for t, i in (e[:2] for e in self.ev) if t == tipo]


class _Prov(mesh.MeshProvider):
    nome, determinism, usa_gpu = "blocky", "D1", True  # versao herdada: depende do env, como no provider real
    licenca = {"modelo": "MIT", "uso_comercial": True, "notice": "stub"}

    def __init__(self, rec, gpu=True):
        super().__init__()
        self.rec, self.usa_gpu = rec, gpu

    def preflight(self):
        return True, "ok"

    def preflight_item(self, _item):
        return True, "ok"

    def custo(self, _item, _perfil):
        return {"segundos_estimados": 0.1, "vram_mb": 0}

    def gerar(self, item, _perfil, staging):
        rec, i = self.rec, item["id"]
        rec.entrar("g")
        try:
            rec.log("g0", i)
            rec.iniciou[i].set()
            time.sleep(rec.delay_g.get(i, 0.0))
            if rec.falha_g == i:
                raise erro_provider_run("gerar falhou (fake)", id=i)
            rec.log("g1", i)
        finally:
            rec.sair("g")
        return SimpleNamespace(dir=staging, meta={})


_AUS = object()


def _instalar(monkeypatch, rec, *, gpu=True, tris=None):
    monkeypatch.setattr(doctor, "exigir", lambda _c: None)
    prov = _Prov(rec, gpu)
    monkeypatch.setattr("forge3d.providers.obter", lambda _r: prov)

    def _post(job, **kw):
        i = job["nome_base"]
        rec.entrar("p")
        try:
            rec.log("p0", i)
            rec.envs[i] = (kw.get("env_extra", _AUS), os.environ.get("FORGE3D_CYCLES_DEVICE"))
            if i == rec.ids[0] and len(rec.ids) > 1:
                rec.viu_overlap = rec.iniciou[rec.ids[1]].wait(rec.espera)
            time.sleep(rec.delay_p.get(i, 0.0))
            if rec.falha_p == i:
                raise erro_bpy("post falhou (fake)")
            out = Path(job["saida_dir"])
            out.mkdir(parents=True, exist_ok=True)
            (out / job["nome_arquivo"]).write_bytes(_cubo_fechado_glb(1.0))
            rec.log("p1", i)
        finally:
            rec.sair("p")
        return {"ok": True, "arquivos": [{"caminho": job["nome_arquivo"], "papel": "mesh", "nivel": 0, "triangulos": 12}],
                "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0}}

    monkeypatch.setattr("forge3d.post.executar", _post)
    orig_qc, orig_g11, orig_pub = qc.verificar, qc.verificar_g11_orcamento_cena, publish.publicar

    def _verificar(item, perfil, pasta, resultado, **kw):
        rel = orig_qc(item, perfil, pasta, resultado, **kw)
        if tris:
            rel["medidas"]["triangulos"] = tris
        return rel

    def _g11(*a, **kw):
        rec.log("g11", "-")
        return orig_g11(*a, **kw)

    def _publicar(*a, **kw):
        rec.log("publicar", "-")
        return orig_pub(*a, **kw)

    monkeypatch.setattr(qc, "verificar", _verificar)
    monkeypatch.setattr(qc, "verificar_g11_orcamento_cena", _g11)
    monkeypatch.setattr(publish, "publicar", _publicar)


def _lote(tmp: Path, ids=("a.01",), *, prompt="um cubo", seed=1, g11=None, falha="continuar", qtd=None, qualidade=None) -> Path:
    doc: dict = {"schema": "forge3d/spec@6", "projeto": "t9", "perfil": "godot4-aa", "destino_exportacao": str(tmp / "saida"),
                 "politica": {"falha": falha}, "lote": []}
    for i in ids:
        it = {"id": i, "tipo": "prop_estatico", "rota": "blocky", "altura_metros": 1.0, "pivot": "base", "colisao": "none",
              "prompt": prompt, "seed": seed}
        it.update({k: v for k, v in (("quantidade_cena", qtd), ("qualidade", qualidade)) if v is not None})
        doc["lote"].append(it)
    if g11:
        doc["orcamento_cena"] = g11
    caminho = tmp / "lote.yaml"
    caminho.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return caminho


IDS3 = ("a.01", "a.02", "a.03")


def _atrasos(rec):
    rec.delay_g, rec.delay_p = {"a.02": 0.2}, {"a.01": 0.3, "a.02": 0.0, "a.03": 0.1}


@pytest.mark.parametrize(("overlap", "env_ov"), [(True, None), (None, None), (True, "0")])
def test_overlap_pipeline_sobrepoe_stage1_do_proximo_com_stage2_atual(tmp_path, monkeypatch, overlap, env_ov):
    if env_ov:
        monkeypatch.setenv("FORGE3D_OVERLAP", env_ov)
    rec = _Rec(IDS3)
    _atrasos(rec)
    _instalar(monkeypatch, rec)
    rel, codigo = pipeline.executar(_lote(tmp_path, IDS3), overlap=overlap)
    assert codigo == 0 and [i["id"] for i in rel["itens"]] == list(IDS3)  # ordem do spec, apesar dos atrasos
    assert all(i["estado"] == "publicado" for i in rel["itens"])
    assert rec.viu_overlap is True  # Stage 1 de a.02 comecou enquanto Stage 2 de a.01 ainda corria
    assert rec.idx("g0", "a.02") < rec.idx("p1", "a.01")
    assert rec.maximo["g"] == 1 and rec.maximo["p"] == 1  # I6: nunca 2 inferencias GPU / 2 pos-processos juntos
    assert all(env == ({"FORGE3D_CYCLES_DEVICE": "CPU"}, None) for env in rec.envs.values())  # os.environ intacto
    assert "FORGE3D_CYCLES_DEVICE" not in os.environ


def test_overlap_desligado_e_sequencial_sem_env_extra(tmp_path, monkeypatch):
    rec = _Rec(IDS3, espera=1.0)
    _instalar(monkeypatch, rec)
    rel, codigo = pipeline.executar(_lote(tmp_path, IDS3), overlap=False)
    assert codigo == 0 and rec.viu_overlap is False
    assert rec.idx("p1", "a.01") < rec.idx("g0", "a.02")
    assert all(env == (_AUS, None) for env in rec.envs.values())  # sem overlap nada de env_extra (compat com mocks antigos)
    assert [i["id"] for i in rel["itens"]] == list(IDS3)


def test_overlap_abortar_falha_no_stage2_para_de_agendar(tmp_path, monkeypatch):
    rec = _Rec(IDS3)
    rec.falha_p = "a.02"
    _instalar(monkeypatch, rec)
    rel, codigo = pipeline.executar(_lote(tmp_path, IDS3, falha="abortar"), overlap=True)
    estados = {i["id"]: i["estado"] for i in rel["itens"]}
    assert codigo != 0 and estados["a.02"] == "falhou" and estados.get("a.03") != "publicado"
    assert rec.ids_de("p0") == ["a.01", "a.02"] and "a.03" not in rec.ids_de("p1")


def test_overlap_abortar_falha_no_stage1_faz_flush_do_pendente(tmp_path, monkeypatch):
    rec = _Rec(IDS3)
    rec.falha_g = "a.02"
    _instalar(monkeypatch, rec)
    rel, codigo = pipeline.executar(_lote(tmp_path, IDS3, falha="abortar"), overlap=True)
    estados = {i["id"]: i["estado"] for i in rel["itens"]}
    assert codigo != 0 and estados == {"a.01": "publicado", "a.02": "falhou"}
    assert "a.03" not in rec.ids_de("g0") and rec.ids_de("p1") == ["a.01"]


def test_overlap_continuar_isola_falha_do_item(tmp_path, monkeypatch):
    rec = _Rec(IDS3)
    rec.falha_g = "a.02"
    _instalar(monkeypatch, rec)
    rel, codigo = pipeline.executar(_lote(tmp_path, IDS3, falha="continuar"), overlap=True)
    assert codigo != 0 and [(i["id"], i["estado"]) for i in rel["itens"]] == [
        ("a.01", "publicado"), ("a.02", "falhou"), ("a.03", "publicado")]


_G11_ALTO = {"triangulos_max": 400000, "draw_calls_max": 400, "vram_mb_max": 1000}


def test_overlap_g11_reprova_antes_de_publicar(tmp_path, monkeypatch):
    rec = _Rec(IDS3[:2])
    _instalar(monkeypatch, rec, tris=5000)
    destino = tmp_path / "saida"
    rel, codigo = pipeline.executar(_lote(tmp_path, IDS3[:2], g11=_G11_ALTO, qtd=100), overlap=True)  # 2 x 100 x 5000 > 400k
    assert codigo == EXIT_QC and rel["orcamento_cena"]["status"] == "falhou"
    assert "publicar" not in [e[0] for e in rec.ev] and rec.idx("p1", "a.02") < rec.idx("g11", "-")
    assert rel["artifacts"] == [] and (not destino.exists() or not list(destino.iterdir()))
    assert all(i["estado"] == "reprovado" and i["codigo"] == "FORGE-E-QC-SCENE" for i in rel["itens"])


def test_overlap_g11_aprovado_avalia_antes_de_qualquer_publish(tmp_path, monkeypatch):
    rec = _Rec(IDS3[:2])
    _instalar(monkeypatch, rec, tris=5000)
    rel, codigo = pipeline.executar(_lote(tmp_path, IDS3[:2], g11=_G11_ALTO, qtd=1), overlap=True)
    assert codigo == 0 and rel["orcamento_cena"]["status"] == "ok"
    marcas = [e[0] for e in rec.ev]
    assert marcas.count("g11") == 1 and marcas.count("publicar") == 2 and rec.idx("g11", "-") < rec.idx("publicar", "-")


def test_warm_worker_no_pipeline_liga_so_durante_o_run_e_encerra(tmp_path, monkeypatch):
    mw = importlib.import_module("forge3d.providers.mesh_trellis_worker")
    encerrados, vistos = [], []
    monkeypatch.setattr(mw, "encerrar_worker_trellis2", lambda: encerrados.append(1))
    rec = _Rec(("a.01",))
    _instalar(monkeypatch, rec)
    gerar = _Prov.gerar
    monkeypatch.setattr(_Prov, "gerar", lambda s, *a: (vistos.append(mesh_trellis.warm_worker_ativo()), gerar(s, *a))[1])
    pipeline.executar(_lote(tmp_path), warm_worker=True)
    assert vistos == [True] and mesh_trellis.warm_worker_ativo() is False and encerrados
    (tmp_path / "saida").mkdir(exist_ok=True)
    pipeline.executar(_lote(tmp_path, prompt="outro"), warm_worker=None)
    assert vistos == [True, False]


def test_overlap_ativo_regras(monkeypatch):
    ov = importlib.import_module("forge3d.pipeline_overlap")
    monkeypatch.setattr("forge3d.providers.obter", lambda rota: SimpleNamespace(usa_gpu=(rota == "mesh")))

    def t(rota="mesh", **kw):
        return {"id": "x", "rota": rota, "estado_previsto": "pronto", "cache_hit": False, **kw}

    gpu2, cpu2 = [t(), t()], [t("blocky"), t("blocky")]
    assert ov.overlap_ativo(gpu2) and not ov.overlap_ativo(cpu2) and not ov.overlap_ativo([t(), t("blocky")])  # auto: >=2 GPU
    assert not ov.overlap_ativo([t(), t(cache_hit=True)]) and not ov.overlap_ativo([t(), t(estado_previsto="bloqueada")])
    assert ov.overlap_ativo(cpu2, overlap=True) and not ov.overlap_ativo(cpu2[:1], overlap=True)
    assert not ov.overlap_ativo(gpu2 * 2, overlap=False)
    for val in ("1", "true", "sim", "on"):
        monkeypatch.setenv("FORGE3D_OVERLAP", val)
        assert ov.overlap_ativo(cpu2) and not ov.overlap_ativo(cpu2[:1])
    for val in ("0", "false", "nao", "off"):
        monkeypatch.setenv("FORGE3D_OVERLAP", val)
        assert not ov.overlap_ativo(gpu2)
        assert ov.overlap_ativo(gpu2, overlap=True)  # argumento explicito vence o env


def _chamar_post(monkeypatch, job_dir: Path, **kw) -> dict:
    visto: dict = {}

    def _run(cmd, **k):
        visto.update(k)
        Path(json.loads((job_dir / "_job.json").read_text())["saida_resultado"]).write_text(json.dumps({"ok": True, "arquivos": []}))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(post, "binario", lambda: "blender-falso")
    monkeypatch.setattr(post.subprocess, "run", _run)
    job = {"saida_dir": str(job_dir), "saida_resultado": str(job_dir / "resultado.json"), "item": {}}
    assert post.executar(job, **kw)["ok"] is True
    return visto


def test_post_executar_env_extra_so_no_subprocesso(tmp_path, monkeypatch):
    k = _chamar_post(monkeypatch, tmp_path / "j1", env_extra={"FORGE3D_CYCLES_DEVICE": "CPU"})
    assert k["env"]["FORGE3D_CYCLES_DEVICE"] == "CPU" and k["env"]["PATH"] == os.environ["PATH"]
    assert "FORGE3D_CYCLES_DEVICE" not in os.environ
    for vazio in (None, {}):
        assert _chamar_post(monkeypatch, tmp_path / "j2", env_extra=vazio).get("env") is None  # preserva mocks antigos


def test_aceita_kwarg_inspeciona_assinatura():
    ak = pipeline_item._aceita_kwarg

    def _quatro(a, b, c, d): ...
    def _com(a, b, c, d, *, env_extra=None): ...
    def _var(a, b, c, d, **kw): ...

    assert ak(_com, "env_extra") and ak(_var, "env_extra") and not ak(_quatro, "env_extra")
    assert not ak(None, "env_extra")  # nao inspecionavel (TypeError) -> False, sem excecao


@pytest.mark.parametrize("forma", ["quatro_args", "kwargs"])
def test_finalizar_item_cpu_respeita_assinatura_do_pos_processar(tmp_path, monkeypatch, forma):
    rec, chamadas = _Rec(("a.01",)), []
    _instalar(monkeypatch, rec)
    glb = _cubo_fechado_glb(1.0)

    def _corpo(item, bruto, run_id, kw):
        chamadas.append(kw)
        final = Path(bruto.dir).parent / "final"
        final.mkdir(parents=True, exist_ok=True)
        (final / f"{item['id']}.glb").write_bytes(glb)
        return {"ok": True, "dir_final": str(final), "arquivos": [{"caminho": f"{item['id']}.glb", "papel": "mesh", "nivel": 0, "triangulos": 12,
                      "sha256": sha256_arquivo(final / f"{item['id']}.glb"), "bytes": len(glb)}],
                "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0}}

    if forma == "quatro_args":
        monkeypatch.setattr(pipeline_item, "_pos_processar", lambda item, perfil, bruto, run_id: _corpo(item, bruto, run_id, {}))
    else:
        monkeypatch.setattr(pipeline_item, "_pos_processar", lambda item, perfil, bruto, run_id, **kw: _corpo(item, bruto, run_id, kw))
    sd, perfil = spec.preparar(spec.carregar_arquivo(_lote(tmp_path)))[:2]
    tarefa = plan.montar(sd, perfil, lambda _k: False)[0]
    item = sd["lote"][0]
    prep = pipeline_item.preparar_item_bruto(item, tarefa, perfil=perfil, run_id="r9")
    assert prep["cache_hit"] is False and prep["bruto"].dir.is_dir()
    saida = pipeline_item.finalizar_item_cpu(
        item, tarefa, prep, spec_doc=sd, perfil=perfil, spec_hash="h", destino=tmp_path / "saida", run_id="r9",
        publicar_arquivos=False, env_extra_post={"FORGE3D_CYCLES_DEVICE": "CPU"})  # pos_processar_fn=None: resolve em runtime
    assert saida["estado"] == "aprovado_nao_publicado" and len(chamadas) == 1  # monkeypatch visto + sem TypeError
    assert chamadas[0] == ({"env_extra": {"FORGE3D_CYCLES_DEVICE": "CPU"}} if forma == "kwargs" else {})
    assert cache.ler_cache(tarefa["chave"]) is not None


# ---------------------------------------------------------------- 4. cache / plan diagnostico
def _cachear(tmp_path, monkeypatch, **lote_kw) -> Path:
    rec = _Rec(("a.01",))
    _instalar(monkeypatch, rec)
    lote = _lote(tmp_path, **lote_kw)
    assert pipeline.executar(lote)[1] == 0
    return lote


def _diag(tmp_path, no_cache=False, **lote_kw) -> dict:
    sd, perfil = spec.preparar(spec.carregar_arquivo(_lote(tmp_path, **lote_kw)))[:2]
    return plan.montar(sd, perfil, lambda k: publish.ler_cache(k) is not None, no_cache=no_cache)[0]["cache_diagnostico"]


def test_primeiro_run_miss_sem_cache_anterior(tmp_path, monkeypatch):
    _instalar(monkeypatch, _Rec(("a.01",)))
    d = _diag(tmp_path)
    assert (d["status"], d["motivo"], d["campos_alterados"]) == ("miss", "sem_cache_anterior", [])
    assert cache.ler_ultimo_registro_item("a.01") is None


def test_hit_e_no_cache(tmp_path, monkeypatch):
    _cachear(tmp_path, monkeypatch)
    d = _diag(tmp_path)
    assert (d["status"], d["motivo"], d["campos_alterados"]) == ("hit", None, [])
    n = _diag(tmp_path, no_cache=True)
    assert (n["status"], n["motivo"]) == ("miss", "no_cache")


@pytest.mark.parametrize(("mutacao", "campo"), [({"prompt": "outro cubo"}, "item.prompt"), ({"seed": 2}, "item.seed")])
def test_miss_por_campo_do_item(tmp_path, monkeypatch, mutacao, campo):
    _cachear(tmp_path, monkeypatch)
    d = _diag(tmp_path, **mutacao)
    assert (d["status"], d["motivo"]) == ("miss", "campos_alterados") and campo in d["campos_alterados"]


def test_miss_por_env_rembg_e_steps_trellis(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_MODELO_MESH", "trellis2")
    monkeypatch.setenv("FORGE3D_REMBG_MODELO", "u2net")
    _cachear(tmp_path, monkeypatch)
    assert _diag(tmp_path)["status"] == "hit"
    monkeypatch.setenv("FORGE3D_REMBG_MODELO", "isnet-general-use")
    d = _diag(tmp_path)
    assert d["motivo"] == "campos_alterados" and "provider.rembg_mod" in d["campos_alterados"]
    monkeypatch.setenv("FORGE3D_REMBG_MODELO", "u2net")
    monkeypatch.setenv("FORGE3D_TRELLIS2_STEPS", "30")
    d = _diag(tmp_path)
    assert d["status"] == "miss" and {"provider.steps", "provider.steps_env"} & set(d["campos_alterados"])


def test_plan_json_cli_traz_cache_diagnostico(tmp_path, monkeypatch, capsys):
    lote = _cachear(tmp_path, monkeypatch)
    capsys.readouterr()
    assert main(["plan", str(lote), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["tarefas"][0]["cache_diagnostico"]["status"] == "hit"
    assert main(["plan", str(lote), "--json", "--no-cache"]) == 0
    assert json.loads(capsys.readouterr().out)["tarefas"][0]["cache_diagnostico"]["motivo"] == "no_cache"


def test_ler_ultimo_registro_item_devolve_o_mais_recente(tmp_path, monkeypatch):
    lote = _cachear(tmp_path, monkeypatch)
    sd, perfil = spec.preparar(spec.carregar_arquivo(lote))[:2]
    chave1 = plan.montar(sd, perfil, lambda _k: False)[0]["chave"]
    rec1 = cache.ler_ultimo_registro_item("a.01")
    assert isinstance(rec1, dict) and rec1["chave"] == chave1 and cache.ler_ultimo_registro_item("nao.existe") is None
    _cachear(tmp_path, monkeypatch, seed=7)
    assert cache.ler_ultimo_registro_item("a.01")["chave"] != chave1
    for ponteiro in (paths.dir_cache() / ".por_id").glob("*.json"):
        ponteiro.write_text("{corrompido", encoding="utf-8")
    assert cache.ler_ultimo_registro_item("a.01") is None  # JSON invalido nao explode


def test_gc_ignora_por_id_mesmo_velho(tmp_path, monkeypatch):
    _cachear(tmp_path, monkeypatch)
    raiz = paths.dir_cache()
    antigo = time.time() - 90 * 86400
    chaves = [p for p in raiz.iterdir() if not p.name.startswith(".")]
    for p in [raiz / ".por_id", *(raiz / ".por_id").iterdir(), *chaves]:
        os.utime(p, (antigo, antigo))
    rel = forge_gc.executar(30, aplicar=True)
    assert [a["caminho"] for a in rel["alvos"] if a["removido"]] == [str(c) for c in chaves]  # controle: cache velho sai
    assert not any(".por_id" in a["caminho"] for a in rel["alvos"])
    assert (raiz / ".por_id").is_dir() and cache.ler_ultimo_registro_item("a.01") is not None


# ---------------------------------------------------------------- 5. release 0.9.12 e higiene
def test_versoes_0_9_12_consistentes():
    assert forge3d.__version__ == forge3d.PIPELINE_VERSION == post.PIPELINE_VERSION == "0.9.13"
    assert tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"] == "0.9.13"


def test_cli_run_aceita_overlap_e_warm_worker():
    p = parsers.construir_parser()
    assert p.parse_args(["run", "lote.yaml"]).overlap is None and p.parse_args(["run", "lote.yaml"]).warm_worker is False
    assert p.parse_args(["run", "lote.yaml", "--overlap"]).overlap is True
    assert p.parse_args(["run", "lote.yaml", "--no-overlap"]).overlap is False
    assert p.parse_args(["run", "lote.yaml", "--warm-worker"]).warm_worker is True
    assert p.parse_args(["run", "l.yaml", "--overlap", "--warm-worker", "--no-cache"]).no_cache is True


def test_mcp_forge3d_run_expoe_overlap_e_warm_worker_opcionais():
    ferramenta = next(t for t in mcp_server.TOOLS if t["name"] == "forge3d_run")
    props = ferramenta["inputSchema"]["properties"]
    assert props["overlap"]["type"] == "boolean" and props["warm_worker"]["type"] == "boolean"
    assert ferramenta["inputSchema"]["required"] == ["lote"]


def test_aceita_kwarg_positional_only_e_cache_diag_provider_none():
    assert pipeline_item._aceita_kwarg(lambda env_extra, /: env_extra, "env_extra") is False
    mat = cache_diag.material_chave_cache(
        {"id": "p.01", "rota": "blocky", "tipo": "prop_estatico"}, "0.9.12", None, {}
    )
    assert mat["providers"] == {"blocky": ""} and mat["provider_campos"] == {}
