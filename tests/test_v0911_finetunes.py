"""Testes TDD independentes (janela limpa) para v0.9.11 (D136) — Contratos C1, C2, C3 e Opcao 1 (unitarios)."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import types
from array import array
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from forge3d import config
from forge3d.providers import concept_views_origem, mesh_i23d

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
    spec = importlib.util.spec_from_file_location("delight_pbr_v0911", RAIZ / "tools" / "delight_pbr.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakePixels:
    def __init__(self, data: list[float]) -> None:
        self._buf = array("f", data)

    def foreach_get(self, dst: array) -> None:
        dst[:] = self._buf

    def foreach_set(self, src: array) -> None:
        self._buf = array("f", src)


class _FakeImage:
    def __init__(self, px_sub: int, texels_rgba: list[tuple[float, float, float, float]]) -> None:
        assert len(texels_rgba) == px_sub * px_sub
        flat = [c for rgba in texels_rgba for c in rgba]
        self.pixels = _FakePixels(flat)

    def texel(self, idx: int) -> tuple[float, float, float, float]:
        b = self.pixels._buf
        off = idx * 4
        return (float(b[off]), float(b[off + 1]), float(b[off + 2]), float(b[off + 3]))


# ------------------------------------------------------------------ 1. C1: Native PBR Preservation & delight_pbr
def test_c1_modular_hints_pbr_nativo_preserva_nativo_saudavel_e_filtra_ferro_lamacento() -> None:
    import bake_pbr_nativo_blend as bnb

    px_sub = 10
    n_tex = px_sub * px_sub

    # Caso A: PBR nativo saudavel (p50_met=0.05 <= 0.85, p90_met=0.60 < 0.70, std_rough ~ 0.13 >= 0.03)
    # Mesmo com img_dl_hints contendo falso-positivo metalico frontal (dm=0.90, dw=1.0 em 30% dos texels),
    # DEVE preservar metallic e roughness nativos intactos e retornar nativo_puro_preservado=True.
    nat_saudavel = [
        (0.05, 0.74, 1.0, 1.0) if i < 85 else (0.60, 0.34, 1.0, 1.0)
        for i in range(n_tex)
    ]
    ao_uniforme = [(0.82, 0.82, 0.82, 1.0) for _ in range(n_tex)]
    dl_falso_positivo = [
        (0.90, 0.28, 1.0, 1.0) if i < 30 else (0.0, 0.78, 1.0, 1.0)
        for i in range(n_tex)
    ]
    img_nat_a = _FakeImage(px_sub, nat_saudavel)
    img_ao_a = _FakeImage(px_sub, ao_uniforme)
    img_dl_a = _FakeImage(px_sub, dl_falso_positivo)

    res_a = bnb.modular_hints_pbr_nativo(img_nat_a, img_ao_a, px_sub, img_dl_hints=img_dl_a)
    assert res_a.get("delight_hints_aplicados") is False
    assert res_a.get("nativo_puro_preservado") is True
    assert "p50_met" in res_a and "p90_met" in res_a and "std_rough" in res_a
    for i, esperado in enumerate(nat_saudavel):
        obtido = img_nat_a.texel(i)
        assert obtido[0] == pytest.approx(esperado[0], abs=1e-6)
        assert obtido[1] == pytest.approx(esperado[1], abs=1e-6)

    # Caso B: img_dl_hints is None -> DEVE preservar nm (>= 0.85 quando native metallic e 0.90),
    # inclusive quando p50_met > 0.85 (saturado) ou ferro_lamacento.
    nat_metal_puro = [(0.90, 0.25 if (i % 2 == 0) else 0.45, 1.0, 1.0) for i in range(n_tex)]
    img_nat_b = _FakeImage(px_sub, nat_metal_puro)
    img_ao_b = _FakeImage(px_sub, ao_uniforme)
    res_b = bnb.modular_hints_pbr_nativo(img_nat_b, img_ao_b, px_sub, img_dl_hints=None)
    assert res_b.get("delight_hints_aplicados") is False
    assert img_nat_b.texel(0)[0] >= 0.85

    # Caso C: ferro_lamacento=True (p50_met < 0.55 e p90_met >= 0.70) com img_dl_hints presente:
    # apenas texels com nm >= 0.20 podem receber boost do delight; texels com nm < 0.20 ficam foscos (< 0.25).
    nat_lamacento = [
        (0.05, 0.76, 1.0, 1.0) if i < 70 else ((0.35, 0.48, 1.0, 1.0) if i < 85 else (0.80, 0.28, 1.0, 1.0))
        for i in range(n_tex)
    ]
    dl_boost = [(0.92, 0.26, 1.0, 1.0) for _ in range(n_tex)]
    img_nat_c = _FakeImage(px_sub, nat_lamacento)
    img_ao_c = _FakeImage(px_sub, ao_uniforme)
    img_dl_c = _FakeImage(px_sub, dl_boost)

    bnb.modular_hints_pbr_nativo(img_nat_c, img_ao_c, px_sub, img_dl_hints=img_dl_c)
    # Texel 0 tinha nm = 0.05 (< 0.20): nao pode virar metalico mesmo com dm=0.92, dw=1.0
    assert img_nat_c.texel(0)[0] < 0.25
    # Texel 75 tinha nm = 0.35 (>= 0.20): recebe boost metalico do delight
    assert img_nat_c.texel(75)[0] >= 0.70


def test_c1_delight_pbr_pele_quente_e_pano_ocre_fosco_vs_metais_reais() -> None:
    dp = _carregar_delight_pbr()

    # 1. Pele quente com contraste de sombreamento (ex.: (206, 139, 113) e (188, 129, 99) + sombra (136, 90, 72))
    img_skin = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    d_skin = ImageDraw.Draw(img_skin)
    d_skin.rectangle((12, 12, 84, 84), fill=(206, 139, 113, 255))
    d_skin.rectangle((48, 12, 84, 84), fill=(188, 129, 99, 255))
    for y in range(20, 76, 8):
        d_skin.line((16, y, 80, y), fill=(136, 90, 72, 255), width=2)

    # 2. Pano ocre fosco (174, 114, 54) com dobras suaves (local_range_g em 2..18)
    img_ochre = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    d_ochre = ImageDraw.Draw(img_ochre)
    d_ochre.rectangle((12, 12, 84, 84), fill=(174, 114, 54, 255))
    for y in range(18, 78, 12):
        d_ochre.line((16, y, 80, y), fill=(180, 118, 57, 255), width=2)
        d_ochre.line((16, y + 4, 80, y + 4), fill=(168, 110, 51, 255), width=2)

    # 3. Ferro escuro verdadeiro (de test_v097_finetunes)
    img_iron = Image.new("RGBA", (64, 64), (50, 52, 55, 255))
    d_iron = ImageDraw.Draw(img_iron)
    for y in range(4, 60, 4):
        d_iron.line((4, y, 60, y), fill=(74, 76, 78, 255), width=2)
        d_iron.line((4, y + 2, 60, y + 2), fill=(35, 37, 39, 255), width=2)

    # 4. Prata fria (180, 185, 195) com listras (225, 230, 238) / (110, 115, 125)
    img_silver = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    d_silver = ImageDraw.Draw(img_silver)
    d_silver.rectangle((12, 12, 84, 84), fill=(180, 185, 195, 255))
    for y in range(18, 78, 6):
        d_silver.line((16, y, 80, y), fill=(225, 230, 238, 255), width=1)
        d_silver.line((16, y + 2, 80, y + 2), fill=(110, 115, 125, 255), width=1)

    # 5. Ouro (215, 170, 58)
    img_gold = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    d_gold = ImageDraw.Draw(img_gold)
    d_gold.rectangle((12, 12, 84, 84), fill=(215, 170, 58, 255))
    for y in range(18, 78, 8):
        d_gold.line((16, y, 80, y), fill=(246, 208, 92, 255), width=1)
        d_gold.line((16, y + 3, 80, y + 3), fill=(155, 118, 34, 255), width=1)

    # 6. Bronze especular (195, 118, 56) + highlight (245, 195, 130)
    img_bronze = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    d_bronze = ImageDraw.Draw(img_bronze)
    d_bronze.rectangle((12, 12, 84, 84), fill=(195, 118, 56, 255))
    for y in range(18, 78, 6):
        d_bronze.line((16, y, 80, y), fill=(245, 195, 130, 255), width=1)
        d_bronze.line((16, y + 2, 80, y + 2), fill=(128, 74, 32, 255), width=1)

    fns = [dp._mapas_pbr_pil, dp.estimar_mapas_pbr] + ([dp._mapas_pbr_cv2] if dp._TEM_CV2 else [])
    for fn_pbr in fns:
        m_skin, _ = fn_pbr(img_skin)
        assert m_skin.getpixel((30, 30)) < 30, f"Pele quente (206,139,113) classificada como metal em {fn_pbr.__name__}"
        assert m_skin.getpixel((64, 30)) < 30, f"Pele quente (188,129,99) classificada como metal em {fn_pbr.__name__}"

        m_ochre, _ = fn_pbr(img_ochre)
        assert m_ochre.getpixel((48, 48)) < 30, f"Pano ocre fosco (174,114,54) classificado como metal em {fn_pbr.__name__}"

        m_iron, _ = fn_pbr(img_iron)
        assert m_iron.getpixel((30, 30)) > 140

        m_silver, _ = fn_pbr(img_silver)
        assert m_silver.getpixel((48, 48)) > 140

        m_gold, _ = fn_pbr(img_gold)
        assert m_gold.getpixel((48, 48)) > 140

        m_bronze, _ = fn_pbr(img_bronze)
        assert m_bronze.getpixel((48, 48)) > 140


# ------------------------------------------------------------------ 2. C2: High->Low Cage Params
def test_c2_calcular_parametros_cage_pbr_nativo_vs_legado() -> None:
    import bake_pbr_exec as bpe

    # Quando usar_pbr_nativo=True: (max(0.002, 0.004 * diag), max(0.008, 0.014 * diag))
    cage_nat, ray_nat = bpe._calcular_parametros_cage(
        8.6, True, True, False, False, usar_pbr_nativo=True
    )
    assert cage_nat == pytest.approx(max(0.002, 0.004 * 8.6))
    assert ray_nat == pytest.approx(max(0.008, 0.014 * 8.6))
    assert cage_nat <= 0.04

    cage_nat_min, ray_nat_min = bpe._calcular_parametros_cage(
        0.2, False, False, False, True, usar_pbr_nativo=True
    )
    assert cage_nat_min == pytest.approx(0.002)
    assert ray_nat_min == pytest.approx(0.008)

    # Quando usar_pbr_nativo=False (default): preserva valores exatos legados
    c_prot, r_prot = bpe._calcular_parametros_cage(2.0, True, False, False, True, usar_pbr_nativo=False)
    assert (c_prot, r_prot) == pytest.approx((max(0.010, 0.014 * 2.0), max(0.025, 0.036 * 2.0)))

    c_det, r_det = bpe._calcular_parametros_cage(2.0, False, True, False, False, usar_pbr_nativo=False)
    assert (c_det, r_det) == pytest.approx((max(0.004, min(0.012, 0.008 * 2.0)), max(0.012, min(0.030, 0.020 * 2.0))))

    c_def, r_def = bpe._calcular_parametros_cage(2.0, False, False, False, True)
    assert (c_def, r_def) == pytest.approx((max(0.02, 0.03 * 2.0), max(0.025, 0.06 * 2.0)))


# ------------------------------------------------------------------ 3. C3: _limites_anatomicos & _osso_permitido
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


def _importar_autorig_grafo_puro(monkeypatch: pytest.MonkeyPatch):
    if "mathutils" not in sys.modules:
        mod_mu = types.ModuleType("mathutils")
        mod_mu.Vector = _Vec3  # type: ignore[attr-defined]
        mod_mu.Matrix = object  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "mathutils", mod_mu)
    if "bpy" not in sys.modules:
        monkeypatch.setitem(sys.modules, "bpy", types.ModuleType("bpy"))
    import autorig_grafo as ag

    return ag


def test_c3_limites_anatomicos_e_osso_permitido_tronco_abduzido(monkeypatch: pytest.MonkeyPatch) -> None:
    ag = _importar_autorig_grafo_puro(monkeypatch)

    # Personagem parrudo em A-pose:
    # h = 2.0, sh_x = 0.48, leg_abs = 0.28, min_elbow_x = 0.58
    # min_elbow_x (0.58) > leg_abs + 0.06*h (0.40) e min_elbow_x (0.58) > sh_x + 0.04*h (0.56)
    h = 2.0
    m: dict[str, Any] = {
        "z_min": 0.0,
        "z_max": h,
        "altura": h,
        "cy": 0.0,
        "torso_hw": 0.36,
        "neck_hw": 0.08,
        "leg_top_z": 0.88,
        "hip_z": 0.96,
        "spine_z": 1.10,
        "spine1_z": 1.24,
        "chest_z": 1.38,
        "chest_top_z": 1.58,
        "neck_z": 1.66,
        "head_top_z": 2.00,
        "shoulder_z": 1.50,
        "shoulder_x_L": 0.48,
        "shoulder_x_R": -0.48,
        "elbow_x_L": 0.58,
        "elbow_x_R": -0.58,
        "leg_x_L": 0.28,
        "leg_x_R": -0.28,
        "knee_z": 0.48,
        "ankle_z": 0.14,
        "braco_L": {"shoulder": _Vec3((0.48, 0.0, 1.50)), "elbow": _Vec3((0.58, 0.06, 1.16))},
        "braco_R": {"shoulder": _Vec3((-0.48, 0.0, 1.50)), "elbow": _Vec3((-0.58, 0.06, 1.16))},
    }

    for tem_neck in (True, False):
        lim = ag._limites_anatomicos(m, tem_neck=tem_neck)
        assert lim["arms_abducted"] > 0.5
        assert lim["tronco_max_x"] < 0.58, (
            f"tronco_max_x ({lim['tronco_max_x']:.4f}) nao foi limitado medialmente a min_elbow_x (0.58)"
        )

        # Ponto no cotovelo/antebraco: abs(v.x) > lim["tronco_max_x"] e v.z >= lim["upper_torso_z_min"],
        # mas ABAIXO de lim["arm_z_cut_lo"] (ex.: z = 1.16 < arm_z_cut_lo = 1.22).
        z_cotovelo_baixo = 0.5 * (lim["upper_torso_z_min"] + lim["arm_z_cut_lo"])
        assert lim["upper_torso_z_min"] <= z_cotovelo_baixo < lim["arm_z_cut_lo"]
        v_elbow = _Vec3((lim["tronco_max_x"] + 0.02, 0.05, z_cotovelo_baixo))

        for nome_tronco in ("UpperTorso", "Chest", "Spine1", "Spine"):
            permitido = ag._osso_permitido(
                nome_tronco, v_elbow, m, bracos_baixos=True, tem_neck=tem_neck, lim=lim
            )
            assert permitido is False, (
                f"{nome_tronco} vazou para cotovelo/antebraco em v=({v_elbow.x:.3f}, {v_elbow.z:.3f}) "
                f"com tronco_max_x={lim['tronco_max_x']:.3f}, arm_z_cut_lo={lim['arm_z_cut_lo']:.3f}"
            )


# ------------------------------------------------------------------ 4. Option 1: 1-View TRELLIS.2 + Gemini Back View
def test_option1_gerar_vista_traseira_de_origem_1_chamada_e_retry_multifigura(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert hasattr(concept_views_origem, "gerar_vista_traseira_de_origem"), (
        "concept_views_origem.gerar_vista_traseira_de_origem ainda nao implementado"
    )

    origem_png = tmp_path / "origem_front.png"
    img_f = Image.new("RGBA", (64, 64), (220, 220, 220, 255))
    ImageDraw.Draw(img_f).rectangle((22, 10, 42, 54), fill=(180, 60, 50, 255))
    img_f.save(origem_png, format="PNG")
    origem_bytes = origem_png.read_bytes()

    destino_1 = tmp_path / "back_single"
    chamadas_1: list[dict[str, Any]] = []

    def mock_gemini_single(_ai, prompt, _neg, seed, out_png, **kwargs):
        chamadas_1.append({"prompt": prompt, "seed": seed, "out": out_png.name, "kwargs": kwargs})
        im = Image.new("RGBA", (64, 64), (220, 220, 220, 255))
        ImageDraw.Draw(im).rectangle((22, 10, 42, 54), fill=(70, 90, 160, 255))
        im.save(out_png, format="PNG")
        return {"ok": True, "tempo_s": 0.04, "modelo": "gemini/test-v0911"}

    monkeypatch.setattr(concept_views_origem, "_chamar_gemini_conceito", mock_gemini_single)

    res1 = concept_views_origem.gerar_vista_traseira_de_origem(
        {"id": "boss.oni.01", "prompt": "armored oni warrior", "vistas": 4},
        origem_png,
        destino_1,
    )
    assert res1["ok"] is True
    assert len(chamadas_1) == 1
    assert chamadas_1[0]["out"] == "concept_back.png"
    assert chamadas_1[0]["kwargs"].get("referencia_png") == origem_png
    assert (destino_1 / "concept_back.png").is_file()
    assert not (destino_1 / "concept_left.png").exists()
    assert not (destino_1 / "concept_right.png").exists()
    assert res1["vista_back"] == str(destino_1 / "concept_back.png")
    assert "front" in res1["vistas"] and res1["vistas"]["back"] == str(destino_1 / "concept_back.png")
    assert "back" in res1["vistas_detalhes"]
    if (destino_1 / "concept_front.png").is_file():
        assert (destino_1 / "concept_front.png").read_bytes() == origem_bytes

    # Caso com multi-figure sheet na 1a tentativa -> no maximo 1 retry (total 2 chamadas)
    destino_2 = tmp_path / "back_retry"
    chamadas_2: list[dict[str, Any]] = []

    def mock_gemini_retry(_ai, prompt, _neg, seed, out_png, **kwargs):
        chamadas_2.append({"prompt": prompt, "seed": seed, "out": out_png.name})
        im = Image.new("RGBA", (64, 64), (220, 220, 220, 255))
        d = ImageDraw.Draw(im)
        if len(chamadas_2) == 1:
            # Duas figuras separadas por coluna vazia central -> _detectar_multiplas_figuras == True
            d.rectangle((6, 10, 22, 54), fill=(60, 80, 150, 255))
            d.rectangle((42, 10, 58, 54), fill=(60, 80, 150, 255))
        else:
            d.rectangle((22, 10, 42, 54), fill=(60, 80, 150, 255))
        im.save(out_png, format="PNG")
        return {"ok": True, "tempo_s": 0.04, "modelo": "gemini/test-v0911"}

    monkeypatch.setattr(concept_views_origem, "_chamar_gemini_conceito", mock_gemini_retry)
    res2 = concept_views_origem.gerar_vista_traseira_de_origem(
        {"id": "boss.oni.02", "prompt": "armored oni warrior", "vistas": 4},
        origem_png,
        destino_2,
    )
    assert res2["ok"] is True
    assert len(chamadas_2) == 2
    assert res2["vistas_detalhes"]["back"].get("retentativa_multiplas_figuras") is True


def test_option1_mesh_i23d_trellis_preserva_back_e_remove_left_right(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from forge3d.providers import mesh as mesh_mod

    destino = tmp_path / "raw_trellis_opt1"
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
        return {
            "report": {"ativo": True, "executado": True},
            "albedo": "input_delit.png",
            "metallic_hint": "",
            "roughness_hint": "",
            "emissive_hint": "",
            "arquivos": [alb],
        }

    for target_mod in (mesh_mod, mesh_i23d._diag):
        monkeypatch.setattr(target_mod, "modelo_escolhido", lambda: "trellis", raising=False)
        monkeypatch.setattr(target_mod, "script_delight", lambda: destino / "dl_stub.py", raising=False)
        monkeypatch.setattr(target_mod, "_alfa_util", lambda _p: (True, 0.5), raising=False)
    monkeypatch.setattr(mesh_i23d._trellis, "executar_i23d_trellis2_local", fake_trellis)

    out = mesh_i23d.executar_i23d_step(
        item={"id": "boss.trellis.opt1", "tipo": "personagem_humanoide", "vistas": 4},
        destino=destino,
        imagem=Path(vistas_paths["front"]),
        concept_meta={"vistas": vistas_paths},
        env={},
        t0=0.0,
        pose_guard_fn=lambda i, im, d, e: (im, {"ok": True}),
        delight_fn=fake_delight,
    )
    # 1) Delight roda apenas 1x (front) e marca vistas_extras_ignoradas_single_view=True
    assert len(delight_calls) == 1
    res_json = json.loads((destino / "i23d_resultado.json").read_text(encoding="utf-8"))
    assert (
        res_json.get("vistas_extras_ignoradas_single_view") is True
        or out["resultado"].get("vistas_extras_ignoradas_single_view") is True
    )

    # 2) left e right sao removidas de vistas_ortograficas, mas back DEVE ser preservada!
    modelo_json = json.loads((destino / "modelo.json").read_text(encoding="utf-8"))
    vo = modelo_json.get("vistas_ortograficas") or {}
    assert "left" not in vo and "right" not in vo
    assert "back" in vo and Path(vo["back"]).is_file(), (
        f"Vista 'back' foi descartada de modelo['vistas_ortograficas'] no modo trellis: {vo}"
    )
