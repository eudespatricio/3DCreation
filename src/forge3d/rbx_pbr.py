"""Descoberta e resolucao de texturas PBR e ``SurfaceAppearance`` para Roblox."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from . import upload
from .errors import erro_spec
from .rbx_xml import _escrever_xml_seguro

logger = logging.getLogger(__name__)

inferir_papel_textura_roblox = upload.inferir_papel_textura_roblox
remover_imagens_embutidas_glb = upload.remover_imagens_embutidas_glb

_CANAL_SURFACE = ("ColorMap", "MetalnessMap", "NormalMap", "RoughnessMap")
_ALIASES_SURFACE = {
    "colormap": "ColorMap",
    "color_map": "ColorMap",
    "basecolor": "ColorMap",
    "albedo": "ColorMap",
    "metalnessmap": "MetalnessMap",
    "metalness_map": "MetalnessMap",
    "metalness": "MetalnessMap",
    "metallic": "MetalnessMap",
    "normalmap": "NormalMap",
    "normal_map": "NormalMap",
    "normal": "NormalMap",
    "roughnessmap": "RoughnessMap",
    "roughness_map": "RoughnessMap",
    "roughness": "RoughnessMap",
}


def _normalizar_mapas_pbr(mapas: Mapping[str, str | Path] | None) -> dict[str, str]:
    """Normaliza chaves de mapa PBR para os 4 campos de ``SurfaceAppearance``."""
    if not mapas:
        return {}
    saida: dict[str, str] = {}
    for chave, valor in mapas.items():
        if not valor:
            continue
        destino = _ALIASES_SURFACE.get(str(chave).strip().lower())
        if destino:
            saida[destino] = str(valor)
    return saida


def _eh_manifesto_v6(dados: Mapping[str, Any]) -> bool:
    schema_str = str(dados.get("schema") or "").strip()
    return schema_str == "forge3d/manifest@6" or schema_str.endswith("@6")


def descobrir_texturas_pbr(
    pasta: str | Path,
    item_id: str,
    *,
    permitir_orm_fallback: bool = True,
) -> dict[str, str]:
    """Descobre arquivos de textura PBR existentes em ``pasta`` para ``item_id``."""
    base = Path(pasta)
    if not base.is_dir():
        return {}
    candidatos = {
        "ColorMap": (f"{item_id}_baseColor.png", f"{item_id}_albedo.png", "baseColor.png"),
        "NormalMap": (f"{item_id}_normal.png", "normal.png"),
        "RoughnessMap": (f"{item_id}_roughness.png", "roughness.png"),
        "MetalnessMap": (
            f"{item_id}_metalness.png",
            f"{item_id}_metallic.png",
            "metalness.png",
            "metallic.png",
        ),
    }
    encontrados: dict[str, str] = {}
    for campo, nomes in candidatos.items():
        for nome in nomes:
            if (base / nome).is_file():
                encontrados[campo] = nome
                break

    if "RoughnessMap" not in encontrados and permitir_orm_fallback:
        eh_v6 = False
        if item_id:
            cand_man = base / f"{item_id}.manifest.json"
            if cand_man.is_file():
                try:
                    man_obj = json.loads(cand_man.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    logger.warning("descobrir_texturas_pbr: falha ao ler %s: %s", cand_man, exc)
                else:
                    if isinstance(man_obj, Mapping):
                        eh_v6 = _eh_manifesto_v6(man_obj)
        if not eh_v6:
            for nome_orm in (f"{item_id}_orm.png", "orm.png"):
                if (base / nome_orm).is_file():
                    encontrados["RoughnessMap"] = nome_orm
                    break
    return encontrados


def _resolver_asset_ids_pbr(
    mapas: Mapping[str, str],
    asset_ids: Mapping[str, str] | None = None,
    *,
    item_id: str | None = None,
    ledger: str | Path | bool | None = None,
) -> dict[str, str]:
    combinado: dict[str, str] = {}
    if ledger and item_id:
        caminho_ledger: str | Path | None = None if isinstance(ledger, bool) else ledger
        combinado.update(upload.asset_ids_do_ledger(item_id, caminho_ledger))
    if asset_ids:
        for chave, valor in asset_ids.items():
            if chave and valor:
                combinado[str(chave)] = str(valor)
    if not combinado:
        return dict(mapas)

    por_canal: dict[str, str] = {}
    for chave, valor in combinado.items():
        canal = _ALIASES_SURFACE.get(str(chave).strip().lower())
        if canal:
            por_canal[canal] = upload.formatar_rbxassetid(valor)

    if not mapas:
        return {c: por_canal[c] for c in _CANAL_SURFACE if c in por_canal}

    resultado: dict[str, str] = {}
    for campo, uri in mapas.items():
        escolhido = (
            combinado.get(uri)
            or combinado.get(Path(uri).name)
            or combinado.get(Path(uri).stem)
            or combinado.get(campo)
            or por_canal.get(campo)
        )
        if escolhido is None and campo == "RoughnessMap":
            stem_uri = Path(uri).stem.lower()
            if stem_uri.endswith("_orm") or stem_uri == "orm":
                escolhido = combinado.get("OrmPacked") or combinado.get("orm")
        resultado[campo] = upload.formatar_rbxassetid(escolhido) if escolhido else uri
    return resultado


def _surface_appearance_xml(
    mapas: Mapping[str, str | Path] | None,
    referent: str = "RBXSA0",
    *,
    nome: str = "SurfaceAppearance",
    alpha_mode: int = 0,
    asset_ids: Mapping[str, str] | None = None,
    item_id: str | None = None,
    ledger: str | Path | bool | None = None,
) -> list[str]:
    norm = _normalizar_mapas_pbr(mapas)
    norm = _resolver_asset_ids_pbr(norm, asset_ids, item_id=item_id, ledger=ledger)
    if not norm:
        return []
    linhas = [
        f'<Item class="SurfaceAppearance" referent="{escape(referent)}">',
        "<Properties>",
        f'<string name="Name">{escape(nome)}</string>',
        f'<token name="AlphaMode">{int(alpha_mode)}</token>',
    ]
    for campo in _CANAL_SURFACE:
        uri = norm.get(campo)
        if uri:
            linhas.append(f'<Content name="{campo}"><url>{escape(uri)}</url></Content>')
        else:
            linhas.append(f'<Content name="{campo}"><null></null></Content>')
    linhas += ["</Properties>", "</Item>"]
    return linhas


def surface_appearance_xml(
    mapas: Mapping[str, str | Path] | None,
    *,
    referent: str = "RBXSA0",
    nome: str = "SurfaceAppearance",
    alpha_mode: int = 0,
    asset_ids: Mapping[str, str] | None = None,
    item_id: str | None = None,
    ledger: str | Path | bool | None = None,
) -> str:
    """Gera XML ``<Item class="SurfaceAppearance">`` quando ha mapas PBR validos."""
    linhas = _surface_appearance_xml(
        mapas,
        referent=referent,
        nome=nome,
        alpha_mode=alpha_mode,
        asset_ids=asset_ids,
        item_id=item_id,
        ledger=ledger,
    )
    if not linhas:
        return ""
    xml = "\n".join(linhas)
    ElementTree.fromstring(xml)
    return xml


def _canal_por_nome(caminho: str) -> str:
    return inferir_papel_textura_roblox(caminho, None) or "ColorMap"


def _extrair_mapas_pbr_manifesto_dict(
    dados: Mapping[str, Any],
    *,
    pasta_base: Path | None = None,
    id_efetivo: str = "",
) -> dict[str, str]:
    """Extrai mapas PBR de um dicionario de manifesto (respeitando ``@6`` sem ``OrmPacked``)."""
    eh_v6_ou_novo = _eh_manifesto_v6(dados)
    mapas: dict[str, str] = {}
    bruto_tex = dados.get("texturas") or dados.get("surface_appearance")
    if isinstance(bruto_tex, Mapping):
        mapas.update(_normalizar_mapas_pbr(bruto_tex))

    orm_fallback: str | None = None
    entradas = dados.get("files") or dados.get("arquivos") or dados.get("arquivos_textura") or []
    if isinstance(entradas, list):
        for arq in entradas:
            if not isinstance(arq, Mapping):
                continue
            caminho = str(arq.get("caminho") or "").strip()
            if not caminho:
                continue
            papel = str(arq.get("papel") or "").strip().lower()
            canal = inferir_papel_textura_roblox(caminho, papel)
            if canal == "OrmPacked":
                orm_fallback = orm_fallback or caminho
                continue
            if canal in _CANAL_SURFACE and canal not in mapas:
                mapas[canal] = caminho

    if pasta_base is not None:
        for canal, caminho in descobrir_texturas_pbr(
            pasta_base, id_efetivo, permitir_orm_fallback=False
        ).items():
            mapas.setdefault(canal, caminho)

    if "RoughnessMap" not in mapas and not eh_v6_ou_novo:
        if orm_fallback:
            mapas["RoughnessMap"] = orm_fallback
        elif pasta_base is not None:
            for nome_orm in (f"{id_efetivo}_orm.png", "orm.png"):
                if (pasta_base / nome_orm).is_file():
                    mapas["RoughnessMap"] = nome_orm
                    break
    return mapas


def _carregar_manifesto_rbx(
    origem_manifesto: Path,
    item_id: str | None = None,
    contexto: str = "surface-appearance",
) -> tuple[dict[str, Any], dict[str, str], str]:
    try:
        dados = json.loads(origem_manifesto.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise erro_spec(f"{contexto}: manifesto ilegivel: {exc}") from exc
    if not isinstance(dados, dict):
        raise erro_spec(f"{contexto}: manifesto precisa ser um objeto JSON")

    manifest_id = str(dados.get("asset_id") or dados.get("id") or "").strip()
    pedido = (item_id or "").strip()
    if pedido and manifest_id and pedido != manifest_id:
        raise erro_spec(
            f"{contexto}: item '{pedido}' nao corresponde ao asset_id '{manifest_id}' do manifesto"
        )
    id_efetivo = pedido or manifest_id
    mapas = _extrair_mapas_pbr_manifesto_dict(
        dados, pasta_base=origem_manifesto.parent, id_efetivo=id_efetivo
    )
    return dados, mapas, id_efetivo


def _mapas_pbr_manifesto(
    origem_manifesto: Path,
    item_id: str | None = None,
) -> tuple[dict[str, str], str]:
    """Extrai mapas PBR de um arquivo ``manifest.json`` e faz fallback na pasta irma."""
    _dados, mapas, id_efetivo = _carregar_manifesto_rbx(origem_manifesto, item_id)
    return mapas, id_efetivo


def exportar_surface_appearance(
    texturas: Mapping[str, str | Path] | str | Path,
    item_id: str | None = None,
    saida: str | Path | None = None,
    *,
    asset_ids: Mapping[str, str] | None = None,
    ledger: str | Path | bool | None = None,
) -> dict:
    """Gera ``.rbxmx`` com ``SurfaceAppearance`` (``materiais_max: 1`` preservado)."""
    id_efetivo = (item_id or "").strip()
    if isinstance(texturas, (str, Path)):
        origem = Path(texturas).expanduser()
        if origem.is_file():
            mapas, id_efetivo = _mapas_pbr_manifesto(origem, item_id)
        elif origem.is_dir():
            mapas = descobrir_texturas_pbr(origem, id_efetivo)
            if not mapas and id_efetivo:
                cand_man = origem / f"{id_efetivo}.manifest.json"
                if cand_man.is_file():
                    mapas, id_efetivo = _mapas_pbr_manifesto(cand_man, id_efetivo)
        else:
            raise erro_spec(f"surface-appearance: origem nao encontrada: {origem}")
    else:
        mapas = _normalizar_mapas_pbr(texturas)

    mapas = _resolver_asset_ids_pbr(
        mapas, asset_ids, item_id=id_efetivo or None, ledger=ledger
    )
    if not mapas:
        raise erro_spec("surface-appearance: nenhuma textura PBR encontrada")
    itens = _surface_appearance_xml(mapas, referent="RBX0")
    xml = "\n".join(
        ['<?xml version="1.0" encoding="utf-8"?>', '<roblox version="4">']
        + itens
        + ["</roblox>"]
    ) + "\n"
    ElementTree.fromstring(xml)

    destino_str, tamanho = _escrever_xml_seguro(xml, saida, "surface-appearance")
    return {
        "ok": True,
        "saida": destino_str,
        "bytes": tamanho,
        "mapas": mapas,
        "materiais": 1,
        "xml": xml,
    }


def _resolver_mesh_uri(
    *,
    mesh_id: str | None,
    mesh_arquivo: str | None,
    id_efetivo: str,
    manifesto: Mapping[str, Any] | None,
    asset_ids: Mapping[str, str] | None,
    ledger: str | Path | bool | None,
) -> str:
    candidato: str | None = mesh_id
    if not candidato and asset_ids:
        chaves = [
            "mesh",
            "MeshId",
            "mesh_id",
            mesh_arquivo or "",
            Path(mesh_arquivo).name if mesh_arquivo else "",
            Path(mesh_arquivo).stem if mesh_arquivo else "",
            id_efetivo,
        ]
        for chave in chaves:
            if chave and asset_ids.get(chave):
                candidato = str(asset_ids[chave])
                break
    if not candidato and ledger and id_efetivo:
        caminho_ledger: str | Path | None = None if isinstance(ledger, bool) else ledger
        mapa_ledger = upload.resolver_ledger(caminho_ledger, asset_id=id_efetivo)
        for role in ("mesh", "model", "Model", ""):
            if (id_efetivo, role) in mapa_ledger:
                candidato = mapa_ledger[(id_efetivo, role)]
                break
    if not candidato and isinstance(manifesto, Mapping):
        rbx_bloco = manifesto.get("roblox")
        if isinstance(rbx_bloco, Mapping):
            bruto = rbx_bloco.get("asset_id") or rbx_bloco.get("assetId")
            if bruto:
                candidato = str(bruto)

    if candidato:
        limpo = candidato.strip()
        if limpo.isdigit() or limpo.startswith("rbxassetid://"):
            return upload.formatar_rbxassetid(limpo)
        return limpo
    return mesh_arquivo or ""
