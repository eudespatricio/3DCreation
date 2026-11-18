"""Dispatch do auto-rig sem Blender (D-02): esqueleto explicito humanoide vence o tipo.

O bug original forcava ``quadruped@1`` para ``tipo: criatura`` mesmo com esqueleto humanoide
explicito. Este teste importa ``blender/autorig.py`` com ``bpy``/``bmesh``/``mathutils`` falsos e
verifica o despacho de ``auto_rigar_por_tipo`` sem precisar de Blender.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _importar_autorig():
    spec_mod = importlib.util.spec_from_file_location(
        "autorig_dispatch_test", RAIZ / "blender" / "autorig.py"
    )
    assert spec_mod and spec_mod.loader

    fake_bpy = types.ModuleType("bpy")
    fake_bmesh = types.ModuleType("bmesh")
    fake_mu = types.ModuleType("mathutils")
    fake_mu.Matrix = object
    fake_mu.Quaternion = object
    fake_mu.Vector = object

    backup = {k: sys.modules.get(k) for k in ("bpy", "bmesh", "mathutils")}
    sys.modules["bpy"] = fake_bpy
    sys.modules["bmesh"] = fake_bmesh
    sys.modules["mathutils"] = fake_mu
    try:
        mod = importlib.util.module_from_spec(spec_mod)
        spec_mod.loader.exec_module(mod)
        return mod
    finally:
        for k, v in backup.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_autorig_dispatch_esqueleto_humanoide_explicito_vence_tipo():
    autorig = _importar_autorig()
    chamadas: list[tuple[str, str]] = []

    def fake_humanoide(obj, esqueleto, criar_armadura_fn):
        chamadas.append(("humanoide", esqueleto))
        return ("HUM", esqueleto)

    autorig.auto_rigar_humanoide = fake_humanoide

    obj = object()
    criar = object()

    # mob bipede: tipo "criatura" com esqueleto humanoide explicito -> humanoide (nao quadruped)
    res = autorig.auto_rigar_por_tipo(obj, "godot-humanoid-aa@1", criar, tipo="criatura")
    assert res == ("HUM", "godot-humanoid-aa@1")

    # mesmo com tipo de quadrupede: esqueleto explicito humanoide vence
    res2 = autorig.auto_rigar_por_tipo(
        obj, "godot-humanoid@1", criar, tipo="criatura_quadrupede"
    )
    assert res2 == ("HUM", "godot-humanoid@1")

    # r15 (humanoide) tambem vence
    res3 = autorig.auto_rigar_por_tipo(obj, "r15@1", criar, tipo="criatura")
    assert res3 == ("HUM", "r15@1")

    assert chamadas == [
        ("humanoide", "godot-humanoid-aa@1"),
        ("humanoide", "godot-humanoid@1"),
        ("humanoide", "r15@1"),
    ]
