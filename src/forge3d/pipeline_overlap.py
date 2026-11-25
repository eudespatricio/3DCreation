"""Overlap GPU/CPU no ``run``: gerar o item k+1 (GPU) enquanto o Blender pos-processa o item k.

Produtor/consumidor de 1 slot: o thread principal roda o estagio 1 (``preparar_item_bruto``, GPU)
e um unico worker roda o estagio 2 (``finalizar_item_cpu``, Blender/QC/cache) com Cycles forcado
em CPU para nao disputar VRAM com o gerador. Backpressure: antes de enfileirar o estagio 2 do item
k, o estagio 2 do item k-1 e coletado — no maximo 1 job de GPU e 1 de Blender ao mesmo tempo.

Contrato com ``pipeline.executar`` (serial): mesmos dicts de item, mesmos exit codes, mesma ordem
das tarefas, ``politica.falha == "abortar"`` corta o lote no primeiro item que falhou.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import providers
from .errors import EXIT_AMBIENTE, EXIT_OK, EXIT_PROVIDER, EXIT_RECURSO, ForgeError
from .pipeline_item import finalizar_item_cpu, preparar_item_bruto
from .pipeline_report import _estado_por_codigo

__all__ = ["CYCLES_DEVICE_OVERLAP", "executar_lote_overlap", "overlap_ativo"]

CYCLES_DEVICE_OVERLAP = "CPU"
_LIGADO = ("1", "true", "sim", "on")
_DESLIGADO = ("0", "false", "nao", "off")

_Resultado = tuple[dict[str, Any], int, bool]  # (item do relatorio, exit code, aborta o lote)


def _executa_trabalho(tarefa: dict) -> bool:
    return tarefa["estado_previsto"] != "bloqueada" and not tarefa.get("cache_hit")


def _usa_gpu(rota: str) -> bool:
    try:
        provider = providers.obter(rota)
    except ForgeError:
        # rota sem provider ja virou tarefa bloqueada no plano: nao conta como job de GPU
        return False
    return bool(getattr(provider, "usa_gpu", False))


def overlap_ativo(tarefas: list[dict], *, overlap: bool | None = None) -> bool:
    """Decide o overlap: flag explicita > ``FORGE3D_OVERLAP`` > auto (>= 2 itens de GPU a gerar)."""
    if overlap is True:
        return len(tarefas) >= 2
    if overlap is False:
        return False
    env = os.environ.get("FORGE3D_OVERLAP", "").strip().lower()
    if env in _LIGADO:
        return len(tarefas) >= 2
    if env in _DESLIGADO:
        return False
    gpu = sum(1 for t in tarefas if _executa_trabalho(t) and _usa_gpu(str(t["rota"])))
    return gpu >= 2


def _item_bloqueado(tarefa: dict) -> tuple[dict[str, Any], int]:
    item = {
        "id": tarefa["id"],
        "estado": "bloqueado",
        "rota": tarefa["rota"],
        "codigo": tarefa.get("codigo", "FORGE-E-PROVIDER"),
        "razao": tarefa["razao"],
    }
    return item, EXIT_RECURSO if tarefa.get("codigo") == "FORGE-E-RECURSO" else EXIT_PROVIDER


def _item_forge_error(item: dict, exc: ForgeError, politica: str) -> _Resultado:
    estado = _estado_por_codigo(exc.codigo)
    saida = {
        "id": item["id"],
        "estado": estado,
        "rota": item.get("rota"),
        "codigo": exc.codigo,
        "razao": exc.mensagem,
        "detalhes": exc.detalhes,
    }
    return saida, exc.exit_code, politica == "abortar" and estado == "falhou"


def _item_interno(item: dict, exc: Exception) -> _Resultado:
    saida = {
        "id": item["id"],
        "estado": "falhou",
        "rota": item.get("rota"),
        "codigo": "FORGE-E-INTERNO",
        "razao": f"{type(exc).__name__}: {exc}",
    }
    # serial tambem nao aborta em erro interno: so ForgeError com estado "falhou" corta o lote
    return saida, EXIT_AMBIENTE, False


def executar_lote_overlap(
    tarefas: list[dict],
    por_id: dict[str, dict],
    *,
    spec_doc: dict,
    perfil: dict,
    spec_hash: str,
    destino: Path,
    run_id: str,
    publicar_arquivos: bool,
    ignorar_cache: bool,
    politica: str,
    pos_processar_fn: Callable | None = None,
) -> tuple[list[dict], list[int], dict[str, Any]]:
    """Roda o lote em 2 estagios sobrepostos. Devolve ``(itens, codigos, info_overlap)``."""
    slots: list[_Resultado | None] = [None] * len(tarefas)
    corte: int | None = None  # indice do primeiro item que abortou o lote (inclusivo)
    sobrepostos = 0
    env_cpu = {"FORGE3D_CYCLES_DEVICE": CYCLES_DEVICE_OVERLAP}

    def estagio2(item: dict, tarefa: dict, prep: dict[str, Any]) -> _Resultado:
        try:
            saida = finalizar_item_cpu(
                item,
                tarefa,
                prep,
                spec_doc=spec_doc,
                perfil=perfil,
                spec_hash=spec_hash,
                destino=destino,
                run_id=run_id,
                publicar_arquivos=publicar_arquivos,
                adiar_publicacao=True,
                pos_processar_fn=pos_processar_fn,
                env_extra_post=env_cpu,
            )
        except ForgeError as exc:
            return _item_forge_error(item, exc, politica)
        except Exception as exc:  # noqa: BLE001 - nada derruba o lote inteiro (P6)
            return _item_interno(item, exc)
        return saida, EXIT_OK, False

    def coletar(pendente: tuple[int, Future[_Resultado]]) -> bool:
        """Espera o estagio 2 pendente; True quando ele pede para abortar o lote."""
        idx, fut = pendente
        res = fut.result()
        slots[idx] = res
        return res[2]

    pendente: tuple[int, Future[_Resultado]] | None = None
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="forge3d-estagio2") as pool:
        for idx, tarefa in enumerate(tarefas):
            item = por_id[tarefa["id"]]
            if tarefa["estado_previsto"] == "bloqueada" and not tarefa.get("cache_hit"):
                bloq, cod = _item_bloqueado(tarefa)
                slots[idx] = (bloq, cod, False)
                continue
            if pendente is not None:
                # estagio 1 deste item roda enquanto o estagio 2 do anterior esta no worker
                sobrepostos += 1
            falha: _Resultado | None = None
            try:
                item["_paleta"] = item.get("paleta") or spec_doc.get("paleta")
                prep = preparar_item_bruto(
                    item, tarefa, perfil=perfil, run_id=run_id, no_cache=ignorar_cache
                )
            except ForgeError as exc:
                falha = _item_forge_error(item, exc, politica)
            except Exception as exc:  # noqa: BLE001 - nada derruba o lote inteiro (P6)
                falha = _item_interno(item, exc)
            if falha is not None:
                slots[idx] = falha
                if falha[2]:
                    # abortar: drena o estagio 2 pendente (resultado entra) e para de agendar
                    if pendente is not None and coletar(pendente):
                        corte = pendente[0]
                    else:
                        corte = idx
                    pendente = None
                    break
                continue
            # backpressure: no maximo 1 Blender por vez; o anterior termina antes do proximo entrar
            if pendente is not None:
                aborta = coletar(pendente)
                anterior = pendente[0]
                pendente = None
                if aborta:
                    corte = anterior
                    break
            pendente = (idx, pool.submit(estagio2, item, tarefa, prep))
        if pendente is not None and coletar(pendente):
            corte = pendente[0]

    limite = len(tarefas) if corte is None else corte + 1
    validos = [s for s in slots[:limite] if s is not None]
    itens = [s[0] for s in validos]
    codigos = [s[1] for s in validos]
    info = {
        "ativo": True,
        "itens_sobrepostos": int(sobrepostos),
        "cycles_device_forcado": CYCLES_DEVICE_OVERLAP,
    }
    return itens, codigos, info
