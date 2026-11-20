"""Medicao G11 de itens staged e agregacao/resumo de relatorios do pipeline."""

from __future__ import annotations

import json
import logging
import struct
from pathlib import Path

from . import qc
from .errors import EXIT_OK, EXIT_PARCIAL, PRECEDENCIA, ForgeError

logger = logging.getLogger(__name__)


def _escrever_json(caminho: Path, obj: dict) -> None:
    caminho.write_text(
        json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _contar_primitivas_glb(caminho: Path) -> int:
    try:
        gltf, _ = qc.ler_glb_bin(caminho)
        meshes = gltf.get("meshes") or []
        return max(1, sum(len(m.get("primitives") or []) for m in meshes))
    except (ForgeError, OSError, ValueError, struct.error, IndexError, KeyError, TypeError, AttributeError) as exc:
        logger.debug("fallback primitivas=1 em %s: %s", caminho, exc)
        return 1


def _medir_item_g11(item: dict, staging: dict) -> dict:
    """Extrai metricas reais do item staged para avaliacao do Gate G11 (inclui partes[] F07)."""
    iid = str(item["id"])
    origem: Path = staging["origem"]
    resultado: dict = staging["resultado"]
    relatorio_qc: dict = staging["relatorio_qc"]
    manifesto: dict = staging["manifesto"]

    texturas: list[dict] = []
    for arq in resultado.get("arquivos", []):
        papel = str(arq.get("papel") or "")
        if papel not in qc.PAPEIS_TEXTURA:
            continue
        p_tex = origem / str(arq.get("caminho") or "")
        px = 1024
        if p_tex.is_file():
            dims = qc._validar_bytes_imagem(p_tex.read_bytes())
            if dims:
                px = max(dims)
        canais = 1 if papel in ("roughness", "metallic") else 4
        texturas.append({"id": f"{iid}:{arq['caminho']}", "px": px, "canais": canais})

    g4 = next((g for g in relatorio_qc.get("gates", []) if g.get("id") == "G4"), None)
    for idx, emb in enumerate(((g4 or {}).get("medido") or {}).get("embutidas") or []):
        px_list = emb.get("px")
        if isinstance(px_list, list) and px_list:
            texturas.append({"id": f"{iid}:emb:{idx}", "px": max(int(x) for x in px_list), "canais": 4})

    partes_res = resultado.get("partes") or manifesto.get("partes") or item.get("partes") or []
    arqs_parte = [a for a in resultado.get("arquivos", []) if a.get("papel") == "parte"]
    prim_partes = 0
    if arqs_parte:
        for arq in arqs_parte:
            p_glb = origem / str(arq.get("caminho") or "")
            prim_partes += _contar_primitivas_glb(p_glb) if p_glb.is_file() else 1
    elif partes_res:
        for p in partes_res:
            rel = str(p.get("arquivo") or f"{p.get('nome', '')}.glb") if isinstance(p, dict) else ""
            p_cand = origem / rel if rel else None
            prim_partes += _contar_primitivas_glb(p_cand) if (p_cand and p_cand.is_file()) else 1

    primitivas = max(1, int(relatorio_qc["medidas"].get("primitivas") or 1), prim_partes)
    tris = int(relatorio_qc["medidas"]["triangulos"])
    if partes_res:
        tris_partes = sum(int(p.get("triangulos") or 0) for p in partes_res if isinstance(p, dict))
        if tris_partes > 0:
            tris = max(tris, tris_partes)

    eh_pbr = (
        item.get("material") == "pbr"
        or bool(item.get("pbr_zonas"))
        or bool(item.get("material_procedural"))
    )
    skinned = (
        bool(item.get("auto_rig"))
        or bool(item.get("skinned"))
        or bool((manifesto.get("anexo") or {}).get("skinned"))
        or bool((item.get("rig") or {}).get("modo"))
        or bool((manifesto.get("rig") or {}).get("modo"))
    )
    return {
        "id": iid,
        "tris": tris,
        "primitivas": primitivas,
        "quantidade_cena": int(item.get("quantidade_cena", 1)),
        "mesh_key": str(item.get("mesh_key") or iid),
        "material_key": f"pbr:{iid}" if eh_pbr else "palette_padrao",
        "skinned": skinned,
        "texturas": texturas,
    }


def _estado_por_codigo(codigo: str) -> str:
    if codigo in ("FORGE-E-PROVIDER", "FORGE-E-RECURSO", "FORGE-E-LICENCA"):
        return "bloqueado"
    if codigo == "FORGE-E-QC":
        return "reprovado"
    return "falhou"


def _agregar(codigos: list[int], itens: list[dict]) -> int:
    """Nada publicado => exit da causa mais grave; mistura => parcial (docs/contratos.md §5)."""
    publicados = sum(
        1 for i in itens if i["estado"] in ("publicado", "cache_hit", "aprovado_nao_publicado")
    )
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
