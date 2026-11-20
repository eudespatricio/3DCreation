"""QC — portao duro entre "gerou" e "entrou no jogo" (D9, I5).

Fachada modular que reexporta todas as funcoes e constantes de QC mantendo ``<=500L`` por modulo.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import ForgeError, erro_qc
from .qc_cena import _vram_mapa_mb, verificar_g11_orcamento_cena
from .qc_fidelidade import avaliar_fidelidade_concept_3d
from .qc_gates import (
    _avaliar_g1,
    _avaliar_g2,
    _avaliar_g3,
    _avaliar_g4,
    _avaliar_g5,
)
from .qc_gates_ext import (
    _avaliar_g6,
    _avaliar_g7,
    _avaliar_g8,
    _avaliar_g9,
    _avaliar_g10,
    _avaliar_g15,
)
from .qc_geom import _componentes, _convexo, convexidade, topologia
from .qc_glb import (
    _accessor,
    _aplicar_mat4,
    _mat4_de_no,
    _mat4_det3,
    _mat4_identidade,
    _mat4_mul,
    _matrizes_mundo_nos,
    analisar,
    ler_glb,
    ler_glb_bin,
    malha,
)
from .qc_midia import (
    _CLIPES_CICLICOS,
    PAPEIS_TEXTURA,
    _dimensoes_bytes_imagem,
    _imagens_embutidas,
    _png_dimensoes,
    _pot,
    _silhueta_iou_lod,
    _skin_status,
    _uv_status,
    _validar_bytes_imagem,
    animacoes,
)
from .qc_orientacao import (
    _TIPOS_ORGANICOS,
    LIMIAR_SCORE_FRENTE,
    _desvio_pivo,
    _g2_orientacao,
    _inspecionar_facetamento_organico,
    _vec3_cross,
    _vec3_dot,
    _vec3_norm,
)
from .qc_roblox import (
    LIMIAR_AMPLITUDE_G14_GRAUS,
    LIMIAR_ANCORA_MM,
    LIMIAR_SEPARACAO_MM,
    verificar_g12_separacao,
    verificar_g13_ancoras,
    verificar_g14_animacao_roblox,
    verificar_gates_roblox,
)

__all__ = [
    "ler_glb",
    "ler_glb_bin",
    "analisar",
    "malha",
    "topologia",
    "convexidade",
    "animacoes",
    "escala_do_perfil",
    "avaliar_fidelidade_concept_3d",
    "verificar",
    "verificar_g11_orcamento_cena",
    "verificar_g12_separacao",
    "verificar_g13_ancoras",
    "verificar_g14_animacao_roblox",
    "GATES",
    "PAPEIS_TEXTURA",
    "LIMIAR_SCORE_FRENTE",
    "LIMIAR_SEPARACAO_MM",
    "LIMIAR_ANCORA_MM",
    "LIMIAR_AMPLITUDE_G14_GRAUS",
]

GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11", "G12", "G13", "G14", "G15")

# Reexportacoes de helpers internos testados diretamente em suites de unidade.
_REEXPORTS = (
    _CLIPES_CICLICOS,
    _TIPOS_ORGANICOS,
    _accessor,
    _aplicar_mat4,
    _componentes,
    _convexo,
    _desvio_pivo,
    _dimensoes_bytes_imagem,
    _g2_orientacao,
    _imagens_embutidas,
    _inspecionar_facetamento_organico,
    _mat4_de_no,
    _mat4_det3,
    _mat4_identidade,
    _mat4_mul,
    _matrizes_mundo_nos,
    _png_dimensoes,
    _pot,
    _silhueta_iou_lod,
    _skin_status,
    _uv_status,
    _validar_bytes_imagem,
    _vec3_cross,
    _vec3_dot,
    _vec3_norm,
    _vram_mapa_mb,
)


def escala_do_perfil(perfil: dict) -> float:
    """Fator entre metro e unidade do arquivo exportado (D62). Perfil sem o campo = 1.0."""
    valor = float((perfil.get("unidades") or {}).get("escala_saida", 1.0))
    if valor <= 0:
        raise erro_qc(f"perfil com escala_saida invalida: {valor}")
    return valor


def _gate_falha(gid: str, erro: str) -> dict[str, Any]:
    return {"id": gid, "status": "falhou", "medido": {"erro": erro}, "codigo": "FORGE-E-QC"}


def _rodar_gate(gid: str, fn: Callable[..., dict], *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except (ForgeError, OverflowError, struct.error, ValueError) as exc:
        return _gate_falha(gid, str(exc))


def verificar(
    item: dict,
    perfil: dict,
    pasta: Path,
    resultado: dict,
    *,
    escala_saida: float | None = None,
    exigir_tangent_normal: bool = True,
    exigir_orientacao: bool = True,
) -> dict:
    """Roda G1-G10 e G12-G15 sobre o artefato. Devolve relatorio; nao levanta."""
    v = perfil["validacao"]
    medidas = resultado.get("medidas", {})
    arquivos = resultado.get("arquivos", [])
    escala = float(escala_saida) if escala_saida is not None else escala_do_perfil(perfil)
    if escala <= 0:
        raise erro_qc(f"escala_saida invalida: {escala}")

    arq_malha = next((a for a in arquivos if a["papel"] == "mesh"), None)
    if arq_malha is None:
        raise erro_qc("nenhum arquivo de malha no resultado do pos-processo", id=item["id"])

    try:
        gltf, binario = ler_glb_bin(pasta / arq_malha["caminho"])
    except (ForgeError, OSError, OverflowError, struct.error, ValueError) as exc:
        return {
            "aprovado": False,
            "gates": [_gate_falha("G1", str(exc))],
            "codigo": "FORGE-E-QC",
            "medidas": {
                "triangulos": 0,
                "vertices": 0,
                "bbox_m": [0.0, 0.0, 0.0],
                "escala_saida": escala,
                "materiais": 0,
                "primitivas": 0,
                "ossos": 0,
                "animacoes": [],
                "partes_colisao": int(medidas.get("partes_colisao", 0)),
                "tangentes": False,
                "uv_lightmap": False,
            },
        }
    info = analisar(gltf, binario)
    erros_gltf = list(info.get("erros") or ())
    sock_res = resultado.get("sockets") if "sockets" in resultado else medidas.get("sockets")
    if sock_res is None:
        cand_sock_item = item.get("sockets_manifest") or item.get("sockets")
        if isinstance(cand_sock_item, dict) or (
            isinstance(cand_sock_item, list)
            and cand_sock_item
            and not isinstance(cand_sock_item[0], str)
        ):
            sock_res = cand_sock_item
    info["_sockets"] = sock_res

    tags_item = [str(t) for t in (item.get("tags") or [])]
    eh_blocky = (
        item.get("rota") == "blocky"
        or item.get("estilo") == "blocky_voxel"
        or "blocky_voxel" in tags_item
    )
    checar_facetamento = (
        exigir_orientacao
        and str(item.get("tipo") or "") in _TIPOS_ORGANICOS
        and not eh_blocky
        and info["triangulos"] >= 200
        and bool(gltf.get("meshes"))
    )
    fac_info = {
        "arestas_suaves": 0,
        "arestas_facetadas": 0,
        "fracao_facetada": 0.0,
        "facetada": False,
    }
    if checar_facetamento:
        try:
            fac_info = _inspecionar_facetamento_organico(gltf, binario)
        except (ForgeError, IndexError, OverflowError, struct.error, ValueError) as exc:
            erros_gltf.append(f"facetamento_invalido:{exc}")
    permite_alpha_cards = bool(item.get("alpha_cards"))
    raw_anexo = item.get("anexo")
    anexo_item: dict = raw_anexo if isinstance(raw_anexo, dict) else {}

    try:
        g2_gate, _altura = _avaliar_g2(
            gltf, binario, item, perfil, info, medidas, escala, exigir_orientacao
        )
    except (ForgeError, OverflowError, struct.error, ValueError) as exc:
        g2_gate = _gate_falha("G2", str(exc))
    try:
        g10_gate, clipes = _avaliar_g10(gltf, binario, item, info, exigir_orientacao)
    except (ForgeError, OverflowError, struct.error, ValueError) as exc:
        g10_gate, clipes = _gate_falha("G10", str(exc)), []
    try:
        gates_roblox = [
            g
            for g in verificar_gates_roblox(item, perfil, pasta, resultado, escala, gltf=gltf)
            if exigir_orientacao or (g.get("medido") or {}).get("aplicavel", True)
        ]
    except (ForgeError, OverflowError, struct.error, ValueError) as exc:
        gates_roblox = [_gate_falha(gid, str(exc)) for gid in ("G12", "G13", "G14")]

    g1_gate = _rodar_gate(
        "G1",
        _avaliar_g1,
        gltf,
        binario,
        medidas,
        v,
        permite_alpha_cards,
        checar_facetamento,
        fac_info,
    )
    if erros_gltf:
        g1_gate["status"] = "falhou"
        g1_gate["codigo"] = "FORGE-E-QC"
        med_g1 = g1_gate.get("medido")
        if isinstance(med_g1, dict):
            med_g1["erros_gltf"] = erros_gltf
        else:
            g1_gate["medido"] = {"erros_gltf": erros_gltf}

    g15_gate = _rodar_gate("G15", _avaliar_g15, gltf, binario, item, perfil, info, pasta, resultado)
    gates: list[dict] = [
        g1_gate,
        g2_gate,
        _rodar_gate("G3", _avaliar_g3, gltf, binario, item, perfil, info),
        _rodar_gate("G4", _avaliar_g4, gltf, binario, item, perfil, info, pasta, arquivos),
        _rodar_gate(
            "G5",
            _avaliar_g5,
            info,
            v,
            exigir_tangent_normal,
            checar_facetamento,
            fac_info,
            item=item,
        ),
        _rodar_gate("G6", _avaliar_g6, gltf, binario, item, perfil, info, medidas, anexo_item),
        _rodar_gate("G7", _avaliar_g7, gltf, item, perfil, info, medidas, pasta, arquivos, escala),
        _rodar_gate("G8", _avaliar_g8, resultado),
        _rodar_gate("G9", _avaliar_g9, gltf, binario, item, v, info, pasta, arquivos, permite_alpha_cards),
        g10_gate,
        *gates_roblox,
        *(
            [g15_gate]
            if exigir_orientacao or (g15_gate.get("medido") or {}).get("aplicavel", True)
            else []
        ),
    ]

    limpos = []
    for g in gates:
        if g.get("codigo") is None:
            g.pop("codigo", None)
        limpos.append(g)

    aprovado = all(g["status"] != "falhou" for g in limpos)
    primeiro = next((g for g in limpos if g["status"] == "falhou"), None)
    return {
        "aprovado": aprovado,
        "gates": limpos,
        "codigo": (primeiro or {}).get("codigo") or ("FORGE-E-QC" if not aprovado else None),
        "medidas": {
            "triangulos": info["triangulos"],
            "vertices": info["vertices"],
            "bbox_m": [round(v / escala, 6) for v in info["bbox_m"]],
            "escala_saida": escala,
            "materiais": info["materiais"],
            "primitivas": info["primitivas"],
            "ossos": info["ossos"],
            "animacoes": clipes,
            "partes_colisao": int(medidas.get("partes_colisao", 0)),
            "tangentes": bool(info.get("tangentes", False)),
            "uv_lightmap": bool(info.get("uv_lightmap", False)),
        },
    }
