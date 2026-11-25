"""Testes comportamentais independentes (Sem Oraculo Comprado) para Onda 6: PBR Heal/Margins/GAP-065, Delight/PBR, Cutout, Preflight 2D e GPU Lock."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import subprocess
import sys
from array import array
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image, ImageDraw

from forge3d import config, locks, pipeline_item, profiles, publish, qc
from forge3d.errors import ForgeError
from forge3d.providers import concept_views_origem, mesh, mesh_diag, mesh_trellis

RAIZ = Path(__file__).resolve().parents[1]
BLENDER_DIR = RAIZ / "blender"
TOOLS_DIR = RAIZ / "tools"
VENV_I23D_PY = Path.home() / ".cache" / "forge3d" / "venv-i23d" / "bin" / "python"

for _p in (str(BLENDER_DIR), str(TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _carregar_modulo(nome: str, caminho: Path) -> Any:
    spec = importlib.util.spec_from_file_location(nome, caminho)
    assert spec is not None and spec.loader is not None, f"Falha ao carregar {caminho}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _px_rgba(img: Image.Image, x: int, y: int) -> tuple[int, int, int, int]:
    val: Any = img.getpixel((x, y))
    return (int(val[0]), int(val[1]), int(val[2]), int(val[3]))


def _px_l(img: Image.Image, x: int, y: int) -> int:
    val: Any = img.getpixel((x, y))
    return int(val[0] if isinstance(val, tuple) else val)


def test_bake_pbr_heal_propagar_texels_validos_buf_voronoi_e_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import bake_pbr_heal as bph

    w, h, n = 9, 9, 81
    valid_mask, target_mask, buf_orig = [False] * n, [False] * n, [0.0] * (n * 4)
    for y in range(1, 8):
        for x in range(1, 8):
            idx = y * w + x
            target_mask[idx] = True
            if not (3 <= x <= 5 and 3 <= y <= 5):
                valid_mask[idx] = True
                buf_orig[idx * 4 : idx * 4 + 4] = [0.80, 0.45, 0.25, 1.0]

    out_def, curados_def = bph.propagar_texels_validos_buf(array("f", buf_orig), list(valid_mask), list(target_mask), w, h, canais=4)
    assert curados_def == 9
    for y in range(3, 6):
        for x in range(3, 6):
            off = (y * w + x) * 4
            assert [float(out_def[off + c]) for c in range(4)] == pytest.approx([0.80, 0.45, 0.25, 1.0], abs=1e-5)

    if hasattr(bph, "_NP"):
        monkeypatch.setattr(bph, "_NP", None)
        out_py, curados_py = bph.propagar_texels_validos_buf(array("f", buf_orig), list(valid_mask), list(target_mask), w, h, canais=4)
        assert curados_py == 9
        for y in range(3, 6):
            for x in range(3, 6):
                off = (y * w + x) * 4
                assert [float(out_py[off + c]) for c in range(4)] == pytest.approx([0.80, 0.45, 0.25, 1.0], abs=1e-5)

    out_iso, curados_iso = bph.propagar_texels_validos_buf(
        array("f", [0.0, 0.0, 0.0, 1.0] * 16), [False] * 16, [i in (5, 6, 9, 10) for i in range(16)], 4, 4,
        canais=4, fallback_rgba=(0.78, 0.78, 0.78, 1.0),
    )
    assert curados_iso == 4
    for idx in (5, 6, 9, 10):
        assert [float(out_iso[idx * 4 + c]) for c in range(4)] == pytest.approx([0.78, 0.78, 0.78, 1.0], abs=1e-5)


def test_bake_pbr_passes_margem_bake_px_proporcional() -> None:
    import bake_pbr_passes as bpp

    assert (bpp._margem_bake_px(512, submapa=False), bpp._margem_bake_px(512, submapa=True)) == (6, 4)
    assert (bpp._margem_bake_px(1024, submapa=False), bpp._margem_bake_px(1024, submapa=True)) == (8, 8)
    assert (bpp._margem_bake_px(2048, submapa=False), bpp._margem_bake_px(2048, submapa=True)) == (16, 16)
    assert (bpp._margem_bake_px(4096, submapa=False), bpp._margem_bake_px(4096, submapa=True)) == (16, 16)


def test_gap065_emissive_hint_conflito_e_deprecation_warning() -> None:
    import bake_pbr
    import bake_pbr_emissive as bpe
    import bake_pbr_exec as bp_exec

    with pytest.raises(ValueError, match="emissive_hint"):
        bpe._resolver_emissive_hint_alias("a.png", "b.png")
    for fn in (bake_pbr.executar_bake_high_low, bp_exec.executar_bake_high_low):
        with pytest.raises(ValueError, match="emissive_hint"):
            fn(None, "/tmp/out", "item", 512, 1000, None, None, None, None, emissive_hint="a.png", emissive_hint_png="b.png")
    with pytest.warns(DeprecationWarning):
        assert bpe._resolver_emissive_hint_alias(None, "b.png") == "b.png"
    assert bpe._resolver_emissive_hint_alias("a.png", None) == "a.png"
    assert bpe._resolver_emissive_hint_alias("a.png", "a.png") == "a.png"


# ------------------------------------------------------------------ 4. tools/delight.py: rampa monotona e borda bicolor
def _construir_imagens_delight_teste() -> tuple[Image.Image, Image.Image]:
    # 3 faixas iguais (60, 125, 190) -> media = mediana = l_ref = 125.0.
    # Na coluna x=96 (interior da faixa 190, onde l_low ~ 190 > l_ref), pixels y=60..68 tem v = 121..129.
    img_ramp = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d_r = ImageDraw.Draw(img_ramp)
    d_r.rectangle((16, 16, 47, 111), fill=(60, 60, 60, 255))
    d_r.rectangle((48, 16, 79, 111), fill=(125, 125, 125, 255))
    d_r.rectangle((80, 16, 111, 111), fill=(190, 190, 190, 255))
    for idx, v in enumerate(range(121, 130)):
        img_ramp.putpixel((96, 60 + idx), (v, v, v, 255))

    img_two = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d_two = ImageDraw.Draw(img_two)
    d_two.rectangle((20, 20, 64, 108), fill=(36, 38, 42, 255))
    d_two.rectangle((64, 20, 108, 108), fill=(236, 236, 240, 255))
    return img_ramp, img_two


def _validar_saidas_delight(out_ramp: Image.Image, out_two: Image.Image, label: str) -> None:
    lums = [_px_rgba(out_ramp, 96, 60 + idx)[0] for idx in range(9)]
    diffs = [lums[i + 1] - lums[i] for i in range(len(lums) - 1)]
    assert min(diffs) >= 0, f"Nao-monotona em {label}: lums={lums}, diffs={diffs}"
    salto_lref = lums[5] - lums[3]
    assert 1 <= salto_lref <= 5, f"Salto descontinuo entre l_ref-1 e l_ref+1 ({label}): salto={salto_lref}, lums={lums}"
    assert max(diffs) <= 3, f"Degrau abrupto em l_ref ({label}): max_diff={max(diffs)}, lums={lums}"

    lum_interior = _px_rgba(out_two, 88, 64)[0]
    lum_borda = _px_rgba(out_two, 106, 64)[0]
    assert lum_borda >= 180, f"Borda clara escureceu em {label}: lum_borda={lum_borda}"
    assert abs(lum_borda - lum_interior) <= 8, (
        f"Bleed de media global na borda clara em {label}: borda={lum_borda} vs interior={lum_interior}"
    )


def test_delight_transicao_monotona_l_ref_e_borda_bicolor_pil_e_cv2(tmp_path: Path) -> None:
    dl = _carregar_modulo("delight_onda6", TOOLS_DIR / "delight.py")
    img_ramp, img_two = _construir_imagens_delight_teste()
    _validar_saidas_delight(dl._delight_pil(img_ramp), dl._delight_pil(img_two), "PIL")

    if getattr(dl, "_TEM_CV2", False):
        _validar_saidas_delight(dl._delight_cv2(img_ramp), dl._delight_cv2(img_two), "cv2_inproc")
    elif VENV_I23D_PY.is_file():
        p_ramp_in, p_ramp_out = tmp_path / "ramp_in.png", tmp_path / "ramp_out.png"
        p_two_in, p_two_out = tmp_path / "two_in.png", tmp_path / "two_out.png"
        img_ramp.save(p_ramp_in)
        img_two.save(p_two_in)
        for p_in, p_out in ((p_ramp_in, p_ramp_out), (p_two_in, p_two_out)):
            subprocess.run(
                [str(VENV_I23D_PY), str(TOOLS_DIR / "delight.py"), "--imagem", str(p_in), "--saida-albedo", str(p_out)],
                check=True, capture_output=True, text=True,
            )
        with Image.open(p_ramp_out) as oramp, Image.open(p_two_out) as otwo:
            _validar_saidas_delight(oramp.convert("RGBA"), otwo.convert("RGBA"), "cv2_venv")


# ------------------------------------------------------------------ 5. tools/delight_pbr.py: pedra fria, gelo, rim alpha=80 e runas neon
def _construir_imagens_pbr_onda6() -> tuple[Image.Image, Image.Image, Image.Image]:
    img_stone = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d_st = ImageDraw.Draw(img_stone)
    d_st.ellipse((20, 16, 108, 112), fill=(118, 126, 138, 255))
    for y in range(24, 104, 8):
        d_st.line((28, y, 100, y), fill=(127, 135, 147, 255), width=3)
        d_st.line((28, y + 4, 100, y + 4), fill=(109, 117, 129, 255), width=3)

    img_ice = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d_ice = ImageDraw.Draw(img_ice)
    d_ice.ellipse((16, 12, 112, 116), fill=(0, 255, 255, 80))
    d_ice.ellipse((22, 18, 106, 110), fill=(175, 228, 245, 255))
    d_ice.ellipse((36, 30, 92, 96), fill=(185, 235, 248, 255))

    img_runes = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d_rn = ImageDraw.Draw(img_runes)
    d_rn.rectangle((14, 14, 114, 114), fill=(215, 175, 55, 80))
    d_rn.rectangle((20, 20, 108, 108), fill=(48, 52, 60, 255))
    d_rn.rectangle((34, 36, 56, 92), fill=(0, 248, 255, 255))
    d_rn.rectangle((72, 36, 94, 92), fill=(255, 115, 0, 255))
    return img_stone, img_ice, img_runes


def _validar_pbr_onda6(
    met_stone: Image.Image, em_ice: Image.Image, met_runes: Image.Image, em_runes: Image.Image,
    img_stone: Image.Image, img_ice: Image.Image, label: str,
) -> None:
    fg_stone = [(x, y) for y in range(128) for x in range(128) if _px_rgba(img_stone, x, y)[3] >= 200]
    met_stone_ratio = sum(1 for x, y in fg_stone if _px_l(met_stone, x, y) > 32) / float(len(fg_stone))
    assert met_stone_ratio < 0.01, f"Falso metalico em ovo de pedra ({label}): {met_stone_ratio:.4f}"

    fg_ice = [(x, y) for y in range(128) for x in range(128) if _px_rgba(img_ice, x, y)[3] >= 200]
    em_ice_ratio = sum(1 for x, y in fg_ice if _px_l(em_ice, x, y) > 16) / float(len(fg_ice))
    assert em_ice_ratio < 0.005, f"Falso emissive em ovo de gelo ({label}): {em_ice_ratio:.4f}"

    assert _px_l(em_ice, 18, 64) == 0, f"Rim alpha=80 virou emissive ({label})"
    assert _px_l(met_runes, 16, 64) == 0, f"Rim alpha=80 virou metallic ({label})"
    assert _px_l(em_runes, 16, 64) == 0, f"Rim alpha=80 virou emissive em runas ({label})"
    assert _px_l(em_runes, 45, 64) > 100, f"Runa neon ciano nao detectada ({label})"
    assert _px_l(em_runes, 83, 64) > 100, f"Runa neon laranja nao detectada ({label})"


def test_delight_pbr_pedra_fria_gelo_rim_alpha80_e_runas_neon(tmp_path: Path) -> None:
    dp = _carregar_modulo("delight_pbr_onda6", TOOLS_DIR / "delight_pbr.py")
    img_stone, img_ice, img_runes = _construir_imagens_pbr_onda6()
    met_st_pil, _ = dp._mapas_pbr_pil(img_stone)
    em_ice_pil = dp._emissive_pil(img_ice)
    met_rn_pil, _ = dp._mapas_pbr_pil(img_runes)
    em_rn_pil = dp._emissive_pil(img_runes)
    _validar_pbr_onda6(met_st_pil, em_ice_pil, met_rn_pil, em_rn_pil, img_stone, img_ice, "PIL")
    if VENV_I23D_PY.is_file():
        script = (
            "import sys; from PIL import Image; "
            f"sys.path.insert(0, {str(TOOLS_DIR)!r}); import delight_pbr as dp; "
            "st = Image.open(sys.argv[1]); ic = Image.open(sys.argv[2]); rn = Image.open(sys.argv[3]); "
            "ms, _ = dp._mapas_pbr_cv2(st); ei = dp._emissive_cv2(ic); "
            "mr, _ = dp._mapas_pbr_cv2(rn); er = dp._emissive_cv2(rn); "
            "ms.save(sys.argv[4]); ei.save(sys.argv[5]); mr.save(sys.argv[6]); er.save(sys.argv[7])"
        )
        p_st, p_ic, p_rn = tmp_path / "st.png", tmp_path / "ic.png", tmp_path / "rn.png"
        p_ms, p_ei, p_mr, p_er = tmp_path / "ms.png", tmp_path / "ei.png", tmp_path / "mr.png", tmp_path / "er.png"
        img_stone.save(p_st)
        img_ice.save(p_ic)
        img_runes.save(p_rn)
        subprocess.run(
            [str(VENV_I23D_PY), "-c", script, str(p_st), str(p_ic), str(p_rn), str(p_ms), str(p_ei), str(p_mr), str(p_er)],
            check=True, capture_output=True, text=True,
        )
        with Image.open(p_ms) as ms, Image.open(p_ei) as ei, Image.open(p_mr) as mr, Image.open(p_er) as er:
            _validar_pbr_onda6(ms.convert("L"), ei.convert("L"), mr.convert("L"), er.convert("L"), img_stone, img_ice, "cv2")


def test_cutout_clean_halo_bleed_margem_e_rembg_cpu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cc = _carregar_modulo("cutout_clean_onda6", TOOLS_DIR / "cutout_clean.py")
    pg = _carregar_modulo("pose_guard_onda6", TOOLS_DIR / "pose_guard.py")

    img_halo = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    d_h = ImageDraw.Draw(img_halo)
    d_h.rectangle((36, 36, 124, 124), fill=(128, 128, 128, 95))
    d_h.rectangle((39, 39, 121, 121), fill=(128, 128, 128, 140))
    d_h.rectangle((42, 42, 118, 118), fill=(190, 65, 45, 255))

    limpa = cc.limpar_halo_e_sangrar_rgb(img_halo, (128.0, 128.0, 128.0), usou_rembg=True, alpha_corte=160, bleed_px=6)
    alphas = {limpa.getpixel((x, y))[3] for y in range(160) for x in range(160)}
    assert alphas <= {0, 255}, f"Alphas semitransparentes restaram apos limpeza: {alphas}"

    for dist in range(1, 5):
        r_b, g_b, b_b, a_b = limpa.getpixel((42 - dist, 80))
        assert a_b == 0 and r_b > 120 and r_b > g_b + 30, f"Bleed RGB falhou a {dist}px: {(r_b, g_b, b_b, a_b)}"

    p_halo_in, p_halo_out = tmp_path / "halo_in.png", tmp_path / "halo_out.png"
    img_halo.save(p_halo_in)
    info_pg = pg.decompor_silhueta_arma(str(p_halo_in), str(p_halo_out))
    assert info_pg["ok"] is True and float(info_pg.get("halo_semitransparente", 0.0)) < 0.005
    with Image.open(p_halo_out) as im_pg_out:
        alphas_pg = {im_pg_out.getpixel((x, y))[3] for y in range(im_pg_out.height) for x in range(im_pg_out.width)}
        assert alphas_pg <= {0, 255}

    img_big = Image.new("RGBA", (284, 284), (0, 0, 0, 0))
    ImageDraw.Draw(img_big).rectangle((2, 2, 281, 281), fill=(180, 140, 90, 255))
    rec_big = cc.recortar_com_margem_segura(img_big, margem_frac=0.12)
    assert rec_big.width > 284 and rec_big.height > 284
    fg_count = sum(1 for y in range(rec_big.height) for x in range(rec_big.width) if rec_big.getpixel((x, y))[3] > 0)
    area_fg = fg_count / float(rec_big.width * rec_big.height)
    assert area_fg <= 0.65, f"Canvas nao expandiu o suficiente: area_fg={area_fg:.4f} ({rec_big.size})"

    monkeypatch.delenv("FORGE3D_REMBG_MODELO", raising=False)
    monkeypatch.setattr(cc, "onnx_tem_cuda", lambda: False)
    assert cc.modelo_rembg_padrao_cpu() == "u2net"
    monkeypatch.setenv("FORGE3D_I23D_DEVICE", "cpu")
    assert mesh_diag._rembg_modelo() == "u2net"
    assert cc.criar_sessao_rembg_otimizada(SimpleNamespace(new_session=lambda m: f"s:{m}"), "u2net") == "s:u2net"
    assert pg._recorte_rapido_estudio(Image.new("RGB", (32, 32), (128, 128, 128)), (128.0, 128.0, 128.0)) is None
    monkeypatch.setitem(sys.modules, "rembg", SimpleNamespace(new_session=lambda _m: (_ for _ in ()).throw(LookupError("No session class found"))))
    p_lk_in, p_lk_out = tmp_path / "lk_in.png", tmp_path / "lk_out.png"
    img_op = Image.new("RGBA", (64, 64), (240, 240, 240, 255))
    ImageDraw.Draw(img_op).rectangle((16, 16, 48, 48), fill=(180, 60, 40, 255))
    img_op.save(p_lk_in)
    assert pg.decompor_silhueta_arma(p_lk_in, p_lk_out)["ok"] is True and p_lk_out.is_file()


# ------------------------------------------------------------------ 7. concept_views_origem.py (GAP-067 #3)
def test_gap067_concept_views_origem_prompt_com_pipe_e_refresh_front_sha256(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origem_png = tmp_path / "origem.png"
    Image.new("RGBA", (64, 64), (210, 80, 60, 255)).save(origem_png)
    destino = tmp_path / "vistas"
    destino.mkdir()
    stale_front = destino / "concept_front.png"
    Image.new("RGBA", (64, 64), (20, 40, 200, 255)).save(stale_front)
    assert stale_front.read_bytes() != origem_png.read_bytes()

    prompts_recebidos: list[str] = []

    def fake_gemini(_ai: Any, prompt: str, _neg: str, seed: int, out_png: Path, **_kw: Any) -> dict[str, Any]:
        prompts_recebidos.append(prompt)
        Image.new("RGBA", (64, 64), (90, 120, 150, 255)).save(out_png)
        return {"ok": True, "tempo_s": 0.01, "modelo": "gemini/test", "seed": seed}

    monkeypatch.setattr(concept_views_origem, "_chamar_gemini_conceito", fake_gemini)
    res = concept_views_origem.gerar_vista_traseira_de_origem(
        {"id": "relic.01", "prompt": "dino | relic | ancient", "vistas": 4},
        origem_png, destino,
    )
    assert res["ok"] is True
    assert prompts_recebidos and "dino | relic | ancient" in prompts_recebidos[0]
    assert stale_front.read_bytes() == origem_png.read_bytes()


# ------------------------------------------------------------------ 8. concept_preflight.py
def test_concept_preflight_autopad_aspect_icone_legacy64_e_topdown(tmp_path: Path) -> None:
    from forge3d.providers import concept_preflight as cp

    p_tight = tmp_path / "tight.png"
    im_tight = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    px_t: Any = im_tight.load()
    for y in range(8, 248):
        for x in range(8, 248):
            v = 60 + ((x * 3 + y * 5) % 140)
            px_t[x, y] = (v, max(20, v - 20), min(255, v + 15), 255)
    im_tight.save(p_tight)
    p_padded, rel_pad = cp.validar_e_preparar_concept_2d(
        p_tight, tmp_path / "out_pad", item={"id": "egg.01", "tipo": "prop_estatico"}
    )
    assert rel_pad["auto_padded"] is True and float(rel_pad["fg_fill_pos"]) <= 0.65 and p_padded.is_file()

    p_mast = tmp_path / "mast.png"
    im_mast = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    px_m: Any = im_mast.load()
    for y in range(28, 228):
        for x in range(112, 144):
            v = 70 + ((x * 7 + y * 3) % 120)
            px_m[x, y] = (v, v, v, 255)
    im_mast.save(p_mast)

    rel_prop = cp.avaliar_concept_2d(p_mast, item={"id": "prop.mastro", "tipo": "prop_estatico"})
    assert rel_prop["aprovado"] is False and any("aspect" in f for f in rel_prop["falhas"])
    assert cp.avaliar_concept_2d(p_mast, item={"id": "arma.lanca", "tipo": "prop_equipavel", "parte": "arma"})["aprovado"] is True
    assert cp.avaliar_concept_2d(p_mast, item={"id": "prop.lanca2d", "tipo": "prop_estatico", "extrudir_2d": True})["aprovado"] is True

    p_icon = tmp_path / "icon256.png"
    im_icon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ImageDraw.Draw(im_icon).rectangle((32, 32, 224, 224), fill=(120, 150, 200, 255))
    im_icon.save(p_icon)
    rel_icon = cp.avaliar_concept_2d(p_icon, item={"id": "prop.icone", "tipo": "prop_estatico"})
    assert rel_icon["aprovado"] is False and "icone_2d_plano" in rel_icon["falhas"]

    p_mock64 = tmp_path / "mock64.png"
    Image.new("RGBA", (64, 64), (255, 0, 0, 255)).save(p_mock64)
    rel_mock64 = cp.avaliar_concept_2d(p_mock64, item={"id": "prop.mock", "tipo": "prop_estatico"})
    assert rel_mock64["aprovado"] is True and "icone_2d_plano" not in rel_mock64["falhas"]
    p_blank = tmp_path / "blank_chrom256.png"
    Image.new("RGBA", (256, 256), (20, 180, 90, 255)).save(p_blank)
    assert "silhueta_vazia" in cp.avaliar_concept_2d(p_blank, item={"id": "prop.blank", "tipo": "prop_estatico"})["erros"]

    p_top45 = tmp_path / "top45.png"
    im_top = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    px_top: Any = im_top.load()
    for y in range(40, 150):
        for x in range(110, 146):
            v = 160 + ((x * 5 + y * 3) % 70)
            px_top[x, y] = (v, v - 10, v - 20, 255)
    for y in range(150, 224):
        for x in range(36, 220):
            v = 18 + ((x + y) % 18)
            px_top[x, y] = (v, v, v + 4, 255)
    im_top.save(p_top45)
    rel_top = cp.avaliar_concept_2d(p_top45, item={"id": "prop.top45", "tipo": "prop_estatico"})
    assert "vista_topo_45_suspeita" in rel_top["avisos"], rel_top


# ------------------------------------------------------------------ 9. GPU lock scoping (pipeline_item + mesh + mesh_trellis)
def test_gpu_lock_desacoplado_de_concept_cutout_preflight_e_exclusivo_no_trellis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from forge3d.providers import concept_preflight as cp
    from tests.test_v098_trellis import _criar_fake_trellis2_dir

    t2_dir = _criar_fake_trellis2_dir(tmp_path)
    monkeypatch.setenv("FORGE3D_TRELLIS2_DIR", str(t2_dir))
    monkeypatch.setenv("FORGE3D_I23D_DEVICE", "cuda:0")
    monkeypatch.setenv("FORGE3D_MODELO_MESH", "trellis2")

    lock_state: dict[str, Any] = {"held": False, "acquisitions": 0}
    trace: list[tuple[str, bool]] = []

    @contextlib.contextmanager
    def spy_lock_gpu(_run_id: str, esperar: bool = False):
        lock_state["held"] = True
        lock_state["acquisitions"] = int(lock_state["acquisitions"]) + 1
        trace.append(("gpu_lock_enter", True))
        try:
            yield
        finally:
            lock_state["held"] = False
            trace.append(("gpu_lock_exit", False))

    monkeypatch.setattr(locks, "lock_gpu", spy_lock_gpu)
    concept_png = tmp_path / "concept_cloud.png"
    Image.new("RGBA", (64, 64), (180, 140, 90, 255)).save(concept_png)

    prov = mesh.MeshProvider()
    assert getattr(prov, "gerencia_lock_gpu", False) is True
    monkeypatch.setattr(prov, "preflight_item", lambda _item: (True, "ok"))

    def spy_resolver_entrada(_item: dict, dest: Path, _env: dict) -> tuple[Path, dict]:
        trace.append(("cloud_concept", bool(lock_state["held"])))
        out_c = dest / "concept.png"
        out_c.write_bytes(concept_png.read_bytes())
        return out_c, {"provedor_concept": "gemini"}

    monkeypatch.setattr(prov, "_resolver_entrada", spy_resolver_entrada)
    orig_prep = mesh_trellis._preparar_inputs_locais

    def spy_prep(imagem: Path, dest: Path, env: dict):
        trace.append(("cpu_cutout", bool(lock_state["held"])))
        return orig_prep(imagem, dest, env)

    monkeypatch.setattr(mesh_trellis, "_preparar_inputs_locais", spy_prep)
    orig_preflight = cp.validar_e_preparar_concept_2d

    def spy_preflight(*a: Any, **kw: Any):
        trace.append(("preflight_2d", bool(lock_state["held"])))
        return orig_preflight(*a, **kw)

    monkeypatch.setattr(cp, "validar_e_preparar_concept_2d", spy_preflight)

    def spy_trellis_subproc(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
        if any("trellis2_infer.py" in str(c) for c in cmd):
            trace.append(("trellis2_infer", bool(lock_state["held"])))
            out_dir = Path(cmd[cmd.index("--saida-dir") + 1])
            res_path = Path(cmd[cmd.index("--resultado") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "modelo.glb").write_bytes(b"glTF\x02\x00\x00\x00")
            res_path.write_text(json.dumps({"ok": True, "faces": 4000}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mesh_trellis._diag, "subproc_run", spy_trellis_subproc)
    monkeypatch.setattr(pipeline_item.providers, "obter", lambda _r: prov)
    (tmp_path / "final_ok").mkdir(exist_ok=True)
    arq_ok = [{"caminho": "prop.glb", "papel": "mesh", "sha256": "sha256:" + "0" * 64, "bytes": 12, "nivel": 0, "triangulos": 12}]
    monkeypatch.setattr(pipeline_item, "_pos_processar", lambda *_a, **_k: {"dir_final": str(tmp_path / "final_ok"), "arquivos": arq_ok, "medidas": {}})
    med_ok = {"triangulos": 12, "vertices": 8, "bbox_m": [1.0, 1.0, 1.0], "materiais": 1}
    monkeypatch.setattr(qc, "verificar", lambda *_a, **_k: {"aprovado": True, "gates": [{"id": "G1", "status": "ok"}], "medidas": med_ok})
    monkeypatch.setattr(publish, "salvar_cache", lambda *_a, **_k: None)

    pipeline_item.executar_item(
        {"id": "prop.lock.01", "tipo": "prop_estatico", "rota": "mesh", "prompt": "stone relic"},
        {"chave": "k_lock"}, spec_doc={"projeto": "demo", "perfil": "godot4"},
        perfil=profiles.carregar("godot4"), spec_hash="sha256:" + "a" * 64,
        destino=tmp_path / "out_ok", run_id="run-lock-1", publicar_arquivos=False, no_cache=True,
    )
    assert ("cloud_concept", False) in trace and ("cpu_cutout", False) in trace
    assert ("preflight_2d", False) in trace and ("trellis2_infer", True) in trace
    assert lock_state["acquisitions"] == 1

    lock_state["acquisitions"] = 0
    trace.clear()
    bad_icon = tmp_path / "bad_icon_256.png"
    im_bad = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ImageDraw.Draw(im_bad).rectangle((32, 32, 224, 224), fill=(100, 120, 140, 255))
    im_bad.save(bad_icon)

    with pytest.raises(ForgeError):
        mesh_trellis.executar_i23d_trellis2_local(
            {"id": "prop.bad.01", "tipo": "prop_estatico"},
            tmp_path / "out_bad", bad_icon, {},
            gpu_lock_factory=lambda: spy_lock_gpu("run-lock-bad"),
        )
    assert lock_state["acquisitions"] == 0
    assert not any(ev == "trellis2_infer" for ev, _ in trace)
