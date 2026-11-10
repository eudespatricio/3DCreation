"""Concept text-to-image do Forge3D (roda DENTRO da venv de concept, nunca no nucleo).

Uso (o provider ``mesh`` monta esta linha quando o item nao tem ``origem``):

    <venv-concept>/bin/python tools/concept_infer.py \
        --prompt "..." --negative "..." --seed 20261110 \
        --saida staging/concept.png --resultado staging/concept.json \
        --modelo stable-diffusion-v1-5/stable-diffusion-v1-5

Canal: JSON em disco. Nada de parse de stdout (I9).

Modelo: Stable Diffusion 1.5 (CreativeML OpenRAIL-M), fp16, 512², ~2 GB de pesos.
Determinismo: D2 (seed fixa + versoes pinadas); nao e byte-identico entre drivers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import traceback
from pathlib import Path


def _salvar(caminho: str, obj: dict) -> None:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, sort_keys=True, indent=1)
        fh.write("\n")


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Forge3D concept (SD1.5) — canal JSON")
    p.add_argument("--prompt", required=True)
    p.add_argument("--negative", default="")
    p.add_argument("--seed", type=int, default=20261110)
    p.add_argument("--saida", required=True)
    p.add_argument("--resultado", required=True)
    p.add_argument("--modelo", default="stable-diffusion-v1-5/stable-diffusion-v1-5")
    p.add_argument("--largura", type=int, default=512)
    p.add_argument("--altura", type=int, default=512)
    p.add_argument("--passos", type=int, default=25)
    p.add_argument("--guidance", type=float, default=7.5)
    p.add_argument("--device", default="cuda")
    return p.parse_args()


def _revisao_local(caminho: str) -> str:
    """Extrai o hash do snapshot HF do caminho local, quando existir."""
    if not caminho:
        return ""
    partes = Path(caminho).parts
    if "snapshots" in partes:
        i = partes.index("snapshots")
        if i + 1 < len(partes):
            return partes[i + 1]
    return Path(caminho).name


def main() -> int:
    args = _args()
    resultado: dict = {
        "ok": False,
        "modelo": args.modelo,
        "seed": args.seed,
        "prompt": args.prompt,
        "negative": args.negative,
        "largura": args.largura,
        "altura": args.altura,
        "passos": args.passos,
        "guidance": args.guidance,
    }
    try:
        import torch
        from diffusers import StableDiffusionPipeline

        if args.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA indisponivel na venv de concept")
        dtype = torch.float16 if args.device.startswith("cuda") else torch.float32
        resultado["device"] = args.device
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
        torch.manual_seed(args.seed)

        t0 = time.monotonic()
        comuns = {
            "torch_dtype": dtype,
            "safety_checker": None,
            "requires_safety_checker": False,
        }
        try:
            # no CPU os pesos fp16 sao carregados e convertidos para float32; evita baixar
            # uma segunda copia (~3,4 GB) so para o fallback
            pipe = StableDiffusionPipeline.from_pretrained(
                args.modelo, variant="fp16", **comuns
            )
        except Exception:
            pipe = StableDiffusionPipeline.from_pretrained(args.modelo, **comuns)
        pipe.set_progress_bar_config(disable=True)
        pipe.to(args.device)
        if hasattr(pipe, "enable_attention_slicing"):
            pipe.enable_attention_slicing()
        if hasattr(pipe, "enable_vae_slicing"):
            pipe.enable_vae_slicing()
        t_carregar = time.monotonic()

        gerador = torch.Generator(device=args.device).manual_seed(args.seed)
        imagem = pipe(
            prompt=args.prompt,
            negative_prompt=args.negative or None,
            num_inference_steps=args.passos,
            guidance_scale=args.guidance,
            width=args.largura,
            height=args.altura,
            generator=gerador,
        ).images[0]
        t_gerar = time.monotonic()

        saida = Path(args.saida)
        saida.parent.mkdir(parents=True, exist_ok=True)
        imagem.save(saida)
        t_salvar = time.monotonic()

        resultado.update(
            {
                "ok": True,
                "png": str(saida),
                "png_bytes": saida.stat().st_size,
                "png_sha256": "sha256:"
                + hashlib.sha256(saida.read_bytes()).hexdigest(),
                "revisao": _revisao_local(
                    getattr(getattr(getattr(pipe, "unet", None), "config", None), "_name_or_path", "")
                ),
                "tempos_s": {
                    "carregar": round(t_carregar - t0, 3),
                    "gerar": round(t_gerar - t_carregar, 3),
                    "salvar": round(t_salvar - t_gerar, 3),
                    "total": round(t_salvar - t0, 3),
                },
            }
        )
        if torch.cuda.is_available():
            resultado["vram_pico_mb"] = round(
                torch.cuda.max_memory_allocated() / (1024**2), 1
            )
            resultado["vram_reservada_mb"] = round(
                torch.cuda.max_memory_reserved() / (1024**2), 1
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - erro vira arquivo, nao stdout
        resultado.update(
            {
                "ok": False,
                "erro": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=10),
            }
        )
        return 1
    finally:
        _salvar(args.resultado, resultado)


if __name__ == "__main__":
    raise SystemExit(main())
