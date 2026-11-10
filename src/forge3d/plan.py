"""Planejamento — puro, sem GPU, sem escrita de asset (D5, L2).

``plan`` e o passo que transforma um script em utilitario: responde "o que seria feito, quanto custa,
quanto vem do cache" sem gastar recurso. E o que roda no CI de pull request.
"""

from __future__ import annotations

from . import __version__, providers
from .canonical import chave_cache
from .errors import ForgeError
from .spec import resolver_item

__all__ = ["montar", "perfil_resolvido"]


def perfil_resolvido(perfil: dict) -> dict:
    """Perfil sem metadados de origem: entra na chave de cache so o que muda a saida."""
    return {k: v for k, v in perfil.items() if not k.startswith("_")}


def montar(spec_doc: dict, perfil: dict, cache_disponivel) -> list[dict]:
    """Lista de tarefas resolvidas. Rota nao implementada vira ``bloqueada``, nao erro fatal."""
    tarefas: list[dict] = []
    perfil_para_chave = perfil_resolvido(perfil)

    for item in spec_doc["lote"]:
        tarefa = {
            "id": item["id"],
            "tipo": item["tipo"],
            "rota": item["rota"],
            "estado_previsto": "pronto",
            "razao": None,
            "chave": None,
            "cache_hit": False,
            "provedor": None,
            "estimativa": None,
        }
        try:
            provider = providers.obter(item["rota"])
        except ForgeError as exc:
            tarefa["estado_previsto"] = "bloqueada"
            tarefa["razao"] = exc.mensagem
            tarefa["codigo"] = exc.codigo
            tarefas.append(tarefa)
            continue

        chave = chave_cache(
            resolver_item(item),
            __version__,
            {item["rota"]: provider.versao},
            perfil_para_chave,
        )
        tarefa["chave"] = chave
        tarefa["provedor"] = {"nome": provider.nome, "versao": provider.versao}
        tarefa["estimativa"] = provider.custo(item, perfil)
        tarefa["cache_hit"] = bool(cache_disponivel(chave))

        pronto, razao = provider.preflight()
        if not pronto:
            tarefa["estado_previsto"] = "bloqueada"
            tarefa["razao"] = razao
            if "VRAM" in razao:
                # D11/I6: falta de VRAM e recurso (exit 6), nao falha de provider (exit 5)
                tarefa["codigo"] = "FORGE-E-RECURSO"
        tarefas.append(tarefa)

    return tarefas


def resumo(tarefas: list[dict]) -> dict:
    total = len(tarefas)
    bloqueadas = sum(1 for t in tarefas if t["estado_previsto"] == "bloqueada")
    hits = sum(1 for t in tarefas if t["cache_hit"])
    segundos = sum(
        float((t["estimativa"] or {}).get("segundos_estimados", 0))
        for t in tarefas
        if not t["cache_hit"]
    )
    vram = max([int((t["estimativa"] or {}).get("vram_mb", 0)) for t in tarefas] or [0])
    return {
        "total": total,
        "prontas": total - bloqueadas,
        "bloqueadas": bloqueadas,
        "cache_hits": hits,
        "a_executar": total - bloqueadas - hits,
        "segundos_estimados": round(segundos, 1),
        "vram_pico_mb": vram,
    }
