"""Carregamento de partes segmentadas R15 e validacao de proporcao de bracos para QC Roblox."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ForgeError
from .qc_geom import topologia
from .qc_glb import ler_glb_bin, malha

LIMIAR_PROPORCAO_BRACO_MIN = 0.02
_PARTES_BRACO_R15 = frozenset({"LeftUpperArm", "RightUpperArm", "LeftLowerArm", "RightLowerArm"})


@dataclass
class _ParteMalha:
    nome: str
    arquivo: str
    pos: list[tuple[float, float, float]]
    tris_box: list[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ]
    ]
    wmin: tuple[float, float, float]
    wmax: tuple[float, float, float]
    fechada: bool


def _aabb_verts(
    pos: list[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    xs = [p[0] for p in pos]
    ys = [p[1] for p in pos]
    zs = [p[2] for p in pos]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _vec3_valido(val: Any) -> tuple[float, float, float] | None:
    if not isinstance(val, (list, tuple)) or len(val) != 3:
        return None
    if any(isinstance(c, bool) or not isinstance(c, (int, float)) for c in val):
        return None
    out = (float(val[0]), float(val[1]), float(val[2]))
    return out if all(math.isfinite(c) for c in out) else None


def _carregar_parte_malha(
    p: dict, pasta: Path, tol_export: float
) -> tuple[_ParteMalha | None, str | None]:
    del tol_export
    nome = str(p.get("nome") or "")
    rel = str(p.get("arquivo") or f"{nome}.glb")
    caminho = pasta / rel
    if not caminho.is_file():
        return None, f"parte_ausente:{rel}"
    try:
        gltf_p, bin_p = ler_glb_bin(caminho)
        if not (gltf_p.get("meshes") or []):
            return None, f"parte_sem_malha:{rel}"
        pos_loc, tris_loc = malha(gltf_p, bin_p)
        topo_p = topologia(gltf_p, bin_p)
    except (ForgeError, OSError, ValueError, struct.error, IndexError, KeyError, TypeError, AttributeError) as exc:
        return None, f"parte_ilegivel:{rel}:{exc}"
    if not pos_loc or not tris_loc:
        return None, f"parte_vazia:{rel}"

    lmin, lmax = _aabb_verts(pos_loc)
    diag = math.sqrt(sum((lmax[d] - lmin[d]) ** 2 for d in range(3)))
    if diag <= 1e-9:
        return None, f"parte_degenerada:{rel}"
    lcenter = ((lmin[0] + lmax[0]) * 0.5, (lmin[1] + lmax[1]) * 0.5, (lmin[2] + lmax[2]) * 0.5)
    anc_vec = _vec3_valido(p.get("ancora"))
    pivo_decl = p.get("pivo")
    if anc_vec is None:
        pivot_na_ancora = False
    elif pivo_decl in ("junta", "ancora", "local") or pivo_decl == [0.0, 0.0, 0.0]:
        pivot_na_ancora = True
    elif pivo_decl in ("mundo", "compartilhado", "global"):
        pivot_na_ancora = False
    else:
        d0_sq = sum(lcenter[d] ** 2 for d in range(3))
        da_sq = sum((lcenter[d] - anc_vec[d]) ** 2 for d in range(3))
        pivot_na_ancora = d0_sq <= da_sq + 1e-9
    if pivot_na_ancora and anc_vec is not None:
        ax, ay, az = anc_vec
        pos_w = [(v[0] + ax, v[1] + ay, v[2] + az) for v in pos_loc]
        wmin = (lmin[0] + ax, lmin[1] + ay, lmin[2] + az)
        wmax = (lmax[0] + ax, lmax[1] + ay, lmax[2] + az)
    else:
        pos_w = pos_loc
        wmin, wmax = lmin, lmax

    tris_box = []
    for i0, i1, i2 in tris_loc:
        p0, p1, p2 = pos_w[i0], pos_w[i1], pos_w[i2]
        fmin = (min(p0[0], p1[0], p2[0]), min(p0[1], p1[1], p2[1]), min(p0[2], p1[2], p2[2]))
        fmax = (max(p0[0], p1[0], p2[0]), max(p0[1], p1[1], p2[1]), max(p0[2], p1[2], p2[2]))
        tris_box.append((p0, p1, p2, fmin, fmax))

    return (
        _ParteMalha(
            nome=nome,
            arquivo=rel,
            pos=pos_w,
            tris_box=tris_box,
            wmin=wmin,
            wmax=wmax,
            fechada=int(topo_p.get("bordas_abertas", 0)) == 0,
        ),
        None,
    )


def _verificar_proporcao_partes(partes: list[dict]) -> list[str]:
    """Valida que partes de braco R15 (UpperArm/LowerArm) nao estejam famintas (>= 2% dos tris)."""
    tris_por_nome: dict[str, int] = {}
    for p in partes:
        if not isinstance(p, dict):
            continue
        nome = str(p.get("nome") or "")
        tris_raw = p.get("triangulos")
        if nome and isinstance(tris_raw, (int, float)) and not isinstance(tris_raw, bool):
            tris_por_nome[nome] = max(0, int(tris_raw))
    if not tris_por_nome:
        return []
    bracos_presentes = sorted(_PARTES_BRACO_R15 & set(tris_por_nome))
    if not bracos_presentes:
        return []
    total_tris = sum(tris_por_nome.values())
    if total_tris <= 0:
        return [f"parte_braco_faminta:{nome}:0.0000<{LIMIAR_PROPORCAO_BRACO_MIN}" for nome in bracos_presentes]
    problemas: list[str] = []
    for nome in bracos_presentes:
        frac = tris_por_nome[nome] / float(total_tris)
        if frac < LIMIAR_PROPORCAO_BRACO_MIN:
            problemas.append(f"parte_braco_faminta:{nome}:{frac:.4f}<{LIMIAR_PROPORCAO_BRACO_MIN}")
    return problemas
