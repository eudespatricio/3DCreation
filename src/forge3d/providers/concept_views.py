"""Orquestracao cloud (1 ou 4 vistas ortograficas) e normalizacao PNG para ``concept``."""

from __future__ import annotations

import hashlib
import json
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
            resultado = cloud_ai_mod.gerar_conceito_gemini(
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
        ref_para_chamada = (
            ref_png
            if ref_png is not None
            else (None if vista == "front" else Path(vistas_paths["front"]))
        )
        res_v = cloud_ai_mod.gerar_conceito_gemini(
            vista_prompt,
            negative_final,
            seed + idx,
            vista_png,
            largura=largura,
            altura=altura,
            item_id=item.get("id"),
            referencia_png=ref_para_chamada,
        )
        w_real, h_real, digesto_vista = normalizar_fn(vista_png)
        vistas_paths[vista] = str(vista_png)
        vistas_detalhes[vista] = {
            "arquivo": vista_png.name,
            "largura_real": w_real,
            "altura_real": h_real,
            "revisao": digesto_vista[:12],
            "seed": seed + idx,
        }
        resultados_vistas.append(res_v)

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
