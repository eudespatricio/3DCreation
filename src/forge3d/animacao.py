"""Clipes base procedurais (D66/D69 + Fase B): definição única, fora do Blender.

Os clipes nascem em espaço semântico (``tronco``, ``coluna``, ``cabeca``, ``braco_e``, ``braco_d``,
``antebraco_e``, ``antebraco_d``, ``perna_e``, ``perna_d``, ``canela_e``, ``canela_d``) e o perfil
resolve o nome do osso em cada esqueleto (``rig.retarget``). A **mesma** definição alimenta o
``bpy`` (embutido no glb) e o ``.rbxlx``/``.rbxmx`` (KeyframeSequence), mantendo Godot e Roblox
sincronizados com determinismo (D1).
"""

from __future__ import annotations

import math

from . import profiles

__all__ = [
    "FPS",
    "SEGUNDOS_IDLE",
    "SEGUNDOS_WALK",
    "SEGUNDOS_RUN",
    "SEGUNDOS_JUMP",
    "SEGUNDOS_ATTACK",
    "SEGUNDOS_BLOCK",
    "SEGUNDOS_HIT",
    "SEGUNDOS_DEATH",
    "MOTORES_IDLE",
    "MOTORES_WALK",
    "MOTORES_RUN",
    "MOTORES_JUMP",
    "MOTORES_ATTACK",
    "MOTORES_BLOCK",
    "MOTORES_HIT",
    "MOTORES_DEATH",
    "clipes",
]

FPS = 24
SEGUNDOS_IDLE = 2.0
SEGUNDOS_WALK = 2.0
SEGUNDOS_RUN = 1.667
SEGUNDOS_JUMP = 1.667
SEGUNDOS_ATTACK = 0.833
SEGUNDOS_BLOCK = 1.0
SEGUNDOS_HIT = 0.5
SEGUNDOS_DEATH = 1.25

_NAO_LOOP_CLIPES = frozenset({"jump", "attack", "block", "hit", "death"})

#: Frações do ciclo com chave para `idle` (0, 25, 50, 75 e 100 %).
FRACOES = (0.0, 0.25, 0.5, 0.75, 1.0)

#: Frações do ciclo com chave para `walk`, `run` e `jump` (9 chaves em passos de 12,5 %).
FRACOES_CICLO = (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0)

#: Motores do `idle`: (osso semântico, amplitude em graus no eixo local, defasagem no ciclo, eixo).
MOTORES_IDLE = (
    ("coluna", 0.8, 0.0, "X"),
    ("tronco", 1.6, 0.0, "X"),
    ("cabeca", -1.2, 0.12, "X"),
    ("braco_e", 2.0, 0.25, "X"),
    ("braco_d", 2.0, 0.75, "X"),
)

#: Motores harmônicos de locomoção: (osso, amplitude_graus, defasagem, eixo, ciclos, offset_graus).
#: 2 ciclos em 2,0 s = passada natural de 1,0 s; perna/braço opostos com flexão unidirecional em
#: joelhos (<= 0°) e cotovelos (>= 0°). Eixos em juntas R15 compartilhadas ficam distintos (Z/Y vs X).
MOTORES_WALK = (
    ("quadril", 3.0, 0.0, "Z", 2, 0.0),
    ("coluna", 2.0, 0.0, "Y", 2, 0.0),
    ("tronco", 2.5, 0.75, "X", 4, -3.5),
    ("cabeca", 1.5, 0.25, "X", 4, 2.0),
    ("ombro_e", 2.5, 0.5, "Z", 2, 0.0),
    ("ombro_d", 2.5, 0.0, "Z", 2, 0.0),
    ("braco_e", 22.0, 0.5, "X", 2, 0.0),
    ("braco_d", 22.0, 0.0, "X", 2, 0.0),
    ("antebraco_e", 10.0, 0.5, "X", 2, 12.0),
    ("antebraco_d", 10.0, 0.0, "X", 2, 12.0),
    ("perna_e", 28.0, 0.0, "X", 2, 0.0),
    ("perna_d", 28.0, 0.5, "X", 2, 0.0),
    ("canela_e", 18.0, 0.75, "X", 2, -18.0),
    ("canela_d", 18.0, 0.25, "X", 2, -18.0),
    ("pe_e", 12.0, 0.25, "X", 2, 0.0),
    ("pe_d", 12.0, 0.75, "X", 2, 0.0),
)

#: Corrida: passada mais ampla, inclinação à frente e cotovelos dobrados.
MOTORES_RUN = (
    ("quadril", 5.0, 0.0, "Z", 2, 0.0),
    ("coluna", 4.0, 0.0, "Y", 2, 0.0),
    ("tronco", 5.0, 0.75, "X", 4, -12.0),
    ("cabeca", 3.0, 0.25, "X", 4, 8.0),
    ("ombro_e", 4.0, 0.5, "Z", 2, 0.0),
    ("ombro_d", 4.0, 0.0, "Z", 2, 0.0),
    ("braco_e", 42.0, 0.5, "X", 2, 8.0),
    ("braco_d", 42.0, 0.0, "X", 2, 8.0),
    ("antebraco_e", 18.0, 0.5, "X", 2, 48.0),
    ("antebraco_d", 18.0, 0.0, "X", 2, 48.0),
    ("perna_e", 45.0, 0.0, "X", 2, 5.0),
    ("perna_d", 45.0, 0.5, "X", 2, 5.0),
    ("canela_e", 32.0, 0.75, "X", 2, -35.0),
    ("canela_d", 32.0, 0.25, "X", 2, -35.0),
    ("pe_e", 18.0, 0.25, "X", 2, -4.0),
    ("pe_d", 18.0, 0.75, "X", 2, -4.0),
)

#: Salto balístico: (osso semântico, eixo, ângulos em graus para as 9 frações de `FRACOES_CICLO`).
#: Fases: neutro -> agachar -> impulso -> subida -> ápice -> descida -> pouso -> amortecer -> neutro.
MOTORES_JUMP = (
    ("quadril", "Z", (0.0, 3.0, -2.0, 0.0, 2.0, 0.0, -3.0, 2.0, 0.0)),
    ("coluna", "X", (0.0, -10.0, 4.0, -4.0, -6.0, -6.0, -10.0, -4.0, 0.0)),
    ("tronco", "X", (0.0, -18.0, 6.0, -6.0, -8.0, -10.0, -20.0, -6.0, 0.0)),
    ("cabeca", "X", (0.0, 12.0, -4.0, 4.0, 5.0, 6.0, 14.0, 4.0, 0.0)),
    ("ombro_e", "Z", (0.0, 6.0, -10.0, -14.0, -16.0, -8.0, 4.0, 2.0, 0.0)),
    ("ombro_d", "Z", (0.0, -6.0, 10.0, 14.0, 16.0, 8.0, -4.0, -2.0, 0.0)),
    ("braco_e", "X", (0.0, -35.0, 70.0, 105.0, 120.0, 65.0, -20.0, -5.0, 0.0)),
    ("braco_d", "X", (0.0, -35.0, 70.0, 105.0, 120.0, 65.0, -20.0, -5.0, 0.0)),
    ("antebraco_e", "X", (0.0, 25.0, 20.0, 15.0, 10.0, 20.0, 35.0, 10.0, 0.0)),
    ("antebraco_d", "X", (0.0, 25.0, 20.0, 15.0, 10.0, 20.0, 35.0, 10.0, 0.0)),
    ("perna_e", "X", (0.0, 35.0, -15.0, 40.0, 50.0, 25.0, 38.0, 12.0, 0.0)),
    ("perna_d", "X", (0.0, 35.0, -15.0, 40.0, 50.0, 25.0, 38.0, 12.0, 0.0)),
    ("canela_e", "X", (0.0, -55.0, -5.0, -60.0, -70.0, -30.0, -60.0, -18.0, 0.0)),
    ("canela_d", "X", (0.0, -55.0, -5.0, -60.0, -70.0, -30.0, -60.0, -18.0, 0.0)),
    ("pe_e", "X", (0.0, 18.0, -28.0, -15.0, -10.0, -18.0, 20.0, 8.0, 0.0)),
    ("pe_d", "X", (0.0, 18.0, -28.0, -15.0, -10.0, -18.0, 20.0, 8.0, 0.0)),
)

#: Ataque corpo-a-corpo (wind-up -> golpe -> follow-through -> retorno).
MOTORES_ATTACK = (
    ("quadril", "Z", (0.0, -10.0, -14.0, 18.0, 22.0, 14.0, 6.0, 2.0, 0.0)),
    ("coluna", "Y", (0.0, -16.0, -22.0, 24.0, 28.0, 18.0, 8.0, 3.0, 0.0)),
    ("tronco", "X", (0.0, 8.0, 10.0, -18.0, -24.0, -14.0, -6.0, -2.0, 0.0)),
    ("cabeca", "X", (0.0, -4.0, -6.0, 12.0, 15.0, 10.0, 4.0, 1.0, 0.0)),
    ("ombro_d", "Z", (0.0, 12.0, 18.0, -14.0, -18.0, -10.0, -4.0, -1.0, 0.0)),
    ("braco_d", "X", (0.0, -45.0, -70.0, 85.0, 95.0, 60.0, 28.0, 10.0, 0.0)),
    ("antebraco_d", "X", (0.0, 65.0, 75.0, 20.0, 12.0, 18.0, 24.0, 12.0, 0.0)),
    ("ombro_e", "Z", (0.0, -6.0, -8.0, 8.0, 10.0, 6.0, 3.0, 1.0, 0.0)),
    ("braco_e", "X", (0.0, 18.0, 24.0, -18.0, -25.0, -16.0, -8.0, -3.0, 0.0)),
    ("antebraco_e", "X", (0.0, 35.0, 40.0, 30.0, 25.0, 22.0, 18.0, 8.0, 0.0)),
    ("perna_e", "X", (0.0, 10.0, 14.0, 26.0, 28.0, 20.0, 12.0, 4.0, 0.0)),
    ("perna_d", "X", (0.0, -8.0, -12.0, -22.0, -24.0, -18.0, -10.0, -4.0, 0.0)),
    ("canela_e", "X", (0.0, -14.0, -18.0, -28.0, -30.0, -22.0, -12.0, -4.0, 0.0)),
    ("canela_d", "X", (0.0, -10.0, -14.0, -16.0, -18.0, -14.0, -8.0, -2.0, 0.0)),
    ("pe_e", "X", (0.0, 4.0, 6.0, 10.0, 12.0, 8.0, 4.0, 2.0, 0.0)),
    ("pe_d", "X", (0.0, -6.0, -8.0, -12.0, -14.0, -10.0, -6.0, -2.0, 0.0)),
)

#: Postura defensiva / escudo levantado.
MOTORES_BLOCK = (
    ("quadril", "Z", (0.0, 8.0, 12.0, 12.0, 12.0, 12.0, 10.0, 5.0, 0.0)),
    ("coluna", "Y", (0.0, 14.0, 20.0, 20.0, 20.0, 20.0, 16.0, 8.0, 0.0)),
    ("tronco", "X", (0.0, -8.0, -12.0, -12.0, -14.0, -12.0, -10.0, -5.0, 0.0)),
    ("cabeca", "X", (0.0, 8.0, 10.0, 10.0, 10.0, 10.0, 8.0, 4.0, 0.0)),
    ("ombro_e", "Z", (0.0, -10.0, -16.0, -16.0, -16.0, -16.0, -12.0, -6.0, 0.0)),
    ("braco_e", "X", (0.0, 55.0, 80.0, 80.0, 82.0, 80.0, 65.0, 30.0, 0.0)),
    ("antebraco_e", "X", (0.0, 60.0, 88.0, 88.0, 90.0, 88.0, 72.0, 35.0, 0.0)),
    ("ombro_d", "Z", (0.0, 4.0, 6.0, 6.0, 6.0, 6.0, 4.0, 2.0, 0.0)),
    ("braco_d", "X", (0.0, 15.0, 22.0, 22.0, 22.0, 22.0, 18.0, 8.0, 0.0)),
    ("antebraco_d", "X", (0.0, 35.0, 50.0, 50.0, 50.0, 50.0, 40.0, 20.0, 0.0)),
    ("perna_e", "X", (0.0, 14.0, 20.0, 20.0, 20.0, 20.0, 16.0, 8.0, 0.0)),
    ("perna_d", "X", (0.0, -12.0, -16.0, -16.0, -16.0, -16.0, -12.0, -6.0, 0.0)),
    ("canela_e", "X", (0.0, -18.0, -26.0, -26.0, -26.0, -26.0, -20.0, -10.0, 0.0)),
    ("canela_d", "X", (0.0, -12.0, -16.0, -16.0, -16.0, -16.0, -12.0, -6.0, 0.0)),
    ("pe_e", "X", (0.0, 6.0, 8.0, 8.0, 8.0, 8.0, 6.0, 3.0, 0.0)),
    ("pe_d", "X", (0.0, -4.0, -6.0, -6.0, -6.0, -6.0, -4.0, -2.0, 0.0)),
)

#: Recuo de impacto rápido.
MOTORES_HIT = (
    ("quadril", "Z", (0.0, -8.0, -12.0, -9.0, -5.0, -3.0, -1.5, -0.5, 0.0)),
    ("coluna", "X", (0.0, 14.0, 22.0, 18.0, 12.0, 7.0, 4.0, 1.5, 0.0)),
    ("tronco", "X", (0.0, 18.0, 26.0, 20.0, 12.0, 7.0, 4.0, 1.5, 0.0)),
    ("cabeca", "X", (0.0, 16.0, 24.0, 18.0, 10.0, 5.0, 3.0, 1.0, 0.0)),
    ("ombro_e", "Z", (0.0, -10.0, -14.0, -10.0, -6.0, -3.0, -1.5, -0.5, 0.0)),
    ("ombro_d", "Z", (0.0, 10.0, 14.0, 10.0, 6.0, 3.0, 1.5, 0.5, 0.0)),
    ("braco_e", "X", (0.0, -18.0, -28.0, -22.0, -14.0, -8.0, -4.0, -1.5, 0.0)),
    ("braco_d", "X", (0.0, -16.0, -24.0, -18.0, -12.0, -6.0, -3.0, -1.0, 0.0)),
    ("antebraco_e", "X", (0.0, 25.0, 35.0, 28.0, 18.0, 10.0, 5.0, 2.0, 0.0)),
    ("antebraco_d", "X", (0.0, 25.0, 35.0, 28.0, 18.0, 10.0, 5.0, 2.0, 0.0)),
    ("perna_e", "X", (0.0, 12.0, 18.0, 14.0, 9.0, 5.0, 3.0, 1.0, 0.0)),
    ("perna_d", "X", (0.0, -8.0, -12.0, -9.0, -6.0, -3.0, -2.0, -0.5, 0.0)),
    ("canela_e", "X", (0.0, -18.0, -26.0, -20.0, -12.0, -7.0, -4.0, -1.5, 0.0)),
    ("canela_d", "X", (0.0, -10.0, -15.0, -12.0, -7.0, -4.0, -2.0, -0.5, 0.0)),
    ("pe_e", "X", (0.0, 8.0, 12.0, 9.0, 6.0, 3.0, 1.5, 0.5, 0.0)),
    ("pe_d", "X", (0.0, -5.0, -8.0, -6.0, -4.0, -2.0, -1.0, -0.5, 0.0)),
)

#: Queda e derrota no solo (sem loop).
MOTORES_DEATH = (
    ("quadril", "Z", (0.0, 6.0, 12.0, 18.0, 22.0, 24.0, 24.0, 24.0, 24.0)),
    ("coluna", "X", (0.0, 10.0, -8.0, -28.0, -52.0, -72.0, -82.0, -85.0, -85.0)),
    ("tronco", "X", (0.0, 12.0, -6.0, -18.0, -26.0, -30.0, -32.0, -32.0, -32.0)),
    ("cabeca", "X", (0.0, 10.0, 6.0, -8.0, -18.0, -22.0, -24.0, -24.0, -24.0)),
    ("ombro_e", "Z", (0.0, -8.0, -14.0, -18.0, -20.0, -22.0, -22.0, -22.0, -22.0)),
    ("ombro_d", "Z", (0.0, 8.0, 14.0, 18.0, 20.0, 22.0, 22.0, 22.0, 22.0)),
    ("braco_e", "X", (0.0, -15.0, 20.0, 45.0, 30.0, 15.0, 10.0, 10.0, 10.0)),
    ("braco_d", "X", (0.0, -15.0, 15.0, 35.0, 22.0, 12.0, 8.0, 8.0, 8.0)),
    ("antebraco_e", "X", (0.0, 20.0, 28.0, 22.0, 16.0, 12.0, 10.0, 10.0, 10.0)),
    ("antebraco_d", "X", (0.0, 20.0, 26.0, 20.0, 14.0, 10.0, 8.0, 8.0, 8.0)),
    ("perna_e", "X", (0.0, 16.0, 22.0, 18.0, 10.0, 4.0, 2.0, 2.0, 2.0)),
    ("perna_d", "X", (0.0, 10.0, 14.0, 12.0, 8.0, 4.0, 2.0, 2.0, 2.0)),
    ("canela_e", "X", (0.0, -32.0, -48.0, -36.0, -18.0, -8.0, -4.0, -4.0, -4.0)),
    ("canela_d", "X", (0.0, -24.0, -36.0, -26.0, -14.0, -6.0, -4.0, -4.0, -4.0)),
    ("pe_e", "X", (0.0, 10.0, 12.0, -6.0, -18.0, -22.0, -24.0, -24.0, -24.0)),
    ("pe_d", "X", (0.0, 8.0, 10.0, -4.0, -14.0, -18.0, -20.0, -20.0, -20.0)),
)

_DESLOCAMENTO_QUADRIL_Z: dict[str, tuple[float, ...]] = {
    "jump": (0.0, -0.06, 0.04, 0.28, 0.36, 0.18, -0.05, -0.08, 0.0),
    "attack": (0.0, -0.01, -0.02, 0.01, 0.0, -0.01, -0.01, 0.0, 0.0),
    "block": (0.0, -0.03, -0.05, -0.05, -0.05, -0.05, -0.04, -0.02, 0.0),
    "hit": (0.0, -0.02, -0.04, -0.03, -0.02, -0.01, 0.0, 0.0, 0.0),
    "death": (0.0, -0.05, -0.14, -0.30, -0.52, -0.68, -0.74, -0.75, -0.75),
}


def _chaves_harmonicas(
    mapa: dict[str, str],
    motores: tuple,
    fracoes: tuple[float, ...],
    total_frames: int,
    bob_amp_z: float = 0.0,
) -> list[dict]:
    chaves = []
    for fracao in fracoes:
        poses = []
        for entrada in motores:
            if len(entrada) == 4:
                semantico, amplitude, defasagem, eixo = entrada
                ciclos, offset = 1.0, 0.0
            else:
                semantico, amplitude, defasagem, eixo, ciclos, offset = entrada
            osso = mapa.get(semantico)
            if not osso:
                continue
            graus = offset + amplitude * math.sin(2.0 * math.pi * (ciclos * fracao + defasagem))
            pose: dict[str, object] = {"osso": osso, "graus": round(graus, 6), "eixo": eixo}
            if semantico == "quadril" and bob_amp_z > 0.0:
                dz = bob_amp_z * abs(math.sin(2.0 * math.pi * fracao))
                pose["deslocamento_m"] = [0.0, 0.0, round(dz, 6)]
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
    for idx, fracao in enumerate(fracoes):
        poses = []
        for semantico, eixo, valores in motores:
            osso = mapa.get(semantico)
            if not osso:
                continue
            pose: dict[str, object] = {
                "osso": osso,
                "graus": round(float(valores[idx]), 6),
                "eixo": eixo,
            }
            if semantico == "quadril" and bob_z is not None:
                pose["deslocamento_m"] = [0.0, 0.0, round(float(bob_z[idx]), 6)]
            poses.append(pose)
        chaves.append(
            {
                "frame": 1 + int(round(fracao * total_frames)),
                "segundos": round(fracao * total_frames / FPS, 4),
                "poses": poses,
            }
        )
    return chaves


_DEFINICOES = {
    "idle": ("harmonica", SEGUNDOS_IDLE, FRACOES, MOTORES_IDLE, 0.0),
    "walk": ("harmonica", SEGUNDOS_WALK, FRACOES_CICLO, MOTORES_WALK, 0.025),
    "run": ("harmonica", SEGUNDOS_RUN, FRACOES_CICLO, MOTORES_RUN, 0.045),
    "jump": ("balistica", SEGUNDOS_JUMP, FRACOES_CICLO, MOTORES_JUMP, 0.0),
    "attack": ("balistica", SEGUNDOS_ATTACK, FRACOES_CICLO, MOTORES_ATTACK, 0.0),
    "block": ("balistica", SEGUNDOS_BLOCK, FRACOES_CICLO, MOTORES_BLOCK, 0.0),
    "hit": ("balistica", SEGUNDOS_HIT, FRACOES_CICLO, MOTORES_HIT, 0.0),
    "death": ("balistica", SEGUNDOS_DEATH, FRACOES_CICLO, MOTORES_DEATH, 0.0),
}


def clipes(perfil: dict, esqueleto: str, pedidos: list[str] | None) -> list[dict]:
    """Materializa os clipes pedidos para um esqueleto.

    Devolve ``[]`` quando não há pedido, quando o clipe não tem gerador ou quando o perfil não
    declara retarget para o esqueleto (o chamador avisa; ver ``FORGE-W-ANIM``).
    """
    mapa = profiles.retarget(perfil, esqueleto)
    pedidos = [str(p) for p in (pedidos or [])]
    if not mapa or not pedidos:
        return []
    saida = []
    for nome in pedidos:
        if nome not in profiles.ANIMACOES_SUPORTADAS:
            continue
        espec = _DEFINICOES.get(nome)
        if espec is None:
            continue
        modo, segundos, fracoes, motores, bob_amp = espec
        total = int(round(segundos * FPS))
        if modo == "balistica":
            chaves = _chaves_balisticas(
                mapa,
                motores,
                fracoes,
                total,
                bob_z=_DESLOCAMENTO_QUADRIL_Z.get(nome),
            )
        else:
            chaves = _chaves_harmonicas(mapa, motores, fracoes, total, bob_amp_z=bob_amp)
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
