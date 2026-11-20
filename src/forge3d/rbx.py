"""Fachada publica para exportacao Roblox R15, MeshPart, Accessory, SurfaceAppearance e animacoes."""

from __future__ import annotations

from .rbx_acessorio import (
    _normalizar_sockets_map,
    _resolver_socket_offset,
    _socket_pos_studs,
    exportar_acessorio_rbxmx,
)
from .rbx_anim import (
    _sequencia_xml,
    exportar_animacao,
    exportar_animacoes,
    ler_place,
)
from .rbx_meshpart import (
    exportar_manifesto_luau_pbr,
    exportar_meshpart_pbr_rbxmx,
    gerar_manifesto_luau_pbr,
    gerar_rbxmx_meshpart_pbr,
)
from .rbx_pbr import (
    _surface_appearance_xml,
    descobrir_texturas_pbr,
    exportar_surface_appearance,
    inferir_papel_textura_roblox,
    remover_imagens_embutidas_glb,
    surface_appearance_xml,
)
from .rbx_r15 import exportar_r15
from .rbx_r15_rig import _bone_tree_xml
from .rbx_xml import (
    JOINT_R15,
    JOINT_R15_REV,
    PARENT_R15,
    _attachment_xml,
    _cframe,
    _matriz_rotacao,
    _mul_mat3,
    _parte_xml,
    _roblox,
    _vec,
)

__all__ = [
    "JOINT_R15",
    "JOINT_R15_REV",
    "PARENT_R15",
    "_attachment_xml",
    "_bone_tree_xml",
    "_cframe",
    "_matriz_rotacao",
    "_mul_mat3",
    "_normalizar_sockets_map",
    "_parte_xml",
    "_resolver_socket_offset",
    "_roblox",
    "_sequencia_xml",
    "_socket_pos_studs",
    "_surface_appearance_xml",
    "_vec",
    "descobrir_texturas_pbr",
    "exportar_acessorio_rbxmx",
    "exportar_animacao",
    "exportar_animacoes",
    "exportar_manifesto_luau_pbr",
    "exportar_meshpart_pbr_rbxmx",
    "exportar_r15",
    "exportar_surface_appearance",
    "gerar_manifesto_luau_pbr",
    "gerar_rbxmx_meshpart_pbr",
    "inferir_papel_textura_roblox",
    "ler_place",
    "remover_imagens_embutidas_glb",
    "surface_appearance_xml",
]
