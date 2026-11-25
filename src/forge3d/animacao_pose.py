"""Calibracao de pose natural (aducao de bracos e escala/clamp de deslocamento) para Roblox R15."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def peso_gravidade_clipe(nome_clipe: str, fracao: float) -> float:
    """Peso temporal [0..1] do caimento gravitacional conforme dinamica do clipe."""
    f = max(0.0, min(1.0, float(fracao)))
    nome = str(nome_clipe or "").strip().lower()
    if nome in ("idle", "walk", "run", "hit"):
        return 1.0
    if nome == "death":
        return 0.8
    if nome in ("ride_idle", "ride_fly"):
        return 0.4
    if nome == "jump":
        return 0.2 + 0.8 * (math.cos(math.pi * f) ** 2)
    if nome in ("attack", "slash_combo", "block", "cast"):
        return 1.0 - 0.35 * math.sin(math.pi * f)
    return 1.0


def _pt3(ancoras: Mapping[str, Sequence[float]], chave: str) -> tuple[float, float, float] | None:
    val = ancoras.get(chave)
    if isinstance(val, (list, tuple)) and len(val) == 3:
        return (float(val[0]), float(val[1]), float(val[2]))
    return None


def calcular_aducao_braco_ancoras(ancoras: Mapping[str, Sequence[float]] | None) -> float:
    """Calcula graus de aducao gravitacional para ``LeftUpperArm``/``RightUpperArm`` via ``rig.ancoras`` Y-up."""
    if not isinstance(ancoras, Mapping) or not ancoras:
        return 0.0

    angulos: list[float] = []
    thetas_low: list[float] = []
    sh_xs: list[float] = []
    for sh_nome, el_nome, hd_nome in (
        ("LeftUpperArm", "LeftLowerArm", "LeftHand"),
        ("RightUpperArm", "RightLowerArm", "RightHand"),
    ):
        sh = _pt3(ancoras, sh_nome)
        el = _pt3(ancoras, el_nome)
        if sh is None or el is None:
            continue
        hd = _pt3(ancoras, hd_nome)
        fim = hd if hd is not None else el
        sh_xs.append(abs(sh[0]))
        dx = abs(fim[0] - sh[0])
        dy = max(sh[1] - fim[1], 1e-4)
        angulos.append(math.degrees(math.atan2(dx, dy)))
        if hd is not None:
            thetas_low.append(math.degrees(math.atan2(abs(hd[0] - el[0]), max(el[1] - hd[1], 1e-4))))

    if not angulos:
        return 0.0
    theta_arm_total = sum(angulos) / len(angulos)
    tem_lower = bool(thetas_low)
    theta_lower = (sum(thetas_low) / len(thetas_low)) if thetas_low else 0.0
    if theta_arm_total <= 22.0 or (tem_lower and theta_lower <= 14.0 and theta_arm_total <= 28.0):
        return 0.0

    sh_half = (sum(sh_xs) / len(sh_xs)) if sh_xs else 0.7
    leg_xs = [
        abs(p[0])
        for nome_leg in ("LeftUpperLeg", "RightUpperLeg")
        if (p := _pt3(ancoras, nome_leg)) is not None
    ]
    hip_half = (sum(leg_xs) / len(leg_xs)) if leg_xs else (0.5 * sh_half)
    hip_ratio = hip_half / max(sh_half, 1e-4)
    t_prop = max(0.0, min(1.0, (hip_ratio - 0.45) / 0.35))
    target_deg = 13.0 + 4.0 * t_prop
    return min(26.0, max(0.0, theta_arm_total - target_deg))


def aducao_base_marcha(nome_clipe: str) -> float:
    """Retorna aducao base (graus) das coxas em marcha humana (walk/run)."""
    nome = str(nome_clipe or "").strip().lower()
    if nome == "walk":
        return 4.5
    if nome == "run":
        return 6.0
    return 0.0


def calcular_aducao_perna_ancoras(ancoras: Mapping[str, Sequence[float]] | None) -> float:
    """Calcula aducao extra (graus) de UpperLeg.L/R proporcional a ``hip_dx / altura`` via ancoras Y-up."""
    if not isinstance(ancoras, Mapping) or not ancoras:
        return 0.0

    ul = _pt3(ancoras, "LeftUpperLeg") or _pt3(ancoras, "UpperLeg.L")
    ur = _pt3(ancoras, "RightUpperLeg") or _pt3(ancoras, "UpperLeg.R")
    fl = _pt3(ancoras, "LeftFoot") or _pt3(ancoras, "Foot.L")
    fr = _pt3(ancoras, "RightFoot") or _pt3(ancoras, "Foot.R")
    if ul is None or ur is None or fl is None or fr is None:
        return 0.0

    hip_dx = abs(ul[0] - ur[0])
    foot_dx = abs(fl[0] - fr[0])
    leg_len = 0.5 * (max(ul[1] - fl[1], 1e-4) + max(ur[1] - fr[1], 1e-4))
    y_foot = 0.5 * (fl[1] + fr[1])

    head = _pt3(ancoras, "Head")
    if head is not None:
        h_est = max((head[1] - y_foot) / 0.79, 1e-4)
    elif (neck := _pt3(ancoras, "Neck")) is not None:
        h_est = max((neck[1] - y_foot) / 0.72, 1e-4)
    else:
        ys = [
            float(v[1])
            for v in ancoras.values()
            if isinstance(v, (list, tuple)) and len(v) == 3
        ]
        h_est = max(((max(ys) - min(ys)) / 0.88) if ys else 1.75, 1e-4)

    hip_ratio = hip_dx / h_est
    foot_ratio = foot_dx / h_est
    if hip_ratio <= 0.15 and foot_ratio <= 0.16:
        return 0.0

    alvo_ratio = max(0.090, min(0.145, 0.090 + 0.35 * max(0.0, hip_ratio - 0.20)))
    foot_dx_alvo = alvo_ratio * h_est
    if foot_dx <= foot_dx_alvo + 1e-4:
        return 0.0

    sin_tot = max(0.0, min(0.85, (foot_dx - foot_dx_alvo) / max(2.0 * leg_len, 1e-4)))
    theta_tot = math.degrees(math.asin(sin_tot))
    return round(max(0.0, min(10.0, theta_tot - 4.5)), 4)


def escala_deslocamento_ancoras(
    ancoras: Mapping[str, Sequence[float]] | None,
    mps: float = 0.28,
) -> tuple[float, float]:
    """Retorna ``(fator_altura, min_y_quadril_studs)`` a partir de ``rig.ancoras`` em studs Y-up."""
    mps_eff = float(mps) if mps and mps > 0 else 0.28
    if not isinstance(ancoras, Mapping) or not ancoras:
        return (1.0, -1e9)

    ys = [
        float(v[1])
        for v in ancoras.values()
        if isinstance(v, (list, tuple)) and len(v) == 3
    ]
    if not ys:
        return (1.0, -1e9)

    foot_ys = [
        p[1]
        for k in ("LeftFoot", "RightFoot", "LeftAnkle", "RightAnkle")
        if (p := _pt3(ancoras, k)) is not None
    ]
    y_min = min(foot_ys) if foot_ys else min(ys)
    head = _pt3(ancoras, "Head") or _pt3(ancoras, "Neck")
    y_head = head[1] if head is not None else max(ys)
    span_y = y_head - y_min
    if span_y <= 0.1:
        fator_altura = 1.0
    else:
        fator_altura = max(0.5, min(3.0, (span_y * mps_eff) / 1.35))

    lt = _pt3(ancoras, "LowerTorso") or _pt3(ancoras, "Root")
    if lt is None:
        return (fator_altura, -1e9)

    y_floor = y_min - 0.22 * fator_altura
    clearance = 0.55 * fator_altura
    min_y_quadril_studs = -max(0.2, (lt[1] - y_floor) - clearance)
    return (fator_altura, min_y_quadril_studs)
