"""Conectores plugaveis de IA (Gemini, Higgsfield e status TRELLIS.2 MIT local) — stdlib pura (D26).

Zero dependencias externas de pip: usa apenas ``urllib.request``, ``json`` e ``base64``.
As chaves de API sao lidas de variaveis de ambiente ou de ``~/.config/forge3d/<provider>.key``
e NUNCA sao expostas em logs, relatorios do ``doctor`` ou mensagens de excecao.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .. import paths
from ..errors import erro_provider_run
from .cloud_gemini_kitbash import (
    _construir_pbr_zonas_padrao,
    _inferir_estilo_kitbash,
    _inferir_papel_peca,
    _normalizar_l2_floats,
    _parsear_plano_kitbash_json,
    _planejar_kitbash_offline,
    _resolver_modelo_embedding_gemini,
    _extrair_vetor_embedding_gemini,
    gerar_embedding_gemini,
    planejar_kitbash_gemini,
)
from .cloud_gemini_media import (
    _extrair_bytes_imagem_gemini,
    _extrair_bytes_imagem_higgsfield,
    _extrair_texto_gemini,
    _parsear_rubrica_qa,
    avaliar_qualidade_visual_gemini,
    gerar_conceito_gemini,
    gerar_conceito_higgsfield,
)

MODELO_GEMINI_PADRAO = "gemini-nano-banana-2.1"
MODELOS_GEMINI_SUPORTADOS = (
    "gemini-nano-banana-2.1",
    "gemini-3-pro-image",
    "gemini-3.1-flash-lite-image",
)
MODELO_GEMINI_QA_PADRAO = "gemini-4-hydrogen"
MODELO_GEMINI_EMBEDDING_PADRAO = "gemini-embedding-2-preview"
ALIASES_GEMINI_EMBEDDING: dict[str, str] = {
    "gemini-embedding-2": "gemini-embedding-2-preview",
    "gemini-embedding-2-preview": "gemini-embedding-2-preview",
    "text-embedding-004": "text-embedding-004",
}
MODELO_GEMINI_KITBASH_PADRAO = "gemini-3.1-flash-lite"
URL_GEMINI_INTERACTIONS = "https://generativelanguage.googleapis.com/v1beta/interactions"
API_REVISION_GEMINI = "2026-05-20"
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
    "gemini_embedding": {
        "modelo": "Google Gemini Embedding-2 (gemini-embedding-2-preview)",
        "uso_comercial": True,
        "notice": (
            "Vetores de busca semantica gerados via Google Gemini Embedding-2 API sob "
            "Google Cloud / Gemini API Terms of Service (uso comercial permitido)."
        ),
    },
    "gemini-embedding-2": {
        "modelo": "Google Gemini Embedding-2 (gemini-embedding-2-preview)",
        "uso_comercial": True,
        "notice": (
            "Vetores de busca semantica gerados via Google Gemini Embedding-2 API sob "
            "Google Cloud / Gemini API Terms of Service (uso comercial permitido)."
        ),
    },
    "gemini-embedding-2-preview": {
        "modelo": "Google Gemini Embedding-2 (gemini-embedding-2-preview)",
        "uso_comercial": True,
        "notice": (
            "Vetores de busca semantica gerados via Google Gemini Embedding-2 API sob "
            "Google Cloud / Gemini API Terms of Service (uso comercial permitido)."
        ),
    },
    "gemini_kitbash": {
        "modelo": "Google Gemini Kitbash Planner (Interactions API)",
        "uso_comercial": True,
        "notice": (
            "Plano de montagem kitbash sob pecas CC0 curadas via Google Gemini Interactions API "
            "(uso comercial permitido; geometria derivada exclusivamente do Vault CC0)."
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
        "modelo": "Microsoft TRELLIS.2-4B (MIT local)",
        "uso_comercial": True,
        "notice": (
            "Malha 3D gerada localmente via Microsoft TRELLIS.2-4B (MIT) em subprocesso "
            "isolado (uso comercial permitido)."
        ),
    },
}

_LICENCAS_CLOUD = LICENCAS_CLOUD


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
    raizes = [paths.raiz_config()]
    # Isolamento (D25): com FORGE3D_CONFIG explicito nao cai no ~/.config/forge3d do
    # usuario, senao testes e runs isolados enxergam a chave real e "auto" muda de provider.
    if "FORGE3D_CONFIG" not in os.environ:
        raizes.append(Path.home() / ".config" / "forge3d")
    for raiz in raizes:
        caminho = raiz / nome_arquivo
        if caminho.is_file():
            conteudo = caminho.read_text(encoding="utf-8").strip()
            if conteudo:
                return conteudo.splitlines()[0].strip()
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
    modelo = modelo_gemini_escolhido()
    try:
        chave, fonte = _ler_chave_gemini()
    except OSError as exc:
        return False, f"erro ao ler chave Gemini ({exc}; modelo={modelo})"
    if not chave:
        return (
            False,
            f"chave ausente (defina FORGE3D_GEMINI_API_KEY ou ~/.config/forge3d/gemini.key; modelo={modelo})",
        )
    return True, f"pronto ({fonte}, modelo={modelo})"


def higgsfield_disponivel() -> tuple[bool, str]:
    try:
        chave, fonte = _ler_chave_higgsfield()
    except OSError as exc:
        return False, f"erro ao ler chave Higgsfield ({exc})"
    if not chave:
        return (
            False,
            "chave ausente (defina FORGE3D_HIGGSFIELD_API_KEY ou ~/.config/forge3d/higgsfield.key)",
        )
    return True, f"pronto ({fonte}, modelo={modelo_higgsfield_escolhido()})"


def roblox_open_cloud_disponivel() -> tuple[bool, str]:
    try:
        chave, fonte = _ler_chave_roblox()
    except OSError as exc:
        return False, f"erro ao ler chave Roblox ({exc})"
    if not chave:
        return (
            False,
            "chave ausente (defina FORGE3D_ROBLOX_API_KEY ou ~/.config/forge3d/roblox.key)",
        )
    return True, f"pronto ({fonte})"


def trellis_disponivel() -> tuple[bool, str]:
    from . import mesh_trellis

    try:
        ok, det = mesh_trellis.preflight_trellis2()
    except OSError as exc:
        return False, f"inativo (erro ao diagnosticar TRELLIS.2: {exc})"
    if ok:
        return True, f"local ({det})"
    return False, f"inativo ({det})"


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
        try:
            detalhe = exc.read().decode("utf-8", errors="replace")[:500]
        except (OSError, ValueError, AttributeError) as read_exc:
            detalhe = f"{exc} ({read_exc})"
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


__all__ = [
    "ALIASES_GEMINI_EMBEDDING",
    "API_REVISION_GEMINI",
    "LICENCAS_CLOUD",
    "MODELO_GEMINI_EMBEDDING_PADRAO",
    "MODELO_GEMINI_KITBASH_PADRAO",
    "MODELO_GEMINI_PADRAO",
    "MODELO_GEMINI_QA_PADRAO",
    "MODELOS_GEMINI_SUPORTADOS",
    "MODELO_HIGGSFIELD_PADRAO",
    "URL_GEMINI_BASE",
    "URL_GEMINI_INTERACTIONS",
    "URL_HIGGSFIELD_PADRAO",
    "_LICENCAS_CLOUD",
    "_construir_pbr_zonas_padrao",
    "_extrair_bytes_imagem_gemini",
    "_extrair_bytes_imagem_higgsfield",
    "_extrair_texto_gemini",
    "_extrair_vetor_embedding_gemini",
    "_inferir_estilo_kitbash",
    "_inferir_papel_peca",
    "_ler_arquivo_chave",
    "_ler_chave_gemini",
    "_ler_chave_higgsfield",
    "_ler_chave_roblox",
    "_normalizar_l2_floats",
    "_parsear_plano_kitbash_json",
    "_parsear_rubrica_qa",
    "_planejar_kitbash_offline",
    "_post_json_seguro",
    "_resolver_modelo_embedding_gemini",
    "_sanitizar_texto_erro",
    "avaliar_qualidade_visual_gemini",
    "gemini_disponivel",
    "gerar_conceito_gemini",
    "gerar_conceito_higgsfield",
    "gerar_embedding_gemini",
    "higgsfield_disponivel",
    "modelo_gemini_escolhido",
    "modelo_higgsfield_escolhido",
    "planejar_kitbash_gemini",
    "registrar_licencas_cloud",
    "roblox_open_cloud_disponivel",
    "trellis_disponivel",
    "url_higgsfield",
]
