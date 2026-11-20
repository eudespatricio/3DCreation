"""Prompts CLIP, negativos, vistas ortograficas e politica de pose ControlNet para ``concept``."""

from __future__ import annotations

import importlib.util
import json
import os
import re
from pathlib import Path

LIMITE_TOKENS_CLIP = 77

SUFIXO_PADRAO = (
    "isolated object, front view, centered, plain neutral light gray background, "
    "game asset concept art, soft studio lighting, high detail"
)

NEGATIVO_PADRAO = (
    "blurry, low quality, cropped, text, watermark, logo, multiple views, "
    "busy background, extra limbs, deformed, duplicate, frame, "
    "halo, rim light, backlighting, shadow, drop shadow, white border"
)

VISTAS_ORTOGRAFICAS = ("front", "back", "left", "right")

SUFIXOS_VISTA_ORTOGRAFICA: dict[str, str] = {
    "front": "orthographic front view, straight-on, symmetrical canonical pose",
    "back": "orthographic back view, rear view, straight-on",
    "left": "orthographic left side profile view, straight-on",
    "right": "orthographic right side profile view, straight-on",
}


def sufixo_efetivo(prompt: str, sufixo: str) -> str:
    """Sufixo sem os trechos que o prompt ja repete (C11)."""
    alvo = (prompt or "").lower()
    partes = []
    for fragmento in (sufixo or "").split(","):
        limpo = fragmento.strip()
        if not limpo or limpo.lower() in alvo:
            continue
        partes.append(limpo)
    return ", ".join(partes)


def estimar_tokens_clip(texto: str) -> int:
    """Estimativa conservadora de tokens CLIP (inclui BOS/EOS)."""
    tokens = re.findall(r"[A-Za-z0-9]+|[^\sA-Za-z0-9]", texto or "")
    total = 2
    for tok in tokens:
        if tok.isalnum() and len(tok) > 9:
            total += max(1, (len(tok) + 5) // 6)
        else:
            total += 1
    return total


def combinar_prompt(
    prompt: str,
    sufixo: str,
    limite_tokens: int = LIMITE_TOKENS_CLIP,
) -> str:
    """Mescla ``prompt`` + ``sufixo`` mantendo ``prompt`` intacto dentro do limite CLIP."""
    base = (prompt or "").strip()
    efetivo = sufixo_efetivo(base, sufixo)
    if not efetivo:
        return base
    atual = base
    for fragmento in efetivo.split(","):
        limpo = fragmento.strip()
        if not limpo:
            continue
        candidato = f"{atual}, {limpo}" if atual else limpo
        if estimar_tokens_clip(candidato) <= limite_tokens:
            atual = candidato
    return atual


def prompt_para_vista(prompt: str, vista: str, sufixo: str | None = None) -> str:
    """Constroi prompt ortografico para uma vista especifica (front/back/left/right)."""
    if vista not in SUFIXOS_VISTA_ORTOGRAFICA:
        raise ValueError(
            f"vista ortografica invalida: {vista!r} (use {', '.join(VISTAS_ORTOGRAFICAS)})"
        )
    base = (prompt or "").strip()
    suf_bruto = (
        sufixo if sufixo is not None else os.environ.get("FORGE3D_CONCEPT_SUFIXO", SUFIXO_PADRAO)
    ).strip()
    frags_base = [
        frag.strip()
        for frag in suf_bruto.split(",")
        if frag.strip() and frag.strip().lower() != "front view"
    ]
    efetivo = sufixo_efetivo(base, ", ".join(frags_base))
    partes = [
        p
        for p in (
            base,
            SUFIXOS_VISTA_ORTOGRAFICA[vista],
            "consistent proportions and colors across all orthographic views",
            efetivo,
        )
        if p
    ]
    return ", ".join(partes)


def _chave_env_item(item_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", item_id).strip("_").upper()
    return f"FORGE3D_CONCEPT_NEGATIVO_{slug}" if slug else ""


def negativo_efetivo(item: dict) -> str:
    """Combina negativo global + por item (env/meta) sem quebrar ``spec@1..@3``."""
    base = os.environ.get("FORGE3D_CONCEPT_NEGATIVO", NEGATIVO_PADRAO).strip()
    extras: list[str] = []

    for chave in ("negativo", "negative"):
        val = item.get(chave)
        if isinstance(val, str) and val.strip():
            extras.append(val.strip())

    meta = item.get("meta")
    if isinstance(meta, dict):
        for chave in ("negativo", "negative"):
            val = meta.get(chave)
            if isinstance(val, str) and val.strip():
                extras.append(val.strip())

    mapa_raw = os.environ.get("FORGE3D_CONCEPT_NEGATIVO_MAP", "").strip()
    mapa: dict[str, object] | None = None
    if mapa_raw:
        try:
            parsed = json.loads(mapa_raw)
        except ValueError as exc:
            raise ValueError(f"FORGE3D_CONCEPT_NEGATIVO_MAP JSON invalido: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("FORGE3D_CONCEPT_NEGATIVO_MAP deve ser um objeto JSON (dict)")
        mapa = parsed

    item_id = str(item.get("id") or "").strip()
    if item_id:
        if mapa is not None:
            val_mapa = mapa.get(item_id)
            if isinstance(val_mapa, str):
                extras.append(val_mapa.strip())
        env_item = _chave_env_item(item_id)
        if env_item:
            val_env = os.environ.get(env_item, "").strip()
            if val_env:
                extras.append(val_env)

    partes: list[str] = []
    vistos: set[str] = set()
    for bloco in [base, *extras]:
        for frag in (bloco or "").split(","):
            limpo = frag.strip()
            if not limpo:
                continue
            chave = limpo.lower()
            if chave not in vistos:
                vistos.add(chave)
                partes.append(limpo)
    return ", ".join(partes)


def _pose_env_raw() -> str:
    return os.environ.get("FORGE3D_CONCEPT_POSE", "").strip().lower().replace("-", "")


def resolver_pose_com_estado(item: dict, *, controlnet_ok: bool) -> str:
    """Resolve ``FORGE3D_CONCEPT_POSE`` dado o estado de disponibilidade do ControlNet."""
    if "FORGE3D_CONCEPT_POSE" not in os.environ:
        if (
            item.get("tipo") == "personagem_humanoide"
            and bool(item.get("auto_rig"))
            and controlnet_ok
        ):
            return "apose"
        return ""
    raw = _pose_env_raw()
    if raw in ("", "none", "off", "0"):
        return ""
    if raw in ("tpose", "apose"):
        return raw
    if raw == "auto":
        if item.get("tipo") == "personagem_humanoide" and controlnet_ok:
            return "apose" if item.get("auto_rig") else "tpose"
        return ""
    raise ValueError(
        f"FORGE3D_CONCEPT_POSE invalido: {raw!r} (use '', 'tpose', 'apose' ou 'auto')"
    )


def estado_pose_cache_com_estado(*, controlnet_ok: bool) -> str:
    """Resumo deterministico da politica de pose ControlNet para chave de cache (D6)."""
    cn = "cn1" if controlnet_ok else "cn0"
    if "FORGE3D_CONCEPT_POSE" not in os.environ:
        return f"smart_{cn}"
    raw = _pose_env_raw()
    if raw in ("", "none", "off", "0"):
        return "off"
    if raw == "auto":
        return f"auto_{cn}"
    return raw


def gerar_pose_png(
    pose: str, destino_png: Path, largura: int, altura: int, script: Path
) -> Path:
    if not script.is_file():
        raise FileNotFoundError(f"script pose_map ausente em {script}")
    spec = importlib.util.spec_from_file_location("forge3d_pose_map", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"nao foi possivel carregar {script}")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.gerar_pose_map(pose, destino_png, largura=largura, altura=altura)
