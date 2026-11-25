"""Portao G15b: avaliacao volumetrica e multi-angulo em Python puro + Pillow."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .errors import ForgeError
from .qc_fidelidade import _carregar_mascara_arquivo
from .qc_geom import topologia
from .qc_glb import malha

logger = logging.getLogger(__name__)

MIN_DEPTH_RATIO_G15B = 0.08
MIN_DEPTH_RATIO_SOFT_G15B = 0.12
MIN_AABB_FILL_G15B = 0.06
MIN_SHELL_SOLIDITY_G15B = 0.11
MIN_FRONT_BACK_COVERAGE_G15B = 0.55
MAX_THIN_SLICE_FRAC_G15B = 0.55
MIN_Z_FILL_G15B = 0.16
MIN_BACK_IOU_G15B = 0.40
_MARGEM_GRID = 4


def _nao_aplicavel() -> dict[str, Any]:
    return {
        "aplicavel": False,
        "aprovado": True,
        "motivos": [],
        "depth_ratio_z": 0.0,
        "aabb_fill": 0.0,
        "shell_solidity": 0.0,
        "front_cov": 0.0,
        "back_cov": 0.0,
        "thin_slice_frac": 0.0,
        "z_fill_ratio": 0.0,
        "back_iou": None,
    }


def _deve_pular(
    gltf: dict,
    pos: list[tuple[float, float, float]],
    tris: list[tuple[int, int, int]],
    item: dict,
) -> bool:
    if not pos or not tris:
        return True
    raw_asset = gltf.get("asset")
    gen = str((raw_asset.get("generator") if isinstance(raw_asset, dict) else "") or "").strip().lower()
    if len(tris) <= 48 or gen.startswith("forge3d-e2e") or gen.startswith("forge3d-test"):
        return True
    rota = str(item.get("rota") or "").strip()
    if bool(item.get("extrudir_2d")) or rota == "extrude_2d":
        return True
    if bool(item.get("alpha_cards")):
        return True
    raw_anexo = item.get("anexo")
    parte = str(
        item.get("parte") or (raw_anexo.get("parte") if isinstance(raw_anexo, dict) else "") or ""
    ).strip()
    if parte in ("arma", "escudo", "capa"):
        return True
    if str(item.get("tipo") or "").strip() in ("textura", "mapa_setor"):
        return True
    return rota == "blocky" and len(tris) <= 128


def _rasterizar_volumetria_frontal(
    pos: list[tuple[float, float, float]],
    tris: list[tuple[int, int, int]],
    dz: float,
    tamanho: int,
    margem: int = _MARGEM_GRID,
) -> tuple[float, float, float, float, float]:
    us = [-p[0] for p in pos]
    vs = [p[1] for p in pos]
    min_u, max_v = min(us), max(vs)
    bw = max(max(us) - min_u, 1e-6)
    bh = max(max_v - min(vs), 1e-6)
    escala = max(1, tamanho - 2 * margem) / max(bw, bh)
    ox = (tamanho - bw * escala) / 2.0
    oy = (tamanho - bh * escala) / 2.0
    sx_v = [ox + (u - min_u) * escala for u in us]
    sy_v = [oy + (max_v - v) * escala for v in vs]

    n_cel = tamanho * tamanho
    touched = [False] * n_cel
    z_min = [math.inf] * n_cel
    z_max = [-math.inf] * n_cel
    has_front = [False] * n_cel
    has_back = [False] * n_cel
    n_pts = len(pos)

    for a, b, c in tris:
        if a < 0 or b < 0 or c < 0 or a >= n_pts or b >= n_pts or c >= n_pts:
            continue
        pa, pb, pc = pos[a], pos[b], pos[c]
        ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
        vx, vy, vz = pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        norma = math.sqrt(nx * nx + ny * ny + nz * nz)
        if norma <= 1e-12:
            continue
        nz_u = nz / norma
        eh_front = nz_u < -0.1
        eh_back = nz_u > 0.1

        x0, y0, z0 = sx_v[a], sy_v[a], pa[2]
        x1, y1, z1 = sx_v[b], sy_v[b], pb[2]
        x2, y2, z2 = sx_v[c], sy_v[c], pc[2]
        det = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
        if abs(det) <= 1e-12:
            continue
        inv_det = 1.0 / det
        ix0 = max(0, min(tamanho - 1, int(math.floor(min(x0, x1, x2)))))
        ix1 = max(0, min(tamanho - 1, int(math.floor(max(x0, x1, x2)))))
        iy0 = max(0, min(tamanho - 1, int(math.floor(min(y0, y1, y2)))))
        iy1 = max(0, min(tamanho - 1, int(math.floor(max(y0, y1, y2)))))
        zlo, zhi = min(z0, z1, z2), max(z0, z1, z2)

        for py in range(iy0, iy1 + 1):
            cy = py + 0.5
            row = py * tamanho
            for px in range(ix0, ix1 + 1):
                cx = px + 0.5
                w0 = ((x1 - cx) * (y2 - cy) - (y1 - cy) * (x2 - cx)) * inv_det
                if w0 < -1e-6:
                    continue
                w1 = ((x2 - cx) * (y0 - cy) - (y2 - cy) * (x0 - cx)) * inv_det
                if w1 < -1e-6:
                    continue
                w2 = 1.0 - w0 - w1
                if w2 < -1e-6:
                    continue
                zp = max(zlo, min(zhi, w0 * z0 + w1 * z1 + w2 * z2))
                idx = row + px
                touched[idx] = True
                if zp < z_min[idx]:
                    z_min[idx] = zp
                if zp > z_max[idx]:
                    z_max[idx] = zp
                if eh_front:
                    has_front[idx] = True
                if eh_back:
                    has_back[idx] = True

    sil_idxs = [i for i, t in enumerate(touched) if t]
    sil_pixels = len(sil_idxs)
    denom_px = float(max(1, sil_pixels))
    dz_safe = max(dz, 1e-6)
    lim_fino = 0.05 * dz_safe
    front_cov = sum(1 for i in sil_idxs if has_front[i]) / denom_px
    back_cov = sum(1 for i in sil_idxs if has_back[i]) / denom_px
    spans = [z_max[i] - z_min[i] for i in sil_idxs]
    thin_slice_frac = sum(1 for s in spans if s < lim_fino) / denom_px
    z_fill_ratio = (sum(spans) / denom_px) / dz_safe if sil_pixels > 0 else 0.0
    sil_bbox_frac = sil_pixels / max(1.0, (bw * escala) * (bh * escala))
    return front_cov, back_cov, thin_slice_frac, z_fill_ratio, sil_bbox_frac


def _calcular_back_iou(
    pos: list[tuple[float, float, float]],
    tris: list[tuple[int, int, int]],
    concept_back: Path | None,
    tamanho: int,
    margem: int = _MARGEM_GRID,
) -> float | None:
    if concept_back is None:
        return None
    cb_path = Path(concept_back)
    if not cb_path.is_file():
        return None
    try:
        m_back = (
            _carregar_mascara_arquivo(cb_path)
            if tamanho == 64
            else _carregar_mascara_arquivo(cb_path, tamanho=tamanho)
        )
    except ForgeError as exc:
        logger.debug("concept_back ilegivel em G15b '%s': %s", cb_path, exc)
        return None

    us = [p[0] for p in pos]
    vs = [p[1] for p in pos]
    min_u, max_v = min(us), max(vs)
    bw = max(max(us) - min_u, 1e-6)
    bh = max(max_v - min(vs), 1e-6)
    escala = max(1, tamanho - 2 * margem) / max(bw, bh)
    ox = (tamanho - bw * escala) / 2.0
    oy = (tamanho - bh * escala) / 2.0
    im = Image.new("L", (tamanho, tamanho), 0)
    draw, n_pts = ImageDraw.Draw(im), len(us)
    for a, b, c in tris:
        if min(a, b, c) >= 0 and max(a, b, c) < n_pts:
            pts_2d = [(ox + (us[i] - min_u) * escala, oy + (max_v - vs[i]) * escala) for i in (a, b, c)]
            draw.polygon(pts_2d, fill=255)
    mask_glb, mask_ref = list(im.getdata()), m_back["mask"]
    inter = sum(1 for a, b in zip(mask_ref, mask_glb) if a > 0 and b > 0)
    uniao = sum(1 for a, b in zip(mask_ref, mask_glb) if a > 0 or b > 0)
    return inter / float(uniao) if uniao > 0 else 0.0


def avaliar_volumetria_glb(
    gltf: dict, binario: bytes, item: dict, info: dict, *, concept_back: Path | None = None, tamanho: int = 64
) -> dict[str, Any]:
    """Avalia volumetria 3D e cobertura frontal/traseira do GLB (G15b)."""
    pos, tris = malha(gltf, binario) if gltf.get("meshes") else ([], [])
    item_d = item if isinstance(item, dict) else {}
    if _deve_pular(gltf, pos, tris, item_d):
        return _nao_aplicavel()

    dx = max(p[0] for p in pos) - min(p[0] for p in pos)
    dy = max(p[1] for p in pos) - min(p[1] for p in pos)
    dz = max(p[2] for p in pos) - min(p[2] for p in pos)
    depth_ratio_z = dz / max(dx, dy, 1e-6)

    g1_med = info.get("g1_medido") if isinstance(info, dict) else None
    g1_dict = g1_med if isinstance(g1_med, dict) else {}
    topo = {} if ("aabb_fill" in g1_dict and "nao_manifold" in g1_dict) else topologia(pos, tris)
    aabb_fill = float(g1_dict["aabb_fill"] if "aabb_fill" in g1_dict else topo["aabb_fill"])
    nao_manifold = int(g1_dict["nao_manifold"] if "nao_manifold" in g1_dict else topo["nao_manifold"])

    front_cov, back_cov, thin_slice_frac, z_fill_ratio, sil_bbox_frac = _rasterizar_volumetria_frontal(
        pos, tris, dz, max(16, int(tamanho))
    )
    back_iou = _calcular_back_iou(pos, tris, concept_back, max(16, int(tamanho)))
    shell_solidity = aabb_fill / max(sil_bbox_frac * z_fill_ratio, 1e-6)

    motivos: list[str] = []
    if depth_ratio_z < MIN_DEPTH_RATIO_G15B or (
        depth_ratio_z < MIN_DEPTH_RATIO_SOFT_G15B and (aabb_fill < 0.15 or z_fill_ratio < 0.35)
    ):
        motivos.append("colapso_profundidade_z")
    if nao_manifold == 0 and aabb_fill < MIN_AABB_FILL_G15B and shell_solidity < MIN_SHELL_SOLIDITY_G15B:
        motivos.append("volume_baixo_aabb")
    if front_cov < MIN_FRONT_BACK_COVERAGE_G15B:
        motivos.append("buraco_cobertura_frontal")
    if back_cov < MIN_FRONT_BACK_COVERAGE_G15B:
        motivos.append("cavidade_ou_cobertura_traseira")
    if thin_slice_frac > MAX_THIN_SLICE_FRAC_G15B:
        motivos.append("casca_fina_colapsada")
    if z_fill_ratio < MIN_Z_FILL_G15B and aabb_fill < 0.14:
        motivos.append("cavidade_profunda_z")
    if back_iou is not None and back_iou < MIN_BACK_IOU_G15B:
        motivos.append("baixa_fidelidade_traseira")

    return {
        "aplicavel": True,
        "aprovado": len(motivos) == 0,
        "motivos": motivos,
        "depth_ratio_z": round(depth_ratio_z, 4),
        "aabb_fill": round(aabb_fill, 4),
        "shell_solidity": round(shell_solidity, 4),
        "front_cov": round(front_cov, 4),
        "back_cov": round(back_cov, 4),
        "thin_slice_frac": round(thin_slice_frac, 4),
        "z_fill_ratio": round(z_fill_ratio, 4),
        "back_iou": None if back_iou is None else round(back_iou, 4),
    }
