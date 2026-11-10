"""Inferencia image-to-3D do Forge3D (roda DENTRO da venv de GPU, nunca no nucleo).

Uso (o provider ``mesh`` monta esta linha):

    FORGE3D_VENV_I23D=~/.cache/forge3d/venv-i23d \
    PYTHONPATH=~/.cache/forge3d/vendor/TripoSR \
    <venv>/bin/python tools/i23d_infer.py \
        --imagem entrada.png --saida-dir staging --resultado resultado.json \
        --modelo stabilityai/TripoSR --mc-resolution 256 --sem-rembg

Canal: JSON em disco. Nada de parse de stdout (mesma regra do Blender, I9).

Saida: ``<saida-dir>/modelo.glb`` com POSITION + COLOR_0 (sem UV). O bake de UV/textura e feito
depois no ``blender/postprocess.py``, que nao depende de CUDA.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path


def _salvar(caminho: str, obj: dict) -> None:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, sort_keys=True, indent=1)
        fh.write("\n")


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Forge3D i23d (TripoSR) — canal JSON")
    p.add_argument("--imagem", required=True)
    p.add_argument("--saida-dir", required=True)
    p.add_argument("--resultado", required=True)
    p.add_argument("--modelo", default="stabilityai/TripoSR")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--mc-resolution", type=int, default=256)
    p.add_argument("--chunk-size", type=int, default=8192)
    p.add_argument("--foreground-ratio", type=float, default=0.85)
    p.add_argument(
        "--remover-fundo",
        action="store_true",
        help="usa rembg; sem isso a imagem precisa ter fundo neutro/alfa",
    )
    return p.parse_args()


def _preparar_imagem(caminho: str, remover_fundo: bool, foreground_ratio: float):
    import numpy as np
    from PIL import Image

    imagem = Image.open(caminho).convert("RGBA")
    if remover_fundo:
        import rembg
        from tsr.utils import remove_background, resize_foreground

        sessao = rembg.new_session()
        recortada = remove_background(imagem, sessao)
        recortada = resize_foreground(recortada, foreground_ratio)
        arr = np.array(recortada).astype("float32") / 255.0
        arr = arr[:, :, :3] * arr[:, :, 3:4] + (1.0 - arr[:, :, 3:4]) * 0.5
        return Image.fromarray((arr * 255.0).astype("uint8"))
    # fundo neutro: compoe alfa sobre cinza medio (o modelo foi treinado assim)
    fundo = Image.new("RGBA", imagem.size, (128, 128, 128, 255))
    return Image.alpha_composite(fundo, imagem).convert("RGB")


def main() -> int:
    args = _args()
    saida_dir = Path(args.saida_dir).expanduser().resolve()
    saida_dir.mkdir(parents=True, exist_ok=True)
    resultado: dict = {
        "ok": False,
        "modelo": args.modelo,
        "mc_resolution": args.mc_resolution,
        "imagem": str(Path(args.imagem).expanduser().resolve()),
    }
    try:
        import torch

        resultado["torch"] = torch.__version__
        resultado["cuda_disponivel"] = bool(torch.cuda.is_available())
        if args.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA indisponivel na venv de i23d")
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()

        from tsr.system import TSR

        imagem = _preparar_imagem(args.imagem, args.remover_fundo, args.foreground_ratio)
        imagem.save(saida_dir / "input.png")

        t0 = time.monotonic()
        modelo = TSR.from_pretrained(
            args.modelo,
            config_name="config.yaml",
            weight_name="model.ckpt",
        )
        modelo.renderer.set_chunk_size(args.chunk_size)
        modelo.to(args.device)
        t_carregar = time.monotonic()

        with torch.no_grad():
            codigos = modelo([imagem], device=args.device)
        t_forward = time.monotonic()

        malhas = modelo.extract_mesh(codigos, True, resolution=args.mc_resolution)
        t_extrair = time.monotonic()

        malha = malhas[0]
        destino = saida_dir / "modelo.glb"
        malha.export(destino)
        t_exportar = time.monotonic()

        resultado.update(
            {
                "ok": True,
                "glb": str(destino),
                "glb_bytes": destino.stat().st_size,
                "vertices": int(len(malha.vertices)),
                "faces": int(len(malha.faces)),
                "tempos_s": {
                    "carregar": round(t_carregar - t0, 3),
                    "forward": round(t_forward - t_carregar, 3),
                    "extrair": round(t_extrair - t_forward, 3),
                    "exportar": round(t_exportar - t_extrair, 3),
                    "total": round(t_exportar - t0, 3),
                },
            }
        )
        if torch.cuda.is_available():
            resultado["vram_pico_mb"] = round(torch.cuda.max_memory_allocated() / (1024**2), 1)
            resultado["vram_reservada_mb"] = round(torch.cuda.max_memory_reserved() / (1024**2), 1)
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
