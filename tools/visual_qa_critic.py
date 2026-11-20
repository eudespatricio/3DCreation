#!/usr/bin/env python3
"""Critico deterministico de QA visual (e opcional Gemini Vision) para turntables PNG e G15.

Verifica em folhas 2x2 (``render_preview.py --turntable``), renders avulsos ou pares concept->render:
1. Faixa preta / borrao na testa (``forehead_smear``)
2. Assimetria ou manchas nas pernas (``leg_asymmetry`` / ``leg_mottling``)
3. Silhueta e enquadramento (``silhouette_blank`` / ``silhouette_clipped``)
4. Fidelidade concept->3D G15 via ``--concept <path>`` (``avaliar_fidelidade_concept_3d``)
5. Opcional ``--gemini``: avaliacao multimodal com ``gemini-4-hydrogen`` via ``cloud_ai``

Uso:
    python tools/visual_qa_critic.py <turntable_png> [--json] [--gemini]
    python tools/visual_qa_critic.py <render_png> --concept <concept_png> [--json]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from PIL import Image

RAIZ_REPO = Path(__file__).resolve().parents[1]
if str(RAIZ_REPO / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO / "src"))

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from visual_qa_fidelidade import (  # noqa: E402
    _analisar_mascara,
    _checar_silhueta_e_enquadramento,
    _eh_foreground,
    _estimar_fundo_rgb,
    _fg_by_y,
    _luminancia,
    _media_rgb,
    _mediana_int,
    _reduzir_para_analise,
    _tem_alfa_transparente,
    avaliar_fidelidade_concept_3d,
    avaliar_fidelidade_g15,
    dividir_quadrantes,
)

__all__ = [
    "avaliar_fidelidade_concept_3d",
    "avaliar_fidelidade_g15",
    "avaliar_turntable_png",
    "dividir_quadrantes",
    "main",
]

_REEXPORTS = (
    _eh_foreground,
    _estimar_fundo_rgb,
    _mediana_int,
    _reduzir_para_analise,
    _tem_alfa_transparente,
)


def _checar_testa_manchada(info_front: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    bbox = info_front["bbox"]
    if bbox is None:
        return [], {"aplicado": False}
    fx0, fy0, fx1, fy1 = bbox
    fw = max(1, fx1 - fx0 + 1)
    fh = max(1, fy1 - fy0 + 1)
    cx = (fx0 + fx1) / 2.0

    testa_y0, testa_y1 = fy0 + 0.03 * fh, fy0 + 0.10 * fh
    bochecha_y0, bochecha_y1 = fy0 + 0.10 * fh, fy0 + 0.19 * fh
    x_half_t = 0.14 * fw
    x_half_b = 0.16 * fw

    testa_px: list[tuple[int, int, int]] = []
    bochecha_px: list[tuple[int, int, int]] = []
    for x, y, rgb in info_front["fg_coords"]:
        if testa_y0 <= y < testa_y1 and abs(x - cx) <= x_half_t:
            testa_px.append(rgb)
        elif bochecha_y0 <= y < bochecha_y1 and abs(x - cx) <= x_half_b:
            bochecha_px.append(rgb)

    if len(testa_px) < 4 or len(bochecha_px) < 4:
        return [], {"aplicado": False, "n_testa": len(testa_px), "n_bochecha": len(bochecha_px)}

    lums_t = [_luminancia(*p) for p in testa_px]
    lums_b = [_luminancia(*p) for p in bochecha_px]
    lum_t = sum(lums_t) / len(lums_t)
    lum_b = sum(lums_b) / len(lums_b)
    frac_preta = sum(1 for v in lums_t if v < 0.10) / float(len(lums_t))

    mean_t = _media_rgb(testa_px)
    mean_b = _media_rgb(bochecha_px)
    chrom_delta = math.sqrt(sum((a - b) ** 2 for a, b in zip(mean_t, mean_b)))
    lum_delta = lum_b - lum_t

    defeitos: list[str] = []
    if (lum_t < 0.10 or frac_preta >= 0.65) and (lum_delta >= 0.18 or chrom_delta >= 0.22):
        defeitos.append(
            f"forehead_smear (front): faixa escura na testa (lum_testa={lum_t:.3f}, "
            f"lum_bochecha={lum_b:.3f}, delta={lum_delta:.3f})"
        )

    return defeitos, {
        "aplicado": True,
        "lum_testa": round(lum_t, 4),
        "lum_bochecha": round(lum_b, 4),
        "lum_delta": round(lum_delta, 4),
        "chrom_delta": round(chrom_delta, 4),
        "frac_preta": round(frac_preta, 4),
    }


def _stats_tira(pixels: list[tuple[int, int, int]]) -> tuple[tuple[float, float, float], float]:
    if not pixels:
        return (0.0, 0.0, 0.0), 0.0
    n = float(len(pixels))
    mean_rgb = _media_rgb(pixels)
    lums = [_luminancia(*p) for p in pixels]
    mean_lum = sum(lums) / n
    var_lum = sum((v - mean_lum) ** 2 for v in lums) / n
    return mean_rgb, math.sqrt(var_lum)


def _checar_pernas(nome: str, info: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    bbox = info["bbox"]
    if bbox is None:
        return [], {"aplicado": False}
    fx0, fy0, fx1, fy1 = bbox
    fw = max(1, fx1 - fx0 + 1)
    fh = max(1, fy1 - fy0 + 1)
    cx = (fx0 + fx1) / 2.0

    leg_y0, leg_y1 = fy0 + 0.60 * fh, fy0 + 0.92 * fh
    esq_px: list[tuple[int, int, int]] = []
    dir_px: list[tuple[int, int, int]] = []
    centro_px = 0
    for x, y, rgb in info["fg_coords"]:
        if not (leg_y0 <= y < leg_y1):
            continue
        if abs(x - cx) <= max(1.0, 0.02 * fw):
            centro_px += 1
        elif (fx0 + 0.05 * fw) <= x < (cx - 0.04 * fw):
            esq_px.append(rgb)
        elif (cx + 0.04 * fw) <= x <= (fx1 - 0.05 * fw):
            dir_px.append(rgb)

    alt_leg = max(1.0, leg_y1 - leg_y0)
    larg_centro = max(1.0, 2.0 * max(1.0, 0.02 * fw))
    frac_centro = centro_px / (alt_leg * larg_centro)
    # Em props de coluna unica (ex.: obelisco/altar), a linha central e solida (sem separar duas pernas)
    if len(esq_px) < 6 or len(dir_px) < 6 or frac_centro > 0.55:
        return [], {"aplicado": False, "n_esq": len(esq_px), "n_dir": len(dir_px), "frac_centro": round(frac_centro, 4)}

    mean_l, std_l = _stats_tira(esq_px)
    mean_r, std_r = _stats_tira(dir_px)
    rgb_delta = math.sqrt(sum((a - b) ** 2 for a, b in zip(mean_l, mean_r)))

    defeitos: list[str] = []
    if rgb_delta > 0.15:
        defeitos.append(
            f"leg_asymmetry ({nome}): diferenca cromatica esquerda/direita {rgb_delta:.3f} > 0.15"
        )
    if max(std_l, std_r) > 0.22:
        defeitos.append(
            f"leg_mottling ({nome}): variancia excessiva nas pernas (std_esq={std_l:.3f}, std_dir={std_r:.3f})"
        )

    return defeitos, {
        "aplicado": True,
        "rgb_delta": round(rgb_delta, 4),
        "std_esq": round(std_l, 4),
        "std_dir": round(std_r, 4),
    }


def _checar_intrusao_botas(nome: str, info: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    bbox = info["bbox"]
    if bbox is None:
        return [], {"aplicado": False}
    fx0, fy0, fx1, fy1 = bbox
    fh = max(1, fy1 - fy0 + 1)
    cx = (fx0 + fx1) / 2.0
    h_img = info["h"]
    fg_by_y = _fg_by_y(info)

    zonas = {
        "upper": (fy0 + 0.58 * fh, fy0 + 0.70 * fh),
        "boot": (fy0 + 0.75 * fh, fy0 + 0.93 * fh),
    }

    def _coletar_interior(lado: str, zona: tuple[float, float]) -> list[tuple[int, int, int]]:
        y0, y1 = zona
        pixels: list[tuple[int, int, int]] = []
        for y in range(max(0, int(y0)), min(h_img - 1, int(y1)) + 1):
            xs_rgb = fg_by_y.get(y, [])
            lado_px = [(x, rgb) for x, rgb in xs_rgb if (x < cx if lado == "left" else x > cx)]
            if len(lado_px) < 6:
                continue
            xs = [x for x, _ in lado_px]
            min_x = min(xs)
            max_x = max(xs)
            margem = 0.16 * (max_x - min_x)
            lim_inf = min_x + margem
            lim_sup = max_x - margem
            for x, rgb in lado_px:
                if lim_inf <= x <= lim_sup:
                    pixels.append(rgb)
        return pixels

    metricas: dict[str, Any] = {}
    defeitos: list[str] = []

    for lado in ("left", "right"):
        boot_interior = _coletar_interior(lado, zonas["boot"])
        upper_interior = _coletar_interior(lado, zonas["upper"])
        n_boot = len(boot_interior)
        n_upper = len(upper_interior)
        if n_boot < 40 or n_upper < 20:
            metricas[lado] = {
                "aplicado": False,
                "n_boot": n_boot,
                "n_upper": n_upper,
                "dark": 0,
                "intrusion_fraction": 0.0,
            }
            continue

        mr = _mediana_int([p[0] for p in boot_interior])
        mg = _mediana_int([p[1] for p in boot_interior])
        mb = _mediana_int([p[2] for p in boot_interior])
        mr_up = _mediana_int([p[0] for p in upper_interior])
        mg_up = _mediana_int([p[1] for p in upper_interior])
        mb_up = _mediana_int([p[2] for p in upper_interior])

        warm_leather = mr - mb >= 16 and mr >= 55
        distinct = abs(mr - mr_up) + abs(mb - mb_up) >= 18
        if not (warm_leather and distinct):
            metricas[lado] = {
                "aplicado": False,
                "n_boot": n_boot,
                "n_upper": n_upper,
                "dark": 0,
                "intrusion_fraction": 0.0,
                "boot_median": [mr, mg, mb],
                "upper_median": [mr_up, mg_up, mb_up],
            }
            continue

        dark = [
            p for p in boot_interior
            if p[0] < mr * 0.58 and (p[0] - p[2]) < (mr - mb) * 0.45
        ]
        intrusion_fraction = len(dark) / float(n_boot)
        if intrusion_fraction >= 0.008 and len(dark) >= 8:
            defeitos.append(
                f"boot_interpenetration ({nome}/{lado}): intrusao escura na bota "
                f"({intrusion_fraction:.3f})"
            )
        metricas[lado] = {
            "aplicado": True,
            "n_boot": n_boot,
            "n_upper": n_upper,
            "dark": len(dark),
            "intrusion_fraction": round(intrusion_fraction, 4),
            "boot_median": [mr, mg, mb],
            "upper_median": [mr_up, mg_up, mb_up],
        }

    return defeitos, metricas


def _checar_continuidade_torso(info_front: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    bbox = info_front["bbox"]
    if bbox is None:
        return [], {"aplicado": False}
    fx0, fy0, fx1, fy1 = bbox
    fw = max(1, fx1 - fx0 + 1)
    fh = max(1, fy1 - fy0 + 1)
    cx = (fx0 + fx1) / 2.0
    h_img = info_front["h"]
    fg_by_y = _fg_by_y(info_front)

    upper_y0, upper_y1 = fy0 + 0.22 * fh, fy0 + 0.33 * fh
    lower_y0, lower_y1 = fy0 + 0.36 * fh, fy0 + 0.47 * fh
    margem_x = 0.14 * fw
    borda_x = 3

    def _pixels_zona(y0: float, y1: float) -> tuple[list[tuple[int, int, int]], list[float]]:
        pixels: list[tuple[int, int, int]] = []
        gradientes: list[float] = []
        for y in range(max(0, int(y0)), min(h_img - 1, int(y1)) + 1):
            row = fg_by_y.get(y, [])
            fg_set = {x for x, _ in row}
            rgb_map = {x: rgb for x, rgb in row}
            x_start = max(fx0 + borda_x, int(cx - margem_x))
            x_end = min(fx1 - borda_x, int(cx + margem_x))
            for x in range(x_start, x_end + 1):
                if x in fg_set:
                    pixels.append(rgb_map[x])
            for x in range(x_start, x_end):
                if x in fg_set and (x + 1) in fg_set:
                    gradientes.append(abs(_luminancia(*rgb_map[x]) - _luminancia(*rgb_map[x + 1])))
        return pixels, gradientes

    upper_pixels, upper_grads = _pixels_zona(upper_y0, upper_y1)
    lower_pixels, lower_grads = _pixels_zona(lower_y0, lower_y1)

    n_pares_upper = len(upper_grads)
    n_pares_lower = len(lower_grads)
    if n_pares_upper < 40 or n_pares_lower < 40:
        return [], {
            "aplicado": False,
            "n_pares_superior": n_pares_upper,
            "n_pares_inferior": n_pares_lower,
            "upper_grad": round(sum(upper_grads) / n_pares_upper, 4) if n_pares_upper else 0.0,
            "lower_grad": round(sum(lower_grads) / n_pares_lower, 4) if n_pares_lower else 0.0,
            "ratio": 0.0,
            "chrom_delta": 0.0,
        }

    mean_upper = _media_rgb(upper_pixels)
    mean_lower = _media_rgb(lower_pixels)
    chrom_delta = math.sqrt(sum((a - b) ** 2 for a, b in zip(mean_upper, mean_lower)))
    upper_grad = sum(upper_grads) / n_pares_upper
    lower_grad = sum(lower_grads) / n_pares_lower
    ratio = (lower_grad / upper_grad) if upper_grad > 0.0 else 0.0

    if chrom_delta >= 0.16 or upper_grad < 0.007:
        return [], {
            "aplicado": False,
            "n_pares_superior": n_pares_upper,
            "n_pares_inferior": n_pares_lower,
            "upper_grad": round(upper_grad, 4),
            "lower_grad": round(lower_grad, 4),
            "ratio": round(ratio, 4),
            "chrom_delta": round(chrom_delta, 4),
        }

    defeitos: list[str] = []
    if ratio < 0.32:
        defeitos.append(
            f"tunic_texture_step (front): perda de textura na faixa inferior da tunica "
            f"(ratio={ratio:.3f}, upper={upper_grad:.4f}, lower={lower_grad:.4f})"
        )
    return defeitos, {
        "aplicado": True,
        "n_pares_superior": n_pares_upper,
        "n_pares_inferior": n_pares_lower,
        "upper_grad": round(upper_grad, 4),
        "lower_grad": round(lower_grad, 4),
        "ratio": round(ratio, 4),
        "chrom_delta": round(chrom_delta, 4),
    }


def avaliar_turntable_png(
    caminho_png: Path,
    *,
    usar_gemini: bool = False,
    contexto: str = "",
    layout: str = "auto",
) -> dict[str, Any]:
    """Executa verificacoes deterministicas (e opcionalmente Gemini Vision) num PNG."""
    caminho = Path(caminho_png)
    if not caminho.is_file():
        raise FileNotFoundError(f"imagem nao encontrada: {caminho}")

    with Image.open(caminho) as img:
        layout_real, quadrantes = dividir_quadrantes(img, layout=layout)

    defeitos: list[str] = []
    metricas: dict[str, Any] = {"quadrantes": {}}
    infos: dict[str, dict[str, Any]] = {}

    for qnome, quad in quadrantes.items():
        info = _analisar_mascara(quad)
        infos[qnome] = info
        d_sil, m_sil = _checar_silhueta_e_enquadramento(qnome, info)
        defeitos.extend(d_sil)
        metricas["quadrantes"][qnome] = m_sil

    d_testa, m_testa = _checar_testa_manchada(infos["front"])
    defeitos.extend(d_testa)
    metricas["forehead_smear"] = m_testa

    metricas["legs"] = {}
    for qnome in ("front", "back"):
        if qnome in infos:
            d_leg, m_leg = _checar_pernas(qnome, infos[qnome])
            defeitos.extend(d_leg)
            metricas["legs"][qnome] = m_leg

    metricas["boots"] = {}
    for qnome in ("front", "back"):
        if qnome in infos:
            d_boots, m_boots = _checar_intrusao_botas(qnome, infos[qnome])
            defeitos.extend(d_boots)
            metricas["boots"][qnome] = m_boots

    if "front" in infos:
        d_torso, m_torso = _checar_continuidade_torso(infos["front"])
        defeitos.extend(d_torso)
        metricas["torso_continuity"] = m_torso
    else:
        metricas["torso_continuity"] = {"aplicado": False}

    gemini_res: dict[str, Any] | None = None
    if usar_gemini:
        from forge3d.providers import cloud_ai

        gemini_res = cloud_ai.avaliar_qualidade_visual_gemini(caminho, contexto=contexto)
        if not gemini_res.get("aprovado", False):
            for df in gemini_res.get("defeitos", []):
                defeitos.append(f"gemini_qa: {df}")
            if not gemini_res.get("defeitos"):
                defeitos.append("gemini_qa: reprovado pela rubrica multimodal")

    aprovado = len(defeitos) == 0
    return {
        "ok": True,
        "aprovado": aprovado,
        "arquivo": str(caminho),
        "layout": layout_real,
        "defeitos": defeitos,
        "metricas": metricas,
        "gemini": gemini_res,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Critico deterministico de QA visual em PNG")
    parser.add_argument("turntable_png", type=Path, help="Caminho para o PNG turntable 2x2 ou render")
    parser.add_argument("--concept", type=Path, default=None, help="PNG do concept 2D para fidelidade G15")
    parser.add_argument("--json", action="store_true", dest="em_json", help="Imprime saida em JSON")
    parser.add_argument("--gemini", action="store_true", help="Executa rubrica complementar gemini-4-hydrogen")
    parser.add_argument("--context", default="", help="Contexto opcional enviado ao avaliador Gemini")
    parser.add_argument(
        "--layout",
        choices=("auto", "turntable", "single"),
        default="auto",
        help="Layout da imagem (padrao: auto)",
    )
    args = parser.parse_args(argv)

    try:
        if args.concept is not None:
            relatorio = avaliar_fidelidade_concept_3d(args.concept, args.turntable_png)
        else:
            relatorio = avaliar_turntable_png(
                args.turntable_png,
                usar_gemini=args.gemini,
                contexto=args.context,
                layout=args.layout,
            )
    except Exception as exc:  # noqa: BLE001 - erro reportado em JSON/stderr com codigo 2
        if args.em_json:
            print(json.dumps({"ok": False, "aprovado": False, "erro": str(exc)}, ensure_ascii=False))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    if args.em_json:
        print(json.dumps(relatorio, indent=2, ensure_ascii=False))
    else:
        status = "PASS" if relatorio["aprovado"] else "FAIL"
        if "layout" in relatorio:
            print(f"[{status}] {relatorio['arquivo']} (layout={relatorio['layout']})")
        else:
            print(
                f"[{status}] {relatorio['render']} vs {relatorio['concept']} "
                f"(iou={relatorio['iou_silhueta']:.3f}, score={relatorio['score']:.3f})"
            )
        if relatorio["defeitos"]:
            for d in relatorio["defeitos"]:
                print(f"  - {d}")
        else:
            print("  - Nenhum defeito visual detectado.")
        if relatorio.get("gemini"):
            g = relatorio["gemini"]
            print(f"  - Gemini ({g['modelo']}): nota={g['nota']:.1f}, aprovado={g['aprovado']}")

    return 0 if relatorio["aprovado"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
