"""Gate G11 de orcamento de cena AA (triangulos, draw calls e VRAM de texturas)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .profiles import ORCAMENTO_CENA_PADRAO


def _vram_mapa_mb(px: int, canais: int) -> float:
    """Estimativa de VRAM GPU por textura (ASTC/BC7 RGB=1B/px, BC4 grayscale=0.5B/px + mipmap 1.333x)."""
    bytes_por_px = 1.0 if canais >= 3 else 0.5
    return (float(px) * float(px) * bytes_por_px * 1.3333) / (1024.0 * 1024.0)


def verificar_g11_orcamento_cena(
    itens_medidos: Sequence[Mapping[str, Any]],
    limite_cena: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Gate G11: valida se a composicao simultanea de cena cabe no orcamento AA."""
    cfg = dict(ORCAMENTO_CENA_PADRAO)
    if isinstance(limite_cena, Mapping):
        for k, val in limite_cena.items():
            if val is not None:
                cfg[k] = val
        if limite_cena.get("triangulos_max") is not None:
            cfg["triangulos_cena_max"] = int(limite_cena["triangulos_max"])
        if limite_cena.get("draw_calls_max") is not None:
            cfg["draw_calls_cena_max"] = int(limite_cena["draw_calls_max"])
        if limite_cena.get("vram_mb_max") is not None:
            cfg["vram_texturas_mb_max"] = float(limite_cena["vram_mb_max"])

    teto_tris = int(cfg["triangulos_cena_max"])
    teto_dc = int(cfg["draw_calls_cena_max"])
    teto_vram = float(cfg["vram_texturas_mb_max"])
    ref_tris = max(1, int(cfg.get("capacidade_referencia_tris", 500_000)))

    tris_cena = 0
    instancing_batches: set[tuple[str, str, int]] = set()
    draw_calls_nao_instanciados = 0
    texturas_unicas: dict[str, float] = {}
    resumo_itens: list[dict[str, Any]] = []

    for it in itens_medidos:
        iid = str(it.get("id") or "?")
        tris_unit = max(0, int(it.get("tris") or 0))
        qtd = max(0, int(it.get("quantidade_cena", 1)))
        if qtd == 0:
            continue

        tris_sub = tris_unit * qtd
        tris_cena += tris_sub

        skinned = bool(it.get("skinned", False))
        primitivas = max(1, int(it.get("primitivas") or it.get("materiais") or 1))
        mesh_key = str(it.get("mesh_key") or iid)
        mat_key = str(it.get("material_key") or "palette_padrao")
        if skinned:
            draw_calls_nao_instanciados += qtd * primitivas
        else:
            for surf_idx in range(primitivas):
                instancing_batches.add((mesh_key, mat_key, surf_idx))

        for tex in it.get("texturas") or ():
            tid = str(tex.get("id") or "")
            px = int(tex.get("px") or 1024)
            canais = int(tex.get("canais") or 4)
            if tid and tid not in texturas_unicas:
                texturas_unicas[tid] = _vram_mapa_mb(px, canais)

        resumo_itens.append(
            {
                "id": iid,
                "tris_unit": tris_unit,
                "primitivas": primitivas,
                "qtd": qtd,
                "tris_cena": tris_sub,
            }
        )

    draw_calls_total = len(instancing_batches) + draw_calls_nao_instanciados
    vram_total_mb = round(sum(texturas_unicas.values()), 2)
    aprovado = (
        tris_cena <= teto_tris
        and draw_calls_total <= teto_dc
        and vram_total_mb <= teto_vram
    )
    ocupacao_ref_pct = round((tris_cena / float(ref_tris)) * 100.0, 2)
    ocupacao_teto_pct = round((tris_cena / float(max(1, teto_tris))) * 100.0, 2)

    return {
        "id": "G11",
        "status": "ok" if aprovado else "falhou",
        "medido": {
            "triangulos_cena": tris_cena,
            "ocupacao_500k_pct": ocupacao_ref_pct,
            "ocupacao_teto_80_pct": ocupacao_teto_pct,
            "draw_calls_estimados": draw_calls_total,
            "lotes_instanciados": len(instancing_batches),
            "vram_texturas_mb": vram_total_mb,
            "texturas_unicas": len(texturas_unicas),
            "itens": resumo_itens,
        },
        "limite": {
            "triangulos_cena_max": teto_tris,
            "draw_calls_cena_max": teto_dc,
            "vram_texturas_mb_max": teto_vram,
        },
        "codigo": None if aprovado else "FORGE-E-QC-SCENE",
    }
