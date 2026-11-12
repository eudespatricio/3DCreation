"""Testes de Pose Guard, Delight/PBR Hints, BiRefNet fallback, Extrude 2D wiring e bench_i23d."""

from __future__ import annotations

import ast
import importlib.util
import json
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFilter

from forge3d.providers import concept, mesh

RAIZ = Path(__file__).resolve().parents[1]
POSE_GUARD_PATH = RAIZ / "tools" / "pose_guard.py"
DELIGHT_PATH = RAIZ / "tools" / "delight.py"
I23D_PATH = RAIZ / "tools" / "i23d_infer.py"
CONCEPT_INFER_PATH = RAIZ / "tools" / "concept_infer.py"
BENCH_PATH = RAIZ / "tools" / "bench_i23d.py"
MESH_PY_PATH = RAIZ / "src" / "forge3d" / "providers" / "mesh.py"


def _carregar_modulo(nome: str, caminho: Path):
    spec = importlib.util.spec_from_file_location(nome, caminho)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _desenhar_silhueta_tpose(caminho: Path) -> Path:
    img = Image.new("RGBA", (256, 256), (128, 128, 128, 255))
    d = ImageDraw.Draw(img)
    # Cabeca
    d.ellipse((112, 20, 144, 52), fill=(210, 180, 160, 255))
    # Tronco
    d.rectangle((104, 54, 152, 148), fill=(70, 90, 140, 255))
    # Bracos horizontais em T-pose (20%..32%)
    d.rectangle((24, 58, 232, 78), fill=(190, 195, 205, 255))
    # Pernas
    d.rectangle((106, 148, 124, 232), fill=(50, 55, 70, 255))
    d.rectangle((132, 148, 150, 232), fill=(50, 55, 70, 255))
    img.save(caminho)
    return caminho


def _desenhar_silhueta_apose(caminho: Path) -> Path:
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((112, 20, 144, 52), fill=(210, 180, 160, 255))
    d.rectangle((106, 54, 150, 148), fill=(70, 90, 140, 255))
    # Bracos abertos em ~40 graus deixando espaco de ar entre torso e bracos
    d.polygon([(106, 58), (98, 72), (50, 136), (62, 144)], fill=(190, 195, 205, 255))
    d.polygon([(150, 58), (158, 72), (206, 136), (194, 144)], fill=(190, 195, 205, 255))
    d.rectangle((108, 148, 124, 232), fill=(50, 55, 70, 255))
    d.rectangle((132, 148, 148, 232), fill=(50, 55, 70, 255))
    img.save(caminho)
    return caminho


def _desenhar_silhueta_arms_down(caminho: Path) -> Path:
    img = Image.new("RGBA", (256, 256), (128, 128, 128, 255))
    d = ImageDraw.Draw(img)
    d.ellipse((112, 20, 144, 52), fill=(210, 180, 160, 255))
    # Tronco + bracos colados ao lado sem fresta de ar
    d.rectangle((92, 54, 164, 152), fill=(70, 90, 140, 255))
    # Pernas coladas
    d.rectangle((106, 152, 150, 232), fill=(50, 55, 70, 255))
    img.save(caminho)
    return caminho


def _criar_glb_cubo_com_textura(caminho: Path, tex_img: Image.Image) -> Path:
    """Constroi um GLB valido minimo (cubo unitario + textura baseColor PNG embutida)."""
    import io

    verts = [
        (-0.5, 0.0, -0.5),
        (0.5, 0.0, -0.5),
        (0.5, 1.0, -0.5),
        (-0.5, 1.0, -0.5),
        (-0.5, 0.0, 0.5),
        (0.5, 0.0, 0.5),
        (0.5, 1.0, 0.5),
        (-0.5, 1.0, 0.5),
    ]
    tris = [
        (0, 1, 2),
        (0, 2, 3),
        (4, 6, 5),
        (4, 7, 6),
        (0, 4, 5),
        (0, 5, 1),
        (3, 2, 6),
        (3, 6, 7),
        (0, 3, 7),
        (0, 7, 4),
        (1, 5, 6),
        (1, 6, 2),
    ]
    pos_bytes = b"".join(struct.pack("<fff", *v) for v in verts)
    idx_bytes = b"".join(struct.pack("<HHH", *t) for t in tris)
    buf_png = io.BytesIO()
    tex_img.save(buf_png, format="PNG")
    png_bytes = buf_png.getvalue()

    def _pad4(b: bytes) -> bytes:
        rem = len(b) % 4
        return b + (b"\x00" * (4 - rem) if rem else b"")

    pos_off = 0
    idx_off = len(_pad4(pos_bytes))
    png_off = idx_off + len(_pad4(idx_bytes))
    bin_chunk = _pad4(pos_bytes) + _pad4(idx_bytes) + _pad4(png_bytes)

    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "material": 0,
                    }
                ]
            }
        ],
        "materials": [
            {
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.8,
                }
            }
        ],
        "textures": [{"source": 0}],
        "images": [{"bufferView": 2, "mimeType": "image/png"}],
        "buffers": [{"byteLength": len(bin_chunk)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": pos_off, "byteLength": len(pos_bytes)},
            {"buffer": 0, "byteOffset": idx_off, "byteLength": len(idx_bytes)},
            {"buffer": 0, "byteOffset": png_off, "byteLength": len(png_bytes)},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(verts),
                "type": "VEC3",
                "min": [-0.5, 0.0, -0.5],
                "max": [0.5, 1.0, 0.5],
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": len(tris) * 3,
                "type": "SCALAR",
            },
        ],
    }
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    pad_j = (4 - len(json_bytes) % 4) % 4
    json_chunk = json_bytes + b" " * pad_j

    total_len = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    glb = (
        struct.pack("<III", 0x46546C67, 2, total_len)
        + struct.pack("<II", len(json_chunk), 0x4E4F534A)
        + json_chunk
        + struct.pack("<II", len(bin_chunk), 0x004E4942)
        + bin_chunk
    )
    caminho.write_bytes(glb)
    return caminho


# ------------------------------------------------------------------ Pose Guard


def test_pose_guard_distingue_tpose_apose_de_arms_down(tmp_path):
    pg = _carregar_modulo("pose_guard_test", POSE_GUARD_PATH)

    tpose = _desenhar_silhueta_tpose(tmp_path / "tpose.png")
    apose = _desenhar_silhueta_apose(tmp_path / "apose.png")
    arms_down = _desenhar_silhueta_arms_down(tmp_path / "arms_down.png")

    r_t = pg.detectar_pose_imagem(str(tpose))
    r_a = pg.detectar_pose_imagem(str(apose))
    r_d = pg.detectar_pose_imagem(str(arms_down))

    assert r_t["pose"] == "tpose_apose", r_t
    assert r_t["precisa_repose"] is False
    assert r_t["largura_ombros"] > 0.7

    assert r_a["pose"] == "tpose_apose", r_a
    assert r_a["precisa_repose"] is False
    assert r_a["razao_flanco"] > 0.25

    assert r_d["pose"] == "arms_down", r_d
    assert r_d["precisa_repose"] is True
    assert r_d["largura_ombros"] < 0.45


def test_pose_guard_decompor_silhueta_arma_recorta_espada(tmp_path):
    pg = _carregar_modulo("pose_guard_arma_test", POSE_GUARD_PATH)
    src = tmp_path / "espada.png"
    out = tmp_path / "espada_cutout.png"

    # Espada vertical centralizada em imagem com alpha transparente
    img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((60, 14, 68, 92), fill=(200, 205, 215, 255))
    d.rectangle((46, 92, 82, 98), fill=(210, 170, 50, 255))
    d.rectangle((61, 98, 67, 118), fill=(110, 70, 40, 255))
    # Pequeno ruido isolado no canto que deve ser descartado
    img.putpixel((2, 2), (255, 0, 0, 255))
    img.save(src)

    info = pg.decompor_silhueta_arma(str(src), str(out))
    assert info["ok"] is True
    assert out.is_file()
    with Image.open(out) as cut:
        assert cut.mode == "RGBA"
        assert cut.width < 60  # recortou margens transparentes
        assert cut.getpixel((0, 0))[3] == 0


# ------------------------------------------------------------------ Delight & PBR


def test_delight_achata_ponto_especular_e_preserva_alfa(tmp_path):
    dl = _carregar_modulo("delight_test", DELIGHT_PATH)

    img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Pano azul medio uniforme com mancha especular branca no centro
    d.rectangle((16, 16, 112, 112), fill=(55, 85, 160, 255))
    d.ellipse((56, 56, 72, 72), fill=(255, 255, 255, 255))
    img.putpixel((20, 20), (55, 85, 160, 180))

    delit = dl.delight_imagem(img)
    assert delit.mode == "RGBA"
    assert delit.size == img.size
    # Canal alfa intacto
    assert delit.getpixel((0, 0))[3] == 0
    assert delit.getpixel((20, 20))[3] == 180
    assert delit.getpixel((64, 64))[3] == 255
    # Ponto especular foi achatado significativamente abaixo de 255
    assert max(delit.getpixel((64, 64))[:3]) < 225
    # Azul base permanece preservado (B dominante)
    r_b, g_b, b_b, _ = delit.getpixel((28, 28))
    assert b_b > r_b + 40 and b_b > g_b + 20


def _desenhar_placa_pbr(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    # Bloco prata com sombreamento/chanfro metalico realista
    d.rectangle((10, 10, 54, 54), fill=(180, 185, 195, 255))
    for offset in range(12, 52, 6):
        d.line((10, offset, 54, offset), fill=(225, 230, 238, 255), width=2)
        d.line((10, offset + 3, 54, offset + 3), fill=(110, 115, 125, 255), width=2)
    # Bloco ouro/latao (H ~ 43 deg, S ~ 185, V = 215)
    d.rectangle((70, 10, 114, 54), fill=(215, 170, 58, 255))
    # Bloco pano azul fosco
    d.rectangle((10, 70, 54, 114), fill=(50, 72, 138, 255))
    # Bloco pele/couro
    d.rectangle((70, 70, 114, 114), fill=(150, 95, 58, 255))


def test_estimar_mapas_pbr_metal_prata_ouro_vs_pano():
    dl = _carregar_modulo("delight_pbr_test", DELIGHT_PATH)

    img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    _desenhar_placa_pbr(img)

    metallic, roughness = dl.estimar_mapas_pbr(img)
    assert metallic.mode == "L"
    assert roughness.mode == "L"
    assert metallic.getpixel((24, 24)) > 180  # prata (chanfro/armadura)
    assert metallic.getpixel((92, 32)) > 180  # ouro
    assert metallic.getpixel((32, 92)) < 30   # pano
    assert metallic.getpixel((92, 92)) < 30   # couro/pele
    assert roughness.getpixel((92, 32)) < 110  # metal liso (~0.25..0.38)
    assert roughness.getpixel((92, 92)) == 140  # couro/pele (~0.55)
    assert roughness.getpixel((32, 92)) > 180  # pano (~0.82)


def test_pbr_sem_halo_metalico_em_silhueta_sobre_cinza_neutro_128():
    """Regressao: input.png opaco sobre cinza (128,128,128) nao gera anel metalico de borda."""
    dl = _carregar_modulo("delight_halo_test", DELIGHT_PATH)
    img = Image.new("RGBA", (192, 192), (128, 128, 128, 255))
    d = ImageDraw.Draw(img)
    # Silhueta opaca com roupa branca uniforme, calca escura e fivela dourada
    d.rectangle((64, 36, 128, 96), fill=(215, 215, 218, 255))
    d.rectangle((68, 96, 124, 168), fill=(40, 45, 58, 255))
    d.rectangle((86, 92, 106, 102), fill=(215, 170, 58, 255))

    metallic, _roughness = dl.estimar_mapas_pbr(img)
    # Todo pixel de fundo (fora da caixa [64..128, 36..168]) deve ter metallic == 0
    for y in range(192):
        for x in range(192):
            if not (64 <= x <= 128 and 36 <= y <= 168):
                assert metallic.getpixel((x, y)) == 0, f"halo metalico em ({x}, {y})"
    # Borda do tecido branco uniforme contra o fundo neutro tambem fica 0
    assert metallic.getpixel((65, 50)) == 0
    assert metallic.getpixel((96, 97)) > 180  # fivela dourada continua metalica


def test_pbr_cabelo_escuro_com_brilho_nao_vira_metal_prata():
    """Regressao: mechas pretas com reflexos claros (L baixo ao redor) permanecem foscas."""
    dl = _carregar_modulo("delight_hair_test", DELIGHT_PATH)
    img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((24, 16, 104, 112), fill=(26, 28, 32, 255))
    for offset in range(24, 104, 10):
        d.line((30, offset, 98, offset), fill=(190, 194, 200, 255), width=2)

    metallic, roughness = dl.estimar_mapas_pbr(img)
    for y in range(20, 108):
        for x in range(30, 98):
            assert metallic.getpixel((x, y)) < 20
            assert roughness.getpixel((x, y)) > 180


@pytest.mark.skipif(
    not (Path.home() / ".cache" / "forge3d" / "venv-i23d" / "bin" / "python").is_file(),
    reason="venv-i23d nao instalada neste host",
)
def test_pose_guard_e_delight_cli_cv2_na_venv_i23d(tmp_path):
    """Garante execucao real com cv2+numpy nas ferramentas CLI dentro da venv-i23d."""
    py = str(Path.home() / ".cache" / "forge3d" / "venv-i23d" / "bin" / "python")
    tpose = _desenhar_silhueta_tpose(tmp_path / "tpose.png")
    pg_json = tmp_path / "pg.json"
    p1 = subprocess.run(
        [py, str(POSE_GUARD_PATH), "--imagem", str(tpose), "--resultado", str(pg_json)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert p1.returncode == 0
    pg_res = json.loads(pg_json.read_text(encoding="utf-8"))
    assert pg_res["ok"] is True
    assert pg_res["pose"] == "tpose_apose"

    dl_json = tmp_path / "dl.json"
    albedo = tmp_path / "albedo.png"
    metallic = tmp_path / "metallic.png"
    roughness = tmp_path / "roughness.png"
    p2 = subprocess.run(
        [
            py,
            str(DELIGHT_PATH),
            "--imagem",
            str(tpose),
            "--saida-albedo",
            str(albedo),
            "--saida-metallic",
            str(metallic),
            "--saida-roughness",
            str(roughness),
            "--resultado",
            str(dl_json),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert p2.returncode == 0
    dl_res = json.loads(dl_json.read_text(encoding="utf-8"))
    assert dl_res["ok"] is True
    assert dl_res["backend"] == "cv2+numpy"
    assert albedo.is_file() and metallic.is_file() and roughness.is_file()

    # Verifica tambem arms_down e mascaras PBR em imagem com armadura prata/ouro vs pano no cv2
    arms_down = _desenhar_silhueta_arms_down(tmp_path / "arms_down.png")
    pg_down_json = tmp_path / "pg_down.json"
    subprocess.run(
        [py, str(POSE_GUARD_PATH), "--imagem", str(arms_down), "--resultado", str(pg_down_json)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(pg_down_json.read_text(encoding="utf-8"))["pose"] == "arms_down"

    pbr_in = tmp_path / "pbr_in.png"
    img_pbr = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    _desenhar_placa_pbr(img_pbr)
    img_pbr.save(pbr_in)

    m_cv2 = tmp_path / "m_cv2.png"
    r_cv2 = tmp_path / "r_cv2.png"
    dl_cv2 = tmp_path / "dl_cv2.json"
    subprocess.run(
        [
            py,
            str(DELIGHT_PATH),
            "--imagem",
            str(pbr_in),
            "--saida-metallic",
            str(m_cv2),
            "--saida-roughness",
            str(r_cv2),
            "--resultado",
            str(dl_cv2),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    with Image.open(m_cv2) as mm, Image.open(r_cv2) as rr:
        assert mm.getpixel((24, 24)) > 180
        assert mm.getpixel((92, 32)) > 180
        assert mm.getpixel((32, 92)) < 30
        assert rr.getpixel((92, 32)) < 110
        assert rr.getpixel((32, 92)) > 180

    # Verifica tambem ausencia de halo metalico sobre fundo cinza (128,128,128) opaco no cv2
    opaco_in = tmp_path / "opaco_128.png"
    img_op = Image.new("RGB", (192, 192), (128, 128, 128))
    d_op = ImageDraw.Draw(img_op)
    d_op.rectangle((64, 36, 128, 96), fill=(215, 215, 218))
    d_op.rectangle((68, 96, 124, 168), fill=(40, 45, 58))
    d_op.rectangle((86, 92, 106, 102), fill=(215, 170, 58))
    img_op.save(opaco_in)
    m_op = tmp_path / "m_op.png"
    subprocess.run(
        [py, str(DELIGHT_PATH), "--imagem", str(opaco_in), "--saida-metallic", str(m_op)],
        capture_output=True,
        text=True,
        check=True,
    )
    with Image.open(m_op) as mm_op:
        assert mm_op.getpixel((60, 50)) == 0
        assert mm_op.getpixel((65, 50)) == 0
        assert mm_op.getpixel((132, 120)) == 0
        assert mm_op.getpixel((96, 97)) > 180


# ------------------------------------------------------------------ BiRefNet fallback


def test_i23d_criar_sessao_rembg_fallback_offline_para_u2net(monkeypatch):
    mod = _carregar_modulo("i23d_rembg_test", I23D_PATH)
    chamadas: list[str] = []

    def fake_new_session(model_name: str = "u2net"):
        chamadas.append(model_name)
        if model_name == "birefnet-general":
            raise ConnectionError("offline")
        return f"sessao:{model_name}"

    monkeypatch.setitem(sys.modules, "rembg", SimpleNamespace(new_session=fake_new_session))
    sessao, usado, fallback = mod._criar_sessao_rembg("birefnet-general")
    assert sessao == "sessao:u2net"
    assert usado == "u2net"
    assert fallback is True
    assert chamadas == ["birefnet-general", "u2net"]

    # Quando o modelo solicitado funciona, nao ativa fallback.
    def fake_ok(model_name: str = "u2net"):
        return f"sessao:{model_name}"

    monkeypatch.setitem(sys.modules, "rembg", SimpleNamespace(new_session=fake_ok))
    sessao2, usado2, fallback2 = mod._criar_sessao_rembg("birefnet-general")
    assert sessao2 == "sessao:birefnet-general"
    assert usado2 == "birefnet-general"
    assert fallback2 is False

    # Nome de modelo inexistente propaga ValueError em vez de mascarar erro.
    def fake_unknown(model_name: str = "u2net"):
        raise ValueError(f"No session class found for model '{model_name}'")

    monkeypatch.setitem(sys.modules, "rembg", SimpleNamespace(new_session=fake_unknown))
    with pytest.raises(ValueError):
        mod._criar_sessao_rembg("modelo_desconhecido")


# ------------------------------------------------------------------ concept_infer img2img


def test_concept_infer_controlnet_img2img_cpu_mock(monkeypatch, tmp_path):
    mod = _carregar_modulo("concept_infer_img2img_test", CONCEPT_INFER_PATH)

    init_img = tmp_path / "init.png"
    pose_img = tmp_path / "pose.png"
    Image.new("RGBA", (64, 64), (180, 120, 80, 255)).save(init_img)
    Image.new("RGB", (64, 64), (0, 0, 0)).save(pose_img)
    saida = tmp_path / "repose.png"
    res_json = tmp_path / "repose.json"
    capturado: dict = {}

    class _FakeVae:
        def to(self, dtype=None):
            return None

        def decode(self, z, *a, **kw):
            return [z]

    class _FakeTok:
        eos_token_id = 2

        def __call__(self, txt, truncation=False, add_special_tokens=True):
            return {"input_ids": [1, 2, 3]}

        def decode(self, ids, skip_special_tokens=True):
            return "hero"

    class _FakePipe:
        def __init__(self):
            self.tokenizer = _FakeTok()
            self.vae = _FakeVae()
            self.unet = SimpleNamespace(config=SimpleNamespace(_name_or_path="snap/sd15"))

        def set_progress_bar_config(self, disable=True):
            return None

        def enable_attention_slicing(self):
            return None

        def enable_vae_slicing(self):
            return None

        def enable_model_cpu_offload(self):
            return None

        def to(self, device):
            return None

        def __call__(self, **kwargs):
            capturado["call_kwargs"] = kwargs
            return SimpleNamespace(images=[Image.new("RGB", (64, 64), (150, 150, 150))])

    class _FakeCN:
        @classmethod
        def from_pretrained(cls, *a, **kw):
            return "cn"

    class _FakeCNImg2Img:
        @classmethod
        def from_pretrained(cls, *a, **kw):
            capturado["loaded_cls"] = "StableDiffusionControlNetImg2ImgPipeline"
            return _FakePipe()

    fake_torch = SimpleNamespace(
        float16="float16",
        float32="float32",
        cuda=SimpleNamespace(is_available=lambda: False),
        manual_seed=lambda s: None,
        Generator=lambda device=None: SimpleNamespace(manual_seed=lambda s: "gen"),
    )
    fake_diffusers = SimpleNamespace(
        StableDiffusionPipeline=_FakeCNImg2Img,
        ControlNetModel=_FakeCN,
        StableDiffusionControlNetImg2ImgPipeline=_FakeCNImg2Img,
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "concept_infer.py",
            "--prompt",
            "knight",
            "--saida",
            str(saida),
            "--resultado",
            str(res_json),
            "--largura",
            "64",
            "--altura",
            "64",
            "--controlnet",
            "lllyasviel/control_v11p_sd15_openpose",
            "--pose-imagem",
            str(pose_img),
            "--init-imagem",
            str(init_img),
            "--strength",
            "0.45",
            "--device",
            "cpu",
        ],
    )
    assert mod.main() == 0
    dados = json.loads(res_json.read_text(encoding="utf-8"))
    assert dados["ok"] is True
    assert dados["modo"] == "controlnet_img2img"
    assert dados["strength"] == 0.45
    assert capturado["loaded_cls"] == "StableDiffusionControlNetImg2ImgPipeline"
    assert capturado["call_kwargs"]["strength"] == 0.45
    assert isinstance(capturado["call_kwargs"]["image"], Image.Image)
    assert isinstance(capturado["call_kwargs"]["control_image"], Image.Image)


# ------------------------------------------------------------------ mesh.py wiring


def test_mesh_py_nao_importa_deps_pesadas_no_nucleo():
    arvore = ast.parse(MESH_PY_PATH.read_text(encoding="utf-8"))
    proibidos = {"numpy", "cv2", "torch", "rembg"}
    encontrados: set[str] = set()
    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            for alias in node.names:
                encontrados.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            encontrados.add(node.module.split(".")[0])
    assert not (encontrados & proibidos), f"imports proibidos em mesh.py: {encontrados & proibidos}"


def test_mesh_extrude_2d_emite_bruto_extrude_sem_triposr(monkeypatch, tmp_path):
    prov = mesh.MeshProvider()
    monkeypatch.setattr(prov, "preflight_item", lambda item: (True, "ok"))

    arma_png = tmp_path / "espada.png"
    Image.new("RGBA", (64, 64), (180, 190, 200, 255)).save(arma_png)
    destino = tmp_path / "bruto_arma"
    comandos: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        comandos.append(cmd)
        script_nome = Path(cmd[1]).name
        if script_nome == "pose_guard.py":
            out_png = Path(cmd[cmd.index("--saida-png") + 1])
            out_res = Path(cmd[cmd.index("--resultado") + 1])
            Image.new("RGBA", (32, 64), (200, 200, 210, 255)).save(out_png)
            out_res.write_text(json.dumps({"ok": True}), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if script_nome == "delight.py":
            Image.new("RGBA", (32, 64), (190, 190, 200, 255)).save(
                Path(cmd[cmd.index("--saida-albedo") + 1])
            )
            Image.new("L", (32, 64), 230).save(Path(cmd[cmd.index("--saida-metallic") + 1]))
            Image.new("L", (32, 64), 80).save(Path(cmd[cmd.index("--saida-roughness") + 1]))
            Path(cmd[cmd.index("--resultado") + 1]).write_text(
                json.dumps({"ok": True}), encoding="utf-8"
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"TripoSR nao deveria rodar em extrudir_2d: {cmd}")

    monkeypatch.setattr(mesh.subprocess, "run", fake_run)
    raw = prov.gerar(
        {
            "id": "arma.espada.01",
            "tipo": "prop_equipavel",
            "parte": "arma",
            "extrudir_2d": True,
            "origem": str(arma_png),
        },
        {"perfil": "godot4"},
        destino,
    )
    assert raw.schema == "forge3d/bruto-extrude@1"
    modelo = json.loads((destino / "modelo.json").read_text(encoding="utf-8"))
    assert modelo["schema"] == "forge3d/bruto-extrude@1"
    assert modelo["modo"] == "arma"
    assert modelo["imagem"] == "input_cutout.png"
    assert modelo["metallic_hint"] == "metallic_hint.png"
    assert modelo["roughness_hint"] == "roughness_hint.png"
    assert not any("i23d_infer.py" in str(c) for c in comandos)


def test_mesh_humanoide_hero_ativa_pose_guard_delight_e_proteger_decimate(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    (
        tmp_path
        / "hf"
        / "hub"
        / ("models--" + concept.CONTROLNET_MODELO_PADRAO.replace("/", "--"))
    ).mkdir(parents=True)

    prov = mesh.MeshProvider()
    monkeypatch.setattr(prov, "preflight_item", lambda item: (True, "ok"))

    origem_png = _desenhar_silhueta_arms_down(tmp_path / "hero_arms_down.png")
    destino = tmp_path / "bruto_hero"
    capturado: dict = {"i23d_img": None, "repose_chamado": False}

    def fake_run(cmd, **_kwargs):
        script_nome = Path(cmd[1]).name
        if script_nome == "pose_guard.py":
            out_res = Path(cmd[cmd.index("--resultado") + 1])
            out_res.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "pose": "arms_down",
                        "razao_flanco": 0.05,
                        "largura_ombros": 0.31,
                        "precisa_repose": True,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if script_nome == "concept_infer.py":
            capturado["repose_chamado"] = True
            assert "--init-imagem" in cmd
            assert "--controlnet" in cmd
            assert "--pose-imagem" in cmd
            saida = Path(cmd[cmd.index("--saida") + 1])
            _desenhar_silhueta_tpose(saida)
            Path(cmd[cmd.index("--resultado") + 1]).write_text(
                json.dumps({"ok": True, "modo": "controlnet_img2img"}), encoding="utf-8"
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if script_nome == "i23d_infer.py":
            capturado["i23d_img"] = cmd[cmd.index("--imagem") + 1]
            out_dir = Path(cmd[cmd.index("--saida-dir") + 1])
            (out_dir / "modelo.glb").write_bytes(b"glTF")
            Image.new("RGB", (64, 64), (160, 140, 120)).save(out_dir / "input.png")
            Path(cmd[cmd.index("--resultado") + 1]).write_text(
                json.dumps(
                    {
                        "ok": True,
                        "torch": "2.4.1",
                        "faces": 15000,
                        "rembg_modelo": "u2net",
                        "rembg_fallback": True,
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if script_nome == "delight.py":
            Image.new("RGBA", (64, 64), (150, 130, 115, 255)).save(
                Path(cmd[cmd.index("--saida-albedo") + 1])
            )
            Image.new("L", (64, 64), 0).save(Path(cmd[cmd.index("--saida-metallic") + 1]))
            Image.new("L", (64, 64), 200).save(Path(cmd[cmd.index("--saida-roughness") + 1]))
            Path(cmd[cmd.index("--resultado") + 1]).write_text(
                json.dumps({"ok": True}), encoding="utf-8"
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"comando inesperado: {cmd}")

    monkeypatch.setattr(mesh.subprocess, "run", fake_run)
    raw = prov.gerar(
        {
            "id": "hero.sentinel.01",
            "tipo": "personagem_humanoide",
            "qualidade": "hero",
            "pose_guard": "repose",
            "origem": str(origem_png),
        },
        {"perfil": "godot4"},
        destino,
    )
    assert raw.schema == "forge3d/bruto-arquivo@1"
    assert capturado["repose_chamado"] is True
    assert capturado["i23d_img"] == str(destino / "origem_repose.png")

    modelo = json.loads((destino / "modelo.json").read_text(encoding="utf-8"))
    assert modelo["proteger_decimate"] is True
    assert modelo["origem_textura"] == "input_delit.png"
    assert modelo["metallic_hint"] == "metallic_hint.png"
    assert modelo["roughness_hint"] == "roughness_hint.png"

    res_i23d = json.loads((destino / "i23d_resultado.json").read_text(encoding="utf-8"))
    assert res_i23d["pose_guard"]["pose"] == "arms_down"
    assert res_i23d["pose_guard"]["repose_aplicado"] is True
    assert res_i23d["rembg_modelo"] == "u2net"
    assert res_i23d["rembg_fallback"] is True

    # Verifica versao preserva tokens esperados
    vers = prov.versao
    assert "+rm" in vers and "+pg" in vers and "+dl" in vers and "+q" in vers
    assert "rembgauto2" in vers and "@" in vers and "+cut2" in vers

    # Modo 'auto' detecta arms_down sem sobrescrever arte original nitida
    capturado["repose_chamado"] = False
    capturado["i23d_img"] = None
    destino_auto = tmp_path / "bruto_hero_auto"
    prov.gerar(
        {
            "id": "hero.sentinel.02",
            "tipo": "personagem_humanoide",
            "qualidade": "hero",
            "pose_guard": "auto",
            "origem": str(origem_png),
        },
        {"perfil": "godot4"},
        destino_auto,
    )
    assert capturado["repose_chamado"] is False
    assert capturado["i23d_img"] == str(origem_png)
    res_auto = json.loads((destino_auto / "i23d_resultado.json").read_text(encoding="utf-8"))
    assert res_auto["pose_guard"]["pose"] == "arms_down"
    assert res_auto["pose_guard"]["precisa_repose"] is True
    assert res_auto["pose_guard"]["repose_aplicado"] is False


# ------------------------------------------------------------------ bench_i23d


def test_bench_i23d_help_e_metricas_puras(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(BENCH_PATH), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "--modo" in proc.stdout

    bench = _carregar_modulo("bench_i23d_test", BENCH_PATH)

    # Nitidez Laplaciana: tabuleiro nitido >> borrado > uniforme
    nitida = Image.new("L", (64, 64), 40)
    for y in range(64):
        for x in range(64):
            if (x // 4 + y // 4) % 2 == 0:
                nitida.putpixel((x, y), 220)
    borrada = nitida.filter(ImageFilter.GaussianBlur(radius=3))
    uniforme = Image.new("L", (64, 64), 128)

    s_nitida = bench.laplacian_sharpness(nitida)
    s_borrada = bench.laplacian_sharpness(borrada)
    s_uniforme = bench.laplacian_sharpness(uniforme)
    assert s_uniforme == 0.0
    assert s_nitida > s_borrada * 4.0 > 0.0

    # Silhueta 4 vistas e extracao de baseColor em GLB sintetico
    glb = _criar_glb_cubo_com_textura(tmp_path / "cubo.glb", nitida.convert("RGBA"))
    sil = bench.silhouette_4view(glb, resolucao=64)
    assert set(sil["vistas"]) == {"frente", "lado", "topo", "tres_quartos"}
    assert 0.5 < sil["media"] <= 1.0
    for cov in sil["vistas"].values():
        assert 0.4 < cov <= 1.0

    med = bench.medir_glb(glb, resolucao=64)
    assert med["triangulos"] == 12
    assert med["g1_nao_manifold"] == 0
    assert med["basecolor_laplacian_var"] == pytest.approx(s_nitida, rel=0.01)


def test_bench_i23d_triposg_probe_json():
    proc = subprocess.run(
        [sys.executable, str(BENCH_PATH), "--modo", "triposg_probe", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    dados = json.loads(proc.stdout)
    assert dados["ok"] is True
    assert dados["modo"] == "triposg_probe"
    assert "viavel_local" in dados


def test_mesh_template_humanoide_usa_mpfb2_sem_triposr(monkeypatch, tmp_path):
    prov = mesh.MeshProvider()
    monkeypatch.setattr(prov, "preflight_item", lambda item: (True, "ok"))

    foto_png = tmp_path / "hero.png"
    Image.new("RGBA", (64, 128), (200, 150, 120, 255)).save(foto_png)
    destino = tmp_path / "bruto_tmpl"
    chamadas: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        chamadas.append(cmd)
        if any("template_prep.py" in str(c) for c in cmd):
            out_dir = Path(cmd[cmd.index("--saida-dir") + 1])
            res_json = Path(cmd[cmd.index("--resultado") + 1])
            tex = out_dir / "input_template.png"
            Image.new("RGBA", (64, 128), (195, 145, 118, 255)).save(tex)
            res_json.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "foto_template": str(tex),
                        "marcos": {"olhos_frac": 0.93, "boca_frac": 0.89},
                        "delight": {"executado": True},
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if any("template_body.py" in str(c) for c in cmd):
            job = json.loads(Path(cmd[-1]).read_text(encoding="utf-8"))
            out_dir = Path(job["saida"])
            (out_dir / "template_body.glb").write_bytes(b"glTF")
            Image.new("RGBA", (64, 64), (195, 145, 118, 255)).save(out_dir / "baseColor.png")
            (out_dir / "relatorio.json").write_text(
                json.dumps({"triangulos": 27036, "template": "mpfb2 (CC0)"}), encoding="utf-8"
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"TripoSR nao deveria rodar em template_humanoide: {cmd}")

    monkeypatch.setattr(mesh.subprocess, "run", fake_run)
    raw = prov.gerar(
        {
            "id": "hero.tmpl.01",
            "tipo": "personagem_humanoide",
            "parte": "corpo",
            "template_humanoide": True,
            "origem": str(foto_png),
        },
        {"perfil": "godot4", "material": {"textura_max": 1024}},
        destino,
    )
    assert raw.schema == "forge3d/bruto-arquivo@1"
    modelo = json.loads((destino / "modelo.json").read_text(encoding="utf-8"))
    assert modelo["arquivo"] == "template_body.glb"
    assert modelo["proteger_decimate"] is True
    res = json.loads((destino / "i23d_resultado.json").read_text(encoding="utf-8"))
    assert res["modo"] == "mpfb2_template"
    assert raw.meta["modelo"] == "mpfb2"
    assert not any("i23d_infer.py" in str(c) for c in chamadas)

    from forge3d import providers

    lic_mpfb = providers.LICENCAS["mpfb2"]
    assert lic_mpfb["uso_comercial"] is True
    assert "CC0" in lic_mpfb["notice"]
