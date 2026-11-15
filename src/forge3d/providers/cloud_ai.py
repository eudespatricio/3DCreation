"""Conectores plugaveis de IA em nuvem (Gemini / Imagen e Higgsfield) — stdlib pura (D26).

Zero dependencias externas de pip: usa apenas ``urllib.request``, ``json`` e ``base64``.
As chaves de API sao lidas de variaveis de ambiente ou de ``~/.config/forge3d/<provider>.key``
e NUNCA sao expostas em logs, relatorios do ``doctor`` ou mensagens de excecao.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .. import paths
from ..errors import erro_provider_run

MODELO_GEMINI_PADRAO = "imagen-3.0-generate-002"
URL_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
MODELO_HIGGSFIELD_PADRAO = "higgsfield-soul-1"
URL_HIGGSFIELD_PADRAO = "https://api.higgsfield.ai/v1/images/generations"

LICENCAS_CLOUD: dict[str, dict[str, Any]] = {
    "gemini": {
        "modelo": "Google Gemini / Imagen API",
        "uso_comercial": True,
        "notice": (
            "Concept art gerado via Google Gemini / Imagen API paga sob Google Cloud / "
            "Gemini API Terms of Service (uso comercial permitido ao titular da conta)."
        ),
    },
    "higgsfield": {
        "modelo": "Higgsfield AI API",
        "uso_comercial": True,
        "notice": (
            "Concept art gerado via Higgsfield AI API sob termos comerciais da assinatura "
            "Higgsfield (uso comercial permitido ao titular da chave)."
        ),
    },
}


def registrar_licencas_cloud() -> None:
    from . import LICENCAS

    for k, v in LICENCAS_CLOUD.items():
        LICENCAS.setdefault(k, dict(v))


def _sanitizar_texto_erro(texto: str, segredos: list[str]) -> str:
    saida = texto or ""
    for segredo in segredos:
        s = (segredo or "").strip()
        if s and len(s) >= 4:
            saida = saida.replace(s, "***REDACTED***")
    saida = re.sub(r"([?&]key=)[^&\s\"']+", r"\1***REDACTED***", saida, flags=re.IGNORECASE)
    saida = re.sub(r"(Bearer\s+)[^\s\"']+", r"\1***REDACTED***", saida, flags=re.IGNORECASE)
    return saida


def _ler_arquivo_chave(nome_arquivo: str) -> str:
    for raiz in (paths.raiz_config(), Path.home() / ".config" / "forge3d"):
        caminho = raiz / nome_arquivo
        if caminho.is_file():
            try:
                conteudo = caminho.read_text(encoding="utf-8").strip()
                if conteudo:
                    return conteudo.splitlines()[0].strip()
            except OSError:
                continue
    return ""


def _ler_chave_gemini() -> tuple[str, str]:
    env_key = os.environ.get("FORGE3D_GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key, "env:FORGE3D_GEMINI_API_KEY"
    arq_key = _ler_arquivo_chave("gemini.key")
    if arq_key:
        return arq_key, "arquivo:gemini.key"
    return "", ""


def _ler_chave_higgsfield() -> tuple[str, str]:
    env_key = os.environ.get("FORGE3D_HIGGSFIELD_API_KEY", "").strip()
    if env_key:
        return env_key, "env:FORGE3D_HIGGSFIELD_API_KEY"
    arq_key = _ler_arquivo_chave("higgsfield.key")
    if arq_key:
        return arq_key, "arquivo:higgsfield.key"
    return "", ""


def _ler_chave_roblox() -> tuple[str, str]:
    for var in ("FORGE3D_ROBLOX_API_KEY", "ROBLOX_OPEN_CLOUD_API_KEY"):
        val = os.environ.get(var, "").strip()
        if val:
            return val, f"env:{var}"
    arq_key = _ler_arquivo_chave("roblox.key")
    if arq_key:
        return arq_key, "arquivo:roblox.key"
    return "", ""


def modelo_gemini_escolhido() -> str:
    return os.environ.get("FORGE3D_GEMINI_MODELO", MODELO_GEMINI_PADRAO).strip() or MODELO_GEMINI_PADRAO


def modelo_higgsfield_escolhido() -> str:
    return (
        os.environ.get("FORGE3D_HIGGSFIELD_MODELO", MODELO_HIGGSFIELD_PADRAO).strip()
        or MODELO_HIGGSFIELD_PADRAO
    )


def url_higgsfield() -> str:
    return (
        os.environ.get("FORGE3D_HIGGSFIELD_API_URL", URL_HIGGSFIELD_PADRAO).strip()
        or URL_HIGGSFIELD_PADRAO
    )


def gemini_disponivel() -> tuple[bool, str]:
    chave, fonte = _ler_chave_gemini()
    if not chave:
        return (
            False,
            "chave ausente (defina FORGE3D_GEMINI_API_KEY ou ~/.config/forge3d/gemini.key)",
        )
    return True, f"pronto ({fonte}, modelo={modelo_gemini_escolhido()})"


def higgsfield_disponivel() -> tuple[bool, str]:
    chave, fonte = _ler_chave_higgsfield()
    if not chave:
        return (
            False,
            "chave ausente (defina FORGE3D_HIGGSFIELD_API_KEY ou ~/.config/forge3d/higgsfield.key)",
        )
    return True, f"pronto ({fonte}, modelo={modelo_higgsfield_escolhido()})"


def roblox_open_cloud_disponivel() -> tuple[bool, str]:
    chave, fonte = _ler_chave_roblox()
    if not chave:
        return (
            False,
            "chave ausente (defina FORGE3D_ROBLOX_API_KEY ou ~/.config/forge3d/roblox.key)",
        )
    return True, f"pronto ({fonte})"


def _extrair_bytes_imagem_gemini(resposta: dict[str, Any]) -> bytes:
    preds = resposta.get("predictions")
    if isinstance(preds, list) and preds:
        p0 = preds[0]
        if isinstance(p0, dict):
            b64 = p0.get("bytesBase64Encoded") or p0.get("b64_json") or p0.get("image")
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

    Imgs = resposta.get("generatedImages") or resposta.get("images")
    if isinstance(Imgs, list) and Imgs:
        im0 = Imgs[0]
        if isinstance(im0, str) and im0.strip():
            return base64.b64decode(im0)
        if isinstance(im0, dict):
            raw_inner = im0.get("image")
            img_inner: dict[str, Any] = raw_inner if isinstance(raw_inner, dict) else im0
            b64 = img_inner.get("imageBytes") or img_inner.get("bytesBase64Encoded") or img_inner.get("b64_json")
            if isinstance(b64, str) and b64.strip():
                return base64.b64decode(b64)

    raise ValueError("resposta Gemini nao contem imagem em base64 (predictions/candidates/generatedImages)")


def _extrair_bytes_imagem_higgsfield(resposta: dict[str, Any], timeout_s: int = 120) -> bytes:
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
                    req_img = urllib.request.Request(url_img, method="GET")
                    with urllib.request.urlopen(req_img, timeout=timeout_s) as resp_img:
                        return resp_img.read()

    raise ValueError("resposta Higgsfield nao contem imagem valida (data/images/b64_json)")


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
) -> dict[str, Any]:
    from . import LICENCAS

    chave, fonte = _ler_chave_gemini()
    if not chave:
        raise erro_provider_run(
            "conector Gemini sem chave configurada (FORGE3D_GEMINI_API_KEY ou ~/.config/forge3d/gemini.key)",
            id=item_id,
            modelo="gemini",
        )

    modelo = modelo_gemini_escolhido()
    url_custom = os.environ.get("FORGE3D_GEMINI_API_URL", "").strip()
    prompt_completo = prompt if not negativo else f"{prompt}. Avoid: {negativo}"

    if url_custom:
        endpoint = url_custom
    elif "imagen" in modelo.lower():
        endpoint = f"{URL_GEMINI_BASE}/{modelo}:predict"
    else:
        endpoint = f"{URL_GEMINI_BASE}/{modelo}:generateContent"

    if ":generateContent" in endpoint:
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt_completo}]}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "seed": int(seed),
            },
        }
    else:
        payload = {
            "instances": [{"prompt": prompt_completo}],
            "parameters": {
                "sampleCount": 1,
                "seed": int(seed),
                "aspectRatio": "1:1" if largura == altura else f"{largura}:{altura}",
            },
        }

    corpo = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=corpo,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": chave,
        },
        method="POST",
    )

    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw_resp = resp.read().decode("utf-8")
        dados = json.loads(raw_resp)
        img_bytes = _extrair_bytes_imagem_gemini(dados)
    except urllib.error.HTTPError as exc:
        detalhe = ""
        try:
            detalhe = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detalhe = str(exc)
        msg_limpa = _sanitizar_texto_erro(f"HTTP {exc.code}: {detalhe}", [chave])
        raise erro_provider_run(
            f"falha HTTP no conector Gemini ({modelo}): {msg_limpa}",
            id=item_id,
            modelo="gemini",
        ) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        msg_limpa = _sanitizar_texto_erro(str(exc), [chave])
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
    from . import LICENCAS

    chave, fonte = _ler_chave_higgsfield()
    if not chave:
        raise erro_provider_run(
            "conector Higgsfield sem chave configurada (FORGE3D_HIGGSFIELD_API_KEY ou ~/.config/forge3d/higgsfield.key)",
            id=item_id,
            modelo="higgsfield",
        )

    modelo = modelo_higgsfield_escolhido()
    endpoint = url_higgsfield()
    payload: dict[str, Any] = {
        "model": modelo,
        "prompt": prompt,
        "negative_prompt": negativo,
        "seed": int(seed),
        "width": int(largura),
        "height": int(altura),
        "response_format": "b64_json",
    }
    corpo = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=corpo,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {chave}",
        },
        method="POST",
    )

    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw_resp = resp.read().decode("utf-8")
        dados = json.loads(raw_resp)
        img_bytes = _extrair_bytes_imagem_higgsfield(dados, timeout_s=timeout_s)
    except urllib.error.HTTPError as exc:
        detalhe = ""
        try:
            detalhe = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detalhe = str(exc)
        msg_limpa = _sanitizar_texto_erro(f"HTTP {exc.code}: {detalhe}", [chave])
        raise erro_provider_run(
            f"falha HTTP no conector Higgsfield ({modelo}): {msg_limpa}",
            id=item_id,
            modelo="higgsfield",
        ) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        msg_limpa = _sanitizar_texto_erro(str(exc), [chave])
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
