"""Migracao de lote entre versoes do contrato (`spec@1`/`@2` -> `spec@3`).

Regra da fase P6: a migracao sobe a versao e canonicaliza alias. Nao inventa valor — lote que o
contrato novo recusa continua recusado, com o motivo do B1-B17.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from forge3d import migrate, spec
from forge3d.cli.main import main
from forge3d.errors import ForgeError

EXEMPLOS = Path(__file__).resolve().parents[1] / "examples"


def _modular_antigo(tmp_path: Path) -> Path:
    """Lote `@2` com rota modular e **sem** o bloco `modular` (o B15 exige)."""
    doc = yaml.safe_load((EXEMPLOS / "lote_10_modular.yaml").read_text(encoding="utf-8"))
    doc["schema"] = "forge3d/spec@2"
    for item in doc["lote"]:
        item.pop("modular", None)
    arq = tmp_path / "modular_sem_bloco.yaml"
    arq.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return arq


def test_lote_01_migra_do_spec_1_para_o_corrente():
    plano = migrate.planejar(EXEMPLOS / "lote_01.yaml")
    assert plano["de"] == "forge3d/spec@1"
    assert plano["para"] == "forge3d/spec@3"
    assert plano["valido"], plano["erros"]
    assert plano["mudancas"] == [
        {"campo": "schema", "de": "forge3d/spec@1", "para": "forge3d/spec@3"}
    ]
    assert "schema: forge3d/spec@3" in plano["texto"]


def test_migracao_preserva_comentarios_e_campo_do_spec_2():
    plano = migrate.planejar(EXEMPLOS / "lote_03_kit.yaml")
    assert plano["de"] == "forge3d/spec@2"
    assert plano["valido"], plano["erros"]
    assert plano["texto"].lstrip().startswith("#")  # comentario preservado
    assert "parte: corpo" in plano["texto"]


def test_lote_no_contrato_corrente_nao_muda():
    plano = migrate.planejar(EXEMPLOS / "lote_10_modular.yaml")
    assert plano["mudancas"] == []
    assert plano["de"] == plano["para"] == "forge3d/spec@3"


def test_alias_legado_e_canonicalizado(tmp_path):
    doc = yaml.safe_load((EXEMPLOS / "lote_01.yaml").read_text(encoding="utf-8"))
    doc["estilo_global"] = "minecraft_bedrock"
    arq = tmp_path / "alias.yaml"
    arq.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")

    plano = migrate.planejar(arq)
    assert plano["valido"], plano["erros"]
    assert "minecraft_bedrock" not in plano["texto"]
    assert "blocky_voxel" in plano["texto"]
    assert {"campo": "estilo_global", "de": "minecraft_bedrock", "para": "blocky_voxel"} in plano[
        "mudancas"
    ]


def test_modular_sem_bloco_nao_migra(tmp_path):
    plano = migrate.planejar(_modular_antigo(tmp_path))
    assert plano["valido"] is False
    assert any("B15" in e or "modular" in e for e in plano["erros"]), plano["erros"]


def test_gravar_saida_gera_lote_aceito_pelo_contrato(tmp_path):
    plano = migrate.planejar(EXEMPLOS / "lote_01.yaml")
    destino = tmp_path / "lote.v3.yaml"
    escrito = migrate.gravar(plano, saida=destino)
    assert escrito == destino and destino.is_file()
    assert yaml.safe_load(destino.read_text(encoding="utf-8"))["schema"] == "forge3d/spec@3"
    spec.preparar(spec.carregar_arquivo(destino))  # schema + B1-B17


def test_em_lugar_sobrescreve_o_proprio_lote(tmp_path):
    copia = tmp_path / "lote.yaml"
    copia.write_text((EXEMPLOS / "lote_01.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    plano = migrate.planejar(copia)
    migrate.gravar(plano, em_lugar=True)
    assert "schema: forge3d/spec@3" in copia.read_text(encoding="utf-8")


def test_recusa_sobrescrever_o_original_sem_em_lugar(tmp_path):
    copia = tmp_path / "lote.yaml"
    copia.write_text((EXEMPLOS / "lote_01.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    plano = migrate.planejar(copia)
    with pytest.raises(ForgeError):
        migrate.gravar(plano, saida=copia)


def test_cli_migrate_json_grava_e_reporta(tmp_path, capsys):
    destino = tmp_path / "out.yaml"
    rc = main(["migrate", str(EXEMPLOS / "lote_01.yaml"), "--saida", str(destino), "--json"])
    assert rc == 0
    relatorio = json.loads(capsys.readouterr().out)
    assert relatorio["comando"] == "migrate"
    assert relatorio["de"] == "forge3d/spec@1"
    assert relatorio["para"] == "forge3d/spec@3"
    assert relatorio["escrito"] == str(destino)
    assert relatorio["valido"] is True


def test_cli_migrate_invalido_sai_2(tmp_path, capsys):
    rc = main(["migrate", str(_modular_antigo(tmp_path))])
    assert rc == 2
    assert "FORGE-E-SPEC" in capsys.readouterr().err
