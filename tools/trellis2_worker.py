#!/usr/bin/env python3
"""Worker residente TRELLIS.2-4B via protocolo JSON-lines stdin/stdout (MIT, I9)."""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# Salvaguardas obrigatorias antes de importar torch/cv2 em GPU 6 GB
os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("ATTN_BACKEND", "flash_attn")

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

import trellis2_infer as _infer  # noqa: E402


class _WorkerEstado:
    """Mantem pipeline carregado em CPU RAM e metadados entre jobs."""

    def __init__(self) -> None:
        self.pipe: Any = None
        self.config: tuple[str, str, str, str, bool] | None = None
        self.jobs: int = 0


def _emitir(proto_out: Any, dados: dict[str, Any]) -> None:
    proto_out.write(json.dumps(dados, sort_keys=True) + "\n")
    proto_out.flush()


def _descarregar_pipe(estado: _WorkerEstado) -> None:
    if estado.pipe is not None:
        try:
            estado.pipe.move_all_to_cpu()
        except (RuntimeError, OSError, AttributeError) as exc:
            sys.stderr.write(f"[trellis2_worker] aviso move_all_to_cpu no unload: {exc}\n")
        estado.pipe = None
        estado.config = None
    gc.collect()
    torch_mod = sys.modules.get("torch")
    if torch_mod is not None and torch_mod.cuda.is_available():
        torch_mod.cuda.empty_cache()


def _req_para_args(req: dict[str, Any]) -> argparse.Namespace:
    imagem, saida_dir, resultado = (str(req.get(k) or "").strip() for k in ("imagem", "saida_dir", "resultado"))
    if not imagem or not saida_dir or not resultado:
        raise ValueError("req deve conter 'imagem', 'saida_dir' e 'resultado'")
    quant = str(req.get("quant") or "BF16").strip().upper()
    if quant not in ("BF16", "Q8_0", "Q4_K_M"):
        raise ValueError(f"--quant invalido: {quant!r}")
    pipeline_type = str(req.get("pipeline_type") or "512").strip().lower()
    if pipeline_type not in ("512", "1024_cascade"):
        raise ValueError(f"--pipeline-type invalido: {pipeline_type!r}")
    to_glb_def = float(os.environ.get("FORGE3D_TRELLIS2_TO_GLB_TIMEOUT_S", "240") or "240")
    return argparse.Namespace(
        imagem=imagem, saida_dir=saida_dir, resultado=resultado,
        models_dir=str(req.get("models_dir") or _infer._default_models_dir()),
        repo_dir=str(req.get("repo_dir") or _infer._default_repo_dir()),
        modelo=str(req.get("modelo") or "microsoft/TRELLIS.2-4B"),
        seed=int(req.get("seed") if req.get("seed") is not None else 1),
        quant=quant, pipeline_type=pipeline_type,
        steps=int(req.get("steps") if req.get("steps") is not None else 25),
        shape_guidance=float(req.get("shape_guidance") if req.get("shape_guidance") is not None else 7.5),
        tex_guidance=float(req.get("tex_guidance") if req.get("tex_guidance") is not None else 3.0),
        max_tokens=int(req.get("max_tokens") if req.get("max_tokens") is not None else 49152),
        texture_size=int(req.get("texture_size") if req.get("texture_size") is not None else 2048),
        decimation_target=int(req.get("decimation_target") if req.get("decimation_target") is not None else 80000),
        remesh_project=float(req.get("remesh_project") if req.get("remesh_project") is not None else 0.9),
        to_glb_timeout_s=float(req.get("to_glb_timeout_s") if req.get("to_glb_timeout_s") is not None else to_glb_def),
        no_remesh=bool(req.get("no_remesh", False)), tiled_tex=bool(req.get("tiled_tex", False)),
    )


def _obter_pipe(
    estado: _WorkerEstado, cfg: tuple[str, str, str, str, bool],
    models_dir: Path, repo_dir: Path, quant: str, tiled_tex: bool, torch_mod: Any,
) -> Any:
    if estado.pipe is not None and estado.config == cfg:
        return estado.pipe
    if estado.pipe is not None:
        _descarregar_pipe(estado)

    _infer._instalar_shims_comfy(models_dir, repo_dir)
    from trellis2_gguf.pipelines import Trellis2ImageTo3DPipeline
    from trellis2_gguf.utils import gguf_utils

    _infer._aplicar_patch_ggml(gguf_utils, torch_mod)
    is_bf16 = quant == "BF16"
    pipe = Trellis2ImageTo3DPipeline.from_pretrained(
        str(models_dir / "Trellis2"), keep_models_loaded=False,
        enable_gguf=not is_bf16, gguf_quant="Q8_0" if is_bf16 else quant, precision=None,
    )
    pipe.low_vram = True
    pipe.use_tiled_decoder_for_texture = bool(tiled_tex)
    estado.pipe, estado.config = pipe, cfg
    return pipe


def _executar_infer(estado: _WorkerEstado, req_path_str: str) -> dict[str, Any]:
    req_path = Path(req_path_str).expanduser()
    req = json.loads(req_path.read_text(encoding="utf-8"))
    if not isinstance(req, dict):
        raise ValueError(f"req JSON invalido em {req_path}")

    res_str = str(req.get("resultado") or "").strip()
    resultado_path = Path(res_str).expanduser() if res_str else None
    resultado: dict[str, Any] = {
        "ok": False, "provedor": "trellis2_local", "modelo": req.get("modelo", "microsoft/TRELLIS.2-4B"),
        "seed": req.get("seed", 1), "quant": req.get("quant", "BF16"), "pipeline_type": req.get("pipeline_type", "512"),
        "steps": req.get("steps", 25), "shape_guidance": req.get("shape_guidance", 7.5),
        "tex_guidance": req.get("tex_guidance", 3.0), "decimation_target": req.get("decimation_target", 80000),
        "texture_size": req.get("texture_size", 2048), "remesh_project": req.get("remesh_project", 0.9),
    }
    mesh_out = glb_obj = meshes = None
    try:
        args = _req_para_args(req)
        imagem_path, models_dir, repo_dir, img_pil = _infer._validar_parametros(args)
        saida_dir = Path(args.saida_dir).expanduser()

        import torch

        resultado["torch"] = torch.__version__
        resultado["cuda_disponivel"] = bool(torch.cuda.is_available())
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA indisponivel na venv de TRELLIS.2")
        torch.cuda.reset_peak_memory_stats()

        import cumesh
        import o_voxel

        saida_dir.mkdir(parents=True, exist_ok=True)
        _infer._copiar_se_diferente(imagem_path, saida_dir / "input.png")
        if _infer._tem_alfa_transparente(img_pil):
            _infer._copiar_se_diferente(imagem_path, saida_dir / "input_rgba.png")

        cfg = (str(models_dir), str(repo_dir), args.quant, args.pipeline_type, bool(args.tiled_tex))
        t0 = time.monotonic()
        pipe = _obter_pipe(estado, cfg, models_dir, repo_dir, args.quant, args.tiled_tex, torch)
        pipe.cuda()
        t_carga = time.monotonic()

        meshes = pipe.run(
            image=img_pil, seed=args.seed, preprocess_image=True, pipeline_type=args.pipeline_type,
            sparse_structure_sampler_params={"steps": args.steps},
            shape_slat_sampler_params={"steps": args.steps, "guidance_strength": args.shape_guidance},
            tex_slat_sampler_params={"steps": args.steps, "guidance_strength": args.tex_guidance},
            max_num_tokens=args.max_tokens, sparse_structure_resolution=32,
            use_tiled=True, generate_texture_slat=True,
        )
        t_inf = time.monotonic()
        mesh_out = meshes[0]

        pipe.move_all_to_cpu()
        gc.collect()
        torch.cuda.empty_cache()

        glb_obj, to_glb_meta = _infer._executar_to_glb_seguro(
            o_voxel, cumesh, mesh_out, decimation_target=args.decimation_target, texture_size=args.texture_size,
            remesh=not args.no_remesh, remesh_project=args.remesh_project, timeout_s=args.to_glb_timeout_s,
        )
        destino_glb = saida_dir / "modelo.glb"
        glb_obj.export(str(destino_glb))
        t_glb = time.monotonic()

        resultado.update({
            "ok": True, "arquivo": "modelo.glb", "glb": str(destino_glb),
            "glb_bytes": int(destino_glb.stat().st_size), "faces": _infer._contar_faces_glb(glb_obj),
            "to_glb_meta": to_glb_meta,
            "vram_pico_mb": round(torch.cuda.max_memory_allocated() / (1024**2), 1),
            "vram_reservada_mb": round(torch.cuda.max_memory_reserved() / (1024**2), 1),
            "tempos_s": {
                "carga": round(t_carga - t0, 3), "inferencia": round(t_inf - t_carga, 3),
                "to_glb": round(t_glb - t_inf, 3), "total": round(t_glb - t0, 3),
            },
        })
    except (ValueError, FileNotFoundError, OSError) as exc:
        msg = f"{type(exc).__name__}: {exc}"
        resultado.update({"ok": False, "erro": msg, "traceback": traceback.format_exc(limit=10)})
        sys.stderr.write(f"[trellis2_worker] erro de validacao: {msg}\n")
    except Exception as exc:  # noqa: BLE001 - erro vira JSON em disco e stderr, nunca stdout
        msg = f"{type(exc).__name__}: {exc}"
        resultado.update({"ok": False, "erro": msg, "traceback": traceback.format_exc(limit=10)})
        sys.stderr.write(f"[trellis2_worker] falha na inferencia: {msg}\n")
    finally:
        if estado.pipe is not None:
            try:
                estado.pipe.move_all_to_cpu()
            except (RuntimeError, OSError, AttributeError) as exc:
                sys.stderr.write(f"[trellis2_worker] aviso move_all_to_cpu no finally: {exc}\n")
        del mesh_out, glb_obj, meshes
        gc.collect()
        torch_mod = sys.modules.get("torch")
        if torch_mod is not None and torch_mod.cuda.is_available():
            torch_mod.cuda.empty_cache()
        if resultado_path is not None:
            _infer._salvar_json(resultado_path, resultado)

    estado.jobs += 1
    return {
        "ok": bool(resultado.get("ok")), "resultado": str(resultado_path) if resultado_path else "",
        "jobs": estado.jobs, "erro": resultado.get("erro"),
    }


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Forge3D worker residente TRELLIS.2-4B (JSON-lines stdin/stdout, I9)").parse_args(argv)
    proto_out = sys.stdout
    sys.stdout = sys.stderr
    estado = _WorkerEstado()
    try:
        for linha in sys.stdin:
            texto = linha.strip()
            if not texto:
                continue
            try:
                cmd_doc = json.loads(texto)
                if not isinstance(cmd_doc, dict):
                    raise ValueError(f"comando nao-objeto: {type(cmd_doc).__name__}")
                cmd = cmd_doc.get("cmd")
                if cmd == "ping":
                    _emitir(proto_out, {"ok": True, "pid": os.getpid(), "jobs": estado.jobs, "config": list(estado.config) if estado.config is not None else None})
                elif cmd == "shutdown":
                    _descarregar_pipe(estado)
                    _emitir(proto_out, {"ok": True, "bye": True})
                    return 0
                elif cmd == "infer":
                    _emitir(proto_out, _executar_infer(estado, str(cmd_doc.get("req_path") or "")))
                else:
                    sys.stderr.write(f"[trellis2_worker] comando desconhecido: {cmd!r}\n")
                    _emitir(proto_out, {"ok": False, "erro": f"comando desconhecido: {cmd!r}"})
            except Exception as exc:  # noqa: BLE001 - loop resiliente reporta erro em JSON e stderr
                msg = f"{type(exc).__name__}: {exc}"
                sys.stderr.write(f"[trellis2_worker] erro no loop de comandos: {msg}\n")
                _emitir(proto_out, {"ok": False, "erro": msg})
        return 0
    finally:
        _descarregar_pipe(estado)
        sys.stdout = proto_out


if __name__ == "__main__":
    raise SystemExit(main())
