"""Testes do Contrato por Request (Request Contract) e Isolamento de Assets.

Valida:
1. Schema spec@2 e spec@3 aceitando 'requisicao'.
2. Regra B22 e deteccao de input adulterado (FORGE-E-INPUT-TAMPERED).
3. Isolamento de cache com flag no_cache e isolamento='estrito'.
4. Expurgacao segura de orfaos no destino com clean_dest / limpar_destino=True.
5. CLI e MCP server com parametros no_cache e clean_dest.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from forge3d import mcp_server, paths, pipeline, spec
from forge3d.canonical import sha256_arquivo
from forge3d.errors import EXIT_SPEC, ForgeError


@pytest.fixture(autouse=True)
def _isolar_estado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge3d_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge3d_config"))


@pytest.fixture
def base_spec_doc(tmp_path: Path) -> dict:
    destino = paths.dir_saida() / f"req_{tmp_path.name}"
    destino.mkdir(parents=True, exist_ok=True)
    uid = uuid.uuid4().hex[:8]
    return {
        "schema": "forge3d/spec@3",
        "projeto": "bench_request",
        "perfil": "godot4",
        "destino_exportacao": str(destino),
        "estilo_global": "blocky_voxel",
        "lote": [
            {
                "id": f"item.teste.{uid}",
                "tipo": "prop_estatico",
                "prompt": "caixa de madeira",
                "altura_metros": 1.0,
            }
        ],
    }


def test_schema_requisicao_valido(base_spec_doc: dict):
    doc = dict(base_spec_doc)
    doc["requisicao"] = {
        "id": "req-20261112-test-01",
        "isolamento": "estrito",
        "limpar_destino": True,
    }
    spec_doc, _perfil, avisos = spec.preparar(doc)
    assert spec_doc["requisicao"]["id"] == "req-20261112-test-01"
    assert spec_doc["requisicao"]["isolamento"] == "estrito"
    assert spec_doc["requisicao"]["limpar_destino"] is True


def test_normalizacao_defaults_requisicao(base_spec_doc: dict):
    doc = dict(base_spec_doc)
    doc["requisicao"] = {"id": "req-padrao"}
    spec_doc, _perfil, _ = spec.preparar(doc)
    assert spec_doc["requisicao"]["isolamento"] == "padrao"
    assert spec_doc["requisicao"]["limpar_destino"] is False


def test_base_externa_valida_e_tampered(base_spec_doc: dict, tmp_path: Path):
    img = tmp_path / "entrada.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfakeimagebytes")
    hash_correto = sha256_arquivo(img)

    doc = dict(base_spec_doc)
    doc["requisicao"] = {
        "id": "req-selada",
        "base_externa": {
            "origem": str(img),
            "sha256": hash_correto,
            "tipo": "prop_estatico",
        },
    }
    # Deve validar com sucesso
    spec_doc, _, _ = spec.preparar(doc)
    assert spec_doc["requisicao"]["base_externa"]["sha256"] == hash_correto

    # 1. Arquivo adulterado: hash diverge
    doc_tampered = dict(base_spec_doc)
    doc_tampered["requisicao"] = {
        "id": "req-tampered",
        "base_externa": {
            "origem": str(img),
            "sha256": "sha256:" + "0" * 64,
        },
    }
    with pytest.raises(ForgeError) as exc_info:
        spec.preparar(doc_tampered)
    assert exc_info.value.codigo == "FORGE-E-INPUT-TAMPERED"
    assert exc_info.value.exit_code == EXIT_SPEC

    # 2. Arquivo inexistente
    doc_missing = dict(base_spec_doc)
    doc_missing["requisicao"] = {
        "id": "req-missing",
        "base_externa": {
            "origem": str(tmp_path / "nao_existe.png"),
            "sha256": hash_correto,
        },
    }
    with pytest.raises(ForgeError) as exc_info2:
        spec.preparar(doc_missing)
    assert exc_info2.value.codigo == "FORGE-E-INPUT-TAMPERED"
    assert exc_info2.value.exit_code == EXIT_SPEC


def test_base_externa_conflito_tipo_com_item(base_spec_doc: dict, tmp_path: Path):
    img = tmp_path / "ref.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    h = sha256_arquivo(img)

    doc = dict(base_spec_doc)
    doc["requisicao"] = {
        "id": "req-tipo",
        "base_externa": {
            "origem": str(img),
            "sha256": h,
            "tipo": "criatura",  # Diverge de prop_estatico no item
        },
    }
    doc["lote"][0]["origem"] = str(img)
    with pytest.raises(ForgeError) as exc_info:
        spec.preparar(doc)
    assert exc_info.value.codigo == "FORGE-E-SPEC"
    assert "B22" in str(exc_info.value.detalhes.get("erros", []))


@pytest.mark.blender
def test_isolamento_cache_no_cache_e_estrito(base_spec_doc: dict, tmp_path: Path):
    spec_path = tmp_path / "spec_exec.yaml"
    import yaml

    spec_path.write_text(yaml.dump(base_spec_doc, sort_keys=False), encoding="utf-8")

    # 1. Execucao 1: gera artefato e popula cache
    rel1, cod1 = pipeline.executar(spec_path, plano_apenas=False, publicar_arquivos=True)
    assert cod1 == 0
    assert rel1["itens"][0]["cache_hit"] is False
    assert rel1["itens"][0]["trabalho_executado"] is True

    # 2. Execucao 2 normal: cache hit
    rel2, cod2 = pipeline.executar(spec_path, plano_apenas=False, publicar_arquivos=True)
    assert cod2 == 0
    assert rel2["itens"][0]["cache_hit"] is True
    assert rel2["itens"][0]["trabalho_executado"] is False

    # 3. Execucao 3 com no_cache=True via parametro: ignora cache
    rel3, cod3 = pipeline.executar(
        spec_path, plano_apenas=False, publicar_arquivos=True, no_cache=True
    )
    assert cod3 == 0
    assert rel3["itens"][0]["cache_hit"] is False
    assert rel3["itens"][0]["trabalho_executado"] is True

    # 4. Execucao 4 com isolamento='estrito' no spec: ignora cache automaticamente
    doc_estrito = dict(base_spec_doc)
    doc_estrito["requisicao"] = {"id": "req-estrita", "isolamento": "estrito"}
    spec_path_estrito = tmp_path / "spec_estrito.yaml"
    spec_path_estrito.write_text(yaml.dump(doc_estrito, sort_keys=False), encoding="utf-8")

    rel4, cod4 = pipeline.executar(spec_path_estrito, plano_apenas=False, publicar_arquivos=True)
    assert cod4 == 0
    assert rel4["itens"][0]["cache_hit"] is False
    assert rel4["itens"][0]["trabalho_executado"] is True


@pytest.mark.blender
def test_clean_dest_expurga_orfaos(base_spec_doc: dict, tmp_path: Path):
    destino = Path(base_spec_doc["destino_exportacao"])

    # Simular asset legado previamente existente no destino
    legado_manifest = destino / "personagem.legado.01.manifest.json"
    legado_glb = destino / "personagem.legado.01.glb"
    legado_png = destino / "personagem.legado.01_baseColor.png"
    legado_manifest.write_text(
        json.dumps(
            {
                "asset_id": "personagem.legado.01",
                "files": [
                    {"caminho": "personagem.legado.01.glb"},
                    {"caminho": "personagem.legado.01_baseColor.png"},
                ],
            }
        ),
        encoding="utf-8",
    )
    legado_glb.write_bytes(b"glbfake")
    legado_png.write_bytes(b"pngfake")

    # Arquivo estranho qualquer (nao registrado em nenhum manifesto) NAO deve ser deletado
    estranho = destino / "README.txt"
    estranho.write_text("arquivo pessoal do usuario", encoding="utf-8")
    # Mas artefato de asset solto (sem manifesto, ex. PNG antigo) deve ser purgado para o verify passar
    orfao_png = destino / "orfao_antigo.png"
    orfao_png.write_bytes(b"pngorfao")

    import yaml

    doc_limpeza = dict(base_spec_doc)
    doc_limpeza["requisicao"] = {"id": "req-clean", "limpar_destino": True}
    spec_path = tmp_path / "spec_clean.yaml"
    spec_path.write_text(yaml.dump(doc_limpeza, sort_keys=False), encoding="utf-8")

    rel, cod = pipeline.executar(spec_path, plano_apenas=False, publicar_arquivos=True)
    assert cod == 0
    assert "expurgados" in rel
    assert "personagem.legado.01.manifest.json" in rel["expurgados"]
    assert "personagem.legado.01.glb" in rel["expurgados"]
    assert "personagem.legado.01_baseColor.png" in rel["expurgados"]

    # Manifestos e arquivos legados foram deletados
    assert not legado_manifest.exists()
    assert not legado_glb.exists()
    assert not legado_png.exists()
    assert not orfao_png.exists()
    assert "orfao_antigo.png" in rel["expurgados"]

    # O arquivo estranho que nao pertencia a nenhum manifesto foi preservado
    assert estranho.is_file()

    # O asset do lote atual esta publicado
    item_id = base_spec_doc["lote"][0]["id"]
    assert (destino / f"{item_id}.manifest.json").is_file()


@pytest.mark.blender
def test_mcp_server_no_cache_e_clean_dest(base_spec_doc: dict, tmp_path: Path):
    import yaml

    spec_path = tmp_path / "spec_mcp.yaml"
    spec_path.write_text(yaml.dump(base_spec_doc, sort_keys=False), encoding="utf-8")

    # MCP Plan com no_cache
    resp_plan = mcp_server.processar_mensagem(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "forge3d_plan", "arguments": {"lote": str(spec_path), "no_cache": True}},
        }
    )
    assert resp_plan is not None
    assert resp_plan["result"]["isError"] is False

    # MCP Run com no_cache e clean_dest
    resp_run = mcp_server.processar_mensagem(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "forge3d_run",
                "arguments": {
                    "lote": str(spec_path),
                    "no_cache": True,
                    "clean_dest": True,
                },
            },
        }
    )
    assert resp_run is not None
    assert resp_run["result"]["isError"] is False


@pytest.mark.blender
def test_cli_flags_no_cache_e_clean_dest(base_spec_doc: dict, tmp_path: Path):
    from forge3d.cli import comandos
    import yaml

    spec_path = tmp_path / "spec_cli.yaml"
    spec_path.write_text(yaml.dump(base_spec_doc, sort_keys=False), encoding="utf-8")

    # Testa plan com --no-cache
    ret_plan = comandos.despachar(["plan", str(spec_path), "--no-cache", "--json"])
    assert ret_plan == 0

    # Testa run com --no-cache e --clean-dest
    ret_run = comandos.despachar(["run", str(spec_path), "--no-cache", "--clean-dest", "--json"])
    assert ret_run == 0


def test_isolamento_estrito_rejeita_origem_nao_selada_fora_de_base_externa(
    base_spec_doc: dict, tmp_path: Path
):
    img_base = tmp_path / "base_careca.jpg"
    img_base.write_bytes(b"\xff\xd8\xff\xe0base")
    img_antiga = tmp_path / "espada_antiga.png"
    img_antiga.write_bytes(b"\x89PNG\r\n\x1a\nold")

    doc = dict(base_spec_doc)
    doc["requisicao"] = {
        "id": "req-estrita-limpa",
        "isolamento": "estrito",
        "base_externa": {
            "origem": str(img_base),
            "sha256": sha256_arquivo(img_base),
            "tipo": "personagem_humanoide",
        },
    }
    doc["lote"] = [
        {
            "id": "heroi.base.01",
            "tipo": "personagem_humanoide",
            "prompt": "base careca",
            "altura_metros": 1.72,
            "origem": str(img_base),
        },
        {
            "id": "arma.antiga.01",
            "tipo": "prop_equipavel",
            "prompt": "espada antiga fora do contrato",
            "altura_metros": 1.0,
            "origem": str(img_antiga),
        },
    ]
    with pytest.raises(ForgeError) as exc_info:
        spec.preparar(doc)
    assert exc_info.value.codigo == "FORGE-E-INPUT-TAMPERED"
    assert exc_info.value.exit_code == EXIT_SPEC
    assert exc_info.value.detalhes.get("regra") == "B22"
