"""``doctor`` — preflight do ambiente, com razao legivel em vez de traceback (D17).

Risco R1 medido no arquivo de riscos: a maior parte do tempo perdido em pipeline e ambiente.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import jsonschema

from . import __version__, config, paths, post, profiles, providers
from .errors import erro_ambiente

__all__ = ["checar", "exigir"]


def _item(nome: str, ok: bool, detalhe: str, critico: bool = True) -> dict:
    return {"nome": nome, "ok": ok, "detalhe": detalhe, "critico": critico}


def _checar_schemas() -> dict:
    falhas = []
    for nome in ("spec.v1.schema.json", "spec.v2.schema.json", "manifest.v1.schema.json"):
        arq = paths.raiz_dados() / "schemas" / nome
        if not arq.is_file():
            falhas.append(f"{nome} ausente")
            continue
        try:
            jsonschema.Draft202012Validator.check_schema(json.loads(arq.read_text(encoding="utf-8")))
        except jsonschema.SchemaError as exc:
            falhas.append(f"{nome}: {exc.message}")
    return _item("schemas", not falhas, "; ".join(falhas) or "spec@1/spec@2 e manifest@1 validos")


def _checar_perfis() -> dict:
    nomes = profiles.perfis_disponiveis()
    if not nomes:
        return _item("perfis", False, "nenhum perfil encontrado em profiles/")
    erros = []
    for nome in nomes:
        try:
            profiles.carregar(nome)
        except Exception as exc:  # noqa: BLE001 - doctor nunca derruba
            erros.append(f"{nome}: {exc}")
    return _item("perfis", not erros, ", ".join(nomes) if not erros else "; ".join(erros))


def _checar_estado() -> dict:
    try:
        paths.garantir_dirs()
        teste = paths.raiz_estado() / ".escrita"
        teste.write_text("ok", encoding="utf-8")
        teste.unlink()
        return _item("estado", True, str(paths.raiz_estado()))
    except OSError as exc:
        return _item("estado", False, f"{paths.raiz_estado()}: {exc}")


def _checar_allowlist() -> dict:
    try:
        raizes = config.listar()
    except Exception as exc:  # noqa: BLE001
        return _item("allowlist", False, str(exc))
    return _item(
        "allowlist",
        True,
        f"{len(raizes)} raiz(es), incluindo o sandbox {paths.dir_saida()}",
        critico=False,
    )


def _checar_disco() -> dict:
    uso = shutil.disk_usage(paths.raiz_estado())
    livres_gb = uso.free / (1024**3)
    return _item(
        "disco", livres_gb >= 5, f"{livres_gb:.0f} GB livres em {paths.raiz_estado()}",
        critico=livres_gb < 2,
    )


def _checar_gpu() -> dict:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return _item("gpu", True, "nvidia-smi ausente (rota mesh indisponivel; rotas D1 seguem)", critico=False)
    try:
        import subprocess

        saida = subprocess.run(
            [exe, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return _item("gpu", False, f"nvidia-smi falhou: {exc}", critico=False)
    return _item("gpu", bool(saida), saida or "sem resposta", critico=False)


def _checar_providers() -> dict:
    estado = providers.registrados()
    texto = " · ".join(f"{k}: {v}" for k, v in estado.items())
    return _item("providers", True, texto, critico=False)


def _checar_python() -> dict:
    ok = sys.version_info >= (3, 12)
    return _item("python", ok, f"{sys.version.split()[0]} em {sys.executable}")


def _checar_script_blender() -> dict:
    try:
        return _item("blender_script", True, str(post.script()))
    except erro_ambiente as exc:
        return _item("blender_script", False, exc.mensagem)


def checar() -> dict:
    checks = [
        _checar_python(),
        _checar_schemas(),
        _checar_perfis(),
        _checar_estado(),
        _checar_script_blender(),
        _checar_blender(),
        _checar_allowlist(),
        _checar_disco(),
        _checar_gpu(),
        _checar_providers(),
    ]
    criticos_ok = all(c["ok"] for c in checks if c["critico"])
    return {
        "ok": criticos_ok,
        "versao": __version__,
        "estado": str(paths.raiz_estado()),
        "config": str(paths.raiz_config()),
        "dados": str(paths.raiz_dados()),
        "checks": checks,
    }


def _checar_blender() -> dict:
    ok, detalhe = post.preflight()
    return _item("blender", ok, detalhe)


def exigir(necessario: tuple[str, ...] = ("blender",)) -> None:
    """Falha rapido quando o ambiente nao sustenta a execucao (exit 4)."""
    problemas = []
    for nome in necessario:
        if nome == "blender":
            ok, detalhe = post.preflight()
            if not ok:
                problemas.append(f"blender: {detalhe}")
        elif nome == "estado":
            r = _checar_estado()
            if not r["ok"]:
                problemas.append(f"estado: {r['detalhe']}")
    if problemas:
        raise erro_ambiente("pré-requisito ausente — rode `forge3d doctor`", problemas=problemas)
