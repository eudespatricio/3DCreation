"""Orquestracao em subprocesso isolado para TRELLIS.2-4B local (MIT, D18/D26/D29/I9)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .. import paths
from ..errors import ForgeError, erro_licenca, erro_provider_run
from . import mesh_diag as _diag
from .mesh_templates import ler_json_obrigatorio

MODELO_TRELLIS_PADRAO = "microsoft/TRELLIS.2-4B"

MODELOS_TRELLIS_MIT: dict[str, str] = {
    "microsoft/TRELLIS.2-4B": "microsoft/TRELLIS.2-4B",
    "TRELLIS.2-4B": "microsoft/TRELLIS.2-4B",
    "microsoft/TRELLIS.2": "microsoft/TRELLIS.2-4B",
    "TRELLIS.2": "microsoft/TRELLIS.2-4B",
    "trellis2": "microsoft/TRELLIS.2-4B",
    "trellis": "microsoft/TRELLIS.2-4B",
    "JeffreyXiang/TRELLIS.2-4B": "JeffreyXiang/TRELLIS.2-4B",
    "TencentARC/Pixal3D": "TencentARC/Pixal3D",
    "Pixal3D": "TencentARC/Pixal3D",
    "microsoft/TRELLIS-image-large": "microsoft/TRELLIS-image-large",
    "JeffreyXiang/TRELLIS-image-large": "JeffreyXiang/TRELLIS-image-large",
    "TRELLIS-image-large": "microsoft/TRELLIS-image-large",
}

_MAPA_MIT_NORM: dict[str, str] = {k.lower(): v for k, v in MODELOS_TRELLIS_MIT.items()}
_QUANTS_VALIDAS = ("BF16", "Q8_0", "Q4_K_M")
_PIPELINE_TYPES_VALIDOS = ("512", "1024_cascade")
_DIAGNOSTICO_TRELLIS2: dict[tuple[str, str, str], dict[str, Any]] = {}


def dir_trellis2() -> Path:
    """Diretorio raiz da instalacao isolada do TRELLIS.2 local."""
    env = os.environ.get("FORGE3D_TRELLIS2_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".cache" / "forge3d" / "trellis2"


def dir_venv_trellis2() -> Path:
    env = os.environ.get("FORGE3D_VENV_TRELLIS2", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return dir_trellis2() / "venv"


def dir_repo_trellis2() -> Path:
    env = os.environ.get("FORGE3D_TRELLIS2_REPO", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return dir_trellis2() / "repo"


def dir_models_trellis2() -> Path:
    env = os.environ.get("FORGE3D_TRELLIS2_MODELS", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return dir_trellis2() / "models"


def script_trellis2_infer() -> Path:
    env = os.environ.get("FORGE3D_TRELLIS2_SCRIPT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    em_dados = paths.raiz_dados() / "tools" / "trellis2_infer.py"
    if em_dados.is_file() or "FORGE3D_ROOT" in os.environ:
        return em_dados
    cand = Path(__file__).resolve().parents[3] / "tools" / "trellis2_infer.py"
    return cand if cand.is_file() else em_dados


def quant_trellis2() -> str:
    raw = os.environ.get("FORGE3D_TRELLIS2_QUANT", "BF16").strip().upper() or "BF16"
    if raw not in _QUANTS_VALIDAS:
        raise ValueError(f"FORGE3D_TRELLIS2_QUANT invalido: {raw!r} (aceitos: {', '.join(_QUANTS_VALIDAS)})")
    return raw


def pipeline_type_trellis2() -> str:
    raw = os.environ.get("FORGE3D_TRELLIS2_PIPELINE_TYPE", "512").strip().lower() or "512"
    if raw not in _PIPELINE_TYPES_VALIDOS:
        raise ValueError(
            f"FORGE3D_TRELLIS2_PIPELINE_TYPE invalido: {raw!r} (aceitos: {', '.join(_PIPELINE_TYPES_VALIDOS)})"
        )
    return raw


def steps_trellis2() -> int:
    raw = os.environ.get("FORGE3D_TRELLIS2_STEPS", "25").strip() or "25"
    val = int(raw)
    if not (1 <= val <= 200):
        raise ValueError(f"FORGE3D_TRELLIS2_STEPS deve estar em [1, 200]: {raw!r}")
    return val


def shape_guidance_trellis2() -> float:
    raw = os.environ.get("FORGE3D_TRELLIS2_SHAPE_GUIDANCE", "7.5").strip() or "7.5"
    val = float(raw)
    if not math.isfinite(val) or val <= 0.0:
        raise ValueError(f"FORGE3D_TRELLIS2_SHAPE_GUIDANCE deve ser > 0: {raw!r}")
    return val


def tex_guidance_trellis2() -> float:
    raw = os.environ.get("FORGE3D_TRELLIS2_TEX_GUIDANCE", "3.0").strip() or "3.0"
    val = float(raw)
    if not math.isfinite(val) or val < 0.0:
        raise ValueError(f"FORGE3D_TRELLIS2_TEX_GUIDANCE deve ser >= 0: {raw!r}")
    return val


def remesh_project_trellis2() -> float:
    raw = os.environ.get("FORGE3D_TRELLIS2_REMESH_PROJECT", "1.0").strip() or "1.0"
    val = float(raw)
    if not math.isfinite(val) or not (0.0 <= val <= 1.0):
        raise ValueError(f"FORGE3D_TRELLIS2_REMESH_PROJECT deve estar em [0.0, 1.0]: {raw!r}")
    return val


def cache_tag_trellis2() -> str:
    """Resumo deterministico das opcoes e codigo TRELLIS.2 para invalidacao de cache (D6)."""
    raw_mod = os.environ.get("FORGE3D_I23D_TRELLIS_MODEL", MODELO_TRELLIS_PADRAO).strip() or MODELO_TRELLIS_PADRAO
    mod = _MAPA_MIT_NORM.get(raw_mod.lower(), raw_mod)
    script = script_trellis2_infer()
    script_hash = "ausente"
    try:
        if script.is_file():
            script_hash = hashlib.sha256(script.read_bytes()).hexdigest()[:8]
    except OSError as exc:
        script_hash = f"err:{type(exc).__name__}"
    partes = [
        mod,
        os.environ.get("FORGE3D_TRELLIS2_QUANT", "BF16").strip().upper() or "BF16",
        os.environ.get("FORGE3D_TRELLIS2_PIPELINE_TYPE", "512").strip().lower() or "512",
        os.environ.get("FORGE3D_TRELLIS2_STEPS", "25").strip() or "25",
        os.environ.get("FORGE3D_TRELLIS2_SHAPE_GUIDANCE", "7.5").strip() or "7.5",
        os.environ.get("FORGE3D_TRELLIS2_TEX_GUIDANCE", "3.0").strip() or "3.0",
        os.environ.get("FORGE3D_TRELLIS2_REMESH_PROJECT", "1.0").strip() or "1.0",
        os.environ.get("FORGE3D_I23D_DECIMATION_TARGET", "").strip(),
        str(dir_repo_trellis2()),
        str(dir_models_trellis2()),
        str(script),
        script_hash,
    ]
    sha8 = hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()[:8]
    return f"tr2{sha8}"


def calcular_decimation_target(item: dict[str, Any]) -> int:
    """Calcula ``decimation_target`` para ``o_voxel.postprocess.to_glb`` no TRELLIS.2."""
    env_raw = os.environ.get("FORGE3D_I23D_DECIMATION_TARGET", "").strip()
    if env_raw:
        val = int(env_raw)
        if val <= 0:
            raise ValueError(f"FORGE3D_I23D_DECIMATION_TARGET deve ser > 0: {env_raw!r}")
        return max(8_000, min(300_000, val))
    lim_item = int(item.get("limite_triangulos") or 0)
    alvo = min(max(int(item.get("limite_triangulos") or 16_000) * 4, 48_000), 100_000)
    return max(alvo, lim_item)


def validar_modelo_trellis_licenca(modelo: str | None = None) -> str:
    """Valida ``FORGE3D_I23D_TRELLIS_MODEL`` contra a allowlist comercial MIT (D18/I7)."""
    bruto = modelo if modelo is not None else os.environ.get("FORGE3D_I23D_TRELLIS_MODEL", MODELO_TRELLIS_PADRAO)
    chave = str(bruto or "").strip() or MODELO_TRELLIS_PADRAO
    canon = _MAPA_MIT_NORM.get(chave.lower())
    if canon is None:
        raise erro_licenca(
            f"FORGE3D_I23D_TRELLIS_MODEL={chave!r} fora da allowlist comercial MIT (D18). Aceitos: {', '.join(sorted(MODELOS_TRELLIS_MIT))}",
            modelo=chave,
        )
    return canon


def pesos_trellis2_ok(
    models_dir: Path | None = None,
    quant: str | None = None,
    pipe_type: str | None = None,
) -> tuple[bool, str]:
    """Valida presenca dos checkpoints locais do TRELLIS.2 para ``quant`` e ``pipe_type``."""
    try:
        q = (quant if quant is not None else quant_trellis2()).strip().upper()
        if q not in _QUANTS_VALIDAS:
            raise ValueError(f"quant invalido: {q!r}")
        pt = (pipe_type if pipe_type is not None else pipeline_type_trellis2()).strip().lower()
        if pt not in _PIPELINE_TYPES_VALIDOS:
            raise ValueError(f"pipeline_type invalido: {pt!r}")
    except ValueError as exc:
        return False, str(exc)

    raiz = (models_dir or dir_models_trellis2()).expanduser().resolve()
    ext = ".safetensors" if q == "BF16" else f"_{q}.gguf"
    obrigatorios = [
        raiz / "Trellis2" / "pipeline.json",
        raiz / "Trellis2" / "decoders" / "Stage1" / "ss_dec_conv3d_16l8_fp16.safetensors",
        raiz / "Trellis2" / "decoders" / "Stage2" / "shape_dec_next_dc_f16c32_fp16.safetensors",
        raiz / "Trellis2" / "decoders" / "Stage2" / "tex_dec_next_dc_f16c32_fp16.safetensors",
        raiz / "Trellis2" / "refiner" / f"ss_flow_img_dit_1_3B_64_bf16{ext}",
        raiz / "Trellis2" / "shape" / f"slat_flow_img2shape_dit_1_3B_512_bf16{ext}",
        raiz / "Trellis2" / "texture" / f"slat_flow_imgshape2tex_dit_1_3B_512_bf16{ext}",
    ]
    if pt == "1024_cascade":
        obrigatorios.extend([
            raiz / "Trellis2" / "shape" / f"slat_flow_img2shape_dit_1_3B_1024_bf16{ext}",
            raiz / "Trellis2" / "texture" / f"slat_flow_imgshape2tex_dit_1_3B_1024_bf16{ext}",
        ])
    faltando = [str(p) for p in obrigatorios if not p.is_file()]
    dinov3_cands = (
        raiz / "facebook" / "dinov3-vitl16-pretrain-lvd1689m",
        raiz / "Trellis2" / "dinov3" / "facebook" / "dinov3-vitl16-pretrain-lvd1689m",
        raiz / "Aero-Ex" / "Dinov3" / "facebook" / "dinov3-vitl16-pretrain-lvd1689m",
    )
    if not any(d.is_dir() for d in dinov3_cands):
        faltando.append(str(dinov3_cands[0]))
    if faltando:
        return False, f"pesos TRELLIS.2 ({q}/{pt}) ausentes: {faltando[0]}"
    return True, f"ok ({q}/{pt})"


def trellis2_local_instalado() -> bool:
    """Verifica sem subprocesso se a instalacao local TRELLIS.2 esta completa no disco."""
    venv_py = dir_venv_trellis2() / "bin" / "python"
    repo_pkg = dir_repo_trellis2() / "trellis2_gguf"
    script = script_trellis2_infer()
    if not (venv_py.is_file() and repo_pkg.is_dir() and script.is_file()):
        return False
    return pesos_trellis2_ok()[0]


def env_subprocesso_trellis2(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Monta ambiente do subprocesso propagando ``cuda128/lib`` via ``LD_LIBRARY_PATH``."""
    env = dict(os.environ if base_env is None else base_env)
    cuda_lib = dir_trellis2() / "cuda128" / "lib"
    if cuda_lib.is_dir():
        cuda_str = str(cuda_lib)
        prev = env.get("LD_LIBRARY_PATH", "").strip()
        partes = [p for p in prev.split(os.pathsep) if p] if prev else []
        if cuda_str not in partes:
            env["LD_LIBRARY_PATH"] = os.pathsep.join([cuda_str, *partes]) if partes else cuda_str
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
    env.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    env.setdefault("ATTN_BACKEND", "flash_attn")
    return env


def diagnostico_trellis2() -> dict[str, Any]:
    """Sonda kernels CUDA e torch da venv TRELLIS.2 via subprocesso (I9/D26)."""
    venv = dir_venv_trellis2()
    repo = dir_repo_trellis2()
    script = script_trellis2_infer()
    chave = (str(venv), str(repo), str(script))
    if chave in _DIAGNOSTICO_TRELLIS2:
        return _DIAGNOSTICO_TRELLIS2[chave]

    python = venv / "bin" / "python"
    if not python.is_file():
        res: dict[str, Any] = {"ok": False, "razao": f"P3: venv TRELLIS.2 ausente em {venv}"}
    elif not (repo / "trellis2_gguf").is_dir():
        res = {"ok": False, "razao": f"P3: pacote trellis2_gguf ausente em {repo}"}
    elif not script.is_file():
        res = {"ok": False, "razao": f"P3: script TRELLIS.2 ausente em {script}"}
    else:
        codigo = (
            "import json, torch, o_voxel, flex_gemm, nvdiffrast, cumesh; "
            "print(json.dumps({'torch': torch.__version__, 'cuda': bool(torch.cuda.is_available())}))"
        )
        try:
            proc = _diag.subproc_run(
                [str(python), "-c", codigo],
                capture_output=True,
                text=True,
                timeout=180,
                env=env_subprocesso_trellis2(),
            )
            linha = next((ln for ln in reversed(proc.stdout.splitlines()) if ln.strip().startswith("{")), "")
            info = json.loads(linha) if linha else {}
            if proc.returncode != 0 or not info:
                det = (proc.stderr or proc.stdout or "").strip().splitlines()
                res = {
                    "ok": False,
                    "razao": "P3: falha ao importar TRELLIS.2 na venv: " + (det[-1] if det else f"exit {proc.returncode}"),
                }
            elif not info.get("cuda"):
                res = {"ok": False, "razao": "P3: venv TRELLIS.2 sem CUDA disponivel"}
            else:
                res = {"ok": True, "torch": info.get("torch"), "cuda": True}
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            res = {"ok": False, "razao": f"P3: falha ao diagnosticar venv TRELLIS.2: {exc}"}

    _DIAGNOSTICO_TRELLIS2[chave] = res
    return res


def preflight_trellis2() -> tuple[bool, str]:
    """Preflight completo para TRELLIS.2 local: licenca, params, GPU/CUDA, pesos e VRAM."""
    try:
        validar_modelo_trellis_licenca()
        quant = quant_trellis2()
        pipe_type = pipeline_type_trellis2()
        steps_trellis2()
        shape_guidance_trellis2()
        tex_guidance_trellis2()
        remesh_project_trellis2()
        calcular_decimation_target({})
    except ForgeError as exc:
        return False, exc.mensagem
    except ValueError as exc:
        return False, f"P3: {exc}"

    if _diag.facade_attr("_device", _diag._device)().startswith("cpu"):
        return False, "P3: TRELLIS.2 local requer GPU CUDA (CPU nao suportado)"

    diag = diagnostico_trellis2()
    if not diag.get("ok"):
        return False, str(diag.get("razao") or "P3: diagnostico TRELLIS.2 falhou")

    ok_pesos, razao_pesos = pesos_trellis2_ok(quant=quant, pipe_type=pipe_type)
    if not ok_pesos:
        return False, f"P3: {razao_pesos}"

    livre = _diag.facade_attr("_vram_livre_mb", _diag._vram_livre_mb)()
    vram_min = _diag.facade_attr("_vram_minima_mb", _diag._vram_minima_mb)()
    if livre is not None and livre < vram_min:
        return False, f"P3: VRAM livre {livre} MiB < {vram_min} MiB exigidos"

    return (
        True,
        f"pronto (TRELLIS.2 local {quant}/{pipe_type}, torch {diag.get('torch', '?')}, venv {dir_venv_trellis2().name})",
    )


def _preparar_inputs_locais(imagem: Path, destino: Path, env: dict[str, str]) -> tuple[Path, Path | None]:
    input_png = destino / "input.png"
    if imagem.resolve() != input_png.resolve():
        shutil.copyfile(imagem, input_png)
    input_rgba = destino / "input_rgba.png"
    if _diag.facade_attr("_alfa_util", _diag._alfa_util)(imagem)[0]:
        if imagem.resolve() != input_rgba.resolve():
            shutil.copyfile(imagem, input_rgba)
        return input_png, input_rgba

    pg_script = _diag.facade_attr("script_pose_guard", _diag.script_pose_guard)()
    py_img = _diag.facade_attr("_python_imagem", _diag._python_imagem)()
    if not py_img.is_file():
        py_img = Path(sys.executable)
    if not pg_script.is_file():
        sys.stderr.write(f"[mesh_trellis] aviso pose_guard.py ausente ({pg_script}); mantendo input opaco\n")
        return input_png, None
    try:
        proc = _diag.subproc_run(
            [str(py_img), str(pg_script), "--acao", "decompor", "--imagem", str(imagem), "--saida-png", str(input_rgba), "--resultado", str(destino / "cutout_front_resultado.json")],
            capture_output=True, text=True, timeout=_diag.facade_attr("TIMEOUT_S", _diag.TIMEOUT_S), env=env,
        )
        if proc.returncode == 0 and input_rgba.is_file():
            return input_png, input_rgba
        sys.stderr.write(f"[mesh_trellis] aviso recorte 2D falhou (exit {proc.returncode}); mantendo input opaco\n")
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        sys.stderr.write(f"[mesh_trellis] aviso recorte 2D indisponivel ({exc}); mantendo input opaco\n")
    return input_png, None


def executar_i23d_trellis2_local(
    item: dict[str, Any],
    destino: Path,
    imagem: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    """Executa TRELLIS.2-4B local em subprocesso isolado via ``tools/trellis2_infer.py`` (I9)."""
    from . import LICENCAS

    modelo_canon = validar_modelo_trellis_licenca()
    if _diag.facade_attr("_device", _diag._device)().startswith("cpu"):
        raise erro_provider_run("TRELLIS.2 local requer GPU CUDA (CPU nao suportado)", id=item.get("id"), modelo="trellis")

    venv_py = dir_venv_trellis2() / "bin" / "python"
    repo_dir = dir_repo_trellis2()
    models_dir = dir_models_trellis2()
    script = script_trellis2_infer()
    if not venv_py.is_file():
        raise erro_provider_run(f"venv TRELLIS.2 ausente em {dir_venv_trellis2()}", id=item.get("id"), modelo="trellis")
    if not (repo_dir / "trellis2_gguf").is_dir():
        raise erro_provider_run(f"pacote trellis2_gguf ausente em {repo_dir}", id=item.get("id"), modelo="trellis")
    if not script.is_file():
        raise erro_provider_run(f"script trellis2_infer.py ausente em {script}", id=item.get("id"), modelo="trellis")

    try:
        quant = quant_trellis2()
        pipe_type = pipeline_type_trellis2()
        steps = steps_trellis2()
        shape_cfg = shape_guidance_trellis2()
        tex_cfg = tex_guidance_trellis2()
        remesh_proj = remesh_project_trellis2()
        decimation_target = calcular_decimation_target(item)
        seed_raw = item.get("seed")
        seed = int(seed_raw) if seed_raw is not None else 1
        qual = _diag.facade_attr("_qualidade", _diag._qualidade)(item)
        tex_def = "2048" if qual in ("hero", "ultra") else "1024"
        tex_size = int(os.environ.get("FORGE3D_TEX_PX", tex_def))
        timeout_s = max(1, int(os.environ.get("FORGE3D_I23D_TIMEOUT", "1200")))
    except (TypeError, ValueError) as exc:
        raise erro_provider_run(f"parametro invalido para TRELLIS.2 local: {exc}", id=item.get("id"), modelo="trellis") from exc

    ok_pesos, msg_pesos = pesos_trellis2_ok(models_dir=models_dir, quant=quant, pipe_type=pipe_type)
    if not ok_pesos:
        raise erro_provider_run(msg_pesos, id=item.get("id"), modelo="trellis")

    destino.mkdir(parents=True, exist_ok=True)
    input_png, input_rgba = _preparar_inputs_locais(imagem, destino, env)
    front_src = input_rgba if (input_rgba and input_rgba.is_file()) else input_png
    resultado_path = destino / "i23d_resultado.json"
    if resultado_path.exists():
        resultado_path.unlink()

    comando = [
        str(venv_py), str(script),
        "--imagem", str(front_src),
        "--saida-dir", str(destino),
        "--resultado", str(resultado_path),
        "--models-dir", str(models_dir),
        "--repo-dir", str(repo_dir),
        "--modelo", modelo_canon,
        "--seed", str(seed),
        "--quant", quant,
        "--pipeline-type", pipe_type,
        "--steps", str(steps),
        "--shape-guidance", str(shape_cfg),
        "--tex-guidance", str(tex_cfg),
        "--texture-size", str(tex_size),
        "--decimation-target", str(decimation_target),
        "--remesh-project", str(remesh_proj),
    ]
    t0 = time.monotonic()
    try:
        proc = _diag.subproc_run(
            comando, capture_output=True, text=True, timeout=timeout_s, env=env_subprocesso_trellis2(env)
        )
    except subprocess.TimeoutExpired:
        raise erro_provider_run(f"timeout de {timeout_s}s na inferencia TRELLIS.2 local", id=item.get("id"), modelo="trellis") from None
    except OSError as exc:
        raise erro_provider_run(f"falha ao executar venv TRELLIS.2: {exc}", id=item.get("id"), modelo="trellis") from exc

    if not resultado_path.is_file():
        raise erro_provider_run(
            "trellis2_infer nao escreveu i23d_resultado.json",
            id=item.get("id"),
            modelo="trellis",
            exit=proc.returncode,
            stderr=(proc.stderr or proc.stdout or "")[-2000:],
        )
    resultado = ler_json_obrigatorio(resultado_path, "trellis2_local", item.get("id"))
    if not resultado.get("ok"):
        raise erro_provider_run(
            f"TRELLIS.2 local falhou: {resultado.get('erro')}",
            id=item.get("id"),
            modelo="trellis",
            stderr=(resultado.get("traceback") or "")[-2000:],
        )
    glb_out = destino / "modelo.glb"
    if not glb_out.is_file() or glb_out.stat().st_size == 0:
        raise erro_provider_run(f"TRELLIS.2 local nao produziu modelo.glb valido em {destino}", id=item.get("id"), modelo="trellis")

    resultado["provedor"] = "trellis2_local"
    resultado["modelo"] = validar_modelo_trellis_licenca(str(resultado.get("modelo") or modelo_canon))
    resultado["licenca"] = dict(LICENCAS["trellis"])
    resultado.setdefault("tempo_s", round(time.monotonic() - t0, 3))
    resultado_path.write_text(json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return resultado
