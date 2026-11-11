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
    """D66: `idle` tem gerador (sem aviso); clipe sem gerador avisa e nao reprova."""
    doc = spec.carregar_arquivo(EXEMPLO)
    doc["lote"][2]["animacoes_base"] = ["backflip"]
    _spec, _perfil, avisos = spec.preparar(doc)
    assert any(a["codigo"] == "FORGE-W-ANIM" and "backflip" in a["mensagem"] for a in avisos)

    doc = spec.carregar_arquivo(EXEMPLO)
    doc["lote"][2]["animacoes_base"] = ["idle"]
    _spec, _perfil, avisos = spec.preparar(doc)
    assert not [a for a in avisos if a["codigo"] == "FORGE-W-ANIM"], avisos


def _spec_mesh() -> dict:
    return {
        "schema": "forge3d/spec@1",
        "projeto": "demo",
        "perfil": "godot4",
        "destino_exportacao": "~/.local/state/forge3d/saida/mesh",
        "lote": [
            {
                "id": "weapon.axe.ice.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "prompt": "machado de gelo",
                "altura_metros": 1.2,
                "seed": 20261110,
            }
        ],
    }


def test_rota_mesh_bloqueia_sem_venv_com_razao_acionavel(monkeypatch, tmp_path):
    """Sem a venv de i23d o item e bloqueado com motivo nomeado, nao "nao implementado"."""
    from forge3d import plan

    monkeypatch.setenv("FORGE3D_VENV_I23D", str(tmp_path / "venv-ausente"))
    spec_doc, perfil, _avisos = spec.preparar(_spec_mesh())
    tarefas = plan.montar(spec_doc, perfil, lambda chave: False)
    tarefa = tarefas[0]
    assert tarefa["estado_previsto"] == "bloqueada"
    assert tarefa["provedor"]["nome"] == "mesh"
    assert tarefa["estimativa"]["vram_mb"] >= 3000
    assert "venv" in tarefa["razao"].lower(), tarefa["razao"]
    assert "implementad" not in tarefa["razao"]


def test_modelo_mesh_fora_da_allowlist_e_recusado(monkeypatch):
    from forge3d.providers import obter

    monkeypatch.setenv("FORGE3D_MODELO_MESH", "hunyuan3d")
    pronto, razao = obter("mesh").preflight()
    assert pronto is False
    assert "allowlist" in razao.lower() or "licen" in razao.lower()


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
    from forge3d.profiles import FRACAO_EMPUNHADURA
    from forge3d.providers import blocky

    caixas = blocky._caixas("prop_equipavel", 1.10, {})
    pivos = blocky._pivos(caixas, "prop_equipavel")
    x, y, z = pivos["empunhadura"]
    # D58: a regra virou fracao fixa da altura (20%), nao o centro da caixa 'cabo'
    assert abs(z - FRACAO_EMPUNHADURA * 1.10) < 1e-6, z
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

def _spec_v2(**extra) -> dict:
    item = {
        "id": "personagem.sentinel.corpo.01",
        "tipo": "personagem_humanoide",
        "rota": "blocky",
        "parte": "corpo",
        "prompt": "corpo",
        "altura_metros": 1.85,
        "auto_rig": True,
    }
    item.update(extra)
    return {
        "schema": "forge3d/spec@2",
        "projeto": "demo",
        "perfil": "godot4",
        "destino_exportacao": "~/.local/state/forge3d/saida/kit",
        "lote": [item],
    }


def test_spec_v2_parte_valida():
    doc = _spec_v2()
    spec_doc, _perfil, avisos = spec.preparar(doc)
    assert spec_doc["lote"][0]["parte"] == "corpo"
    assert avisos == []


def test_spec_v2_parte_arma_com_tipo_errado_falha_b12():
    doc = _spec_v2(parte="arma", tipo="personagem_humanoide", auto_rig=False)
    with pytest.raises(ForgeError) as exc:
        spec.preparar(doc)
    assert any(e.get("regra") == "B12" for e in exc.value.detalhes["erros"])


def test_spec_v2_capa_com_auto_rig_falha_b13():
    doc = _spec_v2(parte="capa", altura_metros=1.20, auto_rig=True)
    with pytest.raises(ForgeError) as exc:
        spec.preparar(doc)
    assert any(e.get("regra") == "B13" for e in exc.value.detalhes["erros"])


def test_spec_v1_nao_aceita_parte():
    doc = _spec_v2()
    doc["schema"] = "forge3d/spec@1"
    with pytest.raises(ForgeError) as exc:
        spec.preparar(doc)
    assert exc.value.codigo == "FORGE-E-SPEC"

def test_rota_mesh_sem_vram_bloqueia_como_recurso_exit_6(monkeypatch, tmp_path):
    """D11/I6: falta de VRAM e recurso (exit 6), nao falha de provider (exit 5)."""
    from forge3d import plan
    from forge3d.providers import mesh

    monkeypatch.setenv("FORGE3D_VENV_I23D", str(tmp_path / "venv"))
    monkeypatch.setattr(mesh, "_diagnostico", lambda: {"ok": True, "torch": "2.4.1", "cuda": True})
    monkeypatch.setattr(mesh, "_vram_livre_mb", lambda: 100)
    spec_doc, perfil, _avisos = spec.preparar(_spec_mesh())
    tarefa = plan.montar(spec_doc, perfil, lambda chave: False)[0]
    assert tarefa["estado_previsto"] == "bloqueada"
    assert tarefa["codigo"] == "FORGE-E-RECURSO"
    assert "VRAM" in tarefa["razao"]
