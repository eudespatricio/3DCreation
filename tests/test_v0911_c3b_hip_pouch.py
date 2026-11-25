"""Teste TDD unitario independente para v0.9.11 — Contrato C3b (bolsa de cintura vs braco abduzido)."""

from __future__ import annotations

import math
import sys
import types
from pathlib import Path
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ / "blender") not in sys.path:
    sys.path.insert(0, str(RAIZ / "blender"))


class _Vec3:
    def __init__(self, xyz=(0.0, 0.0, 0.0)) -> None:
        self.x, self.y, self.z = float(xyz[0]), float(xyz[1]), float(xyz[2])

    def __getitem__(self, idx: int) -> float:
        return (self.x, self.y, self.z)[idx]

    def __sub__(self, other: _Vec3) -> _Vec3:
        return _Vec3((self.x - other.x, self.y - other.y, self.z - other.z))

    def __add__(self, other: _Vec3) -> _Vec3:
        return _Vec3((self.x + other.x, self.y + other.y, self.z + other.z))

    def __mul__(self, scalar: float) -> _Vec3:
        return _Vec3((self.x * scalar, self.y * scalar, self.z * scalar))

    @property
    def length(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    @property
    def length_squared(self) -> float:
        return self.x * self.x + self.y * self.y + self.z * self.z

    def dot(self, other: _Vec3) -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z


def _importar_autorig_grafo(monkeypatch: pytest.MonkeyPatch):
    if "mathutils" not in sys.modules:
        mod_mu = types.ModuleType("mathutils")
        mod_mu.Vector = _Vec3  # type: ignore[attr-defined]
        mod_mu.Matrix = object  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "mathutils", mod_mu)
    if "bpy" not in sys.modules:
        monkeypatch.setitem(sys.modules, "bpy", types.ModuleType("bpy"))
    import autorig_grafo as ag

    return ag


def test_c3b_hip_pouch_permitido_no_quadril_e_bloqueado_no_braco(monkeypatch: pytest.MonkeyPatch) -> None:
    ag = _importar_autorig_grafo(monkeypatch)
    m: dict[str, Any] = {
        "altura": 6.0, "z_min": 0.0, "z_max": 6.0, "cy": 0.0, "torso_hw": 0.50, "neck_hw": 0.22,
        "leg_x_L": -0.61, "leg_x_R": 0.61, "shoulder_x_L": -0.74, "shoulder_x_R": 0.74,
        "elbow_x_L": -1.57, "elbow_x_R": 1.57, "shoulder_z": 4.62, "chest_top_z": 4.73,
        "neck_z": 4.90, "chest_z": 4.00, "spine1_z": 3.40, "spine_z": 3.08, "hip_z": 2.78,
        "leg_top_z": 2.40, "knee_z": 1.39, "ankle_z": 0.39, "head_top_z": 6.0,
        "braco_L": {"shoulder": _Vec3((-0.74, 0.24, 4.62)), "elbow": _Vec3((-1.57, 0.17, 3.95)), "wrist": _Vec3((-2.45, 0.02, 3.37))},
        "braco_R": {"shoulder": _Vec3((0.74, 0.24, 4.62)), "elbow": _Vec3((1.57, 0.17, 3.95)), "wrist": _Vec3((2.45, 0.02, 3.37))},
    }
    v_pouch, v_arm = _Vec3((-1.14, -0.47, 2.57)), _Vec3((-1.55, 0.0, 3.20))
    for tem_neck in (True, False):
        lim = ag._limites_anatomicos(m, tem_neck=tem_neck)
        assert "hips_max_x" in lim and 1.22 < lim["hips_max_x"] < 1.50
        assert lim.get("arm_hip_block_z", -1e9) > 2.60
        assert ag._osso_permitido("LowerTorso", v_pouch, m, True, tem_neck=tem_neck, lim=lim) is True
        assert ag._osso_permitido("Hips", v_pouch, m, True, tem_neck=tem_neck, lim=lim) is True
        assert ag._osso_permitido("LeftUpperArm", v_pouch, m, True, tem_neck=tem_neck, lim=lim) is False
        assert ag._osso_permitido("LeftLowerArm", v_pouch, m, True, tem_neck=tem_neck, lim=lim) is False
        assert ag._osso_permitido("LowerTorso", v_arm, m, True, tem_neck=tem_neck, lim=lim) is False
        assert ag._osso_permitido("LeftUpperArm", v_arm, m, True, tem_neck=tem_neck, lim=lim) is True
        assert ag._osso_permitido("LeftLowerArm", v_arm, m, True, tem_neck=tem_neck, lim=lim) is True

    m_in: dict[str, Any] = {
        "altura": 2.0, "z_min": 0.0, "z_max": 2.0, "cy": 0.0, "torso_hw": 0.22, "neck_hw": 0.08,
        "leg_x_L": -0.28, "leg_x_R": 0.28, "shoulder_x_L": -0.38, "shoulder_x_R": 0.38,
        "elbow_x_L": -0.70, "elbow_x_R": 0.70, "shoulder_z": 1.50, "chest_top_z": 1.58,
        "neck_z": 1.66, "chest_z": 1.36, "spine1_z": 1.18, "spine_z": 1.06, "hip_z": 0.94,
        "leg_top_z": 0.84, "knee_z": 0.48, "ankle_z": 0.14, "head_top_z": 2.0,
        "braco_L": {"shoulder": _Vec3((-0.38, 0.0, 1.50)), "elbow": _Vec3((-0.70, 0.0, 1.20)), "wrist": _Vec3((-0.52, 0.0, 0.90))},
        "braco_R": {"shoulder": _Vec3((0.38, 0.0, 1.50)), "elbow": _Vec3((0.70, 0.0, 1.20)), "wrist": _Vec3((0.52, 0.0, 0.90))},
    }
    lim_in = ag._limites_anatomicos(m_in, tem_neck=True)
    assert lim_in["hips_max_x"] < 0.52 and ag._osso_permitido("LeftLowerArm", _Vec3((-0.52, 0.0, 0.90)), m_in, True, tem_neck=True, lim=lim_in) is True
    m_low_el = {**m_in, "torso_hw": 0.38, "neck_hw": 0.14, "leg_x_L": -0.315, "leg_x_R": 0.315, "shoulder_x_L": -0.40, "shoulder_x_R": 0.40, "elbow_x_L": -0.634, "elbow_x_R": 0.634, "shoulder_z": 1.57, "chest_top_z": 1.60, "chest_z": 1.40, "spine_z": 1.04, "leg_top_z": 0.90, "knee_z": 0.50, "braco_L": {"shoulder": _Vec3((-0.40, 0.0, 1.57)), "elbow": _Vec3((-0.634, 0.06, 1.20)), "wrist": _Vec3((-0.845, -0.01, 0.82))}, "braco_R": {"shoulder": _Vec3((0.40, 0.0, 1.57)), "elbow": _Vec3((0.634, 0.06, 1.20)), "wrist": _Vec3((0.845, -0.01, 0.82))}}
    assert ag._osso_permitido("RightLowerArm", _Vec3((0.546, 0.0, 1.134)), m_low_el, True, tem_neck=False, lim=ag._limites_anatomicos(m_low_el, tem_neck=False)) is True
