"""D62/GAP-043 — escala de export declarada no manifesto (opcao A da P2).

O que estes testes provam, sem Blender e sem Studio:

* o perfil Roblox declara a unidade (studs) e o Godot nao escala;
* o manifesto sai como ``manifest@3`` com ``unidades_export`` e ``geometry.bbox_m`` em metros;
* o G2 mede o GLB em unidades do arquivo e compara com a altura em metros, dividindo pela escala;
* ``verify`` aceita ``manifest@1`` antigo (escala 1.0) e reprova ``@2`` inconsistente.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from forge3d import profiles, publish, qc
from forge3d.canonical import sha256_arquivo

RAIZ = Path(__file__).resolve().parents[1]
ROBLOX = profiles.carregar("roblox-r15")
GODOT = profiles.carregar("godot4")
ESCALA_STUD = 3.5714
METROS_POR_STUD = 0.28


# ------------------------------------------------------------------ perfis


def test_perfil_roblox_exporta_em_studs():
    unidades = ROBLOX["unidades"]
    assert unidades["escala_saida"] == pytest.approx(ESCALA_STUD)
    assert unidades["metros_por_unidade"] == pytest.approx(METROS_POR_STUD)
    # reciprocos, com o arredondamento de 4 casas do perfil
    assert unidades["escala_saida"] * unidades["metros_por_unidade"] == pytest.approx(1.0, abs=1e-3)


def test_perfil_godot_nao_escala_nada():
    assert qc.escala_do_perfil(GODOT) == 1.0


# ------------------------------------------------------------------ manifesto


def _resultado(escala: float = 1.0) -> dict:
    return {
        "arquivos": [
            {
                "caminho": "a.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 40,
                "sha256": "sha256:" + "1" * 64,
                "bytes": 1,
            }
        ],
        "determinism": "D1",
        "escala_saida": escala,
    }


def _relatorio(escala: float = 1.0) -> dict:
    return {
        "aprovado": True,
        "gates": [
            {"id": "G1", "status": "ok", "medido": {"nao_manifold": 0, "degeneradas": 0}},
            {
                "id": "G2",
                "status": "ok",
                "medido": {
                    "altura_m": 1.85,
                    "esperado_m": 1.85,
                    "delta_pct": 0.0,
                    "desvio_pivo_m": 0.0,
                    "pivo_regra": "base",
                    "escala_saida": escala,
                },
            },
            {"id": "G9", "status": "ok", "medido": {"limite": 3000}},
        ],
        "medidas": {
            "triangulos": 40,
            "vertices": 8,
            "bbox_m": [0.52, 1.85, 0.4],
            "escala_saida": escala,
            "materiais": 1,
            "ossos": 0,
            "partes_colisao": 0,
        },
    }


def _schema(versao: str) -> dict:
    arq = RAIZ / "schemas" / f"manifest.v{versao}.schema.json"
    return json.loads(arq.read_text(encoding="utf-8"))


def _manifesto(perfil: dict, escala: float = 1.0) -> dict:
    return publish.montar_manifesto(
        item={"id": "personagem.r15.guard.01", "rota": "blocky"},
        spec_doc={"projeto": "demo", "perfil": perfil["perfil"], "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome=perfil["perfil"],
        perfil=perfil,
        provider={"nome": "blocky", "versao": "x", "determinism": "D1"},
        resultado=_resultado(escala),
        relatorio_qc=_relatorio(escala),
        licenca={"modelo": "Blocky", "uso_comercial": True, "notice": "template proprio"},
        run_id="run-teste",
    )


def test_manifesto_roblox_declara_unidades_export_em_studs():
    man = _manifesto(ROBLOX, ESCALA_STUD)
    assert man["schema"] == "forge3d/manifest@3"
    assert man["unidades_export"] == {
        "metros_por_unidade": METROS_POR_STUD,
        "escala_saida": ESCALA_STUD,
    }
    # bbox_m continua em metros: o consumidor converte pela unidade declarada
    assert man["geometry"]["bbox_m"] == [0.52, 1.85, 0.4]
    jsonschema.validate(man, _schema("3"))


def test_manifesto_godot_fica_em_metros():
    man = _manifesto(GODOT, 1.0)
    assert man["schema"] == "forge3d/manifest@3"
    assert man["unidades_export"] == {"metros_por_unidade": 1.0, "escala_saida": 1.0}
    jsonschema.validate(man, _schema("3"))


def test_manifesto_v3_sem_unidades_export_reprova():
    man = _manifesto(ROBLOX, ESCALA_STUD)
    man.pop("unidades_export")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(man, _schema("3"))


# ------------------------------------------------------------------ G2


ITEM = {
    "id": "a.b",
    "altura_metros": 1.85,
    "pivot": "base",
    "limite_triangulos": 3000,
    "auto_rig": False,
    "colisao": "none",
}


def _info(altura_studs: float = 6.60714, deslocamento_studs: float = 0.0) -> dict:
    return {
        "triangulos": 40,
        "vertices": 8,
        "primitivas": 1,
        "sem_uv": 0,
        # bbox do GLB como o qc.analisar le: unidades do ARQUIVO (studs no roblox-r15)
        "bbox_m": [1.0, altura_studs, 0.5],
        "min": [0.0, deslocamento_studs, 0.0],
        "max": [1.0, deslocamento_studs + altura_studs, 0.5],
        "materiais": 1,
        "com_textura": 1,
        "imagens": 1,
        "imagens_externas": [],
        "ossos": 0,
        "nomes_ossos": [],
        "nos": [],
        "colisores": [],
    }


def _verificar(tmp_path: Path, monkeypatch, info: dict, perfil: dict, **kwargs) -> dict:
    monkeypatch.setattr(qc, "ler_glb_bin", lambda _caminho: ({}, b""))
    monkeypatch.setattr(qc, "analisar", lambda _gltf: dict(info))
    (tmp_path / "a.glb").write_bytes(b"x")
    resultado = {
        "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0},
        "arquivos": [{"caminho": "a.glb", "papel": "mesh", "nivel": 0, "triangulos": 40}],
        "licenca": {"modelo": "Blocky", "uso_comercial": True},
    }
    return qc.verificar(ITEM, perfil, tmp_path, resultado, **kwargs)


def _g2(relatorio: dict) -> dict:
    return next(g for g in relatorio["gates"] if g["id"] == "G2")


def test_g2_divide_pela_escala_do_perfil(tmp_path, monkeypatch):
    relatorio = _verificar(tmp_path, monkeypatch, _info(), ROBLOX)
    g2 = _g2(relatorio)
    assert g2["status"] == "ok", g2
    assert g2["medido"]["escala_saida"] == pytest.approx(ESCALA_STUD)
    assert g2["medido"]["altura_export"] == pytest.approx(6.60714, abs=1e-4)
    assert g2["medido"]["altura_m"] == pytest.approx(1.85, abs=1e-4)
    assert relatorio["medidas"]["bbox_m"][1] == pytest.approx(1.85, abs=1e-4)


def test_g2_reprova_se_o_glb_em_studs_for_lido_como_metro(tmp_path, monkeypatch):
    relatorio = _verificar(tmp_path, monkeypatch, _info(), ROBLOX, escala_saida=1.0)
    assert _g2(relatorio)["status"] == "falhou"


def test_g2_divide_o_desvio_do_pivo_pela_mesma_escala(tmp_path, monkeypatch):
    # 0,035714 studs = 1 cm: o desvio em metros e medido depois da divisao
    relatorio = _verificar(tmp_path, monkeypatch, _info(deslocamento_studs=0.035714), ROBLOX)
    g2 = _g2(relatorio)
    assert g2["medido"]["desvio_pivo_m"] == pytest.approx(0.01, abs=1e-5)
    assert g2["status"] == "falhou"  # tolerancia do perfil: 2 mm


def test_escala_1_nao_altera_nada(tmp_path, monkeypatch):
    implicito = _verificar(tmp_path, monkeypatch, _info(altura_studs=1.85), GODOT)
    explicito = _verificar(tmp_path, monkeypatch, _info(altura_studs=1.85), GODOT, escala_saida=1.0)
    assert implicito["gates"] == explicito["gates"]
    assert _g2(implicito)["status"] == "ok"


# ------------------------------------------------------------------ verify


def _destino(tmp_path: Path, perfil: dict, *, escala: float = ESCALA_STUD) -> Path:
    arquivo = tmp_path / "a.glb"
    arquivo.write_bytes(b"nao e um glb de verdade")
    relatorio = _relatorio(escala)
    resultado = _resultado(escala)
    resultado["arquivos"][0].update(
        sha256=sha256_arquivo(arquivo), bytes=arquivo.stat().st_size
    )
    man = publish.montar_manifesto(
        item={"id": "a.b", "rota": "blocky"},
        spec_doc={"projeto": "demo", "perfil": perfil["perfil"], "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome=perfil["perfil"],
        perfil=perfil,
        provider={"nome": "blocky", "versao": "x", "determinism": "D1"},
        resultado=resultado,
        relatorio_qc=relatorio,
        licenca={"modelo": "Blocky", "uso_comercial": True, "notice": "template proprio"},
        run_id="run-teste",
    )
    (tmp_path / "a.b.manifest.json").write_text(json.dumps(man), encoding="utf-8")
    return tmp_path


def _erros(destino: Path) -> list[str]:
    return [str(e.get("erro") or "") for e in publish.verificar(destino)["erros"]]


def test_verify_aceita_manifesto_v1_antigo(tmp_path):
    destino = _destino(tmp_path, ROBLOX)
    man = json.loads((destino / "a.b.manifest.json").read_text(encoding="utf-8"))
    man["schema"] = "forge3d/manifest@1"
    man.pop("unidades_export")
    man.pop("animacoes")
    (destino / "a.b.manifest.json").write_text(json.dumps(man), encoding="utf-8")
    erros = _erros(destino)
    # passa pelo schema @1 e chega ao QC (o GLB falso e ilegivel, o contrato nao foi recusado)
    assert "schema" not in erros, erros
    assert any("malha ilegivel" in e for e in erros), erros


def test_verify_reprova_manifesto_v2_sem_unidades_export(tmp_path):
    destino = _destino(tmp_path, ROBLOX)
    man = json.loads((destino / "a.b.manifest.json").read_text(encoding="utf-8"))
    man.pop("unidades_export")
    (destino / "a.b.manifest.json").write_text(json.dumps(man), encoding="utf-8")
    assert "schema" in _erros(destino)


def test_verify_reprova_unidades_export_inconsistentes(tmp_path):
    destino = _destino(tmp_path, ROBLOX)
    man = json.loads((destino / "a.b.manifest.json").read_text(encoding="utf-8"))
    man["unidades_export"]["metros_por_unidade"] = 1.0
    (destino / "a.b.manifest.json").write_text(json.dumps(man), encoding="utf-8")
    assert any("unidades_export inconsistentes" in e for e in _erros(destino))


def test_verify_reprova_escala_que_diverge_do_perfil(tmp_path):
    destino = _destino(tmp_path, ROBLOX)
    man = json.loads((destino / "a.b.manifest.json").read_text(encoding="utf-8"))
    man["unidades_export"] = {"metros_por_unidade": 0.5, "escala_saida": 2.0}
    (destino / "a.b.manifest.json").write_text(json.dumps(man), encoding="utf-8")
    assert any("difere do perfil atual" in e for e in _erros(destino))
