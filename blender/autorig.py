"""Auto-rigging orgânico e animações multi-clipe para Blender 4.2 (Fase B).

Usa **apenas** ``bpy``, ``bmesh``, ``mathutils`` e stdlib (sem Pillow, sem numpy).
Convenção canônica da malha: +Z para cima, base em Z=0, frente +Y, X centrado em 0,
lado esquerdo (``.L`` / ``Left*``) em ``-X`` e lado direito (``.R`` / ``Right*``) em ``+X``
(idêntico a ``blocky.OSSOS_HUMANOIDE`` e ``blocky.OSSOS_R15``).
"""

from __future__ import annotations

import os
import sys

import bpy  # noqa: F401 - necessario para contrato de tipagem/monkeypatch

if __package__:
    from . import autorig_anim_sockets as _as
    from . import autorig_const as _c
    from . import autorig_criaturas as _cr
    from . import autorig_grafo as _gr
    from . import autorig_marcos as _mk
    from . import autorig_ossos as _os
    from . import autorig_pesos_aa as _pa
    from . import autorig_pesos_geo as _pg
    from . import autorig_pose_natural as _pn
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import autorig_anim_sockets as _as
    import autorig_const as _c
    import autorig_criaturas as _cr
    import autorig_grafo as _gr
    import autorig_marcos as _mk
    import autorig_ossos as _os
    import autorig_pesos_aa as _pa
    import autorig_pesos_geo as _pg
    import autorig_pose_natural as _pn

__all__ = [
    "ESQUELETOS_SUPORTADOS",
    "OSSOS_GODOT_HUMANOID_AA",
    "auto_rigar_humanoide",
    "auto_rigar_por_tipo",
    "extrair_sockets",
    "extrair_ancoras",
    "aplicar_animacoes_multi",
    "estimar_marcos",
    "assar_pose_rest_natural",
    "resolver_postura_perfil",
    "microvariacao_postura_seed",
]

ESQUELETOS_SUPORTADOS = _c.ESQUELETOS_SUPORTADOS
_ESQUELETOS_HUMANOS = _c._ESQUELETOS_HUMANOS
_ESQUELETOS_CRIATURA = _c._ESQUELETOS_CRIATURA
_DEDOS_NOMES = _c._DEDOS_NOMES
_OSSOS_DEDOS_L = _c._OSSOS_DEDOS_L
_OSSOS_DEDOS_R = _c._OSSOS_DEDOS_R
_OSSOS_DEDOS = _c._OSSOS_DEDOS
_OSSOS_FACE_AA = _c._OSSOS_FACE_AA
_OSSOS_CAPA_AA = _c._OSSOS_CAPA_AA
_OSSOS_AA_EXTRAS = _c._OSSOS_AA_EXTRAS
OSSOS_GODOT_HUMANOID_AA = _c.OSSOS_GODOT_HUMANOID_AA
_RAIZES = _c._RAIZES
_OSSOS_ASA = _c._OSSOS_ASA
_OSSOS_PATA = _c._OSSOS_PATA
_OSSOS_CAUDA = _c._OSSOS_CAUDA
_OSSOS_PERNA = _c._OSSOS_PERNA
_OSSOS_OMBROS = _c._OSSOS_OMBROS
_OSSOS_BRACO = _c._OSSOS_BRACO
_OSSOS_BRACO_DISTAL = _c._OSSOS_BRACO_DISTAL
_OSSOS_CABECA = _c._OSSOS_CABECA
_OSSOS_PESCOCO = _c._OSSOS_PESCOCO
_OSSOS_TORAX = _c._OSSOS_TORAX
_OSSOS_TRONCO = _c._OSSOS_TRONCO
_OSSOS_COXA = _c._OSSOS_COXA
_OSSOS_CANELA = _c._OSSOS_CANELA
_OSSOS_PE = _c._OSSOS_PE
_MAT_BL_PARA_GLTF_LINHAS = _c._MAT_BL_PARA_GLTF_LINHAS
_SOCKETS_MAPA = _c._SOCKETS_MAPA
_SOCKETS_ALIASES_PARTE = _c._SOCKETS_ALIASES_PARTE
_ALIAS_OSSO_CRIATURA = _c._ALIAS_OSSO_CRIATURA

_selecionar_unico = _c._selecionar_unico
_aplicar_identidade = _c._aplicar_identidade
_garantir_modificador_armature = _c._garantir_modificador_armature
_clamped = _c._clamped
_mediana = _c._mediana
_centroide = _c._centroide
_dist_ponto_segmento = _c._dist_ponto_segmento
_lado_osso = _c._lado_osso

_estimar_lado_braco = _mk._estimar_lado_braco
_torso_meia_largura = _mk._torso_meia_largura
estimar_marcos = _mk.estimar_marcos

_osso = _os._osso
_quadro_mao = _os._quadro_mao
_ossos_dedos_mao = _os._ossos_dedos_mao
_construir_ossos = _os._construir_ossos
_alinhar_roll_ossos = _os._alinhar_roll_ossos

_limites_anatomicos = _gr._limites_anatomicos
_osso_permitido = _gr._osso_permitido
_osso_permitido_semente = _gr._osso_permitido_semente
_ilhas_vertices = _gr._ilhas_vertices
_grafo_superficie = _gr._grafo_superficie
_projecao_segmento = _gr._projecao_segmento
_dijkstra_osso = _gr._dijkstra_osso
_normalizar_top4 = _gr._normalizar_top4
_pesos_vertice_inverso = _gr._pesos_vertice_inverso
_normalizar_grupos_e_mapear = _gr._normalizar_grupos_e_mapear
_suavizar_aneis_juntas = _gr._suavizar_aneis_juntas

_sementes_osso_ilha = _pg._sementes_osso_ilha
_pesos_ilha_geodesicos = _pg._pesos_ilha_geodesicos

_osso_acessorio_ilha = _pa._osso_acessorio_ilha
_refinar_pesos_aa_56 = _pa._refinar_pesos_aa_56
_atribuir_pesos_inverso = _pa._atribuir_pesos_inverso

_alinhar_orientacao_criatura = _cr._alinhar_orientacao_criatura
_estimar_marcos_criatura = _cr._estimar_marcos_criatura
_construir_ossos_criatura = _cr._construir_ossos_criatura
_atribuir_pesos_criatura = _cr._atribuir_pesos_criatura

extrair_sockets = _as.extrair_sockets
extrair_ancoras = _as.extrair_ancoras
aplicar_animacoes_multi = _as.aplicar_animacoes_multi
assar_pose_rest_natural = _pn.assar_pose_rest_natural
resolver_postura_perfil = _pn.resolver_postura_perfil
microvariacao_postura_seed = _pn.microvariacao_postura_seed


def auto_rigar_humanoide(obj, esqueleto: str, criar_armadura_fn) -> tuple["bpy.types.Object", dict]:
    """Cria armadura humanoide ajustada à malha e aplica skinning geodésico topológico."""
    if esqueleto not in _ESQUELETOS_HUMANOS:
        raise ValueError(f"esqueleto nao suportado: {esqueleto}")
    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        raise RuntimeError("objeto invalido para auto-rigging")

    obj.vertex_groups.clear()
    for mod in list(obj.modifiers):
        if mod.type == "ARMATURE":
            obj.modifiers.remove(mod)
    _aplicar_identidade(obj)

    marcos = estimar_marcos(obj)
    ossos = _construir_ossos(esqueleto, marcos)
    rig_obj = criar_armadura_fn(ossos)
    _alinhar_roll_ossos(rig_obj)
    _aplicar_identidade(rig_obj)

    _atribuir_pesos_inverso(obj, ossos, marcos)
    _garantir_modificador_armature(obj, rig_obj)
    grupos = _normalizar_grupos_e_mapear(obj)
    return rig_obj, grupos


def auto_rigar_por_tipo(
    obj,
    esqueleto_spec: str | None,
    criar_armadura_fn,
    tipo: str | None = None,
) -> tuple["bpy.types.Object", dict]:
    """Despacha auto-rig para humanoide, quadrupede ou montaria alada conforme tipo/esqueleto."""
    esq = str(esqueleto_spec or "").strip()
    tipo_norm = str(tipo or "").strip().lower()

    if esq in _ESQUELETOS_HUMANOS:
        # D-02: esqueleto explicito humanoide vence o tipo (mob bipede com tipo "criatura").
        return auto_rigar_humanoide(obj, esq, criar_armadura_fn)

    if esq in _ESQUELETOS_CRIATURA:
        alvo_esq = esq
    elif tipo_norm == "criatura_alada":
        alvo_esq = "winged_mount@1"
    elif tipo_norm in ("criatura_quadrupede", "criatura"):
        alvo_esq = "quadruped@1"
    elif tipo_norm == "montaria":
        xs = [v.co.x for v in obj.data.vertices]
        ys = [v.co.y for v in obj.data.vertices]
        sx = (max(xs) - min(xs)) if xs else 0.0
        sy = (max(ys) - min(ys)) if ys else 0.0
        alvo_esq = "winged_mount@1" if sx > 1.25 * max(sy, 1e-4) else "quadruped@1"
    else:
        return auto_rigar_humanoide(obj, esq or "godot-humanoid@1", criar_armadura_fn)

    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        raise RuntimeError("objeto invalido para auto-rigging")

    obj.vertex_groups.clear()
    for mod in list(obj.modifiers):
        if mod.type == "ARMATURE":
            obj.modifiers.remove(mod)

    com_asas = alvo_esq == "winged_mount@1"
    _alinhar_orientacao_criatura(obj, com_asas=com_asas)
    marcos = _estimar_marcos_criatura(obj, com_asas=com_asas)
    ossos = _construir_ossos_criatura(alvo_esq, marcos)
    rig_obj = criar_armadura_fn(ossos)
    _alinhar_roll_ossos(rig_obj)
    _aplicar_identidade(rig_obj)

    _atribuir_pesos_criatura(obj, ossos, marcos)
    _garantir_modificador_armature(obj, rig_obj)
    grupos = _normalizar_grupos_e_mapear(obj)
    return rig_obj, grupos
