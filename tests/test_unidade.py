"""Testes rapidos (sem Blender): contrato, normalizacao, chave de cache, guardas de caminho."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge3d import canonical, config, paths, spec
from forge3d.errors import ForgeError

RAIZ = Path(__file__).resolve().parents[1]
EXEMPLO = RAIZ / "examples" / "lote_01.yaml"


@pytest.fixture()
def em_sandbox(tmp_path, monkeypatch):
    """Isola paths.* sem tocar no HOME real do operador."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.delenv("FORGE3D_HOME", raising=False)
    monkeypatch.delenv("FORGE3D_CONFIG", raising=False)
    return home


# ---------------------------------------------------------------- contrato


def test_spec_exemplo_valida():
    doc = spec.carregar_arquivo(EXEMPLO)
    spec_doc, perfil, avisos = spec.preparar(doc)
    assert len(spec_doc["lote"]) == 3
    assert perfil["_nome"] == "godot4"
    assert avisos == []


def test_alias_legado_normaliza_para_canonico():
    doc = {
        "schema": "forge3d/spec@1",
        "projeto": "demo",
        "perfil": "godot4",
        "destino_exportacao": "~/.local/state/forge3d/saida/x",
        "estilo_global": "minecraft_bedrock",
        "lote": [{"id": "a.b", "tipo": "prop_estatico", "prompt": "caixa", "altura_metros": 1.0}],
    }
    spec_doc, _perfil, avisos = spec.preparar(doc)
    assert spec_doc["estilo_global"] == "blocky_voxel"
    assert any(a["codigo"] == "FORGE-W-ALIAS" for a in avisos)
    assert spec_doc["lote"][0]["rota"] == "blocky"


def test_spec_altura_negativa_falha_com_exit_2():
    doc = spec.carregar_arquivo(EXEMPLO)
    doc["lote"][0]["altura_metros"] = -1
    with pytest.raises(ForgeError) as exc:
        spec.preparar(doc)
    assert exc.value.exit_code == 2
    assert exc.value.codigo == "FORGE-E-SPEC"


def test_mesh_sem_seed_falha():
    doc = {
        "schema": "forge3d/spec@1",
        "projeto": "demo",
        "perfil": "godot4",
        "destino_exportacao": "~/.local/state/forge3d/saida/x",
        "lote": [
            {
                "id": "a.b",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "prompt": "espada",
                "altura_metros": 1.0,
            }
        ],
    }
    with pytest.raises(ForgeError) as exc:
        spec.preparar(doc)
    assert exc.value.exit_code == 2


def test_id_duplicado_falha_regra_b1():
    doc = spec.carregar_arquivo(EXEMPLO)
    doc["lote"][1]["id"] = doc["lote"][0]["id"]
    with pytest.raises(ForgeError) as exc:
        spec.preparar(doc)
    assert any(e.get("regra") == "B1" for e in exc.value.detalhes["erros"])


def test_lod_fora_de_ordem_falha_regra_b4():
    doc = spec.carregar_arquivo(EXEMPLO)
    doc["lote"][0]["lod"] = [100, 50, 80]
    with pytest.raises(ForgeError) as exc:
        spec.preparar(doc)
    assert any(e.get("regra") == "B4" for e in exc.value.detalhes["erros"])


def test_animacoes_base_gera_aviso_nao_erro():
    doc = spec.carregar_arquivo(EXEMPLO)
    doc["lote"][2]["animacoes_base"] = ["idle"]
    _spec, _perfil, avisos = spec.preparar(doc)
    assert any(a["codigo"] == "FORGE-W-ANIM" for a in avisos)


# ---------------------------------------------------------------- cache


def _item_minimo(**extra) -> dict:
    base = {
        "id": "a.b",
        "tipo": "prop_estatico",
        "rota": "blocky",
        "prompt": "caixa",
        "altura_metros": 1.0,
    }
    base.update(extra)
    return base


def test_chave_de_cache_muda_com_versao_do_provider():
    perfil = {"perfil": "godot4"}
    item = _item_minimo()
    k1 = canonical.chave_cache(item, "0.1.0", {"blocky": "0.1.0"}, perfil)
    k2 = canonical.chave_cache(item, "0.1.0", {"blocky": "0.1.1"}, perfil)
    k3 = canonical.chave_cache(item, "0.1.1", {"blocky": "0.1.0"}, perfil)
    assert len({k1, k2, k3}) == 3


def test_chave_de_cache_independe_da_ordem_das_chaves():
    perfil = {"perfil": "godot4"}
    a = canonical.chave_cache({"id": "a.b", "tipo": "x"}, "1", {}, perfil)
    b = canonical.chave_cache({"tipo": "x", "id": "a.b"}, "1", {}, perfil)
    assert a == b


def test_hash_curto_e_estavel():
    assert canonical.hash_curto("abc") == canonical.hash_curto("abc")
    assert canonical.hash_curto("abc") != canonical.hash_curto("abd")


# ---------------------------------------------------------------- guardas


def test_i12_recusa_mnt_e_unc():
    for caminho in ("/mnt/c/jogos/assets", "\\\\wsl.localhost\\Ubuntu\\home\\x"):
        with pytest.raises(ForgeError) as exc:
            config.validar_caminho(config.normalizar(caminho))
        assert exc.value.codigo == "FORGE-E-PATH"


def test_i13_destino_fora_da_allowlist_falha(em_sandbox):
    alvo = em_sandbox.parent / "fora" / "assets"
    with pytest.raises(ForgeError) as exc:
        config.validar_destino(alvo)
    assert exc.value.exit_code == 2
    assert exc.value.codigo == "FORGE-E-DESTINO"


def test_sandbox_do_proprio_forge3d_e_sempre_permitido(em_sandbox):
    permitido = config.validar_destino(paths.dir_saida() / "x")
    assert permitido.is_absolute()


def test_allowlist_add_e_remove(em_sandbox):
    alvo = em_sandbox.parent / "projeto" / "assets"
    config.adicionar(alvo)
    assert config.validar_destino(alvo) == alvo.resolve()
    assert config.remover(alvo) is True
    with pytest.raises(ForgeError):
        config.validar_destino(alvo)


# ---------------------------------------------------------------- atlas


def test_atlas_e_potencia_de_dois_para_todos_os_tamanhos(tmp_path):
    from forge3d.providers import blocky

    for n in (1, 2, 3, 5, 6, 9, 17):
        caixas = [
            {"nome": f"c{i}", "min": [0, 0, 0], "max": [1, 1, 1], "cor": "#8899aa", "padrao": "chapa"}
            for i in range(n)
        ]
        destino = tmp_path / f"n{n}"
        destino.mkdir(parents=True, exist_ok=True)
        _nome, tam = blocky._atlas(caixas, destino)
        assert tam & (tam - 1) == 0, f"atlas {tam} nao e potencia de 2 (n={n})"
        assert all("uv" in c and "uv_topo" in c for c in caixas)


def test_pivos_de_espada_ficam_na_empunhadura():
    from forge3d.providers import blocky

    caixas = blocky._caixas("prop_equipavel", 1.10, {})
    pivos = blocky._pivos(caixas, "prop_equipavel")
    x, y, z = pivos["empunhadura"]
    assert abs(z - 0.11) < 0.02, z  # centro do cabo, nao a base nem a ponta
    assert pivos["base"][2] == 0.0


def test_bruto_declarado_pelo_provider_e_json_canonico(tmp_path):
    from forge3d.providers.blocky import BlockyProvider

    item = _item_minimo(altura_metros=0.5)
    bruto = BlockyProvider().gerar(item, {"perfil": "godot4"}, tmp_path)
    dados = json.loads((tmp_path / "modelo.json").read_text(encoding="utf-8"))
    assert dados["schema"] == "forge3d/bruto-blocky@1"
    assert dados["altura_m"] == 0.5
    assert (tmp_path / "atlas.png").is_file()
    assert bruto.determinism == "D1"
