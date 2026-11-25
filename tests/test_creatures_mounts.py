"""Testes de quadrupedes e montarias aladas: PCA -Z frente, 4-seg wings, MountSeat e clipes."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from forge3d import animacao, profiles

RAIZ = Path(__file__).resolve().parent.parent
GODOT = profiles.carregar("godot4")


def _blender_bin() -> str:
    bin_blender = shutil.which("blender")
    if not bin_blender:
        pytest.skip("blender nao disponivel no PATH")
    return bin_blender


def test_godot4_profile_registers_quadruped_and_winged_mount():
    # Mantem godot-humanoid@1 intacto
    assert len(GODOT["rig"]["mapas"]["godot-humanoid@1"]) == 23
    assert set(GODOT["rig"]["retarget"]["godot-humanoid@1"]) >= {"quadril", "coluna", "tronco", "cabeca"}

    for esq, expected_len in (("quadruped@1", 23), ("winged_mount@1", 31)):
        mapa_ossos = GODOT["rig"]["mapas"][esq]
        ret = GODOT["rig"]["retarget"][esq]
        assert len(mapa_ossos) == expected_len
        assert "MountSeat" in mapa_ossos
        assert "Jaw" in mapa_ossos
        assert {"Tail1", "Tail2", "Tail3"} <= set(mapa_ossos)
        assert {"FrontUpperLeg.L", "FrontUpperLeg.R", "BackUpperLeg.L", "BackUpperLeg.R"} <= set(mapa_ossos)
        assert ret["sela"] == "MountSeat"
        assert ret["mandibula"] == "Jaw"
    assert {"WingShoulder.L", "WingArm.L", "WingForearm.L", "WingTip.L"} <= set(
        GODOT["rig"]["mapas"]["winged_mount@1"]
    )
    assert {"WingShoulder.R", "WingArm.R", "WingForearm.R", "WingTip.R"} <= set(
        GODOT["rig"]["mapas"]["winged_mount@1"]
    )


def test_creature_mount_clips_and_phase_propagation():
    clips_q = {
        c["nome"]: c
        for c in animacao.clipes(
            GODOT, "quadruped@1", ["idle", "walk", "gallop", "bite", "roar", "death"]
        )
    }
    assert set(clips_q) == {"idle", "walk", "gallop", "bite", "roar", "death"}
    assert clips_q["gallop"]["loop"] is True
    assert clips_q["bite"]["loop"] is False
    assert clips_q["roar"]["loop"] is False
    assert clips_q["death"]["loop"] is False

    # Mandibula abre negativamente em bite e roar
    min_jaw_bite = min(
        p["graus"] for ch in clips_q["bite"]["chaves"] for p in ch["poses"] if p["osso"] == "Jaw"
    )
    min_jaw_roar = min(
        p["graus"] for ch in clips_q["roar"]["chaves"] for p in ch["poses"] if p["osso"] == "Jaw"
    )
    assert min_jaw_bite < -25.0
    assert min_jaw_roar < -35.0

    # Serpentine tail wave defasada entre Tail1, Tail2, Tail3
    tail_t0 = {
        p["osso"]: p["graus"]
        for p in clips_q["walk"]["chaves"][0]["poses"]
        if p["osso"].startswith("Tail")
    }
    assert tail_t0["Tail1"] != tail_t0["Tail2"] or tail_t0["Tail2"] != tail_t0["Tail3"]

    clips_w = {
        c["nome"]: c
        for c in animacao.clipes(
            GODOT,
            "winged_mount@1",
            ["idle", "walk", "gallop", "wing_flap", "glide", "bite", "roar", "death"],
        )
    }
    assert set(clips_w) == {"idle", "walk", "gallop", "wing_flap", "glide", "bite", "roar", "death"}
    flap = clips_w["wing_flap"]
    assert flap["loop"] is True
    assert 16 <= len(flap["chaves"]) <= 32
    # Propagacao de fase ao longo dos 4 segmentos da asa e espelho L/R
    picos_l: dict[str, int] = {}
    for seg in ("WingShoulder.L", "WingArm.L", "WingForearm.L", "WingTip.L"):
        serie = [
            next(p["graus"] for p in ch["poses"] if p["osso"] == seg)
            for ch in flap["chaves"][:-1]
        ]
        picos_l[seg] = max(range(len(serie)), key=lambda i: serie[i])
        assert max(serie) - min(serie) > 35.0
    assert picos_l["WingShoulder.L"] != picos_l["WingTip.L"]


_EXPR_CREATURES_BLENDER = """
import json, math, sys
from pathlib import Path
import bmesh, bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
sys.path.insert(0, argv[0])
clipes_winged = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
out_json = Path(argv[2])
import autorig

def _limpar():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

def _criar_armadura(ossos):
    arm = bpy.data.armatures.new("RigCriatura")
    rig = bpy.data.objects.new("RigCriatura", arm)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    ebs = {}
    for o in ossos:
        eb = arm.edit_bones.new(o["nome"])
        eb.head = Vector(o["cabeca"])
        eb.tail = Vector(o["cauda"])
        ebs[o["nome"]] = eb
    for o in ossos:
        if o["pai"]:
            ebs[o["nome"]].parent = ebs[o["pai"]]
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig

def _cilindro(bm, a, b, r, seg=8, rings=6):
    va, vb = Vector(a), Vector(b)
    eixo = vb - va
    comp = max(eixo.length, 1e-4)
    d = eixo.normalized()
    ref = Vector((0, 1, 0)) if abs(d.y) < 0.9 else Vector((1, 0, 0))
    u = d.cross(ref).normalized()
    v = d.cross(u).normalized()
    aneis = []
    for ri in range(rings + 1):
        t = ri / float(rings)
        c = va + d * (comp * t)
        aneis.append([bm.verts.new(c + (u * math.cos(2 * math.pi * si / seg) + v * math.sin(2 * math.pi * si / seg)) * r) for si in range(seg)])
    for ri in range(rings):
        for si in range(seg):
            sn = (si + 1) % seg
            bm.faces.new((aneis[ri][si], aneis[ri][sn], aneis[ri + 1][sn], aneis[ri + 1][si]))
    bm.faces.new(list(reversed(aneis[0])))
    bm.faces.new(aneis[-1])

def _criar_quadrupede(rot_z_deg=0.0, com_asas=False):
    _limpar()
    bm = bmesh.new()
    # Tronco horizontal ao longo de +Y (frente)
    _cilindro(bm, (0, -0.55, 0.72), (0, 0.55, 0.78), 0.22, seg=12, rings=8)
    # Pescoco e cabeca elevados em +Y (focinho mais alto que cauda)
    _cilindro(bm, (0, 0.50, 0.80), (0, 0.82, 1.18), 0.12, seg=10, rings=6)
    _cilindro(bm, (0, 0.78, 1.20), (0, 1.15, 1.16), 0.11, seg=10, rings=6)
    # Cauda fina para tras (-Y)
    _cilindro(bm, (0, -0.55, 0.72), (0, -1.05, 0.60), 0.055, seg=8, rings=6)
    # 4 patas
    for y_leg in (0.42, -0.42):
        for sx in (1.0, -1.0):
            _cilindro(bm, (sx * 0.16, y_leg, 0.65), (sx * 0.16, y_leg, 0.02), 0.06, seg=8, rings=6)
    # Asas largas em +-X (envergadura maior que comprimento do tronco!)
    if com_asas:
        for sx in (1.0, -1.0):
            _cilindro(bm, (sx * 0.18, 0.28, 0.88), (sx * 1.65, 0.05, 1.28), 0.07, seg=8, rings=8)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("Criatura")
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("Criatura", me)
    bpy.context.collection.objects.link(obj)
    obj.rotation_euler.z = math.radians(rot_z_deg)
    return obj

def _checar_pesos(obj):
    sem_peso = 0
    max_inf = 0
    for v in obj.data.vertices:
        gs = [g.weight for g in v.groups if g.weight > 1e-6]
        if not gs:
            sem_peso += 1
        max_inf = max(max_inf, len(gs))
    return sem_peso, max_inf

# 1. Quadrupede invertido 180 deg (-Y inicialmente) -> PCA alinha focinho para +Y_bl
q_inv = _criar_quadrupede(rot_z_deg=180.0, com_asas=False)
rig_q, _ = autorig.auto_rigar_por_tipo(q_inv, "quadruped@1", _criar_armadura, tipo="criatura_quadrupede")
sp_q, mi_q = _checar_pesos(q_inv)
bones_q = {b.name: {"head": list(b.head_local), "tail": list(b.tail_local)} for b in rig_q.data.bones}
mods_q = [m for m in q_inv.modifiers if m.type == "ARMATURE"]
q_dq = bool(mods_q and mods_q[0].use_deform_preserve_volume)
socks_q = autorig.extrair_sockets(rig_q, q_inv)

# 2. Montaria alada rotacionada 90 deg (+X inicialmente) com envergadura > comprimento
w_rot = _criar_quadrupede(rot_z_deg=90.0, com_asas=True)
rig_w, _ = autorig.auto_rigar_por_tipo(w_rot, "winged_mount@1", _criar_armadura, tipo="criatura_alada")
sp_w, mi_w = _checar_pesos(w_rot)
bones_w = {b.name: {"head": list(b.head_local), "tail": list(b.tail_local)} for b in rig_w.data.bones}
socks_w = autorig.extrair_sockets(rig_w, w_rot)
autorig.aplicar_animacoes_multi(rig_w, clipes_winged)
bezier_cnt = sum(1 for a in bpy.data.actions for fc in a.fcurves for kp in fc.keyframe_points if kp.interpolation == "BEZIER")

out_json.write_text(json.dumps({
    "q_ossos": sorted(bones_q),
    "q_head_y": bones_q["Head"]["tail"][1],
    "q_hips_y": bones_q["Hips"]["head"][1],
    "q_tail_y": bones_q["Tail3"]["tail"][1],
    "q_sem_peso": sp_q,
    "q_max_inf": mi_q,
    "q_dq": q_dq,
    "q_sockets": socks_q,
    "w_ossos": sorted(bones_w),
    "w_head_y": bones_w["Head"]["tail"][1],
    "w_tail_y": bones_w["Tail3"]["tail"][1],
    "w_wing_l_x": bones_w["WingTip.L"]["tail"][0],
    "w_wing_r_x": bones_w["WingTip.R"]["tail"][0],
    "w_sem_peso": sp_w,
    "w_max_inf": mi_w,
    "w_sockets": socks_w,
    "w_bezier": bezier_cnt,
}), encoding="utf-8")
"""


@pytest.mark.blender
def test_creatures_mounts_blender_pca_skinning_and_sockets(tmp_path: Path):
    blender = _blender_bin()
    clipes_w = animacao.clipes(GODOT, "winged_mount@1", ["idle", "gallop", "wing_flap", "glide"])
    in_json = tmp_path / "clipes_w.json"
    out_json = tmp_path / "criaturas.json"
    in_json.write_text(json.dumps(clipes_w), encoding="utf-8")

    proc = subprocess.run(
        [
            blender,
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python-expr",
            _EXPR_CREATURES_BLENDER,
            "--",
            str(RAIZ / "blender"),
            str(in_json),
            str(out_json),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    d = json.loads(out_json.read_text(encoding="utf-8"))

    # Quadrupede corrigido de 180 deg para focinho +Y_bl (-Z_gltf) e cauda -Y_bl (+Z_gltf)
    assert d["q_ossos"] == sorted(GODOT["rig"]["mapas"]["quadruped@1"])
    assert d["q_head_y"] > d["q_hips_y"] > d["q_tail_y"]
    assert d["q_sem_peso"] == 0
    assert 1 <= d["q_max_inf"] <= 4
    assert d["q_dq"] is True
    q_socks = {s["nome"]: s for s in d["q_sockets"]}
    assert "MountSeat" in q_socks
    assert q_socks["MountSeat"]["rotacao_quat_wxyz"] == pytest.approx([1.0, 0.0, 0.0, 0.0], abs=1e-4)
    assert q_socks["MountSeat"]["frente_local"] == [0.0, 0.0, -1.0]

    # Montaria alada corrigida apesar da envergadura larga, com 31 ossos e asas L/R simetricas
    assert d["w_ossos"] == sorted(GODOT["rig"]["mapas"]["winged_mount@1"])
    assert d["w_head_y"] > d["w_tail_y"]
    assert d["w_wing_l_x"] < -0.8 and d["w_wing_r_x"] > 0.8
    assert d["w_wing_l_x"] == pytest.approx(-d["w_wing_r_x"], abs=0.05)
    assert d["w_sem_peso"] == 0
    assert 1 <= d["w_max_inf"] <= 4
    w_socks = {s["nome"]: s for s in d["w_sockets"]}
    assert {"Back", "Head", "MountSeat"} <= set(w_socks)
    assert d["w_bezier"] > 50


@pytest.mark.blender
def test_gerar_criatura_anatomica_4_patas_e_asas_no_blender(tmp_path: Path):
    blender = _blender_bin()
    job_path = tmp_path / "criatura_job.json"
    glb_path = tmp_path / "bruto.glb"
    meta_path = tmp_path / "modelo.json"
    job_path.write_text(
        json.dumps(
            {
                "acao": "gerar_criatura",
                "tipo": "criatura_alada",
                "esqueleto": "winged_mount@1",
                "asas": True,
                "saida_dir": str(tmp_path),
                "saida_glb": str(glb_path),
                "saida_meta": str(meta_path),
            }
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            blender,
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(RAIZ / "blender" / "organic_sculpt.py"),
            "--",
            "--modo",
            "criatura",
            str(job_path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert glb_path.is_file()
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["frente"] == "+Y"
    assert meta["canonicalizar"] is False
    assert meta["solda"]["componentes_depois"] == 1
    assert meta["dimensoes_bl"]["largura_x"] > 2.5
    assert meta["dimensoes_bl"]["comprimento_y"] > 2.5
    assert meta["dimensoes_bl"]["altura_z"] > 1.2

    # Verifica no Blender que o GLB possui 4 patas apoiadas no solo (4 quadrantes X/Y em Z<=0.06) e normais suaves
    check_json = tmp_path / "check_criatura.json"
    expr_check = """
import json, sys, bpy
argv = sys.argv[sys.argv.index("--") + 1:]
glb_p, out_p = argv[0], argv[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb_p)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
obj = meshes[0]
verts = [obj.matrix_world @ v.co for v in obj.data.vertices]
z_min = min(v.z for v in verts)
low = [v for v in verts if v.z <= z_min + 0.06]
quadrantes = {
    "fl": any(v.x > 0.12 and v.y > 0.20 for v in low),
    "fr": any(v.x < -0.12 and v.y > 0.20 for v in low),
    "bl": any(v.x > 0.12 and v.y < -0.20 for v in low),
    "br": any(v.x < -0.12 and v.y < -0.20 for v in low),
}
front_z = max(v.z for v in verts if v.y > 0.6)
tail_z = max(v.z for v in verts if v.y < -0.8)
smooth_ratio = sum(1 for p in obj.data.polygons if p.use_smooth) / max(1, len(obj.data.polygons))
with open(out_p, "w", encoding="utf-8") as f:
    json.dump({"quadrantes": quadrantes, "front_z": front_z, "tail_z": tail_z, "smooth_ratio": smooth_ratio}, f)
"""
    proc_c = subprocess.run(
        [
            blender,
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python-expr",
            expr_check,
            "--",
            str(glb_path),
            str(check_json),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc_c.returncode == 0, proc_c.stdout + "\n" + proc_c.stderr
    chk = json.loads(check_json.read_text(encoding="utf-8"))
    assert chk["quadrantes"] == {"fl": True, "fr": True, "bl": True, "br": True}
    assert chk["front_z"] > chk["tail_z"] + 0.4
    assert chk["smooth_ratio"] > 0.99

