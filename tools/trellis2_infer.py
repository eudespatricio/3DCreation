#!/usr/bin/env python3
"""Inferencia image-to-3D local com TRELLIS.2-4B em subprocesso isolado (MIT, I9, D29)."""

from __future__ import annotations

import argparse
import gc
import inspect
import json
import math
import os
import shutil
import signal
import sys
import threading
import time
import traceback
import types
from pathlib import Path
from typing import Any

# Salvaguardas obrigatorias antes de importar torch/cv2 em GPU 6 GB
os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("ATTN_BACKEND", "flash_attn")


def _dir_padrao_trellis2() -> Path:
    env = os.environ.get("FORGE3D_TRELLIS2_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cache" / "forge3d" / "trellis2"


def _default_models_dir() -> str:
    env = os.environ.get("FORGE3D_TRELLIS2_MODELS", "").strip()
    return env or str(_dir_padrao_trellis2() / "models")


def _default_repo_dir() -> str:
    env = os.environ.get("FORGE3D_TRELLIS2_REPO", "").strip()
    return env or str(_dir_padrao_trellis2() / "repo")


def _salvar_json(caminho: Path, dados: dict[str, Any]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as fh:
        json.dump(dados, fh, sort_keys=True, indent=1)
        fh.write("\n")


def _construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Forge3D i23d local (TRELLIS.2-4B MIT) — canal JSON")
    p.add_argument("--imagem", required=True, help="Caminho da imagem de entrada")
    p.add_argument("--saida-dir", required=True, help="Diretorio de saida (modelo.glb)")
    p.add_argument("--resultado", required=True, help="Arquivo JSON de resultado")
    p.add_argument("--models-dir", default=_default_models_dir(), help="Diretorio raiz dos pesos TRELLIS.2")
    p.add_argument("--repo-dir", default=_default_repo_dir(), help="Diretorio do pacote trellis2_gguf")
    p.add_argument("--modelo", default="microsoft/TRELLIS.2-4B", help="Identificador MIT do modelo")
    p.add_argument("--seed", type=int, default=1, help="Seed deterministica")
    p.add_argument("--quant", choices=("BF16", "Q8_0", "Q4_K_M"), default="BF16", help="Precisao dos DiTs")
    p.add_argument("--pipeline-type", choices=("512", "1024_cascade"), default="512", help="Modo de resolucao")
    p.add_argument("--steps", type=int, default=25, help="Passos do sampler")
    p.add_argument("--shape-guidance", type=float, default=7.5, help="CFG da geometria")
    p.add_argument("--tex-guidance", type=float, default=3.0, help="CFG da textura")
    p.add_argument("--max-tokens", type=int, default=49152, help="Teto de tokens esparsos")
    p.add_argument("--texture-size", type=int, default=2048, help="Resolucao da textura o_voxel")
    p.add_argument("--decimation-target", type=int, default=80000, help="Alvo de faces do o_voxel.to_glb")
    p.add_argument("--remesh-project", type=float, default=0.9, help="Proporcao de projecao do remesh [0, 1]")
    p.add_argument(
        "--to-glb-timeout-s",
        type=float,
        default=float(os.environ.get("FORGE3D_TRELLIS2_TO_GLB_TIMEOUT_S", "240") or "240"),
        help="Timeout em segundos para o_voxel.postprocess.to_glb (<=0 desativa)",
    )
    p.add_argument("--no-remesh", action="store_true", help="Desativa remesh no o_voxel.to_glb")
    p.add_argument("--tiled-tex", action="store_true", help="Ativa decoder de textura em tiles")
    return p


def _tem_alfa_transparente(imagem_pil: Any) -> bool:
    tem_alfa = imagem_pil.mode in ("RGBA", "LA", "PA") or "transparency" in imagem_pil.info
    if not tem_alfa:
        return False
    alfa = imagem_pil.convert("RGBA").getchannel("A")
    hist = alfa.histogram()
    total = sum(hist) or 1
    return (sum(hist[:250]) / total) >= 0.01


def _validar_parametros(args: argparse.Namespace) -> tuple[Path, Path, Path, Any]:
    from PIL import Image

    imagem_path = Path(args.imagem).expanduser()
    if not imagem_path.is_file():
        raise FileNotFoundError(f"imagem de entrada inexistente: {imagem_path}")
    with Image.open(imagem_path) as im:
        im.load()
        img_copia = im.copy()

    if args.seed < 0:
        raise ValueError(f"--seed deve ser >= 0: {args.seed}")
    if not (1 <= args.steps <= 200):
        raise ValueError(f"--steps fora do intervalo [1, 200]: {args.steps}")
    if args.shape_guidance <= 0.0:
        raise ValueError(f"--shape-guidance deve ser > 0: {args.shape_guidance}")
    if args.tex_guidance < 0.0:
        raise ValueError(f"--tex-guidance deve ser >= 0: {args.tex_guidance}")
    if args.max_tokens < 1024:
        raise ValueError(f"--max-tokens deve ser >= 1024: {args.max_tokens}")
    if not (256 <= args.texture_size <= 4096):
        raise ValueError(f"--texture-size fora do intervalo [256, 4096]: {args.texture_size}")
    if not (8000 <= args.decimation_target <= 300000):
        raise ValueError(f"--decimation-target fora do intervalo [8000, 300000]: {args.decimation_target}")
    if not (0.0 <= args.remesh_project <= 1.0):
        raise ValueError(f"--remesh-project fora do intervalo [0.0, 1.0]: {args.remesh_project}")
    if not math.isfinite(args.to_glb_timeout_s) or args.to_glb_timeout_s < 0.0:
        raise ValueError(f"--to-glb-timeout-s deve ser >= 0: {args.to_glb_timeout_s}")

    models_dir = Path(args.models_dir).expanduser().resolve()
    repo_dir = Path(args.repo_dir).expanduser().resolve()
    if not (models_dir / "Trellis2").is_dir():
        raise FileNotFoundError(f"diretorio de modelos Trellis2 ausente em {models_dir / 'Trellis2'}")
    if not (repo_dir / "trellis2_gguf").is_dir():
        raise FileNotFoundError(f"pacote trellis2_gguf ausente em {repo_dir}")
    return imagem_path, models_dir, repo_dir, img_copia


def _instalar_shims_comfy(models_dir: Path, repo_dir: Path) -> None:
    sys.modules["folder_paths"] = types.SimpleNamespace(models_dir=str(models_dir))
    comfy_mod = types.ModuleType("comfy")
    comfy_utils = types.ModuleType("comfy.utils")

    class _ProgressBar:
        def __init__(self, total: int) -> None:
            self.total = total
            self.cur = 0

        def update(self, n: int = 1) -> None:
            self.cur += n
            sys.stderr.write(f"[trellis2_infer] step {self.cur}/{self.total}\n")

        def update_absolute(self, value: int, total: int | None = None) -> None:
            self.cur = value
            if total is not None:
                self.total = total

    comfy_utils.ProgressBar = _ProgressBar  # type: ignore[attr-defined]
    comfy_mod.utils = comfy_utils  # type: ignore[attr-defined]
    sys.modules["comfy"] = comfy_mod
    sys.modules["comfy.utils"] = comfy_utils
    repo_str = str(repo_dir)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)


def _aplicar_patch_ggml(gguf_utils: Any, torch_mod: Any) -> None:
    if getattr(gguf_utils, "_native_dequantize_tensor", None) is not None:
        return

    class _StandaloneGGMLSparseLinear(gguf_utils.GGMLLayer, torch_mod.nn.Linear):
        def __init__(
            self, in_features: int, out_features: int, bias: bool = True, device=None, dtype=None
        ) -> None:
            torch_mod.nn.Linear.__init__(self, in_features, out_features, bias=bias, device=device, dtype=dtype)
            self.low_vram = False
            self.chunk_size = 65536

        def forward(self, input_tensor: Any, *args: Any, **kwargs: Any) -> Any:
            is_sparse = (
                input_tensor.__class__.__name__ in ("VarLenTensor", "SparseTensor")
                or hasattr(input_tensor, "feats")
            )
            x = input_tensor.feats if is_sparse else input_tensor
            if self.is_ggml_quantized():
                weight, bias = self.cast_bias_weight(x)
            else:
                weight = self.weight.to(device=x.device, dtype=x.dtype)
                bias = self.bias.to(device=x.device, dtype=x.dtype) if self.bias is not None else None
            if self.low_vram and x.shape[0] > self.chunk_size:
                out = gguf_utils.chunked_apply_linear(weight, bias, x, self.chunk_size)
            else:
                out = torch_mod.nn.functional.linear(x, weight, bias)
            return input_tensor.replace(out) if is_sparse else out

    gguf_utils.GGMLSparseLinear = _StandaloneGGMLSparseLinear


def _copiar_se_diferente(origem: Path, destino: Path) -> None:
    if origem.resolve() != destino.resolve():
        shutil.copyfile(origem, destino)


def _contar_faces_glb(glb_obj: Any) -> int | None:
    faces = getattr(glb_obj, "faces", None)
    if faces is not None and hasattr(faces, "__len__"):
        return int(len(faces))
    geom = getattr(glb_obj, "geometry", None)
    if isinstance(geom, dict):
        return sum(int(len(g.faces)) for g in geom.values() if hasattr(g, "faces"))
    return None


def _chamar_com_sigalrm(timeout_s: float, fn: Any) -> Any:
    """Executa ``fn()`` sob guarda POSIX SIGALRM quando na thread principal e ``timeout_s > 0``."""
    usar_alarme = (
        float(timeout_s) > 0.0
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
        and threading.current_thread() is threading.main_thread()
    )
    if not usar_alarme:
        return fn()

    def _on_alarm(_signum: int, _frame: Any) -> None:
        raise TimeoutError(f"o_voxel.postprocess.to_glb excedeu timeout de {timeout_s:.1f}s")

    prev_handler = signal.signal(signal.SIGALRM, _on_alarm)
    t_ini = time.monotonic()
    timeout_lim = min(float(timeout_s), 86400.0)
    prev_itimer = signal.setitimer(signal.ITIMER_REAL, timeout_lim)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, prev_handler)
        if prev_itimer[0] > 0.0:
            restante = max(1e-4, prev_itimer[0] - (time.monotonic() - t_ini))
            signal.setitimer(signal.ITIMER_REAL, restante, prev_itimer[1])


def _executar_to_glb_seguro(
    o_voxel_mod: Any,
    cumesh_mod: Any,
    mesh_out: Any,
    *,
    decimation_target: int,
    texture_size: int,
    remesh: bool,
    remesh_project: float,
    timeout_s: float = 240.0,
) -> tuple[Any, dict[str, Any]]:
    """Executa ``o_voxel.postprocess.to_glb`` com injecao de remesh/pre-UV, guarda SIGALRM e fallback seguro."""
    meta: dict[str, Any] = {
        "remesh_solicitado": bool(remesh),
        "remesh_aplicado": bool(remesh),
        "remesh_fallback": False,
        "motivo_fallback": None,
        "remove_inner_faces_injetado": False,
        "pre_uv_limpezas": [],
    }
    remeshing_ns = getattr(cumesh_mod, "remeshing", None) if cumesh_mod is not None else None
    orig_rnb = getattr(remeshing_ns, "remesh_narrow_band_dc", None) if remeshing_ns is not None else None
    if remeshing_ns is not None and callable(orig_rnb):
        def _wrapped_rnb(*args: Any, **kwargs: Any) -> Any:
            try:
                sig = inspect.signature(orig_rnb)
                if "remove_inner_faces" in sig.parameters:
                    bound = sig.bind_partial(*args, **kwargs)
                    if "remove_inner_faces" not in bound.arguments:
                        kwargs["remove_inner_faces"] = True
                        meta["remove_inner_faces_injetado"] = True
            except (TypeError, ValueError) as exc:
                sys.stderr.write(f"[trellis2_infer] aviso inspect remesh_narrow_band_dc: {exc}\n")
            return orig_rnb(*args, **kwargs)

        remeshing_ns.remesh_narrow_band_dc = _wrapped_rnb

    cumesh_cls = getattr(cumesh_mod, "CuMesh", None) if cumesh_mod is not None else None
    orig_uv_unwrap = getattr(cumesh_cls, "uv_unwrap", None) if cumesh_cls is not None else None
    if cumesh_cls is not None and callable(orig_uv_unwrap):
        def _wrapped_uv_unwrap(self_mesh: Any, *args: Any, **kwargs: Any) -> Any:
            passos = (
                ("remove_duplicate_faces", (), {}),
                ("remove_degenerate_faces", (), {}),
                ("repair_non_manifold_edges", (), {}),
                ("remove_small_connected_components", (1e-5,), {}),
                ("fill_holes", (), {"max_hole_perimeter": 3e-2}),
                ("unify_face_orientations", (), {}),
            )
            for nome_m, m_args, m_kwargs in passos:
                if hasattr(self_mesh, nome_m):
                    fn_m = getattr(self_mesh, nome_m)
                    if callable(fn_m):
                        try:
                            fn_m(*m_args, **m_kwargs)
                        except (RuntimeError, ValueError, TypeError) as exc:
                            sys.stderr.write(f"[trellis2_infer] aviso pre_uv {nome_m}: {exc}\n")
                        else:
                            meta["pre_uv_limpezas"].append(nome_m)
            return orig_uv_unwrap(self_mesh, *args, **kwargs)

        cumesh_cls.uv_unwrap = _wrapped_uv_unwrap

    def _rodar(usar_remesh: bool) -> Any:
        return _chamar_com_sigalrm(
            timeout_s,
            lambda: o_voxel_mod.postprocess.to_glb(
                vertices=mesh_out.vertices,
                faces=mesh_out.faces,
                attr_volume=mesh_out.attrs,
                coords=mesh_out.coords,
                attr_layout=mesh_out.layout,
                voxel_size=mesh_out.voxel_size,
                aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
                decimation_target=decimation_target,
                texture_size=texture_size,
                remesh=usar_remesh,
                remesh_project=remesh_project,
            ),
        )

    try:
        try:
            glb_obj = _rodar(bool(remesh))
        except (TimeoutError, RuntimeError) as exc:
            if not remesh:
                raise
            sys.stderr.write(
                f"[trellis2_infer] to_glb(remesh=True) falhou ({type(exc).__name__}: {exc}); tentando remesh=False\n"
            )
            meta["remesh_fallback"] = True
            meta["motivo_fallback"] = str(exc)
            meta["remesh_aplicado"] = False
            meta["pre_uv_limpezas_falha_remesh"] = list(meta["pre_uv_limpezas"])
            meta["pre_uv_limpezas"] = []
            gc.collect()
            torch_mod = sys.modules.get("torch")
            if torch_mod is not None and torch_mod.cuda.is_available():
                torch_mod.cuda.synchronize()
                torch_mod.cuda.empty_cache()
            glb_obj = _rodar(False)
    finally:
        if remeshing_ns is not None and callable(orig_rnb):
            remeshing_ns.remesh_narrow_band_dc = orig_rnb
        if cumesh_cls is not None and callable(orig_uv_unwrap):
            cumesh_cls.uv_unwrap = orig_uv_unwrap
    return glb_obj, meta


def _executar_inferencia(
    args: argparse.Namespace,
    imagem_path: Path,
    img_pil: Any,
    models_dir: Path,
    repo_dir: Path,
    saida_dir: Path,
    resultado: dict[str, Any],
) -> None:
    import torch

    resultado["torch"] = torch.__version__
    resultado["cuda_disponivel"] = bool(torch.cuda.is_available())
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA indisponivel na venv de TRELLIS.2")
    torch.cuda.reset_peak_memory_stats()

    import cumesh
    import o_voxel

    _instalar_shims_comfy(models_dir, repo_dir)
    from trellis2_gguf.pipelines import Trellis2ImageTo3DPipeline
    from trellis2_gguf.utils import gguf_utils

    _aplicar_patch_ggml(gguf_utils, torch)

    saida_dir.mkdir(parents=True, exist_ok=True)
    _copiar_se_diferente(imagem_path, saida_dir / "input.png")
    if _tem_alfa_transparente(img_pil):
        _copiar_se_diferente(imagem_path, saida_dir / "input_rgba.png")

    pipe = None
    mesh_out = None
    glb_obj = None
    try:
        t0 = time.monotonic()
        is_bf16 = args.quant == "BF16"
        pipe = Trellis2ImageTo3DPipeline.from_pretrained(
            str(models_dir / "Trellis2"),
            keep_models_loaded=False,
            enable_gguf=not is_bf16,
            gguf_quant="Q8_0" if is_bf16 else args.quant,
            precision=None,
        )
        pipe.low_vram = True
        pipe.cuda()
        pipe.use_tiled_decoder_for_texture = bool(args.tiled_tex)
        t_carga = time.monotonic()

        meshes = pipe.run(
            image=img_pil,
            seed=args.seed,
            preprocess_image=True,
            pipeline_type=args.pipeline_type,
            sparse_structure_sampler_params={"steps": args.steps},
            shape_slat_sampler_params={"steps": args.steps, "guidance_strength": args.shape_guidance},
            tex_slat_sampler_params={"steps": args.steps, "guidance_strength": args.tex_guidance},
            max_num_tokens=args.max_tokens,
            sparse_structure_resolution=32,
            use_tiled=True,
            generate_texture_slat=True,
        )
        t_inf = time.monotonic()
        mesh_out = meshes[0]

        pipe.move_all_to_cpu()
        gc.collect()
        torch.cuda.empty_cache()

        glb_obj, to_glb_meta = _executar_to_glb_seguro(
            o_voxel,
            cumesh,
            mesh_out,
            decimation_target=args.decimation_target,
            texture_size=args.texture_size,
            remesh=not args.no_remesh,
            remesh_project=args.remesh_project,
            timeout_s=args.to_glb_timeout_s,
        )
        destino_glb = saida_dir / "modelo.glb"
        glb_obj.export(str(destino_glb))
        t_glb = time.monotonic()

        resultado.update(
            {
                "ok": True,
                "arquivo": "modelo.glb",
                "glb": str(destino_glb),
                "glb_bytes": int(destino_glb.stat().st_size),
                "faces": _contar_faces_glb(glb_obj),
                "to_glb_meta": to_glb_meta,
                "vram_pico_mb": round(torch.cuda.max_memory_allocated() / (1024**2), 1),
                "vram_reservada_mb": round(torch.cuda.max_memory_reserved() / (1024**2), 1),
                "tempos_s": {
                    "carga": round(t_carga - t0, 3),
                    "inferencia": round(t_inf - t_carga, 3),
                    "to_glb": round(t_glb - t_inf, 3),
                    "total": round(t_glb - t0, 3),
                },
            }
        )
    finally:
        if pipe is not None:
            pipe.move_all_to_cpu()
        del mesh_out, glb_obj, pipe
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def main(argv: list[str] | None = None) -> int:
    args = _construir_parser().parse_args(argv)
    saida_dir = Path(args.saida_dir).expanduser()
    resultado_path = Path(args.resultado).expanduser()
    resultado: dict[str, Any] = {
        "ok": False,
        "provedor": "trellis2_local",
        "modelo": args.modelo,
        "seed": args.seed,
        "quant": args.quant,
        "pipeline_type": args.pipeline_type,
        "steps": args.steps,
        "shape_guidance": args.shape_guidance,
        "tex_guidance": args.tex_guidance,
        "decimation_target": args.decimation_target,
        "texture_size": args.texture_size,
        "remesh_project": args.remesh_project,
    }
    try:
        imagem_path, models_dir, repo_dir, img_pil = _validar_parametros(args)
        _executar_inferencia(args, imagem_path, img_pil, models_dir, repo_dir, saida_dir, resultado)
        return 0
    except (ValueError, FileNotFoundError, OSError) as exc:
        msg = f"{type(exc).__name__}: {exc}"
        resultado.update({"ok": False, "erro": msg, "traceback": traceback.format_exc(limit=10)})
        sys.stderr.write(f"[trellis2_infer] erro de validacao: {msg}\n")
        return 2
    except Exception as exc:  # noqa: BLE001 - erro vira arquivo JSON e stderr, nunca stdout
        msg = f"{type(exc).__name__}: {exc}"
        resultado.update({"ok": False, "erro": msg, "traceback": traceback.format_exc(limit=10)})
        sys.stderr.write(f"[trellis2_infer] falha na inferencia: {msg}\n")
        return 1
    finally:
        _salvar_json(resultado_path, resultado)


if __name__ == "__main__":
    raise SystemExit(main())
