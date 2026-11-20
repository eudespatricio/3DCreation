"""Conectores Gemini/Higgsfield de geracao de conceito e QA visual — stdlib pura (D26)."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import time
import urllib.error
from pathlib import Path
from typing import Any

from ..errors import erro_provider_run


def _extrair_bytes_imagem_gemini(resposta: dict[str, Any]) -> bytes:
    steps = resposta.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict) or step.get("type") != "model_output":
                continue
            content = step.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "image":
                    continue
                inline = part.get("inline_data") or part.get("inlineData")
                b64 = part.get("data")
                if not b64 and isinstance(inline, dict):
                    b64 = inline.get("data")
                if isinstance(b64, str) and b64.strip():
                    return base64.b64decode(b64)

    cands = resposta.get("candidates")
    if isinstance(cands, list):
        for cand in cands:
            if not isinstance(cand, dict):
                continue
            content = cand.get("content") or {}
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                inline = part.get("inlineData") or part.get("inline_data")
                if isinstance(inline, dict):
                    b64 = inline.get("data")
                    if isinstance(b64, str) and b64.strip():
                        return base64.b64decode(b64)

    preds = resposta.get("predictions")
    if isinstance(preds, list) and preds:
        p0 = preds[0]
        if isinstance(p0, dict):
            b64 = p0.get("bytesBase64Encoded") or p0.get("b64_json") or p0.get("image")
            if isinstance(b64, str) and b64.strip():
                return base64.b64decode(b64)

    imgs = resposta.get("generatedImages") or resposta.get("images")
    if isinstance(imgs, list) and imgs:
        im0 = imgs[0]
        if isinstance(im0, str) and im0.strip():
            return base64.b64decode(im0)
        if isinstance(im0, dict):
            raw_inner = im0.get("image")
            img_inner: dict[str, Any] = raw_inner if isinstance(raw_inner, dict) else im0
            b64 = img_inner.get("imageBytes") or img_inner.get("bytesBase64Encoded") or img_inner.get("b64_json")
            if isinstance(b64, str) and b64.strip():
                return base64.b64decode(b64)

    raise ValueError("resposta Gemini nao contem imagem em base64 (steps/candidates/predictions)")


def _extrair_bytes_imagem_higgsfield(resposta: dict[str, Any], timeout_s: int = 120) -> bytes:
    from . import cloud_ai

    for chave_direta in ("b64_json", "image_base64", "bytesBase64Encoded"):
        val = resposta.get(chave_direta)
        if isinstance(val, str) and val.strip():
            return base64.b64decode(val)

    for chave_lista in ("data", "images", "results", "outputs"):
        lista = resposta.get(chave_lista)
        if isinstance(lista, list) and lista:
            item0 = lista[0]
            if isinstance(item0, str) and item0.strip():
                return base64.b64decode(item0)
            if isinstance(item0, dict):
                for k_b64 in ("b64_json", "image_base64", "bytesBase64Encoded", "base64", "data"):
                    b64 = item0.get(k_b64)
                    if isinstance(b64, str) and b64.strip():
                        return base64.b64decode(b64)
                url_img = item0.get("url") or item0.get("image_url")
                if isinstance(url_img, str) and url_img.startswith(("http://", "https://")):
                    req_img = cloud_ai.urllib.request.Request(url_img, method="GET")
                    with cloud_ai.urllib.request.urlopen(req_img, timeout=timeout_s) as resp_img:
                        return resp_img.read()

    raise ValueError("resposta Higgsfield nao contem imagem valida (data/images/b64_json)")


def _inferir_mime_imagem(dados: bytes) -> str:
    if dados.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(dados) >= 12 and dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def gerar_conceito_gemini(
    prompt: str,
    negativo: str,
    seed: int,
    destino_png: Path,
    *,
    largura: int = 512,
    altura: int = 512,
    timeout_s: int = 120,
    item_id: Any = None,
    referencia_png: Path | None = None,
) -> dict[str, Any]:
    from . import LICENCAS, cloud_ai

    cloud_ai.registrar_licencas_cloud()
    try:
        chave, fonte = cloud_ai._ler_chave_gemini()
    except OSError as exc:
        raise erro_provider_run(f"falha ao ler chave Gemini: {exc}", id=item_id, modelo="gemini") from exc
    if not chave:
        raise erro_provider_run(
            "conector Gemini sem chave configurada (FORGE3D_GEMINI_API_KEY ou ~/.config/forge3d/gemini.key)",
            id=item_id,
            modelo="gemini",
        )

    modelo = cloud_ai.modelo_gemini_escolhido()
    url_custom = os.environ.get("FORGE3D_GEMINI_API_URL", "").strip()
    prompt_final = prompt if not negativo else f"{prompt}. Avoid: {negativo}"

    if referencia_png is not None and modelo.startswith("imagen-"):
        raise erro_provider_run(
            "referencia de estilo so suportada nos modelos gemini-* (nano banana), nao em imagen-*",
            id=item_id,
            modelo="gemini",
        )

    ref_sha: str | None = None
    if modelo.startswith("imagen-"):
        endpoint = url_custom or f"{cloud_ai.URL_GEMINI_BASE}/{modelo}:predict"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": chave,
        }
        payload: dict[str, Any] = {
            "instances": [{"prompt": prompt_final}],
            "parameters": {
                "sampleCount": 1,
                "seed": int(seed),
                "aspectRatio": "1:1" if largura == altura else f"{largura}:{altura}",
            },
        }
    else:
        endpoint = url_custom or cloud_ai.URL_GEMINI_INTERACTIONS
        headers = {
            "x-goog-api-key": chave,
            "Content-Type": "application/json",
            "Api-Revision": cloud_ai.API_REVISION_GEMINI,
        }
        partes_entrada: list[dict[str, Any]] = [{"type": "text", "text": prompt_final}]
        if referencia_png is not None:
            if not referencia_png.is_file():
                raise erro_provider_run(
                    f"referencia de estilo inexistente: {referencia_png}",
                    id=item_id,
                    modelo="gemini",
                )
            bytes_ref = referencia_png.read_bytes()
            b64_ref = base64.b64encode(bytes_ref).decode("ascii")
            ref_sha = hashlib.sha256(bytes_ref).hexdigest()
            partes_entrada.append(
                {
                    "type": "image",
                    "data": b64_ref,
                    "mime_type": _inferir_mime_imagem(bytes_ref),
                }
            )
        payload = {
            "model": modelo,
            "input": partes_entrada,
        }

    t0 = time.monotonic()
    dados = cloud_ai._post_json_seguro(
        endpoint,
        payload,
        headers,
        timeout_s=timeout_s,
        segredos=[chave],
        provedor="Gemini",
        modelo=modelo,
        item_id=item_id,
    )
    try:
        img_bytes = _extrair_bytes_imagem_gemini(dados)
    except ValueError as exc:
        msg_limpa = cloud_ai._sanitizar_texto_erro(str(exc), [chave])
        raise erro_provider_run(
            f"falha no conector Gemini ({modelo}): {msg_limpa}",
            id=item_id,
            modelo="gemini",
        ) from None

    destino_png.parent.mkdir(parents=True, exist_ok=True)
    destino_png.write_bytes(img_bytes)
    revisao = hashlib.sha256(img_bytes).hexdigest()[:12]
    return {
        "ok": True,
        "provider_conceito": "gemini",
        "modelo": f"gemini/{modelo}",
        "revisao": revisao,
        "seed": int(seed),
        "largura": int(largura),
        "altura": int(altura),
        "fonte_credencial": fonte,
        "tempo_s": round(time.monotonic() - t0, 3),
        "licenca": dict(LICENCAS["gemini"]),
        "referencia_estilo": str(referencia_png) if referencia_png is not None else None,
        "referencia_estilo_sha256": ref_sha,
    }


def gerar_conceito_higgsfield(
    prompt: str,
    negativo: str,
    seed: int,
    destino_png: Path,
    *,
    largura: int = 512,
    altura: int = 512,
    timeout_s: int = 120,
    item_id: Any = None,
) -> dict[str, Any]:
    from . import LICENCAS, cloud_ai

    cloud_ai.registrar_licencas_cloud()
    try:
        chave, fonte = cloud_ai._ler_chave_higgsfield()
    except OSError as exc:
        raise erro_provider_run(
            f"falha ao ler chave Higgsfield: {exc}", id=item_id, modelo="higgsfield"
        ) from exc
    if not chave:
        raise erro_provider_run(
            "conector Higgsfield sem chave configurada (FORGE3D_HIGGSFIELD_API_KEY ou ~/.config/forge3d/higgsfield.key)",
            id=item_id,
            modelo="higgsfield",
        )

    modelo = cloud_ai.modelo_higgsfield_escolhido()
    endpoint = cloud_ai.url_higgsfield()
    payload: dict[str, Any] = {
        "model": modelo,
        "prompt": prompt,
        "negative_prompt": negativo,
        "seed": int(seed),
        "width": int(largura),
        "height": int(altura),
        "response_format": "b64_json",
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {chave}",
    }

    t0 = time.monotonic()
    dados = cloud_ai._post_json_seguro(
        endpoint,
        payload,
        headers,
        timeout_s=timeout_s,
        segredos=[chave],
        provedor="Higgsfield",
        modelo=modelo,
        item_id=item_id,
    )
    try:
        img_bytes = _extrair_bytes_imagem_higgsfield(dados, timeout_s=timeout_s)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        msg_limpa = cloud_ai._sanitizar_texto_erro(str(exc), [chave])
        raise erro_provider_run(
            f"falha no conector Higgsfield ({modelo}): {msg_limpa}",
            id=item_id,
            modelo="higgsfield",
        ) from None

    destino_png.parent.mkdir(parents=True, exist_ok=True)
    destino_png.write_bytes(img_bytes)
    revisao = hashlib.sha256(img_bytes).hexdigest()[:12]
    return {
        "ok": True,
        "provider_conceito": "higgsfield",
        "modelo": f"higgsfield/{modelo}",
        "revisao": revisao,
        "seed": int(seed),
        "largura": int(largura),
        "altura": int(altura),
        "fonte_credencial": fonte,
        "tempo_s": round(time.monotonic() - t0, 3),
        "licenca": dict(LICENCAS["higgsfield"]),
    }


def _extrair_texto_gemini(resposta: dict[str, Any]) -> str:
    steps = resposta.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict) or step.get("type") != "model_output":
                continue
            content = step.get("content")
            if not isinstance(content, list):
                continue
            textos = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
            ]
            if textos:
                return "\n".join(textos).strip()

    outputs = resposta.get("outputs")
    if isinstance(outputs, list):
        textos = [
            p.get("text", "")
            for p in outputs
            if isinstance(p, dict) and isinstance(p.get("text"), str)
        ]
        if textos:
            return "\n".join(textos).strip()

    cands = resposta.get("candidates")
    if isinstance(cands, list):
        for cand in cands:
            if not isinstance(cand, dict):
                continue
            parts = (cand.get("content") or {}).get("parts")
            if isinstance(parts, list):
                textos = [
                    p.get("text", "")
                    for p in parts
                    if isinstance(p, dict) and isinstance(p.get("text"), str)
                ]
                if textos:
                    return "\n".join(textos).strip()

    raise ValueError("resposta Gemini QA nao contem texto (steps/outputs/candidates)")


def _parsear_rubrica_qa(texto: str) -> dict[str, Any]:
    import json

    limpo = texto.strip()
    if limpo.startswith("```"):
        limpo = re.sub(r"^```(?:json)?\s*", "", limpo)
        limpo = re.sub(r"\s*```$", "", limpo)
    try:
        obj = json.loads(limpo)
    except ValueError:
        m = re.search(r"\{.*\}", limpo, flags=re.DOTALL)
        if not m:
            raise ValueError("resposta Gemini QA sem objeto JSON valido") from None
        obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("resposta Gemini QA JSON nao e objeto")
    defeitos_raw = obj.get("defeitos")
    defeitos = [str(d).strip() for d in defeitos_raw if str(d).strip()] if isinstance(defeitos_raw, list) else []
    aprovado = bool(obj.get("aprovado", len(defeitos) == 0))
    nota = float(obj.get("nota", 8.0 if aprovado else 3.0))
    return {"aprovado": aprovado, "nota": nota, "defeitos": defeitos}


def avaliar_qualidade_visual_gemini(caminho_png: Path, contexto: str = "") -> dict[str, Any]:
    """Avalia render/turntable PNG usando ``gemini-4-hydrogen`` via API Interactions."""
    from . import cloud_ai

    caminho = Path(caminho_png)
    if not caminho.is_file():
        raise erro_provider_run(f"imagem para QA visual ausente: {caminho}", modelo="gemini")

    try:
        chave, _fonte = cloud_ai._ler_chave_gemini()
    except OSError as exc:
        raise erro_provider_run(f"falha ao ler chave Gemini QA: {exc}", modelo="gemini") from exc
    if not chave:
        raise erro_provider_run(
            "conector Gemini QA sem chave configurada (FORGE3D_GEMINI_API_KEY ou ~/.config/forge3d/gemini.key)",
            modelo="gemini",
        )

    modelo_qa = (
        os.environ.get("FORGE3D_GEMINI_QA_MODELO", cloud_ai.MODELO_GEMINI_QA_PADRAO).strip()
        or cloud_ai.MODELO_GEMINI_QA_PADRAO
    )
    endpoint = os.environ.get("FORGE3D_GEMINI_API_URL", "").strip() or cloud_ai.URL_GEMINI_INTERACTIONS
    raw_bytes = caminho.read_bytes()
    b64_png = base64.b64encode(raw_bytes).decode("ascii")

    rubrica = (
        "You are a 3D game asset visual QA critic inspecting a turntable or render PNG.\n"
        "Check strictly for: (1) forehead or face texture smears / dark painted bands, "
        "(2) left-right limb/leg color asymmetry or blotchy mottling, "
        "(3) silhouette clipping at borders, missing parts, or broken proportions, "
        "(4) material/PBR consistency.\n"
        "Return ONLY valid JSON with exact keys: "
        '{"aprovado": boolean, "nota": number (0.0 to 10.0), "defeitos": string[]}.'
    )
    if contexto.strip():
        rubrica += f"\nContext: {contexto.strip()}"

    payload: dict[str, Any] = {
        "model": modelo_qa,
        "input": [
            {"type": "text", "text": rubrica},
            {"type": "image", "data": b64_png, "mime_type": _inferir_mime_imagem(raw_bytes)},
        ],
    }
    headers = {
        "x-goog-api-key": chave,
        "Content-Type": "application/json",
        "Api-Revision": cloud_ai.API_REVISION_GEMINI,
    }

    dados = cloud_ai._post_json_seguro(
        endpoint,
        payload,
        headers,
        timeout_s=120,
        segredos=[chave],
        provedor="Gemini",
        modelo=modelo_qa,
    )
    try:
        texto = _extrair_texto_gemini(dados)
        avaliacao = _parsear_rubrica_qa(texto)
    except ValueError as exc:
        msg_limpa = cloud_ai._sanitizar_texto_erro(str(exc), [chave])
        raise erro_provider_run(
            f"falha ao interpretar resposta Gemini QA ({modelo_qa}): {msg_limpa}",
            modelo="gemini",
        ) from None

    return {
        "ok": True,
        "aprovado": avaliacao["aprovado"],
        "nota": avaliacao["nota"],
        "defeitos": avaliacao["defeitos"],
        "modelo": modelo_qa,
    }
