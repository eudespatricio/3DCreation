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
