"""Testes do Vault CC0, Gemini Embedding-2, Kitbash Composer LLM e TRELLIS LoRA (MIT)."""

from __future__ import annotations

import ast
import importlib.util
import json
import math
import urllib.error
from pathlib import Path

import pytest

from forge3d import post
from forge3d.errors import ForgeError
from forge3d.providers import cloud_ai
from forge3d.vault import (
    LICENCAS_PERMITIDAS,
    ORIGENS_PERMITIDAS,
    VaultCC0,
    similaridade_cosseno,
    validar_licenca_cc0,
)

RAIZ = Path(__file__).resolve().parents[1]


def _carregar_modulo_tool(nome: str, arquivo: str):
    spec = importlib.util.spec_from_file_location(nome, RAIZ / "tools" / arquivo)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_vault_usa_apenas_stdlib_d26():
    """Garante zero dependencias externas de pip em src/forge3d/vault.py (D26)."""
    arvore = ast.parse((RAIZ / "src" / "forge3d" / "vault.py").read_text("utf-8"))
    permitidos = {
        "__future__",
        "datetime",
        "hashlib",
        "json",
        "math",
        "os",
        "pathlib",
        "re",
        "sqlite3",
        "struct",
        "sys",
        "typing",
    }
    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                assert mod in permitidos, f"import externo proibido em vault.py: {mod}"
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mod = node.module.split(".")[0]
            assert mod in permitidos, f"from-import externo proibido em vault.py: {mod}"


def test_validar_licenca_cc0_allowlist_e_bloqueio_i7_d18():
    for lic in LICENCAS_PERMITIDAS:
        for orig in ORIGENS_PERMITIDAS:
            res = validar_licenca_cc0(lic, origem=orig)
            assert res["ok"] is True
            assert res["uso_comercial"] is True

    # Rejeicao estrita de NC, BY-NC, GPL e unknown; hunyuan continua bloqueado;
    # pixal3d saiu do bloqueio em 18/11/2026 (D112: LICENSE oficial MIT)
    casos_proibidos = [
        ("CC-BY-NC-4.0", "polyhaven", ""),
        ("BY-NC", "ambientcg", ""),
        ("NC", "kenney", ""),
        ("GPL-3.0", "local_cc0", ""),
        ("GPL", "quaternius", ""),
        ("unknown", "local_cc0", ""),
        ("CC0-1.0", "hunyuan", ""),
        ("CC0-1.0", "local_cc0", "hunyuan3d-2"),
        ("CC0-1.0", "sketchfab_random", ""),
        ("", "local_cc0", ""),
    ]
    for lic, orig, mod in casos_proibidos:
        with pytest.raises(ForgeError) as exc_info:
            validar_licenca_cc0(lic, origem=orig, modelo=mod)
        assert exc_info.value.codigo == "FORGE-E-LICENCA"

    # D112: Pixal3D e MIT desde 18/11/2026 (LICENSE verificada) e sai do bloqueio.
    res_pixal3d = validar_licenca_cc0("MIT", origem="local_cc0", modelo="pixal3d-v1")
    assert res_pixal3d["ok"] is True
    assert res_pixal3d["uso_comercial"] is True


def test_vault_sqlite_crud_sha256_tamper_e_busca_semantica(tmp_path):
    vault_dir = tmp_path / "vault_state"
    vault = VaultCC0(vault_dir)
    assert (vault_dir / "vault.sqlite").is_file()

    arq_espada = tmp_path / "sword_blade.glb"
    arq_espada.write_bytes(b"glTF\x02\x00\x00\x00SWORD_BLADE")
    arq_cabo = tmp_path / "leather_grip.glb"
    arq_cabo.write_bytes(b"glTF\x02\x00\x00\x00LEATHER_GRIP")
    arq_escudo = tmp_path / "wooden_shield.glb"
    arq_escudo.write_bytes(b"glTF\x02\x00\x00\x00WOODEN_SHIELD")

    a1 = vault.registrar_ativo(
        asset_id="kb.sword_blade",
        caminho=arq_espada,
        tipo="kitbash_part",
        categoria="weapon",
        licenca="CC0-1.0",
        origem="quaternius",
        nome="Forged Steel Blade",
        descricao="Lamina de espada de aco forjado",
        tags=["blade", "sword", "steel", "lamina"],
        embedding=[1.0, 0.0, 0.0, 0.0],
    )
    assert a1["sha256"].startswith("sha256:")
    assert a1["licenca"] == "CC0-1.0"

    vault.registrar_ativo(
        asset_id="kb.leather_grip",
        caminho=arq_cabo,
        tipo="kitbash_part",
        categoria="weapon",
        licenca="CC0",
        origem="kenney",
        nome="Leather Hilt Grip",
        descricao="Cabo cilindrico de couro gasto",
        tags=["grip", "handle", "leather", "cabo"],
        embedding=[0.0, 1.0, 0.0, 0.0],
    )
    vault.registrar_ativo(
        asset_id="kb.wooden_shield",
        caminho=arq_escudo,
        tipo="kitbash_part",
        categoria="armor",
        licenca="Public Domain",
        origem="polyhaven",
        nome="Oak Round Shield",
        descricao="Escudo redondo de madeira",
        tags=["shield", "wood", "escudo"],
        embedding=[0.0, 0.0, 1.0, 0.0],
    )

    assert len(vault.listar_ativos()) == 3
    assert len(vault.listar_ativos(categoria="weapon")) == 2

    # Busca semantica via vetor de cosseno
    res_cos = vault.buscar_semantico(
        "item",
        query_embedding=[0.95, 0.05, 0.0, 0.0],
        top_k=2,
    )
    assert res_cos[0]["asset_id"] == "kb.sword_blade"
    assert res_cos[0]["metodo_busca"] == "embedding_cosine"
    assert res_cos[0]["score_cosseno"] > 0.98

    # Busca offline lexical BM25 com expansao de sinonimos PT/EN (sem query_embedding)
    res_lex = vault.buscar_semantico("punho de couro", top_k=2)
    assert res_lex[0]["asset_id"] == "kb.leather_grip"
    assert res_lex[0]["metodo_busca"] == "lexical_bm25"
    assert res_lex[0]["score_lexical"] > 0.0

    # Integridade SHA256 limpa
    ver_ok = vault.validar_integridade(levantar=True)
    assert ver_ok["ok"] is True
    assert ver_ok["validos"] == 3

    # Adulteracao em disco deve disparar FORGE-E-INPUT-TAMPERED
    arq_espada.write_bytes(b"glTF\x02\x00\x00\x00CORRUPTED_BYTES")
    ver_fail = vault.validar_integridade(levantar=False)
    assert ver_fail["ok"] is False
    assert ver_fail["corrompidos"][0]["asset_id"] == "kb.sword_blade"

    with pytest.raises(ForgeError) as exc_tamper:
        vault.validar_integridade(levantar=True)
    assert exc_tamper.value.codigo == "FORGE-E-INPUT-TAMPERED"


def test_gemini_embedding_2_e_planejar_kitbash_mock_e_fallback(monkeypatch, tmp_path):
    cfg_dir = tmp_path / "cfg_empty"
    cfg_dir.mkdir()
    monkeypatch.setenv("FORGE3D_CONFIG", str(cfg_dir))
    monkeypatch.delenv("FORGE3D_GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(cloud_ai, "_ler_arquivo_chave", lambda _nome: "")

    catalogo = [
        {"asset_id": "kb.cylindrical_grip", "nome": "Grip", "tipo": "kitbash_part", "tags": ["grip", "leather"]},
        {"asset_id": "kb.crossguard", "nome": "Guard", "tipo": "kitbash_part", "tags": ["guard", "bronze"]},
        {"asset_id": "kb.sword_blade", "nome": "Blade", "tipo": "kitbash_part", "tags": ["blade", "steel"]},
    ]

    # Fallback deterministico offline quando nao ha chave API
    plano_off = cloud_ai.planejar_kitbash_gemini("forged paladin sword", catalogo)
    assert plano_off["ok"] is True
    assert plano_off["modo"] == "offline_fallback"
    assert len(plano_off["pecas"]) == 3
    assert plano_off["pecas"][0]["snap_para"] is None
    assert plano_off["pecas"][1]["snap_para"] == plano_off["pecas"][0]["id"]
    assert len(plano_off["pbr_zonas"]) >= 1

    # Com chave API configurada: testa gerar_embedding_gemini (alias gemini-embedding-2) e planejar_kitbash_gemini
    segredo = "AIza_EMBED_KITBASH_SECRET_999"
    monkeypatch.setenv("FORGE3D_GEMINI_API_KEY", segredo)
    capturado: list[dict] = []

    class _FakeResp:
        def __init__(self, payload: dict):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

    def fake_urlopen(req, timeout=30):
        body = json.loads(req.data.decode("utf-8"))
        capturado.append({"url": req.full_url, "body": body})
        if ":embedContent" in req.full_url:
            return _FakeResp({"embedding": {"values": [3.0, 4.0, 0.0]}})
        plano_llm = {
            "pecas": [
                {"id": "kb.cylindrical_grip", "papel": "base", "snap_para": None, "escala": 1.0, "pbr_zona": "couro_gasto"},
                {"id": "kb.sword_blade", "papel": "blade", "snap_para": "kb.cylindrical_grip", "escala": 1.0, "pbr_zona": "aco_forjado"},
            ],
            "pbr_zonas": [
                {"nome": "aco_forjado", "preset": "aco_forjado", "cor_hex": "#9AA2AC"},
            ],
            "estilo": "dark_fantasy_pbr",
        }
        return _FakeResp(
            {
                "steps": [
                    {
                        "type": "model_output",
                        "content": [{"type": "text", "text": json.dumps(plano_llm)}],
                    }
                ]
            }
        )

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_urlopen)
    emb = cloud_ai.gerar_embedding_gemini(
        "forged steel sword blade",
        model="gemini-embedding-2",
        output_dimensionality=3,
    )
    assert len(emb) == 3
    assert math.isclose(emb[0], 0.6, rel_tol=1e-5)
    assert math.isclose(emb[1], 0.8, rel_tol=1e-5)
    assert math.isclose(similaridade_cosseno(emb, emb), 1.0, rel_tol=1e-6)
    assert capturado[-1]["url"].endswith("/models/gemini-embedding-2-preview:embedContent")
    assert capturado[-1]["body"]["outputDimensionality"] == 3

    plano_on = cloud_ai.planejar_kitbash_gemini("dark forged broadsword", catalogo)
    assert plano_on["ok"] is True
    assert plano_on["modo"] == "gemini_interactions"
    assert plano_on["estilo"] == "dark_fantasy_pbr"
    assert len(plano_on["pecas"]) == 2
    assert plano_on["pecas"][1]["snap_para"] == "kb.cylindrical_grip"

    # Sanitizacao de segredo em falha de rede
    def fake_err(req, timeout=30):
        raise urllib.error.URLError(f"erro ?key={segredo}")

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_err)
    with pytest.raises(ForgeError) as exc_info:
        cloud_ai.gerar_embedding_gemini("teste")
    assert segredo not in str(exc_info.value)
    assert "REDACTED" in str(exc_info.value)


def test_vault_sync_cc0_cli_seed_manifest_query_verify(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("FORGE3D_GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(cloud_ai, "_ler_arquivo_chave", lambda _nome: "")
    vs = _carregar_modulo_tool("vault_sync_cc0_mod", "vault_sync_cc0.py")

    vault_dir = tmp_path / "vault_cli"
    rc = vs.main(["--seed-local", "--embed", "--verify", "--vault-dir", str(vault_dir), "--json"])
    assert rc == 0
    saida = json.loads(capsys.readouterr().out)
    assert saida["ok"] is True
    assert saida["seed"]["total_registrados"] >= 8
    assert saida["integridade"]["ok"] is True

    # Query via CLI
    rc_q = vs.main(["--query", "forged steel blade", "--vault-dir", str(vault_dir), "--json"])
    assert rc_q == 0
    saida_q = json.loads(capsys.readouterr().out)
    ids_q = [r["asset_id"] for r in saida_q["resultados"]]
    assert "kb.sword_blade" in ids_q or "pbr.steel_forged_albedo" in ids_q

    # Manifesto envenenado com licenca NC deve retornar exit code de erro
    manifest_nc = tmp_path / "bad_manifest.json"
    arq_dummy = tmp_path / "dummy.glb"
    arq_dummy.write_bytes(b"glTF\x02\x00\x00\x00DUMMY")
    manifest_nc.write_text(
        json.dumps(
            [
                {
                    "asset_id": "bad.nc_mesh",
                    "caminho": str(arq_dummy),
                    "licenca": "CC-BY-NC-4.0",
                    "origem": "polyhaven",
                }
            ]
        ),
        encoding="utf-8",
    )
    rc_bad = vs.main(["--manifest", str(manifest_nc), "--vault-dir", str(vault_dir), "--json"])
    assert rc_bad != 0
    saida_bad = json.loads(capsys.readouterr().out)
    assert saida_bad["ok"] is False
    assert saida_bad["codigo"] == "FORGE-E-LICENCA"


def test_colab_trellis_lora_dry_run_e_bloqueio_licenca(tmp_path, capsys):
    tl = _carregar_modulo_tool("colab_trellis_lora_mod", "colab_trellis_lora.py")
    vs = _carregar_modulo_tool("vault_sync_cc0_for_lora", "vault_sync_cc0.py")

    vault_dir = tmp_path / "vault_lora"
    vs.seed_local_cc0(VaultCC0(vault_dir))

    out_lora = tmp_path / "lora_out"
    rc = tl.main(
        [
            "--vault-dir",
            str(vault_dir),
            "--output-dir",
            str(out_lora),
            "--base-model",
            "JeffreyXiang/TRELLIS-image-large",
            "--lora-r",
            "16",
            "--lora-alpha",
            "32",
            "--views",
            "24",
            "--dry-run",
            "--json",
        ]
    )
    assert rc == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["ok"] is True
    assert manifest["licenca"] == "MIT"
    assert manifest["uso_comercial"] is True
    assert manifest["peft_lora"]["r"] == 16
    assert manifest["peft_lora"]["lora_alpha"] == 32
    assert manifest["condicionamento_24_vistas"]["num_vistas"] == 24
    assert (out_lora / "lora_manifest.json").is_file()
    assert (out_lora / "adapter_config.json").is_file()
    assert (out_lora / "conditioning_24views.py").is_file()

    # Rejeicao de dataset contendo item hunyuan ou GPL
    bad_ds = tmp_path / "bad_ds.json"
    arq_glb = tmp_path / "mesh.glb"
    arq_glb.write_bytes(b"glTF\x02\x00\x00\x00MESH")
    bad_ds.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "poison.hunyuan",
                        "caminho": str(arq_glb),
                        "licenca": "CC0-1.0",
                        "origem": "local_cc0",
                        "modelo": "hunyuan3d-2",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    rc_bad = tl.main(["--dataset-manifest", str(bad_ds), "--validate-dataset", "--json"])
    assert rc_bad != 0
    err_out = json.loads(capsys.readouterr().out)
    assert err_out["codigo"] == "FORGE-E-LICENCA"


def test_kitbash_composer_dry_run(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("FORGE3D_GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(cloud_ai, "_ler_arquivo_chave", lambda _nome: "")
    kc = _carregar_modulo_tool("kitbash_composer_dry", "kitbash_composer.py")

    vault_dir = tmp_path / "vault_kb_dry"
    out_dir = tmp_path / "out_kb_dry"
    rc = kc.main(
        [
            "--prompt",
            "forged steel broadsword with leather grip and bronze guard",
            "--vault-dir",
            str(vault_dir),
            "--out-dir",
            str(out_dir),
            "--dry-run",
            "--json",
        ]
    )
    assert rc == 0
    rel = json.loads(capsys.readouterr().out)
    assert rel["ok"] is True
    assert rel["dry_run"] is True
    assert Path(rel["job_in"]).is_file()
    assert Path(rel["plan_json"]).is_file()


@pytest.mark.blender
def test_kitbash_composer_blender_headless_manifold_e_visual_qa(monkeypatch, tmp_path):
    ok_bl, razao = post.preflight()
    if not ok_bl:
        pytest.skip(f"Blender 4.2.x indisponivel: {razao}")

    monkeypatch.delenv("FORGE3D_GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(cloud_ai, "_ler_arquivo_chave", lambda _nome: "")
    kc = _carregar_modulo_tool("kitbash_composer_bl", "kitbash_composer.py")

    vault_dir = tmp_path / "vault_kb_bl"
    out_dir = tmp_path / "out_kb_bl"
    out_glb = out_dir / "paladin_sword.glb"

    rel = kc.compor_kitbash(
        "forged steel broadsword with leather grip and bronze crossguard",
        vault_dir=vault_dir,
        out_glb=out_glb,
        out_dir=out_dir,
        render=True,
        size=240,
        samples=8,
        dry_run=False,
    )
    assert rel["ok"] is True
    assert out_glb.is_file()
    assert rel["geometria"]["nao_manifold"] == 0
    assert rel["geometria"]["triangulos"] > 20
    assert math.isclose(rel["geometria"]["snap_folga_m"], 0.0015, rel_tol=1e-5)
    assert rel["grip_info"]["raio_m"] > 0.01
    assert Path(rel["turntable_png"]).is_file()
    assert rel["qa_visual"]["aprovado"] is True
    assert rel["qa_visual"]["defeitos"] == []
