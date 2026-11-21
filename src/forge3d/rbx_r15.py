"""Exportador principal de place ``.rbxlx`` R15 (blocky e segmentado F08)."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from . import animacao, config, paths, spec
from .errors import erro_spec
from .rbx_acessorio import _normalizar_sockets_map
from .rbx_anim import _sequencia_xml
from .rbx_r15_model import exportar_r15_model
from .rbx_pbr import (
    _extrair_mapas_pbr_manifesto_dict,
    _normalizar_mapas_pbr,
    _resolver_asset_ids_pbr,
    _resolver_mesh_uri,
    _surface_appearance_xml,
    descobrir_texturas_pbr,
)
from .rbx_r15_rig import (
    _bone_tree_xml,
    _carregar_manifesto_r15,
    _montar_motores_e_attachments,
    _montar_partes_blocky,
    _montar_partes_segmentadas,
)
from .rbx_xml import (
    _cframe,
    _parte_xml,
    _roblox,
    _vec,
)


def _validar_asset_ids_r15(
    ossos: list[dict],
    partes: Mapping[str, dict],
    mapas_pbr: Mapping[str, str],
    mesh_uri: str,
    modo_rig: str,
) -> None:
    """Garante que rota nao-blocky tem ``rbxassetid://`` valido em MeshPart e SurfaceAppearance."""
    faltando_mesh: list[str] = []
    if modo_rig == "bone":
        if not str(mesh_uri or "").startswith("rbxassetid://"):
            faltando_mesh.append(f"Forge3DMesh({mesh_uri or 'vazio'})")
    else:
        for osso in ossos:
            nome = osso["nome"]
            if nome == "HumanoidRootPart":
                continue
            uri_parte = str(partes[nome].get("mesh_id") or mesh_uri or "")
            if not uri_parte.startswith("rbxassetid://"):
                faltando_mesh.append(f"{nome}({uri_parte or 'vazio'})")

    faltando_tex = [
        f"{canal}({uri})"
        for canal, uri in mapas_pbr.items()
        if not str(uri or "").startswith("rbxassetid://")
    ]
    if faltando_mesh or faltando_tex:
        detalhes: list[str] = []
        if faltando_mesh:
            detalhes.append(f"MeshId sem rbxassetid://: {', '.join(faltando_mesh)}")
        if faltando_tex:
            detalhes.append(f"SurfaceAppearance sem rbxassetid://: {', '.join(faltando_tex)}")
        raise erro_spec(
            "export-r15: rota nao-blocky exige AssetIds Roblox publicados "
            f"({'; '.join(detalhes)}). Passe --model-id <id>, --asset-ids <json>, "
            "execute 'forge3d upload-model' ou use --rascunho-local."
        )


def exportar_r15(
    lote: str | Path,
    item_id: str,
    saida: str | Path | None = None,
    metros_por_stud: float | None = None,
    anchored_root: bool = False,
    *,
    texturas_dir: str | Path | None = None,
    texturas: Mapping[str, str | Path] | None = None,
    asset_ids: Mapping[str, str] | None = None,
    ledger: str | Path | bool | None = None,
    modo_rig: str = "motor6d",
    sockets: Mapping[str, Any] | list[Any] | None = None,
    manifesto: Mapping[str, Any] | str | Path | None = None,
    model_id: str | int | None = None,
    exigir_asset_ids: bool = False,
) -> dict:
    """Gera um place ``.rbxlx`` com o rig R15 (blocky Parts/MeshParts ou rota segmentada Motor6D)."""
    if modo_rig not in ("motor6d", "bone"):
        raise erro_spec(f"export-r15: modo_rig invalido '{modo_rig}' (use motor6d ou bone)")
    doc = spec.carregar_arquivo(lote)
    doc, perfil, _avisos = spec.preparar(doc)
    item = next((i for i in doc["lote"] if i.get("id") == item_id), None)
    if item is None:
        raise erro_spec(f"export-r15: item '{item_id}' nao existe no lote")

    rig_item = item.get("rig") if isinstance(item.get("rig"), Mapping) else {}
    esqueleto_item = item.get("esqueleto") or rig_item.get("esqueleto")
    auto_rig_ok = bool(item.get("auto_rig")) or rig_item.get("modo") in ("motor6d", "skinned")
    if not auto_rig_ok or esqueleto_item != "r15@1":
        raise erro_spec("export-r15: item precisa de auto_rig: true e esqueleto: r15@1")

    mps = float(metros_por_stud or (perfil.get("unidades") or {}).get("metros_por_stud", 0.28))
    if mps <= 0:
        raise erro_spec("export-r15: metros_por_stud precisa ser > 0")

    eh_blocky = item.get("rota") == "blocky"
    manifesto_eff, pasta_manifesto = _carregar_manifesto_r15(
        manifesto,
        texturas_dir,
        doc,
        item_id,
        usar_destino_exportacao=not eh_blocky,
    )
    if model_id is not None:
        return exportar_r15_model(
            item,
            perfil,
            item_id,
            str(esqueleto_item or "r15@1"),
            mps,
            model_id,
            saida=saida,
            ledger=ledger,
            modo_rig=modo_rig,
            manifesto=manifesto_eff,
        )
    if eh_blocky:
        ossos, partes, caixas, modelo_sockets = _montar_partes_blocky(item, perfil, mps)
    else:
        ossos, partes = _montar_partes_segmentadas(
            item, manifesto_eff, mps, asset_ids, ledger, modo_rig=modo_rig
        )
        caixas = []
        modelo_sockets = None

    raw_sockets_r15 = (
        sockets
        or (manifesto_eff.get("sockets") if isinstance(manifesto_eff, Mapping) else None)
        or item.get("sockets")
        or modelo_sockets
    )
    sockets_r15 = _normalizar_sockets_map(raw_sockets_r15)

    motores, refs, attachments_por_parte, total_attachments, prox_ref = (
        _montar_motores_e_attachments(
            ossos, partes, mps, sockets_r15, eh_blocky=eh_blocky
        )
    )

    humanoid_ref = f"RBX{prox_ref}"
    animator_ref = f"RBX{prox_ref + 1}"
    base_ref = f"RBX{prox_ref + 2}"
    prox_ref += 3

    motores_por_parte: dict[str, list[list[str]]] = {}
    for motor in motores:
        linhas_m = [
            f'<Item class="Motor6D" referent="{motor["ref"]}">',
            "<Properties>",
            f'<string name="Name">{escape(motor["nome"])}</string>',
            f'<Ref name="Part0">{refs[motor["parte0"]]}</Ref>',
            f'<Ref name="Part1">{refs[motor["parte1"]]}</Ref>',
        ]
        c0_p = motor["c0"]
        c1_p = motor["c1"]
        linhas_m += _cframe("C0", c0_p[0], c0_p[1], c0_p[2], rot_mat=motor.get("c0_rot"))
        linhas_m += _cframe("C1", c1_p[0], c1_p[1], c1_p[2], rot_mat=motor.get("c1_rot"))
        linhas_m += ["</Properties>", "</Item>"]
        motores_por_parte.setdefault(motor["parte0"], []).append(linhas_m)

    tex_search_dir = texturas_dir if texturas_dir is not None else pasta_manifesto
    mapas_pbr = _normalizar_mapas_pbr(texturas)
    if not mapas_pbr and isinstance(manifesto_eff, Mapping):
        mapas_pbr = _extrair_mapas_pbr_manifesto_dict(
            manifesto_eff,
            pasta_base=Path(tex_search_dir).expanduser() if tex_search_dir else None,
            id_efetivo=item_id,
        )
    if not mapas_pbr and tex_search_dir is not None:
        mapas_pbr = descobrir_texturas_pbr(tex_search_dir, item_id)
    mapas_pbr = _resolver_asset_ids_pbr(mapas_pbr, asset_ids, item_id=item_id, ledger=ledger)

    mesh_uri = _resolver_mesh_uri(
        mesh_id=None,
        mesh_arquivo=None,
        id_efetivo=item_id,
        manifesto=manifesto_eff,
        asset_ids=asset_ids,
        ledger=ledger,
    )
    if exigir_asset_ids and not eh_blocky and not model_id:
        _validar_asset_ids_r15(ossos, partes, mapas_pbr, mesh_uri, modo_rig)

    hrp_centro_y = partes["HumanoidRootPart"]["centro"][1]
    hrp_meio_y = partes["HumanoidRootPart"]["tamanho"][1] * 0.5
    hip_height = max(0.5, hrp_centro_y - hrp_meio_y)

    aparencia_por_parte: dict[str, list[list[str]]] = {}
    if mapas_pbr and modo_rig == "motor6d":
        for osso in ossos:
            nome = osso["nome"]
            if nome == "HumanoidRootPart":
                continue
            sa_ref = f"RBX{prox_ref}"
            prox_ref += 1
            aparencia_por_parte[nome] = [_surface_appearance_xml(mapas_pbr, referent=sa_ref)]

    linhas = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<roblox version="4">',
        f'<Item class="Workspace" referent="{refs["workspace"]}">',
        "<Properties>",
        '<string name="Name">Workspace</string>',
        "</Properties>",
    ]
    if modo_rig == "bone":
        mesh_ref = f"RBX{prox_ref}"
        prox_ref += 1
        filhos_mesh: list[list[str]] = []
        if mapas_pbr:
            sa_ref = f"RBX{prox_ref}"
            prox_ref += 1
            filhos_mesh.append(_surface_appearance_xml(mapas_pbr, referent=sa_ref))
        bone_xml, prox_ref = _bone_tree_xml(ossos, partes, mps, prox_ref)
        filhos_mesh.append(bone_xml)
        if caixas:
            mn_r = _roblox([min(c["min"][i] for c in caixas) for i in range(3)], mps)
            mx_r = _roblox([max(c["max"][i] for c in caixas) for i in range(3)], mps)
            bbox_tam = (
                max(0.1, abs(mx_r[0] - mn_r[0])),
                max(0.1, abs(mx_r[1] - mn_r[1])),
                max(0.1, abs(mx_r[2] - mn_r[2])),
            )
            bbox_cen = (
                0.5 * (mn_r[0] + mx_r[0]),
                0.5 * (mn_r[1] + mx_r[1]),
                0.5 * (mn_r[2] + mx_r[2]),
            )
        else:
            bbox_cen = partes["HumanoidRootPart"]["centro"]
            bbox_tam = partes["HumanoidRootPart"]["tamanho"]
        linhas += [
            f'<Item class="Model" referent="{refs["model"]}">',
            "<Properties>",
            '<string name="Name">Forge3DR15</string>',
            f'<Ref name="PrimaryPart">{mesh_ref}</Ref>',
            "</Properties>",
        ]
        linhas += _parte_xml(
            "Forge3DMesh",
            mesh_ref,
            bbox_cen,
            bbox_tam,
            0x7D858F,
            filhos_mesh,
            anchored=anchored_root,
            can_collide=True,
            classe="MeshPart",
            mesh_id=mesh_uri or None,
        )
    else:
        linhas += [
            f'<Item class="Model" referent="{refs["model"]}">',
            "<Properties>",
            '<string name="Name">Forge3DR15</string>',
            f'<Ref name="PrimaryPart">{refs["HumanoidRootPart"]}</Ref>',
            "</Properties>",
        ]
        for osso in ossos:
            nome = osso["nome"]
            filhos = (
                attachments_por_parte.get(nome, [])
                + motores_por_parte.get(nome, [])
                + aparencia_por_parte.get(nome, [])
            )
            eh_hrp = nome == "HumanoidRootPart"
            usar_meshpart = (not eh_hrp) and (bool(mapas_pbr) or not eh_blocky)
            mesh_parte = partes[nome].get("mesh_id") or mesh_uri or None
            linhas += _parte_xml(
                nome,
                refs[nome],
                partes[nome]["centro"],
                partes[nome]["tamanho"],
                partes[nome]["cor"],
                filhos,
                anchored=anchored_root if eh_hrp else False,
                can_collide=nome in ("HumanoidRootPart", "LowerTorso", "UpperTorso"),
                transparency=1.0 if eh_hrp else None,
                classe="MeshPart" if usar_meshpart else "Part",
                mesh_id=mesh_parte if usar_meshpart else None,
                collision_fidelity="Box" if usar_meshpart else None,
                render_fidelity="Precise" if usar_meshpart else None,
            )
    linhas += [
        f'<Item class="Humanoid" referent="{humanoid_ref}">',
        "<Properties>",
        '<string name="Name">Humanoid</string>',
        '<token name="RigType">1</token>',
        f'<float name="HipHeight">{hip_height:.4f}</float>',
        "</Properties>",
        f'<Item class="Animator" referent="{animator_ref}">',
        "<Properties>",
        '<string name="Name">Animator</string>',
        "</Properties>",
        "</Item>",
        "</Item>",
        "</Item>",
    ]

    pedidos_anim = (
        item.get("animacoes_base")
        or item.get("clipes")
        or (
            [
                str(a["nome"])
                for a in (item.get("animacoes") or [])
                if isinstance(a, Mapping) and a.get("nome")
            ]
            or None
        )
    )
    clipes = animacao.clipes(perfil, str(esqueleto_item or "r15@1"), pedidos_anim)
    referent_anim = prox_ref
    for clipe in clipes:
        itens, referent_anim = _sequencia_xml(clipe, referent_anim, mps=mps)
        linhas += itens

    linhas += [
        f'<Item class="Part" referent="{base_ref}">',
        "<Properties>",
        '<string name="Name">Baseplate</string>',
        '<bool name="Anchored">true</bool>',
        '<Color3uint8 name="Color3uint8">5404741</Color3uint8>',
    ]
    linhas += _vec("size", 40.0, 1.0, 40.0)
    linhas += _cframe("CFrame", 0.0, -0.5, 0.0)
    linhas += ["</Properties>", "</Item>", "</Item>", "</roblox>"]
    xml = "\n".join(linhas) + "\n"
    ElementTree.fromstring(xml)

    if saida is None:
        destino = paths.dir_saida() / "r15" / f"{item_id}.rbxlx"
    else:
        destino = config.normalizar(saida)
        config.validar_destino(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(xml, encoding="utf-8")
    return {
        "ok": True,
        "saida": str(destino),
        "bytes": destino.stat().st_size,
        "partes": len(ossos) if modo_rig == "motor6d" else 1,
        "motores": len(motores) if modo_rig == "motor6d" else 0,
        "attachments": total_attachments if modo_rig == "motor6d" else 0,
        "modo_rig": modo_rig,
        "metros_por_stud": mps,
        "textura": bool(mapas_pbr),
        **({"surface_appearance": mapas_pbr} if mapas_pbr else {}),
        "animacoes": [c["nome"] for c in clipes],
        "keyframes": {c["nome"]: len(c.get("chaves") or []) for c in clipes},
    }
