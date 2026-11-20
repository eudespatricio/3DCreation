"""Geracao de vistas ortograficas (back/left/right) via Gemini a partir de ``origem`` aprovada."""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..errors import erro_provider_run
from .concept_prompt import SUFIXO_PADRAO, negativo_efetivo, prompt_para_vista, sufixo_efetivo
from .concept_views import (
    _analisar_multiplas_figuras, _chamar_gemini_conceito, _detectar_multiplas_figuras,
    _normalizar_png_real, _recortar_metade_direita_se_frontal_na_esquerda,
    escrever_metadados_concept, resolver_vistas,
)

VISTAS_LATERAIS_TRASEIRA = ("back", "left", "right")
normalizar_png_concept = _normalizar_png_real


def carregar_sufixo_estilo(env: dict[str, str] | None = None) -> str:
    env_map = env if env is not None else os.environ
    return str(env_map.get("FORGE3D_CONCEPT_SUFIXO", SUFIXO_PADRAO)).strip()


def _inspecionar_imagem_preservada(caminho: Path) -> tuple[int, int, str]:
    from PIL import Image

    with Image.open(caminho) as img:
        largura, altura = img.size
    return largura, altura, hashlib.sha256(caminho.read_bytes()).hexdigest()


def gerar_vistas_de_origem(
    item: dict, origem_png: Path, destino: Path, env: dict[str, str] | None = None, *,
    cloud_ai_mod: Any = None, normalizar_fn: Callable[[Path], tuple[int, int, str]] | None = None,
) -> dict[str, Any]:
    """Preserva ``origem_png`` como vista frontal e gera ``back/left/right`` via Gemini."""
    from . import cloud_ai as _default_cloud_ai
    from . import concept as _concept

    origem_path = Path(origem_png).expanduser()
    if not origem_path.is_file():
        raise erro_provider_run(f"imagem de concept inexistente: {origem_path}", id=item.get("id"))

    try:
        vistas = resolver_vistas(item)
        negative_final = negativo_efetivo(item)
        seed = int(item.get("seed", 20261110))
    except (TypeError, ValueError) as exc:
        raise erro_provider_run(str(exc), id=item.get("id")) from exc
    if vistas != 4:
        raise erro_provider_run(f"gerar_vistas_de_origem exige vistas=4 (recebido {vistas})", id=item.get("id"))

    env_map = env if env is not None else os.environ
    prov_raw = str(item.get("provider_conceito") or env_map.get("FORGE3D_PROVIDER_CONCEITO") or "gemini").strip().lower()
    if prov_raw not in ("", "auto", "gemini"):
        raise erro_provider_run(f"vistas=4 exige provider 'gemini' (recebido '{prov_raw}')", id=item.get("id"), modelo=prov_raw)

    ai_mod = cloud_ai_mod if cloud_ai_mod is not None else _default_cloud_ai
    norm_fn = normalizar_fn if normalizar_fn is not None else normalizar_png_concept
    modelo = str(ai_mod.modelo_gemini_escolhido())
    if modelo.startswith("imagen-"):
        raise erro_provider_run("vistas=4 exige modelo gemini-* (ex.: gemini-nano-banana-2.1)", id=item.get("id"), modelo="gemini")

    destino.mkdir(parents=True, exist_ok=True)
    front_png, concept_png = destino / "concept_front.png", destino / "concept.png"
    if origem_path.resolve() != front_png.resolve():
        shutil.copyfile(origem_path, front_png)
    if front_png.resolve() != concept_png.resolve():
        shutil.copyfile(front_png, concept_png)

    w_front, h_front, digesto_front = _inspecionar_imagem_preservada(front_png)
    largura = int(str(env_map.get("FORGE3D_CONCEPT_LARGURA", "512")).strip() or "512")
    altura = int(str(env_map.get("FORGE3D_CONCEPT_ALTURA", "512")).strip() or "512")
    prompt = str(item.get("prompt") or "").strip()
    sufixo = carregar_sufixo_estilo(env)
    efetivo = sufixo_efetivo(prompt, sufixo)
    prompt_final = f"{prompt}, {efetivo}" if (prompt and efetivo) else (prompt or efetivo)

    vistas_paths: dict[str, str] = {"front": str(front_png)}
    vistas_detalhes: dict[str, dict[str, Any]] = {
        "front": {
            "arquivo": front_png.name, "largura_real": w_front, "altura_real": h_front,
            "revisao": digesto_front[:12], "seed": seed, "origem_frontal_preservada": True,
        }
    }
    resultados_vistas: list[dict[str, Any]] = []
    for idx, vista in enumerate(VISTAS_LATERAIS_TRASEIRA, start=1):
        vista_png = destino / f"concept_{vista}.png"
        vista_prompt = prompt_para_vista(prompt, vista, sufixo)
        seed_vista = seed + idx
        res_v = _chamar_gemini_conceito(
            ai_mod, vista_prompt, negative_final, seed_vista, vista_png,
            largura=largura, altura=altura, item_id=item.get("id"), referencia_png=origem_path,
        )
        resultados_vistas.append(res_v)
        w_real, h_real, digesto_vista = norm_fn(vista_png)
        detalhe_v: dict[str, Any] = {
            "arquivo": vista_png.name, "largura_real": w_real, "altura_real": h_real,
            "revisao": digesto_vista[:12], "seed": seed_vista,
        }
        incluir = True
        if _detectar_multiplas_figuras(vista_png):
            seed_retry = seed_vista + 100
            prompt_retry = f"{vista_prompt}, strictly ONE single character only, NO side-by-side comparison, NO front view"
            res_retry = _chamar_gemini_conceito(
                ai_mod, prompt_retry, negative_final, seed_retry, vista_png,
                largura=largura, altura=altura, item_id=item.get("id"), referencia_png=origem_path,
            )
            resultados_vistas.append(res_retry)
            w_real, h_real, digesto_vista = norm_fn(vista_png)
            detalhe_v.update({"largura_real": w_real, "altura_real": h_real, "revisao": digesto_vista[:12], "seed": seed_retry, "retentativa_multiplas_figuras": True})
            mult_ainda, corte_frac, bg_rgba = _analisar_multiplas_figuras(vista_png)
            if mult_ainda:
                if _recortar_metade_direita_se_frontal_na_esquerda(vista_png, front_png, corte_frac, bg_rgba):
                    w_real, h_real, digesto_vista = norm_fn(vista_png)
                    detalhe_v.update({"largura_real": w_real, "altura_real": h_real, "revisao": digesto_vista[:12], "auto_crop": "right_half"})
                else:
                    incluir = False
                    detalhe_v["omitida"] = "multiplas_figuras"
        if incluir:
            vistas_paths[vista] = str(vista_png)
        vistas_detalhes[vista] = detalhe_v

    res_base = dict(resultados_vistas[0]) if resultados_vistas else {}
    tempo_total = round(sum(float(r.get("tempo_s", 0.0)) for r in resultados_vistas), 3)
    resultado: dict[str, Any] = {
        **res_base, "ok": True, "provider_conceito": "gemini",
        "modelo": res_base.get("modelo") or f"gemini/{modelo}",
        "tempo_s": tempo_total, "tempo_provider_s": tempo_total,
        "versao": _concept.VERSAO, "seed": seed, "prompt_final": prompt_final,
        "negativo": negative_final, "pose": "", "largura_real": w_front, "altura_real": h_front,
        "revisao": digesto_front[:12], "origem_frontal_preservada": True,
        "referencia_estilo": str(origem_path), "referencia_estilo_sha256": digesto_front,
        "vistas": dict(vistas_paths), "vistas_ortograficas": dict(vistas_paths),
        "vistas_detalhes": vistas_detalhes,
    }
    escrever_metadados_concept(destino, resultado)
    return resultado
