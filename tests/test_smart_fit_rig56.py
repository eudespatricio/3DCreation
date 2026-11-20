"""Testes do motor Smart-Fit (matematica pura), animacao AA 56 ossos e Godot BoneMap."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from forge3d import animacao, post, profiles

RAIZ = Path(__file__).resolve().parents[1]
BLENDER_DIR = RAIZ / "blender"
POST_IMPORT_GD = RAIZ / "addons" / "forge3d" / "post_import.gd"
PROJ_GODOT = RAIZ / "tools" / "godot_project"

if str(BLENDER_DIR) not in sys.path:
    sys.path.insert(0, str(BLENDER_DIR))

import smart_fit  # noqa: E402

OSSOS_56_ESPERADOS = (
    "Root",
    "Hips",
    "Spine",
    "Chest",
    "Neck",
    "Head",
    "Jaw",
    "Eye.L",
    "Eye.R",
    "Cape",
    "Shoulder.L",
    "UpperArm.L",
    "LowerArm.L",
    "Hand.L",
    "Shoulder.R",
    "UpperArm.R",
    "LowerArm.R",
    "Hand.R",
    "Thumb1.L",
    "Thumb2.L",
    "Thumb3.L",
    "Index1.L",
    "Index2.L",
    "Index3.L",
    "Middle1.L",
    "Middle2.L",
    "Middle3.L",
    "Ring1.L",
    "Ring2.L",
    "Ring3.L",
    "Little1.L",
    "Little2.L",
    "Little3.L",
    "Thumb1.R",
    "Thumb2.R",
    "Thumb3.R",
    "Index1.R",
    "Index2.R",
    "Index3.R",
    "Middle1.R",
    "Middle2.R",
    "Middle3.R",
    "Ring1.R",
    "Ring2.R",
    "Ring3.R",
    "Little1.R",
    "Little2.R",
    "Little3.R",
    "UpperLeg.L",
    "LowerLeg.L",
    "Foot.L",
    "Toe.L",
    "UpperLeg.R",
    "LowerLeg.R",
    "Foot.R",
    "Toe.R",
)


def _blender_bin() -> str:
    try:
        ok, _ = post.preflight()
        if ok:
            return post.binario()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"[test_smart_fit_rig56] preflight Blender falhou: {exc}", file=sys.stderr)
    pytest.skip("Blender 4.2 nao disponivel neste ambiente")


def _godot_bin() -> str:
    env = os.environ.get("FORGE3D_GODOT")
    if env and Path(env).is_file():
        return env
    bin_g = shutil.which("godot") or shutil.which("godot4")
    if bin_g:
        return bin_g
    pytest.skip("Godot 4 headless nao disponivel neste ambiente")


def _rodar_blender_script(tmp_path: Path, codigo: str, tag: str = "sf") -> dict:
    blender = _blender_bin()
    out_json = tmp_path / f"out_{tag}.json"
    script = tmp_path / f"run_{tag}.py"
    script.write_text(codigo, encoding="utf-8")
    proc = subprocess.run(
        [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", str(script), "--", str(out_json)],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"Blender falhou:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert out_json.is_file(), f"JSON nao gerado: {out_json}"
    return json.loads(out_json.read_text(encoding="utf-8"))


def _pontos_cilindro_inclinado(raio: float, comprimento: float, eixo_dir: tuple[float, float, float]) -> list[tuple[float, float, float]]:
    ex, ey, ez = eixo_dir
    n = math.sqrt(ex * ex + ey * ey + ez * ez)
    ux, uy, uz = ex / n, ey / n, ez / n
    ref = (1.0, 0.0, 0.0) if abs(ux) < 0.8 else (0.0, 1.0, 0.0)
    vx = uy * ref[2] - uz * ref[1]
    vy = uz * ref[0] - ux * ref[2]
    vz = ux * ref[1] - uy * ref[0]
    vn = math.sqrt(vx * vx + vy * vy + vz * vz)
    vx, vy, vz = vx / vn, vy / vn, vz / vn
    wx = uy * vz - uz * vy
    wy = uz * vx - ux * vz
    wz = ux * vy - uy * vx

    pts: list[tuple[float, float, float]] = []
    for k in range(101):
        s = comprimento * (k / 100.0)
        for a in range(16):
            ang = 2.0 * math.pi * (a / 16.0)
            ca, sa = math.cos(ang), math.sin(ang)
            pts.append(
                (
                    s * ux + raio * (ca * vx + sa * wx),
                    s * uy + raio * (ca * vy + sa * wy),
                    s * uz + raio * (ca * vz + sa * wz),
                )
            )
    return pts


# ------------------------------------------------------------------ 1. Pure-math Smart-Fit


def test_smart_fit_importa_sem_bpy_e_pca_cilindro():
    assert smart_fit.HAS_BPY is False
    pts = _pontos_cilindro_inclinado(raio=0.022, comprimento=0.40, eixo_dir=(1.0, 1.0, 2.0))
    info = smart_fit.calcular_pca_cilindro(pts, fracao_cabo=(0.05, 0.35))
    assert info["raio_m"] == pytest.approx(0.022, abs=0.0015)
    assert info["comprimento_m"] == pytest.approx(0.12, abs=0.015)
    assert len(info["centro"]) == 3
    assert info["socket_offset"] == info["centro"]

    e_ref = (1.0 / math.sqrt(6.0), 1.0 / math.sqrt(6.0), 2.0 / math.sqrt(6.0))
    dot = abs(sum(a * b for a, b in zip(info["eixo"], e_ref)))
    assert dot > 0.99


def test_smart_fit_angulos_punho_monotonicos():
    fino = smart_fit.calcular_angulos_punho_cilindrico(0.012)
    medio = smart_fit.calcular_angulos_punho_cilindrico(0.025)
    grosso = smart_fit.calcular_angulos_punho_cilindrico(0.045)

    assert fino["soma_graus"] > medio["soma_graus"] > grosso["soma_graus"]
    for res in (fino, medio, grosso):
        for segs in res["dedos"].values():
            assert len(segs) == 3
            assert all(4.0 <= ang <= 95.0 for ang in segs)
        for rx, rz in res["thumb"]:
            assert 4.0 <= rx <= 65.0
            assert 1.0 <= rz <= 45.0


def test_smart_fit_deslocamento_contato():
    # Peca flutuando 0.05 m acima de Z=0 (normal +Z)
    pts_flt = [(0.0, 0.0, 0.05), (0.1, 0.0, 0.05)]
    alvo = [((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)), ((0.1, 0.0, 0.0), (0.0, 0.0, 1.0))]
    res_flt = smart_fit.calcular_deslocamento_contato(pts_flt, alvo, folga_m=0.0015)
    assert res_flt["penetrando"] is False
    assert res_flt["deslocamento"][2] == pytest.approx(-0.0485, abs=1e-5)

    # Peca penetrando -0.01 m dentro de Z=0
    pts_pen = [(0.0, 0.0, -0.01), (0.1, 0.0, 0.02)]
    res_pen = smart_fit.calcular_deslocamento_contato(pts_pen, alvo, folga_m=0.0015)
    assert res_pen["penetrando"] is True
    assert res_pen["deslocamento"][2] == pytest.approx(0.0115, abs=1e-5)


# ------------------------------------------------------------------ 2. Animacao AA & retrocompat


def _perfil_aa_sintetico() -> dict:
    mapa_aa = {
        "quadril": "Hips",
        "coluna": "Spine",
        "tronco": "Chest",
        "pescoco": "Neck",
        "cabeca": "Head",
        "mandibula": "Jaw",
        "capa": "Cape",
        "ombro_e": "Shoulder.L",
        "ombro_d": "Shoulder.R",
        "braco_e": "UpperArm.L",
        "braco_d": "UpperArm.R",
        "antebraco_e": "LowerArm.L",
        "antebraco_d": "LowerArm.R",
        "mao_e": "Hand.L",
        "mao_d": "Hand.R",
        "perna_e": "UpperLeg.L",
        "perna_d": "UpperLeg.R",
        "canela_e": "LowerLeg.L",
        "canela_d": "LowerLeg.R",
        "pe_e": "Foot.L",
        "pe_d": "Foot.R",
        "dedo_pe_e": "Toe.L",
        "dedo_pe_d": "Toe.R",
    }
    for pt_d, en_d in (
        ("polegar", "Thumb"),
        ("indicador", "Index"),
        ("medio", "Middle"),
        ("anelar", "Ring"),
        ("mindinho", "Little"),
    ):
        for seg in (1, 2, 3):
            mapa_aa[f"{pt_d}_{seg}_e"] = f"{en_d}{seg}.L"
            mapa_aa[f"{pt_d}_{seg}_d"] = f"{en_d}{seg}.R"
    return {"rig": {"esqueleto_padrao": "godot-humanoid-aa@1", "retarget": {"godot-humanoid-aa@1": mapa_aa}}}


def test_animacao_aa_secundaria_e_retrocompat():
    godot = profiles.carregar("godot4")
    r15 = profiles.carregar("roblox-r15")

    # Retrocompatibilidade 100% preservada: zero ossos extras nos esqueletos antigos
    for perfil, esq in ((godot, "godot-humanoid@1"), (r15, "r15@1")):
        cls = animacao.clipes(perfil, esq, ["idle", "walk", "run", "jump", "attack"])
        for c in cls:
            assert "Cape" not in c["ossos"]
            assert "Jaw" not in c["ossos"]
            assert "Thumb1.L" not in c["ossos"]

    # Novo esqueleto AA sintetiza Cape, Jaw e falanges com curvas C1 suaves
    aa_perfil = _perfil_aa_sintetico()
    pedidos = ["idle", "walk", "run", "jump", "attack", "death"]
    cls_aa = animacao.clipes(aa_perfil, "godot-humanoid-aa@1", pedidos)
    assert [c["nome"] for c in cls_aa] == pedidos

    for c in cls_aa:
        ossos_c = set(c["ossos"])
        assert {"Cape", "Jaw", "Neck", "Hand.L", "Hand.R", "Thumb1.L", "Index2.R", "Little3.L"} <= ossos_c
        for osso_sec in ("Cape", "Jaw", "Thumb1.L", "Middle2.R"):
            vals = [p["graus"] for ch in c["chaves"] for p in ch["poses"] if p["osso"] == osso_sec]
            assert max(vals) - min(vals) > 1.0, (c["nome"], osso_sec, vals)
        if c["loop"]:
            p0 = {(p["osso"], p["eixo"]): p["graus"] for p in c["chaves"][0]["poses"]}
            pf = {(p["osso"], p["eixo"]): p["graus"] for p in c["chaves"][-1]["poses"]}
            for k, v0 in p0.items():
                assert pf[k] == pytest.approx(v0, abs=1e-4)


# ------------------------------------------------------------------ 4. Godot BoneMap 56


@pytest.mark.godot
def test_godot_bone_map_56_aa_e_retrocompat(tmp_path: Path):
    godot = _godot_bin()
    script = tmp_path / "check_bonemap_aa.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})

func _dump(bm: BoneMap, prefix: String) -> void:
\tvar prof := bm.profile
\tfor i in range(prof.bone_size):
\t\tvar pname := prof.get_bone_name(i)
\t\tvar sname := bm.get_skeleton_bone_name(pname)
\t\tif sname != "":
\t\t\tprint(prefix, " ", pname, "=", sname)

func _initialize() -> void:
\t_dump(PostImport.criar_bone_map_humanoid(), "STD")
\t_dump(PostImport.criar_bone_map_humanoid("godot-humanoid-aa@1"), "AA")
\tquit(0)
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [godot, "--headless", "--path", str(PROJ_GODOT), "--script", str(script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    std: dict[str, str] = {}
    aa: dict[str, str] = {}
    for linha in proc.stdout.splitlines():
        if linha.startswith("STD "):
            k, v = linha[4:].split("=", 1)
            std[k] = v
        elif linha.startswith("AA "):
            k, v = linha[3:].split("=", 1)
            aa[k] = v

    # Legado preservado
    assert std.get("Chest") == "Spine1"
    assert std.get("UpperChest") == "Chest"
    assert "LeftThumbMetacarpal" not in std

    # AA 56 ossos
    assert aa.get("Root") == "Root"
    assert aa.get("Spine") == "Spine"
    assert aa.get("Chest") == "Chest"
    assert aa.get("UpperChest") == "Chest"
    assert aa.get("Jaw") == "Jaw"
    assert aa.get("LeftEye") == "Eye.L"
    assert aa.get("RightEye") == "Eye.R"
    assert aa.get("LeftThumbMetacarpal") == "Thumb1.L"
    assert aa.get("RightLittleDistal") == "Little3.R"
    assert len(aa) == 56
    assert set(aa.values()) <= set(OSSOS_56_ESPERADOS)
