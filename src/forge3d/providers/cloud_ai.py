"""Conectores plugaveis de IA em nuvem (Gemini, Higgsfield e TRELLIS) — stdlib pura (D26).

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

MODELO_GEMINI_PADRAO = "gemini-nano-banana-2.1"
MODELOS_GEMINI_SUPORTADOS = (
    "gemini-nano-banana-2.1",
    "gemini-3-pro-image",
    "gemini-3.1-flash-lite-image",
)
MODELO_GEMINI_QA_PADRAO = "gemini-4-hydrogen"
URL_GEMINI_INTERACTIONS = "https://generativelanguage.googleapis.com/v1beta/interactions"
API_REVISION_GEMINI = "2026-05-20"
URL_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
MODELO_HIGGSFIELD_PADRAO = "higgsfield-soul-1"
URL_HIGGSFIELD_PADRAO = "https://api.higgsfield.ai/v1/images/generations"
URL_TRELLIS_PADRAO = "https://fal.run/fal-ai/trellis"

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
    "trellis": {
        "modelo": "Microsoft TRELLIS (MIT via Cloud API)",
        "uso_comercial": True,
        "notice": (
            "Malha 3D gerada via Microsoft TRELLIS (MIT) hospedado em API cloud "
            "(uso comercial permitido ao titular da chave)."
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
    saida = re.sub(r"(Key\s+)[^\s\"']+", r"\1***REDACTED***", saida, flags=re.IGNORECASE)
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


def _ler_chave_fal() -> tuple[str, str]:
    env_key = os.environ.get("FORGE3D_FAL_API_KEY", "").strip()
    if env_key:
        return env_key, "env:FORGE3D_FAL_API_KEY"
    arq_key = _ler_arquivo_chave("fal.key")
    if arq_key:
        return arq_key, "arquivo:fal.key"
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
    modelo = modelo_gemini_escolhido()
    if not chave:
        return (
            False,
            f"chave ausente (defina FORGE3D_GEMINI_API_KEY ou ~/.config/forge3d/gemini.key; modelo={modelo})",
        )
    return True, f"pronto ({fonte}, modelo={modelo})"


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


def trellis_disponivel() -> tuple[bool, str]:
    chave, fonte = _ler_chave_fal()
    if not chave:
        return (
            False,
            "chave ausente (defina FORGE3D_FAL_API_KEY ou ~/.config/forge3d/fal.key)",
        )
    return True, f"pronto ({fonte}, modelo=trellis)"


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

    raise ValueError("resposta Gemini nao contem imagem em base64 (steps/candidates/predictions)")


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


def _post_json_seguro(
    endpoint: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    timeout_s: int,
    segredos: list[str],
    provedor: str,
    modelo: str,
    item_id: Any = None,
) -> dict[str, Any]:
    corpo = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=corpo, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw_resp = resp.read().decode("utf-8")
        dados = json.loads(raw_resp)
        if not isinstance(dados, dict):
            raise ValueError("resposta JSON nao e um objeto")
        return dados
    except urllib.error.HTTPError as exc:
        detalhe = ""
        try:
            detalhe = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detalhe = str(exc)
        msg_limpa = _sanitizar_texto_erro(f"HTTP {exc.code}: {detalhe}", segredos)
        raise erro_provider_run(
            f"falha HTTP no conector {provedor} ({modelo}): {msg_limpa}",
            id=item_id,
            modelo=provedor.lower(),
        ) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        msg_limpa = _sanitizar_texto_erro(str(exc), segredos)
        raise erro_provider_run(
            f"falha no conector {provedor} ({modelo}): {msg_limpa}",
            id=item_id,
            modelo=provedor.lower(),
        ) from None


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
    prompt_final = prompt if not negativo else f"{prompt}. Avoid: {negativo}"

    if modelo.startswith("imagen-"):
        endpoint = url_custom or f"{URL_GEMINI_BASE}/{modelo}:predict"
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
        # gemini-* (gemini-nano-banana-2.1, gemini-3-pro-image, gemini-3.1-flash-lite-image)
        endpoint = url_custom or URL_GEMINI_INTERACTIONS
        headers = {
            "x-goog-api-key": chave,
            "Content-Type": "application/json",
            "Api-Revision": API_REVISION_GEMINI,
        }
        payload = {
            "model": modelo,
            "input": [{"type": "text", "text": prompt_final}],
        }

    t0 = time.monotonic()
    dados = _post_json_seguro(
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
    caminho = Path(caminho_png)
    if not caminho.is_file():
        raise erro_provider_run(f"imagem para QA visual ausente: {caminho}", modelo="gemini")

    chave, _fonte = _ler_chave_gemini()
    if not chave:
        raise erro_provider_run(
            "conector Gemini QA sem chave configurada (FORGE3D_GEMINI_API_KEY ou ~/.config/forge3d/gemini.key)",
            modelo="gemini",
        )

    modelo_qa = os.environ.get("FORGE3D_GEMINI_QA_MODELO", MODELO_GEMINI_QA_PADRAO).strip() or MODELO_GEMINI_QA_PADRAO
    endpoint = os.environ.get("FORGE3D_GEMINI_API_URL", "").strip() or URL_GEMINI_INTERACTIONS
    b64_png = base64.b64encode(caminho.read_bytes()).decode("ascii")

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
            {"type": "image", "data": b64_png, "mime_type": "image/png"},
        ],
    }
    headers = {
        "x-goog-api-key": chave,
        "Content-Type": "application/json",
        "Api-Revision": API_REVISION_GEMINI,
    }

    dados = _post_json_seguro(
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
        msg_limpa = _sanitizar_texto_erro(str(exc), [chave])
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


def _extrair_bytes_glb_trellis(resposta: dict[str, Any], timeout_s: int = 180) -> bytes:
    for k_b64 in ("glb_base64", "b64_glb", "data"):
        b64 = resposta.get(k_b64)
        if isinstance(b64, str) and b64.strip():
            return base64.b64decode(b64)

    model_mesh = resposta.get("model_mesh")
    if isinstance(model_mesh, dict):
        b64 = model_mesh.get("base64") or model_mesh.get("data")
        if isinstance(b64, str) and b64.strip():
            return base64.b64decode(b64)
        url_glb = model_mesh.get("url")
        if isinstance(url_glb, str) and url_glb.startswith(("http://", "https://")):
            req = urllib.request.Request(url_glb, method="GET")
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return resp.read()

    for k_url in ("glb_url", "mesh_url", "url"):
        url_glb = resposta.get(k_url)
        if isinstance(url_glb, str) and url_glb.startswith(("http://", "https://")):
            req = urllib.request.Request(url_glb, method="GET")
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return resp.read()

    raise ValueError("resposta TRELLIS nao contem GLB (model_mesh.url/glb_base64)")


def gerar_malha_trellis(
    imagem_png: Path,
    destino_glb: Path,
    seed: int = 0,
    *,
    timeout_s: int = 180,
    item_id: Any = None,
) -> dict[str, Any]:
    """Gera malha ``.glb`` via Microsoft TRELLIS (MIT) na API fal.run."""
    from . import LICENCAS

    registrar_licencas_cloud()
    chave, fonte = _ler_chave_fal()
    if not chave:
        raise erro_provider_run(
            "conector TRELLIS sem chave configurada (FORGE3D_FAL_API_KEY ou ~/.config/forge3d/fal.key)",
            id=item_id,
            modelo="trellis",
        )

    caminho_img = Path(imagem_png)
    if not caminho_img.is_file():
        raise erro_provider_run(
            f"imagem de entrada TRELLIS ausente: {caminho_img}",
            id=item_id,
            modelo="trellis",
        )

    b64_img = base64.b64encode(caminho_img.read_bytes()).decode("ascii")
    endpoint = os.environ.get("FORGE3D_FAL_API_URL", "").strip() or URL_TRELLIS_PADRAO
    payload: dict[str, Any] = {
        "image_url": f"data:image/png;base64,{b64_img}",
        "seed": int(seed),
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Key {chave}",
    }

    t0 = time.monotonic()
    dados = _post_json_seguro(
        endpoint,
        payload,
        headers,
        timeout_s=timeout_s,
        segredos=[chave],
        provedor="TRELLIS",
        modelo="trellis",
        item_id=item_id,
    )
    try:
        glb_bytes = _extrair_bytes_glb_trellis(dados, timeout_s=timeout_s)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        msg_limpa = _sanitizar_texto_erro(str(exc), [chave])
        raise erro_provider_run(
            f"falha ao baixar GLB no conector TRELLIS: {msg_limpa}",
            id=item_id,
            modelo="trellis",
        ) from None

    destino = Path(destino_glb)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(glb_bytes)
    revisao = hashlib.sha256(glb_bytes).hexdigest()[:12]
    return {
        "ok": True,
        "provider_mesh": "trellis",
        "modelo": "trellis",
        "revisao": revisao,
        "seed": int(seed),
        "fonte_credencial": fonte,
        "tempo_s": round(time.monotonic() - t0, 3),
        "licenca": dict(LICENCAS["trellis"]),
    }
