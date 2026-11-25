"""Gate QC G14: validacao de KeyframeSequence, arvore aninhada de Pose e amplitude."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from . import animacao, profiles, rbx_anim

LIMIAR_AMPLITUDE_G14_GRAUS = 5.0


def _rot_pose_mat3(pose_el: ElementTree.Element) -> tuple[float, ...]:
    cf = pose_el.find("Properties/CoordinateFrame[@name='CFrame']")
    if cf is None:
        return (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    for tag_pos in ("X", "Y", "Z"):
        txt_pos = cf.findtext(tag_pos)
        if txt_pos is not None:
            v_pos = float(txt_pos)
            if not math.isfinite(v_pos):
                raise ValueError(f"CFrame {tag_pos} nao finito: {txt_pos!r}")
    vals = []
    for tag, default in (
        ("R00", 1.0), ("R01", 0.0), ("R02", 0.0),
        ("R10", 0.0), ("R11", 1.0), ("R12", 0.0),
        ("R20", 0.0), ("R21", 0.0), ("R22", 1.0),
    ):
        txt = cf.findtext(tag)
        val = float(txt) if txt is not None else default
        if not math.isfinite(val):
            raise ValueError(f"CFrame {tag} nao finito: {txt!r}")
        vals.append(val)
    return tuple(vals)


def _ang_mat3_deg(m: tuple[float, ...]) -> float:
    tr = m[0] + m[4] + m[8]
    return math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1.0) * 0.5))))


def _ang_pair_deg(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    tr = (
        a[0] * b[0] + a[3] * b[3] + a[6] * b[6]
        + a[1] * b[1] + a[4] * b[4] + a[7] * b[7]
        + a[2] * b[2] + a[5] * b[5] + a[8] * b[8]
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1.0) * 0.5))))


def _inspecionar_keyframe_sequence(seq: ElementTree.Element) -> dict[str, Any]:
    nome = seq.findtext("Properties/string[@name='Name']") or ""
    loop_el = seq.find("Properties/bool[@name='Loop']")
    loop = True if loop_el is None else (loop_el.text or "").strip().lower() == "true"
    kfs = seq.findall("Item[@class='Keyframe']")
    pose_aninhada = len(kfs) >= 1
    mats_por_osso: dict[str, list[tuple[float, ...]]] = {}
    max_amp = 0.0

    def _visitar(el: ElementTree.Element) -> int:
        filhos = el.findall("Item[@class='Pose']")
        total_filhos = 0
        for fl in filhos:
            pname = fl.findtext("Properties/string[@name='Name']") or ""
            w_sub = fl.findtext("Properties/float[@name='Weight']")
            if w_sub is not None and not math.isfinite(float(w_sub)):
                raise ValueError(f"Weight nao finito em Pose {pname!r}: {w_sub!r}")
            mat = _rot_pose_mat3(fl)
            mats_por_osso.setdefault(pname, []).append(mat)
            total_filhos += 1 + _visitar(fl)
        return total_filhos

    for kf in kfs:
        raizes = kf.findall("Item[@class='Pose']")
        if len(raizes) != 1:
            pose_aninhada = False
            continue
        hrp = raizes[0]
        rname = hrp.findtext("Properties/string[@name='Name']") or ""
        w_txt = hrp.findtext("Properties/float[@name='Weight']")
        peso_raiz = float(w_txt) if w_txt is not None else 0.0
        _rot_pose_mat3(hrp)
        n_sub = _visitar(hrp)
        if (
            rname != "HumanoidRootPart"
            or not math.isfinite(peso_raiz)
            or abs(peso_raiz) > 1e-5
            or n_sub == 0
        ):
            pose_aninhada = False

    for mats in mats_por_osso.values():
        for m in mats:
            max_amp = max(max_amp, _ang_mat3_deg(m))
        for i in range(len(mats)):
            for j in range(i + 1, len(mats)):
                max_amp = max(max_amp, _ang_pair_deg(mats[i], mats[j]))

    return {
        "nome": nome,
        "loop": loop,
        "keyframes": len(kfs),
        "pose_aninhada": pose_aninhada,
        "amplitude_max_graus": round(max_amp, 3),
    }


def _validar_sinais_sequencia(
    seq: ElementTree.Element,
    nome_clipe: str,
    modo_rig: str,
) -> list[str]:
    """Valida invariantes de sinal Z em ``walk``/``run``/``attack`` para ``motor6d``."""
    if modo_rig != "motor6d":
        return []
    nome_low = nome_clipe.strip().lower()
    if nome_low not in ("walk", "run", "attack"):
        return []

    mats_por_osso: dict[str, list[tuple[float, ...]]] = {}
    for kf in seq.findall("Item[@class='Keyframe']"):
        for pose in kf.iter("Item"):
            if pose.get("class") == "Pose":
                pname = pose.findtext("Properties/string[@name='Name']") or ""
                if pname:
                    mats_por_osso.setdefault(pname, []).append(_rot_pose_mat3(pose))

    erros: list[str] = []
    if nome_low in ("walk", "run"):
        rolls_leg: dict[str, list[float]] = {}
        for leg in ("LeftUpperLeg", "RightUpperLeg"):
            if leg in mats_por_osso and len(mats_por_osso[leg]) >= 2:
                rolls_leg[leg] = [math.degrees(math.atan2(-m[1], m[0])) for m in mats_por_osso[leg]]
        if "LeftUpperLeg" in rolls_leg:
            m_l = sum(rolls_leg["LeftUpperLeg"]) / len(rolls_leg["LeftUpperLeg"])
            if abs(m_l) > 1.0 and m_l < 0.0:
                erros.append(f"sinal_z_invertido:{nome_low}:LeftUpperLeg")
        if "RightUpperLeg" in rolls_leg:
            m_r = sum(rolls_leg["RightUpperLeg"]) / len(rolls_leg["RightUpperLeg"])
            if abs(m_r) > 1.0 and m_r > 0.0:
                erros.append(f"sinal_z_invertido:{nome_low}:RightUpperLeg")
        for leg, foot in (("LeftUpperLeg", "LeftFoot"), ("RightUpperLeg", "RightFoot")):
            if leg in rolls_leg and foot in mats_por_osso and len(mats_por_osso[foot]) == len(rolls_leg[leg]):
                rolls_f = [math.degrees(math.atan2(m[3], m[0])) for m in mats_por_osso[foot]]
                m_leg = sum(rolls_leg[leg]) / len(rolls_leg[leg])
                m_foot = sum(rolls_f) / len(rolls_f)
                if abs(m_leg) > 1.0 and abs(m_leg + m_foot) > 2.5:
                    erros.append(f"sinal_z_invertido:{nome_low}:{foot}")
    elif nome_low == "attack" and "RightUpperArm" in mats_por_osso:
        zs = [math.degrees(math.atan2(m[3], m[0])) for m in mats_por_osso["RightUpperArm"]]
        if len(zs) >= 5 and (max(zs) - min(zs)) > 5.0:
            idx_w = int(round(0.25 * (len(zs) - 1)))
            idx_s = int(round(0.50 * (len(zs) - 1)))
            if not (zs[idx_w] > 0.0 and zs[idx_s] < 0.0):
                erros.append(f"sinal_z_invertido:{nome_low}:RightUpperArm")
    return erros


def verificar_g14_animacao_roblox(
    item: dict,
    perfil: dict,
    pasta: Path,
    arquivos: list[dict],
    play_report: Mapping[str, Any] | None = None,
    *,
    ancoras: Mapping[str, Any] | None = None,
) -> dict:
    """Gate G14: KeyframeSequence com arvore Pose aninhada, Loop=true e amplitude >= 5 deg."""
    anim_arqs = [
        a
        for a in arquivos
        if a.get("papel") == "animacao"
        and str(a.get("caminho") or "").lower().endswith((".rbxmx", ".rbxlx"))
    ]
    modo_rig = str((item.get("rig") or {}).get("modo") or "")
    modo_eff = "bone" if modo_rig in ("bone", "skinned") else "motor6d"
    anim_specs = [a for a in (item.get("animacoes") or []) if isinstance(a, dict)]
    pedidos_anim = list(
        dict.fromkeys(
            [
                *(str(a) for a in (item.get("animacoes_base") or []) if a),
                *(str(a) for a in (item.get("clipes") or []) if a),
                *(str(a["nome"]) for a in anim_specs if a.get("nome")),
            ]
        )
    )
    tem_alvo_motor6d = any(str(a.get("alvo") or "") == "motor6d" for a in anim_specs)
    aplicavel = (
        bool(anim_arqs)
        or tem_alvo_motor6d
        or (modo_rig == "motor6d" and bool(pedidos_anim))
    )
    if not aplicavel:
        return {"id": "G14", "status": "ok", "medido": {"aplicavel": False}}

    clipes_medidos: list[dict[str, Any]] = []
    problemas: list[str] = []

    for arq in anim_arqs:
        caminho = pasta / str(arq.get("caminho") or "")
        if not caminho.is_file():
            problemas.append(f"animacao_ausente:{arq.get('caminho')}")
            continue
        try:
            raiz = ElementTree.fromstring(caminho.read_text(encoding="utf-8"))
        except (OSError, ElementTree.ParseError, ValueError) as exc:
            problemas.append(f"animacao_xml_invalido:{arq.get('caminho')}:{exc}")
            continue
        seqs = [el for el in raiz.iter("Item") if el.get("class") == "KeyframeSequence"]
        if not seqs:
            problemas.append(f"sem_keyframe_sequence:{arq.get('caminho')}")
            continue
        for seq in seqs:
            try:
                info_seq = _inspecionar_keyframe_sequence(seq)
            except (TypeError, ValueError) as exc:
                problemas.append(f"animacao_xml_invalido:{arq.get('caminho')}:{exc}")
                continue
            info_seq["fonte"] = str(arq.get("caminho"))
            clipes_medidos.append(info_seq)
            if not info_seq["pose_aninhada"]:
                problemas.append(f"arvore_pose_invalida:{info_seq['nome'] or arq.get('caminho')}")
            problemas.extend(_validar_sinais_sequencia(seq, str(info_seq["nome"]), modo_eff))

    if pedidos_anim and not anim_arqs:
        esq = profiles.esqueleto_para_item(perfil, item)
        mps = float((perfil.get("unidades") or {}).get("metros_por_stud", 0.28))
        clipes_gerados = animacao.clipes(perfil, esq, pedidos_anim)
        for idx, clipe in enumerate(clipes_gerados, start=1):
            linhas, _ = rbx_anim._sequencia_xml(
                clipe, idx * 100, mps=mps, ancoras=ancoras, modo_rig=modo_eff
            )
            seq_el = ElementTree.fromstring("\n".join(linhas))
            info_seq = _inspecionar_keyframe_sequence(seq_el)
            info_seq["fonte"] = f"gerado_{modo_eff}"
            clipes_medidos.append(info_seq)
            problemas.extend(_validar_sinais_sequencia(seq_el, str(info_seq["nome"]), modo_eff))

    validos = [
        c
        for c in clipes_medidos
        if c["pose_aninhada"]
        and c["keyframes"] >= 2
        and c["loop"]
        and c["amplitude_max_graus"] >= LIMIAR_AMPLITUDE_G14_GRAUS
    ]
    if not validos:
        problemas.append("nenhum_clipe_loop_com_amplitude_minima")

    play_studio = (
        dict(play_report)
        if play_report
        else {"status": "skip", "motivo": "studio_mcp_nao_executado"}
    )
    if play_studio.get("status") == "falhou":
        problemas.append(f"play_studio_falhou:{play_studio.get('motivo') or 'sem_movimento'}")

    amp_max = max((c["amplitude_max_graus"] for c in clipes_medidos), default=0.0)
    ok = (not problemas) and bool(validos)
    return {
        "id": "G14",
        "status": "ok" if ok else "falhou",
        "medido": {
            "aplicavel": True,
            "clipes": clipes_medidos,
            "amplitude_max_graus": amp_max,
            "pose_aninhada": (
                all(c["pose_aninhada"] for c in clipes_medidos) if clipes_medidos else False
            ),
            "play_studio": play_studio,
            **({"problemas": problemas} if problemas else {}),
        },
        "limite": {
            "amplitude_min_graus": LIMIAR_AMPLITUDE_G14_GRAUS,
            "loop": True,
            "keyframes_min": 2,
        },
        **({} if ok else {"codigo": "FORGE-E-QC"}),
    }
