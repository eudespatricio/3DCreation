"""Gerador deterministico de mapa OpenPose COCO-18 (512x512 RGB, Pillow puro).

Produz esqueletos OpenPose canonicos em ``tpose`` ou ``apose`` sobre fundo preto para
guiar ControlNet OpenPose no estagio ``concept`` (sem numpy/opencv/torch).
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw

POSES_SUPORTADAS: tuple[str, ...] = ("tpose", "apose")

#: Nomes dos 18 keypoints no formato OpenPose COCO-18 (indices 0..17).
KEYPOINT_NOMES: tuple[str, ...] = (
    "Nose",
    "Neck",
    "RShoulder",
    "RElbow",
    "RWrist",
    "LShoulder",
    "LElbow",
    "LWrist",
    "RHip",
    "RKnee",
    "RAnkle",
    "LHip",
    "LKnee",
    "LAnkle",
    "REye",
    "LEye",
    "REar",
    "LEar",
)

#: Conexoes COCO-18 padrao OpenPose (indices 0-based).
LIMBS: tuple[tuple[int, int], ...] = (
    (1, 2),
    (1, 5),
    (2, 3),
    (3, 4),
    (5, 6),
    (6, 7),
    (1, 8),
    (8, 9),
    (9, 10),
    (1, 11),
    (11, 12),
    (12, 13),
    (1, 0),
    (0, 14),
    (14, 16),
    (0, 15),
    (15, 17),
)

#: Paleta RGB canonica do OpenPose (18 cores).
OPENPOSE_COLORS: tuple[tuple[int, int, int], ...] = (
    (255, 0, 0),
    (255, 85, 0),
    (255, 170, 0),
    (255, 255, 0),
    (170, 255, 0),
    (85, 255, 0),
    (0, 255, 0),
    (0, 255, 85),
    (0, 255, 170),
    (0, 255, 255),
    (0, 170, 255),
    (0, 85, 255),
    (0, 0, 255),
    (85, 0, 255),
    (170, 0, 255),
    (255, 0, 255),
    (255, 0, 170),
    (255, 0, 85),
)

_BASE_TRONCO_PERNAS: dict[int, tuple[float, float]] = {
    0: (0.50, 0.14),    # Nose
    1: (0.50, 0.22),    # Neck
    2: (0.41, 0.23),    # RShoulder (esquerda da imagem em vista frontal)
    5: (0.59, 0.23),    # LShoulder (direita da imagem em vista frontal)
    8: (0.44, 0.49),    # RHip
    9: (0.43, 0.69),    # RKnee
    10: (0.43, 0.89),   # RAnkle
    11: (0.56, 0.49),   # LHip
    12: (0.57, 0.69),   # LKnee
    13: (0.57, 0.89),   # LAnkle
    14: (0.485, 0.12),  # REye
    15: (0.515, 0.12),  # LEye
    16: (0.465, 0.135), # REar
    17: (0.535, 0.135), # LEar
}

_BRACOS_POR_POSE: dict[str, dict[int, tuple[float, float]]] = {
    "tpose": {
        3: (0.27, 0.23),  # RElbow
        4: (0.13, 0.23),  # RWrist
        6: (0.73, 0.23),  # LElbow
        7: (0.87, 0.23),  # LWrist
    },
    "apose": {
        3: (0.33, 0.34),  # RElbow
        4: (0.25, 0.45),  # RWrist
        6: (0.67, 0.34),  # LElbow
        7: (0.75, 0.45),  # LWrist
    },
}


def normalizar_pose(pose: str) -> str:
    chave = (pose or "").strip().lower().replace("-", "")
    if chave not in POSES_SUPORTADAS:
        raise ValueError(
            f"pose invalida: {pose!r} (suportadas: {', '.join(POSES_SUPORTADAS)})"
        )
    return chave


def keypoints_para_pose(
    pose: str, largura: int = 512, altura: int = 512
) -> list[tuple[float, float]]:
    """Retorna os 18 keypoints (x, y) em pixels na ordem COCO-18."""
    if largura <= 0 or altura <= 0:
        raise ValueError("largura e altura devem ser positivas")
    chave = normalizar_pose(pose)
    coords = {**_BASE_TRONCO_PERNAS, **_BRACOS_POR_POSE[chave]}
    return [
        (round(coords[i][0] * largura, 2), round(coords[i][1] * altura, 2))
        for i in range(18)
    ]


def _poligono_elipse(
    p1: tuple[float, float],
    p2: tuple[float, float],
    largura_osso: float,
    passos: int = 24,
) -> list[tuple[float, float]]:
    mx = (p1[0] + p2[0]) * 0.5
    my = (p1[1] + p2[1]) * 0.5
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    rx = max(1.0, math.hypot(dx, dy) * 0.5)
    ry = max(1.0, largura_osso)
    ang = math.atan2(dy, dx)
    ca = math.cos(ang)
    sa = math.sin(ang)
    pts: list[tuple[float, float]] = []
    for k in range(passos):
        theta = (2.0 * math.pi * k) / passos
        lx = rx * math.cos(theta)
        ly = ry * math.sin(theta)
        pts.append((mx + lx * ca - ly * sa, my + lx * sa + ly * ca))
    return pts


def desenhar_pose(pose: str, largura: int = 512, altura: int = 512) -> Image.Image:
    """Desenha o mapa OpenPose COCO-18 em imagem RGB deterministica."""
    pontos = keypoints_para_pose(pose, largura=largura, altura=altura)
    img = Image.new("RGB", (largura, altura), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    escala = min(largura, altura) / 512.0
    stick_w = max(2.0, 4.0 * escala)
    joint_r = max(2.0, 4.0 * escala)

    for idx, (a, b) in enumerate(LIMBS):
        cor = tuple(round(c * 0.6) for c in OPENPOSE_COLORS[idx])
        poly = _poligono_elipse(pontos[a], pontos[b], stick_w)
        draw.polygon(poly, fill=cor)

    for idx, (x, y) in enumerate(pontos):
        cor = OPENPOSE_COLORS[idx]
        draw.ellipse((x - joint_r, y - joint_r, x + joint_r, y + joint_r), fill=cor)

    return img


def gerar_pose_map(
    pose: str,
    saida: str | Path,
    *,
    largura: int = 512,
    altura: int = 512,
) -> Path:
    """Gera e salva o PNG deterministico do mapa de pose em ``saida``."""
    destino = Path(saida)
    destino.parent.mkdir(parents=True, exist_ok=True)
    img = desenhar_pose(pose, largura=largura, altura=altura)
    img.save(destino, format="PNG")
    return destino


def _args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gera mapa OpenPose COCO-18 deterministico (Pillow).")
    p.add_argument("--pose", required=True, choices=list(POSES_SUPORTADAS))
    p.add_argument("--saida", required=True)
    p.add_argument("--largura", type=int, default=512)
    p.add_argument("--altura", type=int, default=512)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    gerar_pose_map(args.pose, args.saida, largura=args.largura, altura=args.altura)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
