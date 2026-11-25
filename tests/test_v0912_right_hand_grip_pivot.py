"""Independent clean-room tests for v0.9.12 right-handed symmetry, finger grip, handle pivot & auto-anexo."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from forge3d import animacao, animacao_motores, config, post, profiles, publish, qc
from forge3d.providers import blocky

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


def _serie_osso(clipe: dict[str, Any], osso: str, eixo: str) -> list[float]:
    alvo = eixo.upper()
    return [
        sum(float(p["graus"]) for p in ch["poses"] if p["osso"] == osso and str(p["eixo"]).upper() == alvo)
        for ch in clipe["chaves"]
    ]


# ------------------------------------------------------------------ 1) Right-handed rig symmetry (Python)


def test_blocky_left_negative_x_right_positive_x() -> None:
    for nome, _pai, cab, cauda in blocky.OSSOS_HUMANOIDE:
        if nome.endswith(".L"):
            assert cab[0] < 0.0 and cauda[0] < 0.0, f"{nome} deve ter X < 0: {cab}, {cauda}"
        elif nome.endswith(".R"):
            assert cab[0] > 0.0 and cauda[0] > 0.0, f"{nome} deve ter X > 0: {cab}, {cauda}"

    for nome, _pai, cab, cauda in blocky.OSSOS_R15:
        if nome.startswith("Left"):
            assert cab[0] < 0.0 and cauda[0] < 0.0, f"{nome} deve ter X < 0: {cab}, {cauda}"
        elif nome.startswith("Right"):
            assert cab[0] > 0.0 and cauda[0] > 0.0, f"{nome} deve ter X > 0: {cab}, {cauda}"

    cores = blocky._cores("personagem_humanoide", {})
    pecas = blocky._template_humanoide(cores)
    lado_l = [p for p in pecas if p["nome"].endswith("_L")]
    lado_r = [p for p in pecas if p["nome"].endswith("_R")]
    assert len(lado_l) == 9 and len(lado_r) == 9
    for p in lado_l:
        assert p["osso"].endswith(".L")
        assert p["min"][0] < p["max"][0] < 0.0
    for p in lado_r:
        assert p["osso"].endswith(".R")
        assert 0.0 < p["min"][0] < p["max"][0]


# ------------------------------------------------------------------ 2) Limb adduction & softened combat


def test_aducao_walk_run_e_motores_combate_suavizados() -> None:
    perfil = profiles.carregar("godot4")
    por_nome = {c["nome"]: c for c in animacao.clipes(perfil, "godot-humanoid@1", ["walk", "run", "jump", "attack", "slash_combo", "cast"])}

    for marcha in ("walk", "run"):
        zl = _serie_osso(por_nome[marcha], "UpperLeg.L", "Z")
        zr = _serie_osso(por_nome[marcha], "UpperLeg.R", "Z")
        mean_l = sum(zl) / len(zl)
        mean_r = sum(zr) / len(zr)
        assert mean_l < -3.0, f"{marcha} UpperLeg.L Z media esperada < -3: {mean_l}"
        assert mean_r > 3.0, f"{marcha} UpperLeg.R Z media esperada > +3: {mean_r}"

    for nome_m, motores in (
        ("MOTORES_JUMP", animacao_motores.MOTORES_JUMP),
        ("MOTORES_SLASH_COMBO", animacao_motores.MOTORES_SLASH_COMBO),
        ("MOTORES_CAST", animacao_motores.MOTORES_CAST),
    ):
        for sem, eixo, vals in motores:
            if sem in ("braco_e", "braco_d") and eixo == "X":
                assert max(vals) <= 75.0, f"{nome_m} {sem} X > 75: {max(vals)}"

    for clipe_nome in ("jump", "slash_combo", "cast"):
        for osso in ("UpperArm.L", "UpperArm.R"):
            xs = _serie_osso(por_nome[clipe_nome], osso, "X")
            assert max(xs) <= 75.0, f"{clipe_nome} {osso} X pico > 75: {max(xs)}"

    atk_y_sems = {sem for sem, eixo, vals in animacao_motores.MOTORES_ATTACK if eixo == "Y" and any(abs(v) > 0 for v in vals)}
    assert {"quadril", "coluna", "tronco"} <= atk_y_sems
    atk_quadril_z = [vals for sem, eixo, vals in animacao_motores.MOTORES_ATTACK if sem == "quadril" and eixo == "Z"]
    assert all(abs(v) == 0.0 for vals in atk_quadril_z for v in vals)

    hips_z = _serie_osso(por_nome["attack"], "Hips", "Z")
    hips_y = _serie_osso(por_nome["attack"], "Hips", "Y")
    chest_y = _serie_osso(por_nome["attack"], "Chest", "Y")
    assert all(abs(v) < 1e-6 for v in hips_z)
    assert max(hips_y) - min(hips_y) > 20.0
    assert max(chest_y) - min(chest_y) > 10.0


# ------------------------------------------------------------------ 3) Weapon hand finger grip (Python)


def test_weapon_hand_finger_grip_dinamico_e_assim_entre_maos() -> None:
    perfil_aa = profiles.carregar("godot4-aa")
    nomes_clipes = ["idle", "attack", "slash_combo", "block", "walk", "run"]
    clipes = animacao.clipes(perfil_aa, "godot-humanoid-aa@1", nomes_clipes)
    assert [c["nome"] for c in clipes] == nomes_clipes

    dedos_aa = ("Thumb", "Index", "Middle", "Ring", "Little")
    for clipe in clipes:
        for dedo in dedos_aa:
            r_means: list[float] = []
            l_means: list[float] = []
            for seg in (1, 2, 3):
                osso_r = f"{dedo}{seg}.R"
                osso_l = f"{dedo}{seg}.L"
                vr = _serie_osso(clipe, osso_r, "X")
                vl = _serie_osso(clipe, osso_l, "X")
                assert len(vr) >= 16, f"{clipe['nome']} sem chaves suficientes para {osso_r}"
                assert (max(vr) - min(vr)) > 1.0, f"{clipe['nome']} {osso_r} sem variacao dinamica"
                mr = sum(vr) / len(vr)
                ml = sum(vl) / len(vl)
                assert mr > ml + 10.0, f"{clipe['nome']} {osso_r} ({mr:.2f}) <= {osso_l} ({ml:.2f})"
                r_means.append(mr)
                l_means.append(ml)

            finger_mean_r = sum(r_means) / len(r_means)
            limiar = 34.0 if dedo == "Thumb" else 50.0
            assert finger_mean_r >= limiar, f"{clipe['nome']} {dedo}.R media {finger_mean_r:.2f} < {limiar}"


# ------------------------------------------------------------------ 4) Handle pivot constant & publish auto_anexo


def _montar_manifesto_teste(item_override: dict[str, Any], perfil_nome: str = "godot4") -> dict[str, Any]:
    item = {
        "id": "prop.teste",
        "tipo": "prop_equipavel",
        "rota": "blocky",
        "altura_metros": 1.0,
        "pivot": "empunhadura",
        "limite_triangulos": 500,
        "colisao": "none",
        **item_override,
    }
    perfil = profiles.carregar(perfil_nome)
    return publish.montar_manifesto(
        item=item,
        spec_doc={"projeto": "forge3d-test", "_arquivo": "spec.yaml"},
        spec_hash="sha256:0123456789abcdef",
        perfil_nome=perfil_nome,
        perfil=perfil,
        provider={"nome": "blocky", "versao": "1.0.0", "determinism": "deterministico"},
        resultado={"arquivos": [{"caminho": "prop.glb", "papel": "mesh", "nivel": 0, "triangulos": 24, "sha256": "a" * 64, "bytes": 128}]},
        relatorio_qc={"aprovado": True, "gates": [{"id": "G1", "status": "ok"}], "medidas": {"triangulos": 24, "vertices": 16, "bbox_m": [0.2, 1.0, 0.2], "escala_saida": 1.0, "materiais": 1}},
        licenca={"modelo": "CC0", "uso_comercial": True, "notice": "ok"},
        run_id="run-test-01",
        created_at="2026-11-25T18:00:00Z",
    )


def test_fracao_empunhadura_e_auto_anexo_manifesto() -> None:
    assert profiles.FRACAO_EMPUNHADURA == pytest.approx(0.12)

    casos_godot = (
        ({"id": "espada_aco"}, "arma", "Hand.R", "RightGripAttachment"),
        ({"id": "escudo_torre"}, "escudo", "LowerArm.L", "LeftGripAttachment"),
        ({"id": "orbe_arcano"}, "orbe", "Hand.L", "LeftGripAttachment"),
        ({"id": "elmo_ferro"}, "elmo", "Head", "HatAttachment"),
    )
    for item_over, parte_esp, osso_esp, att_esp in casos_godot:
        m = _montar_manifesto_teste(item_over, "godot4")
        assert m["anexo"]["parte"] == parte_esp
        assert m["anexo"]["osso"] == osso_esp
        assert m["anexo"]["attachment_roblox"] == att_esp

    casos_r15 = (
        ({"id": "espada_aco"}, "arma", "RightHand"),
        ({"id": "escudo_torre"}, "escudo", "LeftLowerArm"),
        ({"id": "orbe_arcano"}, "orbe", "LeftHand"),
        ({"id": "elmo_ferro"}, "elmo", "Head"),
    )
    for item_over, parte_esp, osso_r15 in casos_r15:
        m_r15 = _montar_manifesto_teste(item_over, "roblox-r15")
        assert m_r15["anexo"]["parte"] == parte_esp
        assert m_r15["anexo"]["osso"] == osso_r15

    m_override = _montar_manifesto_teste({"id": "espada_magica", "parte": "orbe"}, "godot4")
    assert m_override["anexo"]["parte"] == "orbe"
    assert m_override["anexo"]["osso"] == "Hand.L"

    for tipo_nao_equip in ("prop_estatico", "personagem_humanoide"):
        m_sem = _montar_manifesto_teste({"id": "espada_decorativa", "tipo": tipo_nao_equip, "pivot": "base"}, "godot4")
        assert "anexo" not in m_sem


# ------------------------------------------------------------------ Blender integration bundle


_BLENDER_SCRIPT = """
import json, math, os, sys
from pathlib import Path
import bmesh, bpy
from mathutils import Vector

cfg = json.loads(Path(sys.argv[-1]).read_text(encoding="utf-8"))
sys.path.insert(0, cfg["blender_dir"])
import autorig, postprocess

out = {}

def _add_box(bm, cx, cy, cz, sx, sy, sz):
    ret = bmesh.ops.create_cube(bm, size=1.0)
    for v in ret["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz

def _make_humanoid():
    postprocess.limpar_cena()
    bm = bmesh.new()
    _add_box(bm, 0.0, 0.0, 1.08, 0.28, 0.16, 0.56)
    _add_box(bm, 0.0, 0.0, 1.44, 0.11, 0.11, 0.14)
    _add_box(bm, 0.0, 0.0, 1.67, 0.20, 0.22, 0.34)
    for sx in (-1.0, 1.0):
        _add_box(bm, sx * 0.11, 0.0, 0.42, 0.12, 0.12, 0.84)
        _add_box(bm, sx * 0.38, 0.0, 1.32, 0.46, 0.10, 0.10)
    bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=2, use_grid_fill=True)
    me = bpy.data.meshes.new("Human")
    bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new("Human", me)
    bpy.context.collection.objects.link(obj)
    return obj

rig_syms = {}
for esq in ("godot-humanoid@1", "r15@1", "godot-humanoid-aa@1"):
    obj_h = _make_humanoid()
    rig, _ = autorig.auto_rigar_humanoide(obj_h, esq, postprocess.criar_armadura)
    anc = autorig.extrair_ancoras(rig)
    bones_x = {b.name: float(b.head_local.x) for b in rig.data.bones}
    rig_syms[esq] = {"bones_x": bones_x, "ancoras_x": {k: float(v[0]) for k, v in anc.items()}}
out["humanoid_rigs"] = rig_syms

# Part C: finger grip on godot-humanoid-aa@1 (still active in scene) in attack mid-frame
dedos = ("Thumb", "Index", "Middle", "Ring", "Little")
rest_dist = {}
for lado in ("L", "R"):
    palm_rest = rig.data.bones[f"Hand.{lado}"].head_local
    rest_dist[lado] = {d: float((rig.data.bones[f"{d}3.{lado}"].tail_local - palm_rest).length) for d in dedos}
postprocess.animar(rig, cfg["clipes_attack_aa"])
acao = bpy.data.actions["attack"]
rig.animation_data.action = acao
f0, f1 = int(round(acao.frame_range[0])), int(round(acao.frame_range[1]))
mid_fr = (f0 + f1) // 2
bpy.context.scene.frame_set(mid_fr)
bpy.context.view_layer.update()
atk_dist = {}
for lado in ("L", "R"):
    palm_pose = rig.pose.bones[f"Hand.{lado}"].head
    atk_dist[lado] = {d: float((rig.pose.bones[f"{d}3.{lado}"].tail - palm_pose).length) for d in dedos}
out["finger_grip"] = {"rest": rest_dist, "attack": atk_dist, "mid_frame": mid_fr}

# Part B: winged quadruped symmetry
postprocess.limpar_cena()
bm_w = bmesh.new()
_add_box(bm_w, 0.0, 0.0, 0.72, 0.32, 1.10, 0.36)
_add_box(bm_w, 0.0, 0.72, 0.92, 0.20, 0.38, 0.24)
for sx in (-1.0, 1.0):
    _add_box(bm_w, sx * 0.16, 0.36, 0.30, 0.11, 0.11, 0.60)
    _add_box(bm_w, sx * 0.16, -0.36, 0.30, 0.11, 0.11, 0.60)
    _add_box(bm_w, sx * 0.72, 0.18, 0.94, 0.96, 0.30, 0.08)
bmesh.ops.subdivide_edges(bm_w, edges=list(bm_w.edges), cuts=2, use_grid_fill=True)
me_w = bpy.data.meshes.new("Winged")
bm_w.to_mesh(me_w); bm_w.free()
obj_w = bpy.data.objects.new("Winged", me_w)
bpy.context.collection.objects.link(obj_w)
rig_w, _ = autorig.auto_rigar_por_tipo(obj_w, "winged_mount@1", postprocess.criar_armadura, tipo="criatura_alada")
out["winged_bones_x"] = {b.name: float(b.head_local.x) for b in rig_w.data.bones}

# Part D: asymmetric sword empunhadura pivot + Grip socket
postprocess.limpar_cena()
bm_s = bmesh.new()
_add_box(bm_s, 0.10, 0.0, 0.10, 0.04, 0.04, 0.20)    # narrow handle x=0.10, z=0..0.20
_add_box(bm_s, -0.15, 0.0, 0.25, 0.40, 0.08, 0.06)   # wide asymmetric crossguard x=-0.35..0.05, z=0.22..0.28
_add_box(bm_s, 0.10, 0.0, 0.64, 0.06, 0.02, 0.72)    # blade z=0.28..1.00
bmesh.ops.subdivide_edges(bm_s, edges=list(bm_s.edges), cuts=3, use_grid_fill=True)
bmesh.ops.recalc_face_normals(bm_s, faces=bm_s.faces)
me_s = bpy.data.meshes.new("Sword")
bm_s.to_mesh(me_s); bm_s.free()
obj_s = bpy.data.objects.new("Sword", me_s)
bpy.context.collection.objects.link(obj_s)
bpy.context.view_layer.objects.active = obj_s
obj_s.select_set(True)
obj_s.data.uv_layers.new(name="UVMap")
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.03)
bpy.ops.object.mode_set(mode="OBJECT")
mat = bpy.data.materials.new("Steel")
mat.use_nodes = True
obj_s.data.materials.append(mat)
bruto_glb = cfg["sword_bruto_glb"]
postprocess.exportar(bruto_glb, [obj_s], False, com_animacao=False, export_tangents=False, export_image_format="NONE")

res_sword = postprocess.processar(cfg["sword_job"])
out["sword_resultado"] = res_sword
Path(cfg["out_json"]).write_text(json.dumps(out, default=str), encoding="utf-8")
"""


@pytest.fixture(scope="module")
def _blender_bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    blender = _exigir_blender()
    work = tmp_path_factory.mktemp("v0912_rh_grip")
    bruto_dir, saida_dir = work / "bruto", work / "saida"
    bruto_dir.mkdir()
    saida_dir.mkdir()
    bruto_glb = bruto_dir / "espada_assim.glb"
    (bruto_dir / "manifest.json").write_text(
        json.dumps({"schema": "forge3d/bruto-arquivo@1", "arquivo": bruto_glb.name}),
        encoding="utf-8",
    )
    perfil_g4 = profiles.carregar("godot4")
    sword_item = {
        "id": "espada.assim", "tipo": "prop_equipavel", "parte": "arma", "rota": "importer",
        "altura_metros": 1.0, "pivot": "empunhadura", "limite_triangulos": 2000, "colisao": "none", "lod": [100],
    }
    sword_job = {
        "bruto_dir": str(bruto_dir), "bruto_arquivo": "manifest.json", "saida_dir": str(saida_dir),
        "nome_base": "espada.assim", "nome_arquivo": "espada.assim.glb", "perfil": perfil_g4, "item": sword_item,
    }
    clipes_attack = animacao.clipes(profiles.carregar("godot4-aa"), "godot-humanoid-aa@1", ["attack"])
    cfg_path, out_json, script_path = work / "cfg.json", work / "report.json", work / "run_bundle.py"
    cfg_path.write_text(
        json.dumps({
            "blender_dir": str(_BLENDER_DIR), "clipes_attack_aa": clipes_attack,
            "sword_bruto_glb": str(bruto_glb), "sword_job": sword_job, "out_json": str(out_json),
        }),
        encoding="utf-8",
    )
    script_path.write_text(_BLENDER_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script_path), "--", str(cfg_path)],
        capture_output=True, text=True, timeout=240,
    )
    assert proc.returncode == 0, f"Blender falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    data = json.loads(out_json.read_text(encoding="utf-8"))
    data["saida_dir"] = saida_dir
    data["sword_item"] = sword_item
    data["perfil_g4"] = perfil_g4
    return data


@pytest.mark.blender
def test_blender_autorig_humanoide_e_criatura_simetria_direita(_blender_bundle: dict[str, Any]) -> None:
    rigs = _blender_bundle["humanoid_rigs"]
    for esq in ("godot-humanoid@1", "godot-humanoid-aa@1", "r15@1"):
        bx = rigs[esq]["bones_x"]
        ax = rigs[esq]["ancoras_x"]
        for nome, x in bx.items():
            if nome.endswith(".L") or nome.startswith("Left"):
                assert x < 0.0 and ax[nome] < 0.0, f"{esq} {nome} esperado X < 0, obtido {x}"
            elif nome.endswith(".R") or nome.startswith("Right"):
                assert x > 0.0 and ax[nome] > 0.0, f"{esq} {nome} esperado X > 0, obtido {x}"
        if esq == "r15@1":
            assert bx["LeftUpperLeg"] < 0.0 < bx["RightUpperLeg"]
        else:
            assert bx["UpperLeg.L"] < 0.0 < bx["UpperLeg.R"]
        if esq == "godot-humanoid-aa@1":
            assert bx["Eye.L"] < 0.0 < bx["Eye.R"]

    wx = _blender_bundle["winged_bones_x"]
    for req_l, req_r in (("FrontUpperLeg.L", "FrontUpperLeg.R"), ("BackUpperLeg.L", "BackUpperLeg.R"), ("WingShoulder.L", "WingShoulder.R"), ("WingTip.L", "WingTip.R")):
        assert req_l in wx and req_r in wx
        assert wx[req_l] < 0.0 < wx[req_r]
    for nome, x in wx.items():
        if nome.endswith(".L"):
            assert x < 0.0, f"winged {nome} X={x}"
        elif nome.endswith(".R"):
            assert x > 0.0, f"winged {nome} X={x}"


@pytest.mark.blender
def test_blender_finger_grip_attack_fecha_mao_direita_mais_que_esquerda(_blender_bundle: dict[str, Any]) -> None:
    fg = _blender_bundle["finger_grip"]
    for dedo in ("Thumb", "Index", "Middle", "Ring", "Little"):
        d_r_rest = fg["rest"]["R"][dedo]
        d_r_atk = fg["attack"]["R"][dedo]
        d_l_atk = fg["attack"]["L"][dedo]
        assert d_r_atk < d_r_rest - 0.005, f"{dedo}.R nao fechou em attack: rest={d_r_rest:.4f}, atk={d_r_atk:.4f}"
        assert d_r_atk < d_l_atk - 0.003, f"{dedo}.R ({d_r_atk:.4f}) >= {dedo}.L ({d_l_atk:.4f}) em attack"


@pytest.mark.blender
def test_blender_pivo_empunhadura_espada_assimetrica_socket_grip_e_qc(_blender_bundle: dict[str, Any]) -> None:
    res = _blender_bundle["sword_resultado"]
    saida_dir: Path = _blender_bundle["saida_dir"]
    glb_path = saida_dir / "espada.assim.glb"
    assert glb_path.is_file()

    gltf, binario = qc.ler_glb_bin(glb_path)
    info = qc.analisar(gltf, binario)
    # glTF: Y is Up (height 1.0, pivot at 0.12 -> min_y ~ -0.12, max_y ~ +0.88)
    assert info["min"][1] == pytest.approx(-0.12, abs=0.015)
    assert info["max"][1] == pytest.approx(0.88, abs=0.015)
    # Handle shaft was at x=+0.10 while wide crossguard spanned x=-0.35..0.05 (centroid ~ -0.15).
    # Origin X=0 must sit on the handle shaft, so crossguard extends far into -X (< -0.25) and blade near X=0.
    verts, _ = qc.malha(gltf, binario)
    handle_band_xs = [v[0] for v in verts if -0.07 <= v[1] <= 0.03]
    assert handle_band_xs
    assert sum(handle_band_xs) / len(handle_band_xs) == pytest.approx(0.0, abs=0.03)
    assert info["min"][0] < -0.25

    sockets = res.get("sockets") or res["medidas"].get("sockets") or []
    grips = [s for s in sockets if s["nome"] == "Grip"]
    assert len(grips) == 1
    grip = grips[0]
    node_names = {n.get("name") for n in (gltf.get("nodes") or []) if isinstance(n, dict) and "mesh" in n}
    assert grip["osso"] in node_names
    assert grip["rotacao_quat_wxyz"] == pytest.approx([1.0, 0.0, 0.0, 0.0], abs=1e-5)

    res_qc = {**res, "licenca": {"modelo": "CC0", "uso_comercial": True}}
    rel_qc = qc.verificar(_blender_bundle["sword_item"], _blender_bundle["perfil_g4"], saida_dir, res_qc, escala_saida=1.0)
    falhas = [g for g in rel_qc["gates"] if g["status"] == "falhou"]
    assert rel_qc["aprovado"] is True, f"QC falhou: {falhas}"
