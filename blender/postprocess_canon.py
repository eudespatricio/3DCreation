"""Camada L1 de postprocess: canonicalizacao de orientacao e alinhamento de frente."""

from __future__ import annotations

import math
import os
import sys

from mathutils import Matrix, Vector

if __package__:
    from .postprocess_scene import (
        LIMIAR_SCORE_FRENTE,
        TIPOS_ORGANICOS,
        _aplicar_transformes,
        bbox_local,
    )
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from postprocess_scene import (
        LIMIAR_SCORE_FRENTE,
        TIPOS_ORGANICOS,
        _aplicar_transformes,
        bbox_local,
    )


def _extensao_faixa(obj, z0: float, z1: float) -> float:
    """Area da faixa horizontal [z0,z1] no plano XY: cabeca fina vs base larga."""
    xs: list[float] = []
    ys: list[float] = []
    for v in obj.data.vertices:
        co = obj.matrix_world @ v.co
        if z0 <= co.z <= z1:
            xs.append(co.x)
            ys.append(co.y)
    if not xs:
        return 0.0
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def canonicalizar(obj, tipo: str | None = None) -> dict:
    """Altura em Z, largura em X, profundidade em Y, base em Z=0 (tools/normalize_mesh.py)."""
    minimo, maximo = bbox_local()
    extensao = maximo - minimo
    ordem = sorted(range(3), key=lambda i: extensao[i])
    profundidade = ordem[0]
    quadrupede = (
        tipo in ("criatura", "criatura_quadrupede", "montaria")
        and extensao[2] >= 0.30 * max(extensao)
        and max(extensao[0], extensao[1]) > 1.15 * extensao[2]
    )
    criatura_alada = (
        tipo == "criatura_alada"
        and extensao[2] >= 0.30 * max(extensao)
    )
    if quadrupede:
        altura = 2
        profundidade = max((0, 1), key=lambda i: extensao[i])
        largura = 1 - profundidade
    elif criatura_alada:
        altura = 2
        largura, profundidade = 0, 1
    elif (
        tipo in TIPOS_ORGANICOS
        and profundidade == 1
        and extensao[2] >= 0.55 * extensao[0]
    ):
        altura, largura = 2, 0
    else:
        largura, altura = ordem[1], ordem[2]
    destinos = (largura, profundidade, altura)
    linhas = []
    for origem in destinos:
        linha = [0.0, 0.0, 0.0]
        linha[origem] = 1.0
        linhas.append(linha)
    if Matrix(linhas).determinant() < 0:
        # permutacao impar espelharia a malha (logo/texto invertido)
        linhas[1] = [-v for v in linhas[1]]
    rot = Matrix(linhas).to_4x4()
    obj.matrix_world = rot @ obj.matrix_world
    _aplicar_transformes(obj)
    minimo, maximo = bbox_local()
    desloc = Vector(
        (-(minimo.x + maximo.x) / 2.0, -(minimo.y + maximo.y) / 2.0, -minimo.z)
    )
    obj.matrix_world = Matrix.Translation(desloc) @ obj.matrix_world
    _aplicar_transformes(obj)

    info = {
        "altura_eixo": "XYZ"[altura],
        "largura_eixo": "XYZ"[largura],
        "profundidade_eixo": "XYZ"[profundidade],
    }
    if quadrupede:
        info["invertido"] = False
        info["girado_frente"] = False
        info["quadrupede"] = True
        return info
    if tipo in ("personagem_humanoide", "criatura"):
        minimo, maximo = bbox_local()
        altura_z = maximo.z - minimo.z
        n = 12
        areas = []
        for i in range(n):
            z0 = minimo.z + altura_z * i / n
            z1 = minimo.z + altura_z * (i + 1) / n
            areas.append(_extensao_faixa(obj, z0, z1))
        total = sum(areas)
        centro = (
            sum(a * (i + 0.5) for i, a in enumerate(areas)) / total if total else 0.0
        )
        info["centro_area"] = round(centro, 3)
        info["areas"] = [round(a, 6) for a in areas]
        razao_ends = (areas[-1] / areas[0]) if areas and areas[0] > 0 else 0.0
        info["razao_topo_base"] = round(razao_ends, 3)
        fatia = max(altura_z * 0.02, 1e-6)
        area_base_fina = _extensao_faixa(obj, minimo.z, minimo.z + fatia)
        area_topo_fina = _extensao_faixa(obj, maximo.z - fatia, maximo.z)
        invertido_contato = area_base_fina > 0 and area_topo_fina > 3.0 * area_base_fina
        upright_contato = area_topo_fina > 0 and area_base_fina > 3.0 * area_topo_fina
        info["contato_base"] = round(area_base_fina, 6)
        info["contato_topo"] = round(area_topo_fina, 6)
        info["invertido_contato"] = invertido_contato
        deve_inverter = invertido_contato or (
            not upright_contato
            and (razao_ends > 1.5 or (centro < n * 0.48 and razao_ends >= 0.5))
        )
        if total > 0 and deve_inverter:
            # rotacao pura 180 deg em X (det=+1): preserva lateralidade e winding sem espelhar
            obj.matrix_world = Matrix.Rotation(math.pi, 4, "X") @ obj.matrix_world
            _aplicar_transformes(obj)
            minimo, maximo = bbox_local()
            desloc = Vector(
                (-(minimo.x + maximo.x) / 2.0, -(minimo.y + maximo.y) / 2.0, -minimo.z)
            )
            obj.matrix_world = Matrix.Translation(desloc) @ obj.matrix_world
            _aplicar_transformes(obj)
            info["invertido"] = True
        else:
            info["invertido"] = False

        alinh = _alinhar_frente_humanoide(obj)
        info.update(alinh)
    return info


def _medir_score_frente_humanoide(obj) -> float | None:
    """Metrica identica ao qc._g2_orientacao: (pes - canelas) em Y local / altura_z."""
    zs = [v.co.z for v in obj.data.vertices]
    if not zs:
        return None
    z_min, z_max = min(zs), max(zs)
    altura_z = z_max - z_min
    if altura_z <= 1e-6:
        return None
    pes_ys = [v.co.y for v in obj.data.vertices if v.co.z <= z_min + 0.06 * altura_z]
    canela_ys = [
        v.co.y
        for v in obj.data.vertices
        if z_min + 0.12 * altura_z <= v.co.z <= z_min + 0.30 * altura_z
    ]
    if not pes_ys or not canela_ys:
        return None
    pes_mean = sum(pes_ys) / len(pes_ys)
    pes_mid = 0.5 * (min(pes_ys) + max(pes_ys))
    can_mean = sum(canela_ys) / len(canela_ys)
    can_mid = 0.5 * (min(canela_ys) + max(canela_ys))
    return 0.5 * ((pes_mean - can_mean) + (pes_mid - can_mid)) / altura_z


def _alinhar_frente_humanoide(obj, limiar: float = LIMIAR_SCORE_FRENTE) -> dict:
    """Gira 180 em Z quando score_frente < -limiar (mesmo limiar do G2) e recentra a base."""
    score_frente = _medir_score_frente_humanoide(obj)
    info: dict = {}
    if score_frente is not None:
        info["score_frente"] = round(score_frente, 5)
    girado_frente = False
    if score_frente is not None and score_frente < -limiar:
        obj.matrix_world = Matrix.Rotation(math.pi, 4, "Z") @ obj.matrix_world
        _aplicar_transformes(obj)
        xs = [v.co.x for v in obj.data.vertices]
        ys = [v.co.y for v in obj.data.vertices]
        zs = [v.co.z for v in obj.data.vertices]
        desloc = Vector((-(min(xs) + max(xs)) / 2.0, -(min(ys) + max(ys)) / 2.0, -min(zs)))
        obj.matrix_world = Matrix.Translation(desloc) @ obj.matrix_world
        _aplicar_transformes(obj)
        girado_frente = True
    info["girado_frente"] = girado_frente
    return info
