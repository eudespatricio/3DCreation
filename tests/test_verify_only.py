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


def test_sem_blender_o_doctor_responde_em_vez_de_derrubar(monkeypatch):
    """D17: ambiente faltando vira razao legivel. `erro_ambiente` e funcao, nao excecao — o
    `except erro_ambiente` dava TypeError e o doctor morria justamente no caso sem Blender."""
    from forge3d import post
    from forge3d.errors import erro_ambiente

    def sem_blender():
        raise erro_ambiente("blender nao encontrado")

    monkeypatch.setattr(post, "binario", sem_blender)
    ok, detalhe = post.preflight()
    assert ok is False
    assert "blender" in detalhe
    assert doctor.checar()["blender"] is None


def test_doctor_exigir_valida_checks_extras_e_recusa_desconhecido(monkeypatch):
    doctor.exigir(("python", "schemas", "perfis"))

    with pytest.raises(ForgeError) as exc_unk:
        doctor.exigir(("check_inexistente",))
    assert exc_unk.value.codigo == "FORGE-E-AMBIENTE"

    orig_checar = doctor.checar
    monkeypatch.setattr(
        doctor,
        "checar",
        lambda: {
            **orig_checar(),
            "checks": [
                {"nome": "python", "ok": True, "detalhe": "3.12", "critico": True},
                {"nome": "schemas", "ok": False, "detalhe": "schema quebrado", "critico": True},
            ],
        },
    )
    with pytest.raises(ForgeError) as exc_fail:
        doctor.exigir(("python", "schemas"))
    assert exc_fail.value.codigo == "FORGE-E-AMBIENTE"
    assert any("schemas" in p for p in exc_fail.value.detalhes.get("problemas", []))


def test_publish_r15_traduz_osso_anexo_e_rig_esqueleto(tmp_path):
    from forge3d import profiles
    from forge3d.canonical import sha256_arquivo

    glb = tmp_path / "item.glb"
    glb.write_bytes(b"glTF-dummy")
    perfil_r15 = profiles.carregar("roblox-r15")

    esperados = {
        "corpo": "HumanoidRootPart",
        "calcas": "LowerTorso",
        "peitoral": "UpperTorso",
        "capa": "UpperTorso",
        "arma": "RightHand",
        "luvas": "RightHand",
        "escudo": "LeftLowerArm",
        "botas": "RightFoot",
        "ombreiras": "UpperTorso",
        "cabelo": "Head",
    }
    for parte, osso_r15 in esperados.items():
        man = publish.montar_manifesto(
            item={"id": f"kit.{parte}.01", "rota": "mesh", "parte": parte, "seed": 1},
            spec_doc={"projeto": "demo", "perfil": "roblox-r15", "_arquivo": "lote.yaml"},
            spec_hash="sha256:" + "0" * 64,
            perfil_nome="roblox-r15",
            perfil=perfil_r15,
            provider={"nome": "mesh", "versao": "0.1.8", "determinism": "D2"},
            resultado={
                "arquivos": [
                    {
                        "caminho": "item.glb",
                        "papel": "mesh",
                        "nivel": 0,
                        "triangulos": 100,
                        "sha256": sha256_arquivo(glb),
                        "bytes": glb.stat().st_size,
                    }
                ],
                "determinism": "D2",
            },
            relatorio_qc={
                "aprovado": True,
                "gates": [{"id": "G1", "status": "ok"}],
                "medidas": {
                    "triangulos": 100,
                    "vertices": 80,
                    "bbox_m": [0.5, 0.5, 0.5],
                    "materiais": 1,
                    "ossos": 16,
                    "partes_colisao": 0,
                },
            },
            licenca={"modelo": "MIT", "uso_comercial": True, "notice": "teste"},
            run_id="run-r15",
        )
        assert man["anexo"]["osso"] == osso_r15
        if man["anexo"]["skinned"]:
            assert man["rig"] == {"esqueleto": "r15@1", "ossos": 16}

    # Override explicito do usuario nao e sobrescrito
    man_override = publish.montar_manifesto(
        item={"id": "kit.arma.custom", "rota": "mesh", "parte": "arma", "osso": "LeftHand", "seed": 1},
        spec_doc={"projeto": "demo", "perfil": "roblox-r15", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="roblox-r15",
        perfil=perfil_r15,
        provider={"nome": "mesh", "versao": "0.1.8", "determinism": "D2"},
        resultado={
            "arquivos": [
                {
                    "caminho": "item.glb",
                    "papel": "mesh",
                    "nivel": 0,
                    "triangulos": 100,
                    "sha256": sha256_arquivo(glb),
                    "bytes": glb.stat().st_size,
                }
            ],
            "determinism": "D2",
        },
        relatorio_qc={
            "aprovado": True,
            "gates": [{"id": "G1", "status": "ok"}],
            "medidas": {
                "triangulos": 100,
                "vertices": 80,
                "bbox_m": [0.5, 0.5, 0.5],
                "materiais": 1,
                "ossos": 0,
                "partes_colisao": 0,
            },
        },
        licenca={"modelo": "MIT", "uso_comercial": True, "notice": "teste"},
        run_id="run-r15",
    )
    assert man_override["anexo"]["osso"] == "LeftHand"


def test_verify_preserva_budget_hero_g9(tmp_path):
    from forge3d import profiles, qc
    from forge3d.canonical import sha256_arquivo
    from tests.test_seguranca_e_qc import _glb_bytes

    destino = tmp_path / "hero_dest"
    destino.mkdir()
    # GLB valido com ~2500 KB (> 2048 KB padrao do godot4, <= 4096 KB hero)
    glb_base = _glb_bytes()
    padding = b"\x00" * (2600 * 1024)
    glb_hero = glb_base + padding
    arq = destino / "hero.glb"
    arq.write_bytes(glb_hero)

    perfil = profiles.carregar("godot4")
    item = {
        "id": "hero.espada.01",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 1000,
        "qualidade": "hero",
        "auto_rig": False,
        "colisao": "none",
    }
    resultado = {
        "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0},
        "arquivos": [
            {
                "caminho": "hero.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 12,
                "sha256": sha256_arquivo(arq),
                "bytes": arq.stat().st_size,
            }
        ],
        "licenca": {"modelo": "MIT", "uso_comercial": True, "notice": "hero"},
        "determinism": "D2",
    }
    rel_qc = qc.verificar(item, perfil, destino, resultado, escala_saida=1.0)
    assert rel_qc["aprovado"] is True, rel_qc["gates"]
    man = publish.montar_manifesto(
        item={**item, "rota": "mesh", "seed": 7},
        spec_doc={"projeto": "demo", "perfil": "godot4", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4",
        perfil=perfil,
        provider={"nome": "mesh", "versao": "0.1.8", "determinism": "D2"},
        resultado=resultado,
        relatorio_qc=rel_qc,
        licenca={"modelo": "MIT", "uso_comercial": True, "notice": "hero"},
        run_id="run-hero",
    )
    (destino / "hero.espada.01.manifest.json").write_text(json.dumps(man), encoding="utf-8")

    rel_verify = publish.verificar(destino)
    assert rel_verify["ok"] is True, rel_verify["erros"]
