"""Testes do contrato spec@6 / manifest@6, perfis AA, alpha_cards, G9 ultra e Gate G11."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import jsonschema
import pytest
import yaml

import forge3d
from forge3d import canonical, pipeline, plan, profiles, publish, qc, spec, verify
from forge3d.cli.main import main
from forge3d.errors import EXIT_QC, ForgeError

RAIZ = Path(__file__).resolve().parents[1]


def _glb_minimo(
    verts: list[tuple[float, float, float]],
    tris: list[tuple[int, int, int]],
    *,
    normals: list[tuple[float, float, float]] | None = None,
    uvs: list[tuple[float, float]] | None = None,
    skins: list[dict] | None = None,
    nodes_extra: list[dict] | None = None,
    mats: list[dict] | None = None,
) -> bytes:
    """Constroi um GLB valido em memoria com malha arbitraria (ex: card aberto ou aresta-T)."""
    pos_bytes = b"".join(struct.pack("<3f", *v) for v in verts)
    uv_list = uvs or [(0.0, 0.0) if i % 3 == 0 else (1.0, 0.0) if i % 3 == 1 else (0.5, 1.0) for i in range(len(verts))]
    uv_bytes = b"".join(struct.pack("<2f", *uv) for uv in uv_list)
    norm_list = normals or [(0.0, 0.0, 1.0)] * len(verts)
    norm_bytes = b"".join(struct.pack("<3f", *n) for n in norm_list)
    idx_bytes = b"".join(struct.pack("<3H", *t) for t in tris)

    buf = bytearray()
    bvs = []
    accs = []

    def _add(raw: bytes, target: int) -> int:
        while len(buf) % 4 != 0:
            buf.append(0)
        off = len(buf)
        buf.extend(raw)
        bvs.append({"buffer": 0, "byteOffset": off, "byteLength": len(raw), "target": target})
        return len(bvs) - 1

    bv_pos = _add(pos_bytes, 34962)
    bv_norm = _add(norm_bytes, 34962)
    bv_uv = _add(uv_bytes, 34962)
    bv_idx = _add(idx_bytes, 34963)
    while len(buf) % 4 != 0:
        buf.append(0)

    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    accs.append(
        {
            "bufferView": bv_pos,
            "componentType": 5126,
            "count": len(verts),
            "type": "VEC3",
            "min": [min(xs), min(ys), min(zs)],
            "max": [max(xs), max(ys), max(zs)],
        }
    )
    accs.append({"bufferView": bv_norm, "componentType": 5126, "count": len(verts), "type": "VEC3"})
    accs.append({"bufferView": bv_uv, "componentType": 5126, "count": len(verts), "type": "VEC2"})
    accs.append(
        {"bufferView": bv_idx, "componentType": 5123, "count": len(tris) * 3, "type": "SCALAR"}
    )

    nodes = [{"name": "mesh_node", "mesh": 0}]
    if nodes_extra:
        nodes.extend(nodes_extra)

    gltf: dict = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                        "indices": 3,
                        "material": 0,
                    }
                ]
            }
        ],
        "materials": mats
        or [
            {
                "name": "mat0",
                "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1.0]},
            }
        ],
        "accessors": accs,
        "bufferViews": bvs,
        "buffers": [{"byteLength": len(buf)}],
    }
    if skins:
        gltf["skins"] = skins

    json_b = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(json_b) % 4 != 0:
        json_b += b" "

    total = 12 + 8 + len(json_b) + 8 + len(buf)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(json_b), 0x4E4F534A)
        + json_b
        + struct.pack("<II", len(buf), 0x004E4942)
        + bytes(buf)
    )


def _cubo_fechado_glb(altura: float = 1.0) -> bytes:
    """Cubo unitario fechado centrado em XZ com base em Y=0."""
    hx, hz = 0.25, 0.25
    verts = [
        (-hx, 0.0, -hz), (hx, 0.0, -hz), (hx, altura, -hz), (-hx, altura, -hz),
        (-hx, 0.0, hz), (hx, 0.0, hz), (hx, altura, hz), (-hx, altura, hz),
    ]
    tris = [
        (0, 2, 1), (0, 3, 2),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (2, 3, 7), (2, 7, 6),
        (0, 4, 7), (0, 7, 3),
        (1, 2, 6), (1, 6, 5),
    ]
    return _glb_minimo(verts, tris)


def test_versao_0_9_5_e_consistente():
    assert forge3d.__version__ == "0.9.6"
    pyproject = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.9.6"' in pyproject


def test_perfis_aa_e_56_ossos_exatos():
    g4 = profiles.carregar("godot4")
    g4aa = profiles.carregar("godot4-aa")
    r15 = profiles.carregar("roblox-r15")
    raa = profiles.carregar("roblox-aa-80")

    assert g4["versao"] == 2
    assert g4["material"]["textura_max"] == 4096
    assert g4["material"]["filtro"] == "linear_mipmap_anisotropic"
    assert g4["validacao"]["bytes_max_kb"] == 25600
    assert "godot-humanoid-aa@1" in g4["rig"]["mapas"]
    assert "godot-humanoid-aa@1" in g4["rig"]["retarget"]

    assert g4aa["rig"]["esqueleto_padrao"] == "godot-humanoid-aa@1"
    assert g4aa["rig"]["max_ossos"] == 64
    ossos_56 = g4aa["rig"]["mapas"]["godot-humanoid-aa@1"]
    assert len(ossos_56) == 56
    assert len(set(ossos_56)) == 56
    for req in ("Jaw", "Eye.L", "Eye.R", "Cape", "Thumb1.L", "Little3.R", "Toe.R"):
        assert req in ossos_56

    assert r15["versao"] == 3
    assert r15["validacao"]["bytes_max_kb"] == 16384
    assert r15["validacao"]["triangulos_por_parte_max"] == 16000
    assert r15["validacao"]["triangulos_por_parte_max_ultra"] == 18000

    assert raa["rig"]["max_ossos"] == 64
    assert len(raa["rig"]["mapas"]["quadruped@1"]) == 23
    assert len(raa["rig"]["mapas"]["winged_mount@1"]) == 31
    assert raa["rig"]["mapas"]["quadruped@1"] == g4["rig"]["mapas"]["quadruped@1"]
    assert raa["rig"]["mapas"]["winged_mount@1"] == g4["rig"]["mapas"]["winged_mount@1"]
    assert "WingArm.L" in raa["rig"]["mapas"]["winged_mount@1"]


def test_limite_tri_qualidade_e_orcamento_cena_perfil():
    raa = profiles.carregar("roblox-aa-80")
    assert profiles.limite_tri_qualidade(raa, "prop_estatico", "standard") == 5000
    assert profiles.limite_tri_qualidade(raa, "prop_estatico", "hero") == 10000
    assert profiles.limite_tri_qualidade(raa, "prop_estatico", "ultra") == 16000
    assert profiles.limite_tri_qualidade(raa, "modulo_cenario", "ultra") == 16000
    assert profiles.limite_tri_hero(raa, "personagem_humanoide") == 14000

    orc = profiles.orcamento_cena_perfil(raa, {"orcamento_cena": {"triangulos_max": 350000}})
    assert orc["triangulos_cena_max"] == 350000
    assert orc["draw_calls_cena_max"] == 400
    assert orc["vram_texturas_mb_max"] == 200.0


def test_spec_v6_aceita_campos_novos_e_entra_no_cache():
    for campo in ("detalhe_alto", "pbr_zonas", "render_fidelity_roblox", "alpha_cards", "smart_fit", "referencia_estilo"):
        assert campo in spec.CAMPOS_CANONICOS_ITEM

    doc_base = {
        "schema": "forge3d/spec@6",
        "projeto": "citadel_test",
        "perfil": "godot4-aa",
        "destino_exportacao": "~/.local/state/forge3d/saida/spec6",
        "orcamento_cena": {"triangulos_max": 400000, "draw_calls_max": 400, "vram_mb_max": 200},
        "roblox_render": {
            "lighting_technology": "Future",
            "render_fidelity_padrao": "Precise",
            "surface_appearance": True,
            "strip_embedded_textures_glb": True,
        },
        "lote": [
            {
                "id": "hero.knight.01",
                "tipo": "personagem_humanoide",
                "rota": "blocky",
                "altura_metros": 1.85,
                "auto_rig": True,
                "esqueleto": "godot-humanoid-aa@1",
                "qualidade": "ultra",
                "alpha_cards": True,
                "quantidade_cena": 2,
                "render_fidelity_roblox": "Precise",
                "detalhe_alto": {
                    "ativo": True,
                    "subdiv_niveis": 2,
                    "chanfro_bevel_m": 0.008,
                    "crease_angulo_graus": 38.0,
                    "ao_cavidade_forca": 0.35,
                },
                "pbr_zonas": [
                    {"nome": "armadura", "cor_hex": "#707880", "preset": "aco_forjado"}
                ],
                "smart_fit": {"folga_m": 0.0015},
            }
        ],
    }
    prep, perfil, _avisos = spec.preparar(doc_base)
    it = prep["lote"][0]
    assert it["limite_triangulos"] == 28000
    assert it["esqueleto"] == "godot-humanoid-aa@1"

    k1 = canonical.chave_cache(spec.resolver_item(it), "0.9.0", {"blocky": "0.1"}, perfil)
    it_mod = dict(it)
    it_mod["alpha_cards"] = False
    k2 = canonical.chave_cache(spec.resolver_item(it_mod), "0.9.0", {"blocky": "0.1"}, perfil)
    assert k1 != k2

    with pytest.raises(ForgeError):
        spec.preparar({**doc_base, "orcamento_cena": {"triangulos_max": 100}})


def test_spec_v6_b23_referencia_estilo(tmp_path):
    ref_png = tmp_path / "style_sheet.png"
    ref_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    def _doc(provider: str, ref: str) -> dict:
        return {
            "schema": "forge3d/spec@6",
            "projeto": "teste_ref_estilo",
            "perfil": "godot4-aa",
            "destino_exportacao": "~/.local/state/forge3d/saida/spec6",
            "lote": [
                {
                    "id": "espada.ref.01",
                    "tipo": "prop_estatico",
                    "rota": "mesh",
                    "prompt": "espada de cristal arcano",
                    "altura_metros": 0.9,
                    "seed": 7,
                    "provider_conceito": provider,
                    "referencia_estilo": ref,
                }
            ],
        }

    prep, _perfil, _avisos = spec.preparar(_doc("gemini", str(ref_png)))
    assert prep["lote"][0]["referencia_estilo"] == str(ref_png)
    assert "referencia_estilo_hash" in spec.resolver_item(prep["lote"][0])

    # B23: provider sd15/higgsfield nao suporta referencia de estilo
    for provider_ruim in ("sd15", "higgsfield"):
        with pytest.raises(ForgeError) as exc:
            spec.preparar(_doc(provider_ruim, str(ref_png)))
        assert any(e.get("regra") == "B23" for e in exc.value.detalhes["erros"])

    # B23: arquivo inexistente
    with pytest.raises(ForgeError) as exc2:
        spec.preparar(_doc("gemini", str(tmp_path / "nao_existe.png")))
    assert any(e.get("regra") == "B23" for e in exc2.value.detalhes["erros"])

    # B23: rota fora de mesh
    doc_blocky = _doc("gemini", str(ref_png))
    doc_blocky["lote"][0]["rota"] = "blocky"
    with pytest.raises(ForgeError) as exc3:
        spec.preparar(doc_blocky)
    assert any(e.get("regra") == "B23" for e in exc3.value.detalhes["erros"])

    # B23 (D-01): origem + referencia_estilo sao mutuamente exclusivos
    # (origem e input do i23d; referencia ancora o concept, que nao roda com origem)
    origem_png = tmp_path / "entrada.png"
    origem_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    doc_origem = _doc("gemini", str(ref_png))
    doc_origem["lote"][0]["origem"] = str(origem_png)
    with pytest.raises(ForgeError) as exc4:
        spec.preparar(doc_origem)
    assert any(e.get("regra") == "B23" for e in exc4.value.detalhes["erros"])


def test_spec_v6_b24_esqueleto_x_tipo_incompativel():
    def _doc(tipo: str, esqueleto: str) -> dict:
        return {
            "schema": "forge3d/spec@6",
            "projeto": "teste_b24",
            "perfil": "godot4-aa",
            "destino_exportacao": "~/.local/state/forge3d/saida/b24",
            "lote": [
                {
                    "id": "criatura.b24.01",
                    "tipo": tipo,
                    "rota": "mesh",
                    "prompt": "criatura de teste",
                    "altura_metros": 1.5,
                    "seed": 7,
                    "auto_rig": True,
                    "esqueleto": esqueleto,
                }
            ],
        }

    # humanoide em criatura alada/quadrupede/montaria -> B24
    for tipo_ruim in ("criatura_alada", "criatura_quadrupede", "montaria"):
        with pytest.raises(ForgeError) as exc:
            spec.preparar(_doc(tipo_ruim, "godot-humanoid@1"))
        assert any(e.get("regra") == "B24" for e in exc.value.detalhes["erros"])

    # criatura em personagem_humanoide -> B24
    with pytest.raises(ForgeError) as exc2:
        spec.preparar(_doc("personagem_humanoide", "quadruped@1"))
    assert any(e.get("regra") == "B24" for e in exc2.value.detalhes["erros"])

    # D-02: "criatura" generico + esqueleto humanoide explicito e valido (mob bipede)
    prep, _perfil, _avisos = spec.preparar(_doc("criatura", "godot-humanoid-aa@1"))
    assert prep["lote"][0]["esqueleto"] == "godot-humanoid-aa@1"


def test_topologia_e_g1_alpha_cards_vs_t_edges_e_colisao(tmp_path):
    # Card plano aberto: 2 triangulos formando um quad (5 bordas: 4 externas n==1, 1 diagonal n==2)
    quad_glb = _glb_minimo(
        [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.5, 1.0, 0.0), (0.0, 1.0, 0.0)],
        [(0, 1, 2), (0, 2, 3)],
    )
    gltf_q, bin_q = (
        lambda p: (p.write_bytes(quad_glb), qc.ler_glb_bin(p))[1]
    )(tmp_path / "card.glb")
    topo_q = qc.topologia(gltf_q, bin_q)
    assert topo_q["bordas_abertas"] == 4
    assert topo_q["arestas_t"] == 0
    assert topo_q["nao_manifold"] == 4

    perfil = profiles.carregar("godot4-aa")
    res = {
        "medidas": {"nao_manifold": 4, "degeneradas": 0, "partes_colisao": 0},
        "arquivos": [{"caminho": "card.glb", "papel": "mesh", "nivel": 0, "triangulos": 2}],
        "licenca": {"modelo": "MIT", "uso_comercial": True},
    }
    item_sem = {
        "id": "prop.card.01",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 100,
        "colisao": "none",
        "alpha_cards": False,
    }
    rel_sem = qc.verificar(item_sem, perfil, tmp_path, res)
    g1_sem = next(g for g in rel_sem["gates"] if g["id"] == "G1")
    assert g1_sem["status"] == "falhou"

    item_com = {**item_sem, "alpha_cards": True}
    rel_com = qc.verificar(item_com, perfil, tmp_path, res)
    g1_com = next(g for g in rel_com["gates"] if g["id"] == "G1")
    assert g1_com["status"] == "ok", g1_com

    # Aresta-T (3 triangulos compartilhando a mesma aresta 0-1) continua reprovando mesmo com alpha_cards=True!
    t_edge_glb = _glb_minimo(
        [
            (0.0, 0.0, 0.0),
            (0.5, 0.0, 0.0),
            (0.25, 1.0, 0.0),
            (0.25, 0.5, 0.5),
            (0.25, 0.5, -0.5),
        ],
        [(0, 1, 2), (0, 1, 3), (0, 1, 4)],
    )
    (tmp_path / "tedge.glb").write_bytes(t_edge_glb)
    res_t = {
        "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0},
        "arquivos": [{"caminho": "tedge.glb", "papel": "mesh", "nivel": 0, "triangulos": 3}],
        "licenca": {"modelo": "MIT", "uso_comercial": True},
    }
    rel_t = qc.verificar(item_com, perfil, tmp_path, res_t)
    g1_t = next(g for g in rel_t["gates"] if g["id"] == "G1")
    assert g1_t["status"] == "falhou"
    assert g1_t["medido"]["arestas_t"] == 1

    # G7 colisor aberto NUNCA passa mesmo com alpha_cards=True
    (tmp_path / "card_col.glb").write_bytes(quad_glb)
    res_col = {
        "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 1},
        "arquivos": [
            {"caminho": "card.glb", "papel": "mesh", "nivel": 0, "triangulos": 2},
            {"caminho": "card_col.glb", "papel": "colisor", "partes": 1},
        ],
        "licenca": {"modelo": "MIT", "uso_comercial": True},
    }
    rel_col = qc.verificar({**item_com, "colisao": "convex"}, perfil, tmp_path, res_col)
    g7 = next(g for g in rel_col["gates"] if g["id"] == "G7")
    assert g7["status"] == "falhou"


def test_g9_ultra_aplica_teto_parte_ultra():
    raa = profiles.carregar("roblox-aa-80")
    assert raa["validacao"]["triangulos_por_parte_max_ultra"] == 18000
    assert profiles.limite_tri_qualidade(raa, "mapa_setor", "ultra") == 120000


def test_g11_orcamento_cena_aprovado_e_reprovado():
    ok_res = qc.verificar_g11_orcamento_cena(
        [
            {
                "id": "wall.01",
                "tris": 10000,
                "quantidade_cena": 4,
                "mesh_key": "wall",
                "material_key": "stone",
                "skinned": False,
                "texturas": [{"id": "stone_col", "px": 2048, "canais": 4}],
            },
            {
                "id": "mob.01",
                "tris": 2000,
                "quantidade_cena": 50,
                "mesh_key": "mob",
                "material_key": "mob_mat",
                "skinned": False,
                "texturas": [{"id": "mob_col", "px": 1024, "canais": 4}],
            },
        ],
        limite_cena={"triangulos_max": 400000, "draw_calls_max": 400, "vram_mb_max": 200},
    )
    assert ok_res["status"] == "ok"
    assert ok_res["codigo"] is None
    assert ok_res["medido"]["triangulos_cena"] == 140000
    assert ok_res["medido"]["draw_calls_estimados"] == 2

    fail_tris = qc.verificar_g11_orcamento_cena(
        [{"id": "boss", "tris": 50000, "quantidade_cena": 10}],
        limite_cena={"triangulos_max": 400000, "draw_calls_max": 400, "vram_mb_max": 200},
    )
    assert fail_tris["status"] == "falhou"
    assert fail_tris["codigo"] == "FORGE-E-QC-SCENE"

    fail_vram = qc.verificar_g11_orcamento_cena(
        [
            {
                "id": f"tex_{i}",
                "tris": 100,
                "quantidade_cena": 1,
                "texturas": [{"id": f"t_{i}", "px": 4096, "canais": 4}],
            }
            for i in range(10)
        ],
        limite_cena={"triangulos_max": 400000, "draw_calls_max": 400, "vram_mb_max": 200},
    )
    assert fail_vram["status"] == "falhou"
    assert fail_vram["codigo"] == "FORGE-E-QC-SCENE"


def test_exemplo_lote_13_validate_e_plan_scene_budget(capsys, monkeypatch):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("FORGE3D_ROOT", raising=False)
    monkeypatch.delenv("FORGE3D_HOME", raising=False)
    lote13 = RAIZ / "examples" / "lote_13_scene_budget_aa.yaml"
    assert main(["validate", str(lote13)]) == 0
    capsys.readouterr()

    assert main(["plan", str(lote13), "--scene-budget", "--json"]) == 0
    rel = json.loads(capsys.readouterr().out)
    assert rel["orcamento_cena"]["status"] == "ok"
    assert rel["orcamento_cena"]["medido"]["triangulos_cena"] <= 400000


def test_pipeline_g11_bloqueia_publicacao_quando_estoura_orcamento(tmp_path, monkeypatch):
    """I3 + I5: se Gate G11 reprovar, ZERO arquivos sao publicados no destino."""
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "cfg" / "config.yaml"))

    destino = tmp_path / "saida_g11"
    from forge3d import config as cfg_mod, doctor as doc_mod

    cfg_mod.adicionar(tmp_path)
    monkeypatch.setattr(doc_mod, "exigir", lambda _checks: None)

    glb_ok = _cubo_fechado_glb(altura=1.0)

    class _BrutoStub:
        def __init__(self, d: Path):
            self.dir = d
            self.meta = {}

    class _ProvStub:
        nome = "blocky"
        versao = "0.9.0"
        determinism = "D1"
        usa_gpu = False
        licenca = {"modelo": "MIT", "uso_comercial": True, "notice": "stub"}

        def preflight(self):
            return True, "ok"

        def custo(self, _item, _perfil):
            return {"segundos_estimados": 0.1, "vram_mb": 0}

        def gerar(self, _item, _perfil, staging: Path):
            return _BrutoStub(staging)

    monkeypatch.setattr("forge3d.providers.obter", lambda _rota: _ProvStub())

    def _fake_post(job: dict) -> dict:
        out_dir = Path(job["saida_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        nome = job["nome_arquivo"]
        (out_dir / nome).write_bytes(glb_ok)
        return {
            "ok": True,
            "arquivos": [{"caminho": nome, "papel": "mesh", "nivel": 0, "triangulos": 12}],
            "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0},
        }

    monkeypatch.setattr("forge3d.post.executar", _fake_post)

    # Forca verificar() de G1..G10 a reportar 5000 tris por item * 100 copias = 500k > 400k!
    orig_verificar = qc.verificar

    def _fake_verificar(item, perfil, pasta, resultado, **kwargs):
        rel = orig_verificar(item, perfil, pasta, resultado, **kwargs)
        rel["medidas"]["triangulos"] = 5000
        return rel

    monkeypatch.setattr(qc, "verificar", _fake_verificar)

    chamadas_publicar: list[str] = []
    orig_publicar = publish.publicar

    def _spy_publicar(*args, **kwargs):
        chamadas_publicar.append("called")
        return orig_publicar(*args, **kwargs)

    monkeypatch.setattr(publish, "publicar", _spy_publicar)

    lote = tmp_path / "lote_over.yaml"
    lote.write_text(
        yaml.safe_dump(
            {
                "schema": "forge3d/spec@6",
                "projeto": "citadel_test",
                "perfil": "godot4-aa",
                "destino_exportacao": str(destino),
                "orcamento_cena": {
                    "triangulos_max": 400000,
                    "draw_calls_max": 400,
                    "vram_mb_max": 200,
                },
                "lote": [
                    {
                        "id": "prop.over.01",
                        "tipo": "prop_estatico",
                        "rota": "blocky",
                        "altura_metros": 1.0,
                        "pivot": "base",
                        "colisao": "none",
                        "quantidade_cena": 100,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    relatorio, codigo = pipeline.executar(lote)
    assert codigo == EXIT_QC
    assert relatorio["orcamento_cena"]["status"] == "falhou"
    assert relatorio["orcamento_cena"]["codigo"] == "FORGE-E-QC-SCENE"
    assert chamadas_publicar == []
    assert not destino.exists() or list(destino.iterdir()) == []
    assert relatorio["artifacts"] == []


def test_verify_aceita_manifest_v6_com_alpha_cards_e_retrocompatibilidade(tmp_path):
    quad_glb = _glb_minimo(
        [(-0.25, 0.0, 0.0), (0.25, 0.0, 0.0), (0.25, 1.0, 0.0), (-0.25, 1.0, 0.0)],
        [(0, 1, 2), (0, 2, 3)],
    )
    glb_path = tmp_path / "card.glb"
    glb_path.write_bytes(quad_glb)
    perfil = profiles.carregar("godot4-aa")
    item = {
        "id": "prop.foliage.01",
        "tipo": "prop_estatico",
        "rota": "blocky",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 500,
        "colisao": "none",
        "alpha_cards": True,
        "qualidade": "hero",
        "quantidade_cena": 4,
    }
    res = {
        "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0},
        "arquivos": [
            {
                "caminho": "card.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 2,
                "sha256": canonical.sha256_arquivo(glb_path),
                "bytes": glb_path.stat().st_size,
            }
        ],
        "licenca": {"modelo": "MIT", "uso_comercial": True, "notice": "teste"},
        "determinism": "D1",
    }
    rel_qc = qc.verificar(item, perfil, tmp_path, res, escala_saida=1.0)
    assert rel_qc["aprovado"] is True, rel_qc["gates"]

    man = publish.montar_manifesto(
        item=item,
        spec_doc={"projeto": "demo", "perfil": "godot4-aa", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4-aa",
        perfil=perfil,
        provider={"nome": "blocky", "versao": "0.9.0", "determinism": "D1"},
        resultado=res,
        relatorio_qc=rel_qc,
        licenca={"modelo": "MIT", "uso_comercial": True, "notice": "teste"},
        run_id="run-v6",
    )
    assert man["schema"] == "forge3d/manifest@6"
    assert man["alpha_cards"] is True
    assert man["qualidade"] == "hero"
    assert man["quantidade_cena"] == 4
    (tmp_path / "prop.foliage.01.manifest.json").write_text(json.dumps(man), encoding="utf-8")

    man_ex = json.loads((RAIZ / "examples" / "manifest.exemplo.v6.json").read_text(encoding="utf-8"))
    schema_m6 = json.loads((RAIZ / "schemas" / "manifest.v6.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(man_ex, schema_m6)

    rel_ver = verify.verificar(tmp_path)
    assert rel_ver["ok"] is True, rel_ver["erros"]


def test_g2_e_g9_com_godot_humanoid_aa_e_lod_alpha_cards(tmp_path):
    """G2 aceita prefixo godot-humanoid-aa@1 e G9 respeita alpha_cards em LODs + teto ultra."""
    perfil = profiles.carregar("godot4-aa")
    # Malha 2-triangulos aberta (card) para LOD0 e 1-triangulo para LOD1
    lod0 = _glb_minimo(
        [(-0.25, 0.0, 0.0), (0.25, 0.0, 0.0), (0.25, 1.0, 0.0), (-0.25, 1.0, 0.0)],
        [(0, 1, 2), (0, 2, 3)],
    )
    lod1 = _glb_minimo(
        [(-0.25, 0.0, 0.0), (0.25, 0.0, 0.0), (0.0, 1.0, 0.0)],
        [(0, 1, 2)],
    )
    (tmp_path / "m.glb").write_bytes(lod0)
    (tmp_path / "m_LOD1.glb").write_bytes(lod1)

    item = {
        "id": "hero.hair.01",
        "tipo": "prop_estatico",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 500,
        "qualidade": "ultra",
        "esqueleto": "godot-humanoid-aa@1",
        "alpha_cards": True,
        "colisao": "none",
    }
    res = {
        "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0},
        "arquivos": [
            {"caminho": "m.glb", "papel": "mesh", "nivel": 0, "triangulos": 2},
            {"caminho": "m_LOD1.glb", "papel": "lod", "nivel": 1, "triangulos": 1},
        ],
        "licenca": {"modelo": "MIT", "uso_comercial": True},
    }
    rel = qc.verificar(item, perfil, tmp_path, res)
    assert rel["aprovado"] is True, rel["gates"]

    est = plan.estimar_orcamento_cena(
        {
            "schema": "forge3d/spec@6",
            "lote": [
                {
                    "id": "a.b",
                    "tipo": "prop_estatico",
                    "qualidade": "ultra",
                    "limite_triangulos": 16000,
                    "quantidade_cena": 2,
                    "material": "pbr",
                }
            ],
        },
        perfil,
    )
    assert est["status"] == "ok"
    assert est["medido"]["triangulos_cena"] == 32000


def test_exemplos_lote_14_e_15_validate_e_obelisk_manifold_suave(tmp_path, capsys):
    """R1 + V3: lotes v09_aa_godot e v09_aa_roblox validam no repo e obelisco tem gema suave sem intersecao."""
    from forge3d import vault

    for nome_lote in ("lote_14_v09_aa_godot.yaml", "lote_15_v09_aa_roblox.yaml"):
        caminho = RAIZ / "examples" / nome_lote
        assert caminho.is_file(), f"R1: spec ausente em examples/: {caminho}"
        assert main(["validate", str(caminho), "--json"]) == 0
        out_val = json.loads(capsys.readouterr().out)
        assert out_val["ok"] is True

    ob_path = vault.construir_obelisk_aa_manifold_glb(tmp_path / "runestone_obelisk.glb")
    gltf, blob = qc.ler_glb_bin(ob_path)
    topo = qc.topologia(gltf, blob)
    assert topo["nao_manifold"] == 0
    assert topo["degeneradas"] == 0
    assert topo["triangulos"] >= 1000
    fac = qc._inspecionar_facetamento_organico(gltf, blob)
    assert fac["facetada"] is False

    pr = gltf["meshes"][0]["primitives"][0]
    pos = qc._accessor(gltf, blob, pr["attributes"]["POSITION"])
    uvs = qc._accessor(gltf, blob, pr["attributes"]["TEXCOORD_0"])
    ys_fuste = [p[1] for p, u in zip(pos, uvs) if 0.34 <= u[0] <= 0.67]
    ys_gema = [p[1] for p, u in zip(pos, uvs) if u[0] > 0.67]
    assert ys_fuste and ys_gema
    assert max(ys_fuste) < min(ys_gema), (
        f"V3: coroa do obelisco ({max(ys_fuste):.4f}) intercepta gema ({min(ys_gema):.4f})"
    )

