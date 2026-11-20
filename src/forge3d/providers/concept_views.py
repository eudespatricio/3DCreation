"""Orquestracao cloud (1 ou 4 vistas ortograficas) e normalizacao PNG para ``concept``."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from ..errors import erro_provider_run
from .concept_prompt import (
    SUFIXO_PADRAO,
    VISTAS_ORTOGRAFICAS,
    negativo_efetivo,
    prompt_para_vista,
    sufixo_efetivo,
)


def _normalizar_png_real(png: Path) -> tuple[int, int, str]:
    """Re-codifica a imagem como PNG real e devolve (largura, altura, sha256) reais (D-05)."""
    from PIL import Image

    with Image.open(png) as img:
        img.load()
        largura, altura = img.size
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        img.save(png, format="PNG")
    digesto = hashlib.sha256(png.read_bytes()).hexdigest()
    return largura, altura, digesto


def _mascara_fg_amostra(rgba_bytes: bytes, w: int, h: int) -> tuple[list[list[int]], tuple[int, int, int, int]]:
    transparentes = sum(1 for i in range(3, len(rgba_bytes), 4) if rgba_bytes[i] < 240)
    if transparentes >= max(4, int(0.05 * w * h)):
        fg = [[1 if rgba_bytes[(y * w + x) * 4 + 3] >= 32 else 0 for x in range(w)] for y in range(h)]
        return fg, (0, 0, 0, 0)

    ck = max(1, min(4, w // 12, h // 12))
    amostras = [
        (rgba_bytes[((y0 + dy) * w + (x0 + dx)) * 4], rgba_bytes[((y0 + dy) * w + (x0 + dx)) * 4 + 1], rgba_bytes[((y0 + dy) * w + (x0 + dx)) * 4 + 2])
        for x0, y0 in ((0, 0), (w - ck, 0), (0, h - ck), (w - ck, h - ck))
        for dy in range(ck)
        for dx in range(ck)
    ]
    mid = len(amostras) // 2
    med_r, med_g, med_b = (sorted(c[k] for c in amostras)[mid] for k in range(3))
    dists_c = sorted(math.sqrt((c[0] - med_r) ** 2 + (c[1] - med_g) ** 2 + (c[2] - med_b) ** 2) for c in amostras)
    p90_c = dists_c[min(len(dists_c) - 1, int(len(dists_c) * 0.9))]
    limiar_sq = max(24.0, min(60.0, p90_c + 14.0)) ** 2
    fg = [
        [
            1 if ((rgba_bytes[(y * w + x) * 4] - med_r) ** 2 + (rgba_bytes[(y * w + x) * 4 + 1] - med_g) ** 2 + (rgba_bytes[(y * w + x) * 4 + 2] - med_b) ** 2) > limiar_sq else 0
            for x in range(w)
        ]
        for y in range(h)
    ]
    return fg, (med_r, med_g, med_b, 255)


def _blobs_horizontais(col_dens: list[float], x0: int, x1: int) -> list[tuple[int, int]]:
    blobs: list[tuple[int, int]] = []
    cur_ini: int | None = None
    for x in range(x0, x1 + 1):
        ativo = x < x1 and col_dens[x] > 0.02
        if ativo and cur_ini is None:
            cur_ini = x
        elif not ativo and cur_ini is not None:
            if blobs and (cur_ini - blobs[-1][1]) <= 1:
                blobs[-1] = (blobs[-1][0], x)
            else:
                blobs.append((cur_ini, x))
            cur_ini = None
    return blobs


def _analisar_multiplas_figuras(png: Path) -> tuple[bool, float, tuple[int, int, int, int]]:
    from PIL import Image

    if not png.is_file():
        return False, 0.5, (220, 220, 220, 255)
    try:
        with Image.open(png) as img:
            rgba = img.convert("RGBA")
            ow, oh = rgba.size
            if ow < 16 or oh < 16:
                return False, 0.5, (220, 220, 220, 255)
            escala = min(1.0, 128.0 / max(ow, oh))
            w, h = max(16, int(round(ow * escala))), max(16, int(round(oh * escala)))
            if (w, h) != (ow, oh):
                rgba = rgba.resize((w, h), Image.Resampling.BILINEAR)
            raw = rgba.tobytes()
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"[concept] aviso falha ao inspecionar {png.name}: {exc}\n")
        return False, 0.5, (220, 220, 220, 255)

    fg, bg_rgba = _mascara_fg_amostra(raw, w, h)
    total_fg = sum(sum(row) for row in fg)
    if total_fg < max(16, int(0.03 * w * h)):
        return False, 0.5, bg_rgba

    col_dens = [sum(fg[y][x] for y in range(h)) / h for x in range(w)]
    b0, b1 = int(w * 0.25), min(w, int(math.ceil(w * 0.75)))
    min_gap_cols = max(1, int(math.ceil(w * 0.03)))
    gaps: list[tuple[int, int]] = []
    g_ini: int | None = None
    for x in range(b0, b1 + 1):
        vazio = x < b1 and col_dens[x] <= 0.02
        if vazio and g_ini is None:
            g_ini = x
        elif not vazio and g_ini is not None:
            if (x - g_ini) >= min_gap_cols:
                gaps.append((g_ini, x))
            g_ini = None

    def _eh_blob_grande(bx0: int, bx1: int) -> bool:
        b_fg = sum(fg[y][x] for y in range(h) for x in range(bx0, bx1))
        if b_fg < total_fg * 0.15 or b_fg < (w * h) * 0.015:
            return False
        return (sum(1 for y in range(h) if any(fg[y][x] for x in range(bx0, bx1))) / h) >= 0.40

    gaps.sort(key=lambda g: (-(g[1] - g[0]), abs(((g[0] + g[1]) * 0.5) - (w * 0.5))))
    for gx0, gx1 in gaps:
        if any(_eh_blob_grande(a, b) for a, b in _blobs_horizontais(col_dens, 0, gx0)) and any(
            _eh_blob_grande(a, b) for a, b in _blobs_horizontais(col_dens, gx1, w)
        ):
            return True, ((gx0 + gx1) * 0.5) / w, bg_rgba
    return False, 0.5, bg_rgba


def _detectar_multiplas_figuras(png: Path) -> bool:
    """Detecta turnaround/dupla figura lado a lado via densidade de colunas foreground."""
    return _analisar_multiplas_figuras(png)[0]


def _patch_fg_normalizado(img: Any) -> bytes:
    from PIL import Image

    rgba = img.convert("RGBA")
    sw, sh = min(64, max(8, rgba.width)), min(64, max(8, rgba.height))
    amostra = rgba.resize((sw, sh), Image.Resampling.BILINEAR)
    fg, bg_rgba = _mascara_fg_amostra(amostra.tobytes(), sw, sh)
    xs = [x for y in range(sh) for x in range(sw) if fg[y][x]]
    ys = [y for y in range(sh) for x in range(sw) if fg[y][x]]
    if xs and ys and max(xs) > min(xs) and max(ys) > min(ys):
        rx0 = int(min(xs) * rgba.width / sw)
        rx1 = max(rx0 + 1, int((max(xs) + 1) * rgba.width / sw))
        ry0 = int(min(ys) * rgba.height / sh)
        ry1 = max(ry0 + 1, int((max(ys) + 1) * rgba.height / sh))
        rec = rgba.crop((rx0, ry0, rx1, ry1))
    else:
        rec = rgba
    fundo = Image.new("RGBA", rec.size, (bg_rgba[0], bg_rgba[1], bg_rgba[2], 255))
    comp = Image.alpha_composite(fundo, rec).convert("RGB")
    return comp.resize((32, 48), Image.Resampling.BILINEAR).tobytes()


def _recortar_metade_direita_se_frontal_na_esquerda(
    vista_png: Path,
    front_png: Path,
    corte_frac: float,
    bg_rgba: tuple[int, int, int, int],
) -> bool:
    from PIL import Image

    if not vista_png.is_file() or not front_png.is_file():
        return False
    with Image.open(vista_png) as v_im, Image.open(front_png) as f_im:
        v_rgba = v_im.convert("RGBA")
        f_rgba = f_im.convert("RGBA")
    vw, vh = v_rgba.size
    x_split = max(1, min(vw - 1, int(round(vw * corte_frac))))
    esq = v_rgba.crop((0, 0, x_split, vh))
    dir_metade = v_rgba.crop((x_split, 0, vw, vh))
    b_front = _patch_fg_normalizado(f_rgba)
    b_esq = _patch_fg_normalizado(esq)
    b_dir = _patch_fg_normalizado(dir_metade)
    mae_esq = sum(abs(a - b) for a, b in zip(b_esq, b_front)) / max(1, len(b_front))
    mae_dir = sum(abs(a - b) for a, b in zip(b_dir, b_front)) / max(1, len(b_front))
    if mae_esq + 1.5 >= mae_dir:
        return False

    canvas = Image.new("RGBA", (vw, vh), bg_rgba)
    canvas.paste(dir_metade, ((vw - dir_metade.width) // 2, 0))
    canvas.save(vista_png, format="PNG")
    return not _detectar_multiplas_figuras(vista_png)


def _chamar_gemini_conceito(cloud_ai_mod: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    fn = cloud_ai_mod.gerar_conceito_gemini
    try:
        params = inspect.signature(fn).parameters
        aceita_dicas = "dicas_composicao" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
    except (TypeError, ValueError):
        aceita_dicas = False
    if aceita_dicas:
        kwargs["dicas_composicao"] = True
    return fn(*args, **kwargs)


def resolver_vistas(item: dict | None) -> int:
    """Resolve numero de vistas ortograficas de concept (1 ou 4)."""
    if not item or item.get("vistas") is None:
        return 1
    bruto = item.get("vistas")
    if isinstance(bruto, bool) or not isinstance(bruto, (int, str)):
        raise ValueError(f"vistas invalido: {bruto!r} (use 1 ou 4)")
    try:
        vistas = int(bruto)
    except ValueError as exc:
        raise ValueError(f"vistas invalido: {bruto!r} (use 1 ou 4)") from exc
    if vistas not in (1, 4):
        raise ValueError(f"vistas invalido: {vistas} (use 1 ou 4)")
    return vistas


def escrever_metadados_concept(destino: Path, resultado: dict[str, Any]) -> tuple[Path, Path]:
    """Grava ``concept_resultado.json`` completo e o sidecar canonico ``concept.json``."""
    resultado_path = destino / "concept_resultado.json"
    resultado_path.write_text(
        json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    campos_sidecar = (
        "prompt_final",
        "negativo",
        "modelo",
        "seed",
        "revisao",
        "versao",
        "provider_conceito",
        "largura_real",
        "altura_real",
        "referencia_estilo",
        "referencia_estilo_sha256",
        "vistas",
    )
    sidecar = {k: resultado[k] for k in campos_sidecar if k in resultado}
    concept_json_path = destino / "concept.json"
    concept_json_path.write_text(
        json.dumps(sidecar, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return resultado_path, concept_json_path


def gerar_conceito_cloud(
    item: dict,
    destino: Path,
    *,
    prov_conceito: str,
    versao: str,
    cloud_ai_mod: Any,
    normalizar_fn: Callable[[Path], tuple[int, int, str]],
) -> dict[str, Any]:
    """Gera concept via Gemini/Higgsfield em 1 vista ou 4 vistas ortograficas (Gemini)."""
    try:
        vistas = resolver_vistas(item)
        negative_final = negativo_efetivo(item)
        seed = int(item.get("seed", 20261110))
    except (TypeError, ValueError) as exc:
        raise erro_provider_run(str(exc), id=item.get("id")) from exc

    prompt = (item.get("prompt") or "").strip()
    ref_item = item.get("referencia_estilo")
    ref_png = Path(str(ref_item)).expanduser() if ref_item else None
    largura = int(os.environ.get("FORGE3D_CONCEPT_LARGURA", "512").strip() or "512")
    altura = int(os.environ.get("FORGE3D_CONCEPT_ALTURA", "512").strip() or "512")
    sufixo = os.environ.get("FORGE3D_CONCEPT_SUFIXO", SUFIXO_PADRAO).strip()
    efetivo = sufixo_efetivo(prompt, sufixo)
    prompt_final = f"{prompt}, {efetivo}" if efetivo else prompt

    if vistas == 1:
        png = destino / "concept.png"
        if prov_conceito == "gemini":
            resultado = _chamar_gemini_conceito(
                cloud_ai_mod,
                prompt_final,
                negative_final,
                seed,
                png,
                largura=largura,
                altura=altura,
                item_id=item.get("id"),
                referencia_png=ref_png,
            )
        else:
            resultado = cloud_ai_mod.gerar_conceito_higgsfield(
                prompt_final,
                negative_final,
                seed,
                png,
                largura=largura,
                altura=altura,
                item_id=item.get("id"),
            )
        resultado["tempo_provider_s"] = resultado.get("tempo_s", 0.0)
        resultado["versao"] = versao
        resultado["prompt_final"] = prompt_final
        resultado["negativo"] = negative_final
        resultado["pose"] = ""
        largura_real, altura_real, digesto_png = normalizar_fn(png)
        resultado["largura_real"] = largura_real
        resultado["altura_real"] = altura_real
        resultado["revisao"] = digesto_png[:12]
        escrever_metadados_concept(destino, resultado)
        return {"png": png, "meta": resultado}

    if prov_conceito != "gemini":
        raise erro_provider_run(
            f"vistas=4 exige provider 'gemini' (recebido '{prov_conceito}')",
            id=item.get("id"),
            modelo=prov_conceito,
        )
    modelo = cloud_ai_mod.modelo_gemini_escolhido()
    if str(modelo).startswith("imagen-"):
        raise erro_provider_run(
            "vistas=4 exige modelo gemini-* (ex.: gemini-nano-banana-2.1)",
            id=item.get("id"),
            modelo="gemini",
        )

    vistas_paths: dict[str, str] = {}
    vistas_detalhes: dict[str, dict[str, Any]] = {}
    resultados_vistas: list[dict[str, Any]] = []
    for idx, vista in enumerate(VISTAS_ORTOGRAFICAS):
        vista_png = destino / f"concept_{vista}.png"
        vista_prompt = prompt_para_vista(prompt, vista, sufixo)
        seed_vista = seed + idx
        ref_para_chamada = (
            ref_png
            if ref_png is not None
            else (None if vista == "front" else Path(vistas_paths["front"]))
        )
        res_v = _chamar_gemini_conceito(
            cloud_ai_mod,
            vista_prompt,
            negative_final,
            seed_vista,
            vista_png,
            largura=largura,
            altura=altura,
            item_id=item.get("id"),
            referencia_png=ref_para_chamada,
        )
        resultados_vistas.append(res_v)
        w_real, h_real, digesto_vista = normalizar_fn(vista_png)
        detalhe_v: dict[str, Any] = {
            "arquivo": vista_png.name,
            "largura_real": w_real,
            "altura_real": h_real,
            "revisao": digesto_vista[:12],
            "seed": seed_vista,
        }
        incluir_vista = True
        if vista in ("back", "left", "right") and _detectar_multiplas_figuras(vista_png):
            seed_retry = seed_vista + 100
            prompt_retry = f"{vista_prompt}, strictly ONE single character only, NO side-by-side comparison, NO front view"
            res_retry = _chamar_gemini_conceito(
                cloud_ai_mod, prompt_retry, negative_final, seed_retry, vista_png,
                largura=largura, altura=altura, item_id=item.get("id"), referencia_png=ref_para_chamada,
            )
            resultados_vistas.append(res_retry)
            w_real, h_real, digesto_vista = normalizar_fn(vista_png)
            detalhe_v.update({"largura_real": w_real, "altura_real": h_real, "revisao": digesto_vista[:12], "seed": seed_retry, "retentativa_multiplas_figuras": True})
            mult_ainda, corte_frac, bg_rgba = _analisar_multiplas_figuras(vista_png)
            if mult_ainda:
                if _recortar_metade_direita_se_frontal_na_esquerda(vista_png, destino / "concept_front.png", corte_frac, bg_rgba):
                    w_real, h_real, digesto_vista = normalizar_fn(vista_png)
                    detalhe_v.update({"largura_real": w_real, "altura_real": h_real, "revisao": digesto_vista[:12], "auto_crop": "right_half"})
                else:
                    incluir_vista = False
                    detalhe_v["omitida"] = "multiplas_figuras"
        if incluir_vista:
            vistas_paths[vista] = str(vista_png)
        vistas_detalhes[vista] = detalhe_v

    png = destino / "concept.png"
    shutil.copyfile(destino / "concept_front.png", png)

    res_front = resultados_vistas[0]
    tempo_total = round(sum(float(r.get("tempo_s", 0.0)) for r in resultados_vistas), 3)
    resultado = dict(res_front)
    resultado["tempo_s"] = tempo_total
    resultado["tempo_provider_s"] = tempo_total
    resultado["versao"] = versao
    resultado["seed"] = seed
    resultado["prompt_final"] = prompt_final
    resultado["negativo"] = negative_final
    resultado["pose"] = ""
    resultado["largura_real"] = vistas_detalhes["front"]["largura_real"]
    resultado["altura_real"] = vistas_detalhes["front"]["altura_real"]
    resultado["revisao"] = vistas_detalhes["front"]["revisao"]
    resultado["vistas"] = vistas_paths
    resultado["vistas_detalhes"] = vistas_detalhes
    resultado["referencia_estilo"] = str(ref_png) if ref_png is not None else None
    resultado["referencia_estilo_sha256"] = (
        res_front.get("referencia_estilo_sha256") if ref_png is not None else None
    )
    escrever_metadados_concept(destino, resultado)
    return {"png": png, "meta": resultado}


def gerar_conceito_sd15(
    item: dict,
    destino: Path,
    *,
    comando: list[str],
    info: dict[str, Any],
    versao: str,
    licenca_base: dict[str, Any],
    licenca_openpose: dict[str, Any],
    timeout_s: int,
    subprocess_mod: Any,
    normalizar_fn: Callable[[Path], tuple[int, int, str]],
) -> dict[str, Any]:
    """Executa inferencia SD1.5 local em subprocesso (I9) e normaliza PNG/metadados."""
    png: Path = info["png"]
    resultado_path: Path = info["resultado_path"]
    if resultado_path.exists():
        resultado_path.unlink()

    env = dict(os.environ)
    env.setdefault("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    env.setdefault("PYTHONUNBUFFERED", "1")

    t0 = time.monotonic()
    try:
        proc = subprocess_mod.run(
            comando, check=False, capture_output=True, text=True, timeout=timeout_s, env=env
        )
    except subprocess.TimeoutExpired:
        raise erro_provider_run(
            f"timeout de {timeout_s}s na geracao de concept", id=item.get("id")
        ) from None
    except OSError as exc:
        raise erro_provider_run(
            f"falha ao executar a venv de concept: {exc}", id=item.get("id")
        ) from exc

    if not resultado_path.is_file():
        raise erro_provider_run(
            "concept nao escreveu resultado.json",
            id=item.get("id"),
            exit=proc.returncode,
            stderr=(proc.stderr or proc.stdout or "")[-2000:],
        )
    try:
        resultado = json.loads(resultado_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise erro_provider_run(f"resultado.json do concept ilegivel: {exc}") from exc
    if not resultado.get("ok"):
        raise erro_provider_run(
            f"concept falhou: {resultado.get('erro')}",
            id=item.get("id"),
            stderr=(resultado.get("traceback") or "")[-2000:],
        )
    if not png.is_file():
        raise erro_provider_run(f"concept nao produziu PNG em {destino}", id=item.get("id"))

    if resultado.get("prompt_truncado"):
        print(
            "aviso: prompt do concept truncado de "
            f"{resultado.get('prompt_tokens')} para "
            f"{resultado.get('prompt_tokens_efetivo')} tokens (limite CLIP 77)",
            file=sys.stderr,
        )

    lic = dict(licenca_base)
    if info["pose"]:
        lic["notice"] = f"{lic['notice'].rstrip()} {licenca_openpose['notice']}".strip()

    resultado["provider_conceito"] = "sd15"
    resultado["tempo_provider_s"] = round(time.monotonic() - t0, 3)
    resultado["versao"] = versao
    resultado["licenca"] = lic
    resultado["prompt_final"] = info["prompt_final"]
    resultado["negativo"] = info["negative_final"]
    resultado["pose"] = info["pose"]
    if info["pose"]:
        resultado["controlnet"] = info["controlnet"]
        resultado["pose_imagem"] = str(info["pose_png"])
    largura_real, altura_real, _digesto_png = normalizar_fn(png)
    resultado["largura_real"] = largura_real
    resultado["altura_real"] = altura_real
    escrever_metadados_concept(destino, resultado)
    return {"png": png, "meta": resultado}
