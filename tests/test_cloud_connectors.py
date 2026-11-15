"""Testes unitarios dos conectores IA em nuvem (Gemini, Higgsfield), doctor e fallbacks HD."""

from __future__ import annotations

import ast
import base64
import io
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from forge3d import doctor
from forge3d.errors import ForgeError
from forge3d.providers import LICENCAS, cloud_ai, concept, mesh

RAIZ = Path(__file__).resolve().parents[1]


def _png_bytes_rgba(cor: tuple[int, int, int, int] = (90, 140, 210, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (32, 32), cor).save(buf, format="PNG")
    return buf.getvalue()


def test_cloud_ai_usa_apenas_stdlib_d26():
    """Garante zero dependencias externas de pip em cloud_ai.py (D26)."""
    arvore = ast.parse((RAIZ / "src" / "forge3d" / "providers" / "cloud_ai.py").read_text("utf-8"))
    permitidos = {
        "__future__",
        "base64",
        "hashlib",
        "json",
        "os",
        "pathlib",
        "re",
        "time",
        "typing",
        "urllib",
    }
    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                assert mod in permitidos, f"import externo proibido em cloud_ai.py: {mod}"
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mod = node.module.split(".")[0]
            assert mod in permitidos, f"from-import externo proibido em cloud_ai.py: {mod}"


def test_licencas_comerciais_gemini_e_higgsfield_registradas():
    cloud_ai.registrar_licencas_cloud()
    assert "gemini" in LICENCAS
    assert LICENCAS["gemini"]["uso_comercial"] is True
    assert "higgsfield" in LICENCAS
    assert LICENCAS["higgsfield"]["uso_comercial"] is True


def test_gemini_connector_env_e_arquivo_key_mock_http(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    monkeypatch.setenv("FORGE3D_CONFIG", str(cfg_dir))
    monkeypatch.delenv("FORGE3D_GEMINI_API_KEY", raising=False)

    ok0, det0 = cloud_ai.gemini_disponivel()
    assert ok0 is False
    assert "FORGE3D_GEMINI_API_KEY" in det0

    segredo = "AIzaSy_SEGREDO_SUPER_CONFIDENCIAL_998877"
    (cfg_dir / "gemini.key").write_text(segredo + "\n", encoding="utf-8")
    ok1, det1 = cloud_ai.gemini_disponivel()
    assert ok1 is True
    assert "arquivo:gemini.key" in det1
    assert segredo not in det1

    png_raw = _png_bytes_rgba((200, 80, 40, 255))
    b64_png = base64.b64encode(png_raw).decode("ascii")
    capturado: dict = {}

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps({"predictions": [{"bytesBase64Encoded": b64_png}]}).encode("utf-8")

    def fake_urlopen(req, timeout=120):
        capturado["url"] = req.full_url
        capturado["headers"] = dict(req.header_items())
        capturado["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp()

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_urlopen)
    destino = tmp_path / "out_gemini" / "concept.png"
    meta = cloud_ai.gerar_conceito_gemini(
        "armored paladin",
        "blurry, text",
        42,
        destino,
        largura=512,
        altura=512,
    )
    assert destino.is_file()
    assert destino.read_bytes() == png_raw
    assert meta["ok"] is True
    assert meta["provider_conceito"] == "gemini"
    assert meta["licenca"]["uso_comercial"] is True
    assert segredo not in json.dumps(meta)


def test_higgsfield_connector_e_concept_provider_auto(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "config_hf"
    cfg_dir.mkdir()
    monkeypatch.setenv("FORGE3D_CONFIG", str(cfg_dir))
    monkeypatch.delenv("FORGE3D_GEMINI_API_KEY", raising=False)
    segredo_hf = "hf_secret_key_never_expose_123456789"
    monkeypatch.setenv("FORGE3D_HIGGSFIELD_API_KEY", segredo_hf)
    monkeypatch.setenv("FORGE3D_HIGGSFIELD_API_URL", "https://custom.higgsfield.example/v1/gen")

    ok, det = cloud_ai.higgsfield_disponivel()
    assert ok is True
    assert segredo_hf not in det
    assert concept.resolver_provider_conceito({"prompt": "dragon"}) == "higgsfield"

    png_raw = _png_bytes_rgba((40, 180, 110, 255))
    b64_png = base64.b64encode(png_raw).decode("ascii")
    chamadas: list[str] = []

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps({"data": [{"b64_json": b64_png}]}).encode("utf-8")

    def fake_urlopen(req, timeout=120):
        chamadas.append(req.full_url)
        return _FakeResp()

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_urlopen)
    prov = concept.ConceptProvider()
    pronto, razao = prov.preflight({"provider_conceito": "higgsfield"})
    assert pronto is True
    assert segredo_hf not in razao

    res = prov.gerar(
        {
            "id": "mob.dragon.01",
            "prompt": "emerald dragon",
            "seed": 77,
            "provider_conceito": "higgsfield",
        },
        tmp_path / "concept_hf",
    )
    assert res["png"].is_file()
    assert res["meta"]["provider_conceito"] == "higgsfield"
    assert res["meta"]["licenca"]["uso_comercial"] is True
    assert chamadas == ["https://custom.higgsfield.example/v1/gen"]
    assert segredo_hf not in json.dumps(res["meta"])


def test_doctor_conectores_ia_e_zero_vazamento_de_segredos(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "cfg_doc"
    cfg_dir.mkdir()
    monkeypatch.setenv("FORGE3D_CONFIG", str(cfg_dir))
    k_gem = "GEM_SUPER_SECRET_TOKEN_ABC123XYZ"
    k_hig = "HIG_SUPER_SECRET_TOKEN_DEF456UVW"
    k_rbx = "RBX_SUPER_SECRET_TOKEN_GHI789RST"
    monkeypatch.setenv("FORGE3D_GEMINI_API_KEY", k_gem)
    monkeypatch.setenv("FORGE3D_HIGGSFIELD_API_KEY", k_hig)
    monkeypatch.setenv("FORGE3D_ROBLOX_API_KEY", k_rbx)

    rel = doctor.checar()
    assert "conectores_ia" in rel
    con = rel["conectores_ia"]
    for esperado in ("sd15", "triposr", "mpfb_cc0", "gemini", "higgsfield", "roblox_open_cloud"):
        assert esperado in con
        assert isinstance(con[esperado]["ok"], bool)
        assert isinstance(con[esperado]["pronto"], bool)
        assert isinstance(con[esperado]["detalhe"], str)

    assert con["gemini"]["pronto"] is True
    assert con["higgsfield"]["pronto"] is True
    assert con["roblox_open_cloud"]["pronto"] is True

    serializado = json.dumps(rel)
    assert k_gem not in serializado
    assert k_hig not in serializado
    assert k_rbx not in serializado

    # Sanitizacao também em erros HTTP
    def fake_err(req, timeout=120):
        raise urllib.error.URLError(f"falha em ?key={k_gem} com Bearer {k_gem}")

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_err)
    with pytest.raises(ForgeError) as exc_info:
        cloud_ai.gerar_conceito_gemini("knight", "", 1, tmp_path / "x.png")
    assert k_gem not in str(exc_info.value)
    assert "REDACTED" in str(exc_info.value)


def test_i23d_oom_fallback_320_para_256_e_taubin_smooth():
    import importlib.util

    spec_i23d = importlib.util.spec_from_file_location(
        "i23d_infer_test_hd", RAIZ / "tools" / "i23d_infer.py"
    )
    assert spec_i23d and spec_i23d.loader
    mod = importlib.util.module_from_spec(spec_i23d)
    spec_i23d.loader.exec_module(mod)

    res_tentadas: list[int] = []

    class _FakeMesh:
        def __init__(self):
            self.vertices = [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
                [1.0, 1.0, 1.2],
            ]
            self.faces = [
                [0, 1, 2],
                [0, 1, 3],
                [0, 2, 3],
                [1, 2, 4],
                [1, 3, 4],
                [2, 3, 4],
            ]

    class _FakeModel:
        def extract_mesh(self, codigos, has_vertex_color, resolution=256):
            res_tentadas.append(int(resolution))
            if int(resolution) > 256:
                raise RuntimeError("CUDA out of memory")
            return [_FakeMesh()]

    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: True, empty_cache=lambda: None)
    )
    malha, res_final, oom_fb = mod._extrair_malha_com_fallback_oom(
        _FakeModel(), ["cod"], 320, torch_mod=fake_torch
    )
    assert res_tentadas == [320, 256]
    assert res_final == 256
    assert oom_fb is True

    v_antes = [list(v) for v in malha.vertices]
    info_taubin = mod._suavizar_malha_taubin(malha, iteracoes=3)
    assert info_taubin["aplicado"] is True
    assert [list(v) for v in malha.vertices] != v_antes


def test_mpfb2_auto_template_humanoide_e_delight_escamas_coloridas(monkeypatch, tmp_path):
    import importlib.util
    from PIL import ImageDraw

    zip_falso = tmp_path / "makehuman_system_assets_cc0.zip"
    zip_falso.write_bytes(b"PK\x03\x04")
    mpfb_dir = tmp_path / "mpfb"
    mpfb_dir.mkdir()
    (mpfb_dir / "__init__.py").write_text("# mpfb\n", encoding="utf-8")

    monkeypatch.setenv("FORGE3D_MPFB_ASSETS_ZIP", str(zip_falso))
    monkeypatch.setenv("FORGE3D_MPFB_DIR", str(mpfb_dir))
    monkeypatch.delenv("FORGE3D_HUMANOIDE_TEMPLATE", raising=False)

    ok_mpfb, _ = mesh.mpfb2_cc0_disponivel()
    assert ok_mpfb is True
    assert mesh._usar_template_humanoide({"tipo": "personagem_humanoide"}) is True
    assert (
        mesh._usar_template_humanoide(
            {"tipo": "personagem_humanoide", "template_humanoide": False}
        )
        is False
    )

    spec_dl = importlib.util.spec_from_file_location("delight_soft", RAIZ / "tools" / "delight.py")
    assert spec_dl and spec_dl.loader
    dl = importlib.util.module_from_spec(spec_dl)
    spec_dl.loader.exec_module(dl)

    # Escamas verdes/ambar nao metalicas nao devem ser esmagadas como metal (metallic == 0)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((8, 8, 56, 56), fill=(180, 145, 45, 255))  # ocre/ambar fosco (V=180, S=191 -> V<165 se 150)
    d.rectangle((12, 12, 52, 52), fill=(145, 118, 42, 255))
    m_map, r_map = dl.estimar_mapas_pbr(img)
    assert m_map.getpixel((32, 32)) == 0
    assert 120 <= r_map.getpixel((32, 32)) <= 215
