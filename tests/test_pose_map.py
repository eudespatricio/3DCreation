"""Testes deterministicos do gerador OpenPose COCO-18 (tools/pose_map.py, Pillow puro)."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "tools" / "pose_map.py"


def _carregar_pose_map():
    spec = importlib.util.spec_from_file_location("pose_map_mod", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pose_map_gera_rgb_512_fundo_preto_e_reprodutivel(tmp_path):
    mod = _carregar_pose_map()
    for pose in ("tpose", "apose"):
        p1 = tmp_path / f"{pose}_1.png"
        p2 = tmp_path / f"{pose}_2.png"
        mod.gerar_pose_map(pose, p1)
        mod.gerar_pose_map(pose, p2)

        assert p1.is_file()
        assert hashlib.sha256(p1.read_bytes()).hexdigest() == hashlib.sha256(
            p2.read_bytes()
        ).hexdigest()

        with Image.open(p1) as img:
            assert img.mode == "RGB"
            assert img.size == (512, 512)
            assert img.getpixel((0, 0)) == (0, 0, 0)
            assert img.getpixel((511, 511)) == (0, 0, 0)
            # Centro do tronco tem pixels coloridos do esqueleto
            cores = set(img.getdata())
            assert len(cores) > 5
            assert (0, 0, 0) in cores


def test_tpose_e_apose_tem_bracos_distintos_e_simetricos():
    mod = _carregar_pose_map()
    t_pts = mod.keypoints_para_pose("tpose")
    a_pts = mod.keypoints_para_pose("apose")
    assert len(t_pts) == 18
    assert len(a_pts) == 18

    # T-pose: punhos (4, 7) alinhados na altura dos ombros (2, 5)
    assert abs(t_pts[4][1] - t_pts[2][1]) <= 1.0
    assert abs(t_pts[7][1] - t_pts[5][1]) <= 1.0
    # A-pose: punhos bem abaixo dos ombros
    assert a_pts[4][1] > a_pts[2][1] + 50.0
    assert a_pts[7][1] > a_pts[5][1] + 50.0
    # Simetria esquerda/direita em torno de x=256
    assert abs((t_pts[4][0] + t_pts[7][0]) - 512.0) <= 1.0
    assert abs((a_pts[4][0] + a_pts[7][0]) - 512.0) <= 1.0


def test_cli_pose_map_reproduz_sha256_identico(tmp_path):
    a = tmp_path / "cli_a.png"
    b = tmp_path / "cli_b.png"
    r1 = subprocess.run(
        [sys.executable, str(SCRIPT), "--pose", "tpose", "--saida", str(a)],
        capture_output=True,
        text=True,
        check=True,
    )
    r2 = subprocess.run(
        [sys.executable, str(SCRIPT), "--pose", "tpose", "--saida", str(b)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert r1.returncode == 0 and r2.returncode == 0
    assert hashlib.sha256(a.read_bytes()).hexdigest() == hashlib.sha256(b.read_bytes()).hexdigest()


def test_pose_invalida_falha():
    mod = _carregar_pose_map()
    with pytest.raises(ValueError):
        mod.keypoints_para_pose("sentado")
