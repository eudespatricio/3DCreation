"""Biblioteca de 10 materiais PBR procedurais 3D Object-Space/Triplanar no Cycles (Blender 4.2+).

Gera grafos de nodos 100% 3D (sem costuras de UV na origem) usando multi-oitavas de
``ShaderNodeTexNoise``, ``ShaderNodeTexVoronoi``, ``ShaderNodeNewGeometry`` (``Pointiness``/``Normal``),
``ShaderNodeAmbientOcclusion`` e ``ShaderNodeBump``, prontos para assar em BaseColor + Normal + ORM
via ``blender/bake_pbr.py``.
"""

from __future__ import annotations

import os
import sys

try:
    import bpy  # noqa: F401
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bpy = None  # type: ignore[assignment]

if __package__:
    from . import procedural_pbr_presets as _pre
    from . import procedural_pbr_single as _sgl
    from . import procedural_pbr_zonas as _zn
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import procedural_pbr_presets as _pre
    import procedural_pbr_single as _sgl
    import procedural_pbr_zonas as _zn

MATERIAIS_PROCEDURAIS = _pre.MATERIAIS_PROCEDURAIS
PRESETS_PBR = _pre.PRESETS_PBR
_hex_para_rgba_linear = _pre._hex_para_rgba_linear
_resolver_cores_zona = _pre._resolver_cores_zona

criar_material_procedural = _sgl.criar_material_procedural
configurar_saida_albedo_emit = _sgl.configurar_saida_albedo_emit
configurar_saida_orm_hints_emit = _sgl.configurar_saida_orm_hints_emit
configurar_saida_pbr_bsdf = _sgl.configurar_saida_pbr_bsdf
construir_shader_pbr_zonas_blender = _zn.construir_shader_pbr_zonas_blender

__all__ = [
    "MATERIAIS_PROCEDURAIS",
    "PRESETS_PBR",
    "configurar_saida_albedo_emit",
    "configurar_saida_orm_hints_emit",
    "configurar_saida_pbr_bsdf",
    "construir_shader_pbr_zonas_blender",
    "criar_material_procedural",
]
