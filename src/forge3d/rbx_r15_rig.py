"""Montagem de partes, ossos, motores e attachments R15 (blocky e segmentado F08/F10)."""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import Any

from . import upload
from .errors import erro_spec
from .providers import blocky
from .rbx_acessorio import _resolver_socket_offset, _socket_pos_studs
from .rbx_pbr import _carregar_manifesto_rbx
from .rbx_xml import (
    JOINT_R15,
    _attachment_xml,
    _cframe,
    _cor_int,
    _roblox,
)

logger = logging.getLogger(__name__)


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


def _carregar_manifesto_r15(
    manifesto: Mapping[str, Any] | str | Path | None,
    texturas_dir: str | Path | None,
    doc: Mapping[str, Any],
    item_id: str,
    *,
    usar_destino_exportacao: bool = True,
) -> tuple[dict[str, Any] | None, Path | None]:
    """Resolve manifesto explicitamente passado ou via ``texturas_dir`` / ``destino_exportacao``."""
    if isinstance(manifesto, Mapping):
        return dict(manifesto), None
    if isinstance(manifesto, (str, Path)):
        caminho = Path(manifesto).expanduser()
        dados, _mapas, _id = _carregar_manifesto_rbx(caminho, item_id, contexto="export-r15")
        return dados, caminho.parent

    candidatos: list[Path] = []
    if texturas_dir is not None:
        candidatos.append(Path(texturas_dir).expanduser() / f"{item_id}.manifest.json")
    if usar_destino_exportacao:
        dest_exp = doc.get("destino_exportacao")
        if dest_exp:
            candidatos.append(Path(str(dest_exp)).expanduser() / f"{item_id}.manifest.json")

    for cand in candidatos:
        if not cand.is_file():
            continue
        try:
            man_data = json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("export-r15: falha ao ler manifesto %s: %s", cand, exc)
            raise erro_spec(f"export-r15: manifesto ilegivel em {cand}: {exc}") from exc
        if not isinstance(man_data, Mapping):
            raise erro_spec(f"export-r15: manifesto em {cand} precisa ser um objeto JSON")
        return dict(man_data), cand.parent
    return None, None


def _resolver_parte_mesh_uri(
    *,
    nome: str,
    mesh_arquivo: str | None,
    item_id: str,
    asset_ids: Mapping[str, str] | None,
    ledger: str | Path | bool | None,
) -> str:
    """Resolve ``MeshId`` especifico de uma parte R15 (``asset_ids`` -> ``ledger`` -> arquivo local)."""
    candidato: str | None = None
    stem = Path(mesh_arquivo).stem if mesh_arquivo else nome
    if asset_ids:
        chaves = (
            mesh_arquivo or "",
            Path(mesh_arquivo).name if mesh_arquivo else "",
            stem,
            f"{item_id}.{nome}",
            f"{item_id}_{nome}",
            nome,
        )
        for chave in chaves:
            if chave and asset_ids.get(chave):
                candidato = str(asset_ids[chave])
                break
    if not candidato and ledger:
        caminho_ledger: str | Path | None = None if isinstance(ledger, bool) else ledger
        mapa_ledger = upload.resolver_ledger(caminho_ledger)
        lids = (f"{item_id}.{nome}", f"{item_id}_{nome}", nome, stem)
        for lid in lids:
            if not lid:
                continue
            for role in ("mesh", "model", "Model", ""):
                if (lid, role) in mapa_ledger:
                    candidato = mapa_ledger[(lid, role)]
                    break
            if candidato:
                break
    if candidato:
        limpo = candidato.strip()
        if limpo.isdigit() or limpo.startswith("rbxassetid://"):
            return upload.formatar_rbxassetid(limpo)
        return limpo
    return mesh_arquivo or ""


def _montar_partes_blocky(
    item: Mapping[str, Any],
    perfil: Mapping[str, Any],
    mps: float,
) -> tuple[list[dict], dict[str, dict], list[dict], Any]:
    """Gera caixas, ossos e partes R15 normalizadas a partir do ``BlockyProvider``."""
    with tempfile.TemporaryDirectory(prefix="forge3d-r15-") as td:
        blocky.BlockyProvider().gerar(dict(item), dict(perfil), Path(td))
        modelo = json.loads((Path(td) / "modelo.json").read_text(encoding="utf-8"))

    caixas = modelo.get("caixas") or []
    ossos = modelo.get("ossos") or []
    if len(ossos) != 16:
        raise erro_spec(f"export-r15: esperava 16 ossos R15, achei {len(ossos)}")

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
            maior = max(
                minhas,
                key=lambda c: (
                    (c["max"][0] - c["min"][0])
                    * (c["max"][1] - c["min"][1])
                    * (c["max"][2] - c["min"][2])
                ),
            )
            cor = _cor_int(maior["cor"])
            partes[nome] = {
                "centro": _roblox(centro_m, mps),
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
        else:
            centro_m = [0.0, 0.0, max(0.10, 0.05 * alvo_m)]
            tam = (0.20 / mps, 0.20 / mps, 0.20 / mps)
        partes[nome] = {
            "centro": _roblox(centro_m, mps),
            "tamanho": tam,
            "cor": 0x7D858F,
            "centro_m": centro_m,
        }
    return ossos, partes, caixas, modelo.get("sockets")


def _montar_partes_segmentadas(
    item: Mapping[str, Any],
    manifesto_eff: Mapping[str, Any] | None,
    mps: float,
    asset_ids: Mapping[str, str] | None,
    ledger: str | Path | bool | None,
    *,
    modo_rig: str = "motor6d",
) -> tuple[list[dict], dict[str, dict]]:
    """Monta 16 ossos/partes R15 Y-up a partir de ``manifesto['partes']`` e/ou ``rig.ancoras`` (F08/D134)."""
    if not isinstance(manifesto_eff, Mapping):
        raise erro_spec("export-r15: rota nao-blocky exige manifesto com rig.ancoras ou partes[]")
    raw_partes = manifesto_eff.get("partes")
    partes_man = {
        str(p["nome"]): p
        for p in (raw_partes if isinstance(raw_partes, list) else [])
        if isinstance(p, Mapping) and p.get("nome")
    }
    raw_rig = manifesto_eff.get("rig")
    raw_ancoras = raw_rig.get("ancoras") if isinstance(raw_rig, Mapping) else None
    rig_ancoras: Mapping[str, Any] = raw_ancoras if isinstance(raw_ancoras, Mapping) else {}
    tem_ancoras = bool(rig_ancoras) or (
        bool(partes_man) and all("ancora" in p for p in partes_man.values())
    )
    if modo_rig == "bone":
        if not tem_ancoras:
            raise erro_spec(
                "export-r15: rota nao-blocky em modo_rig=bone exige rig.ancoras ou partes[] com ancora"
            )
    else:
        if not partes_man or not tem_ancoras:
            raise erro_spec(
                "export-r15: rota nao-blocky exige manifesto segmentado com partes[] e rig.ancoras"
            )
        faltantes = [
            n for n, *_ in blocky.OSSOS_R15 if n != "HumanoidRootPart" and n not in partes_man
        ]
        if faltantes:
            raise erro_spec(
                "export-r15: manifesto segmentado incompleto para modo_rig=motor6d "
                f"(faltam {len(faltantes)} partes R15: {', '.join(faltantes)})"
            )

    item_id = str(item.get("id") or manifesto_eff.get("asset_id") or "").strip()
    ossos: list[dict] = []
    partes: dict[str, dict] = {}
    for nome, pai, cab, _cauda in blocky.OSSOS_R15:
        # cabeca=None instrui _bone_tree_xml a usar partes[nome]["centro"] (studs Y-up reais do rig)
        ossos.append({"nome": nome, "pai": pai, "cabeca": None})
        if nome == "HumanoidRootPart":
            continue
        p_man = partes_man.get(nome) or {}
        junta = JOINT_R15.get(nome, nome)
        raw_ancora = (
            p_man.get("ancora")
            or rig_ancoras.get(nome)
            or rig_ancoras.get(junta)
        )
        if isinstance(raw_ancora, (list, tuple)) and len(raw_ancora) == 3:
            centro = (float(raw_ancora[0]), float(raw_ancora[1]), float(raw_ancora[2]))
        else:
            centro = _roblox(cab, mps)
        raw_bbox = p_man.get("bbox")
        if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 3:
            tamanho = (
                max(0.05, float(raw_bbox[0])),
                max(0.05, float(raw_bbox[1])),
                max(0.05, float(raw_bbox[2])),
            )
        else:
            tamanho = (1.0, 1.0, 1.0)
        arquivo_parte = str(p_man.get("arquivo") or f"{nome}.glb")
        mesh_uri = _resolver_parte_mesh_uri(
            nome=nome,
            mesh_arquivo=arquivo_parte,
            item_id=item_id,
            asset_ids=asset_ids,
            ledger=ledger,
        )
        partes[nome] = {
            "centro": centro,
            "tamanho": tamanho,
            "cor": 0x7D858F,
            "mesh_id": mesh_uri,
            "arquivo": arquivo_parte,
        }

    lt = partes.get("LowerTorso")
    raw_hrp = rig_ancoras.get("HumanoidRootPart") or rig_ancoras.get("Root")
    if isinstance(raw_hrp, (list, tuple)) and len(raw_hrp) == 3:
        hrp_centro = (float(raw_hrp[0]), float(raw_hrp[1]), float(raw_hrp[2]))
    elif lt is not None:
        hrp_centro = lt["centro"]
    else:
        hrp_centro = (0.0, 2.5, 0.0)
    if lt is not None:
        lt_tam = lt["tamanho"]
        hrp_tam = (min(lt_tam[0], 2.0), lt_tam[1], min(lt_tam[2], 1.0))
    else:
        hrp_tam = (1.5, 1.0, 1.0)
    partes["HumanoidRootPart"] = {
        "centro": hrp_centro,
        "tamanho": hrp_tam,
        "cor": 0x7D858F,
    }
    return ossos, partes


def _montar_motores_e_attachments(
    ossos: list[dict],
    partes: Mapping[str, dict],
    mps: float,
    sockets_r15: Mapping[str, dict[str, Any]] | None,
    *,
    eh_blocky: bool,
) -> tuple[list[dict], dict[str, str], dict[str, list[list[str]]], int, int]:
    """Constroi os 15 ``Motor6D``, ``RigAttachment``s, anexos padrao e ``refs`` deterministicos."""
    motores: list[dict] = []
    for osso in ossos:
        pai = osso.get("pai")
        if not pai:
            continue
        nome = osso["nome"]
        if eh_blocky:
            p0 = partes[pai]["centro_m"]
            p1 = partes[nome]["centro_m"]
            joint = osso["cabeca"]
            c0 = _roblox([joint[i] - p0[i] for i in range(3)], mps)
            c1 = _roblox([joint[i] - p1[i] for i in range(3)], mps)
        else:
            p0_s = partes[pai]["centro"]
            p1_s = partes[nome]["centro"]
            joint_s = partes[nome]["centro"]
            c0 = (joint_s[0] - p0_s[0], joint_s[1] - p0_s[1], joint_s[2] - p0_s[2])
            c1 = (joint_s[0] - p1_s[0], joint_s[1] - p1_s[1], joint_s[2] - p1_s[2])

        nome_motor = JOINT_R15.get(nome, f"{pai}_{nome}")
        c0_rot = osso.get("c0_rot")
        c1_rot = osso.get("c1_rot")
        if sockets_r15:
            # Motor6D so aceita socket direcionado explicitamente ao nome da junta (nunca por osso/parte filha).
            s_entry = sockets_r15.get(nome_motor)
            if isinstance(s_entry, Mapping):
                s_nome = str(s_entry.get("nome") or s_entry.get("id") or "").strip()
                if s_nome and s_nome != nome_motor:
                    s_entry = None
            if isinstance(s_entry, Mapping):
                if c0_rot is None:
                    c0_rot = (
                        s_entry.get("rotacao_quat_wxyz")
                        or s_entry.get("rot_mat")
                        or s_entry.get("c0_rot")
                    )
                if c1_rot is None:
                    c1_rot = s_entry.get("c1_rot")
                s_pos_studs = _socket_pos_studs(s_entry, mps)
                if s_pos_studs is not None:
                    c0 = (
                        c0[0] + s_pos_studs[0],
                        c0[1] + s_pos_studs[1],
                        c0[2] + s_pos_studs[2],
                    )
        motores.append(
            {
                "nome": nome_motor,
                "parte0": pai,
                "parte1": nome,
                "c0": c0,
                "c1": c1,
                "c0_rot": c0_rot,
                "c1_rot": c1_rot,
            }
        )

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
        for parte_nome, pos, rot_m in (
            (motor["parte0"], motor["c0"], motor.get("c0_rot")),
            (motor["parte1"], motor["c1"], motor.get("c1_rot")),
        ):
            att_ref = f"RBX{prox_ref}"
            prox_ref += 1
            total_attachments += 1
            attachments_por_parte.setdefault(parte_nome, []).append(
                _attachment_xml(att_nome, att_ref, pos, rot_mat=rot_m)
            )

    anexos_padrao = (
        ("Head", "HatAttachment", lambda tam: (0.0, tam[1] / 2.0, 0.0)),
        ("Head", "HairAttachment", lambda tam: (0.0, tam[1] / 2.0, 0.0)),
        ("UpperTorso", "BodyBackAttachment", lambda tam: (0.0, 0.0, tam[2] / 2.0)),
        ("UpperTorso", "BodyFrontAttachment", lambda tam: (0.0, 0.0, -tam[2] / 2.0)),
        ("UpperTorso", "LeftCollarAttachment", lambda tam: (-tam[0] / 2.0, tam[1] / 2.0, 0.0)),
        ("UpperTorso", "RightCollarAttachment", lambda tam: (tam[0] / 2.0, tam[1] / 2.0, 0.0)),
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
        pos_padrao = pos_fn(partes[parte_nome]["tamanho"])
        off_pos, off_rot = _resolver_socket_offset(sockets_r15, att_nome, mps)
        if off_pos is not None:
            pos_padrao = (
                pos_padrao[0] + off_pos[0],
                pos_padrao[1] + off_pos[1],
                pos_padrao[2] + off_pos[2],
            )
        attachments_por_parte.setdefault(parte_nome, []).append(
            _attachment_xml(att_nome, att_ref, pos_padrao, rot_mat=off_rot)
        )
    return motores, refs, attachments_por_parte, total_attachments, prox_ref
