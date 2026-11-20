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
    """Garante zero dependencias externas de pip em cloud_*.py (D26)."""
    permitidos = {
        "__future__",
        "base64",
        "hashlib",
        "json",
        "math",
        "os",
        "pathlib",
        "re",
        "time",
        "typing",
        "urllib",
    }
    alvos = sorted((RAIZ / "src" / "forge3d" / "providers").glob("cloud_*.py"))
    assert alvos
    for arq in alvos:
        arvore = ast.parse(arq.read_text("utf-8"))
        for node in ast.walk(arvore):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    assert mod in permitidos, f"import externo proibido em {arq.name}: {mod}"
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mod = node.module.split(".")[0]
                assert mod in permitidos, f"from-import externo proibido em {arq.name}: {mod}"


def test_licencas_comerciais_gemini_e_higgsfield_registradas():
    cloud_ai.registrar_licencas_cloud()
    assert "gemini" in LICENCAS
    assert LICENCAS["gemini"]["uso_comercial"] is True
    assert "gemini_embedding" in LICENCAS
    assert LICENCAS["gemini_embedding"]["uso_comercial"] is True
    assert "gemini_kitbash" in LICENCAS
    assert LICENCAS["gemini_kitbash"]["uso_comercial"] is True
    assert cloud_ai._LICENCAS_CLOUD["gemini_embedding"]["uso_comercial"] is True
    assert cloud_ai._LICENCAS_CLOUD["gemini_kitbash"]["uso_comercial"] is True
    assert "higgsfield" in LICENCAS
    assert LICENCAS["higgsfield"]["uso_comercial"] is True
    assert "trellis" in LICENCAS
    assert LICENCAS["trellis"]["uso_comercial"] is True
    assert "Microsoft TRELLIS" in LICENCAS["trellis"]["modelo"]


def test_gemini_connector_env_e_arquivo_key_mock_http(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    monkeypatch.setenv("FORGE3D_CONFIG", str(cfg_dir))
    monkeypatch.delenv("FORGE3D_GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("FORGE3D_GEMINI_MODELO", raising=False)

    ok0, det0 = cloud_ai.gemini_disponivel()
    assert ok0 is False
    assert "FORGE3D_GEMINI_API_KEY" in det0

    segredo = "AIzaSy_SEGREDO_SUPER_CONFIDENCIAL_998877"
    (cfg_dir / "gemini.key").write_text(segredo + "\n", encoding="utf-8")
    ok1, det1 = cloud_ai.gemini_disponivel()
    assert ok1 is True
    assert "arquivo:gemini.key" in det1
    assert "gemini-nano-banana-2.1" in det1
    assert segredo not in det1

    png_raw = _png_bytes_rgba((200, 80, 40, 255))
    b64_png = base64.b64encode(png_raw).decode("ascii")
    capturado: dict = {}

    class _FakeResp:
        def __init__(self, payload: dict):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    resposta_interactions = {
        "steps": [
            {
                "type": "model_output",
                "content": [{"type": "image", "data": b64_png}],
            }
        ]
    }

    def fake_urlopen(req, timeout=120):
        capturado["url"] = req.full_url
        capturado["headers"] = {k.lower(): v for k, v in req.header_items()}
        capturado["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(resposta_interactions)

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
    assert capturado["url"] == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert capturado["headers"]["api-revision"] == "2026-05-20"
    assert capturado["headers"]["x-goog-api-key"] == segredo
    assert capturado["body"] == {
        "model": "gemini-nano-banana-2.1",
        "input": [{"type": "text", "text": "armored paladin. Avoid: blurry, text"}],
    }
    assert meta["ok"] is True
    assert meta["provider_conceito"] == "gemini"
    assert meta["modelo"] == "gemini/gemini-nano-banana-2.1"
    assert meta["licenca"]["uso_comercial"] is True
    assert segredo not in json.dumps(meta)


def test_gemini_concept_com_referencia_estilo_payload_e_proveniencia(monkeypatch, tmp_path):
    """D113: referencia_estilo vira parte de imagem no payload e hash no resultado."""
    import hashlib as _hl

    segredo = "AIza_TEST_KEY_REF_ESTILO_42"
    monkeypatch.setenv("FORGE3D_GEMINI_API_KEY", segredo)
    monkeypatch.delenv("FORGE3D_GEMINI_MODELO", raising=False)

    png_ref = tmp_path / "style_sheet.png"
    png_ref.write_bytes(_png_bytes_rgba((10, 20, 30, 255)))
    png_saida = _png_bytes_rgba((200, 60, 40, 255))
    b64_saida = base64.b64encode(png_saida).decode("ascii")
    capturado: dict = {}

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"steps": [{"type": "model_output", "content": [{"type": "image", "data": b64_saida}]}]}
            ).encode("utf-8")

    def fake_urlopen(req, timeout=120):
        capturado["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp()

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_urlopen)
    destino = tmp_path / "out_ref" / "concept.png"
    meta = cloud_ai.gerar_conceito_gemini(
        "sword in the style sheet",
        "",
        7,
        destino,
        referencia_png=png_ref,
    )
    entrada = capturado["body"]["input"]
    assert entrada[0] == {"type": "text", "text": "sword in the style sheet"}
    assert entrada[1]["type"] == "image"
    assert entrada[1]["mime_type"] == "image/png"
    assert entrada[1]["data"] == base64.b64encode(png_ref.read_bytes()).decode("ascii")
    assert meta["referencia_estilo"] == str(png_ref)
    assert meta["referencia_estilo_sha256"] == _hl.sha256(png_ref.read_bytes()).hexdigest()
    assert segredo not in json.dumps(meta)


def test_gemini_referencia_estilo_inexistente_falha(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE3D_GEMINI_API_KEY", "AIza_TEST_KEY_REF_AUSENTE")
    with pytest.raises(ForgeError):
        cloud_ai.gerar_conceito_gemini(
            "x", "", 1, tmp_path / "c.png", referencia_png=tmp_path / "nao_existe.png"
        )


def test_gemini_modelos_novos_e_legado_imagen_predict(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE3D_GEMINI_API_KEY", "AIza_TEST_KEY_778899")
    png_raw = _png_bytes_rgba((50, 120, 210, 255))
    b64_png = base64.b64encode(png_raw).decode("ascii")
    chamadas: list[dict] = []

    class _FakeResp:
        def __init__(self, payload: dict):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    def fake_urlopen(req, timeout=120):
        body = json.loads(req.data.decode("utf-8"))
        chamadas.append({"url": req.full_url, "body": body})
        if req.full_url.endswith(":predict"):
            return _FakeResp({"predictions": [{"bytesBase64Encoded": b64_png}]})
        if body.get("model") == "gemini-3-pro-image":
            return _FakeResp(
                {"steps": [{"type": "model_output", "content": [{"type": "image", "inline_data": {"data": b64_png}}]}]}
            )
        return _FakeResp(
            {"candidates": [{"content": {"parts": [{"inlineData": {"data": b64_png}}]}}]}
        )

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_urlopen)

    monkeypatch.setenv("FORGE3D_GEMINI_MODELO", "gemini-3-pro-image")
    m1 = cloud_ai.gerar_conceito_gemini("golem", "", 10, tmp_path / "g1.png")
    assert m1["modelo"] == "gemini/gemini-3-pro-image"
    assert chamadas[-1]["url"].endswith("/v1beta/interactions")

    monkeypatch.setenv("FORGE3D_GEMINI_MODELO", "gemini-3.1-flash-lite-image")
    m2 = cloud_ai.gerar_conceito_gemini("knight", "", 11, tmp_path / "g2.png")
    assert m2["modelo"] == "gemini/gemini-3.1-flash-lite-image"
    assert chamadas[-1]["url"].endswith("/v1beta/interactions")

    monkeypatch.setenv("FORGE3D_GEMINI_MODELO", "imagen-3.0-generate-002")
    m3 = cloud_ai.gerar_conceito_gemini("wizard", "", 12, tmp_path / "g3.png")
    assert m3["modelo"] == "gemini/imagen-3.0-generate-002"
    assert chamadas[-1]["url"].endswith("/imagen-3.0-generate-002:predict")


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
    monkeypatch.delenv("FORGE3D_GEMINI_MODELO", raising=False)
    k_gem = "GEM_SUPER_SECRET_TOKEN_ABC123XYZ"
    k_hig = "HIG_SUPER_SECRET_TOKEN_DEF456UVW"
    k_rbx = "RBX_SUPER_SECRET_TOKEN_GHI789RST"
    monkeypatch.setenv("FORGE3D_GEMINI_API_KEY", k_gem)
    monkeypatch.setenv("FORGE3D_HIGGSFIELD_API_KEY", k_hig)
    monkeypatch.setenv("FORGE3D_ROBLOX_API_KEY", k_rbx)

    rel = doctor.checar()
    assert "conectores_ia" in rel
    con = rel["conectores_ia"]
    for esperado in ("sd15", "triposr", "mpfb_cc0", "gemini", "higgsfield", "trellis", "roblox_open_cloud"):
        assert esperado in con
        assert isinstance(con[esperado]["ok"], bool)
        assert isinstance(con[esperado]["pronto"], bool)
        assert isinstance(con[esperado]["detalhe"], str)

    assert con["gemini"]["pronto"] is True
    assert "gemini-nano-banana-2.1" in con["gemini"]["detalhe"]
    assert con["higgsfield"]["pronto"] is True
    assert con["trellis"]["pronto"] is True
    assert con["roblox_open_cloud"]["pronto"] is True

    serializado = json.dumps(rel)
    assert k_gem not in serializado
    assert k_hig not in serializado
    assert k_rbx not in serializado
    serial_low = serializado.lower()
    for proibido in ("fal" + ".run", "fal" + ".ai", "fal" + ".key", "forge3d_" + "fal_api_key"):
        assert proibido not in serial_low

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


def test_avaliar_qualidade_visual_gemini_mock(monkeypatch, tmp_path):
    segredo = "AIza_QA_SECRET_11223344"
    monkeypatch.setenv("FORGE3D_GEMINI_API_KEY", segredo)
    png_path = tmp_path / "turntable.png"
    png_path.write_bytes(_png_bytes_rgba((180, 150, 120, 255)))
    capturado: dict = {}

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            qa_json = json.dumps(
                {"aprovado": False, "nota": 4.2, "defeitos": ["black forehead band"]}
            )
            return json.dumps(
                {
                    "steps": [
                        {
                            "type": "model_output",
                            "content": [{"type": "text", "text": f"```json\n{qa_json}\n```"}],
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(req, timeout=120):
        capturado["url"] = req.full_url
        capturado["headers"] = {k.lower(): v for k, v in req.header_items()}
        capturado["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp()

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_urlopen)
    res = cloud_ai.avaliar_qualidade_visual_gemini(png_path, contexto="hero paladin")
    assert res["ok"] is True
    assert res["aprovado"] is False
    assert res["nota"] == 4.2
    assert res["defeitos"] == ["black forehead band"]
    assert res["modelo"] == "gemini-4-hydrogen"
    assert capturado["url"] == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert capturado["headers"]["api-revision"] == "2026-05-20"
    assert capturado["body"]["model"] == "gemini-4-hydrogen"
    assert capturado["body"]["input"][1]["type"] == "image"

    def fake_err(req, timeout=120):
        raise urllib.error.URLError(f"erro ?key={segredo}")

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_err)
    with pytest.raises(ForgeError) as exc_info:
        cloud_ai.avaliar_qualidade_visual_gemini(png_path)
    assert segredo not in str(exc_info.value)
    assert "REDACTED" in str(exc_info.value)


def test_trellis_connector_mock(monkeypatch, tmp_path):
    ok1, det1 = cloud_ai.trellis_disponivel()
    assert ok1 is True
    assert "colab_trellis_worker" in det1
    assert "TRELLIS.2-4B" in det1
    for proibido in ("fal" + ".run", "fal" + ".ai", "fal" + ".key", "forge3d_" + "fal_api_key"):
        assert proibido not in det1.lower()

    assert not hasattr(cloud_ai, "gerar_malha_trellis")
    assert not hasattr(cloud_ai, "URL_TRELLIS_PADRAO")
    assert not hasattr(cloud_ai, "_ler_chave_fal")

    vazio_root = tmp_path / "sem_worker"
    (vazio_root / "schemas").mkdir(parents=True)
    monkeypatch.setenv("FORGE3D_ROOT", str(vazio_root))
    ok0, det0 = cloud_ai.trellis_disponivel()
    assert ok0 is False
    assert "colab_trellis_worker.py" in det0


def test_ler_arquivo_chave_falha_explicita_em_oserror_e_gemini_disponivel_reporta(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "cfg_perm"
    cfg_dir.mkdir()
    monkeypatch.setenv("FORGE3D_CONFIG", str(cfg_dir))
    monkeypatch.delenv("FORGE3D_GEMINI_API_KEY", raising=False)
    chave_path = cfg_dir / "gemini.key"
    chave_path.write_text("segredo\n", encoding="utf-8")

    def _boom_read_text(self, *args, **kwargs):
        raise PermissionError("sem permissao de leitura")

    monkeypatch.setattr(Path, "read_text", _boom_read_text)
    with pytest.raises(PermissionError):
        cloud_ai._ler_arquivo_chave("gemini.key")
    ok, det = cloud_ai.gemini_disponivel()
    assert ok is False
    assert "erro ao ler chave Gemini" in det


def test_concept_4_vistas_sem_referencia_usa_front_como_ancora_com_sha_nulo(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE3D_GEMINI_API_KEY", "gem_4v_noref_secret")
    monkeypatch.delenv("FORGE3D_GEMINI_MODELO", raising=False)
    chamadas: list[dict] = []
    b64_out = base64.b64encode(_png_bytes_rgba((180, 120, 90, 255))).decode("ascii")

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"steps": [{"type": "model_output", "content": [{"type": "image", "data": b64_out}]}]}
            ).encode("utf-8")

    def fake_urlopen(req, timeout=120):
        chamadas.append(json.loads(req.data.decode("utf-8")))
        return _FakeResp()

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_urlopen)
    out_dir = tmp_path / "c4v_noref"
    res = concept.ConceptProvider().gerar(
        {
            "id": "prop.shield.01",
            "tipo": "prop_equipavel",
            "prompt": "ornate dwarven shield",
            "provider_conceito": "gemini",
            "vistas": 4,
            "seed": 50,
        },
        out_dir,
    )
    assert len(chamadas) == 4
    assert not any(p.get("type") == "image" for p in chamadas[0]["input"])
    assert all(any(p.get("type") == "image" for p in c["input"]) for c in chamadas[1:])
    assert res["meta"]["referencia_estilo"] is None
    assert res["meta"]["referencia_estilo_sha256"] is None
    assert (out_dir / "concept.json").is_file()
    cjson = json.loads((out_dir / "concept.json").read_text(encoding="utf-8"))
    assert cjson["prompt_final"]
    assert set(cjson["vistas"]) == {"front", "back", "left", "right"}
    for p_str in cjson["vistas"].values():
        assert Path(p_str).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_spec_v6_subrotas_vistas_plan_budget_e_post_forward(tmp_path):
    from forge3d import plan_budget, post, profiles, spec

    ref_png = tmp_path / "ref.png"
    ref_png.write_bytes(_png_bytes_rgba((10, 20, 30, 255)))
    doc = {
        "schema": "forge3d/spec@6",
        "projeto": "m4_subrotas",
        "perfil": "godot4",
        "destino_exportacao": "~/.local/state/forge3d/saida/m4_sub",
        "lote": [
            {
                "id": "sub.i23d.01",
                "tipo": "prop_equipavel",
                "parte": "elmo",
                "rota": "i23d",
                "origem": str(ref_png),
                "prompt": "winged paladin helm",
                "seed": 11,
                "altura_metros": 0.35,
                "pivot": "base",
            },
            {
                "id": "sub.tmpl.01",
                "tipo": "personagem_humanoide",
                "rota": "template",
                "prompt": "paladin knight",
                "seed": 12,
                "altura_metros": 1.8,
                "pivot": "base",
                "vistas": 4,
                "referencia_estilo": str(ref_png),
            },
            {
                "id": "sub.proc.01",
                "tipo": "criatura_quadrupede",
                "rota": "procedural",
                "prompt": "stone hound",
                "seed": 13,
                "altura_metros": 1.2,
                "pivot": "base",
            },
            {
                "id": "sub.ext2d.01",
                "tipo": "prop_equipavel",
                "parte": "arma",
                "rota": "extrude_2d",
                "origem": str(ref_png),
                "prompt": "runed sword",
                "seed": 14,
                "altura_metros": 1.0,
                "pivot": "empunhadura",
            },
        ],
    }
    prep, perfil, _avisos = spec.preparar(doc)
    assert [it["rota"] for it in prep["lote"]] == ["i23d", "template", "procedural", "extrude_2d"]
    res_tmpl = spec.resolver_item(prep["lote"][1])
    assert res_tmpl["vistas"] == 4
    res_i23d = spec.resolver_item(prep["lote"][0])
    assert "origem_hash" in res_i23d

    orc = plan_budget.estimar_orcamento_cena(prep, perfil)
    fontes = {it["id"]: it["fonte"] for it in orc["estimativa"]["itens"]}
    assert fontes["sub.i23d.01"] == "i23d_heuristica"
    assert fontes["sub.tmpl.01"] == "template_humanoide"
    assert fontes["sub.proc.01"].startswith("procedural_")
    assert fontes["sub.ext2d.01"] == "extrude_2d"

    job_prep = post._preparar_job(
        {
            "saida_dir": str(tmp_path),
            "item": {"id": "sub.tmpl.01", "vistas": 4, "vistas_ortograficas": {"front": "a.png"}},
        }
    )
    assert job_prep["vistas"] == 4
    assert job_prep["vistas_ortograficas"] == {"front": "a.png"}
    assert post.PIPELINE_VERSION == "0.9.8"
    assert profiles.carregar("godot4")["perfil"] == "godot4"


def _desenhar_turntable_sintetico(
    caminho: Path,
    *,
    cor_testa: tuple[int, int, int, int] = (220, 175, 145, 255),
    cor_bochecha: tuple[int, int, int, int] = (220, 175, 145, 255),
    cor_perna_esq: tuple[int, int, int, int] = (60, 95, 165, 255),
    cor_perna_dir: tuple[int, int, int, int] = (60, 95, 165, 255),
) -> Path:
    from PIL import ImageDraw

    qw, qh = 160, 200
    bg = (110, 114, 120, 255)
    sheet = Image.new("RGBA", (qw * 2, qh * 2), bg)
    draw = ImageDraw.Draw(sheet)

    def _desenhar_humanoide(ox: int, oy: int, frontal_ou_costas: bool) -> None:
        # Cabeca (y: 20..52, cx: 80 -> w_box ~ 44..116)
        draw.rectangle((ox + 68, oy + 20, ox + 92, oy + 35), fill=cor_testa)
        draw.rectangle((ox + 66, oy + 36, ox + 94, oy + 52), fill=cor_bochecha)
        # Torso + bracos (y: 53..115)
        draw.rectangle((ox + 54, oy + 53, ox + 106, oy + 115), fill=(95, 115, 140, 255))
        # Pernas (y: 116..180)
        if frontal_ou_costas:
            draw.rectangle((ox + 60, oy + 116, ox + 75, oy + 180), fill=cor_perna_esq)
            draw.rectangle((ox + 85, oy + 116, ox + 100, oy + 180), fill=cor_perna_dir)
        else:
            draw.rectangle((ox + 70, oy + 116, ox + 90, oy + 180), fill=cor_perna_esq)

    _desenhar_humanoide(0, 0, True)         # TL: front
    _desenhar_humanoide(qw, 0, False)       # TR: right
    _desenhar_humanoide(0, qh, True)        # BL: back
    _desenhar_humanoide(qw, qh, False)      # BR: 3/4
    sheet.save(caminho, format="PNG")
    return caminho


def test_visual_qa_critic_aprova_limpo_e_reprova_defeitos(tmp_path):
    import importlib.util

    spec_vqa = importlib.util.spec_from_file_location(
        "visual_qa_critic_mod", RAIZ / "tools" / "visual_qa_critic.py"
    )
    assert spec_vqa and spec_vqa.loader
    vqa = importlib.util.module_from_spec(spec_vqa)
    spec_vqa.loader.exec_module(vqa)

    limpo_png = _desenhar_turntable_sintetico(tmp_path / "limpo.png")
    res_ok = vqa.avaliar_turntable_png(limpo_png)
    assert res_ok["aprovado"] is True
    assert res_ok["layout"] == "turntable"
    assert res_ok["defeitos"] == []
    assert vqa.main([str(limpo_png), "--json"]) == 0

    testa_preta_png = _desenhar_turntable_sintetico(
        tmp_path / "testa_preta.png",
        cor_testa=(8, 8, 10, 255),
    )
    res_testa = vqa.avaliar_turntable_png(testa_preta_png)
    assert res_testa["aprovado"] is False
    assert any("forehead_smear" in d for d in res_testa["defeitos"])
    assert vqa.main([str(testa_preta_png)]) == 1

    perna_assim_png = _desenhar_turntable_sintetico(
        tmp_path / "perna_assim.png",
        cor_perna_esq=(210, 35, 35, 255),
        cor_perna_dir=(30, 55, 190, 255),
    )
    res_perna = vqa.avaliar_turntable_png(perna_assim_png)
    assert res_perna["aprovado"] is False
    assert any("leg_asymmetry" in d for d in res_perna["defeitos"])
    assert vqa.main([str(perna_assim_png)]) == 1

    # Regressao V1 + V2: detecta intrusao escura nas botas e perda de textura na faixa inferior da tunica
    v1_v2_png = tmp_path / "defeitos_v1_v2.png"
    with Image.open(limpo_png) as base_sh:
        sh_v12 = base_sh.copy()
    px_sh = sh_v12.load()
    assert px_sh is not None
    # No quadrante frontal (0..160, 0..200), bbox y=20..180 (fh=161):
    # - Texturiza tunica superior (y=55..73) com padrao espinha de peixe e mantem tunica inferior (y=78..96) lisa
    for y_t in range(53, 110):
        for x_t in range(54, 106):
            if y_t < 75:
                delta_t = 14 if ((x_t + y_t) % 2 == 0) else -14
                px_sh[x_t, y_t] = (45 + delta_t, 70 + delta_t, 105 + delta_t, 255)
            else:
                px_sh[x_t, y_t] = (45, 70, 105, 255)
    # - Calca escura (y=114..134) + botas de couro quente (y=140..172) com espinho escuro (V1)
    for y_l in range(114, 136):
        for x_l in list(range(60, 76)) + list(range(85, 101)):
            px_sh[x_l, y_l] = (32, 30, 30, 255)
    for y_b in range(140, 173):
        for x_b in list(range(60, 76)) + list(range(85, 101)):
            px_sh[x_b, y_b] = (112, 64, 38, 255)
    for y_sp in range(142, 152):
        for x_sp in (66, 67, 68, 91, 92, 93):
            px_sh[x_sp, y_sp] = (28, 26, 26, 255)
    sh_v12.save(v1_v2_png, format="PNG")
    res_v12 = vqa.avaliar_turntable_png(v1_v2_png)
    assert res_v12["aprovado"] is False
    assert any("boot_interpenetration" in d for d in res_v12["defeitos"]), res_v12
    assert any("tunic_texture_step" in d for d in res_v12["defeitos"]), res_v12


def test_colab_trellis_worker_gera_spec_v5_valido(tmp_path):
    import importlib.util
    import yaml
    from forge3d import spec

    spec_tw = importlib.util.spec_from_file_location(
        "colab_trellis_worker_mod", RAIZ / "tools" / "colab_trellis_worker.py"
    )
    assert spec_tw and spec_tw.loader
    tw = importlib.util.module_from_spec(spec_tw)
    spec_tw.loader.exec_module(tw)

    glb = tmp_path / "paladin.glb"
    glb.write_bytes(b"glTF\x02\x00\x00\x00TEST")
    digest = tw.sha256_arquivo(glb)
    yaml_str = tw.gerar_yaml_spec_v5(
        [{"stem": "paladin", "glb_rel": str(glb), "sha256": digest, "seed": 42}]
    )
    doc = yaml.safe_load(yaml_str)
    spec_doc, _perfil, _avisos = spec.preparar(doc)
    assert spec_doc["schema"] == "forge3d/spec@5"
    assert spec_doc["requisicao"]["base_externa"]["sha256"] == digest

    yaml_str_v6 = tw.gerar_yaml_spec(
        [{"stem": "paladin", "glb_rel": str(glb), "sha256": digest, "seed": 42}],
        schema_version=6,
        qualidade="hero",
    )
    doc_v6 = yaml.safe_load(yaml_str_v6)
    assert doc_v6["schema"] == "forge3d/spec@6"
    assert doc_v6["lote"][0]["qualidade"] == "hero"


def test_spec_v6_origem_espacos_em_branco_rejeitada(tmp_path):
    from forge3d import profiles, spec, spec_regras

    for rota in ("i23d", "extrude_2d", "template", "import"):
        doc = {
            "schema": "forge3d/spec@6",
            "projeto": "p_ws",
            "perfil": "godot4",
            "destino_exportacao": str(tmp_path / "out"),
            "lote": [
                {
                    "id": f"a.{rota}",
                    "tipo": "prop_estatico",
                    "rota": rota,
                    "altura_metros": 1.0,
                    "origem": "   ",
                }
            ],
        }
        with pytest.raises(ForgeError) as exc:
            spec.preparar(doc)
        assert exc.value.codigo == "FORGE-E-SPEC"

        perfil = profiles.carregar("godot4")
        with pytest.raises(ForgeError) as exc_reg:
            spec_regras.regras_negocio(doc, perfil)
        assert exc_reg.value.codigo == "FORGE-E-SPEC"


def test_concept_preflight_1arg_monkeypatch_e_vistas4_imagen(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE3D_GEMINI_API_KEY", "test_key_preflight")
    monkeypatch.setenv("FORGE3D_GEMINI_MODELO", "imagen-3.0-generate-002")
    ok_v4, razao_v4 = concept.ConceptProvider().preflight(
        {"id": "v4.img", "prompt": "knight", "provider_conceito": "gemini", "vistas": 4}
    )
    assert ok_v4 is False
    assert "gemini-*" in razao_v4

    monkeypatch.setattr(concept, "preflight", lambda item: (True, f"ok:{item}"))
    assert concept.ConceptProvider().preflight() == (True, "ok:None")

    def fake_run(comando, **_kwargs):
        saida = Path(comando[comando.index("--saida") + 1])
        res_path = Path(comando[comando.index("--resultado") + 1])
        Image.new("RGB", (32, 32), (100, 120, 140)).save(saida)
        res_path.write_text(json.dumps({"ok": True, "modelo": "sd15", "seed": 1}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(concept.subprocess, "run", fake_run)
    res = concept.ConceptProvider().gerar(
        {"id": "c.sd15", "prompt": "knight", "provider_conceito": "sd15"},
        tmp_path / "sd15_1arg",
    )
    assert res["png"].is_file()


def test_concept_negativo_map_invalido_sem_id_seed_nulo_e_mime_magic(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE3D_CONCEPT_NEGATIVO_MAP", "{bad_json")
    with pytest.raises(ValueError, match="FORGE3D_CONCEPT_NEGATIVO_MAP"):
        concept.negativo_efetivo({"prompt": "knight"})

    monkeypatch.setenv("FORGE3D_CONCEPT_NEGATIVO_MAP", "[1, 2, 3]")
    with pytest.raises(ValueError, match="objeto JSON"):
        concept.negativo_efetivo({"prompt": "knight"})

    monkeypatch.delenv("FORGE3D_CONCEPT_NEGATIVO_MAP", raising=False)
    monkeypatch.setenv("FORGE3D_GEMINI_API_KEY", "AIza_TEST_SEED_MIME")
    monkeypatch.delenv("FORGE3D_GEMINI_MODELO", raising=False)

    with pytest.raises(ForgeError) as exc_seed:
        concept.ConceptProvider().gerar(
            {"prompt": "knight", "provider_conceito": "gemini", "seed": None},
            tmp_path / "seed_none",
        )
    assert exc_seed.value.codigo == "FORGE-E-PROVIDER-RUN"

    b64_out = base64.b64encode(_png_bytes_rgba((50, 100, 150, 255))).decode("ascii")
    mimes: list[str] = []

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"steps": [{"type": "model_output", "content": [{"type": "image", "data": b64_out}]}]}
            ).encode("utf-8")

    def fake_urlopen(req, timeout=120):
        body = json.loads(req.data.decode("utf-8"))
        mimes.append(body["input"][1]["mime_type"])
        return _FakeResp()

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_urlopen)
    jpg_ref = tmp_path / "ref.jpg"
    buf_jpg = io.BytesIO()
    Image.new("RGB", (16, 16), (20, 30, 40)).save(buf_jpg, format="JPEG")
    jpg_ref.write_bytes(buf_jpg.getvalue())
    cloud_ai.gerar_conceito_gemini("knight", "", 1, tmp_path / "o1.png", referencia_png=jpg_ref)

    webp_ref = tmp_path / "ref.webp"
    webp_ref.write_bytes(b"RIFF\x10\x00\x00\x00WEBPVP8 ")
    cloud_ai.gerar_conceito_gemini("knight", "", 2, tmp_path / "o2.png", referencia_png=webp_ref)
    assert mimes == ["image/jpeg", "image/webp"]


def test_plan_budget_rig_modo_none_e_template_nao_organico(tmp_path):
    from forge3d import plan_budget, profiles, spec

    doc = {
        "schema": "forge3d/spec@6",
        "projeto": "p_rig_none",
        "perfil": "godot4-aa",
        "destino_exportacao": str(tmp_path / "out"),
        "orcamento_cena": {"triangulos_max": 400000, "draw_calls_max": 50, "vram_mb_max": 200},
        "lote": [
            {
                "id": "prop.crate.01",
                "tipo": "prop_estatico",
                "rota": "blocky",
                "altura_metros": 1.0,
                "quantidade_cena": 100,
                "rig": {"modo": "none"},
            }
        ],
    }
    s, p, _ = spec.preparar(doc)
    orc = plan_budget.estimar_orcamento_cena(s, p)
    assert orc["estimativa"]["itens"][0]["skinned"] is False
    assert orc["estimativa"]["draw_calls_estimados"] == 1
    assert orc["estimativa"]["status"] == "ok"

    perfil = profiles.carregar("godot4-aa")
    est_prop = plan_budget._estimar_item_calibrado(
        {"id": "t.prop", "tipo": "prop_estatico", "rota": "template", "limite_triangulos": 1000},
        {"schema": "forge3d/spec@6"},
        perfil,
    )
    assert est_prop["skinned"] is False
    est_hum_none = plan_budget._estimar_item_calibrado(
        {
            "id": "t.hum",
            "tipo": "personagem_humanoide",
            "rota": "template",
            "limite_triangulos": 1000,
            "rig": {"modo": "none"},
        },
        {"schema": "forge3d/spec@6"},
        perfil,
    )
    assert est_hum_none["skinned"] is False


def test_sd15_seed_nulo_preflight_item_b23_whitespace_e_qa_mime(monkeypatch, tmp_path):
    from forge3d import profiles, spec_regras

    # 1) ConceptProvider.gerar com sd15 passa item ao preflight (nao cai no Gemini mesmo com chave ativa)
    monkeypatch.setenv("FORGE3D_GEMINI_API_KEY", "AIza_SHOULD_NOT_BYPASS_SD15_PREFLIGHT")
    monkeypatch.setenv("FORGE3D_VENV_CONCEPT", str(tmp_path / "venv_inexistente"))
    with pytest.raises(ForgeError) as exc_pf:
        concept.ConceptProvider().gerar(
            {"id": "c.sd15.pf", "prompt": "knight", "provider_conceito": "sd15"},
            tmp_path / "sd15_pf",
        )
    assert exc_pf.value.codigo == "FORGE-E-PROVIDER-RUN"
    assert "venv" in str(exc_pf.value).lower()

    # 2) {"seed": None} em sd15 levanta ForgeError FORGE-E-PROVIDER-RUN (simetrico a gemini/higgsfield)
    monkeypatch.setattr(concept, "preflight", lambda item=None: (True, "ok"))
    with pytest.raises(ForgeError) as exc_seed_sd15:
        concept.ConceptProvider().gerar(
            {"id": "c.sd15.seed", "prompt": "knight", "provider_conceito": "sd15", "seed": None},
            tmp_path / "sd15_seed_none",
        )
    assert exc_seed_sd15.value.codigo == "FORGE-E-PROVIDER-RUN"

    # 3) B23 direta em regras_negocio com origem whitespace + referencia_estilo valida nao gera falso B23
    ref_png = tmp_path / "ref_b23.png"
    ref_png.write_bytes(_png_bytes_rgba((40, 80, 120, 255)))
    perfil = profiles.carregar("godot4")
    spec_regras.regras_negocio(
        {
            "lote": [
                {
                    "id": "mesh.b23.ws",
                    "tipo": "prop_estatico",
                    "rota": "mesh",
                    "seed": 7,
                    "origem": "   ",
                    "referencia_estilo": str(ref_png),
                }
            ]
        },
        perfil,
    )

    # 4) avaliar_qualidade_visual_gemini usa _inferir_mime_imagem para JPEG
    jpg_qa = tmp_path / "render.jpg"
    buf_qa = io.BytesIO()
    Image.new("RGB", (16, 16), (90, 90, 90)).save(buf_qa, format="JPEG")
    jpg_qa.write_bytes(buf_qa.getvalue())
    mimes_qa: list[str] = []

    class _FakeRespQA:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"outputs": [{"text": '{"aprovado": true, "nota": 9.0, "defeitos": []}'}]}
            ).encode("utf-8")

    def fake_urlopen_qa(req, timeout=120):
        body = json.loads(req.data.decode("utf-8"))
        mimes_qa.append(body["input"][1]["mime_type"])
        return _FakeRespQA()

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_urlopen_qa)
    res_qa = cloud_ai.avaliar_qualidade_visual_gemini(jpg_qa)
    assert res_qa["aprovado"] is True
    assert mimes_qa == ["image/jpeg"]
