"""Clipes base procedurais V2 (D66/D69 + Biomecanica C1 24fps): definicao unica fora do Blender.

Os clipes nascem em espaco semantico e cada perfil resolve o nome real do osso em
``rig.retarget``. Sintetiza curvas C1 continuas densas a 24 fps (``16..32`` chaves por clipe),
sem descontinuidade em V no quadril e com contra-rotacao de coluna/pescoco/cabeca,
seguimento de fase em bracos/cotovelos e asas, alem de suporte nativo a ``ride_idle``,
``ride_fly`` e esqueletos ``quadruped@1`` / ``winged_mount@1``.
"""

from __future__ import annotations

import math

from . import profiles

__all__ = [
    "FPS",
    "CLIPES_SUPORTADOS",
    "SEGUNDOS_IDLE",
    "SEGUNDOS_WALK",
    "SEGUNDOS_RUN",
    "SEGUNDOS_JUMP",
    "SEGUNDOS_ATTACK",
    "SEGUNDOS_SLASH_COMBO",
    "SEGUNDOS_CAST",
    "SEGUNDOS_BLOCK",
    "SEGUNDOS_HIT",
    "SEGUNDOS_DEATH",
    "SEGUNDOS_RIDE_IDLE",
    "SEGUNDOS_RIDE_FLY",
    "SEGUNDOS_GALLOP",
    "SEGUNDOS_WING_FLAP",
    "SEGUNDOS_GLIDE",
    "SEGUNDOS_BITE",
    "SEGUNDOS_ROAR",
    "MOTORES_IDLE",
    "MOTORES_WALK",
    "MOTORES_RUN",
    "MOTORES_JUMP",
    "MOTORES_ATTACK",
    "MOTORES_BLOCK",
    "MOTORES_HIT",
    "MOTORES_DEATH",
    "amostrar_curva_c1",
    "clipes",
]

FPS = 24
SEGUNDOS_IDLE = 2.0
SEGUNDOS_WALK = 2.0
SEGUNDOS_RUN = 1.667
SEGUNDOS_JUMP = 1.667
SEGUNDOS_ATTACK = 0.833
SEGUNDOS_SLASH_COMBO = 1.5
SEGUNDOS_CAST = 1.25
SEGUNDOS_BLOCK = 1.0
SEGUNDOS_HIT = 0.5
SEGUNDOS_DEATH = 1.25
SEGUNDOS_RIDE_IDLE = 2.0
SEGUNDOS_RIDE_FLY = 1.0
SEGUNDOS_GALLOP = 0.833
SEGUNDOS_WING_FLAP = 1.0
SEGUNDOS_GLIDE = 2.0
SEGUNDOS_BITE = 0.833
SEGUNDOS_ROAR = 1.5

CLIPES_SUPORTADOS = (
    "idle",
    "walk",
    "run",
    "jump",
    "attack",
    "slash_combo",
    "cast",
    "block",
    "hit",
    "death",
    "ride_idle",
    "ride_fly",
    "gallop",
    "wing_flap",
    "glide",
    "bite",
    "roar",
)

_CLIPES_EXCLUSIVOS_CRIATURA = frozenset({"gallop", "wing_flap", "glide", "bite", "roar"})
_NAO_LOOP_CLIPES = frozenset({"jump", "attack", "slash_combo", "cast", "block", "hit", "death", "bite", "roar"})

#: Fracoes legadas mantidas para compatibilidade de constantes importadas.
FRACOES = (0.0, 0.25, 0.5, 0.75, 1.0)
FRACOES_CICLO = (0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0)

#: Motores do `idle` com transferencia sutil de peso no quadril (LowerTorso ativo no R15).
MOTORES_IDLE = (
    ("quadril", 0.6, 0.0, "Z", 1, 0.0),
    ("quadril", 0.35, 0.25, "X", 1, 0.0),
    ("coluna", 0.8, 0.0, "X"),
    ("tronco", 1.6, 0.0, "X"),
    ("cabeca", -1.4, 0.12, "X"),
    ("braco_e", 2.0, 0.25, "X"),
    ("braco_d", 2.0, 0.75, "X"),
)

#: Locomocao humana C1: bounce duplo suave em cosseno, contra-rotacao de coluna/cabeca,
#: joelho assimetrico (<= 0 deg) e seguimento defasado em cotovelos (>= 0 deg).
MOTORES_WALK = (
    ("quadril", 3.2, 0.0, "Z", 2, 0.0),
    ("quadril", 3.5, 0.25, "Y", 2, 0.0),
    ("coluna", 2.8, 0.75, "Y", 2, 0.0),
    ("tronco", 4.5, 0.75, "Y", 2, 0.0),
    ("tronco", 2.2, 0.75, "X", 4, -3.5),
    ("cabeca", 3.5, 0.25, "Y", 2, 0.0),
    ("cabeca", 1.6, 0.25, "X", 4, 2.5),
    ("ombro_e", 2.8, 0.5, "Z", 2, 0.0),
    ("ombro_d", 2.8, 0.0, "Z", 2, 0.0),
    ("braco_e", 22.0, 0.5, "X", 2, 0.0),
    ("braco_d", 22.0, 0.0, "X", 2, 0.0),
    ("antebraco_e", 10.0, 0.58, "X", 2, 13.0),
    ("antebraco_d", 10.0, 0.08, "X", 2, 13.0),
    ("perna_e", 28.0, 0.0, "X", 2, 0.0, 3.0, 0.25),
    ("perna_d", 28.0, 0.5, "X", 2, 0.0, 3.0, 0.25),
    ("canela_e", 18.0, 0.75, "X", 2, -21.0, 2.5, 0.0),
    ("canela_d", 18.0, 0.25, "X", 2, -21.0, 2.5, 0.0),
    ("pe_e", 12.0, 0.25, "X", 2, 0.0),
    ("pe_d", 12.0, 0.75, "X", 2, 0.0),
)

#: Corrida: maior amplitude, inclinacao aerodinamica, contra-rotacao estabilizada e cotovelos flexionados.
MOTORES_RUN = (
    ("quadril", 5.0, 0.0, "Z", 2, 0.0),
    ("quadril", 5.5, 0.25, "Y", 2, 0.0),
    ("coluna", 4.5, 0.75, "Y", 2, 0.0),
    ("tronco", 7.0, 0.75, "Y", 2, 0.0),
    ("tronco", 4.5, 0.75, "X", 4, -12.0),
    ("cabeca", 5.5, 0.25, "Y", 2, 0.0),
    ("cabeca", 3.0, 0.25, "X", 4, 8.5),
    ("ombro_e", 4.5, 0.5, "Z", 2, 0.0),
    ("ombro_d", 4.5, 0.0, "Z", 2, 0.0),
    ("braco_e", 42.0, 0.5, "X", 2, 8.0),
    ("braco_d", 42.0, 0.0, "X", 2, 8.0),
    ("antebraco_e", 18.0, 0.60, "X", 2, 50.0),
    ("antebraco_d", 18.0, 0.10, "X", 2, 50.0),
    ("perna_e", 45.0, 0.0, "X", 2, 5.0, 5.0, 0.25),
    ("perna_d", 45.0, 0.5, "X", 2, 5.0, 5.0, 0.25),
    ("canela_e", 32.0, 0.75, "X", 2, -37.0, 4.5, 0.0),
    ("canela_d", 32.0, 0.25, "X", 2, -37.0, 4.5, 0.0),
    ("pe_e", 18.0, 0.25, "X", 2, -4.0),
    ("pe_d", 18.0, 0.75, "X", 2, -4.0),
)

#: Montaria em repouso (`ride_idle`): pelve abaixada, coxas abduzidas 38 deg e flexionadas 52 deg,
#: joelhos dobrados -78 deg, tronco inclinado 10 deg a frente e maos nas redeas.
MOTORES_RIDE_IDLE = (
    ("quadril", 2.2, 0.0, "Z", 1, 0.0),
    ("quadril", 1.8, 0.25, "X", 1, -6.0),
    ("coluna", 1.2, 0.0, "X", 1, -3.0),
    ("tronco", 2.0, 0.0, "X", 1, -10.0),
    ("tronco", 1.6, 0.5, "Z", 1, 0.0),
    ("cabeca", 1.6, 0.0, "X", 1, 10.0),
    ("braco_e", 3.0, 0.25, "X", 1, 36.0),
    ("braco_d", 3.0, 0.25, "X", 1, 36.0),
    ("braco_e", 1.0, 0.0, "Z", 1, -10.0),
    ("braco_d", 1.0, 0.0, "Z", 1, 10.0),
    ("antebraco_e", 3.5, 0.35, "X", 1, 44.0),
    ("antebraco_d", 3.5, 0.35, "X", 1, 44.0),
    ("perna_e", 2.0, 0.0, "X", 1, 52.0),
    ("perna_d", 2.0, 0.0, "X", 1, 52.0),
    ("perna_e", 1.5, 0.25, "Z", 1, -38.0),
    ("perna_d", 1.5, 0.75, "Z", 1, 38.0),
    ("canela_e", 2.5, 0.5, "X", 1, -78.0),
    ("canela_d", 2.5, 0.5, "X", 1, -78.0),
    ("pe_e", 2.5, 0.25, "X", 1, 12.0),
    ("pe_d", 2.5, 0.25, "X", 1, 12.0),
)

#: Montaria em voo (`ride_fly`): postura montada sincronizada ao batimento de asas.
MOTORES_RIDE_FLY = (
    ("quadril", 4.0, 0.0, "Z", 1, 0.0),
    ("quadril", 4.5, 0.25, "X", 1, -8.0),
    ("coluna", 2.5, 0.0, "X", 1, -5.0),
    ("tronco", 3.5, 0.0, "X", 1, -14.0),
    ("cabeca", 3.0, 0.0, "X", 1, 13.0),
    ("braco_e", 5.5, 0.25, "X", 1, 42.0),
    ("braco_d", 5.5, 0.25, "X", 1, 42.0),
    ("braco_e", 1.5, 0.0, "Z", 1, -12.0),
    ("braco_d", 1.5, 0.0, "Z", 1, 12.0),
    ("antebraco_e", 6.0, 0.35, "X", 1, 48.0),
    ("antebraco_d", 6.0, 0.35, "X", 1, 48.0),
    ("perna_e", 3.5, 0.0, "X", 1, 52.0),
    ("perna_d", 3.5, 0.0, "X", 1, 52.0),
    ("perna_e", 2.0, 0.25, "Z", 1, -38.0),
    ("perna_d", 2.0, 0.75, "Z", 1, 38.0),
    ("canela_e", 4.0, 0.5, "X", 1, -78.0),
    ("canela_d", 4.0, 0.5, "X", 1, -78.0),
    ("pe_e", 4.0, 0.25, "X", 1, 15.0),
    ("pe_d", 4.0, 0.25, "X", 1, 15.0),
)

#: Salto balistico.
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

#: Combo de tres cortes encadeados com torcao pelvica e contra-estabilizacao cervical.
MOTORES_SLASH_COMBO = (
    ("quadril", "Y", (0.0, -18.0, 24.0, 14.0, -22.0, 28.0, -10.0, 12.0, 0.0)),
    ("coluna", "Y", (0.0, -14.0, 22.0, 12.0, -20.0, 26.0, -12.0, 8.0, 0.0)),
    ("tronco", "X", (0.0, 8.0, -16.0, -6.0, -14.0, -22.0, 12.0, -26.0, 0.0)),
    ("cabeca", "Y", (0.0, 12.0, -18.0, -10.0, 18.0, -22.0, 10.0, -8.0, 0.0)),
    ("ombro_d", "Z", (0.0, 16.0, -18.0, -8.0, 14.0, -20.0, 22.0, -16.0, 0.0)),
    ("braco_d", "X", (0.0, -55.0, 90.0, 35.0, -40.0, 95.0, -110.0, 115.0, 0.0)),
    ("antebraco_d", "X", (0.0, 65.0, 18.0, 45.0, 70.0, 16.0, 55.0, 12.0, 0.0)),
    ("ombro_e", "Z", (0.0, -6.0, 10.0, 12.0, -14.0, 12.0, 16.0, -10.0, 0.0)),
    ("braco_e", "X", (0.0, 20.0, -22.0, 55.0, 75.0, -25.0, 85.0, 45.0, 0.0)),
    ("antebraco_e", "X", (0.0, 32.0, 28.0, 22.0, 45.0, 24.0, 40.0, 18.0, 0.0)),
    ("perna_e", "X", (0.0, 12.0, 24.0, 16.0, -10.0, 28.0, 14.0, 32.0, 0.0)),
    ("perna_d", "X", (0.0, -10.0, -20.0, -12.0, 18.0, -24.0, -12.0, -26.0, 0.0)),
    ("canela_e", "X", (0.0, -18.0, -28.0, -20.0, -12.0, -32.0, -18.0, -34.0, 0.0)),
    ("canela_d", "X", (0.0, -12.0, -18.0, -14.0, -24.0, -18.0, -16.0, -18.0, 0.0)),
)

#: Conjuracao de magia (coleta energia -> canalizacao bilateral -> disparo -> retorno).
MOTORES_CAST = (
    ("quadril", "Z", (0.0, 0.0, 3.0, 2.0, 0.0, -3.0, -2.0, 0.0, 0.0)),
    ("coluna", "X", (0.0, -8.0, -10.0, 4.0, 10.0, -12.0, -8.0, -4.0, 0.0)),
    ("tronco", "X", (0.0, -10.0, -14.0, 8.0, 14.0, -18.0, -12.0, -5.0, 0.0)),
    ("cabeca", "X", (0.0, 8.0, 12.0, -6.0, -10.0, 14.0, 10.0, 4.0, 0.0)),
    ("ombro_e", "Z", (0.0, -10.0, -18.0, -22.0, -14.0, 12.0, 8.0, 2.0, 0.0)),
    ("ombro_d", "Z", (0.0, 10.0, 18.0, 22.0, 14.0, -12.0, -8.0, -2.0, 0.0)),
    ("braco_e", "X", (0.0, 30.0, 58.0, 72.0, 42.0, 102.0, 85.0, 35.0, 0.0)),
    ("braco_d", "X", (0.0, 30.0, 58.0, 72.0, 42.0, 102.0, 85.0, 35.0, 0.0)),
    ("antebraco_e", "X", (0.0, 55.0, 78.0, 85.0, 62.0, 18.0, 24.0, 18.0, 0.0)),
    ("antebraco_d", "X", (0.0, 55.0, 78.0, 85.0, 62.0, 18.0, 24.0, 18.0, 0.0)),
    ("perna_e", "X", (0.0, 12.0, 16.0, 14.0, 10.0, 18.0, 14.0, 6.0, 0.0)),
    ("perna_d", "X", (0.0, -10.0, -14.0, -12.0, -8.0, -14.0, -10.0, -4.0, 0.0)),
    ("canela_e", "X", (0.0, -18.0, -24.0, -20.0, -16.0, -24.0, -18.0, -8.0, 0.0)),
    ("canela_d", "X", (0.0, -12.0, -16.0, -14.0, -10.0, -16.0, -12.0, -6.0, 0.0)),
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

#: Recuo de impacto rapido.
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

# Motores especificos para criaturas quadrupedes e montarias aladas
_MOTORES_CRIATURA_IDLE = (
    ("quadril", 1.2, 0.0, "Z", 1, 0.0),
    ("coluna", 1.5, 0.0, "X", 1, 0.0),
    ("tronco", 2.2, 0.1, "X", 1, 0.0),
    ("pescoco", 2.5, 0.25, "X", 1, 0.0),
    ("cabeca", 2.0, 0.35, "X", 1, 0.0),
    ("cauda_1", 8.0, 0.0, "Z", 1, 0.0),
    ("cauda_2", 12.0, 0.16, "Z", 1, 0.0),
    ("cauda_3", 16.0, 0.32, "Z", 1, 0.0),
    ("asa_ombro_e", 3.5, 0.0, "Z", 1, -8.0),
    ("asa_ombro_d", -3.5, 0.0, "Z", 1, 8.0),
    ("asa_braco_e", 4.0, 0.12, "Z", 1, 10.0),
    ("asa_braco_d", -4.0, 0.12, "Z", 1, -10.0),
)

_MOTORES_CRIATURA_WALK = (
    ("quadril", 2.5, 0.0, "Z", 2, 0.0),
    ("coluna", 2.5, 0.25, "Z", 2, 0.0),
    ("tronco", 3.0, 0.75, "Z", 2, 0.0),
    ("pescoco", 3.5, 0.5, "X", 4, 0.0),
    ("cabeca", 3.0, 0.0, "X", 4, 0.0),
    ("cauda_1", 10.0, 0.0, "Z", 2, 0.0),
    ("cauda_2", 14.0, 0.16, "Z", 2, 0.0),
    ("cauda_3", 18.0, 0.32, "Z", 2, 0.0),
    ("pata_dianteira_e", 26.0, 0.0, "X", 2, 0.0),
    ("canela_dianteira_e", 16.0, 0.75, "X", 2, -18.0),
    ("pata_dianteira_d", 26.0, 0.5, "X", 2, 0.0),
    ("canela_dianteira_d", 16.0, 0.25, "X", 2, -18.0),
    ("pata_traseira_e", 26.0, 0.5, "X", 2, 0.0),
    ("canela_traseira_e", 16.0, 0.25, "X", 2, -18.0),
    ("pata_traseira_d", 26.0, 0.0, "X", 2, 0.0),
    ("canela_traseira_d", 16.0, 0.75, "X", 2, -18.0),
)

_MOTORES_CRIATURA_GALLOP = (
    ("quadril", 6.5, 0.0, "X", 1, 0.0),
    ("coluna", 8.0, 0.12, "X", 1, 0.0),
    ("tronco", 7.0, 0.24, "X", 1, 0.0),
    ("pescoco", 8.5, 0.55, "X", 1, 4.0),
    ("cabeca", 7.5, 0.05, "X", 1, -4.0),
    ("cauda_1", 10.0, 0.0, "Z", 1, 0.0),
    ("cauda_2", 14.0, 0.15, "Z", 1, 0.0),
    ("cauda_3", 18.0, 0.30, "Z", 1, 0.0),
    ("pata_dianteira_e", 42.0, 0.0, "X", 1, 4.0),
    ("canela_dianteira_e", 28.0, 0.75, "X", 1, -32.0),
    ("pata_dianteira_d", 42.0, 0.08, "X", 1, 4.0),
    ("canela_dianteira_d", 28.0, 0.83, "X", 1, -32.0),
    ("pata_traseira_e", 44.0, 0.50, "X", 1, -4.0),
    ("canela_traseira_e", 28.0, 0.25, "X", 1, -30.0),
    ("pata_traseira_d", 44.0, 0.58, "X", 1, -4.0),
    ("canela_traseira_d", 28.0, 0.33, "X", 1, -30.0),
    ("asa_ombro_e", 5.0, 0.2, "Z", 1, -12.0),
    ("asa_ombro_d", -5.0, 0.2, "Z", 1, 12.0),
)

_MOTORES_CRIATURA_WING_FLAP = (
    ("quadril", 4.0, 0.5, "X", 1, 0.0),
    ("tronco", 5.5, 0.5, "X", 1, 0.0),
    ("pescoco", 4.0, 0.0, "X", 1, 0.0),
    ("cabeca", 3.5, 0.0, "X", 1, 0.0),
    ("cauda_1", 9.0, 0.0, "X", 1, 0.0),
    ("cauda_2", 12.0, 0.15, "X", 1, 0.0),
    ("cauda_3", 16.0, 0.30, "X", 1, 0.0),
    ("asa_ombro_e", 34.0, 0.0, "Z", 1, -4.0),
    ("asa_ombro_d", -34.0, 0.0, "Z", 1, 4.0),
    ("asa_braco_e", 30.0, 0.12, "Z", 1, 6.0),
    ("asa_braco_d", -30.0, 0.12, "Z", 1, -6.0),
    ("asa_antebraco_e", 26.0, 0.24, "Z", 1, 8.0),
    ("asa_antebraco_d", -26.0, 0.24, "Z", 1, -8.0),
    ("asa_ponta_e", 22.0, 0.36, "Z", 1, 6.0),
    ("asa_ponta_d", -22.0, 0.36, "Z", 1, -6.0),
    ("pata_traseira_e", 3.0, 0.5, "X", 1, -24.0),
    ("pata_traseira_d", 3.0, 0.5, "X", 1, -24.0),
)

_MOTORES_CRIATURA_GLIDE = (
    ("quadril", 1.5, 0.0, "Z", 1, 0.0),
    ("tronco", 1.5, 0.25, "Z", 1, 0.0),
    ("pescoco", 1.2, 0.0, "X", 1, 4.0),
    ("cabeca", 1.0, 0.5, "X", 1, -4.0),
    ("cauda_1", 7.5, 0.0, "Z", 1, 0.0),
    ("cauda_2", 11.0, 0.16, "Z", 1, 0.0),
    ("cauda_3", 15.0, 0.32, "Z", 1, 0.0),
    ("asa_ombro_e", 4.5, 0.0, "Z", 1, -6.0),
    ("asa_ombro_d", -4.5, 0.0, "Z", 1, 6.0),
    ("asa_braco_e", 3.5, 0.12, "Z", 1, 2.0),
    ("asa_braco_d", -3.5, 0.12, "Z", 1, -2.0),
    ("asa_ponta_e", 4.0, 0.25, "Z", 1, 4.0),
    ("asa_ponta_d", -4.0, 0.25, "Z", 1, -4.0),
    ("pata_traseira_e", 2.0, 0.0, "X", 1, -30.0),
    ("pata_traseira_d", 2.0, 0.0, "X", 1, -30.0),
)

_MOTORES_CRIATURA_BITE = (
    ("quadril", "X", (0.0, -6.0, -8.0, 8.0, 10.0, 6.0, 2.0, 0.0, 0.0)),
    ("coluna", "X", (0.0, -10.0, -14.0, 12.0, 16.0, 10.0, 4.0, 1.0, 0.0)),
    ("tronco", "X", (0.0, -12.0, -16.0, 14.0, 18.0, 12.0, 5.0, 1.5, 0.0)),
    ("pescoco", "X", (0.0, 16.0, 22.0, -18.0, -24.0, -12.0, -5.0, -2.0, 0.0)),
    ("cabeca", "X", (0.0, 10.0, 16.0, -12.0, -14.0, -6.0, -2.0, 0.0, 0.0)),
    ("mandibula", "X", (0.0, -12.0, -34.0, -38.0, 4.0, -6.0, -2.0, 0.0, 0.0)),
    ("cauda_1", "Z", (0.0, -8.0, -12.0, 14.0, 16.0, 10.0, 4.0, 1.0, 0.0)),
    ("cauda_2", "Z", (0.0, -10.0, -16.0, 18.0, 20.0, 12.0, 5.0, 2.0, 0.0)),
)

_MOTORES_CRIATURA_ROAR = (
    ("quadril", "X", (0.0, -12.0, -18.0, -20.0, -18.0, -14.0, -8.0, -3.0, 0.0)),
    ("coluna", "X", (0.0, 14.0, 22.0, 24.0, 22.0, 16.0, 10.0, 4.0, 0.0)),
    ("tronco", "X", (0.0, 18.0, 28.0, 30.0, 28.0, 20.0, 12.0, 5.0, 0.0)),
    ("pescoco", "X", (0.0, 12.0, 22.0, 26.0, 24.0, 18.0, 10.0, 4.0, 0.0)),
    ("cabeca", "X", (0.0, 10.0, 18.0, 22.0, 20.0, 14.0, 8.0, 3.0, 0.0)),
    ("mandibula", "X", (0.0, -18.0, -40.0, -44.0, -40.0, -28.0, -12.0, -4.0, 0.0)),
    ("asa_ombro_e", "Z", (0.0, -14.0, -26.0, -30.0, -28.0, -20.0, -10.0, -4.0, 0.0)),
    ("asa_ombro_d", "Z", (0.0, 14.0, 26.0, 30.0, 28.0, 20.0, 10.0, 4.0, 0.0)),
    ("cauda_1", "Z", (0.0, 8.0, -12.0, 14.0, -12.0, 8.0, -4.0, 2.0, 0.0)),
)

_MOTORES_CRIATURA_DEATH = (
    ("quadril", "Z", (0.0, 8.0, 22.0, 48.0, 72.0, 82.0, 85.0, 85.0, 85.0)),
    ("coluna", "Z", (0.0, 6.0, 12.0, 18.0, 22.0, 24.0, 24.0, 24.0, 24.0)),
    ("tronco", "X", (0.0, -8.0, -14.0, -18.0, -22.0, -24.0, -24.0, -24.0, -24.0)),
    ("pescoco", "X", (0.0, -10.0, -18.0, -26.0, -32.0, -35.0, -36.0, -36.0, -36.0)),
    ("cabeca", "X", (0.0, 8.0, 10.0, -6.0, -14.0, -18.0, -18.0, -18.0, -18.0)),
    ("mandibula", "X", (0.0, -6.0, -12.0, -18.0, -20.0, -20.0, -20.0, -20.0, -20.0)),
    ("pata_dianteira_e", "X", (0.0, -18.0, -35.0, -45.0, -52.0, -55.0, -55.0, -55.0, -55.0)),
    ("pata_dianteira_d", "X", (0.0, -12.0, -25.0, -36.0, -44.0, -48.0, -48.0, -48.0, -48.0)),
    ("pata_traseira_e", "X", (0.0, 16.0, 28.0, 36.0, 40.0, 42.0, 42.0, 42.0, 42.0)),
    ("pata_traseira_d", "X", (0.0, 12.0, 22.0, 30.0, 34.0, 36.0, 36.0, 36.0, 36.0)),
    ("asa_ombro_e", "Z", (0.0, 10.0, 22.0, 32.0, 38.0, 42.0, 42.0, 42.0, 42.0)),
    ("asa_ombro_d", "Z", (0.0, -6.0, -14.0, -20.0, -24.0, -26.0, -26.0, -26.0, -26.0)),
)

_DESLOCAMENTO_QUADRIL_Z: dict[str, tuple[float, ...]] = {
    "jump": (0.0, -0.06, 0.04, 0.28, 0.36, 0.18, -0.05, -0.08, 0.0),
    "attack": (0.0, -0.01, -0.02, 0.01, 0.0, -0.01, -0.01, 0.0, 0.0),
    "slash_combo": (0.0, -0.02, 0.01, -0.01, -0.03, 0.02, -0.04, 0.01, 0.0),
    "cast": (0.0, -0.02, -0.03, -0.02, 0.02, 0.01, -0.01, 0.0, 0.0),
    "block": (0.0, -0.03, -0.05, -0.05, -0.05, -0.05, -0.04, -0.02, 0.0),
    "hit": (0.0, -0.02, -0.04, -0.03, -0.02, -0.01, 0.0, 0.0, 0.0),
    "death": (0.0, -0.05, -0.14, -0.30, -0.52, -0.68, -0.74, -0.75, -0.75),
    "bite": (0.0, -0.02, -0.03, 0.03, 0.04, 0.02, 0.0, 0.0, 0.0),
    "roar": (0.0, 0.03, 0.06, 0.08, 0.07, 0.04, 0.02, 0.01, 0.0),
}


_DESLOCAMENTO_QUADRIL_Z_CRIATURA: dict[str, tuple[float, ...]] = {
    "bite": (0.0, -0.02, -0.03, 0.03, 0.04, 0.02, 0.0, 0.0, 0.0),
    "roar": (0.0, 0.03, 0.06, 0.08, 0.07, 0.04, 0.02, 0.01, 0.0),
    "death": (0.0, -0.04, -0.10, -0.20, -0.32, -0.40, -0.42, -0.42, -0.42),
}


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
    p0 = pts[max(0, idx - 1)]
    p1 = pts[idx]
    p2 = pts[idx + 1]
    p3 = pts[min(n - 1, idx + 2)]
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
            pose: dict[str, object] = {
                "osso": osso,
                "graus": round(graus, 6),
                "eixo": eixo,
            }
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


_DEFINICOES_HUMANO = {
    "idle": ("harmonica", SEGUNDOS_IDLE, 24, MOTORES_IDLE, 0.004, 0.0, 0.0, 0.5),
    "walk": ("harmonica", SEGUNDOS_WALK, 24, MOTORES_WALK, 0.025, 0.0, 0.012, 1.0),
    "run": ("harmonica", SEGUNDOS_RUN, 20, MOTORES_RUN, 0.045, -0.02, 0.018, 1.0),
    "ride_idle": ("harmonica", SEGUNDOS_RIDE_IDLE, 24, MOTORES_RIDE_IDLE, 0.008, -0.22, 0.008, 0.5),
    "ride_fly": ("harmonica", SEGUNDOS_RIDE_FLY, 24, MOTORES_RIDE_FLY, 0.028, -0.22, 0.014, 0.5),
    "jump": ("balistica", SEGUNDOS_JUMP, 20, MOTORES_JUMP, 0.0, 0.0, 0.0, 1.0),
    "attack": ("balistica", SEGUNDOS_ATTACK, 20, MOTORES_ATTACK, 0.0, 0.0, 0.0, 1.0),
    "slash_combo": ("balistica", SEGUNDOS_SLASH_COMBO, 24, MOTORES_SLASH_COMBO, 0.0, 0.0, 0.0, 1.0),
    "cast": ("balistica", SEGUNDOS_CAST, 30, MOTORES_CAST, 0.0, 0.0, 0.0, 1.0),
    "block": ("balistica", SEGUNDOS_BLOCK, 24, MOTORES_BLOCK, 0.0, 0.0, 0.0, 1.0),
    "hit": ("balistica", SEGUNDOS_HIT, 16, MOTORES_HIT, 0.0, 0.0, 0.0, 1.0),
    "death": ("balistica", SEGUNDOS_DEATH, 24, MOTORES_DEATH, 0.0, 0.0, 0.0, 1.0),
}

_DEFINICOES_CRIATURA = {
    "idle": ("harmonica", SEGUNDOS_IDLE, 24, _MOTORES_CRIATURA_IDLE, 0.006, 0.0, 0.0, 0.5),
    "walk": ("harmonica", SEGUNDOS_WALK, 24, _MOTORES_CRIATURA_WALK, 0.025, 0.0, 0.012, 1.0),
    "gallop": ("harmonica", SEGUNDOS_GALLOP, 20, _MOTORES_CRIATURA_GALLOP, 0.060, 0.0, 0.010, 0.5),
    "wing_flap": ("harmonica", SEGUNDOS_WING_FLAP, 24, _MOTORES_CRIATURA_WING_FLAP, 0.055, 0.02, 0.0, 0.5),
    "glide": ("harmonica", SEGUNDOS_GLIDE, 24, _MOTORES_CRIATURA_GLIDE, 0.015, 0.0, 0.010, 0.5),
    "bite": ("balistica", SEGUNDOS_BITE, 20, _MOTORES_CRIATURA_BITE, 0.0, 0.0, 0.0, 1.0),
    "roar": ("balistica", SEGUNDOS_ROAR, 24, _MOTORES_CRIATURA_ROAR, 0.0, 0.0, 0.0, 1.0),
    "death": ("balistica", SEGUNDOS_DEATH, 24, _MOTORES_CRIATURA_DEATH, 0.0, -0.42, 0.0, 1.0),
}


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


def clipes(perfil: dict, esqueleto: str, pedidos: list[str] | None) -> list[dict]:
    """Materializa os clipes pedidos para um esqueleto (humanoide, quadruped@1 ou winged_mount@1).

    Devolve ``[]`` quando nao ha pedido, quando o clipe nao tem gerador ou quando o perfil nao
    declara retarget para o esqueleto (o chamador avisa; ver ``FORGE-W-ANIM``).
    """
    pedidos_list = [str(p) for p in (pedidos or [])]
    if not pedidos_list:
        return []
    mapa_base = profiles.retarget(perfil, esqueleto)
    if not mapa_base and not any(p in _CLIPES_EXCLUSIVOS_CRIATURA for p in pedidos_list):
        return []

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
        total = int(round(segundos * FPS))
        fracoes = _fracoes_24fps(total, n_segs)
        if modo == "balistica":
            bob_z = (
                _DESLOCAMENTO_QUADRIL_Z_CRIATURA.get(nome)
                if eh_criatura
                else _DESLOCAMENTO_QUADRIL_Z.get(nome)
            )
            chaves = _chaves_balisticas(
                mapa,
                motores,
                fracoes,
                total,
                bob_z=bob_z,
            )
        else:
            chaves = _chaves_harmonicas(
                mapa,
                motores,
                fracoes,
                total,
                bob_amp_z=bob_amp,
                bob_offset_z=bob_off,
                lat_amp_x=lat_amp,
                ciclos_bounce=cyc_b,
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
