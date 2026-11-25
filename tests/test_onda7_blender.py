"""Onda 7 (testes independentes, @pytest.mark.blender): bake de rest-pose natural, idle sem flutuar, walk/run aduzidos,
ancoras Y-up, GAP-064/065/067 em Blender 4.2 headless. Asserts derivados so do contrato congelado da Onda 7.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from forge3d import animacao, config, post, profiles
from forge3d.rbx_xml import JOINT_R15

RAIZ = Path(__file__).resolve().parents[1]
_BLENDER_DIR = RAIZ / "blender"
R15_16 = set(JOINT_R15) | {"HumanoidRootPart"}


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


_SCRIPT = r'''
import json, math, os, sys, traceback
import bpy, bmesh
from mathutils import Vector

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import autorig, autorig_marcos, autorig_ossos, autorig_pesos_limites as apl
import autorig_pose_natural as apn, autorig_anim_sockets as aas
import postprocess, postprocess_deform, postprocess_export_pipe as pep

NOMES = {
    "r15@1": (("LeftUpperArm", "LeftLowerArm"), ("RightUpperArm", "RightLowerArm")),
    "godot-humanoid@1": (("UpperArm.L", "LowerArm.L"), ("UpperArm.R", "LowerArm.R")),
}

def build(name, arm_deg=45.0, forearm_deg=None, horns=False, pauldron=False, wide_hips=False):
    """Humanoide procedural (h~1.94 m) em A-pose; boxes soldados por remesh voxel."""
    bm = bmesh.new()
    def box(c, sz):
        for v in bmesh.ops.create_cube(bm, size=1.0)["verts"]:
            v.co = Vector((v.co.x * sz[0] + c[0], v.co.y * sz[1] + c[1], v.co.z * sz[2] + c[2]))
    def seg(p0, p1, w, d):
        p0, p1 = Vector(p0), Vector(p1)
        q = (p1 - p0).normalized().to_track_quat("Z", "Y")
        mid, ln = (p0 + p1) * 0.5, (p1 - p0).length
        for v in bmesh.ops.create_cube(bm, size=1.0)["verts"]:
            v.co = q @ Vector((v.co.x * w, v.co.y * d, v.co.z * ln)) + mid
    lx = 0.30 if wide_hips else 0.16
    box((0, 0, 0.98), (2 * lx + 0.22, 0.24, 0.20)); box((0, 0, 1.12), (0.40, 0.22, 0.16)); box((0, 0, 1.40), (0.50, 0.26, 0.40))
    box((0, 0, 1.66), (0.12, 0.12, 0.12)); box((0, 0, 1.80), (0.22, 0.22, 0.28))
    aa = math.radians(arm_deg); fa = math.radians(arm_deg if forearm_deg is None else forearm_deg)
    for s in (1.0, -1.0):
        box((s * lx, 0.04, 0.05), (0.14, 0.26, 0.10))
        seg((s * lx, 0, 0.10), (s * lx, 0, 0.50), 0.13, 0.13); seg((s * lx, 0, 0.46), (s * lx, 0, 0.96), 0.17, 0.17)
        sh = Vector((s * 0.30, 0, 1.55)); el = sh + Vector((s * math.sin(aa), 0, -math.cos(aa))) * 0.34
        dfa = Vector((s * math.sin(fa), 0, -math.cos(fa))); wr = el + dfa * 0.30
        box((s * 0.33, 0, 1.50), (0.18, 0.20, 0.20)); seg(sh, el, 0.12, 0.12); seg(el, wr, 0.10, 0.10); seg(wr, wr + dfa * 0.12, 0.09, 0.05)
        if pauldron: box((s * 0.30, 0, 1.56), (0.22, 0.24, 0.10))
        if horns: seg((s * 0.12, 0, 1.74), (s * 0.52, 0, 1.88), 0.10, 0.10)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj; obj.select_set(True)
    mod = obj.modifiers.new("VoxelWeld", "REMESH"); mod.mode = "VOXEL"; mod.voxel_size = 0.042
    bpy.ops.object.modifier_apply(modifier=mod.name)
    postprocess.reparar_malha(obj)
    return obj

def rig_up(esq, **kw):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    obj = build("h_" + esq.split("@")[0], **kw)
    marcos = autorig_marcos.estimar_marcos(obj)
    rig, _ = autorig.auto_rigar_humanoide(obj, esq, postprocess.criar_armadura)
    return obj, rig, marcos

def rest(rig, nome, tail=False):
    b = rig.data.bones[nome]
    return rig.matrix_world @ (b.tail_local if tail else b.head_local)

def thetas(rig, esq="r15@1"):
    r = {}
    for lado, (up, lo) in zip("LR", NOMES[esq]):
        h = rest(rig, up)
        for chave, f in (("up", rest(rig, lo)), ("tot", rest(rig, lo, True))):
            r[f"{chave}_{lado}"] = math.degrees(math.atan2(abs(f.x - h.x), max(h.z - f.z, 1e-6)))
    return r

def dom_nome(obj, v):
    vgs = {vg.index: vg.name for vg in obj.vertex_groups}
    pesos = [(g.weight, vgs[g.group]) for g in v.groups if g.group in vgs and g.weight > 1e-5]
    return max(pesos)[1] if pesos else None

def snap(obj):
    vgs = {vg.index: vg.name for vg in obj.vertex_groups}
    zs = [v.co.z for v in obj.data.vertices]
    pesos = [sorted((vgs[g.group], round(g.weight, 4)) for g in v.groups if g.group in vgs) for v in obj.data.vertices]
    return {"h": max(zs) - min(zs), "zmin": min(zs), "n": len(zs), "grupos": sorted(vgs.values()), "pesos": pesos}

def mao_x(obj, lado):
    xs = [v.co.x for v in obj.data.vertices if dom_nome(obj, v) in (lado + "LowerArm", lado + "Hand")]
    return sum(xs) / max(len(xs), 1)

def z_chao(rig, pes=("LeftFoot", "RightFoot")):
    return min(min(rest(rig, n).z, rest(rig, n, True).z) for n in pes)

def medir_anim(obj, rig):
    ger = aas.aplicar_animacoes_multi(rig, cfg["clipes"])
    deform = postprocess_deform.medir_deformacao_animacao(obj, rig, ger)
    res = {"max_stretch": float(deform["max_stretch"]) if deform else 999.0, "clipes": {}}
    joelho_rest = abs(rest(rig, "LeftLowerLeg").x - rest(rig, "RightLowerLeg").x)
    cena = bpy.context.scene
    for nome in ("idle", "walk", "run"):
        acao = next(a for a in bpy.data.actions if a.name == nome or a.name.startswith(nome + "_"))
        rig.animation_data.action = acao
        f0, f1 = int(round(acao.frame_range[0])), int(round(acao.frame_range[1]))
        zs, ks = [], []
        for fr in range(f0, f1 + 1):
            cena.frame_set(fr); bpy.context.view_layer.update()
            zs.append(min(float((rig.matrix_world @ getattr(rig.pose.bones[n], t)).z) for n in ("LeftFoot", "RightFoot") for t in ("head", "tail")))
            ks.append(abs(float((rig.matrix_world @ rig.pose.bones["LeftLowerLeg"].head).x - (rig.matrix_world @ rig.pose.bones["RightLowerLeg"].head).x)))
        res["clipes"][nome] = {"min_z": zs, "joelho_sep": ks, "n": len(zs)}
    res["joelho_rest"] = joelho_rest
    return res

def sc_bake(seed=None, preset=None, anim=False, **kw):
    obj, rig, _ = rig_up("r15@1", **kw)
    a, t0, c0, m0, zc0 = snap(obj), thetas(rig), apn.calcular_caimento_braco_rig(rig), mao_x(obj, "Left"), z_chao(rig)
    info = apn.assar_pose_rest_natural(obj, rig, angulo_alvo_graus=14.0, seed=seed, postura_preset=preset)
    b, c1 = snap(obj), apn.calcular_caimento_braco_rig(rig)
    res = {"theta_antes": t0, "theta_depois": thetas(rig), "aplicavel_antes": bool(c0["aplicavel"]), "aplicavel_depois": bool(c1["aplicavel"]),
           "h": [a["h"], b["h"]], "zmin": [a["zmin"], b["zmin"]], "z_chao": [zc0, z_chao(rig)],
           "grupos_iguais": a["grupos"] == b["grupos"], "pesos_iguais": a["pesos"] == b["pesos"], "n_iguais": a["n"] == b["n"],
           "mao_x": [m0, mao_x(obj, "Left")], "tem_armature": any(m.type == "ARMATURE" for m in obj.modifiers),
           "info": json.loads(json.dumps(info, default=str)),
           "ossos": {bn.name: [round(c, 4) for c in (*rest(rig, bn.name), *rest(rig, bn.name, True))] for bn in rig.data.bones}}
    if anim:
        res["anim"] = medir_anim(obj, rig)
    return res

def sc_seeds():
    return {k: sc_bake(seed=s) for k, s in (("a", 11), ("b", 11), ("c", 77))}

def sc_wire(perfil, esq, bruto=None):
    obj, rig, _ = rig_up(esq)
    info, saida = {}, os.path.join(cfg["work"], "wire_" + perfil + ("_blocky" if bruto else ""))
    os.makedirs(saida, exist_ok=True)
    pep._pos_escala_rig_e_animacao(obj, rig, {}, {}, {"rota": "mesh"}, bruto or {}, 1.0, False, False, 30.0, False, info,
                                   pular_reparo_pos_escala=True, perfil=cfg["perfis"][perfil], saida_dir=saida)
    pn = info.get("pose_natural") or {}
    return {"theta": thetas(rig, esq), "pose_natural_aplicado": bool(pn.get("aplicado")), "n_ancoras": len(info.get("ancoras") or {}),
            "g15_ref": info.get("g15_apose_ref"), "g15_ref_existe": os.path.isfile(os.path.join(saida, "_g15_apose_ref.glb"))}

def sc_ancoras():
    obj, rig, _ = rig_up("r15@1")
    rig.location = (0.5, -0.3, 0.2); rig.rotation_euler = (0.0, 0.0, math.radians(30.0))
    bpy.context.view_layer.update()
    esp = {}
    for bn in rig.data.bones:
        p = rig.matrix_world @ bn.head_local
        esp[bn.name] = [p.x, p.z, -p.y]
    return {"anc": aas.extrair_ancoras(rig), "esp": esp}

def sc_fps():
    obj, rig, _ = rig_up("r15@1")
    cena = bpy.context.scene
    cena.render.fps = 25; cena.frame_set(9)
    clipes = [dict(c) for c in cfg["clipes"][:3]]
    clipes[1]["fps"] = 60; clipes[2]["fps"] = 30
    aas.aplicar_animacoes_multi(rig, clipes)
    r = {"fps_ok": int(cena.render.fps), "frame_ok": int(cena.frame_current)}
    cena.render.fps = 25; cena.frame_set(9)
    ruim = {"nome": "ruim", "fps": 48, "duracao_s": 0.5, "chaves": [{"segundos": 0.0, "poses": []}]}
    try:
        aas.aplicar_animacoes_multi(rig, [clipes[0], ruim]); r["levantou"] = None
    except (KeyError, TypeError, ValueError) as exc:
        r["levantou"] = type(exc).__name__
    r["fps_erro"], r["frame_erro"] = int(cena.render.fps), int(cena.frame_current)
    return r

def sc_chifres():
    obj, rig, m = rig_up("godot-humanoid-aa@1", horns=True, pauldron=True)
    lim = apl._limites_anatomicos(m, tem_neck=True)
    horn = [v for v in obj.data.vertices if v.co.z >= 1.70 and abs(v.co.x) >= 0.17]
    excl = [not apl._vertice_no_raio_ombro(v.co.copy(), lim, m) for v in horn]
    dom_sh = sum(1 for v in horn if dom_nome(obj, v) in ("Shoulder.L", "Shoulder.R"))
    paul = []
    for sx in (m["shoulder_x_L"], m["shoulder_x_R"]):
        j = Vector((sx, m["cy"], m["shoulder_z"]))
        paul += [bool(apl._vertice_no_raio_ombro(v.co.copy(), lim, m)) for v in obj.data.vertices if (v.co - j).length <= 0.12]
    return {"n_horn": len(horn), "frac_excluidos": sum(excl) / max(len(excl), 1), "horn_dom_shoulder": dom_sh,
            "n_paul": len(paul), "paul_ok": all(paul)}

def sc_clav():
    obj, rig, m = rig_up("r15@1")
    r = {}
    for rotulo, espelhar in (("normal", False), ("espelhado", True)):
        bL, bR = dict(m["braco_L"]), dict(m["braco_R"])
        bL["clav_x"] = bR["clav_x"] = 0.0
        if espelhar:
            bL["shoulder"] = Vector((-abs(bL["shoulder"].x), bL["shoulder"].y, bL["shoulder"].z))
            bR["shoulder"] = Vector((abs(bR["shoulder"].x), bR["shoulder"].y, bR["shoulder"].z))
        ossos = {o["nome"]: o for o in autorig_ossos._construir_ossos("r15@1", {**m, "braco_L": bL, "braco_R": bR})}
        r[rotulo] = {"L": ossos["LeftUpperArm"]["cabeca"][0], "R": ossos["RightUpperArm"]["cabeca"][0]}
    return r

def sc_quadril_largo():
    obj, rig, _ = rig_up("r15@1", wide_hips=True, forearm_deg=15.0)
    braco = {"LeftUpperArm", "LeftLowerArm", "LeftHand", "RightUpperArm", "RightLowerArm", "RightHand"}
    perna = {"LowerTorso", "LeftUpperLeg", "RightUpperLeg", "LeftLowerLeg", "RightLowerLeg"}
    quadril = [v for v in obj.data.vertices if abs(v.co.x) <= 0.36 and 0.90 <= v.co.z <= 1.06]
    mao = [v for v in obj.data.vertices if abs(v.co.x) >= 0.52 and v.co.z <= 1.10]
    return {"n_quadril": len(quadril), "quadril_roubado_por_braco": sum(1 for v in quadril if dom_nome(obj, v) in braco),
            "n_mao": len(mao), "mao_roubada_por_perna": sum(1 for v in mao if dom_nome(obj, v) in perna)}

out = {}
for nome, fn in (
    ("bake", lambda: sc_bake(anim=True)),
    ("bake_largo", lambda: sc_bake(wide_hips=True)),
    ("seeds", sc_seeds),
    ("wire_roblox", lambda: sc_wire("roblox-r15", "r15@1")),
    ("wire_blocky", lambda: sc_wire("roblox-r15", "r15@1", {"schema": "forge3d/bruto-blocky@1"})),
    ("wire_godot", lambda: sc_wire("godot4", "godot-humanoid@1")),
    ("ancoras", sc_ancoras), ("fps", sc_fps), ("chifres", sc_chifres), ("clav", sc_clav), ("quadril_largo", sc_quadril_largo),
):
    try:
        out[nome] = fn()
    except Exception:
        out[nome] = {"erro": traceback.format_exc()}
open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps(out, default=str))
'''


@pytest.fixture(scope="module")
def _bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    blender = _exigir_blender()
    work = tmp_path_factory.mktemp("onda7_blender")
    cfg = {
        "blender_dir": str(_BLENDER_DIR), "work": str(work), "out_json": str(work / "out.json"),
        "clipes": animacao.clipes(profiles.carregar("roblox-aa-80"), "r15@1", ["idle", "walk", "run"]),
        "perfis": {n: profiles.carregar(n) for n in ("roblox-r15", "godot4")},
    }
    (work / "cfg.json").write_text(json.dumps(cfg, default=str), encoding="utf-8")
    (work / "run.py").write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(work / "run.py"), "--", str(work / "cfg.json")],
        capture_output=True, text=True, timeout=900,
    )
    assert proc.returncode == 0, f"Blender onda7 falhou:\nSTDOUT={proc.stdout[-3000:]}\nSTDERR={proc.stderr[-3000:]}"
    return json.loads((work / "out.json").read_text(encoding="utf-8"))


def _cena(b: dict[str, Any], nome: str) -> dict[str, Any]:
    dados = b[nome]
    assert "erro" not in dados, f"cenario '{nome}' falhou no Blender:\n{dados.get('erro')}"
    return dados


@pytest.mark.blender
@pytest.mark.parametrize("cenario", ["bake", "bake_largo"])
def test_bake_rest_pose_45_para_natural_preserva_malha_pesos_e_zera_caimento(_bundle: dict, cenario: str) -> None:
    c = _cena(_bundle, cenario)
    assert c["aplicavel_antes"] is True
    for lado in "LR":
        assert 41.0 <= c["theta_antes"][f"up_{lado}"] <= 49.0, f"malha de teste nao esta em A-pose ~45: {c['theta_antes']}"
        assert 11.0 <= c["theta_depois"][f"up_{lado}"] <= 18.5, f"braco fora de 11-18.5 deg: {c['theta_depois']}"
        assert c["theta_depois"][f"tot_{lado}"] <= 18.5
    assert c["info"].get("aplicado") is True
    assert abs(c["h"][1] - c["h"][0]) <= 0.001 and abs(c["zmin"][1] - c["zmin"][0]) <= 0.001
    assert abs(c["z_chao"][1] - c["z_chao"][0]) <= 0.001
    assert c["n_iguais"] and c["grupos_iguais"] and c["pesos_iguais"], "bake alterou topologia ou pesos"
    assert c["tem_armature"] is True
    assert c["aplicavel_depois"] is False, "caimento dinamico ainda aplicavel apos o bake (queda dupla)"
    if cenario == "bake":
        assert c["mao_x"][1] < c["mao_x"][0] - 0.15, "malha nao acompanhou o rest-pose assado"


@pytest.mark.blender
def test_bake_mantem_g16_dentro_do_limite_apos_animar(_bundle: dict) -> None:
    assert float(_cena(_bundle, "bake")["anim"]["max_stretch"]) <= 8.5


@pytest.mark.blender
def test_seeds_iguais_repetem_e_seeds_distintas_mudam_rest_pose(_bundle: dict) -> None:
    s = _cena(_bundle, "seeds")
    assert s["a"]["ossos"].keys() == s["c"]["ossos"].keys()
    dif_igual = max(abs(x - y) for n in s["a"]["ossos"] for x, y in zip(s["a"]["ossos"][n], s["b"]["ossos"][n]))
    dif_seed = max(abs(x - y) for n in s["a"]["ossos"] for x, y in zip(s["a"]["ossos"][n], s["c"]["ossos"][n]))
    assert dif_igual <= 1e-4, "mesma seed produziu rest-pose diferente"
    assert dif_seed > 0.003, f"seeds 11 e 77 indistinguiveis (max dif={dif_seed:.5f} m)"
    for k in "ac":
        assert all(11.0 <= s[k]["theta_depois"][f"up_{lado}"] <= 18.5 for lado in "LR")


@pytest.mark.blender
def test_perfil_roblox_assa_pose_e_godot_mantem_apose_na_fiacao_do_pipeline(_bundle: dict) -> None:
    rb, gd, bl = _cena(_bundle, "wire_roblox"), _cena(_bundle, "wire_godot"), _cena(_bundle, "wire_blocky")
    assert rb["pose_natural_aplicado"] is True and rb["n_ancoras"] >= 16
    assert rb["g15_ref"] == "_g15_apose_ref.glb" and rb["g15_ref_existe"] is True
    assert all(11.0 <= rb["theta"][f"up_{lado}"] <= 18.5 for lado in "LR")
    for caso in (gd, bl):
        assert caso["pose_natural_aplicado"] is False
        assert all(41.0 <= caso["theta"][f"up_{lado}"] <= 49.0 for lado in "LR"), f"A-pose 45 nao preservada: {caso['theta']}"


@pytest.mark.blender
def test_idle_nao_flutua_em_nenhum_frame(_bundle: dict) -> None:
    c = _cena(_bundle, "bake")
    z_chao = c["z_chao"][1]
    idle = c["anim"]["clipes"]["idle"]
    assert idle["n"] >= 24
    for fr, z in enumerate(idle["min_z"]):
        assert z_chao - 0.002 <= z <= z_chao + 0.002, f"idle fora do chao no frame #{fr}: z={z:.4f} chao={z_chao:.4f}"


@pytest.mark.blender
@pytest.mark.parametrize("clipe", ["walk", "run"])
def test_locomocao_aduz_joelhos_e_nao_afunda_pes(_bundle: dict, clipe: str) -> None:
    c = _cena(_bundle, "bake")
    dados, rest_sep, z_chao = c["anim"]["clipes"][clipe], c["anim"]["joelho_rest"], c["z_chao"][1]
    media = sum(dados["joelho_sep"]) / len(dados["joelho_sep"])
    assert media <= rest_sep - 0.01, f"{clipe}: joelhos nao aduzem (media={media:.3f} vs repouso={rest_sep:.3f})"
    assert max(dados["joelho_sep"]) <= rest_sep + 0.005, f"{clipe}: pernas abertas alem do repouso"
    assert min(dados["min_z"]) >= z_chao - 0.005, f"{clipe}: pe afundou {min(dados['min_z']):.4f} < {z_chao:.4f}"


@pytest.mark.blender
def test_extrair_ancoras_16_ossos_r15_em_y_up_world(_bundle: dict) -> None:
    c = _cena(_bundle, "ancoras")
    assert R15_16 <= set(c["anc"]), f"faltam ancoras: {sorted(R15_16 - set(c['anc']))}"
    for nome in R15_16:
        assert c["anc"][nome] == pytest.approx(c["esp"][nome], abs=1e-4), f"ancora {nome} fora de (x, z, -y)"


@pytest.mark.blender
def test_gap065_aplicar_animacoes_multi_restaura_fps_e_frame(_bundle: dict) -> None:
    c = _cena(_bundle, "fps")
    assert (c["fps_ok"], c["frame_ok"]) == (25, 9), "fps/frame nao restaurados apos clipes com fps distintos"
    assert (c["fps_erro"], c["frame_erro"]) == (25, 9), f"fps/frame nao restaurados apos excecao ({c['levantou']})"


@pytest.mark.blender
def test_gap064_chifres_largos_nao_pesam_no_ombro_e_ombreira_e_permitida(_bundle: dict) -> None:
    c = _cena(_bundle, "chifres")
    assert c["n_horn"] > 10 and c["n_paul"] > 0
    assert c["frac_excluidos"] >= 0.9, f"chifres dentro do raio do ombro: {c}"
    assert c["horn_dom_shoulder"] == 0, f"chifre com peso dominante em Shoulder.L/R: {c}"
    assert c["paul_ok"] is True


@pytest.mark.blender
def test_gap067_4_clav_x_zero_usa_sinal_do_ombro_no_r15(_bundle: dict) -> None:
    c = _cena(_bundle, "clav")
    assert c["normal"]["L"] > 0.0 > c["normal"]["R"]
    assert c["espelhado"]["L"] < 0.0 < c["espelhado"]["R"], f"clav_x=0 ignorou o sinal de shoulder.x: {c['espelhado']}"


@pytest.mark.blender
def test_gap067_5_quadril_largo_e_pulso_baixo_nao_trocam_pesos_entre_braco_e_perna(_bundle: dict) -> None:
    c = _cena(_bundle, "quadril_largo")
    assert c["n_quadril"] > 5 and c["n_mao"] > 5
    assert c["quadril_roubado_por_braco"] == 0 and c["mao_roubada_por_perna"] == 0, c
