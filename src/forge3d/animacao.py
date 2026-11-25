"""Clipes base procedurais V2 (D66/D69 + Biomecanica C1 24fps): fachada e sintetizador.

Os clipes nascem em espaco semantico e cada perfil resolve o nome real do osso em
``rig.retarget``. Sintetiza curvas C1 continuas densas a 24 fps (``16..32`` chaves por clipe),
sem descontinuidade em V no quadril e com contra-rotacao de coluna/pescoco/cabeca,
seguimento de fase em bracos/cotovelos e asas, alem de suporte nativo a ``ride_idle``,
``ride_fly`` e esqueletos ``quadruped@1`` / ``winged_mount@1``.
"""

from __future__ import annotations

import math

from . import profiles
from .animacao_motores import (
    CLIPES_SUPORTADOS, FPS, FRACOES, FRACOES_CICLO,
    MOTORES_ATTACK, MOTORES_BLOCK, MOTORES_CAST, MOTORES_DEATH, MOTORES_HIT,
    MOTORES_IDLE, MOTORES_JUMP, MOTORES_RIDE_FLY, MOTORES_RIDE_IDLE,
    MOTORES_RUN, MOTORES_SLASH_COMBO, MOTORES_WALK,
    SEGUNDOS_ATTACK, SEGUNDOS_BITE, SEGUNDOS_BLOCK, SEGUNDOS_CAST, SEGUNDOS_DEATH,
    SEGUNDOS_GALLOP, SEGUNDOS_GLIDE, SEGUNDOS_HIT, SEGUNDOS_IDLE, SEGUNDOS_JUMP,
    SEGUNDOS_RIDE_FLY, SEGUNDOS_RIDE_IDLE, SEGUNDOS_ROAR, SEGUNDOS_RUN,
    SEGUNDOS_SLASH_COMBO, SEGUNDOS_WALK, SEGUNDOS_WING_FLAP,
    _CAPA_BALISTICA, _CAPA_HARMONICA, _CHAVES_DEDOS_CASCATA,
    _CLIPES_EXCLUSIVOS_CRIATURA, _CLIPES_GRIP_MAO_ARMA, _DEFINICOES_CRIATURA,
    _DEFINICOES_HUMANO, _DESLOCAMENTO_QUADRIL_Z, _DESLOCAMENTO_QUADRIL_Z_CRIATURA,
    _GRIP_ARMA_FALANGES, _GRIP_ARMA_POLEGAR, _MANDIBULA_BALISTICA, _NAO_LOOP_CLIPES,
)
from .animacao_presets import PRESETS_POSTURA, aplicar_preset_motores, resolver_preset_postura

__all__ = [
    "FPS", "CLIPES_SUPORTADOS", "FRACOES", "FRACOES_CICLO",
    "SEGUNDOS_IDLE", "SEGUNDOS_WALK", "SEGUNDOS_RUN", "SEGUNDOS_JUMP",
    "SEGUNDOS_ATTACK", "SEGUNDOS_SLASH_COMBO", "SEGUNDOS_CAST", "SEGUNDOS_BLOCK",
    "SEGUNDOS_HIT", "SEGUNDOS_DEATH", "SEGUNDOS_RIDE_IDLE", "SEGUNDOS_RIDE_FLY",
    "SEGUNDOS_GALLOP", "SEGUNDOS_WING_FLAP", "SEGUNDOS_GLIDE", "SEGUNDOS_BITE", "SEGUNDOS_ROAR",
    "MOTORES_IDLE", "MOTORES_WALK", "MOTORES_RUN", "MOTORES_RIDE_IDLE", "MOTORES_RIDE_FLY",
    "MOTORES_JUMP", "MOTORES_ATTACK", "MOTORES_SLASH_COMBO", "MOTORES_CAST",
    "MOTORES_BLOCK", "MOTORES_HIT", "MOTORES_DEATH",
    "PRESETS_POSTURA", "resolver_preset_postura", "amostrar_curva_c1", "clipes",
    "_DESLOCAMENTO_QUADRIL_Z", "_DESLOCAMENTO_QUADRIL_Z_CRIATURA", "_NAO_LOOP_CLIPES",
]


def amostrar_curva_c1(valores: tuple[float, ...] | list[float], fracao: float) -> float:
    """Avalia curva Catmull-Rom C1 continua sobre pontos de controle uniformes em [0, 1]."""
    pts = [float(v) for v in valores]
    n = len(pts)
    if n == 0:
        return 0.0
    if n == 1:
        return pts[0]
    u = max(0.0, min(1.0, float(fracao))) * float(n - 1)
    idx = min(n - 2, int(math.floor(u)))
    t = u - float(idx)
    p0, p1 = pts[max(0, idx - 1)], pts[idx]
    p2, p3 = pts[idx + 1], pts[min(n - 1, idx + 2)]
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2.0 * p1)
        + (-p0 + p2) * t
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
    )


def _fracoes_24fps(total_frames: int, n_segs: int) -> tuple[float, ...]:
    """Gera grade densa (16..32 chaves) alinhada aos frames inteiros a 24 fps."""
    if n_segs <= 0:
        return (0.0, 1.0)
    frames_unicos: list[int] = []
    for k in range(n_segs + 1):
        f = int(round(k * total_frames / float(n_segs)))
        if not frames_unicos or f > frames_unicos[-1]:
            frames_unicos.append(f)
    if frames_unicos[-1] != total_frames:
        frames_unicos.append(total_frames)
    return tuple(f / float(total_frames) for f in frames_unicos)


def _avaliar_motor_harmonico(entrada: tuple, fracao: float) -> tuple[str, str, float]:
    if len(entrada) == 4:
        semantico, amplitude, defasagem, eixo = entrada
        ciclos, offset, amp_h2, phase_h2 = 1.0, 0.0, 0.0, 0.0
    elif len(entrada) == 6:
        semantico, amplitude, defasagem, eixo, ciclos, offset = entrada
        amp_h2, phase_h2 = 0.0, 0.0
    else:
        semantico, amplitude, defasagem, eixo, ciclos, offset, amp_h2, phase_h2 = entrada
    graus = offset + amplitude * math.sin(2.0 * math.pi * (ciclos * fracao + defasagem))
    if amp_h2 != 0.0:
        graus += amp_h2 * math.sin(2.0 * math.pi * (2.0 * ciclos * fracao + phase_h2))
    return str(semantico), str(eixo), float(graus)


def _chaves_harmonicas(
    mapa: dict[str, str],
    motores: tuple,
    fracoes: tuple[float, ...],
    total_frames: int,
    bob_amp_z: float = 0.0,
    bob_offset_z: float = 0.0,
    lat_amp_x: float = 0.0,
    ciclos_bounce: float = 1.0,
) -> list[dict]:
    chaves = []
    for fracao in fracoes:
        poses = []
        quadril_desloc_aplicado = False
        for entrada in motores:
            semantico, eixo, graus = _avaliar_motor_harmonico(entrada, fracao)
            osso = mapa.get(semantico)
            if not osso:
                continue
            if semantico.startswith("canela"):
                graus = min(0.0, graus)
            elif semantico.startswith("antebraco"):
                graus = max(0.0, graus)
            pose: dict[str, object] = {"osso": osso, "graus": round(graus, 6), "eixo": eixo}
            if semantico == "quadril" and not quadril_desloc_aplicado and (
                bob_amp_z != 0.0 or bob_offset_z != 0.0 or lat_amp_x != 0.0
            ):
                # Curva C1 suave em cosseno duplo (zero descontinuidade em V em f=0, 0.5, 1.0)
                dx = lat_amp_x * math.sin(2.0 * math.pi * fracao)
                dz = bob_offset_z + bob_amp_z * 0.5 * (
                    1.0 - math.cos(4.0 * math.pi * ciclos_bounce * fracao)
                )
                pose["deslocamento_m"] = [round(dx, 6), 0.0, round(dz, 6)]
                quadril_desloc_aplicado = True
            poses.append(pose)
        chaves.append(
            {
                "frame": 1 + int(round(fracao * total_frames)),
                "segundos": round(fracao * total_frames / FPS, 4),
                "poses": poses,
            }
        )
    return chaves


def _chaves_balisticas(
    mapa: dict[str, str],
    motores: tuple,
    fracoes: tuple[float, ...],
    total_frames: int,
    bob_z: tuple[float, ...] | None = None,
) -> list[dict]:
    chaves = []
    for fracao in fracoes:
        poses = []
        quadril_desloc_aplicado = False
        for semantico, eixo, valores in motores:
            osso = mapa.get(semantico)
            if not osso:
                continue
            graus = amostrar_curva_c1(valores, fracao)
            if semantico.startswith("canela"):
                graus = min(0.0, graus)
            elif semantico.startswith("antebraco"):
                graus = max(0.0, graus)
            pose: dict[str, object] = {"osso": osso, "graus": round(graus, 6), "eixo": eixo}
            if semantico == "quadril" and bob_z is not None and not quadril_desloc_aplicado:
                dz = amostrar_curva_c1(bob_z, fracao)
                pose["deslocamento_m"] = [0.0, 0.0, round(dz, 6)]
                quadril_desloc_aplicado = True
            poses.append(pose)
        chaves.append(
            {
                "frame": 1 + int(round(fracao * total_frames)),
                "segundos": round(fracao * total_frames / FPS, 4),
                "poses": poses,
            }
        )
    return chaves


def _motores_secundarios_aa(
    mapa: dict[str, str],
    nome: str,
    modo: str,
    motores_base: tuple,
) -> tuple:
    """Sintetiza movimento secundario C1 para capa, mandibula e falanges quando no retarget."""
    presentes_base = {m[0] for m in motores_base}
    extras: list[tuple] = []

    if "capa" in mapa and "capa" not in presentes_base:
        if modo == "harmonica":
            amp, defas, cyc, off = _CAPA_HARMONICA.get(nome, (2.5, 0.25, 1.0, 4.0))
            extras.append(("capa", amp, defas, "X", cyc, off))
        else:
            vals = _CAPA_BALISTICA.get(nome, (0.0, 4.0, 10.0, 12.0, 8.0, 4.0, 2.0, 1.0, 0.0))
            extras.append(("capa", "X", vals))

    if "mandibula" in mapa and "mandibula" not in presentes_base:
        if modo == "harmonica":
            amp = -1.2 if nome in ("walk", "run", "ride_fly") else -0.8
            cyc = 2.0 if nome in ("walk", "run", "ride_fly") else 1.0
            extras.append(("mandibula", amp, 0.18, "X", cyc, amp))
        else:
            vals = _MANDIBULA_BALISTICA.get(nome, (0.0, -1.5, -4.0, -5.0, -3.5, -2.0, -1.0, -0.5, 0.0))
            extras.append(("mandibula", "X", vals))

    if "pescoco" in mapa and "pescoco" not in presentes_base:
        if modo == "harmonica":
            if nome in ("walk", "run", "ride_fly"):
                extras.append(("pescoco", 1.8 if nome == "walk" else 2.8, 0.25, "Y", 2.0, 0.0))
            else:
                extras.append(("pescoco", -0.8, 0.12, "X", 1.0, 0.0))
        else:
            extras.append(("pescoco", "X", (0.0, 3.0, -2.0, 2.0, 3.0, 2.0, -1.0, 1.0, 0.0)))

    for sem_mao, defas_m in (("mao_e", 0.35), ("mao_d", 0.85)):
        if sem_mao in mapa and sem_mao not in presentes_base:
            if modo == "harmonica":
                amp_m = 4.5 if nome in ("walk", "run") else 1.8
                cyc_m = 2.0 if nome in ("walk", "run") else 1.0
                extras.append((sem_mao, amp_m, defas_m, "X", cyc_m, 0.0))
            else:
                extras.append((sem_mao, "X", (0.0, 4.0, 8.0, 10.0, 8.0, 5.0, 3.0, 1.0, 0.0)))

    for sem_pe, defas_p in (("dedo_pe_e", 0.30), ("dedo_pe_d", 0.80)):
        if sem_pe in mapa and sem_pe not in presentes_base:
            if modo == "harmonica":
                amp_p = 8.0 if nome in ("walk", "run") else 1.5
                cyc_p = 2.0 if nome in ("walk", "run") else 1.0
                extras.append((sem_pe, amp_p, defas_p, "X", cyc_p, 0.0))
            else:
                extras.append((sem_pe, "X", (0.0, 10.0, -14.0, -10.0, -6.0, -8.0, 12.0, 4.0, 0.0)))

    for lado_suf, phase_lado in (("e", 0.25), ("d", 0.75), ("l", 0.25), ("r", 0.75)):
        eh_mao_arma = lado_suf in ("d", "r") and nome in _CLIPES_GRIP_MAO_ARMA
        for dedo_pref, esc, defas_d in _CHAVES_DEDOS_CASCATA:
            eh_polegar = dedo_pref in ("polegar", "thumb")
            for seg in (1, 2, 3):
                for chave_cand in (f"{dedo_pref}_{seg}_{lado_suf}", f"{dedo_pref}{seg}_{lado_suf}"):
                    if chave_cand in mapa and chave_cand not in presentes_base:
                        if eh_mao_arma:
                            g_base = (
                                _GRIP_ARMA_POLEGAR[seg - 1]
                                if eh_polegar
                                else min(76.0, _GRIP_ARMA_FALANGES[seg - 1] * esc)
                            )
                            if modo == "harmonica":
                                amp_g = 2.0 if nome == "idle" else 3.0
                                cyc_g = 2.0 if nome in ("walk", "run") else 1.0
                                extras.append((chave_cand, amp_g, (phase_lado + defas_d) % 1.0, "X", cyc_g, round(g_base, 3)))
                            else:
                                b0 = round(g_base, 3)
                                p1 = round(min(78.0, g_base * 1.06), 3)
                                p2 = round(min(82.0, g_base * 1.12), 3)
                                vals_g = (
                                    b0, round(b0 * 1.02, 3), p1, p2,
                                    round(p2 * 0.97, 3), p1, round(b0 * 1.04, 3),
                                    round(b0 * 1.01, 3), b0,
                                )
                                extras.append((chave_cand, "X", vals_g))
                        elif modo == "harmonica":
                            base_off = (26.0 if nome in ("ride_idle", "ride_fly") else 18.0) * esc
                            amp_d = (4.5 if nome in ("walk", "run", "ride_fly") else 2.2) * esc
                            cyc_d = 2.0 if nome in ("walk", "run") else 1.0
                            extras.append((chave_cand, amp_d, (phase_lado + defas_d) % 1.0, "X", cyc_d, base_off))
                        else:
                            b0, p1, p2 = round(16.0 * esc, 3), round(38.0 * esc, 3), round(48.0 * esc, 3)
                            vals_d = (b0, p1 * 0.75, p1, p2, p2 * 0.9, p1 * 0.8, b0 * 1.2, b0 * 1.05, b0)
                            if nome == "death":
                                vals_d = (b0, b0 * 1.2, p1, p1, b0 * 1.4, b0 * 1.2, b0, b0, b0)
                            extras.append((chave_cand, "X", vals_d))

    return motores_base if not extras else tuple(motores_base) + tuple(extras)


def _resolver_mapa_clipe(perfil: dict, esqueleto: str, nome: str) -> tuple[dict[str, str], bool]:
    """Resolve tabela de retarget e indica se o alvo e esqueleto de criatura/montaria."""
    mapa = profiles.retarget(perfil, esqueleto)
    eh_criatura = esqueleto in ("quadruped@1", "winged_mount@1") or "pata_dianteira_e" in mapa
    if nome in _CLIPES_EXCLUSIVOS_CRIATURA and not eh_criatura:
        for alt in ("winged_mount@1", "quadruped@1"):
            alt_mapa = profiles.retarget(perfil, alt)
            if alt_mapa:
                return alt_mapa, True
    return mapa, eh_criatura


def clipes(
    perfil: dict,
    esqueleto: str,
    pedidos: list[str] | None,
    *,
    seed: int | None = None,
    postura_preset: str | None = None,
) -> list[dict]:
    """Materializa os clipes pedidos para um esqueleto (humanoide, quadruped@1 ou winged_mount@1).

    Quando ``seed`` e ``postura_preset`` sao ``None``, preserva 100% da saida canonica base.
    """
    pedidos_list = [str(p) for p in (pedidos or [])]
    if not pedidos_list:
        return []
    mapa_base = profiles.retarget(perfil, esqueleto)
    if not mapa_base and not any(p in _CLIPES_EXCLUSIVOS_CRIATURA for p in pedidos_list):
        return []

    rig_cfg = perfil.get("rig") if isinstance(perfil, dict) else None
    postura_cfg = rig_cfg.get("postura") if isinstance(rig_cfg, dict) else None
    variacao_seed_ok = not (isinstance(postura_cfg, dict) and postura_cfg.get("variacao_seed") is False)
    usar_preset = (postura_preset is not None) or (seed is not None and variacao_seed_ok)
    preset_info = (
        resolver_preset_postura(seed=(seed if variacao_seed_ok else None), postura_preset=postura_preset)
        if usar_preset
        else None
    )

    saida = []
    for nome in pedidos_list:
        if nome not in CLIPES_SUPORTADOS:
            continue
        mapa, eh_criatura = _resolver_mapa_clipe(perfil, esqueleto, nome)
        if not mapa:
            continue
        espec = _DEFINICOES_CRIATURA.get(nome) if eh_criatura else _DEFINICOES_HUMANO.get(nome)
        if espec is None and nome in _DEFINICOES_CRIATURA:
            espec = _DEFINICOES_CRIATURA[nome]
        if espec is None:
            continue
        modo, segundos, n_segs, motores, bob_amp, bob_off, lat_amp, cyc_b = espec
        if eh_criatura:
            motores_ef = motores
        else:
            motores_p = aplicar_preset_motores(nome, motores, preset_info) if preset_info else motores
            motores_ef = _motores_secundarios_aa(mapa, nome, modo, motores_p)
        total = int(round(segundos * FPS))
        fracoes = _fracoes_24fps(total, n_segs)
        if modo == "balistica":
            bob_z = _DESLOCAMENTO_QUADRIL_Z_CRIATURA.get(nome) if eh_criatura else _DESLOCAMENTO_QUADRIL_Z.get(nome)
            chaves = _chaves_balisticas(mapa, motores_ef, fracoes, total, bob_z=bob_z)
        else:
            chaves = _chaves_harmonicas(
                mapa, motores_ef, fracoes, total,
                bob_amp_z=bob_amp, bob_offset_z=bob_off, lat_amp_x=lat_amp, ciclos_bounce=cyc_b,
            )
        saida.append(
            {
                "nome": nome,
                "fps": FPS,
                "duracao_s": round(total / FPS, 3),
                "loop": nome not in _NAO_LOOP_CLIPES,
                "chaves": chaves,
                "ossos": sorted({p["osso"] for c in chaves for p in c["poses"]}),
            }
        )
    return saida
