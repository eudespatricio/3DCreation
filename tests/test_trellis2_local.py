"""Testes hermeticos do contrato de integracao local TRELLIS.2-4B (MIT, D6/D18/I9)."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest
from PIL import Image

from forge3d.errors import ForgeError
from forge3d.providers import mesh, mesh_diag, mesh_i23d, mesh_trellis

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT_INFER = RAIZ / "tools" / "trellis2_infer.py"
_BLENDER_BIN = os.environ.get("FORGE3D_BLENDER") or shutil.which("blender") or str(Path.home() / ".local" / "bin" / "blender")
_FORBIDDEN = ("FORGE3D_I23D_ENDPOINT", "FORGE3D_I23D_REQUIRE_REMOTE", "trellis_remoto", "colab_trellis")
_ENV_LIMPAR = (
    "FORGE3D_MODELO_MESH", "FORGE3D_I23D_DEVICE", "FORGE3D_DEVICE",
    "FORGE3D_TRIPOSR", "FORGE3D_I23D_SCRIPT", "FORGE3D_VENV_I23D", "FORGE3D_MODELOS",
    "FORGE3D_TRELLIS2_DIR", "FORGE3D_VENV_TRELLIS2", "FORGE3D_TRELLIS2_REPO",
    "FORGE3D_TRELLIS2_MODELS", "FORGE3D_TRELLIS2_SCRIPT", "FORGE3D_I23D_TRELLIS_MODEL",
    "FORGE3D_TRELLIS2_QUANT", "FORGE3D_TRELLIS2_PIPELINE_TYPE", "FORGE3D_TRELLIS2_STEPS",
    "FORGE3D_TRELLIS2_SHAPE_GUIDANCE", "FORGE3D_TRELLIS2_TEX_GUIDANCE",
    "FORGE3D_TRELLIS2_REMESH_PROJECT", "FORGE3D_I23D_DECIMATION_TARGET",
    "FORGE3D_TEX_PX", "FORGE3D_DELIGHT", "FORGE3D_VRAM_MINIMA_MB", "FORGE3D_I23D_TIMEOUT",
)


@pytest.fixture(autouse=True)
def _isolar_ambiente(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    for var in _ENV_LIMPAR:
        monkeypatch.delenv(var, raising=False)
    mesh_trellis._DIAGNOSTICO_TRELLIS2.clear()
    mesh_diag._DIAGNOSTICO.clear()
    monkeypatch.setattr(mesh, "_vram_livre_mb", lambda: 8192)
    return fake_home


def _escrever_png(caminho: Path, rgba: bool = True) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0)) if rgba else Image.new("RGB", (16, 16), (120, 140, 160))
    if rgba:
        img.putpixel((8, 8), (220, 40, 40, 255))
    img.save(caminho, format="PNG")
    return caminho


def _instalar_trellis2_fake(
    raiz: Path, *, quant: str = "BF16", pipe_type: str = "512", cuda_ok: bool = True, com_cuda_lib: bool = False
) -> dict[str, Path]:
    venv_py = raiz / "venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True, exist_ok=True)
    venv_py.write_text(
        f"#!{sys.executable}\n"
        "import json, subprocess, sys\n"
        "if len(sys.argv) >= 3 and sys.argv[1] == '-c' and 'o_voxel' in sys.argv[2]:\n"
        f"    print(json.dumps({{'torch': '2.6.0+cu128', 'cuda': {cuda_ok!r}}}))\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(subprocess.call([sys.executable, *sys.argv[1:]]))\n",
        encoding="utf-8",
    )
    venv_py.chmod(venv_py.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    repo_pkg = raiz / "repo" / "trellis2_gguf"
    repo_pkg.mkdir(parents=True, exist_ok=True)

    models_dir = raiz / "models"
    ext = ".safetensors" if quant == "BF16" else f"_{quant}.gguf"
    pesos = [
        models_dir / "Trellis2" / "pipeline.json",
        models_dir / "Trellis2" / "decoders" / "Stage1" / "ss_dec_conv3d_16l8_fp16.safetensors",
        models_dir / "Trellis2" / "decoders" / "Stage2" / "shape_dec_next_dc_f16c32_fp16.safetensors",
        models_dir / "Trellis2" / "decoders" / "Stage2" / "tex_dec_next_dc_f16c32_fp16.safetensors",
        models_dir / "Trellis2" / "refiner" / f"ss_flow_img_dit_1_3B_64_bf16{ext}",
        models_dir / "Trellis2" / "shape" / f"slat_flow_img2shape_dit_1_3B_512_bf16{ext}",
        models_dir / "Trellis2" / "texture" / f"slat_flow_imgshape2tex_dit_1_3B_512_bf16{ext}",
    ]
    if pipe_type == "1024_cascade":
        pesos += [
            models_dir / "Trellis2" / "shape" / f"slat_flow_img2shape_dit_1_3B_1024_bf16{ext}",
            models_dir / "Trellis2" / "texture" / f"slat_flow_imgshape2tex_dit_1_3B_1024_bf16{ext}",
        ]
    for arq in pesos:
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_bytes(b"stub")

    dinov3 = models_dir / "facebook" / "dinov3-vitl16-pretrain-lvd1689m"
    dinov3.mkdir(parents=True, exist_ok=True)
    cuda_lib = raiz / "cuda128" / "lib"
    if com_cuda_lib:
        cuda_lib.mkdir(parents=True, exist_ok=True)
    return {"venv_py": venv_py, "repo_pkg": repo_pkg, "models": models_dir, "dinov3": dinov3, "cuda_lib": cuda_lib}


def _escrever_shim_infer(caminho: Path, *, ok: bool = True) -> Path:
    caminho.write_text(
        "import argparse, json, os\nfrom pathlib import Path\np = argparse.ArgumentParser()\n"
        "for f in ('--imagem','--saida-dir','--resultado','--models-dir','--repo-dir','--modelo','--seed',"
        "'--quant','--pipeline-type','--steps','--shape-guidance','--tex-guidance','--texture-size',"
        "'--decimation-target','--remesh-project'): p.add_argument(f, required=True)\n"
        "a = p.parse_args(); out = Path(a.saida_dir); out.mkdir(parents=True, exist_ok=True)\n"
        f"if {ok!r}: (out / 'modelo.glb').write_bytes(b'glTF' + b'\\x00' * 32)\n"
        "d = {'ok': " + repr(ok) + ", 'modelo': a.modelo, 'texture_size': int(a.texture_size), "
        "'decimation_target': int(a.decimation_target), 'ld_library_path': os.environ.get('LD_LIBRARY_PATH', ''), "
        "'faces': 1234, 'torch': '2.6.0+cu128'}\n"
        f"if not {ok!r}: d['erro'] = 'CUDA indisponivel na venv de TRELLIS.2'\n"
        "Path(a.resultado).write_text(json.dumps(d), encoding='utf-8')\n"
        f"raise SystemExit(0 if {ok!r} else 1)\n",
        encoding="utf-8",
    )
    return caminho


# 1. Roteamento mesh_diag.modelo_escolhido()
@pytest.mark.parametrize("alias", ["trellis", "trellis2", "trellis.2", "trellis2_local", "  TRELLIS2  "])
def test_modelo_escolhido_aliases_explicitos(alias: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_MODELO_MESH", alias)
    assert mesh_diag.modelo_escolhido() == "trellis"


def test_modelo_escolhido_auto_e_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_MODELO_MESH", "auto")
    assert mesh_diag.modelo_escolhido() == "triposr"

    tdir = tmp_path / "tr2"
    info = _instalar_trellis2_fake(tdir)
    monkeypatch.setenv("FORGE3D_TRELLIS2_DIR", str(tdir))
    assert mesh_diag.modelo_escolhido() == "trellis"

    monkeypatch.setenv("FORGE3D_I23D_DEVICE", "cpu")
    assert mesh_diag.modelo_escolhido() == "triposr"

    monkeypatch.setenv("FORGE3D_I23D_DEVICE", "cuda:0")
    info["venv_py"].unlink()
    assert mesh_diag.modelo_escolhido() == "triposr"


def test_modelo_escolhido_desconhecido_bloqueado_d18(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_MODELO_MESH", "  Hunyuan3D ")
    assert mesh_diag.modelo_escolhido() == "hunyuan3d"
    prov = mesh.MeshProvider()
    with pytest.raises(ForgeError) as exc_info:
        prov._licenca()
    assert exc_info.value.codigo == "FORGE-E-LICENCA"
    ok, msg = prov.preflight()
    assert ok is False and "hunyuan3d" in msg.lower()


@pytest.mark.parametrize("triposr_env", ["FORGE3D_TRIPOSR", "FORGE3D_I23D_SCRIPT", "FORGE3D_VENV_I23D", "FORGE3D_MODELOS"])
def test_modelo_escolhido_unset_overrides(
    _isolar_ambiente: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, triposr_env: str
) -> None:
    assert mesh_diag.modelo_escolhido() == "triposr"
    default_dir = _isolar_ambiente / ".cache" / "forge3d" / "trellis2"
    _instalar_trellis2_fake(default_dir)
    assert mesh_diag.modelo_escolhido() == "trellis"

    monkeypatch.setenv(triposr_env, str(tmp_path / "triposr_override"))
    assert mesh_diag.modelo_escolhido() == "triposr"

    monkeypatch.setenv("FORGE3D_TRELLIS2_DIR", str(default_dir))
    assert mesh_diag.modelo_escolhido() == "trellis"

    monkeypatch.setenv("FORGE3D_I23D_DEVICE", "cpu")
    assert mesh_diag.modelo_escolhido() == "triposr"


# 2. Fail-fast sem fallback silencioso + bounds invalidos
@pytest.mark.parametrize(
    "cenario",
    [
        "sem_venv", "sem_repo", "sem_script", "sem_pesos_bf16", "sem_pesos_1024",
        "sem_pesos_q8", "sem_pesos_q4", "sem_dinov3", "device_cpu", "cuda_indisponivel", "vram_insuficiente",
    ],
)
def test_fail_fast_trellis2_sem_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cenario: str) -> None:
    monkeypatch.setenv("FORGE3D_MODELO_MESH", "trellis2")
    tdir = tmp_path / f"tr2_{cenario}"
    shim = _escrever_shim_infer(tmp_path / f"shim_{cenario}.py", ok=(cenario != "cuda_indisponivel"))
    info = _instalar_trellis2_fake(tdir, cuda_ok=(cenario != "cuda_indisponivel"))
    monkeypatch.setenv("FORGE3D_TRELLIS2_DIR", str(tdir))
    monkeypatch.setenv("FORGE3D_TRELLIS2_SCRIPT", str(shim))

    if cenario == "sem_venv":
        info["venv_py"].unlink()
    elif cenario == "sem_repo":
        info["repo_pkg"].rmdir()
    elif cenario == "sem_script":
        monkeypatch.setenv("FORGE3D_TRELLIS2_SCRIPT", str(tmp_path / "ausente.py"))
    elif cenario == "sem_pesos_bf16":
        (info["models"] / "Trellis2" / "pipeline.json").unlink()
    elif cenario == "sem_pesos_1024":
        monkeypatch.setenv("FORGE3D_TRELLIS2_PIPELINE_TYPE", "1024_cascade")
    elif cenario == "sem_pesos_q8":
        monkeypatch.setenv("FORGE3D_TRELLIS2_QUANT", "Q8_0")
    elif cenario == "sem_pesos_q4":
        monkeypatch.setenv("FORGE3D_TRELLIS2_QUANT", "Q4_K_M")
    elif cenario == "sem_dinov3":
        info["dinov3"].rmdir()
    elif cenario == "device_cpu":
        monkeypatch.setenv("FORGE3D_I23D_DEVICE", "cpu")
    elif cenario == "vram_insuficiente":
        monkeypatch.setattr(mesh, "_vram_livre_mb", lambda: mesh_diag.VRAM_MINIMA_MB - 1)

    prov = mesh.MeshProvider()
    monkeypatch.setattr(prov, "preflight_triposr", lambda: (_ for _ in ()).throw(AssertionError("fallback TripoSR")))
    ok, msg = prov.preflight()
    assert ok is False and msg and "triposr" not in msg.lower()

    if cenario != "vram_insuficiente":
        img = _escrever_png(tmp_path / "in.png")
        with pytest.raises(ForgeError) as exc_exec:
            mesh_trellis.executar_i23d_trellis2_local({"id": "a1"}, tmp_path / "out", img, dict(os.environ))
        assert exc_exec.value.codigo in ("FORGE-E-PROVIDER-RUN", "FORGE-E-LICENCA")

        with pytest.raises(ForgeError) as exc_step:
            mesh_i23d.executar_i23d_step(
                {"id": "a1"}, tmp_path / "out_step", img, None, dict(os.environ), 0.0,
                lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("fallback TripoSR")),
                lambda *_a, **_kw: {},
            )
        assert exc_step.value.codigo in ("FORGE-E-PROVIDER-RUN", "FORGE-E-LICENCA")


@pytest.mark.parametrize(
    ("env_var", "valor", "getter"),
    [
        ("FORGE3D_TRELLIS2_QUANT", "INT4", mesh_trellis.quant_trellis2),
        ("FORGE3D_TRELLIS2_PIPELINE_TYPE", "2048", mesh_trellis.pipeline_type_trellis2),
        ("FORGE3D_TRELLIS2_STEPS", "0", mesh_trellis.steps_trellis2),
        ("FORGE3D_TRELLIS2_STEPS", "201", mesh_trellis.steps_trellis2),
        ("FORGE3D_TRELLIS2_SHAPE_GUIDANCE", "0", mesh_trellis.shape_guidance_trellis2),
        ("FORGE3D_TRELLIS2_SHAPE_GUIDANCE", "-1.5", mesh_trellis.shape_guidance_trellis2),
        ("FORGE3D_TRELLIS2_TEX_GUIDANCE", "-0.1", mesh_trellis.tex_guidance_trellis2),
        ("FORGE3D_TRELLIS2_REMESH_PROJECT", "-0.01", mesh_trellis.remesh_project_trellis2),
        ("FORGE3D_TRELLIS2_REMESH_PROJECT", "1.01", mesh_trellis.remesh_project_trellis2),
        ("FORGE3D_I23D_DECIMATION_TARGET", "0", lambda: mesh_trellis.calcular_decimation_target({})),
        ("FORGE3D_I23D_DECIMATION_TARGET", "-50", lambda: mesh_trellis.calcular_decimation_target({})),
    ],
)
def test_config_bounds_invalidos_rejeitados(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env_var: str, valor: str, getter
) -> None:
    tdir = tmp_path / "tr2_bounds"
    _instalar_trellis2_fake(tdir)
    monkeypatch.setenv("FORGE3D_TRELLIS2_DIR", str(tdir))
    monkeypatch.setenv("FORGE3D_MODELO_MESH", "trellis2")
    monkeypatch.setenv(env_var, valor)

    with pytest.raises(ValueError):
        getter()
    ok, msg = mesh_trellis.preflight_trellis2()
    assert ok is False and msg, f"{env_var}={valor!r} aceito indevidamente: {(ok, msg)!r}"


# 3. Ambiente de subprocesso (cuda128/lib + defaults)
def test_env_subprocesso_trellis2_ld_e_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tdir = tmp_path / "tr2_env"
    info = _instalar_trellis2_fake(tdir, com_cuda_lib=True)
    monkeypatch.setenv("FORGE3D_TRELLIS2_DIR", str(tdir))
    cuda_str = str(info["cuda_lib"])

    env1 = mesh_trellis.env_subprocesso_trellis2({"LD_LIBRARY_PATH": "/opt/a:/opt/b", "PYTHONUNBUFFERED": "0"})
    assert env1["LD_LIBRARY_PATH"] == f"{cuda_str}:/opt/a:/opt/b"
    assert env1["PYTHONUNBUFFERED"] == "1"
    assert env1["PYTORCH_ALLOC_CONF"] == "expandable_segments:True"
    assert env1["OPENCV_IO_ENABLE_OPENEXR"] == "1"
    assert env1["ATTN_BACKEND"] == "flash_attn"

    env2 = mesh_trellis.env_subprocesso_trellis2({"LD_LIBRARY_PATH": f"/opt/a:{cuda_str}:/opt/b", "ATTN_BACKEND": "sdpa"})
    assert env2["LD_LIBRARY_PATH"].split(os.pathsep).count(cuda_str) == 1
    assert env2["ATTN_BACKEND"] == "sdpa"

    info["cuda_lib"].rmdir()
    assert mesh_trellis.env_subprocesso_trellis2({"LD_LIBRARY_PATH": "/opt/only"})["LD_LIBRARY_PATH"] == "/opt/only"


# 4. Invalidacao de chave de cache D6
def test_d6_cache_key_invalidation(monkeypatch: pytest.MonkeyPatch) -> None:
    prov = mesh.MeshProvider()
    monkeypatch.setenv("FORGE3D_MODELO_MESH", "triposr")
    v_triposr = prov.versao

    monkeypatch.setenv("FORGE3D_MODELO_MESH", "trellis2")
    tag_base, v_base = mesh_trellis.cache_tag_trellis2(), prov.versao
    assert v_base != v_triposr and tag_base in v_base

    mutacoes = [
        ("FORGE3D_I23D_TRELLIS_MODEL", "TencentARC/Pixal3D"),
        ("FORGE3D_TRELLIS2_QUANT", "Q8_0"),
        ("FORGE3D_TRELLIS2_PIPELINE_TYPE", "1024_cascade"),
        ("FORGE3D_TRELLIS2_STEPS", "40"),
        ("FORGE3D_TRELLIS2_SHAPE_GUIDANCE", "5.5"),
        ("FORGE3D_TRELLIS2_TEX_GUIDANCE", "1.5"),
        ("FORGE3D_TRELLIS2_REMESH_PROJECT", "0.5"),
        ("FORGE3D_I23D_DECIMATION_TARGET", "64000"),
    ]
    tags, vers = {tag_base}, {v_base}
    for env_var, valor in mutacoes:
        with monkeypatch.context() as mp:
            mp.setenv(env_var, valor)
            tag, ver = mesh_trellis.cache_tag_trellis2(), prov.versao
            assert tag != tag_base and ver != v_base
            tags.add(tag)
            vers.add(ver)
    assert len(tags) == len(mutacoes) + 1 and len(vers) == len(mutacoes) + 1


# 5. Roundtrip offline em subprocesso + gate D18
@pytest.mark.parametrize(("qualidade", "tex_esperada"), [("standard", 1024), ("hero", 2048), ("ultra", 2048)])
def test_roundtrip_offline_trellis2_e_modelo_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qualidade: str, tex_esperada: int
) -> None:
    tdir = tmp_path / f"tr2_rt_{qualidade}"
    info = _instalar_trellis2_fake(tdir, com_cuda_lib=True)
    shim = _escrever_shim_infer(tmp_path / f"shim_rt_{qualidade}.py", ok=True)
    monkeypatch.setenv("FORGE3D_MODELO_MESH", "trellis2")
    monkeypatch.setenv("FORGE3D_TRELLIS2_DIR", str(tdir))
    monkeypatch.setenv("FORGE3D_TRELLIS2_SCRIPT", str(shim))
    monkeypatch.setenv("FORGE3D_DELIGHT", "0")

    img = _escrever_png(tmp_path / f"in_{qualidade}.png", rgba=True)
    dest = tmp_path / f"direct_{qualidade}"
    res = mesh_trellis.executar_i23d_trellis2_local({"id": f"p_{qualidade}", "qualidade": qualidade}, dest, img, dict(os.environ))
    assert (dest / "modelo.glb").stat().st_size > 0
    assert res["provedor"] == "trellis2_local" and res["licenca"]["uso_comercial"] is True
    assert res["texture_size"] == tex_esperada and str(info["cuda_lib"]) in res["ld_library_path"]

    dest_step = tmp_path / f"step_{qualidade}"
    dados = mesh_i23d.executar_i23d_step(
        {"id": f"p_{qualidade}", "qualidade": qualidade, "tipo": "prop_estatico"},
        dest_step, img, None, dict(os.environ), 0.0,
        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("pose_guard nao deve rodar")),
        lambda *_a, **_kw: {},
    )
    assert dados["resultado"]["provedor"] == "trellis2_local"
    modelo_json = json.loads((dest_step / "modelo.json").read_text(encoding="utf-8"))
    assert modelo_json["frente_origem"] == "-Y" and modelo_json["textura_px"] == tex_esperada


@pytest.mark.parametrize("modelo_ok", ["microsoft/TRELLIS.2-4B", "TencentARC/Pixal3D", "TRELLIS-image-large"])
def test_d18_allowlist_mit_aceitos(modelo_ok: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_MODELO_MESH", "trellis2")
    monkeypatch.setenv("FORGE3D_I23D_TRELLIS_MODEL", modelo_ok)
    assert mesh_trellis.validar_modelo_trellis_licenca()
    assert mesh.MeshProvider().licenca["uso_comercial"] is True


@pytest.mark.parametrize("modelo_ruim", ["tencent/Hunyuan3D-2", "stabilityai/stable-fast-3d", "vendor/nc-only"])
def test_d18_modelo_nao_mit_recusado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, modelo_ruim: str) -> None:
    monkeypatch.setenv("FORGE3D_MODELO_MESH", "trellis2")
    monkeypatch.setenv("FORGE3D_I23D_TRELLIS_MODEL", modelo_ruim)
    with pytest.raises(ForgeError) as exc_val:
        mesh_trellis.validar_modelo_trellis_licenca()
    assert exc_val.value.codigo == "FORGE-E-LICENCA"
    img = _escrever_png(tmp_path / "in.png")
    with pytest.raises(ForgeError) as exc_exec:
        mesh_trellis.executar_i23d_trellis2_local({"id": "bad"}, tmp_path / "out", img, dict(os.environ))
    assert exc_exec.value.codigo == "FORGE-E-LICENCA"


# 6. CLI tools/trellis2_infer.py & contrato I9 (JSON em disco, zero stdout)
def test_trellis2_infer_cli_help_sem_gpu() -> None:
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": ""}
    proc = subprocess.run([sys.executable, str(SCRIPT_INFER), "--help"], capture_output=True, text=True, timeout=30, env=env)
    assert proc.returncode == 0 and "--imagem" in proc.stdout and "--resultado" in proc.stdout


@pytest.mark.parametrize(
    ("caso", "extra"),
    [
        ("imagem_ausente", []), ("png_corrompido", []), ("models_ausente", []),
        ("steps_zero", ["--steps", "0"]), ("steps_alto", ["--steps", "201"]),
        ("tex_baixo", ["--texture-size", "128"]), ("tex_alto", ["--texture-size", "8192"]),
        ("decim_baixo", ["--decimation-target", "1000"]), ("decim_alto", ["--decimation-target", "500000"]),
        ("remesh_neg", ["--remesh-project", "-0.1"]), ("remesh_alto", ["--remesh-project", "1.5"]),
        ("seed_neg", ["--seed", "-1"]),
    ],
)
def test_trellis2_infer_cli_erros_i9_json_zero_stdout(tmp_path: Path, caso: str, extra: list[str]) -> None:
    img = tmp_path / f"{caso}.png"
    if caso == "png_corrompido":
        img.write_bytes(b"corrupt-png-bytes")
    elif caso != "imagem_ausente":
        _escrever_png(img)
    models_dir = tmp_path / f"models_{caso}"
    (models_dir / "Trellis2" if caso != "models_ausente" else models_dir).mkdir(parents=True, exist_ok=True)
    repo_dir = tmp_path / f"repo_{caso}"
    (repo_dir / "trellis2_gguf").mkdir(parents=True, exist_ok=True)
    res_json = tmp_path / f"res_{caso}.json"

    proc = subprocess.run(
        [
            sys.executable, str(SCRIPT_INFER),
            "--imagem", str(img), "--saida-dir", str(tmp_path / f"out_{caso}"),
            "--resultado", str(res_json), "--models-dir", str(models_dir), "--repo-dir", str(repo_dir),
            *extra,
        ],
        capture_output=True, text=True, timeout=30, env={**os.environ, "CUDA_VISIBLE_DEVICES": ""},
    )
    assert proc.returncode != 0 and proc.stdout == ""
    dados = json.loads(res_json.read_text(encoding="utf-8"))
    assert dados["ok"] is False and isinstance(dados.get("erro"), str) and dados["erro"].strip()


# 7. Guarda anti-sobras Colab/remoto
def test_zero_sobras_colab_ou_remoto() -> None:
    assert list((RAIZ / "tools").glob("colab_trellis_*.py")) == []
    ocorrencias: list[str] = []
    for base in (RAIZ / "src" / "forge3d", RAIZ / "tools"):
        for py_arq in sorted(base.rglob("*.py")):
            if "__pycache__" in py_arq.parts:
                continue
            texto = py_arq.read_text(encoding="utf-8")
            for tok in _FORBIDDEN:
                if tok in texto:
                    ocorrencias.append(f"{py_arq.relative_to(RAIZ)}:text:{tok}")
            for node in ast.walk(ast.parse(texto, filename=str(py_arq))):
                vals = [node.value] if isinstance(node, ast.Constant) and isinstance(node.value, str) else (
                    [node.id] if isinstance(node, ast.Name) else (
                        [node.attr] if isinstance(node, ast.Attribute) else (
                            [node.name] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else []
                        )
                    )
                )
                for val in vals:
                    for tok in _FORBIDDEN:
                        if tok in val:
                            ocorrencias.append(f"{py_arq.relative_to(RAIZ)}:ast:{tok}")
    assert ocorrencias == [], f"sobras Colab/remoto encontradas: {ocorrencias}"


# 8. Regressao live E2E (D133): canon -Y em criatura larga e preservacao PBR/UV0
@pytest.mark.blender
def test_canonicalizar_frente_menos_y_nao_tomba_criatura_larga() -> None:
    codigo = f"""
import json, sys
sys.path.insert(0, {str(RAIZ / "blender")!r})
import bpy, postprocess, postprocess_canon
postprocess.limpar_cena()
bpy.ops.mesh.primitive_cube_add(size=1.0)
obj = bpy.context.active_object
for v in obj.data.vertices:
    v.co.x *= 1.00
    v.co.y *= 0.62
    v.co.z = (v.co.z + 0.5) * 0.86
    if v.co.z > 0.55:
        v.co.x *= 1.25
obj.data.update()
info = postprocess_canon.canonicalizar(obj, "criatura", frente_origem="-Y")
cs = [v.co for v in obj.data.vertices]
exts = [max(c[i] for c in cs) - min(c[i] for c in cs) for i in range(3)]
print("CANON_W:" + json.dumps({{"info": info, "exts": exts}}))
"""
    proc = subprocess.run([_BLENDER_BIN, "--background", "--factory-startup", "--python-expr", codigo], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(next(ln for ln in proc.stdout.splitlines() if ln.startswith("CANON_W:"))[8:])
    assert out["info"]["altura_eixo"] == "Z" and out["info"]["largura_eixo"] == "X" and out["info"]["profundidade_eixo"] == "Y"
    assert out["info"]["frente_origem"] == "-Y" and out["info"]["girado_frente"] is True and out["info"]["invertido"] is False
    assert out["exts"][0] > out["exts"][2] > out["exts"][1]


def test_postprocess_bruto_preserva_pbr_nativo_trellis2_e_uv_pos_decimate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(RAIZ / "blender"))
    reparo_calls: list[str] = []
    obj = types.SimpleNamespace(vertex_groups=[], data=types.SimpleNamespace(uv_layers=["UVMap"], materials=["m"], color_attributes=[], polygons=[1] * 20000))
    stubs = {k: types.SimpleNamespace() for k in ("bmesh", "autorig", "extrude_2d")} | {
        "bpy": types.SimpleNamespace(data=types.SimpleNamespace(objects=[])),
        "mathutils": types.SimpleNamespace(Matrix=object, Vector=object),
        "organic_sculpt": types.SimpleNamespace(contar_componentes=lambda _o: 1, soldar_componentes_organicos=lambda _o: {}, aplicar_corrective_smooth=lambda _o, **_kw: {}),
        "bake_pbr": types.SimpleNamespace(deve_ativar_bake_high_low=lambda it, **_kw: it.get("material") == "pbr", objeto_tem_pbr_nativo=lambda _o: True, px_bake_recomendado=lambda _q, _req=None, **_kw: (2048, 2048)),
        "postprocess_canon": types.SimpleNamespace(_alinhar_frente_humanoide=lambda _o: {}, canonicalizar=lambda _o, *_a, **_kw: {}),
        "postprocess_normals_uv": types.SimpleNamespace(aplicar_weighted_normal=lambda _o: {}, suavizar_por_angulo=lambda _o, **_kw: {}),
        "postprocess_repair": types.SimpleNamespace(reparar_malha=lambda _o, **_kw: reparo_calls.append("r") or {"ok": True}),
        "postprocess_scene": types.SimpleNamespace(TIPOS_ORGANICOS=(), _aplicar_transformes=lambda _o: None, _detectar_esqueleto_pelos_ossos=lambda _r: None, _resolver_opcional_bruto=lambda _d, _n: None, criar_armadura=lambda _o: None, importar_fonte=lambda _p: None, malha_triangulada=lambda o: len(o.data.polygons), objetos_colisao_ucx=lambda: [], unir_malhas=lambda: obj),
    }
    for k, v in stubs.items():
        monkeypatch.setitem(sys.modules, k, v)
    spec = importlib.util.spec_from_file_location("_pb_test", RAIZ / "blender" / "postprocess_bruto.py")
    assert spec and spec.loader
    pb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pb)
    info: dict = {}
    ctx = pb._preparar_bruto_arquivo({}, {"arquivo": "modelo.glb", "frente_origem": "-Y"}, "/tmp", {"limite_triangulos": 16000, "material": "opaque"}, {"soldar_componentes_organicos": False, "eh_organico": True, "angulo_graus": 65.0, "corrective_smooth": False, "weighted_normals": False}, "ultra", False, 2048, None, None, info)
    assert ctx["usar_bake_high_low"] is True and info["reparo_inicial"]["adiado_high_pbr_nativo"] is True and reparo_calls == []
    info2: dict = {}
    pb._reduzir_e_suavizar_sem_bake(obj, None, {}, ctx, {"corrective_smooth": False, "weighted_normals": False}, False, info2, lambda *_a, **_kw: False, lambda o, lim, **_kw: o.data.uv_layers.clear() or lim, lambda o: o.data.uv_layers.append("UVMap") or "UVMap")
    assert info2["uv"] == "UVMap" and obj.data.uv_layers == ["UVMap"]
