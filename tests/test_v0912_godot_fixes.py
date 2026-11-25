"""Testes independentes (janela limpa) para v0.9.12 — aducao de pernas, attack yaw, UV rosto e bleed/trava pele."""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pytest
from PIL import Image

from blender import bake_pbr_bleed_pele
from forge3d import animacao, animacao_motores, animacao_pose, config, post, profiles, rbx_anim

RAIZ = Path(__file__).resolve().parents[1]
_BLENDER_DIR = RAIZ / "blender"

_ANC_ESTREITO = {
    "Head": [0.0, 1.80, 0.0], "UpperTorso": [0.0, 1.32, 0.0], "LowerTorso": [0.0, 0.94, 0.0],
    "LeftUpperLeg": [-0.11, 0.90, 0.0], "RightUpperLeg": [0.11, 0.90, 0.0],
    "LeftFoot": [-0.11, 0.04, 0.0], "RightFoot": [0.11, 0.04, 0.0],
}
_ANC_HERO = {
    "Head": [0.0, 1.84, 0.0], "UpperTorso": [0.0, 1.35, 0.0], "LowerTorso": [0.0, 0.98, 0.0],
    "LeftUpperLeg": [-0.2265, 0.92, 0.0], "RightUpperLeg": [0.2265, 0.92, 0.0],
    "LeftFoot": [-0.2265, 0.04, 0.0], "RightFoot": [0.2265, 0.04, 0.0],
}
_ANC_BOSS = {
    "Head": [0.0, 2.40, 0.0], "UpperTorso": [0.0, 1.76, 0.0], "LowerTorso": [0.0, 1.28, 0.0],
    "LeftUpperLeg": [-0.3295, 1.20, 0.0], "RightUpperLeg": [0.3295, 1.20, 0.0],
    "LeftFoot": [-0.3295, 0.05, 0.0], "RightFoot": [0.3295, 0.05, 0.0],
}


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _exigir_blender() -> str:
    try:
        ok, _ = post.preflight()
        blender = post.binario() if ok else None
    except Exception:
        blender = None
    if not blender:
        pytest.skip("Blender 4.2 nao disponivel neste ambiente")
    return blender


def _extrair_mat3_pose(linhas: list[str], parte: str, kf_idx: int = 0) -> list[float]:
    root = ET.fromstring("<roblox>" + "\n".join(linhas) + "</roblox>")
    kfs = [it for it in root.iter("Item") if it.get("class") == "Keyframe"]
    assert kf_idx < len(kfs), f"Keyframe {kf_idx} ausente (total={len(kfs)})"
    for it in kfs[kf_idx].iter("Item"):
        if it.get("class") == "Pose" and it.findtext("Properties/string[@name='Name']") == parte:
            cf = it.find("Properties/CoordinateFrame[@name='CFrame']")
            assert cf is not None
            return [float(cf.findtext(f"R{r}{c}") or "0.0") for r in range(3) for c in range(3)]
    raise AssertionError(f"Pose {parte} ausente no Keyframe {kf_idx}")


def _mul_mat3(a: list[float], b: list[float]) -> list[float]:
    return [sum(a[r * 3 + k] * b[k * 3 + c] for k in range(3)) for r in range(3) for c in range(3)]


def _angulo_z_deg(m: list[float]) -> float:
    return math.degrees(math.atan2(m[3], m[0]))


def _serie_osso(clipe: dict[str, Any], osso: str, eixo: str) -> list[float]:
    alvo = eixo.upper()
    return [
        sum(float(p["graus"]) for p in ch["poses"] if p["osso"] == osso and str(p["eixo"]).upper() == alvo)
        for ch in clipe["chaves"]
    ]


# ------------------------------------------------------------------ 1) Proportional leg adduction


def test_aducao_base_marcha_retorna_valores_por_clipe() -> None:
    assert animacao_pose.aducao_base_marcha("walk") == pytest.approx(4.5)
    assert animacao_pose.aducao_base_marcha("  WALK  ") == pytest.approx(4.5)
    assert animacao_pose.aducao_base_marcha("run") == pytest.approx(6.0)
    assert animacao_pose.aducao_base_marcha(" rUn\n") == pytest.approx(6.0)
    for outro in ("idle", "attack", "", "jump"):
        assert animacao_pose.aducao_base_marcha(outro) == pytest.approx(0.0)


def test_calcular_aducao_perna_ancoras_casos_e_proporcoes() -> None:
    assert animacao_pose.calcular_aducao_perna_ancoras(None) == pytest.approx(0.0)
    assert animacao_pose.calcular_aducao_perna_ancoras({}) == pytest.approx(0.0)
    for faltante in ("LeftUpperLeg", "RightUpperLeg", "LeftFoot", "RightFoot"):
        assert animacao_pose.calcular_aducao_perna_ancoras({k: v for k, v in _ANC_HERO.items() if k != faltante}) == pytest.approx(0.0)

    assert animacao_pose.calcular_aducao_perna_ancoras(_ANC_ESTREITO) == pytest.approx(0.0)
    hero = animacao_pose.calcular_aducao_perna_ancoras(_ANC_HERO)
    boss = animacao_pose.calcular_aducao_perna_ancoras(_ANC_BOSS)
    assert 0.0 < hero <= 10.0 and 0.0 < boss <= 10.0 and boss >= hero


@pytest.mark.parametrize("modo_rig", ["motor6d", "bone"])
def test_sequencia_xml_aducao_perna_e_contrarrolagem_pe_walk(modo_rig: str) -> None:
    extra = animacao_pose.calcular_aducao_perna_ancoras(_ANC_HERO)
    assert extra > 0.0
    poses = [
        {"osso": "LeftUpperLeg", "eixo": "Z", "graus": -4.5},
        {"osso": "RightUpperLeg", "eixo": "Z", "graus": 4.5},
        {"osso": "LeftFoot", "eixo": "Z", "graus": 0.0},
        {"osso": "RightFoot", "eixo": "Z", "graus": 0.0},
    ]
    clipe_z = {
        "nome": "walk", "fps": 24, "duracao_s": 1.0, "loop": True,
        "chaves": [{"frame": 0, "segundos": 0.0, "poses": poses}, {"frame": 24, "segundos": 1.0, "poses": poses}],
    }
    linhas_base, _ = rbx_anim._sequencia_xml(clipe_z, 0, mps=0.28, ancoras=None, modo_rig=modo_rig)
    linhas_wide, _ = rbx_anim._sequencia_xml(clipe_z, 0, mps=0.28, ancoras=_ANC_HERO, modo_rig=modo_rig)

    for leg, foot in (("LeftUpperLeg", "LeftFoot"), ("RightUpperLeg", "RightFoot")):
        ang_base = _angulo_z_deg(_extrair_mat3_pose(linhas_base, leg))
        m_foot_b = _extrair_mat3_pose(linhas_base, foot)
        m_leg_w = _extrair_mat3_pose(linhas_wide, leg)
        m_foot_w = _extrair_mat3_pose(linhas_wide, foot)
        ang_leg_w = _angulo_z_deg(m_leg_w)

        assert abs(ang_base) == pytest.approx(4.5, abs=1e-3)
        assert ang_leg_w * ang_base > 0.0
        assert abs(ang_leg_w) == pytest.approx(4.5 + extra, abs=1e-2)
        if modo_rig == "motor6d":
            ang_foot_b = _angulo_z_deg(m_foot_b)
            ang_foot_w = _angulo_z_deg(m_foot_w)
            assert abs(ang_foot_b + ang_base) == pytest.approx(0.0, abs=1e-2)
            assert ang_foot_w * ang_leg_w < 0.0
            assert abs(_angulo_z_deg(_mul_mat3(m_leg_w, m_foot_w))) == pytest.approx(0.0, abs=1e-2)
        else:
            ang_foot_b_y = math.degrees(math.atan2(m_foot_b[2], m_foot_b[0]))
            ang_foot_w_y = math.degrees(math.atan2(m_foot_w[2], m_foot_w[0]))
            assert abs(ang_foot_b_y + ang_base) == pytest.approx(0.0, abs=1e-2)
            assert ang_foot_w_y == pytest.approx(-ang_leg_w, abs=1e-2)
            assert _angulo_z_deg(m_foot_b) == pytest.approx(0.0, abs=1e-2)
            assert _angulo_z_deg(m_foot_w) == pytest.approx(0.0, abs=1e-2)


@pytest.mark.parametrize("nome_clipe", ["idle", "attack"])
@pytest.mark.parametrize("modo_rig", ["motor6d", "bone"])
def test_sequencia_xml_idle_e_attack_sem_aducao_extra_ou_contrarrolagem_pe(nome_clipe: str, modo_rig: str) -> None:
    clipe = animacao.clipes(profiles.carregar("roblox-r15"), "r15@1", [nome_clipe])[0]
    linhas_sem, _ = rbx_anim._sequencia_xml(clipe, 0, mps=0.28, ancoras=None, modo_rig=modo_rig)
    linhas_com, _ = rbx_anim._sequencia_xml(clipe, 0, mps=0.28, ancoras=_ANC_HERO, modo_rig=modo_rig)

    for parte in ("LeftUpperLeg", "RightUpperLeg", "LeftFoot", "RightFoot"):
        for kf_idx in range(len(clipe["chaves"])):
            assert _extrair_mat3_pose(linhas_com, parte, kf_idx) == pytest.approx(
                _extrair_mat3_pose(linhas_sem, parte, kf_idx), abs=1e-5
            )


# ------------------------------------------------------------------ 2) Attack yaw and Boss G16


@pytest.mark.parametrize(("perfil_nome", "esqueleto"), [("godot4", "godot-humanoid@1"), ("roblox-r15", "r15@1")])
def test_attack_yaw_quadril_tronco_cabeca_e_braco_multi_eixo(perfil_nome: str, esqueleto: str) -> None:
    assert [m for m in animacao_motores.MOTORES_ATTACK if m[0] == "quadril" and m[1] == "Z"] == []
    assert any(m[0] == "quadril" and m[1] == "Y" for m in animacao_motores.MOTORES_ATTACK)

    perfil = profiles.carregar(perfil_nome)
    mapa = profiles.retarget(perfil, esqueleto)
    clipe = animacao.clipes(perfil, esqueleto, ["attack"])[0]

    quadril_y, quadril_z = _serie_osso(clipe, mapa["quadril"], "Y"), _serie_osso(clipe, mapa["quadril"], "Z")
    assert max(abs(v) for v in quadril_z) < 1e-9
    assert (max(quadril_y) - min(quadril_y)) >= 10.0 or max(abs(v) for v in quadril_y) >= 10.0

    tronco_y, cabeca_y = _serie_osso(clipe, mapa["tronco"], "Y"), _serie_osso(clipe, mapa["cabeca"], "Y")
    assert max(abs(v) for v in tronco_y) > 1.0
    i_pico = max(range(len(tronco_y)), key=lambda idx: abs(tronco_y[idx]))
    assert cabeca_y[i_pico] * tronco_y[i_pico] < 0.0

    eixos_ativos = [
        ax for ax in ("X", "Y", "Z") if max(abs(v) for v in _serie_osso(clipe, mapa["braco_d"], ax)) > 1.0
    ]
    assert "X" in eixos_ativos and len(eixos_ativos) >= 2
    assert max(sum(abs(v) for v in _serie_osso(clipe, mapa["ombro_d"], ax)) for ax in ("X", "Y", "Z")) > 0.5
    antebraco_x = _serie_osso(clipe, mapa["antebraco_d"], "X")
    assert (max(antebraco_x) - min(antebraco_x)) > 5.0


@pytest.mark.parametrize(
    ("nome_clipe", "motores"),
    [("slash_combo", animacao_motores.MOTORES_SLASH_COMBO), ("cast", animacao_motores.MOTORES_CAST)],
)
def test_motores_slash_combo_e_cast_validos_e_limitados(nome_clipe: str, motores: tuple[Any, ...]) -> None:
    assert len(motores) > 0
    for m in motores:
        assert len(m) == 3 and m[1] in ("X", "Y", "Z") and len(m[2]) > 0
        limite_canal = 30.0 if m[0].startswith("ombro_") else 120.0
        assert max(abs(float(v)) for v in m[2]) <= limite_canal

    for perfil_nome, esqueleto in (("godot4", "godot-humanoid@1"), ("roblox-r15", "r15@1")):
        perfil = profiles.carregar(perfil_nome)
        mapa = profiles.retarget(perfil, esqueleto)
        clipe = animacao.clipes(perfil, esqueleto, [nome_clipe])[0]
        assert clipe["nome"] == nome_clipe and len(clipe["chaves"]) >= 4
        for chave in clipe["chaves"]:
            for pose in chave["poses"]:
                assert abs(float(pose["graus"])) <= 135.0
        for ombro_chave, braco_chave in (("ombro_e", "braco_e"), ("ombro_d", "braco_d")):
            if mapa[ombro_chave] != mapa[braco_chave]:
                for ax in ("X", "Y", "Z"):
                    assert max(abs(v) for v in _serie_osso(clipe, mapa[ombro_chave], ax)) <= 45.0


# ------------------------------------------------------------------ 3) Bleed & skin metallic buffers (non-Blender)


def test_dilatar_fundo_rgba_buf_extrapola_bordas_e_preserva_validos() -> None:
    w, h = 10, 10
    buf = [0.0, 0.0, 0.0, 1.0] * (w * h)
    mask = [False] * (w * h)
    for y in range(3, 7):
        for x in range(3, 7):
            idx = y * w + x
            mask[idx] = True
            buf[idx * 4 : idx * 4 + 4] = [0.72, 0.45, 0.32, 1.0]

    original = list(buf)
    out_buf, preenchidos = bake_pbr_bleed_pele.dilatar_fundo_rgba_buf(buf, mask, w, h, iters_suaves=16)
    assert preenchidos == (w * h - 16)
    for idx, valido in enumerate(mask):
        r, g, b, _ = out_buf[idx * 4 : idx * 4 + 4]
        assert max(r, g, b) > 0.05
        if valido:
            assert out_buf[idx * 4 : idx * 4 + 4] == pytest.approx(original[idx * 4 : idx * 4 + 4], abs=1e-6)

    buf_all = [0.5, 0.3, 0.2, 1.0] * (w * h)
    res_valid, cnt_valid = bake_pbr_bleed_pele.dilatar_fundo_rgba_buf(list(buf_all), [True] * (w * h), w, h)
    assert cnt_valid == 0 and res_valid == pytest.approx(buf_all, abs=1e-6)

    buf_none = [0.0, 0.0, 0.0, 1.0] * (w * h)
    res_inv, cnt_inv = bake_pbr_bleed_pele.dilatar_fundo_rgba_buf(list(buf_none), [False] * (w * h), w, h)
    assert cnt_inv == 0 and res_inv == pytest.approx(buf_none, abs=1e-6)


def test_aplicar_trava_metalico_rosto_buf_pele_vs_elmo_metalico() -> None:
    px = 8
    n_px = px * px
    face_mask = [False] * n_px
    head_mask = [False] * n_px
    for y in range(2, 6):
        for x in range(2, 6):
            face_mask[y * px + x] = head_mask[y * px + x] = True

    hints_skin = [0.85, 0.20, 1.0, 1.0] * n_px
    bc_skin = [0.62, 0.26, 0.16, 1.0] * n_px
    res_skin = bake_pbr_bleed_pele.aplicar_trava_metalico_rosto_buf(
        hints_skin, bc_skin, face_mask, head_mask, px, px, px, bc_linear=True, min_rough_pele=0.52
    )
    assert res_skin["aplicado"] is True and res_skin["rosto_descoberto"] is True
    for idx in range(n_px):
        if face_mask[idx]:
            assert hints_skin[idx * 4] == pytest.approx(0.0, abs=1e-6)
            assert hints_skin[idx * 4 + 1] >= 0.52 - 1e-6
        else:
            assert hints_skin[idx * 4] == pytest.approx(0.85, abs=1e-6)

    hints_helm = [0.90, 0.25, 1.0, 1.0] * n_px
    bc_helm = [0.22, 0.25, 0.30, 1.0] * n_px
    res_helm = bake_pbr_bleed_pele.aplicar_trava_metalico_rosto_buf(
        hints_helm, bc_helm, face_mask, head_mask, px, px, px, bc_linear=True, min_rough_pele=0.52
    )
    assert res_helm["rosto_descoberto"] is False
    for idx in range(n_px):
        if face_mask[idx]:
            assert hints_helm[idx * 4] == pytest.approx(0.90, abs=1e-6)


# ------------------------------------------------------------------ 4) Consolidated Blender tests


_V0912_BLENDER_SCRIPT = r"""
import json, sys, traceback
from array import array
import bpy, bmesh, numpy as np
from mathutils import Vector

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import autorig_anim_sockets as aas, autorig_pose_natural as apn, bake_pbr_bleed_pele as bpb
import postprocess, postprocess_normals_uv as pnu, postprocess_uv_boost as pub

out = {}

def _criar_rig(nome, *, hip_dx=0.452, h=1.84, extras=()):
    arm = bpy.data.armatures.new(nome + "_arm")
    rig = bpy.data.objects.new(nome, arm)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    eb, s = arm.edit_bones, h / 1.84
    def bone(bname, head, tail, parent=None):
        b = eb.new(bname); b.head, b.tail, b.roll = Vector(head), Vector(tail), 0.0
        if parent is not None: b.parent = parent
        return b
    hips = bone("Hips", (0, 0, 0.92 * s), (0, 0, 1.05 * s))
    spine = bone("Spine", (0, 0, 1.05 * s), (0, 0, 1.25 * s), hips)
    chest = bone("Chest", (0, 0, 1.25 * s), (0, 0, 1.50 * s), spine)
    neck = bone("Neck", (0, 0, 1.50 * s), (0, 0, 1.60 * s), chest)
    bone("Head", (0, 0, 1.60 * s), (0, 0, h), neck)
    hx = hip_dx * 0.5
    for lado, sx in (("L", -1.0), ("R", 1.0)):
        sh = bone("Shoulder." + lado, (sx * 0.06, 0, 1.46 * s), (sx * 0.18, 0, 1.46 * s), chest)
        ua = bone("UpperArm." + lado, (sx * 0.18, 0, 1.46 * s), (sx * 0.24, 0, 1.18 * s), sh)
        la = bone("LowerArm." + lado, (sx * 0.24, 0, 1.18 * s), (sx * 0.28, 0, 0.92 * s), ua)
        bone("Hand." + lado, (sx * 0.28, 0, 0.92 * s), (sx * 0.29, 0, 0.80 * s), la)
        ul = bone("UpperLeg." + lado, (sx * hx, 0, 0.92 * s), (sx * hx, 0, 0.50 * s), hips)
        ll = bone("LowerLeg." + lado, (sx * hx, 0, 0.50 * s), (sx * hx, 0, 0.08 * s), ul)
        bone("Foot." + lado, (sx * hx, 0, 0.08 * s), (sx * hx, -0.14, 0.02), ll)
    for bname, head, tail in extras:
        bone(bname, head, tail, chest)
    bpy.ops.object.mode_set(mode="OBJECT"); bpy.context.view_layer.update()
    return rig

try:
    postprocess.limpar_cena()
    r_est = _criar_rig("rig_estreito", hip_dx=0.20, h=1.84)
    r_cri = _criar_rig("rig_criatura", hip_dx=0.50, h=1.84, extras=[("Wing.L", (0.2, 0, 1.4), (0.8, 0, 1.6)), ("MountSeat", (0, 0, 1.3), (0, 0, 1.4))])
    r_lar = _criar_rig("rig_largo", hip_dx=0.452, h=1.84)
    out["aducao_rig"] = {
        "ok": True,
        "estreito": apn.calcular_aducao_perna_rig(r_est),
        "criatura": apn.calcular_aducao_perna_rig(r_cri),
        "largo": apn.calcular_aducao_perna_rig(r_lar),
    }
except Exception:
    out["aducao_rig"] = {"ok": False, "erro": traceback.format_exc()}

try:
    postprocess.limpar_cena()
    rig_walk = _criar_rig("rig_walk", hip_dx=0.452, h=1.84)
    rest_sep = abs(float((rig_walk.matrix_world @ rig_walk.data.bones["Foot.L"].tail_local).x - (rig_walk.matrix_world @ rig_walk.data.bones["Foot.R"].tail_local).x))
    ger = aas.aplicar_animacoes_multi(rig_walk, cfg["clipes_walk_godot"])
    acao = bpy.data.actions["walk"]
    rig_walk.animation_data.action = acao
    f0, f1 = int(round(acao.frame_range[0])), int(round(acao.frame_range[1]))
    seps_x, lat_z = [], []
    for fr in range(f0, f1 + 1):
        bpy.context.scene.frame_set(fr); bpy.context.view_layer.update()
        pL = rig_walk.matrix_world @ rig_walk.pose.bones["Foot.L"].tail
        pR = rig_walk.matrix_world @ rig_walk.pose.bones["Foot.R"].tail
        seps_x.append(abs(float(pL.x - pR.x)))
        for fn in ("Foot.L", "Foot.R"):
            lat_z.append(abs(float((rig_walk.matrix_world.to_3x3() @ rig_walk.pose.bones[fn].matrix.to_3x3()).col[0].normalized().z)))
    out["walk_blender"] = {
        "ok": True, "geradas": list(ger), "rest_sep": rest_sep,
        "min_sep_x": min(seps_x), "mean_sep_x": sum(seps_x) / len(seps_x), "max_sep_x": max(seps_x),
        "max_foot_lat_z": max(lat_z),
    }
except Exception:
    out["walk_blender"] = {"ok": False, "erro": traceback.format_exc()}

def _contar_ilhas_uv_regiao(obj, faces_idx):
    bm = bmesh.new(); bm.from_mesh(obj.data); bm.faces.ensure_lookup_table()
    uv_lay = bm.loops.layers.uv.active
    v2f = {}
    for f in bm.faces:
        for lp in f.loops:
            v2f.setdefault((round(float(lp[uv_lay].uv.x), 4), round(float(lp[uv_lay].uv.y), 4)), []).append(f.index)
    adj = {f.index: set() for f in bm.faces}
    for fs in v2f.values():
        for fi in fs[1:]: adj[fs[0]].add(fi); adj[fi].add(fs[0])
    comp, cid = {}, 0
    for f in bm.faces:
        if f.index in comp: continue
        st = [f.index]; comp[f.index] = cid
        while st:
            cur = st.pop()
            for nb in adj[cur]:
                if nb not in comp: comp[nb] = cid; st.append(nb)
        cid += 1
    n = len({comp[i] for i in faces_idx})
    bm.free()
    return n

try:
    postprocess.limpar_cena()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=24, radius=1.0)
    obj_hum = bpy.context.active_object; obj_hum.name = "humanoide_capsula"
    bm = bmesh.new(); bm.from_mesh(obj_hum.data)
    for v in bm.verts:
        v.co.x *= 0.275; v.co.y *= 0.175; v.co.z = (v.co.z + 1.0) * 0.92
    bm.normal_update(); bm.to_mesh(obj_hum.data); bm.free(); obj_hum.data.update()

    n_faces = len(obj_hum.data.polygons)
    pnu.desdobrar_uv(obj_hum, eh_organico=True)
    sobreposta = bool(pub.tem_uv_sobreposta(obj_hum))
    front_neg = [p.index for p in obj_hum.data.polygons if p.center.z >= 1.84 * 0.86 and p.normal.y < -0.25]
    front_pos = [p.index for p in obj_hum.data.polygons if p.center.z >= 1.84 * 0.86 and p.normal.y > 0.25]
    ilhas_neg, ilhas_pos = _contar_ilhas_uv_regiao(obj_hum, front_neg), _contar_ilhas_uv_regiao(obj_hum, front_pos)

    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, radius=0.9)
    res_esfera = pub.unificar_ilha_uv_rosto_cabeca(bpy.context.active_object)
    out["uv_head"] = {
        "ok": True, "n_faces": int(n_faces), "sobreposta": sobreposta,
        "n_front_neg": len(front_neg), "ilhas_neg": int(ilhas_neg),
        "n_front_pos": len(front_pos), "ilhas_pos": int(ilhas_pos), "res_esfera": res_esfera,
    }
except Exception:
    out["uv_head"] = {"ok": False, "erro": traceback.format_exc()}

try:
    arr = np.zeros((8, 8, 4), dtype=np.float32); arr[:, :, 3] = 1.0
    m = np.zeros((8, 8), dtype=bool); m[2:6, 2:6] = True
    arr[m, 0], arr[m, 1], arr[m, 2] = 0.72, 0.48, 0.36
    out_np, cnt_np = bpb.dilatar_fundo_rgba_buf(arr.reshape(-1).copy(), m.reshape(-1), 8, 8, iters_suaves=8)
    min_rgb_np = float(np.asarray(out_np, dtype=np.float32).reshape(8, 8, 4)[:, :, :3].max(axis=2).min())

    postprocess.limpar_cena()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20, radius=1.0)
    obj_bk = bpy.context.active_object; obj_bk.name = "hum_bake_64"
    bm = bmesh.new(); bm.from_mesh(obj_bk.data)
    for v in bm.verts:
        v.co.x *= 0.275; v.co.y *= 0.175; v.co.z = (v.co.z + 1.0) * 0.92
    uv_lay = bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for lp in f.loops:
            lp[uv_lay].uv = (0.25 + 0.50 * ((lp.vert.co.x + 0.275) / 0.55), 0.25 + 0.50 * (lp.vert.co.z / 1.84))
    bm.normal_update(); bm.to_mesh(obj_bk.data); bm.free(); obj_bk.data.update()

    px = 64
    img_bc = bpy.data.images.new("bk_bc", width=px, height=px, alpha=False)
    img_bc.colorspace_settings.name = "sRGB"
    bc_buf = [0.0, 0.0, 0.0, 1.0] * (px * px)
    for y in range(16, 48):
        for x in range(16, 48):
            o = (y * px + x) * 4; bc_buf[o : o + 4] = [0.62, 0.26, 0.16, 1.0]
    img_bc.pixels.foreach_set(array("f", bc_buf))

    img_hints = bpy.data.images.new("bk_hints", width=px, height=px, alpha=False)
    img_hints.colorspace_settings.name = "Non-Color"
    img_hints.pixels.foreach_set(array("f", [0.85, 0.20, 1.0, 1.0] * (px * px)))

    res_trava = bpb.travar_metalico_rosto_pele(bpy.context.scene, obj_bk, img_hints, img_bc, px, "hum_64", tipo_item="personagem_humanoide")
    hints_pos = array("f", [0.0] * (px * px * 4)); img_hints.pixels.foreach_get(hints_pos)
    n_met_zero = sum(1 for i in range(px * px) if hints_pos[i * 4] < 0.01)
    _, res_bleed = bpb.dilatar_fundo_basecolor(bpy.context.scene, obj_bk, img_bc, cfg["bleed_bc_png"], px, "hum_64")
    out["bleed_skin"] = {"ok": True, "cnt_np": int(cnt_np), "min_rgb_np": min_rgb_np, "res_trava": res_trava, "n_met_zero": int(n_met_zero), "res_bleed": res_bleed}
except Exception:
    out["bleed_skin"] = {"ok": False, "erro": traceback.format_exc()}

open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps(out, default=str))
"""


@pytest.fixture(scope="module")
def _v0912_blender_bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    blender = _exigir_blender()
    work_dir = tmp_path_factory.mktemp("v0912_blender")
    cfg_path, out_json = work_dir / "cfg.json", work_dir / "report.json"
    bleed_bc_png, script_path = work_dir / "hum_64_baseColor.png", work_dir / "run_v0912.py"
    clipes_walk = animacao.clipes(profiles.carregar("godot4"), "godot-humanoid@1", ["walk"])
    cfg_path.write_text(
        json.dumps({"blender_dir": str(_BLENDER_DIR), "clipes_walk_godot": clipes_walk, "bleed_bc_png": str(bleed_bc_png), "out_json": str(out_json)}),
        encoding="utf-8",
    )
    script_path.write_text(_V0912_BLENDER_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script_path), "--", str(cfg_path)],
        capture_output=True, text=True, timeout=240,
    )
    assert proc.returncode == 0, f"Blender v0912 falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    report = json.loads(out_json.read_text(encoding="utf-8"))
    report["bleed_bc_png"] = bleed_bc_png
    return report


@pytest.mark.blender
def test_blender_calcular_aducao_perna_rig_classifica_estreito_criatura_e_largo(_v0912_blender_bundle: dict[str, Any]) -> None:
    info = _v0912_blender_bundle["aducao_rig"]
    assert info["ok"] is True, info.get("erro")
    assert info["estreito"]["aplicavel"] is False and float(info["estreito"]["extra_graus"]) == pytest.approx(0.0)
    assert info["criatura"]["aplicavel"] is False and float(info["criatura"]["extra_graus"]) == pytest.approx(0.0)
    assert info["largo"]["aplicavel"] is True and float(info["largo"]["extra_graus"]) > 4.0


@pytest.mark.blender
def test_blender_aplicar_animacoes_multi_walk_reduz_separacao_pes_com_sola_nivelada(_v0912_blender_bundle: dict[str, Any]) -> None:
    info = _v0912_blender_bundle["walk_blender"]
    assert info["ok"] is True, info.get("erro")
    assert "walk" in [g["nome"] for g in info["geradas"]]
    assert float(info["rest_sep"]) == pytest.approx(0.452, abs=1e-3)
    assert float(info["mean_sep_x"]) < 0.28 and float(info["min_sep_x"]) < 0.28
    assert float(info["max_sep_x"]) < float(info["rest_sep"]) - 0.10
    assert float(info["max_foot_lat_z"]) < 0.15


@pytest.mark.blender
def test_blender_desdobrar_uv_humanoide_sem_sobreposicao_e_rosto_unificado(_v0912_blender_bundle: dict[str, Any]) -> None:
    info = _v0912_blender_bundle["uv_head"]
    assert info["ok"] is True, info.get("erro")
    assert int(info["n_faces"]) >= 450 and info["sobreposta"] is False
    assert int(info["n_front_neg"]) > 0 and int(info["ilhas_neg"]) <= 2
    assert int(info["n_front_pos"]) > 0 and int(info["ilhas_pos"]) <= 2
    assert info["res_esfera"]["aplicado"] is False


@pytest.mark.blender
def test_blender_bake_bleed_numpy_e_trava_metalico_rosto_pele(_v0912_blender_bundle: dict[str, Any]) -> None:
    info = _v0912_blender_bundle["bleed_skin"]
    assert info["ok"] is True, info.get("erro")
    assert int(info["cnt_np"]) == 48 and float(info["min_rgb_np"]) > 0.1
    assert info["res_trava"]["aplicado"] is True and info["res_trava"]["rosto_descoberto"] is True
    assert int(info["n_met_zero"]) > 0

    path_bc: Path = _v0912_blender_bundle["bleed_bc_png"]
    assert path_bc.is_file()
    with Image.open(path_bc) as im_bc:
        pretos = sum(1 for r, g, b in im_bc.convert("RGB").getdata() if r == 0 and g == 0 and b == 0)
        assert pretos == 0, f"Restaram {pretos} pixels #000000 apos dilatar_fundo_basecolor"
