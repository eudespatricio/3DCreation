"""Testes TDD independentes (janela limpa) para v0.9.10 — Contratos F-01, F-02, F-03, F-07 e F-08 (unitarios)."""

from __future__ import annotations

import importlib.util
import json
import os
import struct
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest
import yaml
from PIL import Image, ImageDraw

from forge3d import animacao, config, profiles, qc, qc_deformacao, qc_skin, rbx, rbx_anim
from forge3d.providers import mesh_i23d
from forge3d.rbx_xml import JOINT_R15

RAIZ = Path(__file__).resolve().parents[1]
for _p in (str(RAIZ / "blender"), str(RAIZ / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _carregar_delight_pbr():
    spec = importlib.util.spec_from_file_location("delight_pbr_v0910", RAIZ / "tools" / "delight_pbr.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pack_glb(gltf: dict, buf: bytearray) -> bytes:
    buf.extend(b"\x00" * ((4 - len(buf) % 4) % 4))
    gltf["buffers"] = [{"byteLength": len(buf)}]
    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((4 - len(jb) % 4) % 4)
    total = 12 + 8 + len(jb) + 8 + len(buf)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(jb), 0x4E4F534A) + jb
        + struct.pack("<II", len(buf), 0x004E4942) + bytes(buf)
    )


def _add_bv(buf: bytearray, bvs: list[dict], raw: bytes, target: int | None = None) -> int:
    buf.extend(b"\x00" * ((4 - len(buf) % 4) % 4))
    bv: dict = {"buffer": 0, "byteOffset": len(buf), "byteLength": len(raw)}
    if target is not None:
        bv["target"] = target
    buf.extend(raw)
    bvs.append(bv)
    return len(bvs) - 1


def _box_geom(center: tuple[float, float, float], half: tuple[float, float, float]):
    cx, cy, cz = center
    hx, hy, hz = half
    verts = [
        (cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz),
        (cx + hx, cy + hy, cz - hz), (cx - hx, cy + hy, cz - hz),
        (cx - hx, cy - hy, cz + hz), (cx + hx, cy - hy, cz + hz),
        (cx + hx, cy + hy, cz + hz), (cx - hx, cy + hy, cz + hz),
    ]
    tris = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
        (2, 3, 7), (2, 7, 6), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
    ]
    return verts, tris


def _multi_node_glb(nodes_boxes: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]]) -> bytes:
    buf, bvs, accessors, meshes, nodes = bytearray(), [], [], [], []
    for idx, (nome, (center, half)) in enumerate(nodes_boxes.items()):
        verts, tris = _box_geom(center, half)
        bv_p = _add_bv(buf, bvs, b"".join(struct.pack("<3f", *v) for v in verts), 34962)
        bv_n = _add_bv(buf, bvs, b"".join(struct.pack("<3f", 0.0, 1.0, 0.0) for _ in verts), 34962)
        bv_u = _add_bv(buf, bvs, b"".join(struct.pack("<2f", (i % 2) * 0.8 + 0.1, ((i // 2) % 2) * 0.8 + 0.1) for i in range(len(verts))), 34962)
        bv_i = _add_bv(buf, bvs, b"".join(struct.pack("<3H", *t) for t in tris), 34963)
        base = len(accessors)
        xs, ys, zs = [v[0] for v in verts], [v[1] for v in verts], [v[2] for v in verts]
        accessors.extend([
            {"bufferView": bv_p, "componentType": 5126, "count": len(verts), "type": "VEC3",
             "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
            {"bufferView": bv_n, "componentType": 5126, "count": len(verts), "type": "VEC3"},
            {"bufferView": bv_u, "componentType": 5126, "count": len(verts), "type": "VEC2"},
            {"bufferView": bv_i, "componentType": 5123, "count": len(tris) * 3, "type": "SCALAR"},
        ])
        meshes.append({"name": nome, "primitives": [{"attributes": {"POSITION": base, "NORMAL": base + 1, "TEXCOORD_0": base + 2}, "indices": base + 3, "material": 0}]})
        nodes.append({"name": nome, "mesh": idx})
    gltf = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes, "meshes": meshes, "accessors": accessors, "bufferViews": bvs,
        "materials": [{"name": "mat0", "pbrMetallicRoughness": {"baseColorFactor": [0.7, 0.7, 0.7, 1.0]}}],
    }
    return _pack_glb(gltf, buf)


def _skinned_limb_glb(joint_specs: list[tuple[str, int | None, tuple[float, float, float]]], n_boxes: int, slot_fn) -> bytes:
    verts, tris, j_weights = [], [], []
    for b_idx in range(n_boxes):
        slot = int(slot_fn(b_idx))
        jx, jy, jz = joint_specs[slot][2]
        v_box, t_box = _box_geom((jx + (b_idx % 5) * 0.03 + 0.04, jy + ((b_idx // 5) % 5) * 0.03 + 0.04, jz + 0.02), (0.01, 0.01, 0.01))
        base_v = len(verts)
        verts.extend(v_box)
        tris.extend((a + base_v, b + base_v, c + base_v) for a, b, c in t_box)
        j_weights.extend([(slot, 1.0)] * 8)

    nodes: list[dict] = [{"name": "MeshNode", "mesh": 0, "skin": 0}]
    world_pos = [pos for _, _, pos in joint_specs]
    children_map: dict[int, list[int]] = {i: [] for i in range(len(joint_specs))}
    for i, (_, p_i, _) in enumerate(joint_specs):
        if p_i is not None:
            children_map[p_i].append(i + 1)
    for i, (nome, p_i, pos) in enumerate(joint_specs):
        p_pos = world_pos[p_i] if p_i is not None else (0.0, 0.0, 0.0)
        nd: dict = {"name": nome, "translation": [pos[k] - p_pos[k] for k in range(3)]}
        if children_map[i]:
            nd["children"] = children_map[i]
        nodes.append(nd)

    buf, bvs = bytearray(), []
    bv_p = _add_bv(buf, bvs, b"".join(struct.pack("<3f", *v) for v in verts), 34962)
    bv_n = _add_bv(buf, bvs, b"".join(struct.pack("<3f", 0.0, 1.0, 0.0) for _ in verts), 34962)
    bv_u = _add_bv(buf, bvs, b"".join(struct.pack("<2f", (i % 2) * 0.8 + 0.1, ((i // 2) % 2) * 0.8 + 0.1) for i in range(len(verts))), 34962)
    bv_j = _add_bv(buf, bvs, b"".join(struct.pack("<4B", slot, 0, 0, 0) for slot, _ in j_weights), 34962)
    bv_w = _add_bv(buf, bvs, b"".join(struct.pack("<4f", w, 0.0, 0.0, 0.0) for _, w in j_weights), 34962)
    bv_i = _add_bv(buf, bvs, b"".join(struct.pack("<3H", *t) for t in tris), 34963)
    bv_ibm = _add_bv(buf, bvs, b"".join(struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -px, -py, -pz, 1) for px, py, pz in world_pos))
    xs, ys, zs = [v[0] for v in verts], [v[1] for v in verts], [v[2] for v in verts]
    accessors: list[dict] = [
        {"bufferView": bv_p, "componentType": 5126, "count": len(verts), "type": "VEC3",
         "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
        {"bufferView": bv_n, "componentType": 5126, "count": len(verts), "type": "VEC3"},
        {"bufferView": bv_u, "componentType": 5126, "count": len(verts), "type": "VEC2"},
        {"bufferView": bv_j, "componentType": 5121, "count": len(verts), "type": "VEC4"},
        {"bufferView": bv_w, "componentType": 5126, "count": len(verts), "type": "VEC4"},
        {"bufferView": bv_i, "componentType": 5123, "count": len(tris) * 3, "type": "SCALAR"},
        {"bufferView": bv_ibm, "componentType": 5126, "count": len(joint_specs), "type": "MAT4"},
    ]
    gltf: dict = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 1]}], "nodes": nodes,
        "skins": [{"joints": list(range(1, len(joint_specs) + 1)), "inverseBindMatrices": 6}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2, "JOINTS_0": 3, "WEIGHTS_0": 4}, "indices": 5, "material": 0}]}],
        "materials": [{"name": "mat0", "pbrMetallicRoughness": {"baseColorFactor": [0.7, 0.7, 0.7, 1.0]}}],
        "accessors": accessors, "bufferViews": bvs,
    }
    return _pack_glb(gltf, buf)


# ------------------------------------------------------------------ 1. F-01: Rig/Skinning & QC
def test_f01_qc_skin_ossos_membro_vazios_100v_e_500v() -> None:
    r15_specs: list[tuple[str, int | None, tuple[float, float, float]]] = [
        ("HumanoidRootPart", None, (0.0, 0.0, 0.0)), ("LowerTorso", 0, (0.0, 0.9, 0.0)),
        ("UpperTorso", 1, (0.0, 1.25, 0.0)), ("Head", 2, (0.0, 1.65, 0.0)),
        ("LeftUpperArm", 2, (0.25, 1.45, 0.0)), ("LeftLowerArm", 4, (0.45, 1.20, 0.0)),
        ("RightUpperArm", 2, (-0.25, 1.45, 0.0)), ("RightLowerArm", 6, (-0.45, 1.20, 0.0)),
        ("LeftUpperLeg", 1, (0.14, 0.85, 0.0)), ("LeftLowerLeg", 8, (0.14, 0.45, 0.0)),
        ("RightUpperLeg", 1, (-0.14, 0.85, 0.0)), ("RightLowerLeg", 10, (-0.14, 0.45, 0.0)),
    ]
    # 16 boxes = 128 vertices (>= 100 verts). Slots 4 (LeftUpperArm) and 6 (RightUpperArm) starved (0 verts).
    active_slots = [1, 2, 3, 5, 7, 8, 9, 10, 11]
    g_s, b_s = qc.ler_glb_bin(_skinned_limb_glb(r15_specs, 16, lambda b: active_slots[b % len(active_slots)]))
    st_s = qc_skin._skin_status(g_s, b_s)
    expected_keys = {
        "ok", "primitivas_skinned", "sem_atributos", "joints_invalidos",
        "pesos_invalidos", "somente_raiz", "sem_deformacao", "ossos_membro_vazios",
    }
    assert expected_keys <= set(st_s.keys())
    assert st_s["ok"] is False
    assert "LeftUpperArm" in st_s["ossos_membro_vazios"] and "RightUpperArm" in st_s["ossos_membro_vazios"]

    all_non_root = list(range(1, len(r15_specs)))
    g_h, b_h = qc.ler_glb_bin(_skinned_limb_glb(r15_specs, 22, lambda b: all_non_root[b % len(all_non_root)]))
    st_h = qc_skin._skin_status(g_h, b_h)
    assert st_h["ok"] is True and st_h["ossos_membro_vazios"] == []

    godot_specs: list[tuple[str, int | None, tuple[float, float, float]]] = [
        ("Root", None, (0.0, 0.0, 0.0)), ("Hips", 0, (0.0, 0.9, 0.0)),
        ("UpperArm.L", 1, (0.25, 1.45, 0.0)), ("LowerArm.L", 2, (0.45, 1.20, 0.0)),
        ("UpperArm.R", 1, (-0.25, 1.45, 0.0)), ("LowerArm.R", 4, (-0.45, 1.20, 0.0)),
        ("UpperLeg.L", 1, (0.14, 0.85, 0.0)), ("LowerLeg.L", 6, (0.14, 0.45, 0.0)),
        ("UpperLeg.R", 1, (-0.14, 0.85, 0.0)), ("LowerLeg.R", 8, (-0.14, 0.45, 0.0)),
    ]
    slots_no_uarm_l = [1, 3, 4, 5, 6, 7, 8, 9]
    g_500, b_500 = qc.ler_glb_bin(_skinned_limb_glb(godot_specs, 80, lambda b: slots_no_uarm_l[b % len(slots_no_uarm_l)]))
    st_500 = qc_skin._skin_status(g_500, b_500)
    assert st_500["ok"] is False and "UpperArm.L" in st_500["ossos_membro_vazios"]


def test_f01_g16_motor6d_reprova_colapso_skinned_e_anexa_medido_skinned(tmp_path: Path) -> None:
    perfil = profiles.carregar("roblox-aa-80")
    comb_name = "boss_partes_combinadas.glb"
    partes = [{"nome": "LowerTorso", "arquivo": "LowerTorso.glb"}, {"nome": "UpperTorso", "arquivo": "UpperTorso.glb"}, {"nome": "Head", "arquivo": "Head.glb"}]
    (tmp_path / comb_name).write_bytes(_multi_node_glb({"LowerTorso": ((0, .3, 0), (.2, .3, .2)), "UpperTorso": ((0, .9, 0), (.2, .3, .2)), "Head": ((0, 1.4, 0), (.15, .15, .15))}))
    item_m6d = {"id": "boss.m6d.01", "tipo": "personagem_humanoide", "auto_rig": True, "esqueleto": "r15@1",
                "rig": {"modo": "motor6d", "esqueleto": "r15@1", "partes_combinadas": comb_name}, "partes": partes}
    base_res = {"arquivos": [{"caminho": "boss.glb", "papel": "mesh"}, {"caminho": comb_name, "papel": "partes_combinadas"}],
                "partes": partes, "partes_combinadas": comb_name}

    g_unsk, b_unsk = qc.ler_glb_bin(_multi_node_glb({"Main": ((0.0, 0.5, 0.0), (0.3, 0.5, 0.3))}))
    res_ok = qc_deformacao.verificar_g16_deformacao(g_unsk, b_unsk, item_m6d, perfil, tmp_path, base_res, {})
    assert res_ok["id"] == "G16" and res_ok["status"] == "ok" and res_ok["medido"]["modo"] == "motor6d_rigido"

    res_collapse = {**base_res, "deformacao_anim": {"max_stretch": 81.82, "p99_stretch": 12.4, "frac_gt_20": 0.08, "frac_gt_30": 0.04}}
    g16_fail = qc_deformacao.verificar_g16_deformacao(g_unsk, b_unsk, item_m6d, perfil, tmp_path, res_collapse, {})
    assert g16_fail["id"] == "G16" and g16_fail["status"] == "falhou" and g16_fail["codigo"] == "FORGE-E-QC"
    assert "skinned" in g16_fail["medido"] and float(g16_fail["medido"]["skinned"]["max_stretch"]) == pytest.approx(81.82)


# ------------------------------------------------------------------ 2. F-02: death / run / Roblox ground-clamp
def test_f02_animacao_death_pitch_joelhos_e_run_chaves() -> None:
    motores_death = list(animacao.MOTORES_DEATH)
    quadril_x = [m for m in motores_death if m[0] == "quadril" and m[1] == "X"]
    assert len(quadril_x) == 1 and min(quadril_x[0][2]) <= -70.0
    canelas = {m[0]: m[2] for m in motores_death if m[0] in ("canela_e", "canela_d") and m[1] == "X"}
    assert min(canelas["canela_e"]) <= -42.0 and min(canelas["canela_d"]) <= -42.0
    assert canelas["canela_e"][-1] <= -20.0 and canelas["canela_d"][-1] <= -20.0
    assert min(animacao._DESLOCAMENTO_QUADRIL_Z["death"]) < -0.5

    clipe_run = animacao.clipes(profiles.carregar("godot4-aa"), "godot-humanoid-aa@1", ["run"])[0]
    assert 25 <= len(clipe_run["chaves"]) <= 32 and float(clipe_run["duracao_s"]) >= 1.6


def _extrair_ys_pose_xml(linhas: list[str], nome_parte: str) -> list[float]:
    root = ElementTree.fromstring("\n".join(linhas))
    return [
        float(item.findtext("Properties/CoordinateFrame[@name='CFrame']/Y") or "0.0")
        for item in root.iter("Item")
        if item.get("class") == "Pose" and item.findtext("Properties/string[@name='Name']") == nome_parte
    ]


def test_f02_rbx_anim_death_clampa_lower_torso_y_com_ancoras() -> None:
    death_clipe = animacao.clipes(profiles.carregar("roblox-aa-80"), "r15@1", ["death"])[0]
    linhas_sem, _ = rbx_anim._sequencia_xml(death_clipe, 0, mps=0.28, ancoras=None)
    ys_sem = _extrair_ys_pose_xml(linhas_sem, "LowerTorso")
    assert ys_sem and min(ys_sem) < -1.9

    ancoras_baixas = {
        "Root": [0.0, 0.35, 0.0], "LowerTorso": [0.0, 0.35, 0.0], "UpperTorso": [0.0, 0.55, 0.0],
        "Head": [0.0, 0.80, 0.0], "LeftUpperLeg": [0.10, 0.32, 0.0], "RightUpperLeg": [-0.10, 0.32, 0.0],
        "LeftFoot": [0.10, 0.05, 0.0], "RightFoot": [-0.10, 0.05, 0.0],
    }
    linhas_com, _ = rbx_anim._sequencia_xml(death_clipe, 0, mps=0.28, ancoras=ancoras_baixas)
    ys_com = _extrair_ys_pose_xml(linhas_com, "LowerTorso")
    assert ys_com and min(ys_com) > min(ys_sem) + 0.4 and min(ys_com) >= -1.65


# ------------------------------------------------------------------ 3. F-03: PBR / Delight / Emissive / Orcamento / vistas: 4
def test_f03_delight_pbr_emissive_ambar_safira_e_ferro_forjado() -> None:
    dp = _carregar_delight_pbr()
    img_em = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d_em = ImageDraw.Draw(img_em)
    d_em.rectangle((16, 16, 112, 112), fill=(45, 45, 50, 255))
    d_em.rectangle((26, 26, 46, 46), fill=(232, 148, 24, 255))   # warm amber furnace glow (V=232, S=229)
    d_em.rectangle((76, 26, 96, 46), fill=(32, 152, 218, 255))   # cool sapphire rune glow (V=218, S=218)
    d_em.rectangle((26, 76, 46, 96), fill=(150, 110, 52, 255))   # matte bronze/leather (non-emissive)

    for fn_e in [dp._emissive_pil] + ([dp._emissive_cv2] if dp._TEM_CV2 else []):
        em = fn_e(img_em)
        assert em.getpixel((36, 36)) >= 180 and em.getpixel((86, 36)) >= 180
        assert em.getpixel((60, 60)) == 0 and em.getpixel((36, 86)) == 0

    img_fe = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d_fe = ImageDraw.Draw(img_fe)
    d_fe.rectangle((12, 12, 58, 58), fill=(48, 50, 56, 255))
    for y_line in range(16, 54, 6):
        d_fe.line((14, y_line, 56, y_line), fill=(86, 92, 102, 255), width=1)
        d_fe.line((14, y_line + 2, 56, y_line + 2), fill=(34, 36, 40, 255), width=1)
    d_fe.rectangle((70, 12, 116, 58), fill=(72, 74, 78, 255))
    d_fe.rectangle((70, 70, 116, 116), fill=(150, 95, 58, 255))

    for fn_p in [dp._mapas_pbr_pil] + ([dp._mapas_pbr_cv2] if dp._TEM_CV2 else []):
        met, rough = fn_p(img_fe)
        assert 183 <= met.getpixel((35, 35)) <= 226 and 61 <= rough.getpixel((35, 35)) <= 97
        assert met.getpixel((92, 35)) < 30 and met.getpixel((92, 92)) < 30


def test_f03_ajustar_resolucao_orcamento_degrau_1024_e_piso_px(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import bake_pbr_maps as bpm

    glb_p = tmp_path / "boss.glb"
    glb_p.write_bytes(b"x" * 100)
    for nome in ("boss_baseColor.png", "boss_normal.png", "boss_orm.png"):
        (tmp_path / nome).write_bytes(b"p" * 50)

    chamadas: list[tuple[str, int]] = []
    tamanho_simulado = {"bytes": 3_000_000}

    def fake_resize(_obj, caminho: str, px_novo: int, _cs: str) -> tuple[int, bool]:
        chamadas.append((os.path.basename(caminho), int(px_novo)))
        if int(px_novo) <= 1024:
            tamanho_simulado["bytes"] = 1_500_000
        return 1234, True

    monkeypatch.setattr(bpm, "_redimensionar_png_no_material", fake_resize)
    monkeypatch.setattr(bpm.os.path, "getsize", lambda p: tamanho_simulado["bytes"] if str(p) == str(glb_p) else 1000)
    texs = [
        {"caminho": "boss_baseColor.png", "papel": "textura", "bytes": 1000},
        {"caminho": "boss_normal.png", "papel": "normal", "bytes": 1000},
        {"caminho": "boss_orm.png", "papel": "orm", "bytes": 1000},
    ]
    bpm.ajustar_resolucao_orcamento(object(), str(tmp_path), texs, str(glb_p), 2_000_000, lambda: None)
    assert chamadas and all(px == 1024 for _, px in chamadas)

    chamadas.clear()
    tamanho_simulado["bytes"] = 5_000_000
    monkeypatch.setattr(bpm, "_redimensionar_png_no_material", lambda _o, c, px, _cs: (chamadas.append((os.path.basename(c), int(px))) or (1234, True)))
    bpm.ajustar_resolucao_orcamento(object(), str(tmp_path), texs, str(glb_p), 2_000_000, lambda: None, piso_px=1024)
    assert chamadas and min(px for _, px in chamadas) >= 1024


def test_f03_mesh_i23d_trellis_single_view_ignora_vistas_extras(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from forge3d.providers import mesh as mesh_mod

    destino = tmp_path / "raw_trellis"
    destino.mkdir()
    vistas_paths: dict[str, str] = {}
    for v in ("front", "back", "left", "right"):
        p = destino / f"concept_{v}.png"
        Image.new("RGBA", (32, 32), (120, 130, 140, 255)).save(p)
        vistas_paths[v] = str(p)
    (destino / "input.png").write_bytes(Path(vistas_paths["front"]).read_bytes())
    (destino / "dl_stub.py").write_text("# stub\n", encoding="utf-8")

    def fake_trellis(item: dict, dest: Path, img: Path, env: dict) -> dict:
        (dest / "modelo.glb").write_bytes(b"glTF")
        res = {"ok": True, "provedor": "trellis2_local", "faces": 4000}
        (dest / "i23d_resultado.json").write_text(json.dumps(res), encoding="utf-8")
        return res

    delight_calls: list[Path] = []

    def fake_delight(entrada: Path, dest: Path, env: dict) -> dict:
        delight_calls.append(entrada)
        alb = dest / "input_delit.png"
        alb.write_bytes(entrada.read_bytes())
        return {"report": {"ativo": True, "executado": True}, "albedo": "input_delit.png",
                "metallic_hint": "", "roughness_hint": "", "emissive_hint": "", "arquivos": [alb]}

    for target_mod in (mesh_mod, mesh_i23d._diag):
        monkeypatch.setattr(target_mod, "modelo_escolhido", lambda: "trellis", raising=False)
        monkeypatch.setattr(target_mod, "script_delight", lambda: destino / "dl_stub.py", raising=False)
        monkeypatch.setattr(target_mod, "_alfa_util", lambda _p: (True, 0.5), raising=False)
    monkeypatch.setattr(mesh_i23d._trellis, "executar_i23d_trellis2_local", fake_trellis)

    out = mesh_i23d.executar_i23d_step(
        item={"id": "boss.trellis.01", "tipo": "personagem_humanoide", "vistas": 4},
        destino=destino, imagem=Path(vistas_paths["front"]), concept_meta={"vistas": vistas_paths},
        env={}, t0=0.0, pose_guard_fn=lambda i, im, d, e: (im, {"ok": True}), delight_fn=fake_delight,
    )
    assert len(delight_calls) == 1
    res_json = json.loads((destino / "i23d_resultado.json").read_text(encoding="utf-8"))
    assert res_json.get("vistas_extras_ignoradas_single_view") is True or out["resultado"].get("vistas_extras_ignoradas_single_view") is True


# ------------------------------------------------------------------ 6. F-07: Roblox Place XML StreamingEnabled=false
def _workspace_streaming_enabled(xml_path: Path) -> str | None:
    root = ElementTree.fromstring(xml_path.read_text(encoding="utf-8"))
    ws = next((e for e in root.findall("Item") if e.get("class") == "Workspace"), None)
    assert ws is not None
    return ws.findtext("Properties/bool[@name='StreamingEnabled']")


def test_f07_roblox_place_xml_streaming_enabled_false(tmp_path: Path) -> None:
    dest = tmp_path / "dest_f07"
    dest.mkdir()
    lote_yaml = tmp_path / "lote_f07.yaml"
    lote_yaml.write_text(yaml.safe_dump({
        "schema": "forge3d/spec@6", "projeto": "demo", "perfil": "roblox-r15", "destino_exportacao": str(dest),
        "lote": [
            {"id": "hero.blocky.01", "tipo": "personagem_humanoide", "rota": "blocky", "altura_metros": 1.8,
             "auto_rig": True, "esqueleto": "r15@1", "animacoes_base": ["idle"], "tags": ["teste"]},
            {"id": "hero.model.01", "tipo": "personagem_humanoide", "rota": "mesh", "prompt": "guerreiro", "seed": 7,
             "altura_metros": 1.85, "auto_rig": True, "esqueleto": "r15@1", "animacoes_base": ["idle"],
             "partes": [{"nome": n, "junta": JOINT_R15[n]} for n in JOINT_R15], "rig": {"modo": "motor6d", "esqueleto": "r15@1"}},
        ],
    }), encoding="utf-8")

    out_blocky = tmp_path / "blocky.rbxlx"
    rbx.exportar_r15(lote_yaml, "hero.blocky.01", saida=out_blocky)
    assert _workspace_streaming_enabled(out_blocky) == "false"

    out_model = tmp_path / "model.rbxlx"
    rbx.exportar_r15(lote_yaml, "hero.model.01", saida=out_model, model_id="72623231126473")
    assert _workspace_streaming_enabled(out_model) == "false"


# ------------------------------------------------------------------ 7. F-08: Natural Arm Gravity Droop
def _extrair_mat3_pose_frame0(linhas: list[str], nome_parte: str) -> list[float]:
    root = ElementTree.fromstring("\n".join(linhas))
    kf0 = root.find("Item[@class='Keyframe']")
    assert kf0 is not None
    for item in kf0.iter("Item"):
        if item.get("class") == "Pose" and item.findtext("Properties/string[@name='Name']") == nome_parte:
            cf = item.find("Properties/CoordinateFrame[@name='CFrame']")
            assert cf is not None
            return [float(cf.findtext(f"R{r}{c}") or "0.0") for r in range(3) for c in range(3)]
    raise AssertionError(f"Pose {nome_parte} ausente no Keyframe 0")


def test_f08_idle_cotovelo_e_aducao_braco_ancoras_rbx_anim() -> None:
    antebracos = {m[0]: m for m in animacao.MOTORES_IDLE if m[0] in ("antebraco_e", "antebraco_d")}
    assert "antebraco_e" in antebracos and "antebraco_d" in antebracos
    for m_ab in antebracos.values():
        assert (float(m_ab[5]) if len(m_ab) >= 6 else float(m_ab[1])) > 0.0

    from forge3d import animacao_pose

    assert animacao_pose.calcular_aducao_braco_ancoras(None) == pytest.approx(0.0)
    anc_vert = {
        "UpperTorso": [0.0, 1.30, 0.0], "LeftUpperArm": [0.24, 1.45, 0.0], "LeftLowerArm": [0.26, 1.15, 0.0],
        "RightUpperArm": [-0.24, 1.45, 0.0], "RightLowerArm": [-0.26, 1.15, 0.0],
        "LeftUpperLeg": [0.12, 0.90, 0.0], "RightUpperLeg": [-0.12, 0.90, 0.0],
    }
    assert animacao_pose.calcular_aducao_braco_ancoras(anc_vert) == pytest.approx(0.0)

    anc_apose45 = {
        "UpperTorso": [0.0, 1.30, 0.0], "LeftUpperArm": [0.22, 1.45, 0.0], "LeftLowerArm": [0.50, 1.17, 0.0],
        "RightUpperArm": [-0.22, 1.45, 0.0], "RightLowerArm": [-0.50, 1.17, 0.0],
        "LeftUpperLeg": [0.12, 0.90, 0.0], "RightUpperLeg": [-0.12, 0.90, 0.0],
    }
    assert 12.0 <= animacao_pose.calcular_aducao_braco_ancoras(anc_apose45) <= 26.0

    idle_clipe = animacao.clipes(profiles.carregar("roblox-aa-80"), "r15@1", ["idle"])[0]
    linhas_none, _ = rbx_anim._sequencia_xml(idle_clipe, 0, ancoras=None)
    m_l_none = _extrair_mat3_pose_frame0(linhas_none, "LeftUpperArm")
    m_r_none = _extrair_mat3_pose_frame0(linhas_none, "RightUpperArm")
    assert abs(m_l_none[1]) < 1e-5 and abs(m_r_none[1]) < 1e-5

    linhas_m6d, _ = rbx_anim._sequencia_xml(idle_clipe, 0, ancoras=anc_apose45, modo_rig="motor6d")
    m_l_m6d = _extrair_mat3_pose_frame0(linhas_m6d, "LeftUpperArm")
    m_r_m6d = _extrair_mat3_pose_frame0(linhas_m6d, "RightUpperArm")
    assert abs(m_l_m6d[1]) >= 0.20 and m_l_m6d[1] == pytest.approx(-m_r_m6d[1], abs=1e-5)

    linhas_bone, _ = rbx_anim._sequencia_xml(idle_clipe, 0, ancoras=anc_apose45, modo_rig="bone")
    m_l_bone = _extrair_mat3_pose_frame0(linhas_bone, "LeftUpperArm")
    m_r_bone = _extrair_mat3_pose_frame0(linhas_bone, "RightUpperArm")
    assert m_l_bone[1] == pytest.approx(-m_l_m6d[1], abs=1e-5)
    assert m_r_bone[1] == pytest.approx(-m_r_m6d[1], abs=1e-5)


def test_f05_qc_orientacao_aceita_fallback_sagital_braco_caido() -> None:
    import math
    from forge3d import qc_orientacao

    def _qmul(a: list[float], b: list[float]) -> list[float]:
        (ax, ay, az, aw), (bx, by, bz, bw) = a, b
        return [aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz]

    def _qarm(c1: tuple[float, float, float]) -> list[float]:
        n1 = qc_orientacao._vec3_norm(c1)
        c2 = qc_orientacao._vec3_norm(qc_orientacao._vec3_cross((1.0, 0.0, 0.0), n1))
        c0 = qc_orientacao._vec3_norm(qc_orientacao._vec3_cross(n1, c2))
        tr = c0[0] + n1[1] + c2[2]
        if tr > 0.0:
            s = math.sqrt(tr + 1.0) * 2.0
            return [(n1[2] - c2[1]) / s, (c2[0] - c0[2]) / s, (c0[1] - n1[0]) / s, 0.25 * s]
        if c0[0] > n1[1] and c0[0] > c2[2]:
            s = math.sqrt(1.0 + c0[0] - n1[1] - c2[2]) * 2.0
            return [0.25 * s, (c0[1] + n1[0]) / s, (c2[0] + c0[2]) / s, (n1[2] - c2[1]) / s]
        if n1[1] > c2[2]:
            s = math.sqrt(1.0 + n1[1] - c0[0] - c2[2]) * 2.0
            return [(c0[1] + n1[0]) / s, 0.25 * s, (n1[2] + c2[1]) / s, (c2[0] - c0[2]) / s]
        s = math.sqrt(1.0 + c2[2] - c0[0] - n1[1]) * 2.0
        return [(c2[0] + c0[2]) / s, (n1[2] + c2[1]) / s, 0.25 * s, (c0[1] - n1[0]) / s]

    q_ul, q_ll = _qarm((0.62, -0.51, 0.59)), _qarm((0.66, -0.70, -0.27))
    q_ur, q_lr = _qarm((-0.62, -0.51, 0.59)), _qarm((-0.66, -0.70, -0.27))
    rel_l = _qmul([-q_ul[0], -q_ul[1], -q_ul[2], q_ul[3]], q_ll)
    rel_r = _qmul([-q_ur[0], -q_ur[1], -q_ur[2], q_ur[3]], q_lr)
    gltf = {
        "nodes": [{"name": "Rig", "children": [1]}, {"name": "Hips", "translation": [0.0, 1.0, 0.0], "children": [2, 4]},
                  {"name": "UpperArm.L", "translation": [0.2, 1.4, 0.0], "rotation": q_ul, "children": [3]}, {"name": "LowerArm.L", "translation": [0.0, 0.25, 0.0], "rotation": rel_l},
                  {"name": "UpperArm.R", "translation": [-0.2, 1.4, 0.0], "rotation": q_ur, "children": [5]}, {"name": "LowerArm.R", "translation": [0.0, 0.25, 0.0], "rotation": rel_r}],
        "skins": [{"joints": [1, 2, 3, 4, 5]}], "meshes": [],
    }
    info = {"min": [-0.6, 0.0, -0.3], "max": [0.6, 1.8, 0.3], "bbox_m": [1.2, 1.8, 0.6], "ossos": 5}
    item = {"tipo": "personagem_humanoide", "auto_rig": True, "esqueleto": "godot-humanoid-aa@1"}
    assert qc_orientacao._g2_orientacao(gltf, b"", item, profiles.carregar("godot4-aa"), info)[0] is True
    a25 = math.radians(25.0) * 0.5
    gltf["nodes"][3]["rotation"] = _qmul(rel_l, [0.0, math.sin(a25), 0.0, math.cos(a25)])
    ok_bad, det_bad = qc_orientacao._g2_orientacao(gltf, b"", item, profiles.carregar("godot4-aa"), info)
    assert ok_bad is False and "LowerArm.L" in det_bad.get("ossos_desalinhados", [])
