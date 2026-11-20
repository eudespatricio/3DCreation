"""Orquestracao de ``run``: plano -> gerar -> pos-processar -> segmentar -> QC -> cache -> publicar.

Regras que moram aqui: falha e local ao item (P6), bloqueio nao e falha (D11), QC reprovado nao
publica (D9) e nada escreve no destino fora de ``publish`` (I3).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, config, doctor, paths, plan, profiles, providers, publish, qc, spec
from .canonical import canon, sha256_bytes
from .errors import EXIT_AMBIENTE, EXIT_OK, EXIT_PROVIDER, EXIT_QC, EXIT_RECURSO, ForgeError
from .pipeline_item import _clipes_pedidos, _esqueleto_divergente, _pos_processar, executar_item
from .pipeline_report import (
    _agregar,
    _escrever_json,
    _estado_por_codigo,
    _medir_item_g11,
    _resumo,
)

__all__ = ["novo_id", "executar", "verificar"]

_REEXPORTS = (_clipes_pedidos, _esqueleto_divergente, providers)


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
    no_cache: bool = False,
    adiar_publicacao: bool = False,
) -> dict:
    return executar_item(
        item,
        tarefa,
        spec_doc=spec_doc,
        perfil=perfil,
        spec_hash=spec_hash,
        destino=destino,
        run_id=run_id,
        publicar_arquivos=publicar_arquivos,
        no_cache=no_cache,
        adiar_publicacao=adiar_publicacao,
        pos_processar_fn=_pos_processar,
    )


def executar(
    caminho: str | Path,
    *,
    plano_apenas: bool = False,
    publicar_arquivos: bool = True,
    no_cache: bool = False,
    clean_dest: bool = False,
    scene_budget: bool = False,
) -> tuple[dict, int]:
    doc = spec.carregar_arquivo(caminho)
    spec_doc, perfil, avisos = spec.preparar(doc)
    destino = config.validar_destino(spec_doc["destino_exportacao"])
    spec_hash = _spec_hash(spec_doc)
    run_id = novo_id()
    caminho_run = _runs(run_id)

    req = spec_doc.get("requisicao") or {}
    isolamento = req.get("isolamento", "padrao")
    ignorar_cache = no_cache or (isolamento == "estrito")
    deve_limpar = clean_dest or bool(req.get("limpar_destino", False))
    aplicar_g11 = ("orcamento_cena" in spec_doc) or (spec_doc.get("schema") == "forge3d/spec@6")

    tarefas = plan.montar(
        spec_doc,
        perfil,
        lambda chave: publish.ler_cache(chave) is not None,
        no_cache=ignorar_cache,
    )
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
        if scene_budget or aplicar_g11:
            relatorio["orcamento_cena"] = plan.estimar_orcamento_cena(spec_doc, perfil)
        relatorio["exit"] = EXIT_OK
        return relatorio, EXIT_OK

    precisa_blender = any(
        t["estado_previsto"] != "bloqueada" and not t["cache_hit"] for t in tarefas
    )
    if precisa_blender or not any(t["cache_hit"] for t in tarefas):
        doctor.exigir(("blender", "estado"))
    else:
        doctor.exigir(("estado",))

    por_id = {item["id"]: item for item in spec_doc["lote"]}
    politica = (spec_doc.get("politica") or {}).get("falha", "continuar")
    codigos: list[int] = []
    manifestos_publicados: list[dict] = []

    for tarefa in tarefas:
        item = por_id[tarefa["id"]]
        if tarefa["estado_previsto"] == "bloqueada" and not tarefa.get("cache_hit"):
            relatorio["itens"].append(
                {
                    "id": tarefa["id"],
                    "estado": "bloqueado",
                    "rota": tarefa["rota"],
                    "codigo": tarefa.get("codigo", "FORGE-E-PROVIDER"),
                    "razao": tarefa["razao"],
                }
            )
            codigos.append(
                EXIT_RECURSO if tarefa.get("codigo") == "FORGE-E-RECURSO" else EXIT_PROVIDER
            )
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
                no_cache=ignorar_cache,
                adiar_publicacao=True,
            )
            relatorio["itens"].append(saida)
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

    # Gate G11 (orcamento_cena) avalia ANTES de publicar qualquer arquivo no destino (I3 + I5).
    g11_falhou = False
    staged_itens = [s for s in relatorio["itens"] if "_staging" in s]
    if aplicar_g11 and staged_itens:
        itens_medidos_g11 = [
            _medir_item_g11(por_id[s["id"]], s["_staging"]) for s in staged_itens
        ]
        rel_g11 = qc.verificar_g11_orcamento_cena(
            itens_medidos_g11,
            limite_cena=profiles.orcamento_cena_perfil(perfil, spec_doc),
        )
        relatorio["orcamento_cena"] = rel_g11
        if rel_g11["status"] == "falhou":
            g11_falhou = True
            for s in staged_itens:
                s.pop("_staging", None)
                s["estado"] = "reprovado"
                s["qc"] = "reprovado"
                s["codigo"] = "FORGE-E-QC-SCENE"
                s["razao"] = "Gate G11 reprovou orcamento_cena"
                s["artefatos"] = []
                s["manifesto"] = None
                s["manifesto_doc"] = None
            relatorio["erro"] = {
                "codigo": "FORGE-E-QC-SCENE",
                "mensagem": "Gate G11 reprovou orcamento_cena",
                "detalhes": rel_g11,
            }
            codigos = [EXIT_QC]

    if not g11_falhou:
        for s in staged_itens:
            staging = s.pop("_staging")
            if publicar_arquivos:
                artefatos = publish.publicar(
                    staging["origem"], destino, staging["manifesto"], run_id
                )
                s["artefatos"] = artefatos
                s["manifesto"] = f"{s['id']}.manifest.json"
                s["manifesto_doc"] = staging["manifesto"]
                relatorio["artifacts"].extend(artefatos)
                manifestos_publicados.append(staging["manifesto"])

    codigo_saida = EXIT_QC if g11_falhou else _agregar(codigos, relatorio["itens"])
    relatorio["exit"] = codigo_saida
    relatorio["resumo"] = _resumo(relatorio["itens"], resumo_plano)

    if publicar_arquivos and deve_limpar and codigo_saida == EXIT_OK and manifestos_publicados:
        expurgados = publish.expurgar_orfaos_destino(destino, manifestos_publicados, run_id)
        if expurgados:
            relatorio["expurgados"] = expurgados

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


def verificar(destino: str | Path, only: str | None = None) -> dict:
    alvo = config.normalizar(destino)
    return publish.verificar(alvo, only=only)
