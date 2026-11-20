"""Exportacao de ``Accessory`` (.rbxmx) e resolucao de sockets em studs para Roblox."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .errors import erro_spec
from .rbx_pbr import (
    _carregar_manifesto_rbx,
    _normalizar_mapas_pbr,
    _resolver_asset_ids_pbr,
    _resolver_mesh_uri,
    _surface_appearance_xml,
    descobrir_texturas_pbr,
)
from .rbx_xml import (
    JOINT_R15,
    _attachment_xml,
    _cframe,
    _escrever_xml_seguro,
    _vec,
)

_MOTOR_NOMES_R15 = frozenset(JOINT_R15.values())

_MAPA_ATT_SOCKETS: dict[str, tuple[str, ...]] = {
    "RightGripAttachment": ("RightGripAttachment", "GripAttachment", "Hand.R", "RightHand", "Socket_HandR"),
    "GripAttachment": ("GripAttachment", "RightGripAttachment", "Hand.R", "RightHand", "Socket_HandR"),
    "LeftGripAttachment": ("LeftGripAttachment", "Hand.L", "LeftHand", "Socket_HandL"),
    "BodyBackAttachment": ("BodyBackAttachment", "Back", "Socket_Back", "Chest", "UpperTorso"),
    "HatAttachment": ("HatAttachment", "Head", "Socket_Head"),
    "HairAttachment": ("HairAttachment", "HatAttachment", "Head", "Socket_Head"),
    "LeftCollarAttachment": ("LeftCollarAttachment", "Shoulder.L", "LeftShoulder", "Socket_ShoulderL"),
    "RightCollarAttachment": ("RightCollarAttachment", "Shoulder.R", "RightShoulder", "Socket_ShoulderR"),
}


def _normalizar_sockets_map(raw_sockets: Any) -> dict[str, dict[str, Any]] | None:
    if isinstance(raw_sockets, Mapping):
        return {str(k): dict(v) for k, v in raw_sockets.items() if isinstance(v, Mapping)}
    if isinstance(raw_sockets, list):
        out: dict[str, dict[str, Any]] = {}
        for item_s in raw_sockets:
            if not isinstance(item_s, Mapping):
                continue
            nome = str(item_s.get("nome") or item_s.get("id") or "").strip()
            osso = str(item_s.get("osso") or "").strip()
            entry = dict(item_s)
            if "rotacao_wxyz" in entry and "rotacao_quat_wxyz" not in entry:
                entry["rotacao_quat_wxyz"] = entry["rotacao_wxyz"]
            if nome:
                out[nome] = entry
            if osso and osso not in out and nome not in _MOTOR_NOMES_R15:
                out[osso] = entry
        return out or None
    return None


def _socket_pos_studs(
    entrada: Mapping[str, Any],
    mps: float,
) -> tuple[float, float, float] | None:
    """Converte posicao do socket para studs: ``posicao_local`` ja esta em studs; ``posicao_m``/``posicao`` em metros."""
    raw_local = entrada.get("posicao_local")
    if isinstance(raw_local, (list, tuple)) and len(raw_local) == 3:
        return (float(raw_local[0]), float(raw_local[1]), float(raw_local[2]))
    raw_m = entrada.get("posicao_m")
    if raw_m is None:
        raw_m = entrada.get("posicao")
    if isinstance(raw_m, (list, tuple)) and len(raw_m) == 3 and mps > 0:
        return (
            float(raw_m[0]) / mps,
            float(raw_m[1]) / mps,
            float(raw_m[2]) / mps,
        )
    return None


def _resolver_socket_offset(
    sockets_map: Mapping[str, Any] | list[Any] | None,
    att_nome: str,
    mps: float,
) -> tuple[tuple[float, float, float] | None, Any]:
    """Busca offset posicional (em studs) e rotacional em ``manifest.sockets`` para um Attachment."""
    norm_map = _normalizar_sockets_map(sockets_map)
    if not norm_map:
        return None, None
    chaves = _MAPA_ATT_SOCKETS.get(att_nome, (att_nome,))
    entrada: Mapping[str, Any] | None = None
    for k in chaves:
        cand = norm_map.get(k)
        if isinstance(cand, Mapping):
            entrada = cand
            break
    if entrada is None:
        return None, None
    pos_studs = _socket_pos_studs(entrada, mps)
    rot_mat = (
        entrada.get("rotacao_quat_wxyz")
        or entrada.get("rotacao_wxyz")
        or entrada.get("rot_mat")
    )
    return pos_studs, rot_mat


def exportar_acessorio_rbxmx(
    origem: Mapping[str, Any] | str | Path,
    *,
    item_id: str | None = None,
    saida: str | Path | None = None,
    mesh_id: str | None = None,
    attachment_name: str | None = None,
    attachment_pos: tuple[float, float, float] = (0.0, 0.0, 0.0),
    size_studs: tuple[float, float, float] | None = None,
    texturas: Mapping[str, str | Path] | str | Path | None = None,
    asset_ids: Mapping[str, str] | None = None,
    ledger: str | Path | bool | None = None,
    skinned: bool | None = None,
    nome_acessorio: str | None = None,
    metros_por_stud: float = 0.28,
) -> dict:
    """Exporta acessorio modular/mesh (``Accessory`` + ``Handle`` ``MeshPart`` + ``Attachment`` + ``SurfaceAppearance``)."""
    if metros_por_stud <= 0:
        raise erro_spec("export-acessorio: metros_por_stud precisa ser > 0")

    manifesto: dict[str, Any] = {}
    mapas: dict[str, str] = {}
    mesh_arquivo: str | None = None
    id_efetivo = (item_id or "").strip()

    if isinstance(origem, Mapping):
        manifesto = dict(origem)
        id_efetivo = id_efetivo or str(manifesto.get("asset_id") or manifesto.get("id") or "").strip()
        bruto_tex = manifesto.get("texturas") or manifesto.get("surface_appearance")
        if isinstance(bruto_tex, Mapping):
            mapas.update(_normalizar_mapas_pbr(bruto_tex))
    else:
        caminho = Path(origem).expanduser()
        if not caminho.exists():
            raise erro_spec(f"export-acessorio: origem nao encontrada: {caminho}")
        if caminho.is_file() and caminho.suffix.lower() == ".json":
            manifesto, mapas, id_efetivo = _carregar_manifesto_rbx(
                caminho, item_id, contexto="export-acessorio"
            )
        elif caminho.is_file() and caminho.suffix.lower() in (".glb", ".gltf", ".fbx"):
            id_efetivo = id_efetivo or caminho.stem
            mesh_arquivo = caminho.name
            cand_man = caminho.parent / f"{id_efetivo}.manifest.json"
            if cand_man.is_file():
                manifesto, mapas, id_efetivo = _carregar_manifesto_rbx(
                    cand_man, id_efetivo, contexto="export-acessorio"
                )
            else:
                mapas = descobrir_texturas_pbr(caminho.parent, id_efetivo)
        elif caminho.is_dir():
            if not id_efetivo:
                raise erro_spec("export-acessorio: informe item_id ao passar diretorio")
            cand_man = caminho / f"{id_efetivo}.manifest.json"
            if cand_man.is_file():
                manifesto, mapas, id_efetivo = _carregar_manifesto_rbx(
                    cand_man, id_efetivo, contexto="export-acessorio"
                )
            else:
                mapas = descobrir_texturas_pbr(caminho, id_efetivo)
                cand_glb = caminho / f"{id_efetivo}.glb"
                if cand_glb.is_file():
                    mesh_arquivo = cand_glb.name
        else:
            raise erro_spec(f"export-acessorio: formato de origem nao suportado: {caminho}")

    if not id_efetivo:
        id_efetivo = "Accessory"

    if not mesh_arquivo and isinstance(manifesto.get("files"), list):
        for arq in manifesto["files"]:
            if isinstance(arq, Mapping) and str(arq.get("papel") or "").lower() == "mesh":
                mesh_arquivo = str(arq.get("caminho") or "").strip() or None
                break

    if isinstance(texturas, Mapping):
        mapas = _normalizar_mapas_pbr(texturas)
    elif isinstance(texturas, (str, Path)):
        tex_path = Path(texturas).expanduser()
        if tex_path.is_file():
            _m, mapas, _id = _carregar_manifesto_rbx(tex_path, id_efetivo, contexto="export-acessorio")
        elif tex_path.is_dir():
            mapas = descobrir_texturas_pbr(tex_path, id_efetivo)
        else:
            raise erro_spec(f"export-acessorio: texturas nao encontradas: {tex_path}")

    mapas = _resolver_asset_ids_pbr(mapas, asset_ids, item_id=id_efetivo, ledger=ledger)

    raw_anexo = manifesto.get("anexo")
    anexo_meta: Mapping[str, Any] = raw_anexo if isinstance(raw_anexo, Mapping) else {}
    parte_anexo = str(anexo_meta.get("parte") or "").strip().lower()
    osso_anexo = str(anexo_meta.get("osso") or "").strip()
    default_att = "HatAttachment"
    if parte_anexo == "arma" or osso_anexo in ("Hand.R", "RightHand"):
        default_att = "RightGripAttachment"
    elif parte_anexo == "escudo" or osso_anexo in ("Hand.L", "LeftHand", "LowerArm.L"):
        default_att = "LeftGripAttachment"
    elif parte_anexo == "capa" or osso_anexo in ("Chest", "UpperTorso", "Back"):
        default_att = "BodyBackAttachment"
    att_nome = (attachment_name or str(anexo_meta.get("attachment_roblox") or "") or default_att).strip()
    eh_skinned = bool(skinned) if skinned is not None else bool(anexo_meta.get("skinned", False))

    raw_unid = manifesto.get("unidades_export")
    unid_acc: Mapping[str, Any] = raw_unid if isinstance(raw_unid, Mapping) else {}
    mps_acc = float(unid_acc.get("metros_por_unidade") or metros_por_stud)
    if size_studs is not None:
        tam = (float(size_studs[0]), float(size_studs[1]), float(size_studs[2]))
    else:
        raw_geom = manifesto.get("geometry")
        bbox = raw_geom.get("bbox_m") if isinstance(raw_geom, Mapping) else None
        if isinstance(bbox, (list, tuple)) and len(bbox) == 3 and mps_acc > 0:
            # geometry.bbox_m ja esta em eixos Y-up [largura_X, altura_Y, profundidade_Z]
            tam = (
                max(0.05, float(bbox[0]) / mps_acc),
                max(0.05, float(bbox[1]) / mps_acc),
                max(0.05, float(bbox[2]) / mps_acc),
            )
        else:
            tam = (1.0, 1.0, 1.0)

    raw_sockets = manifesto.get("sockets")
    sockets_map = _normalizar_sockets_map(raw_sockets)
    sock_pos, sock_rot = _resolver_socket_offset(sockets_map, att_nome, mps_acc)
    if sock_rot is None and isinstance(anexo_meta.get("offset_rot"), (list, tuple)):
        off_r = anexo_meta["offset_rot"]
        if len(off_r) in (4, 9):
            sock_rot = off_r
    att_pos_efetiva = attachment_pos
    if attachment_pos == (0.0, 0.0, 0.0) and sock_pos is not None:
        att_pos_efetiva = sock_pos

    mesh_uri = _resolver_mesh_uri(
        mesh_id=mesh_id,
        mesh_arquivo=mesh_arquivo,
        id_efetivo=id_efetivo,
        manifesto=manifesto,
        asset_ids=asset_ids,
        ledger=ledger,
    )

    nome_acc = (nome_acessorio or id_efetivo).strip()
    mesh_tag = (
        f'<Content name="MeshId"><url>{escape(mesh_uri)}</url></Content>'
        if mesh_uri
        else '<Content name="MeshId"><null></null></Content>'
    )

    weld_xml: list[str] = []
    if not eh_skinned:
        weld_xml = [
            '<Item class="WeldConstraint" referent="RBX4">',
            "<Properties>",
            '<string name="Name">AccessoryWeld</string>',
            '<bool name="Enabled">true</bool>',
            '<Ref name="Part0">RBX1</Ref>',
            '<Ref name="Part1">null</Ref>',
            "</Properties>",
            "</Item>",
        ]

    linhas = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<roblox version="4">',
        '<Item class="Accessory" referent="RBX0">',
        "<Properties>",
        f'<string name="Name">{escape(nome_acc)}</string>',
        *_cframe("AttachmentPoint", *att_pos_efetiva, rot_mat=sock_rot),
        "</Properties>",
        '<Item class="MeshPart" referent="RBX1">',
        "<Properties>",
        '<string name="Name">Handle</string>',
        '<bool name="Anchored">false</bool>',
        '<bool name="CanCollide">false</bool>',
        mesh_tag,
        '<Content name="TextureID"><null></null></Content>',
        *_vec("size", *tam),
        *_cframe("CFrame", 0.0, 0.0, 0.0),
        "</Properties>",
        *_attachment_xml(att_nome, "RBX2", att_pos_efetiva, rot_mat=sock_rot),
        *_surface_appearance_xml(mapas, referent="RBX3"),
        *weld_xml,
        "</Item>",
        "</Item>",
        "</roblox>",
    ]
    xml = "\n".join(linhas) + "\n"
    ElementTree.fromstring(xml)

    destino_str, tamanho = _escrever_xml_seguro(xml, saida, "export-acessorio")
    return {
        "ok": True,
        "saida": destino_str,
        "bytes": tamanho,
        "item_id": id_efetivo,
        "attachment": att_nome,
        "skinned": eh_skinned,
        "mesh_id": mesh_uri or None,
        "mapas": mapas,
        "materiais": 1 if mapas else 0,
        "xml": xml,
    }
