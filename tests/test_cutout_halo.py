"""Regressao do halo escuro no recorte T2I + rembg e prompt negativo do concept."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from forge3d.providers import concept

RAIZ = Path(__file__).resolve().parents[1]
I23D_PATH = RAIZ / "tools" / "i23d_infer.py"


def _carregar_i23d():
    spec = importlib.util.spec_from_file_location("i23d_infer_test", I23D_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _instalar_rembg_falso(monkeypatch, recortada: Image.Image) -> None:
    """Stubs de ``rembg`` e ``tsr.utils`` simulando ``naive_cutout`` sem GPU."""

    def _remove_background(image: Image.Image, _sessao=None) -> Image.Image:
        if image.mode == "RGBA" and image.getextrema()[3][0] < 255:
            return image
        return recortada.copy()

    def _resize_foreground(image: Image.Image, _ratio: float) -> Image.Image:
        return image

    monkeypatch.setitem(sys.modules, "rembg", SimpleNamespace(new_session=lambda: object()))
    monkeypatch.setitem(
        sys.modules,
        "tsr.utils",
        SimpleNamespace(
            remove_background=_remove_background,
            resize_foreground=_resize_foreground,
        ),
    )


def _recorte_premultiplicado_cinza_claro() -> Image.Image:
    """Cria recorte pre-multiplicado (via Image.composite) com borda semitransparente e ruido."""
    fg = Image.new("RGBA", (64, 64), (210, 210, 210, 255))
    mask = Image.new("L", (64, 64), 0)
    for y in range(11, 53):
        for x in range(11, 53):
            if 13 <= x < 51 and 13 <= y < 51:
                mask.putpixel((x, y), 255)
            elif 12 <= x < 52 and 12 <= y < 52:
                mask.putpixel((x, y), 128)
            else:
                mask.putpixel((x, y), 64)
    # Ruido fraco de fundo (< 24/255) nos cantos
    for x, y in ((1, 1), (2, 1), (62, 62)):
        mask.putpixel((x, y), 12)
    return Image.composite(fg, Image.new("RGBA", fg.size, 0), mask)


def test_premultiplied_composite_fringe_sem_halo_escuro(monkeypatch, tmp_path):
    mod = _carregar_i23d()
    recorte = _recorte_premultiplicado_cinza_claro()
    _instalar_rembg_falso(monkeypatch, recorte)

    entrada = tmp_path / "entrada_opaca.png"
    Image.new("RGB", (64, 64), (210, 210, 210)).save(entrada)

    saida = mod._preparar_imagem(str(entrada), remover_fundo=True, foreground_ratio=0.85)
    assert saida.mode == "RGB"

    # Nenhum pixel pode cair abaixo do cinza neutro (128) — antes caia para ~114 no anel de borda.
    for y in range(64):
        for x in range(64):
            r, g, b = saida.getpixel((x, y))
            assert min(r, g, b) >= 128, f"halo escuro em ({x}, {y}): {(r, g, b)}"

    # Ruido fraco foi zerado para o fundo neutro exato e o interior preservou a cor original.
    assert saida.getpixel((1, 1)) == (128, 128, 128)
    assert saida.getpixel((32, 32)) == (210, 210, 210)


def test_straight_alpha_cutout_preserva_cores_sem_lavar_nem_escurecer(monkeypatch, tmp_path):
    mod = _carregar_i23d()

    # Caso 1: borda cinza-clara em alfa reto -> composicao unica >= 128 e interior intacto
    clara = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    for y in range(6, 26):
        for x in range(6, 26):
            alfa = 255 if (8 <= x < 24 and 8 <= y < 24) else 128
            clara.putpixel((x, y), (210, 210, 210, alfa))
    p_clara = tmp_path / "straight_clara.png"
    clara.save(p_clara)

    out_clara = mod._preparar_imagem(str(p_clara), remover_fundo=False, foreground_ratio=0.85)
    assert out_clara.getpixel((0, 0)) == (128, 128, 128)
    assert out_clara.getpixel((6, 16))[0] >= 168
    assert out_clara.getpixel((16, 16)) == (210, 210, 210)

    # Caso 2: objeto colorido em alfa reto (R/G < A) nao pode ser desmultiplicado por engano
    colorida = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    for y in range(6, 26):
        for x in range(6, 26):
            alfa = 255 if (8 <= x < 24 and 8 <= y < 24) else 128
            colorida.putpixel((x, y), (60, 100, 180, alfa))
    p_colorida = tmp_path / "straight_colorida.png"
    colorida.save(p_colorida)

    out_sem = mod._preparar_imagem(str(p_colorida), remover_fundo=False, foreground_ratio=0.85)
    # Composicao linear esperada: 0.502*fg + 0.498*128 ~= (94, 114, 154)
    r, g, b = out_sem.getpixel((6, 16))
    assert abs(r - 94) <= 2 and abs(g - 114) <= 2 and abs(b - 154) <= 2
    assert out_sem.getpixel((16, 16)) == (60, 100, 180)

    # Mesmo com remover_fundo=True, remove_background pula rembg quando ja ha alfa -> nao lava cor
    _instalar_rembg_falso(monkeypatch, colorida)
    out_com = mod._preparar_imagem(str(p_colorida), remover_fundo=True, foreground_ratio=0.85)
    assert out_com.getpixel((6, 16)) == out_sem.getpixel((6, 16))


def test_braco_fino_maior_que_8_por_cento_nao_e_apagado(monkeypatch, tmp_path):
    mod = _carregar_i23d()

    # Braco fino 6x58 em 64x64 = 348/4096 (~8.5%): MinFilter(3) derrubaria para 4x56 (~5.5% < 8%)
    fg = Image.new("RGBA", (64, 64), (220, 160, 120, 255))
    mask = Image.new("L", (64, 64), 0)
    for y in range(3, 61):
        for x in range(29, 35):
            alfa = 255 if (30 <= x < 34 and 4 <= y < 60) else 128
            mask.putpixel((x, y), alfa)
    recorte = Image.composite(fg, Image.new("RGBA", fg.size, 0), mask)
    _instalar_rembg_falso(monkeypatch, recorte)

    entrada = tmp_path / "braco_fino.png"
    Image.new("RGB", (64, 64), (220, 160, 120)).save(entrada)

    saida = mod._preparar_imagem(str(entrada), remover_fundo=True, foreground_ratio=0.85)
    # A borda do braco (x=29, y=30) deve permanecer visivel (nao erodida para 128) e sem halo escuro
    r_borda, g_borda, b_borda = saida.getpixel((29, 30))
    assert r_borda > 160 and g_borda >= 128 and b_borda >= 120
    assert saida.getpixel((31, 30)) == (220, 160, 120)


def test_concept_negativo_inclui_guardas_de_halo_dentro_do_orcamento_clip():
    assert "isolated object" in concept.SUFIXO_PADRAO
    assert "high detail" in concept.SUFIXO_PADRAO

    neg = concept.NEGATIVO_PADRAO.lower()
    for termo in ("halo", "rim light", "backlighting", "shadow", "drop shadow", "white border"):
        assert termo in neg, f"termo ausente em NEGATIVO_PADRAO: {termo}"

    assert concept.estimar_tokens_clip(concept.NEGATIVO_PADRAO) <= concept.LIMITE_TOKENS_CLIP
