"""`verify --only` (I8/I10) e as chaves de topo do `doctor --json` (I7/I9).

O `--only` recorta o veredito: `manifesto` nao abre o glb nem confere hash; `escala`/`pivo`
reexecutam o G2 e devolvem a medida; token desconhecido e erro de spec (exit 2).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge3d import doctor, publish
from forge3d.cli.main import main
from forge3d.errors import ForgeError

RAIZ = Path(__file__).resolve().parents[1]
EXEMPLO = json.loads((RAIZ / "examples/manifest.exemplo.v3.json").read_text(encoding="utf-8"))


def _destino(tmp_path: Path, mutar=None) -> Path:
    """Destino com um manifesto valido; sem arquivos, para provar o que o `--only` NAO faz."""
    man = json.loads(json.dumps(EXEMPLO))
    if mutar is not None:
        mutar(man)
    destino = tmp_path / "destino"
    destino.mkdir()
    (destino / f"{man['asset_id']}.manifest.json").write_text(
        json.dumps(man, ensure_ascii=False), encoding="utf-8"
    )
    return destino


def test_only_manifesto_em_manifesto_completo(tmp_path):
    relatorio = publish.verificar(_destino(tmp_path), only="manifesto")
    assert relatorio["ok"] is True, relatorio["erros"]
    assert relatorio["faltando"] == []
    assert relatorio["total"] == 1


def test_only_manifesto_nao_le_glb_nem_confere_hash(tmp_path):
    """O destino nao tem nenhum dos arquivos listados no manifesto: `manifesto` ainda passa."""
    relatorio = publish.verificar(_destino(tmp_path), only="manifesto")
    assert relatorio["ok"] is True, relatorio["erros"]
    assert all(item["qc_reexecutado"] is None for item in relatorio["itens"])


def test_only_manifesto_aponta_proveniencia_vazia(tmp_path):
    def sem_notice(man: dict) -> None:
        man["licenca"]["notice"] = ""

    relatorio = publish.verificar(_destino(tmp_path, sem_notice), only="manifesto")
    assert relatorio["ok"] is False
    assert {"manifesto": "weapon.sword.fire.01.manifest.json", "campo": "licenca.notice"} in relatorio[
        "faltando"
    ]


def test_aspecto_desconhecido_e_erro_de_spec():
    with pytest.raises(ForgeError) as exc:
        publish._pedidos_verificar("escala,xpto")
    assert exc.value.codigo == "FORGE-E-SPEC"


def test_aspectos_validos_sao_normalizados():
    assert publish._pedidos_verificar(" Escala , PIVO ") == {"escala", "pivo"}
    assert publish._pedidos_verificar(None) is None


def test_cli_verify_only_manifesto_json(tmp_path, capsys):
    destino = _destino(tmp_path)
    assert main(["verify", str(destino), "--only=manifesto", "--json"]) == 0
    relatorio = json.loads(capsys.readouterr().out)
    assert relatorio["faltando"] == []
    assert "escala" not in relatorio


def test_cli_verify_only_desconhecido_sai_2(tmp_path, capsys):
    destino = _destino(tmp_path)
    assert main(["verify", str(destino), "--only=xpto"]) == 2
    assert "FORGE-E-SPEC" in capsys.readouterr().err


def test_doctor_expoe_blender_e_modelos_aptos():
    """I7/I9 leem essas duas chaves no topo do JSON."""
    resultado = doctor.checar()
    assert "blender" in resultado
    assert resultado["blender"] is None or resultado["blender"].startswith("4.2")
    assert resultado["modelos_aptos"], "allowlist comercial vazia"
    assert any("TripoSR" in modelo for modelo in resultado["modelos_aptos"])
    assert all("hunyuan" not in modelo.lower() for modelo in resultado["modelos_aptos"])
