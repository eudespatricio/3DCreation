"""Execucao do Blender headless (D15, I9).

Fronteira: JSON entra, JSON sai. ``stdout`` do Blender e ruido e nunca e consumido como API.
Blender crashando nao derruba o lote — vira erro do item, com uma segunda tentativa em processo novo.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import paths
from .errors import ForgeError, erro_ambiente, erro_bpy

__all__ = ["binario", "versao", "script", "executar", "preflight", "PIPELINE_VERSION"]

PIPELINE_VERSION = "0.9.8"
VERSAO_MIN = (4, 2)
VERSAO_MAX = (4, 3)


def binario() -> str:
    env = os.environ.get("FORGE3D_BLENDER")
    if env:
        return env
    achado = shutil.which("blender")
    if achado:
        return achado
    candidato = Path.home() / ".local" / "bin" / "blender"
    if candidato.is_file():
        return str(candidato)
    raise erro_ambiente(
        "blender nao encontrado. Instale 4.2.x ou defina FORGE3D_BLENDER=/caminho/blender"
    )


def script() -> Path:
    env = os.environ.get("FORGE3D_BLENDER_SCRIPT")
    if env and Path(env).is_file():
        return Path(env)
    for base in (paths.raiz_dados(), Path(__file__).resolve().parent / "data"):
        alvo = base / "blender" / "postprocess.py"
        if alvo.is_file():
            return alvo
    raise erro_ambiente("blender/postprocess.py nao encontrado (repo ou dados do pacote)")


def versao() -> tuple[int, int, int]:
    try:
        saida = subprocess.run(
            [binario(), "--version"], capture_output=True, text=True, timeout=60
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise erro_ambiente(f"falha ao executar blender: {exc}") from exc
    linha = saida.splitlines()[0] if saida else ""
    try:
        numeros = linha.split("Blender")[1].strip().split(" ")[0].split(".")
        return (int(numeros[0]), int(numeros[1]), int(numeros[2]) if len(numeros) > 2 else 0)
    except (IndexError, ValueError) as exc:  # pragma: no cover - saida inesperada
        raise erro_ambiente(f"nao consegui interpretar a versao do blender: {linha!r}") from exc


def preflight() -> tuple[bool, str]:
    try:
        v = versao()
    except ForgeError as exc:
        return False, exc.mensagem
    if v[:2] < VERSAO_MIN or v[:2] >= VERSAO_MAX:
        return False, f"blender {v[0]}.{v[1]} nao suportado (pinado em 4.2.x)"
    return True, f"blender {v[0]}.{v[1]}.{v[2]}"


def _preparar_job(job: dict) -> dict:
    """Encaminha campos opcionais spec@5/spec@6 de ``job['item']`` sem alterar payloads legados."""
    preparado = dict(job)
    item = preparado.get("item")
    if isinstance(item, dict):
        for chave in (
            "material_procedural",
            "suavizacao_normais",
            "provider_conceito",
            "template_humanoide",
            "sockets",
            "detalhe_alto",
            "pbr_zonas",
            "quantidade_cena",
            "render_fidelity_roblox",
            "alpha_cards",
            "smart_fit",
            "roblox_render",
            "vistas",
            "vistas_ortograficas",
        ):
            if chave in item and chave not in preparado:
                preparado[chave] = item[chave]
        if "clipes" in item and "clipes_pedidos" not in preparado:
            preparado["clipes_pedidos"] = list(item["clipes"])
    lote_spec = preparado.get("lote_spec") or preparado.get("spec")
    if (
        isinstance(lote_spec, dict)
        and "roblox_render" in lote_spec
        and "roblox_render" not in preparado
    ):
        preparado["roblox_render"] = lote_spec["roblox_render"]
    return preparado


def _extrair_metadados_v5(resultado: dict) -> dict:
    """Promove metadados opcionais spec@5/spec@6 de ``resultado``/``medidas`` quando presentes."""
    medidas_raw = resultado.get("medidas")
    medidas: dict = medidas_raw if isinstance(medidas_raw, dict) else {}
    for chave in (
        "orientacao_export",
        "sockets",
        "sombreamento",
        "detalhe_alto",
        "pbr_zonas",
        "smart_fit",
    ):
        valor = resultado.get(chave)
        if valor is None and chave in medidas:
            valor = medidas.get(chave)
        if isinstance(valor, dict) and valor:
            resultado[chave] = dict(valor)
        elif isinstance(valor, list) and valor:
            resultado[chave] = list(valor)
    return resultado


def executar(job: dict, timeout: int = 900, tentativas: int = 2) -> dict:
    """Roda o pos-processo. Devolve o ``resultado.json`` ou levanta ``FORGE-E-BPY``."""
    for tentativa in range(1, tentativas + 1):
        resultado = _executar_uma(job, timeout)
        if resultado.get("ok"):
            return _extrair_metadados_v5(resultado)
        if tentativa == tentativas:
            raise erro_bpy(
                f"pos-processo falhou apos {tentativas} tentativa(s): {resultado.get('erro')}",
                stderr=resultado.get("traceback"),
            )
    raise erro_bpy("pos-processo falhou")  # pragma: no cover


def _executar_uma(job: dict, timeout: int) -> dict:
    job_preparado = _preparar_job(job)
    job_path = Path(job_preparado["saida_dir"]) / "_job.json"
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(json.dumps(job_preparado, sort_keys=True, indent=1), encoding="utf-8")

    resultado_path = Path(job["saida_resultado"])
    if resultado_path.exists():
        resultado_path.unlink()

    cmd = [binario(), "--background", "--factory-startup", "--python", str(script()), "--", str(job_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "erro": f"timeout de {timeout}s no blender"}
    except OSError as exc:
        raise erro_ambiente(f"falha ao executar blender: {exc}") from exc

    if not resultado_path.exists():
        return {
            "ok": False,
            "erro": "blender nao escreveu resultado.json",
            "traceback": (proc.stderr or proc.stdout or "")[-2000:],
        }
    try:
        return json.loads(resultado_path.read_text(encoding="utf-8"))
    except ValueError as exc:  # pragma: no cover
        return {"ok": False, "erro": f"resultado.json ilegivel: {exc}"}
