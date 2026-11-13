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
import gc
import inspect
import json
import os
import time
import traceback
from pathlib import Path
from typing import Any


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
    p.add_argument(
        "--rembg-modelo",
        default=os.environ.get("FORGE3D_REMBG_MODELO", "birefnet-general"),
        help="modelo rembg para recorte (default: birefnet-general, fallback offline: u2net)",
    )
    return p.parse_args()


def _limpar_ruido_alfa(imagem, alfa_minimo: int = 24):
    """Zera pixels quase transparentes (< ``alfa_minimo``) sem alterar RGB restante."""
    from PIL import Image

    rgba = imagem.convert("RGBA")
    raw = bytearray(rgba.tobytes())
    for i in range(0, len(raw), 4):
        if raw[i + 3] < alfa_minimo:
            raw[i] = 0
            raw[i + 1] = 0
            raw[i + 2] = 0
            raw[i + 3] = 0
    return Image.frombytes("RGBA", rgba.size, bytes(raw))


def _desmultiplicar_alfa(imagem, alfa_minimo: int = 24):
    """Desfaz pre-multiplicacao do rembg (Image.composite) e zera ruido < ``alfa_minimo``."""
    from PIL import Image

    rgba = imagem.convert("RGBA")
    raw = bytearray(rgba.tobytes())
    for i in range(0, len(raw), 4):
        a = raw[i + 3]
        if a < alfa_minimo:
            raw[i] = 0
            raw[i + 1] = 0
            raw[i + 2] = 0
            raw[i + 3] = 0
        elif a < 255:
            # rembg.naive_cutout usa Image.composite(..., 0, mask), que multiplica RGB por alpha.
            raw[i] = min(255, round(raw[i] * 255 / a))
            raw[i + 1] = min(255, round(raw[i + 1] * 255 / a))
            raw[i + 2] = min(255, round(raw[i + 2] * 255 / a))
    return Image.frombytes("RGBA", rgba.size, bytes(raw))


def _erodir_alfa_seguro(
    rgba,
    alfa_minimo: int = 24,
    razao_opaca_minima: float = 0.08,
):
    """Erode 1px na mascara alfa apenas se a area opaca restante ficar >= ``razao_opaca_minima``."""
    from PIL import ImageFilter

    alfa = rgba.getchannel("A")
    alfa_erodido = alfa.filter(ImageFilter.MinFilter(3))
    dados = alfa_erodido.tobytes()
    total = max(len(dados), 1)
    opacos = sum(1 for val in dados if val >= alfa_minimo)
    if opacos / total < razao_opaca_minima:
        return rgba
    resultado = rgba.copy()
    resultado.putalpha(alfa_erodido)
    return resultado


def _bleed_rgb_borda_transparente(rgba, raio: int = 6):
    """Preenche pixels alpha==0 com a cor da borda mais proxima (sem blur no interior opaco)."""
    from PIL import Image, ImageFilter

    img = rgba.convert("RGBA")
    r_ch, g_ch, b_ch, a_ch = img.split()
    if a_ch.getextrema()[0] == 255 or a_ch.getextrema()[1] == 0:
        return img

    mask_bin = a_ch.point(lambda a: 255 if a >= 128 else 0)
    m_bytes = mask_bin.tobytes()
    mask_f = mask_bin.filter(ImageFilter.BoxBlur(raio)).tobytes()
    a_bytes = a_ch.tobytes()

    canais_out: list[Any] = []
    for canal in (r_ch, g_ch, b_ch):
        orig = canal.tobytes()
        zerado = Image.frombytes(
            "L",
            img.size,
            bytes(v if m else 0 for v, m in zip(orig, m_bytes)),
        )
        borrado = zerado.filter(ImageFilter.BoxBlur(raio)).tobytes()
        ajustado = bytes(
            orig[i]
            if a_bytes[i] >= 128
            else (min(255, round(borrado[i] * 255.0 / mask_f[i])) if mask_f[i] > 0 else orig[i])
            for i in range(len(orig))
        )
        canais_out.append(Image.frombytes("L", img.size, ajustado))
    return Image.merge("RGBA", (*canais_out, a_ch))


def _gerar_cutout_para_textura(
    imagem,
    *,
    desmultiplicar: bool,
    alfa_minimo: int = 160,
    razao_opaca_minima: float = 0.08,
):
    """Prepara RGBA alinhado com borda limpa e bleed de cor para projecao UV sem halo."""
    from PIL import Image

    rgba = imagem.convert("RGBA")
    if desmultiplicar:
        rgba = _desmultiplicar_alfa(rgba, alfa_minimo=alfa_minimo)
    # Mantem nucleo opaco sem comer a silhueta dos membros; borda alpha<160 vira 0 + RGB bleed.
    raw = bytearray(rgba.tobytes())
    for i in range(0, len(raw), 4):
        if raw[i + 3] < alfa_minimo:
            raw[i + 3] = 0
        else:
            raw[i + 3] = 255
    rgba = Image.frombytes("RGBA", rgba.size, bytes(raw))
    if desmultiplicar:
        rgba = _erodir_alfa_seguro(
            rgba,
            alfa_minimo=200,
            razao_opaca_minima=razao_opaca_minima,
        )
    return _bleed_rgb_borda_transparente(rgba, raio=6)


def _compor_cutout_neutro(
    imagem,
    *,
    desmultiplicar: bool,
    alfa_minimo: int = 24,
    razao_opaca_minima: float = 0.08,
):
    """Compoe recorte RGBA sobre cinza neutro (128, 128, 128) sem halo escuro."""
    from PIL import Image

    rgba = imagem.convert("RGBA")
    if desmultiplicar:
        rgba = _desmultiplicar_alfa(rgba, alfa_minimo=alfa_minimo)
        rgba = _erodir_alfa_seguro(
            rgba,
            alfa_minimo=alfa_minimo,
            razao_opaca_minima=razao_opaca_minima,
        )
    fundo = Image.new("RGBA", rgba.size, (128, 128, 128, 255))
    return Image.alpha_composite(fundo, rgba).convert("RGB")


def _criar_sessao_rembg(modelo_nome: str = "birefnet-general") -> tuple[Any, str, bool]:
    """Cria sessao rembg com ``modelo_nome`` e cai em ``u2net`` se rede/download falhar."""
    import rembg

    alvo = (modelo_nome or "birefnet-general").strip() or "birefnet-general"
    try:
        sig = inspect.signature(rembg.new_session)
        params = [
            p
            for p in sig.parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)
        ]
        aceita_arg = bool(params)
    except (TypeError, ValueError):
        aceita_arg = True

    if not aceita_arg:
        return rembg.new_session(), "u2net", False

    usar_sess_opts = False
    if getattr(rembg, "__file__", None):
        try:
            usar_sess_opts = "sess_opts" in inspect.signature(rembg.new_session).parameters
        except (TypeError, ValueError):
            usar_sess_opts = False
    sess_kwargs: dict[str, Any] = {}
    if usar_sess_opts:
        try:
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.enable_mem_pattern = False
            opts.enable_cpu_mem_arena = False
            sess_kwargs["sess_opts"] = opts
        except Exception:  # noqa: BLE001 - fallback sem SessionOptions se onnxruntime indisponivel
            sess_kwargs = {}

    try:
        return rembg.new_session(alvo, **sess_kwargs), alvo, False
    except ValueError as exc:
        if "No session class found" in str(exc) or alvo == "u2net":
            raise
    except Exception:  # noqa: BLE001 - fallback offline para u2net em cache
        if alvo == "u2net":
            raise
    return rembg.new_session("u2net", **sess_kwargs), "u2net", True


def _preparar_imagem(
    caminho: str,
    remover_fundo: bool,
    foreground_ratio: float,
    rembg_modelo: str | None = None,
    rembg_info: dict[str, Any] | None = None,
    rgba_textura_out: list[Any] | None = None,
):
    from PIL import Image

    imagem = Image.open(caminho).convert("RGBA")
    if max(imagem.size) > 1024:
        fator = 1024.0 / float(max(imagem.size))
        novo_tam = (max(1, round(imagem.width * fator)), max(1, round(imagem.height * fator)))
        imagem = imagem.resize(novo_tam, Image.Resampling.LANCZOS)
    if remover_fundo:
        from tsr.utils import remove_background, resize_foreground

        era_opaca = imagem.getchannel("A").getextrema()[0] == 255
        modelo_solicitado = (
            rembg_modelo or os.environ.get("FORGE3D_REMBG_MODELO", "birefnet-general")
        )
        sessao, modelo_usado, fallback = _criar_sessao_rembg(modelo_solicitado)
        if rembg_info is not None:
            rembg_info["rembg_modelo"] = modelo_usado
            rembg_info["rembg_fallback"] = fallback
        try:
            recortada = remove_background(imagem, sessao)
        finally:
            del sessao
            gc.collect()
        if era_opaca and recortada.convert("RGBA").getchannel("A").getextrema()[1] >= 24:
            recortada = _limpar_ruido_alfa(recortada)
        recortada = resize_foreground(recortada, foreground_ratio)
        if rgba_textura_out is not None:
            rgba_textura_out.append(
                _gerar_cutout_para_textura(recortada, desmultiplicar=era_opaca)
            )
        return _compor_cutout_neutro(recortada, desmultiplicar=era_opaca)
    if rembg_info is not None:
        rembg_info["rembg_modelo"] = None
        rembg_info["rembg_fallback"] = False
    if rgba_textura_out is not None:
        rgba_textura_out.append(_gerar_cutout_para_textura(imagem, desmultiplicar=False))
    # fundo neutro: compoe alfa reto sobre cinza medio (o modelo foi treinado assim)
    return _compor_cutout_neutro(imagem, desmultiplicar=False)


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

        rembg_info: dict[str, Any] = {}
        rgba_tex_holder: list[Any] = []
        imagem = _preparar_imagem(
            args.imagem,
            args.remover_fundo,
            args.foreground_ratio,
            rembg_modelo=args.rembg_modelo,
            rembg_info=rembg_info,
            rgba_textura_out=rgba_tex_holder,
        )
        resultado.update(rembg_info)
        imagem.save(saida_dir / "input.png")
        if rgba_tex_holder:
            rgba_tex_holder[0].save(saida_dir / "input_rgba.png")

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
        # TripoSR extrai em +Z up, +X front, +Y camera-right (tsr/utils.py);
        # glTF exige +Y up e os perfis usam -Z frente: (-y, z, -x) tem det=+1 (sem espelho).
        malha.apply_transform(
            [
                [0.0, -1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [-1.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
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
