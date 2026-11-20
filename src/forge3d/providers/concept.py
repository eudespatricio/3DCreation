"""Estagio ``concept`` — text-to-image local (SD1.5) e cloud (Gemini 1/4-vistas, Higgsfield).

O nucleo nao importa ``torch``/``diffusers``; a inferencia SD1.5 roda em subprocesso na
``FORGE3D_VENV_CONCEPT`` e o canal e JSON em disco (I9).
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

from .. import locks
from . import cloud_ai, concept_views
from .concept_prompt import (
    LIMITE_TOKENS_CLIP,
    NEGATIVO_PADRAO,
    SUFIXO_PADRAO,
    SUFIXOS_VISTA_ORTOGRAFICA,
    VISTAS_ORTOGRAFICAS,
    _chave_env_item,
    _pose_env_raw,
    combinar_prompt,
    estado_pose_cache_com_estado,
    estimar_tokens_clip,
    gerar_pose_png,
    negativo_efetivo,
    prompt_para_vista,
    resolver_pose_com_estado,
    sufixo_efetivo,
)
from .concept_views import _normalizar_png_real, escrever_metadados_concept, resolver_vistas

cloud_ai.registrar_licencas_cloud()

VERSAO = "0.2.5"
MODELO_PADRAO = "stable-diffusion-v1-5/stable-diffusion-v1-5"
CONTROLNET_MODELO_PADRAO = "lllyasviel/control_v11p_sd15_openpose"
VRAM_MINIMA_MB = 3000
TIMEOUT_S = 900

_DIAGNOSTICO: dict[tuple[str, str], dict] = {}


def _device() -> str:
    """cuda (default) ou cpu; CPU e fallback lento, mas mantem a rota utilizavel."""
    return (
        os.environ.get("FORGE3D_CONCEPT_DEVICE", os.environ.get("FORGE3D_DEVICE", "cuda"))
        .strip()
        .lower()
    )


def modelo_escolhido() -> str:
    return os.environ.get("FORGE3D_MODELO_CONCEPT", MODELO_PADRAO).strip()


def controlnet_modelo_escolhido() -> str:
    return (
        os.environ.get("FORGE3D_CONCEPT_CONTROLNET_MODELO", CONTROLNET_MODELO_PADRAO).strip()
        or CONTROLNET_MODELO_PADRAO
    )


def dir_venv() -> Path:
    env = os.environ.get("FORGE3D_VENV_CONCEPT")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".venvs" / "concept"


def script_inferencia() -> Path:
    from .. import paths

    env = os.environ.get("FORGE3D_CONCEPT_SCRIPT")
    if env:
        return Path(env).expanduser().resolve()
    return paths.raiz_dados() / "tools" / "concept_infer.py"


def script_pose_map() -> Path:
    from .. import paths

    env = os.environ.get("FORGE3D_POSE_MAP_SCRIPT")
    if env:
        return Path(env).expanduser().resolve()
    return paths.raiz_dados() / "tools" / "pose_map.py"


def _cache_hf() -> Path:
    env = os.environ.get("HF_HOME")
    base = Path(env).expanduser().resolve() if env else Path.home() / ".cache" / "huggingface"
    return base / "hub"


def _modelo_no_cache() -> Path:
    return _cache_hf() / ("models--" + modelo_escolhido().replace("/", "--"))


def _controlnet_no_cache() -> Path:
    return _cache_hf() / ("models--" + controlnet_modelo_escolhido().replace("/", "--"))


def controlnet_disponivel() -> bool:
    return _controlnet_no_cache().is_dir()


def resolver_pose(item: dict) -> str:
    """Resolve ``FORGE3D_CONCEPT_POSE`` ('' | 'tpose' | 'apose' | 'auto')."""
    return resolver_pose_com_estado(item, controlnet_ok=controlnet_disponivel())


def estado_pose_cache() -> str:
    """Resumo deterministico da politica de pose ControlNet para chave de cache (D6)."""
    return estado_pose_cache_com_estado(controlnet_ok=controlnet_disponivel())


def _gerar_pose_png(pose: str, destino_png: Path, largura: int, altura: int) -> Path:
    return gerar_pose_png(pose, destino_png, largura, altura, script_pose_map())


def _vram_livre_mb() -> int | None:
    return locks.vram_livre_mb()


def _diagnostico() -> dict:
    venv = dir_venv()
    script = script_inferencia()
    chave = (str(venv), str(script))
    if chave in _DIAGNOSTICO:
        return _DIAGNOSTICO[chave]

    python = venv / "bin" / "python"
    if not python.is_file():
        resultado = {
            "ok": False,
            "razao": (
                f"P3.5: venv de concept ausente em {venv} — defina FORGE3D_VENV_CONCEPT "
                "(docs/dependencias.md §4)"
            ),
        }
    elif not script.is_file():
        resultado = {"ok": False, "razao": f"P3.5: script de concept ausente em {script}"}
    else:
        codigo = (
            "import json, torch, diffusers, transformers; "
            "print(json.dumps({'torch': torch.__version__, "
            "'diffusers': diffusers.__version__, 'transformers': transformers.__version__, "
            "'cuda': bool(torch.cuda.is_available())}))"
        )
        try:
            proc = subprocess.run(
                [str(python), "-c", codigo],
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            linha = next(
                (ln for ln in reversed(proc.stdout.splitlines()) if ln.strip().startswith("{")),
                "",
            )
            info = json.loads(linha) if linha else {}
            if proc.returncode != 0 or not info:
                detalhe = (proc.stderr or proc.stdout or "").strip().splitlines()
                resultado = {
                    "ok": False,
                    "razao": (
                        "P3.5: falha ao importar torch/diffusers na venv de concept: "
                        + (detalhe[-1] if detalhe else f"exit {proc.returncode}")
                    ),
                }
            elif not info.get("cuda") and not _device().startswith("cpu"):
                resultado = {"ok": False, "razao": "P3.5: venv de concept sem CUDA disponível"}
            else:
                resultado = {"ok": True, **info}
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            resultado = {"ok": False, "razao": f"P3.5: falha ao diagnosticar a venv de concept: {exc}"}

    _DIAGNOSTICO[chave] = resultado
    return resultado


def resolver_provider_conceito(item: dict | None = None) -> str:
    """Resolve ``provider_conceito`` ('auto' | 'sd15' | 'gemini' | 'higgsfield')."""
    raw = (
        str(
            (item or {}).get("provider_conceito")
            or os.environ.get("FORGE3D_PROVIDER_CONCEITO")
            or "auto"
        )
        .strip()
        .lower()
    )
    if raw in ("sd15", "gemini", "higgsfield"):
        return raw
    if raw == "auto":
        if cloud_ai.gemini_disponivel()[0]:
            return "gemini"
        if cloud_ai.higgsfield_disponivel()[0]:
            return "higgsfield"
        return "sd15"
    raise ValueError(
        f"provider_conceito invalido: {raw!r} (use 'auto', 'sd15', 'gemini' ou 'higgsfield')"
    )


def preflight(item: dict | None = None) -> tuple[bool, str]:
    """Checa venv/script/CUDA/pesos (sd15) ou chave de API (gemini/higgsfield)."""
    try:
        prov = resolver_provider_conceito(item)
        vistas = resolver_vistas(item)
    except ValueError as exc:
        return False, f"P3.5: {exc}"

    if vistas == 4 and prov != "gemini":
        return False, f"P3.5: vistas=4 exige provider 'gemini' (recebido '{prov}')"

    if prov == "gemini":
        if vistas == 4:
            modelo = str(cloud_ai.modelo_gemini_escolhido())
            if modelo.startswith("imagen-"):
                return False, "P3.5: vistas=4 exige modelo gemini-* (ex.: gemini-nano-banana-2.1)"
        ok, razao = cloud_ai.gemini_disponivel()
        return ok, f"gemini: {razao}" if not ok else razao
    if prov == "higgsfield":
        ok, razao = cloud_ai.higgsfield_disponivel()
        return ok, f"higgsfield: {razao}" if not ok else razao

    pose_raw = _pose_env_raw()
    if pose_raw not in ("", "none", "off", "0", "tpose", "apose", "auto"):
        return False, f"P3.5: FORGE3D_CONCEPT_POSE invalido: {pose_raw!r}"

    diagnostico = _diagnostico()
    if not diagnostico["ok"]:
        return False, diagnostico["razao"]

    if not _device().startswith("cpu"):
        livre = _vram_livre_mb()
        if livre is not None and livre < VRAM_MINIMA_MB:
            return False, f"P3.5: VRAM livre {livre} MiB < {VRAM_MINIMA_MB} MiB exigidos pelo concept"

    pesos = _modelo_no_cache()
    if not pesos.is_dir():
        return False, (
            f"P3.5: pesos de '{modelo_escolhido()}' ausentes em {pesos}; "
            "rode tools/concept_infer.py uma vez com --modelo para baixar"
        )

    if pose_raw in ("tpose", "apose") and not controlnet_disponivel():
        return False, (
            f"P3.5: pesos de ControlNet '{controlnet_modelo_escolhido()}' ausentes em "
            f"{_controlnet_no_cache()}"
        )

    return True, (
        f"pronto (SD1.5, diffusers {diagnostico.get('diffusers', '?')}, "
        f"venv {dir_venv().name})"
    )


def _chamar_preflight(item: dict | None) -> tuple[bool, str]:
    params = inspect.signature(preflight).parameters
    if len(params) == 0:
        return preflight()
    return preflight(item)


def montar_comando(item: dict, destino: Path) -> tuple[list[str], dict]:
    """Monta a linha de comando do ``concept_infer.py`` e metadados de entrada (sem GPU)."""
    prompt = (item.get("prompt") or "").strip()
    seed = int(item.get("seed", 20261110))
    png = destino / "concept.png"
    resultado_path = destino / "concept_resultado.json"

    sufixo = os.environ.get("FORGE3D_CONCEPT_SUFIXO", SUFIXO_PADRAO).strip()
    prompt_final = combinar_prompt(prompt, sufixo)
    negative_final = negativo_efetivo(item)
    largura = os.environ.get("FORGE3D_CONCEPT_LARGURA", "512").strip() or "512"
    altura = os.environ.get("FORGE3D_CONCEPT_ALTURA", "512").strip() or "512"
    passos = os.environ.get("FORGE3D_CONCEPT_PASSOS", "25").strip() or "25"
    guidance = os.environ.get("FORGE3D_CONCEPT_GUIDANCE", "7.5").strip() or "7.5"

    comando = [
        str(dir_venv() / "bin" / "python"),
        str(script_inferencia()),
        "--prompt",
        prompt_final,
        "--negative",
        negative_final,
        "--seed",
        str(seed),
        "--saida",
        str(png),
        "--resultado",
        str(resultado_path),
        "--modelo",
        modelo_escolhido(),
        "--largura",
        largura,
        "--altura",
        altura,
        "--passos",
        passos,
        "--guidance",
        guidance,
        "--device",
        _device(),
    ]

    pose = resolver_pose(item)
    pose_png: Path | None = None
    controlnet = ""
    controlnet_scale = ""
    if pose:
        pose_png = destino / f"pose_{pose}.png"
        controlnet = controlnet_modelo_escolhido()
        controlnet_scale = os.environ.get("FORGE3D_CONCEPT_CONTROLNET_SCALE", "0.85").strip() or "0.85"
        comando.extend(
            [
                "--controlnet",
                controlnet,
                "--pose-imagem",
                str(pose_png),
                "--controlnet-scale",
                controlnet_scale,
            ]
        )

    info = {
        "png": png,
        "resultado_path": resultado_path,
        "prompt_final": prompt_final,
        "negative_final": negative_final,
        "pose": pose,
        "pose_png": pose_png,
        "controlnet": controlnet,
        "controlnet_scale": controlnet_scale,
        "largura": int(largura),
        "altura": int(altura),
    }
    return comando, info


class ConceptProvider:
    nome = "concept"
    determinism = "D2"  # diffusion nunca e D1 (D7)
    usa_gpu = True

    @property
    def versao(self) -> str:
        return f"{VERSAO}+{estado_pose_cache()}"

    @property
    def licenca(self) -> dict:
        from . import LICENCAS

        return dict(LICENCAS["sd15"])

    def capabilities(self) -> set[str]:
        return {"concept", "text-to-image", "image"}

    def custo(self, item: dict, perfil: dict) -> dict:
        try:
            prov = resolver_provider_conceito(item)
        except ValueError as exc:
            print(f"[concept] aviso custo: {exc}", file=sys.stderr)
            prov = "sd15"
        if prov in ("gemini", "higgsfield"):
            return {"segundos_estimados": 8.0, "vram_mb": 0, "disco_mb": 20}
        if _device().startswith("cpu"):
            return {"segundos_estimados": 180.0, "vram_mb": 0, "disco_mb": 4000}
        return {"segundos_estimados": 15.0, "vram_mb": 3000, "disco_mb": 4000}

    def preflight(self, item: dict | None = None) -> tuple[bool, str]:
        return _chamar_preflight(item)

    def gerar(self, item: dict, destino: Path) -> dict:
        from ..errors import erro_provider_run, erro_recurso
        from . import LICENCAS

        try:
            prov_conceito = resolver_provider_conceito(item)
            vistas = resolver_vistas(item)
        except ValueError as exc:
            raise erro_provider_run(str(exc), id=item.get("id")) from exc

        pronto, razao = _chamar_preflight(item)
        if not pronto:
            if "VRAM" in razao:
                raise erro_recurso(
                    f"concept sem VRAM: {razao}",
                    id=item.get("id"),
                    modelo=prov_conceito if prov_conceito != "sd15" else modelo_escolhido(),
                )
            raise erro_provider_run(
                f"concept indisponivel: {razao}",
                id=item.get("id"),
                modelo=prov_conceito if prov_conceito != "sd15" else modelo_escolhido(),
            )

        prompt = (item.get("prompt") or "").strip()
        if not prompt:
            raise erro_provider_run("concept exige 'prompt' no item", id=item.get("id"))

        ref_item = item.get("referencia_estilo")
        if ref_item and prov_conceito != "gemini":
            raise erro_provider_run(
                f"referencia_estilo exige provider 'gemini' (resolvido '{prov_conceito}')",
                id=item.get("id"),
                modelo=prov_conceito,
            )

        destino.mkdir(parents=True, exist_ok=True)
        if prov_conceito in ("gemini", "higgsfield"):
            return concept_views.gerar_conceito_cloud(
                item,
                destino,
                prov_conceito=prov_conceito,
                versao=VERSAO,
                cloud_ai_mod=cloud_ai,
                normalizar_fn=_normalizar_png_real,
            )

        if vistas == 4:
            raise erro_provider_run(
                "vistas=4 exige provider 'gemini'", id=item.get("id"), modelo=prov_conceito
            )

        try:
            comando, info = montar_comando(item, destino)
        except (TypeError, ValueError) as exc:
            raise erro_provider_run(str(exc), id=item.get("id")) from exc

        if info["pose"] and info["pose_png"] is not None:
            _gerar_pose_png(info["pose"], info["pose_png"], info["largura"], info["altura"])

        return concept_views.gerar_conceito_sd15(
            item,
            destino,
            comando=comando,
            info=info,
            versao=VERSAO,
            licenca_base=self.licenca,
            licenca_openpose=LICENCAS["sd15_openpose"],
            timeout_s=TIMEOUT_S,
            subprocess_mod=subprocess,
            normalizar_fn=_normalizar_png_real,
        )


__all__ = [
    "CONTROLNET_MODELO_PADRAO",
    "LIMITE_TOKENS_CLIP",
    "MODELO_PADRAO",
    "NEGATIVO_PADRAO",
    "SUFIXO_PADRAO",
    "SUFIXOS_VISTA_ORTOGRAFICA",
    "TIMEOUT_S",
    "VERSAO",
    "VISTAS_ORTOGRAFICAS",
    "VRAM_MINIMA_MB",
    "ConceptProvider",
    "_chave_env_item",
    "_normalizar_png_real",
    "combinar_prompt",
    "controlnet_disponivel",
    "controlnet_modelo_escolhido",
    "dir_venv",
    "escrever_metadados_concept",
    "estado_pose_cache",
    "estimar_tokens_clip",
    "modelo_escolhido",
    "montar_comando",
    "negativo_efetivo",
    "preflight",
    "prompt_para_vista",
    "resolver_pose",
    "resolver_provider_conceito",
    "resolver_vistas",
    "script_inferencia",
    "script_pose_map",
    "sufixo_efetivo",
]
