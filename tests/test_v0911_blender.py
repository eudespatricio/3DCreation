"""Testes TDD independentes (@pytest.mark.blender, janela limpa) para v0.9.11 (D136) — C1, C2, C3 e Opcao 1."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from forge3d import animacao, config, post, profiles

RAIZ = Path(__file__).resolve().parents[1]
_BLENDER_DIR = RAIZ / "blender"


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


_V0911_BLENDER_SCRIPT = """
import json, math, os, sys, bpy, bmesh
from array import array
from mathutils import Vector

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import autorig, autorig_grafo, autorig_marcos, autorig_ossos, bake_pbr, postprocess, postprocess_deform

out = {}

# ==============================================================================
# 1) C1 + C2: End-to-End Native PBR Bake (skip bevel/subsurf, tight cage, preserve native ORM)
# ==============================================================================
try:
    postprocess.limpar_cena()
    # Esfera com raio 2.48 -> bbox ~ (4.96, 4.96, 4.96) -> diag ~ 8.59m (uv_layers criado por padrao)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=2.48)
    obj_nat = bpy.context.active_object
    obj_nat.name = "oni_nat"

    mat_nat = bpy.data.materials.new("mat_nativo_trellis")
    mat_nat.use_nodes = True
    nt = mat_nat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")

    px_src = 64
    n_px = px_src * px_src
    img_bc_src = bpy.data.images.new("nat_bc_src", width=px_src, height=px_src, alpha=False)
    img_bc_src.colorspace_settings.name = "sRGB"
    img_bc_src.pixels.foreach_set(array("f", [0.72, 0.48, 0.38, 1.0] * n_px))

    # PBR nativo saudavel: 85% pele/tecido fosco (met=0.04, rough=0.76) e 15% adorno (met=0.58, rough=0.34)
    # p50_met = 0.04 (<= 0.85), p90_met = 0.58 (< 0.70), std_rough ~ 0.15 (>= 0.03)
    img_met_src = bpy.data.images.new("nat_met_src", width=px_src, height=px_src, alpha=False)
    img_met_src.colorspace_settings.name = "Non-Color"
    buf_m = []
    buf_r = []
    for i in range(n_px):
        if (i % 20) < 17:
            buf_m.extend((0.04, 0.04, 0.04, 1.0))
            buf_r.extend((0.76, 0.76, 0.76, 1.0))
        else:
            buf_m.extend((0.58, 0.58, 0.58, 1.0))
            buf_r.extend((0.34, 0.34, 0.34, 1.0))
    img_met_src.pixels.foreach_set(array("f", buf_m))

    img_rough_src = bpy.data.images.new("nat_rough_src", width=px_src, height=px_src, alpha=False)
    img_rough_src.colorspace_settings.name = "Non-Color"
    img_rough_src.pixels.foreach_set(array("f", buf_r))

    for inp_name, im_s in (("Base Color", img_bc_src), ("Metallic", img_met_src), ("Roughness", img_rough_src)):
        tn = nt.nodes.new("ShaderNodeTexImage")
        tn.image = im_s
        nt.links.new(tn.outputs["Color"], bsdf.inputs[inp_name])
    obj_nat.data.materials.append(mat_nat)

    res_bake = bake_pbr.executar_bake_high_low(
        obj=obj_nat,
        saida_dir=cfg["c1_c2_dir"],
        nome_base="oni_nat",
        px=128,
        px_sub=128,
        limite_triangulos=600,
        reparo_fn=postprocess.reparar_malha,
        decimar_fn=postprocess.decimar,
        suavizar_fn=postprocess.suavizar_por_angulo,
        uv_fn=postprocess.desdobrar_uv,
        origem_textura=cfg["front_png"],
        metallic_hint_png=cfg["false_met_hint_png"],
        roughness_hint_png=cfg["false_rough_hint_png"],
        proteger_superficie=True,
        detalhe_alto={"ativo": True, "chanfro_bevel_m": 0.008},
    )
    out["c1_c2_bake"] = {"ok": True, "res": res_bake}
except Exception as exc:
    out["c1_c2_bake"] = {"ok": False, "erro": str(exc)}

# ==============================================================================
# 2) C2: retopologizar_quadriflow em malha fechada com costuras UV (weld_dist=1e-5 -> 0 nm)
# ==============================================================================
try:
    postprocess.limpar_cena()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=28, ring_count=16, radius=1.0)
    obj_qf = bpy.context.active_object
    obj_qf.name = "qf_uv_seams"

    # Simula vertices duplicados de costura UV do glTF ao longo do equador (abertos em weld_dist=0.0,
    # mas 0 nao-manifold em weld_dist=1e-5).
    bm_q = bmesh.new()
    bm_q.from_mesh(obj_qf.data)
    arestas_costura = [e for e in bm_q.edges if abs(e.verts[0].co.z) < 0.05 and abs(e.verts[1].co.z) < 0.05]
    bmesh.ops.split_edges(bm_q, edges=arestas_costura)
    bm_q.to_mesh(obj_qf.data)
    bm_q.free()
    obj_qf.data.update()

    nm_raw = postprocess._rp._contar_nao_manifold(obj_qf, weld_dist=0.0)
    nm_weld = postprocess._rp._contar_nao_manifold(obj_qf, weld_dist=1e-5)
    tris_antes = postprocess.malha_triangulada(obj_qf)

    chamadas_voxel = {"n": 0}
    orig_voxel = postprocess._rp._remesh_voxel_preservando_partes
    def spy_voxel(o):
        chamadas_voxel["n"] += 1
        return orig_voxel(o)

    postprocess._rp._remesh_voxel_preservando_partes = spy_voxel
    try:
        qf_ok = postprocess.retopologizar_quadriflow(obj_qf, alvo_tris=500, alvo_faces=250)
    finally:
        postprocess._rp._remesh_voxel_preservando_partes = orig_voxel

    nm_depois = postprocess._rp._contar_nao_manifold(obj_qf, weld_dist=0.0)
    out["c2_quadriflow"] = {
        "ok": True,
        "nm_raw": list(nm_raw),
        "nm_weld": list(nm_weld),
        "tris_antes": int(tris_antes),
        "qf_ok": bool(qf_ok),
        "voxel_calls": int(chamadas_voxel["n"]),
        "nm_depois": list(nm_depois),
    }
except Exception as exc:
    out["c2_quadriflow"] = {"ok": False, "erro": str(exc)}

# ==============================================================================
# 3) C3: Burly A-pose r15@1 shoulder anchor + UpperTorso lateral cutoff + idle stretch < 3.5
# ==============================================================================
try:
    postprocess.limpar_cena()
    bm = bmesh.new()
    def box(cx, cy, cz, sx, sy, sz, cuts=2):
        bm_t = bmesh.new()
        bmesh.ops.create_cube(bm_t, size=1.0)
        for v in bm_t.verts:
            v.co.x = v.co.x * sx + cx
            v.co.y = v.co.y * sy + cy
            v.co.z = v.co.z * sz + cz
        if cuts > 0:
            bmesh.ops.subdivide_edges(bm_t, edges=list(bm_t.edges), cuts=cuts, use_grid_fill=True)
        me_t = bpy.data.meshes.new("_tmp")
        bm_t.to_mesh(me_t)
        bm_t.free()
        bm.from_mesh(me_t)
        bpy.data.meshes.remove(me_t)

    # Personagem parrudo A-pose (h = 2.0m): ombros largos e cotovelos/antebracos abduzidos
    for s in (1.0, -1.0):
        box(s * 0.26, 0.02, 0.06, 0.14, 0.22, 0.12, cuts=2)
        box(s * 0.26, 0.00, 0.28, 0.16, 0.16, 0.36, cuts=2)
        box(s * 0.26, 0.00, 0.68, 0.18, 0.18, 0.48, cuts=2)
    box(0.0, 0.0, 0.96, 0.56, 0.26, 0.16, cuts=2)
    box(0.0, 0.0, 1.12, 0.52, 0.26, 0.18, cuts=3)
    box(0.0, 0.0, 1.40, 0.64, 0.30, 0.40, cuts=3)
    for s in (1.0, -1.0):
        box(s * 0.44, 0.00, 1.44, 0.30, 0.26, 0.28, cuts=3)  # Ombro/Deltoide
        box(s * 0.58, 0.08, 1.20, 0.20, 0.20, 0.26, cuts=3)  # Cotovelo (z ~ 1.07..1.33)
        box(s * 0.70, 0.04, 0.98, 0.18, 0.18, 0.28, cuts=3)  # Antebraco (z ~ 0.84..1.12)
        box(s * 0.78, -0.02, 0.72, 0.16, 0.18, 0.26, cuts=3) # Mao/Manopla
    box(0.0, 0.0, 1.64, 0.22, 0.22, 0.14, cuts=1)
    box(0.0, 0.0, 1.82, 0.28, 0.26, 0.28, cuts=1)

    me_b = bpy.data.meshes.new("burly_r15")
    bm.to_mesh(me_b)
    bm.free()
    obj_b = bpy.data.objects.new("burly_r15", me_b)
    bpy.context.collection.objects.link(obj_b)
    bpy.context.view_layer.objects.active = obj_b
    obj_b.select_set(True)
    mod_rem = obj_b.modifiers.new("VoxelWeld", "REMESH")
    mod_rem.mode = "VOXEL"
    mod_rem.voxel_size = 0.042
    bpy.ops.object.modifier_apply(modifier=mod_rem.name)
    postprocess.reparar_malha(obj_b)

    marcos = autorig_marcos.estimar_marcos(obj_b)
    lim_r15 = autorig_grafo._limites_anatomicos(marcos, tem_neck=False)
    if hasattr(autorig_ossos, "_definicoes_ossos"):
        try:
            ossos_def = autorig_ossos._definicoes_ossos(marcos, esqueleto="r15@1")
        except TypeError:
            ossos_def = autorig_ossos._definicoes_ossos("r15@1", marcos)
    else:
        ossos_def = autorig_ossos._construir_ossos("r15@1", marcos)
    osso_map = {o["nome"]: o for o in ossos_def}

    z_probe = 0.5 * (lim_r15["upper_torso_z_min"] + lim_r15["arm_z_cut_lo"])
    v_probe = Vector((lim_r15["tronco_max_x"] + 0.03, 0.04, z_probe))
    perm_ut = autorig_grafo._osso_permitido("UpperTorso", v_probe, marcos, True, tem_neck=False, lim=lim_r15)

    rig_r15, _ = autorig.auto_rigar_humanoide(obj_b, "r15@1", postprocess.criar_armadura)
    vgs = {vg.index: vg.name for vg in obj_b.vertex_groups}
    ut_leak_elbow = 0
    for v in obj_b.data.vertices:
        if abs(v.co.x) > lim_r15["tronco_max_x"] + 0.02 and lim_r15["upper_torso_z_min"] <= v.co.z < lim_r15["arm_z_cut_lo"]:
            for g in v.groups:
                if vgs.get(g.group) == "UpperTorso" and g.weight > 0.05:
                    ut_leak_elbow += 1

    geradas_idle = autorig.aplicar_animacoes_multi(rig_r15, cfg["clipes_idle_r15"])
    deform_idle = postprocess_deform.medir_deformacao_animacao(obj_b, rig_r15, geradas_idle)

    sh_L_x = float(marcos["braco_L"]["shoulder"].x)
    sh_R_x = float(marcos["braco_R"]["shoulder"].x)
    el_L_x = abs(float(marcos.get("elbow_x_L") or marcos["braco_L"]["elbow"].x))
    el_R_x = abs(float(marcos.get("elbow_x_R") or marcos["braco_R"]["elbow"].x))
    out["c3_r15"] = {
        "ok": True,
        "sh_L_x": sh_L_x,
        "sh_R_x": sh_R_x,
        "clav_L_x": float(marcos["braco_L"]["clav_x"]),
        "head_L_x": float(osso_map["LeftUpperArm"]["cabeca"][0]),
        "head_R_x": float(osso_map["RightUpperArm"]["cabeca"][0]),
        "bone_L_head_x": float(rig_r15.data.bones["LeftUpperArm"].head_local.x),
        "bone_R_head_x": float(rig_r15.data.bones["RightUpperArm"].head_local.x),
        "min_elbow_x": min(el_L_x, el_R_x),
        "tronco_max_x": float(lim_r15["tronco_max_x"]),
        "arms_abducted": float(lim_r15["arms_abducted"]),
        "perm_upper_torso_below_cut": bool(perm_ut),
        "ut_leak_elbow": int(ut_leak_elbow),
        "idle_max_stretch": float(deform_idle["max_stretch"]) if deform_idle else 999.0,
        "deform_idle": deform_idle,
    }
except Exception as exc:
    out["c3_r15"] = {"ok": False, "erro": str(exc)}

# ==============================================================================
# 4) Option 1: bake_pbr_nativo_back.aplicar_vista_traseira_pbr_nativo
# ==============================================================================
try:
    import bake_pbr_nativo_back as bnb_back

    postprocess.limpar_cena()
    bpy.ops.mesh.primitive_cube_add(size=1.6)
    obj_back = bpy.context.active_object
    obj_back.name = "oni_back_mesh"

    # Subdivide cubo e atribui UV0 deterministica:
    # faces frontais (+Y, normal.y > 0) em u in [0.08, 0.42], v in [0.15, 0.85]
    # faces traseiras (-Y, normal.y < 0) em u in [0.58, 0.92], v in [0.15, 0.85]
    # demais faces em v in [0.02, 0.10]
    bm_b = bmesh.new()
    bm_b.from_mesh(obj_back.data)
    bmesh.ops.subdivide_edges(bm_b, edges=list(bm_b.edges), cuts=3, use_grid_fill=True)
    bmesh.ops.triangulate(bm_b, faces=list(bm_b.faces))
    bm_b.normal_update()
    uv_lay = bm_b.loops.layers.uv.active or bm_b.loops.layers.uv.new("UVMap")
    for f in bm_b.faces:
        ny = f.normal.y
        for lp in f.loops:
            co = lp.vert.co
            tx = max(0.0, min(1.0, (co.x + 0.8) / 1.6))
            tz = max(0.0, min(1.0, (co.z + 0.8) / 1.6))
            if ny > 0.5:
                lp[uv_lay].uv = (0.08 + tx * 0.34, 0.15 + tz * 0.70)
            elif ny < -0.5:
                lp[uv_lay].uv = (0.58 + tx * 0.34, 0.15 + tz * 0.70)
            else:
                lp[uv_lay].uv = (0.08 + tx * 0.84, 0.02 + tz * 0.08)
    bm_b.to_mesh(obj_back.data)
    bm_b.free()
    obj_back.data.update()

    px_b = 128
    img_bc_b = bpy.data.images.new("oni_back_bc", width=px_b, height=px_b, alpha=False)
    img_bc_b.colorspace_settings.name = "sRGB"
    # Azul frontal inicial: R=40/255 (0.157), G=90/255 (0.353), B=210/255 (0.824)
    img_bc_b.pixels.foreach_set(array("f", [40.0 / 255.0, 90.0 / 255.0, 210.0 / 255.0, 1.0] * (px_b * px_b)))
    img_bc_b.filepath_raw = cfg["opt1_path_bc"]
    img_bc_b.file_format = "PNG"
    img_bc_b.save()

    res_back = bnb_back.aplicar_vista_traseira_pbr_nativo(
        bpy.context.scene,
        obj_back,
        img_bc_b,
        cfg["opt1_path_bc"],
        px_b,
        "oni_back",
        cfg["back_png"],
    )
    out["opt1_back"] = {"ok": True, "res": res_back}
except Exception as exc:
    out["opt1_back"] = {"ok": False, "erro": str(exc)}

open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps(out))
"""


@pytest.fixture(scope="module")
def _v0911_bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    blender = _exigir_blender()
    work_dir = tmp_path_factory.mktemp("v0911_blender_tdd")
    c1_c2_dir = work_dir / "c1_c2_out"
    c1_c2_dir.mkdir()

    front_png = work_dir / "front.png"
    Image.new("RGBA", (64, 64), (184, 122, 96, 255)).save(front_png)

    # Falso-positivo de metallic_hint frontal (ex.: delight antigo classificando pele como bronze 210)
    false_met_hint = work_dir / "false_met_hint.png"
    im_fm = Image.new("L", (64, 64), 0)
    ImageDraw.Draw(im_fm).rectangle((12, 12, 52, 52), fill=220)
    im_fm.save(false_met_hint)

    false_rough_hint = work_dir / "false_rough_hint.png"
    Image.new("L", (64, 64), 75).save(false_rough_hint)

    # Vista traseira Option 1: silhueta vermelha/ambar (215, 65, 45, 255) sobre fundo transparente
    back_png = work_dir / "concept_back.png"
    im_back = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    ImageDraw.Draw(im_back).rectangle((16, 16, 112, 112), fill=(215, 65, 45, 255))
    im_back.save(back_png)

    opt1_path_bc = work_dir / "oni_back_baseColor.png"
    out_json = work_dir / "v0911_report.json"
    cfg_path = work_dir / "cfg.json"
    script_path = work_dir / "run_v0911.py"

    perfil_r15 = profiles.carregar("roblox-aa-80")
    clipes_idle_r15 = animacao.clipes(perfil_r15, "r15@1", ["idle"])

    cfg_path.write_text(
        json.dumps(
            {
                "blender_dir": str(_BLENDER_DIR),
                "c1_c2_dir": str(c1_c2_dir),
                "front_png": str(front_png),
                "false_met_hint_png": str(false_met_hint),
                "false_rough_hint_png": str(false_rough_hint),
                "back_png": str(back_png),
                "opt1_path_bc": str(opt1_path_bc),
                "clipes_idle_r15": clipes_idle_r15,
                "out_json": str(out_json),
            }
        ),
        encoding="utf-8",
    )
    script_path.write_text(_V0911_BLENDER_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(script_path),
            "--",
            str(cfg_path),
        ],
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert proc.returncode == 0, f"Blender v0911 script falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    report = json.loads(out_json.read_text(encoding="utf-8"))
    report["work_dir"] = work_dir
    report["c1_c2_dir"] = c1_c2_dir
    report["opt1_path_bc"] = opt1_path_bc
    return report


@pytest.mark.blender
def test_c1_c2_blender_pbr_nativo_bake_preserva_orm_pula_bevel_e_cage_curto(_v0911_bundle: dict[str, Any]) -> None:
    info = _v0911_bundle["c1_c2_bake"]
    assert info["ok"] is True, f"Falha no bake PBR nativo: {info.get('erro')}"
    bake = info["res"]["bake"]

    assert bake["pbr_nativo_preservado"] is True
    # C2: detalhe_alto em PBR nativo deve pular BEVEL/SUBSURF com motivo="pbr_nativo_organico"
    assert bake["detalhe_alto"]["aplicado"] is False
    assert bake["detalhe_alto"].get("motivo") == "pbr_nativo_organico"

    # C2: cage_extrusion enxuto para PBR nativo: max(0.002, 0.004 * diag) <= 0.04 para diag ~ 8.6
    diag = float(bake["bbox_diag"])
    assert float(bake["cage_extrusion"]) == pytest.approx(max(0.002, 0.004 * diag), abs=1e-4)
    assert float(bake["cage_extrusion"]) <= 0.04

    # C1: PBR nativo saudavel nao aplica delight hints falsos
    assert bake["delight_hints_aplicados"] is False
    orm_path = _v0911_bundle["c1_c2_dir"] / "oni_nat_orm.png"
    with Image.open(orm_path) as im_orm:
        blues = sorted(px[2] for px in im_orm.getdata())
        p50_b = blues[len(blues) // 2]
        assert p50_b <= 30, f"Mediana de Metallic (canal B do ORM) contaminada em PBR nativo: p50_b={p50_b}"


@pytest.mark.blender
def test_c2_blender_retopologizar_quadriflow_costura_uv_sem_voxel_remesh(_v0911_bundle: dict[str, Any]) -> None:
    qf = _v0911_bundle["c2_quadriflow"]
    assert qf["ok"] is True, f"Falha no teste quadriflow: {qf.get('erro')}"
    assert qf["nm_raw"][0] > 0, "Pre-condicao invalida: costura UV deveria abrir bordas em weld_dist=0.0"
    assert qf["nm_weld"] == [0, 0], f"Pre-condicao invalida: malha fechada em weld_dist=1e-5 teve {qf['nm_weld']}"
    assert qf["tris_antes"] <= 60_000
    assert qf["qf_ok"] is True
    assert qf["voxel_calls"] == 0, (
        f"retopologizar_quadriflow invocou _remesh_voxel_preservando_partes ({qf['voxel_calls']}x) em malha estanque com costura UV"
    )
    assert qf["nm_depois"] == [0, 0], f"Malha pos-quadriflow nao foi soldada in-place: nm_depois={qf['nm_depois']}"


@pytest.mark.blender
def test_c3_blender_r15_ombro_ancorado_corte_tronco_e_idle_stretch_lt_35(_v0911_bundle: dict[str, Any]) -> None:
    c3 = _v0911_bundle["c3_r15"]
    assert c3["ok"] is True, f"Falha no rig R15 C3: {c3.get('erro')}"

    # 1) LeftUpperArm e RightUpperArm ancorados na junta do ombro (>= 0.85 * |shoulder.x|), simetricos L/R
    sh_abs = abs(float(c3["sh_L_x"]))
    assert abs(float(c3["head_L_x"])) >= 0.85 * sh_abs, (
        f"LeftUpperArm head.x ({c3['head_L_x']:.3f}) enterrado no torax (clav_x={c3['clav_L_x']:.3f}, shoulder.x={sh_abs:.3f})"
    )
    assert abs(float(c3["head_R_x"])) >= 0.85 * abs(float(c3["sh_R_x"]))
    assert float(c3["head_L_x"]) == pytest.approx(-float(c3["head_R_x"]), abs=1e-4)
    assert abs(float(c3["bone_L_head_x"])) >= 0.85 * sh_abs

    # 2) tronco_max_x estritamente medial a min_elbow_x e _osso_permitido("UpperTorso") == False abaixo de arm_z_cut_lo
    assert float(c3["arms_abducted"]) > 0.5
    assert float(c3["tronco_max_x"]) < float(c3["min_elbow_x"]), (
        f"tronco_max_x ({c3['tronco_max_x']:.3f}) >= min_elbow_x ({c3['min_elbow_x']:.3f})"
    )
    assert c3["perm_upper_torso_below_cut"] is False
    assert c3["ut_leak_elbow"] == 0, f"UpperTorso vazou peso para {c3['ut_leak_elbow']} vertices do cotovelo/antebraco"
    assert float(c3["idle_max_stretch"]) < 3.5, f"Stretch de idle excedeu 3.5: {c3['deform_idle']}"


@pytest.mark.blender
def test_option1_blender_aplicar_vista_traseira_pbr_nativo_isola_frente_e_mescla_costas(
    _v0911_bundle: dict[str, Any],
) -> None:
    opt1 = _v0911_bundle["opt1_back"]
    assert opt1["ok"] is True, f"Falha em bake_pbr_nativo_back.aplicar_vista_traseira_pbr_nativo: {opt1.get('erro')}"
    res = opt1["res"]
    assert res.get("vista_back_aplicada") is True
    assert int(res.get("pixels_mesclados", 0)) > 0
    assert 0.80 <= float(res.get("ganho_luminancia", 0.0)) <= 1.25

    path_bc: Path = _v0911_bundle["opt1_path_bc"]
    assert path_bc.is_file()
    with Image.open(path_bc) as im_bc:
        rgb = im_bc.convert("RGB")
        w, h = rgb.size
        # Regiao UV frontal (+Y): u in [0.18, 0.32], v in [0.35, 0.65] -> deve permanecer azul (40, 90, 210) (< 5/255 delta)
        front_deltas = []
        for y in range(int(h * 0.35), int(h * 0.65)):
            for x in range(int(w * 0.18), int(w * 0.32)):
                r, g, b = rgb.getpixel((x, y))
                front_deltas.append(max(abs(r - 40), abs(g - 90), abs(b - 210)))
        assert max(front_deltas) < 5, f"Pixels frontais (+Y) foram alterados pelo blend traseiro: max_delta={max(front_deltas)}"

        # Regiao UV traseira (-Y): u in [0.68, 0.82], v in [0.35, 0.65] -> deve ter migrado do azul para vermelho/ambar
        back_rb_diffs = []
        for y in range(int(h * 0.35), int(h * 0.65)):
            for x in range(int(w * 0.68), int(w * 0.82)):
                r, _g, b = rgb.getpixel((x, y))
                back_rb_diffs.append(r - b)
        avg_rb = sum(back_rb_diffs) / float(len(back_rb_diffs))
        assert avg_rb > 20.0, f"Pixels traseiros (-Y) nao receberam projecao de concept_back.png: avg(R-B)={avg_rb:.1f}"
