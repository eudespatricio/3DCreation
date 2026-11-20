"""``doctor`` — preflight do ambiente, com razao legivel em vez de traceback (D17).

Risco R1 medido no arquivo de riscos: a maior parte do tempo perdido em pipeline e ambiente.
"""

from __future__ import annotations

import json
import os
import shutil
import sys

import jsonschema

from . import __version__, config, paths, post, profiles, providers
from .errors import ForgeError, erro_ambiente

__all__ = ["checar", "exigir"]


def _item(nome: str, ok: bool, detalhe: str, critico: bool = True) -> dict:
    return {"nome": nome, "ok": ok, "detalhe": detalhe, "critico": critico}


def _checar_schemas() -> dict:
    falhas = []
    for nome in (
        "spec.v1.schema.json",
        "spec.v2.schema.json",
        "spec.v3.schema.json",
        "spec.v4.schema.json",
        "spec.v5.schema.json",
        "spec.v6.schema.json",
        "manifest.v1.schema.json",
        "manifest.v2.schema.json",
        "manifest.v3.schema.json",
        "manifest.v4.schema.json",
        "manifest.v5.schema.json",
        "manifest.v6.schema.json",
    ):
        arq = paths.raiz_dados() / "schemas" / nome
        if not arq.is_file():
            falhas.append(f"{nome} ausente")
            continue
        try:
            jsonschema.Draft202012Validator.check_schema(json.loads(arq.read_text(encoding="utf-8")))
        except jsonschema.SchemaError as exc:
            falhas.append(f"{nome}: {exc.message}")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, OSError) as exc:
            falhas.append(f"{nome}: {exc}")
    return _item("schemas", not falhas, "; ".join(falhas) or "spec@1..@6 e manifest@1..@6 validos")


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
        teste = paths.raiz_estado() / f".escrita.{os.getpid()}"
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


def _diagnosticar_conectores_ia() -> dict[str, dict]:
    from .providers import cloud_ai, concept, mesh

    cloud_ai.registrar_licencas_cloud()
    sd15_ok, sd15_det = concept.preflight({"provider_conceito": "sd15"})
    triposr_ok, triposr_det = mesh.MeshProvider().preflight()
    mpfb_ok, mpfb_det = mesh.mpfb2_cc0_disponivel()
    gem_ok, gem_det = cloud_ai.gemini_disponivel()
    hig_ok, hig_det = cloud_ai.higgsfield_disponivel()
    tre_ok, tre_det = cloud_ai.trellis_disponivel()
    rbx_ok, rbx_det = cloud_ai.roblox_open_cloud_disponivel()

    def _fmt(ok: bool, det: str) -> dict:
        return {
            "ok": bool(ok),
            "pronto": bool(ok),
            "status": "pronto" if ok else "indisponivel",
            "detalhe": det,
        }

    return {
        "sd15": _fmt(sd15_ok, sd15_det),
        "triposr": _fmt(triposr_ok, triposr_det),
        "mpfb_cc0": _fmt(mpfb_ok, mpfb_det),
        "gemini": _fmt(gem_ok, gem_det),
        "higgsfield": _fmt(hig_ok, hig_det),
        "trellis": _fmt(tre_ok, tre_det),
        "roblox_open_cloud": _fmt(rbx_ok, rbx_det),
    }


def _checar_providers() -> dict:
    estado = providers.registrados()
    texto = " · ".join(f"{k}: {v}" for k, v in estado.items())
    return _item("providers", True, texto, critico=False)


def _checar_conectores_ia(conectores: dict[str, dict]) -> dict:
    resumo = " · ".join(
        f"{k}: {'pronto' if v['ok'] else 'off'}" for k, v in conectores.items()
    )
    return _item("conectores_ia", True, resumo, critico=False)


def _checar_python() -> dict:
    ok = sys.version_info >= (3, 12)
    return _item("python", ok, f"{sys.version.split()[0]} em {sys.executable}")


def _checar_script_blender() -> dict:
    try:
        return _item("blender_script", True, str(post.script()))
    except ForgeError as exc:
        return _item("blender_script", False, exc.mensagem)


def checar() -> dict:
    conectores = _diagnosticar_conectores_ia()
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
        _checar_conectores_ia(conectores),
    ]
    criticos_ok = all(c["ok"] for c in checks if c["critico"])
    return {
        "ok": criticos_ok,
        "versao": __version__,
        "estado": str(paths.raiz_estado()),
        "config": str(paths.raiz_config()),
        "dados": str(paths.raiz_dados()),
        # I7/I9: chaves de topo estaveis para o pipe (o `checks` continua detalhado)
        "blender": _versao_blender(),
        "modelos_aptos": sorted(
            {v["modelo"] for v in providers.LICENCAS.values() if v.get("uso_comercial")},
            key=str.lower,
        ),
        "conectores_ia": conectores,
        "checks": checks,
    }


def _versao_blender() -> str | None:
    """Versao do Blender em string (I9); ``None`` quando ausente."""
    try:
        maior, menor, micro = post.versao()
    except ForgeError:
        return None
    return f"{maior}.{menor}.{micro}"


def _checar_blender() -> dict:
    ok, detalhe = post.preflight()
    return _item("blender", ok, detalhe)


def exigir(necessario: tuple[str, ...] = ("blender",)) -> None:
    """Falha rapido quando o ambiente nao sustenta a execucao (exit 4)."""
    rel = checar()
    por_nome = {c["nome"]: c for c in rel.get("checks", [])}
    desconhecidos = [nome for nome in necessario if nome not in por_nome]
    if desconhecidos:
        raise erro_ambiente(
            f"check(s) desconhecido(s) em doctor.exigir: {', '.join(desconhecidos)}",
            checks=desconhecidos,
            disponiveis=sorted(por_nome),
        )
    problemas = []
    for nome in necessario:
        c = por_nome[nome]
        if not c["ok"]:
            problemas.append(f"{nome}: {c['detalhe']}")
    if problemas:
        raise erro_ambiente("pré-requisito ausente — rode `forge3d doctor`", problemas=problemas)
