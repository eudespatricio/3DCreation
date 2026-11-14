"""Export nativo R15 para Roblox Studio (``.rbxlx``), sem import manual.

O ``blocky`` já conhece as caixas e os 16 ossos R15. Este módulo monta um **place** com 16
``Part``s (uma por parte R15, agregando as caixas daquele osso) e 15 ``Motor6D`` com pivô no
joint. Não há upload nem ``MeshPart``: o arquivo é aberto direto no Studio, com as cores do
blocky. A textura/atlas e o GLB continuam sendo o caminho de mesh; aqui é o rig nativo.
"""

from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from . import animacao, config, paths, spec, upload
from .errors import erro_spec
from .providers import blocky

__all__ = [
    "JOINT_R15",
    "descobrir_texturas_pbr",
    "exportar_acessorio_rbxmx",
    "exportar_animacao",
    "exportar_animacoes",
    "exportar_r15",
    "exportar_surface_appearance",
    "ler_place",
    "surface_appearance_xml",
]

#: Parte R15 -> nome da junta (Motor6D) no padrao do Roblox. O Animator casa a Pose pelo nome da
#: JUNTA, nao da parte: sem este mapa o clipe carrega e nao move nada.
JOINT_R15 = {
    "LowerTorso": "Root",
    "UpperTorso": "Waist",
    "Head": "Neck",
    "LeftUpperArm": "LeftShoulder",
    "LeftLowerArm": "LeftElbow",
    "LeftHand": "LeftWrist",
    "RightUpperArm": "RightShoulder",
    "RightLowerArm": "RightElbow",
    "RightHand": "RightWrist",
    "LeftUpperLeg": "LeftHip",
    "LeftLowerLeg": "LeftKnee",
    "LeftFoot": "LeftAnkle",
    "RightUpperLeg": "RightHip",
    "RightLowerLeg": "RightKnee",
    "RightFoot": "RightAnkle",
}


def _cor_int(hexcor: str) -> int:
    valor = int(str(hexcor).lstrip("#"), 16)
    r, g, b = (valor >> 16) & 0xFF, (valor >> 8) & 0xFF, valor & 0xFF
    return (r << 16) | (g << 8) | b


def _vec(tag: str, x: float, y: float, z: float) -> list[str]:
    return [
        f'<Vector3 name="{tag}">',
        f"<X>{x:.6f}</X>",
        f"<Y>{y:.6f}</Y>",
        f"<Z>{z:.6f}</Z>",
        "</Vector3>",
    ]


def _cframe(tag: str, x: float, y: float, z: float) -> list[str]:
    return [
        f'<CoordinateFrame name="{tag}">',
        f"<X>{x:.6f}</X>",
        f"<Y>{y:.6f}</Y>",
        f"<Z>{z:.6f}</Z>",
        "<R00>1</R00><R01>0</R01><R02>0</R02>",
        "<R10>0</R10><R11>1</R11><R12>0</R12>",
        "<R20>0</R20><R21>0</R21><R22>1</R22>",
        "</CoordinateFrame>",
    ]


def _roblox(p, mps: float) -> tuple[float, float, float]:
    """metros (x, y, z) do blocky -> studs (x, z, -y) no Roblox."""
    return (p[0] / mps, p[2] / mps, -p[1] / mps)


def _attachment_xml(nome: str, ref: str, pos) -> list[str]:
    linhas = [
        f'<Item class="Attachment" referent="{ref}">',
        "<Properties>",
        f'<string name="Name">{escape(nome)}</string>',
    ]
    linhas += _cframe("CFrame", *pos)
    linhas += ["</Properties>", "</Item>"]
    return linhas


def _parte_xml(
    nome: str,
    ref: str,
    centro,
    tamanho,
    cor: int,
    filhos: list[list[str]],
    *,
    anchored: bool = False,
    can_collide: bool = False,
    transparency: float | None = None,
    classe: str = "Part",
    mesh_id: str | None = None,
) -> list[str]:
    linhas = [
        f'<Item class="{escape(classe)}" referent="{ref}">',
        "<Properties>",
        f'<string name="Name">{escape(nome)}</string>',
        f'<bool name="Anchored">{"true" if anchored else "false"}</bool>',
        f'<bool name="CanCollide">{"true" if can_collide else "false"}</bool>',
        f'<Color3uint8 name="Color3uint8">{cor}</Color3uint8>',
    ]
    if classe == "MeshPart":
        if mesh_id:
            linhas.append(f'<Content name="MeshId"><url>{escape(mesh_id)}</url></Content>')
        else:
            linhas.append('<Content name="MeshId"><null></null></Content>')
        linhas.append('<Content name="TextureID"><null></null></Content>')
    if transparency is not None:
        linhas.append(f'<float name="Transparency">{transparency:.6g}</float>')
    linhas += _vec("size", *tamanho)
    linhas += _cframe("CFrame", *centro)
    linhas += ["</Properties>"]
    for filho in filhos:
        linhas += filho
    linhas += ["</Item>"]
    return linhas


def _matriz_rotacao(graus: float, eixo: str) -> list[float]:
    """Matriz 3x3 (linha a linha) de rotação em torno de um eixo local, em graus."""
    rad = math.radians(float(graus))
    c, s = math.cos(rad), math.sin(rad)
    if eixo.upper() == "Y":
        return [c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c]
    if eixo.upper() == "Z":
        return [c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0]
    return [1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c]


def _mul_mat3(a: list[float], b: list[float]) -> list[float]:
    """Multiplica duas matrizes 3x3 em formato lista linha a linha."""
    return [
        a[r * 3] * b[c] + a[r * 3 + 1] * b[c + 3] + a[r * 3 + 2] * b[c + 6]
        for r in range(3)
        for c in range(3)
    ]


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
    "orm": "RoughnessMap",
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


def descobrir_texturas_pbr(pasta: str | Path, item_id: str) -> dict[str, str]:
    """Descobre arquivos de textura PBR existentes em ``pasta`` para ``item_id``."""
    base = Path(pasta)
    if not base.is_dir():
        return {}
    candidatos = {
        "ColorMap": (f"{item_id}_baseColor.png", f"{item_id}_albedo.png", "baseColor.png"),
        "NormalMap": (f"{item_id}_normal.png", "normal.png"),
        "RoughnessMap": (f"{item_id}_roughness.png", f"{item_id}_orm.png", "roughness.png", "orm.png"),
        "MetalnessMap": (f"{item_id}_metalness.png", f"{item_id}_metallic.png", "metalness.png", "metallic.png"),
    }
    encontrados: dict[str, str] = {}
    for campo, nomes in candidatos.items():
        for nome in nomes:
            if (base / nome).is_file():
                encontrados[campo] = nome
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
    """Gera XML ``<Item class="SurfaceAppearance">`` quando há mapas PBR válidos."""
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
    nome = Path(caminho).name.lower()
    if "_normal." in nome or nome == "normal.png":
        return "NormalMap"
    if "_orm." in nome or "_roughness." in nome or nome in ("orm.png", "roughness.png"):
        return "RoughnessMap"
    if "_metalness." in nome or "_metallic." in nome or nome in ("metalness.png", "metallic.png"):
        return "MetalnessMap"
    return "ColorMap"


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

    mapas: dict[str, str] = {}
    bruto_tex = dados.get("texturas") or dados.get("surface_appearance")
    if isinstance(bruto_tex, Mapping):
        mapas.update(_normalizar_mapas_pbr(bruto_tex))

    entradas = dados.get("files") or dados.get("arquivos") or dados.get("arquivos_textura") or []
    if isinstance(entradas, list):
        for arq in entradas:
            if not isinstance(arq, Mapping):
                continue
            caminho = str(arq.get("caminho") or "").strip()
            if not caminho:
                continue
            papel = str(arq.get("papel") or "").strip().lower()
            canal = _ALIASES_SURFACE.get(papel)
            if canal is None and papel == "textura":
                canal = _canal_por_nome(caminho)
            if canal and canal not in mapas:
                mapas[canal] = caminho

    for canal, caminho in descobrir_texturas_pbr(origem_manifesto.parent, id_efetivo).items():
        mapas.setdefault(canal, caminho)

    return dados, mapas, id_efetivo


def _mapas_pbr_manifesto(
    origem_manifesto: Path,
    item_id: str | None = None,
) -> tuple[dict[str, str], str]:
    """Extrai mapas PBR de um arquivo ``manifest.json`` e faz fallback na pasta irma."""
    _dados, mapas, id_efetivo = _carregar_manifesto_rbx(origem_manifesto, item_id)
    return mapas, id_efetivo


def _escrever_xml_seguro(
    xml: str,
    saida: str | Path | None,
    contexto: str,
) -> tuple[str | None, int]:
    destino_str = None
    tamanho = len(xml.encode("utf-8"))
    if saida is not None:
        destino = config.normalizar(saida)
        config.validar_destino(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(xml, encoding="utf-8")
        destino_str = str(destino)
        tamanho = destino.stat().st_size
    return destino_str, tamanho


def exportar_surface_appearance(
    texturas: Mapping[str, str | Path] | str | Path,
    item_id: str | None = None,
    saida: str | Path | None = None,
    *,
    asset_ids: Mapping[str, str] | None = None,
    ledger: str | Path | bool | None = None,
) -> dict:
    """Gera ``.rbxmx`` com ``SurfaceAppearance`` (``materiais_max: 1`` preservado).

    Aceita caminho para ``manifest.json``, pasta com texturas PBR (usando ``item_id``) ou
    mapeamento direto canal/alias -> caminho/URL.
    """
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
    att_nome = (attachment_name or str(anexo_meta.get("attachment_roblox") or "") or "HatAttachment").strip()
    eh_skinned = bool(skinned) if skinned is not None else bool(anexo_meta.get("skinned", False))

    if size_studs is not None:
        tam = (float(size_studs[0]), float(size_studs[1]), float(size_studs[2]))
    else:
        raw_geom = manifesto.get("geometry")
        bbox = raw_geom.get("bbox_m") if isinstance(raw_geom, Mapping) else None
        raw_unid = manifesto.get("unidades_export")
        unid: Mapping[str, Any] = raw_unid if isinstance(raw_unid, Mapping) else {}
        mps = float(unid.get("metros_por_unidade") or metros_por_stud)
        if isinstance(bbox, (list, tuple)) and len(bbox) == 3 and mps > 0:
            tam = (max(0.05, float(bbox[0]) / mps), max(0.05, float(bbox[2]) / mps), max(0.05, float(bbox[1]) / mps))
        else:
            tam = (1.0, 1.0, 1.0)

    mesh_uri = _resolver_mesh_uri(
        mesh_id=mesh_id,
        mesh_arquivo=mesh_arquivo,
        id_efetivo=id_efetivo,
        manifesto=manifesto,
        asset_ids=asset_ids,
        ledger=ledger,
    )

    nome_acc = (nome_acessorio or id_efetivo).strip()
    mesh_tag = f'<Content name="MeshId"><url>{escape(mesh_uri)}</url></Content>' if mesh_uri else '<Content name="MeshId"><null></null></Content>'

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
        *_cframe("AttachmentPoint", *attachment_pos),
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
        *_attachment_xml(att_nome, "RBX2", attachment_pos),
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


_PRIORIDADE_CLIPE = {"idle": 0, "walk": 1, "run": 1}
_NAO_LOOP_CLIPES = frozenset({"jump", "attack", "block", "hit", "death"})


def _bone_tree_xml(
    ossos: list[dict],
    partes: Mapping[str, dict],
    mps: float,
    ref_start: int,
) -> tuple[list[str], int]:
    """Gera hierarquia aninhada ``<Item class="Bone">`` a partir dos ossos R15."""
    filhos_por_pai: dict[str | None, list[dict]] = {}
    for osso in ossos:
        filhos_por_pai.setdefault(osso.get("pai"), []).append(osso)

    prox = ref_start

    def _emit(osso: dict, pai_pos: tuple[float, float, float]) -> list[str]:
        nonlocal prox
        nome = str(osso["nome"])
        ref = f"RBX{prox}"
        prox += 1
        cab = osso.get("cabeca")
        abs_pos = _roblox(cab, mps) if cab else partes[nome]["centro"]
        rel_pos = (abs_pos[0] - pai_pos[0], abs_pos[1] - pai_pos[1], abs_pos[2] - pai_pos[2])
        linhas = [
            f'<Item class="Bone" referent="{ref}">',
            "<Properties>",
            f'<string name="Name">{escape(nome)}</string>',
            *_cframe("CFrame", *rel_pos),
            "</Properties>",
        ]
        for filho in filhos_por_pai.get(nome, []):
            linhas += _emit(filho, abs_pos)
        linhas.append("</Item>")
        return linhas

    out: list[str] = []
    for raiz in filhos_por_pai.get(None, []):
        out += _emit(raiz, (0.0, 0.0, 0.0))
    return out, prox


def _sequencia_xml(clipe: dict, referent: int) -> tuple[list[str], int]:
    """KeyframeSequence do Roblox com as poses do clipe (D69)."""
    nome_clipe = str(clipe.get("nome") or "")
    loop = bool(clipe.get("loop", nome_clipe not in _NAO_LOOP_CLIPES))
    prioridade = int(clipe.get("priority", _PRIORIDADE_CLIPE.get(nome_clipe, 2)))
    linhas = [
        f'<Item class="KeyframeSequence" referent="RBX{referent}">',
        "<Properties>",
        f'<string name="Name">{escape(nome_clipe)}</string>',
        f'<bool name="Loop">{"true" if loop else "false"}</bool>',
        f'<token name="Priority">{prioridade}</token>',
        "</Properties>",
    ]
    referent += 1
    for chave in clipe.get("chaves") or []:
        linhas += [
            f'<Item class="Keyframe" referent="RBX{referent}">',
            "<Properties>",
            f'<float name="Time">{float(chave.get("segundos", 0.0)):.4f}</float>',
            "</Properties>",
        ]
        referent += 1
        # pose COMPLETA: o Animator do Roblox so aplica a chave quando ela cobre as juntas do
        # rig; junta fora do clipe entra com identidade (medido: clipe parcial nao move nada,
        # nem no client nem no servidor). Poses que compartilham a mesma junta R15 são compostas.
        dadas_m: dict[str, list[float]] = {}
        dadas_pos: dict[str, list[float]] = {}
        for p in chave.get("poses") or []:
            junta = JOINT_R15.get(str(p.get("osso", "")), str(p.get("osso", "")))
            m_p = _matriz_rotacao(float(p.get("graus", 0.0)), str(p.get("eixo") or "X"))
            dadas_m[junta] = m_p if junta not in dadas_m else _mul_mat3(dadas_m[junta], m_p)
            desl = p.get("deslocamento_m")
            if isinstance(desl, (list, tuple)) and len(desl) == 3:
                dx, dy, dz = float(desl[0]), float(desl[1]), float(desl[2])
                acc = dadas_pos.setdefault(junta, [0.0, 0.0, 0.0])
                acc[0] += dx
                acc[1] += dz
                acc[2] += -dy
        identidade = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        for junta in JOINT_R15.values():
            m = dadas_m.get(junta, identidade)
            pos = dadas_pos.get(junta)
            pos_tag = (
                f"<X>{pos[0]:.6f}</X><Y>{pos[1]:.6f}</Y><Z>{pos[2]:.6f}</Z>"
                if pos is not None and any(abs(v) > 1e-9 for v in pos)
                else "<X>0</X><Y>0</Y><Z>0</Z>"
            )
            linhas += [
                f'<Item class="Pose" referent="RBX{referent}">',
                "<Properties>",
                '<CoordinateFrame name="CFrame">',
                pos_tag,
                f"<R00>{m[0]:.6f}</R00><R01>{m[1]:.6f}</R01><R02>{m[2]:.6f}</R02>",
                f"<R10>{m[3]:.6f}</R10><R11>{m[4]:.6f}</R11><R12>{m[5]:.6f}</R12>",
                f"<R20>{m[6]:.6f}</R20><R21>{m[7]:.6f}</R21><R22>{m[8]:.6f}</R22>",
                "</CoordinateFrame>",
                '<float name="Weight">1</float>',
                f'<string name="Name">{escape(junta)}</string>',
                "</Properties>",
                "</Item>",
            ]
            referent += 1
        linhas.append("</Item>")
    linhas.append("</Item>")
    return linhas, referent


def _gerar_rbxmx_animacoes(
    lote: str | Path,
    item_id: str,
    pedidos: list[str],
    saida: str | Path | None,
    sufixo_padrao: str,
) -> tuple[Path, list[dict]]:
    doc = spec.carregar_arquivo(lote)
    doc, perfil, _avisos = spec.preparar(doc)
    item = next((i for i in doc["lote"] if i.get("id") == item_id), None)
    if item is None:
        raise erro_spec(f"export-anim: item '{item_id}' nao existe no lote")
    clipes = animacao.clipes(perfil, item.get("esqueleto") or "r15@1", pedidos)
    if not clipes:
        raise erro_spec(
            f"export-anim: '{', '.join(pedidos)}' nao tem gerador ou o item nao pede animacao "
            f"(animacoes_base={item.get('animacoes_base')})"
        )
    itens: list[str] = []
    referent = 0
    for escolhido in clipes:
        seq, referent = _sequencia_xml(escolhido, referent)
        itens += seq
    xml = "\n".join(
        ['<?xml version="1.0" encoding="utf-8"?>', '<roblox version="4">']
        + itens
        + ["</roblox>"]
    ) + "\n"
    ElementTree.fromstring(xml)

    if saida is None:
        destino = paths.dir_saida() / "r15" / f"{item_id}_{sufixo_padrao}.rbxmx"
    else:
        destino = Path(saida).expanduser()
        if str(destino).startswith("/mnt/") or str(destino).startswith("//"):
            raise erro_spec("export-anim: nao escreve em /mnt ou UNC")
        destino = config.normalizar(destino)
        config.validar_destino(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(xml, encoding="utf-8")
    return destino, clipes


def exportar_animacao(
    lote: str | Path,
    item_id: str,
    clipe: str | list[str] | tuple[str, ...] = "idle",
    saida: str | Path | None = None,
) -> dict:
    """Gera um ``.rbxmx`` com KeyframeSequence (``idle``, ``walk``, ``run``, ``jump``).

    A definicao e a mesma do glb (`animacao.clipes`) e do `.rbxlx` (D69): nao existe segunda fonte.
    """
    if isinstance(clipe, (list, tuple)):
        return exportar_animacoes(lote, item_id, list(clipe), saida=saida)
    if isinstance(clipe, str) and "," in clipe:
        lista = [c.strip() for c in clipe.split(",") if c.strip()]
        if not lista:
            raise erro_spec("export-anim: informe ao menos um clipe")
        if len(lista) > 1:
            return exportar_animacoes(lote, item_id, lista, saida=saida)
        clipe = lista[0]
    destino, clipes = _gerar_rbxmx_animacoes(lote, item_id, [str(clipe)], saida, str(clipe))
    escolhido = clipes[0]
    return {
        "ok": True,
        "saida": str(destino),
        "bytes": destino.stat().st_size,
        "clipe": escolhido["nome"],
        "duracao_s": escolhido["duracao_s"],
        "keyframes": len(escolhido.get("chaves") or []),
    }


def exportar_animacoes(
    lote: str | Path,
    item_id: str,
    clipes: list[str] | tuple[str, ...] | None = None,
    saida: str | Path | None = None,
) -> dict:
    """Gera um ``.rbxmx`` multi-clipe com todas as KeyframeSequence pedidas (D69 / Fase B)."""
    doc = spec.carregar_arquivo(lote)
    doc, _perfil, _avisos = spec.preparar(doc)
    item = next((i for i in doc["lote"] if i.get("id") == item_id), None)
    if item is None:
        raise erro_spec(f"export-anim: item '{item_id}' nao existe no lote")
    pedidos = [str(c) for c in (clipes or item.get("animacoes_base") or ["idle", "walk", "run", "jump"])]
    destino, gerados = _gerar_rbxmx_animacoes(lote, item_id, pedidos, saida, "anims")
    return {
        "ok": True,
        "saida": str(destino),
        "bytes": destino.stat().st_size,
        "clipes": [c["nome"] for c in gerados],
        "duracoes_s": {c["nome"]: c["duracao_s"] for c in gerados},
        "keyframes": {c["nome"]: len(c.get("chaves") or []) for c in gerados},
    }


def ler_place(caminho: str | Path) -> dict:
    """Le o place gerado: Partes, Motor6D, clipes (KeyframeSequence), SurfaceAppearance e Accessories."""
    raiz = ElementTree.parse(Path(caminho)).getroot()
    nomes: dict[str, str] = {}
    partes: dict[str, dict] = {}
    motores: list[dict] = []
    clipes: list[dict] = []
    surface_appearances: list[dict] = []
    acessorios: list[dict] = []

    def _cframe(node) -> list[float]:
        return [float(node.findtext(e)) for e in ("X", "Y", "Z")]

    def _content_url(props, nome_campo: str) -> str | None:
        node = props.find(f"Content[@name='{nome_campo}']")
        if node is None:
            return None
        url = node.findtext("url")
        return url if url else None

    def _ler_surface(sa_node, parte: str | None) -> dict | None:
        sa_props = sa_node.find("Properties")
        if sa_props is None:
            return None
        return {
            "parte": parte,
            "nome": sa_props.findtext("string[@name='Name']") or "",
            "ColorMap": _content_url(sa_props, "ColorMap"),
            "NormalMap": _content_url(sa_props, "NormalMap"),
            "RoughnessMap": _content_url(sa_props, "RoughnessMap"),
            "MetalnessMap": _content_url(sa_props, "MetalnessMap"),
        }

    for sa in raiz.findall("Item[@class='SurfaceAppearance']"):
        lido_sa = _ler_surface(sa, None)
        if lido_sa is not None:
            surface_appearances.append(lido_sa)

    for item in raiz.iter("Item"):
        classe = item.get("class")
        props = item.find("Properties")
        if props is None:
            continue
        if classe in ("Part", "MeshPart"):
            nome = props.findtext("string[@name='Name']") or ""
            if nome == "Baseplate":
                continue
            nomes[item.get("referent") or ""] = nome
            size = props.find("Vector3[@name='size']")
            cf = props.find("CoordinateFrame[@name='CFrame']")
            if size is not None and cf is not None:
                partes[nome] = {
                    "size": [float(size.findtext(e) or 0.0) for e in ("X", "Y", "Z")],
                    "cframe": _cframe(cf),
                }
            for sa in item.findall("Item[@class='SurfaceAppearance']"):
                lido_sa = _ler_surface(sa, nome)
                if lido_sa is not None:
                    surface_appearances.append(lido_sa)
        elif classe == "Accessory":
            handle = item.find("Item[@class='MeshPart']")
            h_props = handle.find("Properties") if handle is not None else None
            atts = (
                [
                    att.findtext("Properties/string[@name='Name']") or ""
                    for att in handle.findall("Item[@class='Attachment']")
                ]
                if handle is not None
                else []
            )
            acessorios.append(
                {
                    "nome": props.findtext("string[@name='Name']") or "",
                    "handle": (
                        h_props.findtext("string[@name='Name']") or ""
                        if h_props is not None
                        else ""
                    ),
                    "mesh_id": _content_url(h_props, "MeshId") if h_props is not None else None,
                    "attachments": atts,
                }
            )
    for item in raiz.iter("Item"):
        classe = item.get("class")
        props = item.find("Properties")
        if props is None:
            continue
        if classe == "Motor6D":
            motores.append(
                {
                    "nome": props.findtext("string[@name='Name']") or "",
                    "part0": nomes.get(props.findtext("Ref[@name='Part0']") or "", ""),
                    "part1": nomes.get(props.findtext("Ref[@name='Part1']") or "", ""),
                    "c0": _cframe(props.find("CoordinateFrame[@name='C0']")),
                    "c1": _cframe(props.find("CoordinateFrame[@name='C1']")),
                }
            )
        elif classe == "KeyframeSequence":
            chaves = []
            for keyframe in item.findall("Item[@class='Keyframe']"):
                poses = []
                for pose in keyframe.findall("Item[@class='Pose']"):
                    cf = pose.find("Properties/CoordinateFrame[@name='CFrame']")
                    poses.append(
                        {
                            "osso": pose.findtext("Properties/string[@name='Name']") or "",
                            "cframe": (
                                [float(cf.findtext(e) or 0.0) for e in ("X", "Y", "Z")]
                                + [
                                    float(cf.findtext(f"R{i}{j}") or 0.0)
                                    for i in range(3)
                                    for j in range(3)
                                ]
                                if cf is not None
                                else []
                            ),
                        }
                    )
                chaves.append(
                    {
                        "tempo": float(
                            keyframe.findtext("Properties/float[@name='Time']") or 0.0
                        ),
                        "poses": poses,
                    }
                )
            clipes.append(
                {
                    "nome": props.findtext("string[@name='Name']") or "",
                    "loop": (props.findtext("bool[@name='Loop']") or "false") == "true",
                    "priority": int(props.findtext("token[@name='Priority']") or 0),
                    "chaves": chaves,
                }
            )
    return {
        "partes": partes,
        "motores": motores,
        "clipes": clipes,
        "surface_appearances": surface_appearances,
        "acessorios": acessorios,
    }


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
) -> dict:
    """Gera um place ``.rbxlx`` com o rig R15 (Parts/MeshParts + Motor6D ou Bone skinned) do item blocky."""
    if modo_rig not in ("motor6d", "bone"):
        raise erro_spec(f"export-r15: modo_rig invalido '{modo_rig}' (use motor6d ou bone)")
    doc = spec.carregar_arquivo(lote)
    doc, perfil, _avisos = spec.preparar(doc)
    item = next((i for i in doc["lote"] if i.get("id") == item_id), None)
    if item is None:
        raise erro_spec(f"export-r15: item '{item_id}' nao existe no lote")
    if item.get("rota") != "blocky":
        raise erro_spec("export-r15: so a rota blocky gera .rbxlx nativo")
    if not item.get("auto_rig") or item.get("esqueleto") != "r15@1":
        raise erro_spec("export-r15: item precisa de auto_rig: true e esqueleto: r15@1")

    mps = float(metros_por_stud or (perfil.get("unidades") or {}).get("metros_por_stud", 0.28))
    if mps <= 0:
        raise erro_spec("export-r15: metros_por_stud precisa ser > 0")

    with tempfile.TemporaryDirectory(prefix="forge3d-r15-") as td:
        blocky.BlockyProvider().gerar(item, perfil, Path(td))
        modelo = json.loads((Path(td) / "modelo.json").read_text(encoding="utf-8"))

    caixas = modelo.get("caixas") or []
    ossos = modelo.get("ossos") or []
    if len(ossos) != 16:
        raise erro_spec(f"export-r15: esperava 16 ossos R15, achei {len(ossos)}")

    # GAP-044: o blocky nasce com a altura dele (1,906 m neste R15) e o pos-processo normaliza a
    # malha para `altura_metros`. O .rbxlx tem que aplicar a MESMA transformacao — escala uniforme
    # e pivo na base — senao o rig fica 3% acima do package no Studio.
    alvo_m = float(item["altura_metros"])
    minimo = [min(c["min"][i] for c in caixas) for i in range(3)]
    maximo = [max(c["max"][i] for c in caixas) for i in range(3)]
    altura_bruta = maximo[2] - minimo[2]
    if altura_bruta <= 0:
        raise erro_spec("export-r15: geometria com altura zero")
    fator = alvo_m / altura_bruta
    pivo = [(minimo[0] + maximo[0]) / 2, (minimo[1] + maximo[1]) / 2, minimo[2]]

    def _normalizar(ponto: list[float]) -> list[float]:
        return [round((ponto[i] - pivo[i]) * fator, 6) for i in range(3)]

    caixas = [{**c, "min": _normalizar(c["min"]), "max": _normalizar(c["max"])} for c in caixas]
    ossos = [
        {
            **o,
            "cabeca": _normalizar(o["cabeca"]),
            **({"cauda": _normalizar(o["cauda"])} if o.get("cauda") else {}),
        }
        for o in ossos
    ]

    partes: dict[str, dict] = {}
    pendentes: list[str] = []
    for osso in ossos:
        nome = osso["nome"]
        minhas = [c for c in caixas if c.get("osso") == nome]
        if minhas:
            mn = [min(c["min"][i] for c in minhas) for i in range(3)]
            mx = [max(c["max"][i] for c in minhas) for i in range(3)]
            centro_m = [(mn[i] + mx[i]) / 2 for i in range(3)]
            tamanho_m = [max(0.02, mx[i] - mn[i]) for i in range(3)]
            maior = max(minhas, key=lambda c: (c["max"][0] - c["min"][0]) * (c["max"][1] - c["min"][1]) * (c["max"][2] - c["min"][2]))
            cor = _cor_int(maior["cor"])
            partes[nome] = {
                "centro": _roblox(centro_m, mps),
                # GAP-044: o TAMANHO tambem permuta, como o centro. Antes ele ia (x, y, z) direto e a
                # Part saia com altura = profundidade, esticando o rig em Y (6,8086 em vez de 6,6071).
                "tamanho": (tamanho_m[0] / mps, tamanho_m[2] / mps, tamanho_m[1] / mps),
                "cor": cor,
                "centro_m": centro_m,
            }
        else:
            pendentes.append(nome)

    for nome in pendentes:
        if nome == "HumanoidRootPart" and "LowerTorso" in partes:
            lt = partes["LowerTorso"]
            centro_m = list(lt["centro_m"])
            lt_tam = lt["tamanho"]
            tam = (min(lt_tam[0], 2.0), lt_tam[1], min(lt_tam[2], 1.0))
            cor = 0x7D858F
        else:
            centro_m = [0.0, 0.0, max(0.10, 0.05 * alvo_m)]
            tam = (0.20 / mps, 0.20 / mps, 0.20 / mps)
            cor = 0x7D858F
        partes[nome] = {
            "centro": _roblox(centro_m, mps),
            "tamanho": tam,
            "cor": cor,
            "centro_m": centro_m,
        }

    motores: list[dict] = []
    for osso in ossos:
        pai = osso.get("pai")
        if not pai:
            continue
        nome = osso["nome"]
        p0 = partes[pai]["centro_m"]
        p1 = partes[nome]["centro_m"]
        joint = osso["cabeca"]
        c0 = _roblox([joint[i] - p0[i] for i in range(3)], mps)
        c1 = _roblox([joint[i] - p1[i] for i in range(3)], mps)
        motores.append(
            {
                "nome": JOINT_R15.get(nome, f"{pai}_{nome}"),
                "parte0": pai,
                "parte1": nome,
                "c0": c0,
                "c1": c1,
            }
        )

    # referents deterministas: Workspace=RBX0, Model=RBX1, partes=RBX2.., motores, attachments, Humanoid, Baseplate
    refs = {"workspace": "RBX0", "model": "RBX1"}
    prox_ref = 2
    for osso in ossos:
        refs[osso["nome"]] = f"RBX{prox_ref}"
        prox_ref += 1
    for motor in motores:
        motor["ref"] = f"RBX{prox_ref}"
        prox_ref += 1

    attachments_por_parte: dict[str, list[list[str]]] = {}
    total_attachments = 0
    for motor in motores:
        att_nome = f"{motor['nome']}RigAttachment"
        for parte_nome, pos in ((motor["parte0"], motor["c0"]), (motor["parte1"], motor["c1"])):
            att_ref = f"RBX{prox_ref}"
            prox_ref += 1
            total_attachments += 1
            attachments_por_parte.setdefault(parte_nome, []).append(
                _attachment_xml(att_nome, att_ref, pos)
            )
    anexos_padrao = (
        ("Head", "HatAttachment", lambda tam: (0.0, tam[1] / 2.0, 0.0)),
        ("Head", "HairAttachment", lambda tam: (0.0, tam[1] / 2.0, 0.0)),
        ("UpperTorso", "BodyBackAttachment", lambda tam: (0.0, 0.0, tam[2] / 2.0)),
        ("UpperTorso", "BodyFrontAttachment", lambda tam: (0.0, 0.0, -tam[2] / 2.0)),
        ("UpperTorso", "LeftCollarAttachment", lambda tam: (tam[0] / 2.0, tam[1] / 2.0, 0.0)),
        ("UpperTorso", "RightCollarAttachment", lambda tam: (-tam[0] / 2.0, tam[1] / 2.0, 0.0)),
        ("LowerTorso", "WaistCenterAttachment", lambda _tam: (0.0, 0.0, 0.0)),
        ("RightHand", "RightGripAttachment", lambda tam: (0.0, -tam[1] / 2.0, 0.0)),
        ("LeftHand", "LeftGripAttachment", lambda tam: (0.0, -tam[1] / 2.0, 0.0)),
    )
    for parte_nome, att_nome, pos_fn in anexos_padrao:
        if parte_nome not in partes:
            continue
        att_ref = f"RBX{prox_ref}"
        prox_ref += 1
        total_attachments += 1
        attachments_por_parte.setdefault(parte_nome, []).append(
            _attachment_xml(att_nome, att_ref, pos_fn(partes[parte_nome]["tamanho"]))
        )

    humanoid_ref = f"RBX{prox_ref}"
    animator_ref = f"RBX{prox_ref + 1}"
    base_ref = f"RBX{prox_ref + 2}"
    prox_ref += 3

    motores_por_parte: dict[str, list[list[str]]] = {}
    for motor in motores:
        linhas = [
            f'<Item class="Motor6D" referent="{motor["ref"]}">',
            "<Properties>",
            f'<string name="Name">{escape(motor["nome"])}</string>',
            f'<Ref name="Part0">{refs[motor["parte0"]]}</Ref>',
            f'<Ref name="Part1">{refs[motor["parte1"]]}</Ref>',
        ]
        linhas += _cframe("C0", *motor["c0"])
        linhas += _cframe("C1", *motor["c1"])
        linhas += ["</Properties>", "</Item>"]
        motores_por_parte.setdefault(motor["parte0"], []).append(linhas)

    mapas_pbr = _normalizar_mapas_pbr(texturas)
    if not mapas_pbr and texturas_dir is not None:
        mapas_pbr = descobrir_texturas_pbr(texturas_dir, item_id)
    mapas_pbr = _resolver_asset_ids_pbr(mapas_pbr, asset_ids, item_id=item_id, ledger=ledger)
    mesh_uri = _resolver_mesh_uri(
        mesh_id=None,
        mesh_arquivo=None,
        id_efetivo=item_id,
        manifesto=None,
        asset_ids=asset_ids,
        ledger=ledger,
    )

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

    linhas = ['<?xml version="1.0" encoding="utf-8"?>', '<roblox version="4">', f'<Item class="Workspace" referent="{refs["workspace"]}">', "<Properties>", '<string name="Name">Workspace</string>', "</Properties>"]
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
            usar_meshpart = bool(mapas_pbr) and not eh_hrp
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
                mesh_id=mesh_uri or None if usar_meshpart else None,
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
    # D69: os clipes pedidos viram KeyframeSequence dentro do place (mesma definicao do glb)
    clipes = animacao.clipes(perfil, item.get("esqueleto") or "r15@1", item.get("animacoes_base"))
    referent_anim = prox_ref
    for clipe in clipes:
        itens, referent_anim = _sequencia_xml(clipe, referent_anim)
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
    ElementTree.fromstring(xml)  # falha cedo se o XML estiver quebrado

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
