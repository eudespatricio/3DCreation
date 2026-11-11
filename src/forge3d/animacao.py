"""Clipe base procedural (D66/D69): a definição única, fora do Blender.

O clipe nasce em espaço semântico (`coluna`, `tronco`, `cabeca`, `braco_e`, `braco_d`) e o perfil
resolve o nome do osso em cada esqueleto (`rig.retarget`). A **mesma** definição alimenta o `bpy`
(clipe embutido no glb) e o `.rbxlx` (KeyframeSequence), então os dois não podem divergir — e o
clipe é determinístico (D1): senoide de 5 chaves, sem seed e sem modelo generativo.
"""

from __future__ import annotations

import math

from . import profiles

__all__ = ["FPS", "SEGUNDOS_IDLE", "MOTORES_IDLE", "clipes"]

FPS = 24
SEGUNDOS_IDLE = 2.0

#: Motores do `idle`: (osso semântico, amplitude em graus no eixo local, defasagem no ciclo).
#: O eixo local X é o de flexão do perfil (positivo = para a frente); amplitudes pequenas para
#: ler como respiração, não como pose.
MOTORES_IDLE = (
    ("coluna", 0.8, 0.0, "X"),
    ("tronco", 1.6, 0.0, "X"),
    ("cabeca", -1.2, 0.12, "X"),
    ("braco_e", 2.0, 0.25, "X"),
    ("braco_d", 2.0, 0.75, "X"),
)

#: Frações do ciclo com chave: 0, 25, 50, 75 e 100 % (a primeira e a última fecham o loop)
FRACOES = (0.0, 0.25, 0.5, 0.75, 1.0)


def clipes(perfil: dict, esqueleto: str, pedidos: list[str] | None) -> list[dict]:
    """Materializa os clipes pedidos para um esqueleto.

    Devolve ``[]`` quando não há pedido, quando o clipe não tem gerador ou quando o perfil não
    declara retarget para o esqueleto (o chamador avisa; ver `FORGE-W-ANIM`).
    """
    mapa = profiles.retarget(perfil, esqueleto)
    pedidos = [str(p) for p in (pedidos or [])]
    if not mapa or not pedidos:
        return []
    total = int(round(SEGUNDOS_IDLE * FPS))
    saida = []
    for nome in pedidos:
        if nome not in profiles.ANIMACOES_SUPORTADAS:
            continue
        chaves = []
        for fracao in FRACOES:
            poses = []
            for semantico, amplitude, defasagem, eixo in MOTORES_IDLE:
                osso = mapa.get(semantico)
                if not osso:
                    continue
                graus = amplitude * math.sin(2.0 * math.pi * (fracao + defasagem))
                poses.append({"osso": osso, "graus": round(graus, 6), "eixo": eixo})
            chaves.append(
                {
                    "frame": 1 + int(round(fracao * total)),
                    "segundos": round(fracao * total / FPS, 4),
                    "poses": poses,
                }
            )
        saida.append(
            {
                "nome": nome,
                "fps": FPS,
                "duracao_s": round(total / FPS, 3),
                "chaves": chaves,
                "ossos": sorted({p["osso"] for c in chaves for p in c["poses"]}),
            }
        )
    return saida
