"""Testes do estagio concept, ControlNet pose, negativo, CLIP e proveniencia (sem GPU)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from forge3d import publish, spec
from forge3d.providers import LICENCAS, concept
from forge3d.providers.concept import (
    CONTROLNET_MODELO_PADRAO,
    ConceptProvider,
    combinar_prompt,
    estimar_tokens_clip,
    montar_comando,
    negativo_efetivo,
    resolver_pose,
)
from forge3d.providers.mesh import MeshProvider

RAIZ = Path(__file__).resolve().parents[1]


def test_sd15_e_openpose_estao_na_allowlist_comercial():
    assert "sd15" in LICENCAS
    assert LICENCAS["sd15"]["uso_comercial"] is True
    assert "OpenRAIL" in LICENCAS["sd15"]["notice"]
    assert "sd15_openpose" in LICENCAS
    assert LICENCAS["sd15_openpose"]["uso_comercial"] is True
    assert "CreativeML OpenRAIL-M" in LICENCAS["sd15_openpose"]["notice"]


def test_concept_preflight_sem_venv_da_razao_acionavel(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE3D_VENV_CONCEPT", str(tmp_path / "sem-venv"))
    pronto, razao = ConceptProvider().preflight()
    assert pronto is False
    assert "venv" in razao.lower(), razao


def test_mesh_com_origem_nao_checa_concept(monkeypatch):
    monkeypatch.setattr(MeshProvider, "preflight", lambda self: (True, "mesh ok"))

    def nao_deveria(self):
        raise AssertionError("concept nao deveria ser checado quando ha origem")

    monkeypatch.setattr(ConceptProvider, "preflight", nao_deveria)
    pronto, razao = MeshProvider().preflight_item({"origem": "concept.png"})
    assert pronto is True
    assert razao == "mesh ok"


def test_mesh_sem_origem_checa_concept(monkeypatch):
    monkeypatch.setattr(MeshProvider, "preflight", lambda self: (True, "mesh ok"))
    monkeypatch.setattr(
        ConceptProvider, "preflight", lambda self: (False, "P3.5: venv ausente")
    )
    pronto, razao = MeshProvider().preflight_item({"prompt": "corpo", "seed": 1})
    assert pronto is False
    assert "P3.5" in razao


def test_manifesto_grava_providers_texture_e_licenca_combinada():
    resultado = {
        "arquivos": [
            {
                "caminho": "a.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 1,
                "sha256": "sha256:" + "0" * 64,
                "bytes": 10,
            }
        ],
        "concept": {
            "modelo": "stable-diffusion-v1-5/stable-diffusion-v1-5",
            "versao": "0.1.0",
            "revisao": "451f4fe16113bff5a5d2269ed5ad43b0592e9a14",
            "seed": 7,
            "licenca": {
                "modelo": "Stable Diffusion 1.5",
                "uso_comercial": True,
                "notice": "Stable Diffusion 1.5 sob CreativeML OpenRAIL-M.",
            },
        },
    }
    relatorio = {
        "aprovado": True,
        "gates": [{"id": "G1", "status": "ok"}],
        "medidas": {
            "triangulos": 1,
            "vertices": 1,
            "bbox_m": [0.1, 0.1, 0.1],
            "materiais": 1,
            "ossos": 0,
            "partes_colisao": 0,
        },
    }
    manifesto = publish.montar_manifesto(
        item={"id": "a.b", "rota": "mesh", "seed": 7},
        spec_doc={"projeto": "demo", "perfil": "godot4", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4",
        provider={"nome": "mesh", "versao": "x", "determinism": "D2"},
        resultado=resultado,
        relatorio_qc=relatorio,
        licenca={"modelo": "TripoSR", "uso_comercial": True, "notice": "TripoSR (MIT)."},
        run_id="run-teste",
    )
    textura = manifesto["providers"]["texture"]
    assert textura["name"] == "concept/stable-diffusion-v1-5"
    assert textura["version"].startswith("0.1.0+451f4fe")
    assert textura["seed"] == 7
    assert "Concept:" in manifesto["licenca"]["notice"]
    assert "OpenRAIL" in manifesto["licenca"]["notice"]


def test_manifesto_sem_concept_nao_cria_provider_texture():
    resultado = {
        "arquivos": [
            {
                "caminho": "a.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 1,
                "sha256": "sha256:" + "0" * 64,
                "bytes": 10,
            }
        ]
    }
    relatorio = {
        "aprovado": True,
        "gates": [{"id": "G1", "status": "ok"}],
        "medidas": {
            "triangulos": 1,
            "vertices": 1,
            "bbox_m": [0.1, 0.1, 0.1],
            "materiais": 1,
            "ossos": 0,
            "partes_colisao": 0,
        },
    }
    manifesto = publish.montar_manifesto(
        item={"id": "a.b", "rota": "mesh", "seed": 7},
        spec_doc={"projeto": "demo", "perfil": "godot4", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4",
        provider={"nome": "mesh", "versao": "x", "determinism": "D2"},
        resultado=resultado,
        relatorio_qc=relatorio,
        licenca={"modelo": "TripoSR", "uso_comercial": True, "notice": "TripoSR (MIT)."},
        run_id="run-teste",
    )
    assert "texture" not in manifesto["providers"]
    assert "Concept:" not in manifesto["licenca"]["notice"]


def test_combinar_prompt_respeita_limite_clip_e_preserva_prompt_intacto():
    curto = combinar_prompt("medieval iron sword", concept.SUFIXO_PADRAO)
    assert curto.startswith("medieval iron sword, ")
    assert "isolated object" in curto
    assert "high detail" in curto

    # Prompt longo (~62 tokens): o prompt inteiro permanece e so cabem os primeiros trechos do sufixo
    palavras = " ".join(["iron"] * 60)
    mesclado = combinar_prompt(palavras, concept.SUFIXO_PADRAO, limite_tokens=77)
    assert mesclado.startswith(palavras)
    assert estimar_tokens_clip(mesclado) <= 77
    assert "isolated object" in mesclado
    assert "high detail" not in mesclado

    # Prompt no limite: nenhum sufixo adicionado, prompt intacto
    muito_longo = " ".join(["iron"] * 75)
    assert combinar_prompt(muito_longo, concept.SUFIXO_PADRAO, limite_tokens=77) == muito_longo


def test_negativo_por_item_env_e_meta_sem_quebrar_spec(monkeypatch):
    item = {"id": "personagem.capa.01", "tipo": "personagem_humanoide", "prompt": "empty cloak"}
    monkeypatch.setenv("FORGE3D_CONCEPT_NEGATIVO_PERSONAGEM_CAPA_01", "human, face, blurry")
    neg = negativo_efetivo(item)
    assert "human" in neg and "face" in neg
    assert neg.lower().count("blurry") == 1

    # Meta / campo direto no dicionario tambem funciona
    neg_meta = negativo_efetivo(
        {"id": "x.y", "meta": {"negativo": "helmet, cape"}}
    )
    assert "helmet" in neg_meta and "cape" in neg_meta

    # spec@1..@3 continua validando lotes normalmente (sem exigir campo negativo no YAML)
    doc = {
        "schema": "forge3d/spec@3",
        "projeto": "demo",
        "perfil": "godot4",
        "destino_exportacao": "~/.local/state/forge3d/saida/x",
        "lote": [
            {
                "id": "personagem.capa.01",
                "tipo": "personagem_humanoide",
                "rota": "mesh",
                "prompt": "empty cloak",
                "altura_metros": 1.2,
                "seed": 7,
            }
        ],
    }
    spec_doc, _perfil, _avisos = spec.preparar(doc)
    assert spec_doc["lote"][0]["id"] == "personagem.capa.01"


def test_resolver_pose_e_montar_comando_controlnet(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.delenv("FORGE3D_CONCEPT_CONTROLNET_MODELO", raising=False)
    monkeypatch.delenv("FORGE3D_CONCEPT_CONTROLNET_SCALE", raising=False)

    humanoide = {
        "id": "personagem.guarda.01",
        "tipo": "personagem_humanoide",
        "prompt": "robot guard",
        "seed": 42,
    }
    prop = {
        "id": "prop.caixa.01",
        "tipo": "prop_estatico",
        "prompt": "wooden crate",
        "seed": 42,
    }

    monkeypatch.setenv("FORGE3D_CONCEPT_POSE", "")
    assert resolver_pose(humanoide) == ""
    cmd_sem, info_sem = montar_comando(humanoide, tmp_path)
    assert "--controlnet" not in cmd_sem
    assert info_sem["pose"] == ""

    # auto sem cache local nao ativa ControlNet
    monkeypatch.setenv("FORGE3D_CONCEPT_POSE", "auto")
    assert resolver_pose(humanoide) == ""

    # auto com cache local ativa tpose apenas para personagem_humanoide
    cache_cn = (
        tmp_path / "hf" / "hub" / ("models--" + CONTROLNET_MODELO_PADRAO.replace("/", "--"))
    )
    cache_cn.mkdir(parents=True)
    assert resolver_pose(humanoide) == "tpose"
    assert resolver_pose(prop) == ""

    cmd_auto, info_auto = montar_comando(humanoide, tmp_path)
    assert "--controlnet" in cmd_auto
    assert cmd_auto[cmd_auto.index("--controlnet") + 1] == CONTROLNET_MODELO_PADRAO
    assert cmd_auto[cmd_auto.index("--pose-imagem") + 1] == str(tmp_path / "pose_tpose.png")
    assert cmd_auto[cmd_auto.index("--controlnet-scale") + 1] == "0.85"
    assert info_auto["pose"] == "tpose"

    # Explicito apose + modelo/scale customizados
    monkeypatch.setenv("FORGE3D_CONCEPT_POSE", "apose")
    monkeypatch.setenv("FORGE3D_CONCEPT_CONTROLNET_MODELO", "custom/openpose")
    monkeypatch.setenv("FORGE3D_CONCEPT_CONTROLNET_SCALE", "0.7")
    cmd_apose, info_apose = montar_comando(prop, tmp_path)
    assert cmd_apose[cmd_apose.index("--controlnet") + 1] == "custom/openpose"
    assert cmd_apose[cmd_apose.index("--pose-imagem") + 1] == str(tmp_path / "pose_apose.png")
    assert cmd_apose[cmd_apose.index("--controlnet-scale") + 1] == "0.7"
    assert info_apose["pose"] == "apose"


def test_preflight_explicito_sem_pesos_controlnet_falha(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("FORGE3D_CONCEPT_POSE", "tpose")
    monkeypatch.setattr(concept, "_diagnostico", lambda: {"ok": True, "diffusers": "0.31.0"})
    monkeypatch.setattr(concept, "_vram_livre_mb", lambda: 6000)
    (tmp_path / "hf" / "hub" / "models--stable-diffusion-v1-5--stable-diffusion-v1-5").mkdir(
        parents=True
    )

    pronto, razao = concept.preflight()
    assert pronto is False
    assert "ControlNet" in razao


def test_concept_gerar_gera_pose_png_e_grava_meta_com_mock(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE3D_CONCEPT_POSE", "tpose")
    monkeypatch.setenv("FORGE3D_CONCEPT_NEGATIVO_CHAR_01", "extra arms")
    monkeypatch.setattr(concept, "preflight", lambda: (True, "pronto"))

    capturado: dict = {}

    def fake_run(comando, capture_output=True, text=True, timeout=None, env=None, **_kwargs):
        capturado["comando"] = comando
        saida = Path(comando[comando.index("--saida") + 1])
        res_path = Path(comando[comando.index("--resultado") + 1])
        Image.new("RGB", (64, 64), (200, 200, 200)).save(saida)
        res_path.write_text(
            json.dumps(
                {
                    "ok": True,
                    "modelo": comando[comando.index("--modelo") + 1],
                    "seed": 11,
                    "png": str(saida),
                    "png_bytes": saida.stat().st_size,
                    "png_sha256": "sha256:" + "a" * 64,
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(concept.subprocess, "run", fake_run)
    destino = tmp_path / "stage"
    res = ConceptProvider().gerar(
        {"id": "char.01", "tipo": "personagem_humanoide", "prompt": "sentinel robot", "seed": 11},
        destino,
    )
    assert res["png"].is_file()
    assert (destino / "pose_tpose.png").is_file()
    assert "--controlnet" in capturado["comando"]
    assert res["meta"]["pose"] == "tpose"
    assert res["meta"]["controlnet"] == CONTROLNET_MODELO_PADRAO
    assert "extra arms" in res["meta"]["negativo"]
    assert "OpenPose" in res["meta"]["licenca"]["notice"]


def test_concept_infer_controlnet_cpu_mock(monkeypatch, tmp_path):
    spec_mod = importlib.util.spec_from_file_location(
        "concept_infer_test", RAIZ / "tools" / "concept_infer.py"
    )
    assert spec_mod is not None and spec_mod.loader is not None
    mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(mod)

    pose_img = tmp_path / "pose.png"
    Image.new("RGB", (64, 64), (0, 0, 0)).save(pose_img)
    saida = tmp_path / "out.png"
    res_json = tmp_path / "res.json"

    chamadas: dict = {"vae_dtypes": [], "decode_dtypes": []}

    class _FakeTensor:
        def __init__(self, dtype="float16"):
            self.dtype = dtype

        def to(self, dtype=None):
            return _FakeTensor(dtype=dtype)

    class _FakeVae:
        def to(self, dtype=None):
            chamadas["vae_dtypes"].append(dtype)

        def decode(self, z, *args, **kwargs):
            chamadas["decode_dtypes"].append(getattr(z, "dtype", None))
            return [z]

    class _FakeTokenizer:
        eos_token_id = 2

        def __call__(self, txt, truncation=False, add_special_tokens=True):
            return {"input_ids": [1, 2, 3]}

        def decode(self, ids, skip_special_tokens=True):
            return "robot"

    class _FakePipe:
        def __init__(self):
            self.tokenizer = _FakeTokenizer()
            self.vae = _FakeVae()
            self.unet = SimpleNamespace(config=SimpleNamespace(_name_or_path="snap/abc"))

        def set_progress_bar_config(self, disable=True):
            return None

        def enable_attention_slicing(self):
            chamadas["attn_slicing"] = True

        def enable_vae_slicing(self):
            chamadas["vae_slicing"] = True

        def enable_model_cpu_offload(self):
            chamadas["cpu_offload"] = True

        def to(self, device):
            chamadas["pipe_to"] = device

        def __call__(self, **kwargs):
            chamadas["call_kwargs"] = kwargs
            # Simula latents fp16 passando pelo vae.decode
            self.vae.decode(_FakeTensor("float16"))
            return SimpleNamespace(images=[Image.new("RGB", (64, 64), (100, 100, 100))])

    fake_torch = SimpleNamespace(
        float16="float16",
        float32="float32",
        cuda=SimpleNamespace(
            is_available=lambda: True,
            reset_peak_memory_stats=lambda: None,
            max_memory_allocated=lambda: 1024 * 1024,
            max_memory_reserved=lambda: 2 * 1024 * 1024,
            empty_cache=lambda: chamadas.setdefault("empty_cache", 0)
            or chamadas.__setitem__("empty_cache", chamadas["empty_cache"] + 1),
            mem_get_info=lambda: (4000 * 1024 * 1024, 6000 * 1024 * 1024),
        ),
        backends=SimpleNamespace(cudnn=SimpleNamespace(deterministic=False, benchmark=True)),
        manual_seed=lambda s: None,
        Generator=lambda device=None: SimpleNamespace(manual_seed=lambda s: f"gen-{s}"),
    )

    class _FakeControlNet:
        @classmethod
        def from_pretrained(cls, *a, **kw):
            return "fake-cn"

    class _FakeCNPipe:
        @classmethod
        def from_pretrained(cls, *a, **kw):
            chamadas["cn_pipe_kw"] = kw
            return _FakePipe()

    fake_diffusers = SimpleNamespace(
        StableDiffusionPipeline=_FakeCNPipe,
        ControlNetModel=_FakeControlNet,
        StableDiffusionControlNetPipeline=_FakeCNPipe,
    )

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "concept_infer.py",
            "--prompt",
            "robot",
            "--saida",
            str(saida),
            "--resultado",
            str(res_json),
            "--largura",
            "64",
            "--altura",
            "64",
            "--controlnet",
            CONTROLNET_MODELO_PADRAO,
            "--pose-imagem",
            str(pose_img),
            "--controlnet-scale",
            "0.8",
            "--device",
            "cuda",
        ],
    )
    rc = mod.main()
    assert rc == 0
    dados = json.loads(res_json.read_text(encoding="utf-8"))
    assert dados["ok"] is True
    assert dados["controlnet"] == CONTROLNET_MODELO_PADRAO
    assert chamadas["vae_dtypes"] == ["float32"]
    assert chamadas["decode_dtypes"] == ["float32"]
    assert chamadas["attn_slicing"] is True
    assert chamadas["vae_slicing"] is True
    assert chamadas["cpu_offload"] is True
    assert chamadas["empty_cache"] == 1
    assert chamadas["call_kwargs"]["controlnet_conditioning_scale"] == 0.8
    assert isinstance(chamadas["call_kwargs"]["image"], Image.Image)
