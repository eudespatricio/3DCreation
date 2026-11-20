"""Exportacao de ``MeshPart`` PBR (.rbxmx) e manifesto Luau ``--!strict`` para Roblox."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from . import upload
from .errors import erro_spec
from .rbx_pbr import (
    _ALIASES_SURFACE,
    _CANAL_SURFACE,
    _carregar_manifesto_rbx,
    _resolver_asset_ids_pbr,
    _resolver_mesh_uri,
    descobrir_texturas_pbr,
    inferir_papel_textura_roblox,
)
from .rbx_xml import (
    COLLISION_FIDELITY_TOKENS,
    RENDER_FIDELITY_TOKENS,
    _escrever_xml_seguro,
)


def gerar_rbxmx_meshpart_pbr(
    *,
    nome: str,
    mesh_id: str,
    mapas_pbr: Mapping[str, str],
    render_fidelity: str = "Precise",
    collision_fidelity: str = "Box",
    tamanho_studs: tuple[float, float, float] = (4.0, 4.0, 4.0),
) -> str:
    """Emite .rbxmx pronto para import no Studio com RenderFidelity + SurfaceAppearance."""
    rf_tok = RENDER_FIDELITY_TOKENS.get(str(render_fidelity), 1)
    cf_tok = COLLISION_FIDELITY_TOKENS.get(str(collision_fidelity), 2)

    mesh_str = str(mesh_id or "").strip()
    if mesh_str:
        mesh_uri = (
            mesh_str
            if mesh_str.startswith("rbxassetid://") or not mesh_str.isdigit()
            else f"rbxassetid://{mesh_str}"
        )
        mesh_content = f"<url>{escape(mesh_uri)}</url>"
    else:
        mesh_content = "<null></null>"

    mapas_norm: dict[str, str] = {}
    for chave, valor in (mapas_pbr or {}).items():
        if not valor:
            continue
        val_str = str(valor).strip()
        if not val_str:
            continue
        stem_v = Path(val_str).stem.lower()
        if stem_v.endswith("_orm") or stem_v == "orm":
            continue
        canal = inferir_papel_textura_roblox(val_str, str(chave)) or _ALIASES_SURFACE.get(
            str(chave).strip().lower()
        )
        if canal in _CANAL_SURFACE:
            mapas_norm[canal] = val_str

    def _uri(val: str | None) -> str:
        if not val:
            return "<null></null>"
        limpo = str(val).strip()
        u = (
            limpo
            if limpo.startswith("rbxassetid://") or not limpo.isdigit()
            else f"rbxassetid://{limpo}"
        )
        return f"<url>{escape(u)}</url>"

    xml = "\n".join(
        [
            '<roblox version="4">',
            '  <Item class="MeshPart" referent="RBX0">',
            "    <Properties>",
            f'      <string name="Name">{escape(nome)}</string>',
            '      <bool name="Anchored">true</bool>',
            f'      <token name="CollisionFidelity">{cf_tok}</token>',
            f'      <token name="RenderFidelity">{rf_tok}</token>',
            f'      <Content name="MeshId">{mesh_content}</Content>',
            f'      <Vector3 name="size"><X>{tamanho_studs[0]:.4f}</X><Y>{tamanho_studs[1]:.4f}</Y><Z>{tamanho_studs[2]:.4f}</Z></Vector3>',
            "    </Properties>",
            '    <Item class="SurfaceAppearance" referent="RBX1">',
            "      <Properties>",
            '        <string name="Name">SurfaceAppearance</string>',
            '        <token name="AlphaMode">0</token>',
            f'        <Content name="ColorMap">{_uri(mapas_norm.get("ColorMap"))}</Content>',
            f'        <Content name="NormalMap">{_uri(mapas_norm.get("NormalMap"))}</Content>',
            f'        <Content name="RoughnessMap">{_uri(mapas_norm.get("RoughnessMap"))}</Content>',
            f'        <Content name="MetalnessMap">{_uri(mapas_norm.get("MetalnessMap"))}</Content>',
            "      </Properties>",
            "    </Item>",
            "  </Item>",
            "</roblox>",
        ]
    )
    ElementTree.fromstring(xml)
    return xml


def exportar_meshpart_pbr_rbxmx(
    origem: Mapping[str, Any] | str | Path | None = None,
    *,
    item_id: str | None = None,
    nome: str | None = None,
    mesh_id: str | None = None,
    mapas_pbr: Mapping[str, str] | None = None,
    saida: str | Path | None = None,
    render_fidelity: str | None = None,
    collision_fidelity: str = "Box",
    tamanho_studs: tuple[float, float, float] | None = None,
    asset_ids: Mapping[str, str] | None = None,
    ledger: str | Path | bool | None = None,
    metros_por_stud: float = 0.28,
) -> dict[str, Any]:
    """Exporta ``.rbxmx`` com ``MeshPart`` + ``SurfaceAppearance`` (``RenderFidelity`` configuravel)."""
    manifesto: dict[str, Any] = {}
    mapas: dict[str, str] = {}
    mesh_arquivo: str | None = None
    id_efetivo = (item_id or nome or "").strip()

    if isinstance(origem, Mapping):
        manifesto = dict(origem)
        id_efetivo = (
            id_efetivo or str(manifesto.get("asset_id") or manifesto.get("id") or "").strip()
        )
        entradas = (
            manifesto.get("files")
            or manifesto.get("arquivos")
            or manifesto.get("arquivos_textura")
            or []
        )
        if isinstance(entradas, list):
            for arq in entradas:
                if not isinstance(arq, Mapping):
                    continue
                cam = str(arq.get("caminho") or "").strip()
                pap = str(arq.get("papel") or "").strip().lower()
                if pap == "mesh" and not mesh_arquivo:
                    mesh_arquivo = cam or None
                canal = inferir_papel_textura_roblox(cam, pap)
                if canal in _CANAL_SURFACE and canal not in mapas:
                    mapas[canal] = cam
    elif isinstance(origem, (str, Path)):
        caminho = Path(origem).expanduser()
        if caminho.is_file() and caminho.suffix.lower() == ".json":
            manifesto, mapas_lidos, id_efetivo = _carregar_manifesto_rbx(
                caminho, item_id, contexto="export-meshpart-pbr"
            )
            for k, v in mapas_lidos.items():
                if not Path(v).stem.lower().endswith("_orm") and Path(v).stem.lower() != "orm":
                    mapas[k] = v
            for arq in manifesto.get("files") or []:
                if isinstance(arq, Mapping) and str(arq.get("papel") or "").lower() == "mesh":
                    mesh_arquivo = str(arq.get("caminho") or "").strip() or None
                    break
        elif caminho.is_dir():
            mapas = descobrir_texturas_pbr(caminho, id_efetivo, permitir_orm_fallback=False)
            if id_efetivo and (caminho / f"{id_efetivo}.glb").is_file():
                mesh_arquivo = f"{id_efetivo}.glb"
        elif caminho.is_file():
            id_efetivo = id_efetivo or caminho.stem
            mesh_arquivo = caminho.name
            mapas = descobrir_texturas_pbr(caminho.parent, id_efetivo, permitir_orm_fallback=False)
        else:
            raise erro_spec(f"export-meshpart-pbr: origem nao encontrada: {caminho}")

    if mapas_pbr:
        for k, v in mapas_pbr.items():
            if not v:
                continue
            canal = inferir_papel_textura_roblox(str(v), str(k)) or _ALIASES_SURFACE.get(
                str(k).strip().lower()
            )
            if canal in _CANAL_SURFACE:
                mapas[canal] = str(v)

    mapas = _resolver_asset_ids_pbr(
        mapas, asset_ids, item_id=id_efetivo or None, ledger=ledger
    )
    mapas = {
        k: v
        for k, v in mapas.items()
        if not (Path(v).stem.lower().endswith("_orm") or Path(v).stem.lower() == "orm")
    }

    mesh_uri = _resolver_mesh_uri(
        mesh_id=mesh_id,
        mesh_arquivo=mesh_arquivo,
        id_efetivo=id_efetivo,
        manifesto=manifesto,
        asset_ids=asset_ids,
        ledger=ledger,
    )
    rf_final = str(
        render_fidelity
        or manifesto.get("render_fidelity_roblox")
        or (manifesto.get("roblox_render") or {}).get("render_fidelity_padrao")
        or "Precise"
    )
    if tamanho_studs is not None:
        tam = (float(tamanho_studs[0]), float(tamanho_studs[1]), float(tamanho_studs[2]))
    else:
        raw_geom = manifesto.get("geometry")
        bbox = raw_geom.get("bbox_m") if isinstance(raw_geom, Mapping) else None
        if isinstance(bbox, (list, tuple)) and len(bbox) == 3 and metros_por_stud > 0:
            # geometry.bbox_m ja esta em eixos Y-up [largura_X, altura_Y, profundidade_Z]
            tam = (
                max(0.05, float(bbox[0]) / metros_por_stud),
                max(0.05, float(bbox[1]) / metros_por_stud),
                max(0.05, float(bbox[2]) / metros_por_stud),
            )
        else:
            tam = (4.0, 4.0, 4.0)

    nome_final = (nome or id_efetivo or "MeshPart").strip()
    xml = gerar_rbxmx_meshpart_pbr(
        nome=nome_final,
        mesh_id=mesh_uri,
        mapas_pbr=mapas,
        render_fidelity=rf_final,
        collision_fidelity=collision_fidelity,
        tamanho_studs=tam,
    ) + "\n"
    destino_str, tamanho = _escrever_xml_seguro(xml, saida, "export-meshpart-pbr")
    return {
        "ok": True,
        "saida": destino_str,
        "bytes": tamanho,
        "nome": nome_final,
        "mesh_id": mesh_uri,
        "render_fidelity": rf_final,
        "collision_fidelity": collision_fidelity,
        "mapas": mapas,
        "materiais": 1,
        "xml": xml,
    }


def gerar_manifesto_luau_pbr(registros: Mapping[str, Mapping[str, Any]]) -> str:
    """Emite modulo Luau --!strict com MeshId + 4 mapas PBR para consumo direto no Studio."""
    linhas = [
        "--!strict",
        "-- Gerado por forge3d export-pbr-luau (nao editar a mao)",
        "return table.freeze({",
    ]
    campos_luau = (
        ("meshId", ("meshId", "mesh_id", "MeshId", "mesh")),
        ("colorMap", ("colorMap", "ColorMap", "color_map", "baseColor")),
        ("normalMap", ("normalMap", "NormalMap", "normal_map", "normal")),
        ("roughnessMap", ("roughnessMap", "RoughnessMap", "roughness_map", "roughness")),
        ("metalnessMap", ("metalnessMap", "MetalnessMap", "metalness_map", "metallic", "metalness")),
    )
    for chave in sorted(registros):
        reg = registros[chave]
        linhas.append(f"\t[{json.dumps(chave)}] = table.freeze({{")
        for campo, aliases in campos_luau:
            val = None
            for alias in aliases:
                if reg.get(alias) is not None:
                    val = reg.get(alias)
                    break
            if val is not None and str(val).strip():
                limpo = str(val).strip()
                if limpo.startswith("rbxassetid://"):
                    limpo = limpo[len("rbxassetid://") :].strip()
                if limpo.isdigit():
                    linhas.append(f"\t\t{campo} = {int(limpo)},")
                else:
                    linhas.append(f"\t\t{campo} = {json.dumps(str(val))},")
        linhas.append("\t}),")
    linhas.append("})")
    return "\n".join(linhas) + "\n"


def exportar_manifesto_luau_pbr(
    fontes: Mapping[str, Mapping[str, Any]] | Sequence[str | Path] | str | Path | None = None,
    saida: str | Path | None = None,
    *,
    ledger: str | Path | bool | None = None,
) -> dict[str, Any]:
    """Constroi e opcionalmente grava manifesto Luau PBR a partir de dict, manifestos ou ledger."""
    registros: dict[str, dict[str, Any]] = {}
    mapa_canal_luau = {
        "mesh": "meshId",
        "model": "meshId",
        "Model": "meshId",
        "MeshId": "meshId",
        "meshId": "meshId",
        "ColorMap": "colorMap",
        "colorMap": "colorMap",
        "NormalMap": "normalMap",
        "normalMap": "normalMap",
        "RoughnessMap": "roughnessMap",
        "roughnessMap": "roughnessMap",
        "MetalnessMap": "metalnessMap",
        "metalnessMap": "metalnessMap",
    }

    def _aplicar_ledger(cam_l: str | Path | None) -> None:
        for (aid, role), uri in upload.resolver_ledger(cam_l).items():
            if not role or role == "OrmPacked" or aid.lower().endswith("_orm"):
                continue
            canal = inferir_papel_textura_roblox(aid, role) or role
            chave_luau = mapa_canal_luau.get(canal) or mapa_canal_luau.get(role)
            if not chave_luau:
                continue
            limpo = uri.removeprefix("rbxassetid://")
            registros.setdefault(aid, {})[chave_luau] = int(limpo) if limpo.isdigit() else uri

    def _aplicar_manifesto_arquivo(man_p: Path) -> None:
        man, mapas_m, id_m = _carregar_manifesto_rbx(man_p, contexto="export-pbr-luau")
        reg_m = registros.setdefault(id_m, {})
        rbx_b = man.get("roblox")
        if isinstance(rbx_b, Mapping) and (rbx_b.get("asset_id") or rbx_b.get("assetId")):
            raw_id = str(rbx_b.get("asset_id") or rbx_b.get("assetId")).removeprefix(
                "rbxassetid://"
            )
            reg_m["meshId"] = int(raw_id) if raw_id.isdigit() else raw_id
        for c_rbx, val_m in mapas_m.items():
            if Path(val_m).stem.lower().endswith("_orm"):
                continue
            c_luau = mapa_canal_luau.get(c_rbx)
            if c_luau:
                raw_v = str(val_m).removeprefix("rbxassetid://")
                reg_m[c_luau] = int(raw_v) if raw_v.isdigit() else val_m

    if isinstance(fontes, Mapping):
        for k, v in fontes.items():
            if isinstance(v, Mapping):
                registros[str(k)] = dict(v)
    elif fontes is not None:
        lista_fontes = [fontes] if isinstance(fontes, (str, Path)) else list(fontes)
        for f in lista_fontes:
            p = Path(f).expanduser()
            if p.is_file() and p.suffix.lower() == ".jsonl":
                _aplicar_ledger(p)
            elif p.is_file() and p.suffix.lower() == ".json":
                _aplicar_manifesto_arquivo(p)
            elif p.is_dir():
                for man_p in sorted(p.glob("*.manifest.json")):
                    _aplicar_manifesto_arquivo(man_p)

    if ledger:
        _aplicar_ledger(None if isinstance(ledger, bool) else ledger)

    luau = gerar_manifesto_luau_pbr(registros)
    destino_str, tamanho = _escrever_xml_seguro(luau, saida, "export-pbr-luau")
    return {
        "ok": True,
        "saida": destino_str,
        "bytes": tamanho,
        "total": len(registros),
        "registros": registros,
        "luau": luau,
    }
