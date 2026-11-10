"""Orquestracao de ``run``: plano -> gerar -> pos-processar -> QC -> cache -> publicar.

Regras que moram aqui: falha e local ao item (P6), bloqueio nao e falha (D11), QC reprovado nao
publica (D9) e nada escreve no destino fora de ``publish`` (I3).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, config, doctor, paths, plan, post, providers, publish, spec
from .canonical import canon, sha256_arquivo, sha256_bytes
from .errors import (
    EXIT_AMBIENTE,
    EXIT_OK,
    EXIT_PARCIAL,
    EXIT_QC,
    EXIT_RECURSO,
    PRECEDENCIA,
    ForgeError,
)

__all__ = ["novo_id", "executar", "verificar"]


def novo_id() -> str:
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{carimbo}-{os.urandom(3).hex()}"


def _spec_hash(spec_doc: dict) -> str:
    limpo = {k: v for k, v in spec_doc.items() if not k.startswith("_")}
    return sha256_bytes(canon(limpo))


def _runs(run_id: str) -> Path:
    d = paths.dir_runs() / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _escrever_json(caminho: Path, obj: dict) -> None:
    caminho.write_text(
        json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------- item


def _pos_processar(item: dict, perfil: dict, bruto, run_id: str) -> dict:
    final = paths.dir_staging() / run_id / item["id"] / "final"
    final.mkdir(parents=True, exist_ok=True)
    job = {
        "bruto_dir": str(bruto.dir),
        "bruto_arquivo": "modelo.json",
        "saida_dir": str(final),
        "saida_resultado": str(final / "resultado.json"),
        "perfil": plan.perfil_resolvido(perfil),
        "item": {k: v for k, v in item.items() if not k.startswith("_")},
        "nome_base": item["id"],
        "nome_arquivo": f"{item['id']}.glb",
    }
    resultado = post.executar(job)
    for arq in resultado.get("arquivos", []):
        caminho = final / arq["caminho"]
        arq["bytes"] = caminho.stat().st_size if caminho.is_file() else 0
        arq["sha256"] = sha256_arquivo(caminho) if caminho.is_file() else "sha256:" + "0" * 64
    resultado["dir_final"] = str(final)
    return resultado


def _executar_item(
    item: dict,
    tarefa: dict,
    *,
    spec_doc: dict,
    perfil: dict,
    spec_hash: str,
    destino: Path,
    run_id: str,
    publicar_arquivos: bool,
) -> dict:
    from . import qc as qc_mod

    chave = tarefa["chave"]
    entrada_cache = publish.ler_cache(chave)

    if entrada_cache is not None:
        origem, entrada = entrada_cache
        resultado = entrada["resultado"]
        relatorio_qc = entrada["qc"]
        provedor = entrada["provider"]
        licenca = entrada["licenca"]
        estado = "cache_hit"
    else:
        provider = providers.obter(item["rota"])
        staging = paths.dir_staging() / run_id / item["id"] / "bruto"
        staging.mkdir(parents=True, exist_ok=True)
        bruto = provider.gerar(item, perfil, staging)

        resultado = _pos_processar(item, perfil, bruto, run_id)
        resultado["determinism"] = provider.determinism
        licenca = providers.licenca_de(
            "procedural" if provider.nome in ("blocky", "import") else provider.nome
        )
        resultado["licenca"] = licenca

        relatorio_qc = qc_mod.verificar(item, perfil, Path(resultado["dir_final"]), resultado)
        if not relatorio_qc["aprovado"]:
            falhou = [g["id"] for g in relatorio_qc["gates"] if g["status"] == "falhou"]
            raise ForgeError(
                "FORGE-E-QC",
                f"QC reprovou: {', '.join(falhou)}",
                EXIT_QC,
                {"gates": falhou, "relatorio": relatorio_qc},
            )

        provedor = {
            "nome": provider.nome,
            "versao": provider.versao,
            "determinism": provider.determinism,
        }
        publish.salvar_cache(
            chave,
            Path(resultado["dir_final"]),
            {
                "resultado": resultado,
                "qc": relatorio_qc,
                "provider": provedor,
                "licenca": licenca,
                "item": spec.resolver_item(item),
            },
        )
        origem = Path(resultado["dir_final"])
        estado = "publicado"

    manifesto = publish.montar_manifesto(
        item=item,
        spec_doc=spec_doc,
        spec_hash=spec_hash,
        perfil_nome=spec_doc["perfil"],
        provider=provedor,
        resultado=resultado,
        relatorio_qc=relatorio_qc,
        licenca=licenca,
        run_id=run_id,
    )

    artefatos: list[dict] = []
    if publicar_arquivos:
        artefatos = publish.publicar(origem, destino, manifesto, run_id)

    return {
        "id": item["id"],
        "estado": estado,
        "rota": item["rota"],
        "determinism": resultado.get("determinism", "D1"),
        "qc": "aprovado" if relatorio_qc["aprovado"] else "reprovado",
        "cache_hit": entrada_cache is not None,
        "trabalho_executado": entrada_cache is None,
        "triangulos": relatorio_qc["medidas"]["triangulos"],
        "artefatos": artefatos,
        "manifesto": f"{item['id']}.manifest.json" if publicar_arquivos else None,
    }


# ---------------------------------------------------------------- lote


def executar(
    caminho: str | Path,
    *,
    plano_apenas: bool = False,
    publicar_arquivos: bool = True,
) -> tuple[dict, int]:
    doc = spec.carregar_arquivo(caminho)
    spec_doc, perfil, avisos = spec.preparar(doc)
    destino = config.validar_destino(spec_doc["destino_exportacao"])
    spec_hash = _spec_hash(spec_doc)
    run_id = novo_id()
    caminho_run = _runs(run_id)

    tarefas = plan.montar(spec_doc, perfil, lambda chave: publish.ler_cache(chave) is not None)
    resumo_plano = plan.resumo(tarefas)

    _escrever_json(
        caminho_run / "plano.json",
        {
            "schema": "forge3d/plano@1",
            "run_id": run_id,
            "projeto": spec_doc["projeto"],
            "perfil": spec_doc["perfil"],
            "destino": str(destino),
            "spec_hash": spec_hash,
            "pipeline_version": __version__,
            "resumo": resumo_plano,
            "tarefas": tarefas,
        },
    )

    relatorio: dict = {
        "schema": "forge3d/report@1",
        "comando": "plan" if plano_apenas else "run",
        "run_id": run_id,
        "projeto": spec_doc["projeto"],
        "perfil": spec_doc["perfil"],
        "destino": str(destino),
        "spec_hash": spec_hash,
        "pipeline_version": __version__,
        "avisos": avisos,
        "plano": resumo_plano,
        "itens": [],
        "artifacts": [],
    }

    if plano_apenas:
        relatorio["tarefas"] = tarefas
        relatorio["exit"] = EXIT_OK
        return relatorio, EXIT_OK

    doctor.exigir(("blender", "estado"))

    por_id = {item["id"]: item for item in spec_doc["lote"]}
    politica = (spec_doc.get("politica") or {}).get("falha", "continuar")
    codigos: list[int] = []

    for tarefa in tarefas:
        item = por_id[tarefa["id"]]
        if tarefa["estado_previsto"] == "bloqueada":
            relatorio["itens"].append(
                {
                    "id": tarefa["id"],
                    "estado": "bloqueado",
                    "rota": tarefa["rota"],
                    "codigo": tarefa.get("codigo", "FORGE-E-PROVIDER"),
                    "razao": tarefa["razao"],
                }
            )
            codigos.append(EXIT_RECURSO if tarefa.get("codigo") == "FORGE-E-RECURSO" else 5)
            continue

        try:
            item["_paleta"] = item.get("paleta") or spec_doc.get("paleta")
            saida = _executar_item(
                item,
                tarefa,
                spec_doc=spec_doc,
                perfil=perfil,
                spec_hash=spec_hash,
                destino=destino,
                run_id=run_id,
                publicar_arquivos=publicar_arquivos,
            )
            relatorio["itens"].append(saida)
            relatorio["artifacts"].extend(saida["artefatos"])
            codigos.append(EXIT_OK)
        except ForgeError as exc:
            estado = _estado_por_codigo(exc.codigo)
            relatorio["itens"].append(
                {
                    "id": item["id"],
                    "estado": estado,
                    "rota": item.get("rota"),
                    "codigo": exc.codigo,
                    "razao": exc.mensagem,
                    "detalhes": exc.detalhes,
                }
            )
            codigos.append(exc.exit_code)
            if politica == "abortar" and estado == "falhou":
                break
        except Exception as exc:  # noqa: BLE001 - nada derruba o lote inteiro
            relatorio["itens"].append(
                {
                    "id": item["id"],
                    "estado": "falhou",
                    "rota": item.get("rota"),
                    "codigo": "FORGE-E-INTERNO",
                    "razao": f"{type(exc).__name__}: {exc}",
                }
            )
            codigos.append(EXIT_AMBIENTE)

    codigo_saida = _agregar(codigos, relatorio["itens"])
    relatorio["exit"] = codigo_saida
    relatorio["resumo"] = _resumo(relatorio["itens"], resumo_plano)

    _escrever_json(caminho_run / "relatorio.json", relatorio)
    publish.registrar_ledger(
        {
            "run_id": run_id,
            "evento": "run",
            "projeto": spec_doc["projeto"],
            "exit": codigo_saida,
            "resumo": relatorio["resumo"],
        }
    )
    return relatorio, codigo_saida


def _estado_por_codigo(codigo: str) -> str:
    if codigo in ("FORGE-E-PROVIDER", "FORGE-E-RECURSO", "FORGE-E-LICENCA"):
        return "bloqueado"
    if codigo == "FORGE-E-QC":
        return "reprovado"
    return "falhou"


def _agregar(codigos: list[int], itens: list[dict]) -> int:
    """Nada publicado => exit da causa mais grave; mistura => parcial (docs/contratos.md §5)."""
    publicados = sum(1 for i in itens if i["estado"] in ("publicado", "cache_hit"))
    erros = [c for c in codigos if c != EXIT_OK]
    if not erros:
        return EXIT_OK
    if publicados == 0:
        for code in PRECEDENCIA:
            if code in erros and code != EXIT_OK:
                return code
        return erros[0]
    return EXIT_PARCIAL


def _resumo(itens: list[dict], resumo_plano: dict) -> dict:
    def contar(estado: str) -> int:
        return sum(1 for i in itens if i["estado"] == estado)

    return {
        "total": len(itens),
        "publicados": contar("publicado"),
        "cache_hits": contar("cache_hit"),
        "reprovados": contar("reprovado"),
        "bloqueados": contar("bloqueado"),
        "falhas": contar("falhou"),
        "trabalho_executado": sum(1 for i in itens if i.get("trabalho_executado")),
        "segundos_estimados": resumo_plano.get("segundos_estimados", 0),
    }


def verificar(destino: str | Path) -> dict:
    alvo = config.normalizar(destino)
    return publish.verificar(alvo)
