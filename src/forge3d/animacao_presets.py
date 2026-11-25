"""Presets deterministicos de microvariacao postural por ``seed`` ou ``postura_preset``."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

PRESETS_POSTURA: tuple[str, ...] = (
    "neutro_relaxado",
    "guarda_atento",
    "descontraido",
    "confiante",
    "explorador",
)

# (angulo_braco_delta_e, angulo_braco_delta_d, cotovelo_flex_e, cotovelo_flex_d,
#  tronco_pitch, cabeca_yaw, cabeca_pitch, fase_idle)
_PERFIS_POSTURA: dict[str, tuple[float, float, float, float, float, float, float, float]] = {
    "neutro_relaxado": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    "guarda_atento": (2.5, 1.5, 5.0, 4.0, -2.5, -3.5, 2.0, 0.08),
    "descontraido": (-1.5, 2.0, 2.0, 5.5, 1.8, 4.0, -1.5, 0.16),
    "confiante": (-2.0, -2.0, 3.5, 3.5, 2.8, 2.5, 2.5, 0.24),
    "explorador": (1.8, -1.8, 4.5, 2.5, -1.5, -4.5, -2.0, 0.32),
}


def _jitter_unitario(digest: bytes, idx: int) -> float:
    return (digest[idx] / 127.5) - 1.0


def resolver_preset_postura(
    seed: int | None = None,
    postura_preset: str | None = None,
) -> dict[str, Any]:
    """Resolve preset deterministico e offsets sutis de postura para tronco, cabeca e bracos."""
    nome_norm = str(postura_preset or "").strip().lower()
    if nome_norm in _PERFIS_POSTURA:
        preset = nome_norm
    elif seed is not None:
        digest = hashlib.sha256(f"forge3d-postura:{int(seed)}".encode("utf-8")).digest()
        preset = PRESETS_POSTURA[digest[0] % len(PRESETS_POSTURA)]
    else:
        preset = "neutro_relaxado"

    b_e, b_d, c_e, c_d, t_p, h_y, h_p, fase = _PERFIS_POSTURA[preset]

    if seed is not None:
        digest = hashlib.sha256(f"forge3d-postura:{int(seed)}".encode("utf-8")).digest()
        b_e += 1.4 * _jitter_unitario(digest, 1)
        b_d += 1.4 * _jitter_unitario(digest, 2)
        c_e += 2.2 * _jitter_unitario(digest, 3)
        c_d += 2.2 * _jitter_unitario(digest, 4)
        t_p += 1.2 * _jitter_unitario(digest, 5)
        h_y += 2.6 * _jitter_unitario(digest, 6)
        h_p += 1.2 * _jitter_unitario(digest, 7)
        fase = (fase + 0.25 * (digest[8] / 255.0)) % 1.0

    return {
        "preset": preset,
        "angulo_braco_delta_e": round(b_e, 4),
        "angulo_braco_delta_d": round(b_d, 4),
        "cotovelo_flex_e": round(max(-4.0, c_e), 4),
        "cotovelo_flex_d": round(max(-4.0, c_d), 4),
        "tronco_pitch": round(t_p, 4),
        "cabeca_yaw": round(h_y, 4),
        "cabeca_pitch": round(h_p, 4),
        "fase_idle": round(fase % 1.0, 4),
    }


def _normalizar_motor_harmonico(
    entrada: tuple,
) -> tuple[str, float, float, str, float, float, float, float]:
    if len(entrada) == 4:
        sem, amp, defas, eixo = entrada
        return (str(sem), float(amp), float(defas), str(eixo), 1.0, 0.0, 0.0, 0.0)
    if len(entrada) == 6:
        sem, amp, defas, eixo, cyc, off = entrada
        return (str(sem), float(amp), float(defas), str(eixo), float(cyc), float(off), 0.0, 0.0)
    sem, amp, defas, eixo, cyc, off, amp_h2, ph_h2 = entrada
    return (
        str(sem),
        float(amp),
        float(defas),
        str(eixo),
        float(cyc),
        float(off),
        float(amp_h2),
        float(ph_h2),
    )


def _empacotar_motor_harmonico(
    sem: str,
    amp: float,
    defas: float,
    eixo: str,
    cyc: float,
    off: float,
    amp_h2: float,
    ph_h2: float,
) -> tuple:
    if amp_h2 != 0.0:
        return (sem, amp, defas, eixo, cyc, off, amp_h2, ph_h2)
    return (sem, amp, defas, eixo, cyc, off)


def aplicar_preset_motores(
    nome_clipe: str,
    motores: tuple,
    preset_info: Mapping[str, Any] | None,
) -> tuple:
    """Aplica microvariacao de postura a ``idle`` (e sutil em ``walk``/``run``) sem tocar ``quadril``."""
    if not isinstance(preset_info, Mapping):
        return motores

    nome = str(nome_clipe or "").strip().lower()
    if nome not in ("idle", "walk", "run"):
        return motores

    b_e = float(preset_info.get("angulo_braco_delta_e", 0.0))
    b_d = float(preset_info.get("angulo_braco_delta_d", 0.0))
    c_e = float(preset_info.get("cotovelo_flex_e", 0.0))
    c_d = float(preset_info.get("cotovelo_flex_d", 0.0))
    t_p = float(preset_info.get("tronco_pitch", 0.0))
    h_y = float(preset_info.get("cabeca_yaw", 0.0))
    h_p = float(preset_info.get("cabeca_pitch", 0.0))
    fase = float(preset_info.get("fase_idle", 0.0)) % 1.0

    if all(abs(v) < 1e-6 for v in (b_e, b_d, c_e, c_d, t_p, h_y, h_p, fase)):
        return motores

    saida: list[tuple] = []
    if nome == "idle":
        offsets_x = {
            "tronco": t_p,
            "cabeca": h_p,
            "braco_e": b_e,
            "braco_d": b_d,
            "antebraco_e": c_e,
            "antebraco_d": c_d,
        }
        tem_cabeca_y = False
        for entrada in motores:
            if len(entrada) == 3:
                saida.append(entrada)
                continue
            sem, amp, defas, eixo, cyc, off, amp_h2, ph_h2 = _normalizar_motor_harmonico(entrada)
            # Nunca altera quadril (preserva zero Z-roll e paridade LowerTorso/Hips)
            if sem != "quadril":
                defas = (defas + fase) % 1.0
                if eixo == "X" and sem in offsets_x:
                    off = off + offsets_x[sem]
                    if sem.startswith("antebraco"):
                        off = max(2.5, off)
                if sem == "cabeca" and eixo == "Y":
                    off = off + h_y
                    tem_cabeca_y = True
            saida.append(_empacotar_motor_harmonico(sem, amp, defas, eixo, cyc, off, amp_h2, ph_h2))
        if not tem_cabeca_y and abs(h_y) >= 1e-4:
            saida.append(("cabeca", 0.9, fase, "Y", 1.0, h_y))
        return tuple(saida)

    # Locomocao (walk / run): ajuste sutil em braco/cotovelo mantendo joelho<=0, cotovelo>=0 e loop
    offsets_loc = {
        "braco_e": 0.45 * b_e,
        "braco_d": 0.45 * b_d,
        "antebraco_e": 0.45 * c_e,
        "antebraco_d": 0.45 * c_d,
    }
    if all(abs(v) < 1e-6 for v in offsets_loc.values()):
        return motores
    for entrada in motores:
        if len(entrada) == 3:
            saida.append(entrada)
            continue
        sem, amp, defas, eixo, cyc, off, amp_h2, ph_h2 = _normalizar_motor_harmonico(entrada)
        if eixo == "X" and sem in offsets_loc:
            off = off + offsets_loc[sem]
            if sem.startswith("antebraco"):
                off = max(2.0, off)
        saida.append(_empacotar_motor_harmonico(sem, amp, defas, eixo, cyc, off, amp_h2, ph_h2))
    return tuple(saida)
