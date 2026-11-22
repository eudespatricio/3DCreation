"""Exportacao de ``KeyframeSequence`` (.rbxmx) com arvore R15 de ``Pose`` e parser ``ler_place``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape
from pathlib import Path
from xml.etree import ElementTree

from . import animacao, animacao_pose, config, paths, spec
from .errors import erro_spec
from .rbx_xml import (
    JOINT_R15_REV,
    R15_FILHOS,
    _quat_de_eixo_graus,
    _quat_mul,
    _quat_normalizar,
    _quat_para_mat3,
)

_PRIORIDADE_CLIPE = {
    "idle": 0,
    "walk": 1,
    "run": 1,
    "gallop": 1,
    "wing_flap": 1,
    "glide": 1,
    "ride_idle": 0,
    "ride_fly": 1,
}
_NAO_LOOP_CLIPES = frozenset(
    {
        "jump",
        "attack",
        "slash_combo",
        "cast",
        "block",
        "hit",
        "death",
        "bite",
        "roar",
        "tail_swipe",
        "land",
        "rear_up",
        "mount_up",
        "dismount",
    }
)


def _sequencia_xml(
    clipe: dict,
    referent: int,
    mps: float = 0.28,
    *,
    ancoras: Mapping[str, Sequence[float]] | None = None,
    modo_rig: str = "motor6d",
) -> tuple[list[str], int]:
    """KeyframeSequence do Roblox com arvore aninhada de ``Pose`` R15 (D69 / F05)."""
    mps_eff = float(mps) if mps and mps > 0 else 0.28
    nome_clipe = str(clipe.get("nome") or "")
    loop = bool(clipe.get("loop", nome_clipe not in _NAO_LOOP_CLIPES))
    prioridade = int(clipe.get("priority", _PRIORIDADE_CLIPE.get(nome_clipe, 2)))
    usar_ancoras = ancoras is not None
    drop_base = animacao_pose.calcular_aducao_braco_ancoras(ancoras) if usar_ancoras else 0.0
    fator_altura, min_y_quadril_studs = (
        animacao_pose.escala_deslocamento_ancoras(ancoras, mps=mps_eff)
        if usar_ancoras
        else (1.0, -1e9)
    )
    duracao_s = float(clipe.get("duracao_s") or 0.0)
    linhas = [
        f'<Item class="KeyframeSequence" referent="RBX{referent}">',
        "<Properties>",
        f'<string name="Name">{escape(nome_clipe)}</string>',
        f'<bool name="Loop">{"true" if loop else "false"}</bool>',
        f'<token name="Priority">{prioridade}</token>',
        "</Properties>",
    ]
    referent += 1
    identidade = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]

    def _emit_pose(
        nome_parte: str,
        dadas_q: dict[str, tuple[float, float, float, float]],
        dadas_pos: dict[str, list[float]],
        linhas_out: list[str],
        ref_idx: int,
    ) -> int:
        eh_raiz = nome_parte == "HumanoidRootPart"
        m = _quat_para_mat3(dadas_q[nome_parte]) if nome_parte in dadas_q else identidade
        pos = dadas_pos.get(nome_parte)
        pos_tag = (
            f"<X>{pos[0]:.6f}</X><Y>{pos[1]:.6f}</Y><Z>{pos[2]:.6f}</Z>"
            if pos is not None and any(abs(v) > 1e-9 for v in pos)
            else "<X>0</X><Y>0</Y><Z>0</Z>"
        )
        peso = "0" if eh_raiz else "1"
        linhas_out.extend(
            [
                f'<Item class="Pose" referent="RBX{ref_idx}">',
                "<Properties>",
                '<CoordinateFrame name="CFrame">',
                pos_tag,
                f"<R00>{m[0]:.6f}</R00><R01>{m[1]:.6f}</R01><R02>{m[2]:.6f}</R02>",
                f"<R10>{m[3]:.6f}</R10><R11>{m[4]:.6f}</R11><R12>{m[5]:.6f}</R12>",
                f"<R20>{m[6]:.6f}</R20><R21>{m[7]:.6f}</R21><R22>{m[8]:.6f}</R22>",
                "</CoordinateFrame>",
                f'<float name="Weight">{peso}</float>',
                f'<string name="Name">{escape(nome_parte)}</string>',
            ]
        )
        if not eh_raiz:
            linhas_out.extend(
                [
                    '<token name="EasingStyle">0</token>',
                    '<token name="EasingDirection">0</token>',
                ]
            )
        linhas_out.append("</Properties>")
        ref_idx += 1
        for filho in R15_FILHOS.get(nome_parte, ()):
            ref_idx = _emit_pose(filho, dadas_q, dadas_pos, linhas_out, ref_idx)
        linhas_out.append("</Item>")
        return ref_idx

    chaves = clipe.get("chaves") or []
    for idx_ch, chave in enumerate(chaves):
        linhas += [
            f'<Item class="Keyframe" referent="RBX{referent}">',
            "<Properties>",
            '<string name="Name">Keyframe</string>',
            f'<float name="Time">{float(chave.get("segundos", 0.0)):.4f}</float>',
            "</Properties>",
        ]
        referent += 1
        dadas_q: dict[str, tuple[float, float, float, float]] = {}
        dadas_pos: dict[str, list[float]] = {}
        for p in chave.get("poses") or []:
            raw_osso = str(p.get("osso", "")).strip()
            parte = JOINT_R15_REV.get(raw_osso, raw_osso)
            raw_quat = p.get("rotacao_quat_wxyz")
            if isinstance(raw_quat, (list, tuple)) and len(raw_quat) == 4:
                q_p = _quat_normalizar([float(v) for v in raw_quat])
            else:
                q_p = _quat_de_eixo_graus(float(p.get("graus", 0.0)), str(p.get("eixo") or "X"))
            dadas_q[parte] = q_p if parte not in dadas_q else _quat_mul(dadas_q[parte], q_p)
            desl = p.get("deslocamento_m")
            if isinstance(desl, (list, tuple)) and len(desl) == 3:
                dx = float(desl[0]) * fator_altura
                dy = float(desl[1]) * fator_altura
                dz = float(desl[2]) * fator_altura
                acc = dadas_pos.setdefault(parte, [0.0, 0.0, 0.0])
                acc[0] += dx / mps_eff
                acc[1] += dz / mps_eff
                acc[2] += -dy / mps_eff

        if usar_ancoras:
            if nome_clipe == "death" and "LowerTorso" in dadas_pos:
                dadas_pos["LowerTorso"][1] = max(dadas_pos["LowerTorso"][1], min_y_quadril_studs)
            if drop_base > 0.0:
                if duracao_s > 0.0 and "segundos" in chave:
                    fracao = max(0.0, min(1.0, float(chave["segundos"]) / duracao_s))
                elif len(chaves) > 1:
                    fracao = idx_ch / float(len(chaves) - 1)
                else:
                    fracao = 0.0
                drop_eff = drop_base * animacao_pose.peso_gravidade_clipe(nome_clipe, fracao)
                if drop_eff > 0.0:
                    ang_l = drop_eff if modo_rig == "bone" else -drop_eff
                    ang_r = -drop_eff if modo_rig == "bone" else drop_eff
                    for parte_arm, ang_arm in (("LeftUpperArm", ang_l), ("RightUpperArm", ang_r)):
                        q_drop = _quat_de_eixo_graus(ang_arm, "Z")
                        dadas_q[parte_arm] = (
                            q_drop
                            if parte_arm not in dadas_q
                            else _quat_mul(dadas_q[parte_arm], q_drop)
                        )

        referent = _emit_pose("HumanoidRootPart", dadas_q, dadas_pos, linhas, referent)
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
    mps = float((perfil.get("unidades") or {}).get("metros_por_stud", 0.28))
    itens: list[str] = []
    referent = 0
    for escolhido in clipes:
        seq, referent = _sequencia_xml(escolhido, referent, mps=mps)
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
    """Gera um ``.rbxmx`` com KeyframeSequence (``idle``, ``walk``, ``run``, ``jump``)."""
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

    def _ler_cf(node) -> list[float]:
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
                    "cframe": _ler_cf(cf),
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
                    "c0": _ler_cf(props.find("CoordinateFrame[@name='C0']")),
                    "c1": _ler_cf(props.find("CoordinateFrame[@name='C1']")),
                }
            )
        elif classe == "KeyframeSequence":
            chaves = []
            for keyframe in item.findall("Item[@class='Keyframe']"):
                poses = []
                for pose in keyframe.findall(".//Item[@class='Pose']"):
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
