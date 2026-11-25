"""Geracao de vistas ortograficas (back/left/right) via Gemini a partir de ``origem`` aprovada."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..errors import ForgeError, erro_provider_run
from .concept_prompt import (
    SUFIXO_PADRAO,
    negativo_efetivo,
    prompt_para_vista,
    reforcar_prompt_rig,
    sufixo_efetivo,
)
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


def _preparar_ctx_origem(
    item: dict, origem_png: Path, destino: Path, env: dict[str, str] | None,
    cloud_ai_mod: Any, normalizar_fn: Callable[[Path], tuple[int, int, str]] | None,
    *, exigir_vistas4: bool,
) -> tuple[Path, Path, dict[str, Any], Any, Any, int, str, str, str, bool, int, int, tuple[str, str, str]]:
    from . import cloud_ai as _default_cloud_ai

    origem_path = Path(origem_png).expanduser()
    if not origem_path.is_file():
        raise erro_provider_run(f"imagem de concept inexistente: {origem_path}", id=item.get("id"))
    try:
        vistas = resolver_vistas(item)
        negative_final = negativo_efetivo(item)
        seed = int(item.get("seed", 20261110))
    except (TypeError, ValueError) as exc:
        raise erro_provider_run(str(exc), id=item.get("id")) from exc
    if exigir_vistas4 and vistas != 4:
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
    front_png = destino / "concept_front.png"
    if origem_path.resolve() != front_png.resolve():
        copiar = exigir_vistas4 or not front_png.is_file()
        if not copiar:
            copiar = (
                hashlib.sha256(origem_path.read_bytes()).hexdigest()
                != hashlib.sha256(front_png.read_bytes()).hexdigest()
            )
        if copiar:
            shutil.copyfile(origem_path, front_png)
    w_front, h_front, digesto_front = _inspecionar_imagem_preservada(front_png if front_png.is_file() else origem_path)
    largura = int(str(env_map.get("FORGE3D_CONCEPT_LARGURA", "512")).strip() or "512")
    altura = int(str(env_map.get("FORGE3D_CONCEPT_ALTURA", "512")).strip() or "512")
    prompt = reforcar_prompt_rig(str(item.get("prompt") or "").strip(), item)
    auto_rig_vista = bool(item.get("auto_rig")) and item.get("tipo") in ("personagem_humanoide", "criatura", None)
    sufixo = carregar_sufixo_estilo(env)
    efetivo = sufixo_efetivo(prompt, sufixo)
    prompt_final = f"{prompt}, {efetivo}" if (prompt and efetivo) else (prompt or efetivo)
    det_front = {
        "arquivo": (front_png if front_png.is_file() else origem_path).name,
        "largura_real": w_front, "altura_real": h_front,
        "revisao": digesto_front[:12], "seed": seed, "origem_frontal_preservada": True,
    }
    return (
        origem_path, front_png, det_front, ai_mod, norm_fn, seed, prompt,
        sufixo, negative_final, auto_rig_vista, largura, altura,
        (modelo, prompt_final, digesto_front),
    )


def _gerar_uma_vista_de_origem(
    vista: str, seed_vista: int, destino: Path, origem_path: Path, front_png: Path,
    prompt: str, sufixo: str, negative_final: str, largura: int, altura: int,
    auto_rig_vista: bool, item_id: Any, ai_mod: Any, norm_fn: Callable[[Path], tuple[int, int, str]],
) -> tuple[bool, Path, dict[str, Any], list[dict[str, Any]]]:
    vista_png = destino / f"concept_{vista}.png"
    vista_prompt = prompt_para_vista(prompt, vista, sufixo, auto_rig=auto_rig_vista)
    resultados: list[dict[str, Any]] = []
    res_v = _chamar_gemini_conceito(
        ai_mod, vista_prompt, negative_final, seed_vista, vista_png,
        largura=largura, altura=altura, item_id=item_id, referencia_png=origem_path,
    )
    resultados.append(res_v)
    w_real, h_real, digesto_vista = norm_fn(vista_png)
    detalhe_v: dict[str, Any] = {
        "arquivo": vista_png.name, "largura_real": w_real, "altura_real": h_real,
        "revisao": digesto_vista[:12], "seed": seed_vista,
    }
    incluir = True
    if _detectar_multiplas_figuras(vista_png):
        seed_retry = seed_vista + 100
        prompt_retry = f"{vista_prompt}, strictly ONE single character {vista} view only, NO side-by-side, NO front view"
        res_retry = _chamar_gemini_conceito(
            ai_mod, prompt_retry, negative_final, seed_retry, vista_png,
            largura=largura, altura=altura, item_id=item_id, referencia_png=origem_path,
        )
        resultados.append(res_retry)
        w_real, h_real, digesto_vista = norm_fn(vista_png)
        detalhe_v.update({"largura_real": w_real, "altura_real": h_real, "revisao": digesto_vista[:12], "seed": seed_retry, "retentativa_multiplas_figuras": True})
        mult_ainda, corte_frac, bg_rgba = _analisar_multiplas_figuras(vista_png)
        if mult_ainda:
            ref_crop = front_png if front_png.is_file() else origem_path
            if _recortar_metade_direita_se_frontal_na_esquerda(vista_png, ref_crop, corte_frac, bg_rgba):
                w_real, h_real, digesto_vista = norm_fn(vista_png)
                detalhe_v.update({"largura_real": w_real, "altura_real": h_real, "revisao": digesto_vista[:12], "auto_crop": "right_half"})
            else:
                incluir = False
                detalhe_v["omitida"] = "multiplas_figuras"
    return incluir, vista_png, detalhe_v, resultados


def gerar_vistas_de_origem(
    item: dict, origem_png: Path, destino: Path, env: dict[str, str] | None = None, *,
    cloud_ai_mod: Any = None, normalizar_fn: Callable[[Path], tuple[int, int, str]] | None = None,
) -> dict[str, Any]:
    """Preserva ``origem_png`` como vista frontal e gera ``back/left/right`` via Gemini."""
    from . import concept as _concept

    (
        origem_path, front_png, det_front, ai_mod, norm_fn, seed, prompt,
        sufixo, negative_final, auto_rig_vista, largura, altura, ctx_meta,
    ) = _preparar_ctx_origem(item, origem_png, destino, env, cloud_ai_mod, normalizar_fn, exigir_vistas4=True)
    modelo, prompt_final, digesto_front = ctx_meta

    concept_png = destino / "concept.png"
    if front_png.resolve() != concept_png.resolve():
        shutil.copyfile(front_png, concept_png)

    vistas_paths: dict[str, str] = {"front": str(front_png)}
    vistas_detalhes: dict[str, dict[str, Any]] = {"front": det_front}
    resultados_vistas: list[dict[str, Any]] = []
    for idx, vista in enumerate(VISTAS_LATERAIS_TRASEIRA, start=1):
        incluir, vista_png, detalhe_v, res_list = _gerar_uma_vista_de_origem(
            vista, seed + idx, destino, origem_path, front_png, prompt, sufixo,
            negative_final, largura, altura, auto_rig_vista, item.get("id"), ai_mod, norm_fn,
        )
        resultados_vistas.extend(res_list)
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
        "negativo": negative_final, "pose": "", "largura_real": det_front["largura_real"],
        "altura_real": det_front["altura_real"], "revisao": digesto_front[:12],
        "origem_frontal_preservada": True, "referencia_estilo": str(origem_path),
        "referencia_estilo_sha256": digesto_front,
        "vistas": dict(vistas_paths), "vistas_ortograficas": dict(vistas_paths),
        "vistas_detalhes": vistas_detalhes,
    }
    escrever_metadados_concept(destino, resultado)
    return resultado


def gerar_vista_traseira_de_origem(
    item: dict, origem_png: Path, destino: Path, env: dict[str, str] | None = None, *,
    cloud_ai_mod: Any = None, normalizar_fn: Callable[[Path], tuple[int, int, str]] | None = None,
) -> dict[str, Any]:
    """Gera somente ``concept_back.png`` via Gemini para projecao traseira no modo 1-view TRELLIS.2."""
    (
        origem_path, front_png, det_front, ai_mod, norm_fn, seed, prompt,
        sufixo, negative_final, auto_rig_vista, largura, altura, ctx_meta,
    ) = _preparar_ctx_origem(item, origem_png, destino, env, cloud_ai_mod, normalizar_fn, exigir_vistas4=False)
    modelo, _prompt_final, _digesto_front = ctx_meta

    incluir, back_png, detalhe_v, res_list = _gerar_uma_vista_de_origem(
        "back", seed + 1, destino, origem_path, front_png, prompt, sufixo,
        negative_final, largura, altura, auto_rig_vista, item.get("id"), ai_mod, norm_fn,
    )
    front_ref = front_png if front_png.is_file() else origem_path
    vistas_paths: dict[str, str] = {"front": str(front_ref)}
    if incluir:
        vistas_paths["back"] = str(back_png)
    res_base = dict(res_list[0]) if res_list else {}
    return {
        **res_base,
        "ok": True,
        "provider_conceito": "gemini",
        "modelo": res_base.get("modelo") or f"gemini/{modelo}",
        "tempo_s": round(sum(float(r.get("tempo_s", 0.0)) for r in res_list), 3),
        "vista_back": str(back_png) if incluir else "",
        "origem_frontal_preservada": True,
        "vistas": vistas_paths,
        "vistas_ortograficas": dict(vistas_paths),
        "vistas_detalhes": {"front": det_front, "back": detalhe_v},
    }


def anexar_vista_back_trellis(
    item: dict, front_png: Path, meta_c: dict | None, destino: Path, env: dict[str, str],
) -> dict[str, Any]:
    """Anexa vista ``back`` via Gemini (quando disponivel) mantendo modo 1-view para TRELLIS.2."""
    from . import cloud_ai

    meta = {**dict(meta_c or {}), "vistas_solicitadas": 4, "vistas_extras_ignoradas_single_view": True}
    vo_item = item.get("vistas_ortograficas")
    if isinstance(vo_item, dict) and vo_item.get("back") and Path(str(vo_item["back"])).is_file():
        meta["vistas"] = {"front": str(front_png), "back": str(vo_item["back"])}
        meta["vista_back_textura_trellis"] = True
        return meta
    env_map = env if env is not None else os.environ
    prov_raw = str(item.get("provider_conceito") or env_map.get("FORGE3D_PROVIDER_CONCEITO") or "gemini").strip().lower()
    ok_gem, _ = cloud_ai.gemini_disponivel()
    if prov_raw not in ("", "auto", "gemini") or not ok_gem or str(cloud_ai.modelo_gemini_escolhido()).startswith("imagen-"):
        return meta
    try:
        res_back = gerar_vista_traseira_de_origem(item, front_png, destino, env)
    except (ForgeError, OSError, ValueError) as exc:
        sys.stderr.write(f"[concept_views_origem] aviso vista back Gemini indisponivel ({exc}); seguindo 1-vista\n")
        return meta
    vistas_res = res_back.get("vistas") or {}
    if vistas_res.get("back"):
        meta["vistas"] = {"front": str(front_png), "back": str(vistas_res["back"])}
        meta["vista_back_textura_trellis"] = True
    if isinstance(res_back.get("vistas_detalhes"), dict):
        det_ant = dict(meta.get("vistas_detalhes") or {}) if isinstance(meta.get("vistas_detalhes"), dict) else {}
        det_ant.update(res_back["vistas_detalhes"])
        meta["vistas_detalhes"] = det_ant
    return meta
