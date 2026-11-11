"""Correcoes da janela: C7 (verify x pivo_regra), C9 (rembg), C10 (FORGE3D_MODELOS), C11 (CLIP)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from PIL import Image

from forge3d import publish
from forge3d.canonical import sha256_arquivo
from forge3d.providers import mesh
from forge3d.providers.concept import SUFIXO_PADRAO, sufixo_efetivo

RAIZ = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ C7

def _manifesto(destino: Path, *, com_pivo: bool) -> Path:
    arquivo = destino / "a.glb"
    arquivo.write_bytes(b"nao e um glb de verdade")
    medido_g2 = {"altura_m": 1.0, "esperado_m": 1.0, "delta_pct": 0.0, "desvio_pivo_m": 0.0}
    if com_pivo:
        medido_g2["pivo_regra"] = "base"
    resultado = {
        "arquivos": [
            {
                "caminho": "a.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 1,
                "sha256": sha256_arquivo(arquivo),
                "bytes": arquivo.stat().st_size,
            }
        ],
        "determinism": "D2",
    }
    relatorio = {
        "aprovado": True,
        "gates": [
            {"id": "G1", "status": "ok"},
            {"id": "G2", "status": "ok", "medido": medido_g2},
            {"id": "G9", "status": "ok", "medido": {"limite": 1000}},
        ],
        "medidas": {
            "triangulos": 1,
            "vertices": 1,
            "bbox_m": [0.1, 0.1, 0.1],
            "materiais": 1,
            "ossos": 0,
            "partes_colisao": 0,
        },
    }
    man = publish.montar_manifesto(
        item={"id": "a.b", "rota": "mesh", "seed": 7},
        spec_doc={"projeto": "demo", "perfil": "godot4", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4",
        provider={"nome": "blocky", "versao": "x", "determinism": "D1"},
        resultado=resultado,
        relatorio_qc=relatorio,
        licenca={"modelo": "Blocky", "uso_comercial": True, "notice": "template proprio"},
        run_id="run-teste",
    )
    alvo = destino / "a.b.manifest.json"
    alvo.write_text(json.dumps(man), encoding="utf-8")
    return destino


def test_verify_reprova_manifesto_sem_pivo_regra(tmp_path):
    """GAP-037/C7: ausencia de pivo_regra e reprovacao, nao perdao silencioso."""
    destino = _manifesto(tmp_path, com_pivo=False)
    relatorio = publish.verificar(destino)
    assert relatorio["ok"] is False
    assert any("G2.pivo_regra" in (e.get("erro") or "") for e in relatorio["erros"]), relatorio["erros"]


def test_verify_com_pivo_regra_nao_reclama_do_pivo(tmp_path):
    destino = _manifesto(tmp_path, com_pivo=True)
    relatorio = publish.verificar(destino)
    assert not any("G2.pivo_regra" in (e.get("erro") or "") for e in relatorio["erros"])


# ------------------------------------------------------------------ C9

def _png(caminho: Path, *, com_alfa: bool) -> Path:
    modo = "RGBA" if com_alfa else "RGB"
    cor = (120, 120, 120, 255) if com_alfa else (120, 120, 120)
    img = Image.new(modo, (8, 8), cor)
    if com_alfa:
        for x in range(8):
            img.putpixel((x, 0), (0, 0, 0, 0))
    img.save(caminho)
    return caminho


def test_rembg_desligado_quando_a_imagem_ja_tem_alfa(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE3D_I23D_REMOVER_FUNDO", raising=False)
    remover, motivo = mesh._decidir_rembg(_png(tmp_path / "a.png", com_alfa=True), None)
    assert remover is False
    assert "transparente" in motivo


def test_rembg_ligado_quando_o_fundo_e_opaco(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE3D_I23D_REMOVER_FUNDO", raising=False)
    remover, motivo = mesh._decidir_rembg(_png(tmp_path / "b.png", com_alfa=False), None)
    assert remover is True
    assert "opaco" in motivo


def test_concept_sempre_remove_fundo(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE3D_I23D_REMOVER_FUNDO", raising=False)
    remover, motivo = mesh._decidir_rembg(
        _png(tmp_path / "c.png", com_alfa=False), {"modelo": "sd15"}
    )
    assert remover is True
    assert motivo == "concept"


def test_env_continua_mandando(tmp_path, monkeypatch):
    imagem = _png(tmp_path / "d.png", com_alfa=True)
    monkeypatch.setenv("FORGE3D_I23D_REMOVER_FUNDO", "1")
    assert mesh._decidir_rembg(imagem, None) == (True, "env=1")
    monkeypatch.setenv("FORGE3D_I23D_REMOVER_FUNDO", "0")
    assert mesh._decidir_rembg(imagem, {"modelo": "sd15"}) == (False, "env=0")


def test_versao_registra_a_politica_de_rembg(monkeypatch):
    monkeypatch.delenv("FORGE3D_I23D_REMOVER_FUNDO", raising=False)
    assert "rembgauto2" in mesh.MeshProvider().versao
    monkeypatch.setenv("FORGE3D_I23D_REMOVER_FUNDO", "1")
    assert "rembgon" in mesh.MeshProvider().versao


# ------------------------------------------------------------------ C10

def _sem_ambiente_de_maquina(monkeypatch, tmp_path):
    monkeypatch.setattr(mesh, "_cache_hf", lambda: tmp_path / "hf-vazio")
    monkeypatch.setattr(mesh, "_diagnostico", lambda: {"ok": True, "torch": "2.4.1", "cuda": True})
    monkeypatch.setattr(mesh, "_vram_livre_mb", lambda: 99999)


def test_preflight_acha_pesos_em_forge3d_modelos(tmp_path, monkeypatch):
    """GAP-040/C10: pesos no caminho local nao podem ser reportados como ausentes."""
    _sem_ambiente_de_maquina(monkeypatch, tmp_path)
    modelos = tmp_path / "modelos"
    (modelos / "TripoSR").mkdir(parents=True)
    monkeypatch.setenv("FORGE3D_MODELOS", str(modelos))
    pronto, razao = mesh.MeshProvider().preflight()
    assert pronto is True, razao


def test_preflight_sem_pesos_aponta_forge3d_modelos(tmp_path, monkeypatch):
    _sem_ambiente_de_maquina(monkeypatch, tmp_path)
    monkeypatch.setenv("FORGE3D_MODELOS", str(tmp_path / "modelos-vazio"))
    pronto, razao = mesh.MeshProvider().preflight()
    assert pronto is False
    assert "FORGE3D_MODELOS" in razao


# ------------------------------------------------------------------ C11

def _concept_infer():
    spec = importlib.util.spec_from_file_location(
        "concept_infer_mod", RAIZ / "tools" / "concept_infer.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class _Tokenizador:
    """Dublê do tokenizador CLIP: uma palavra = um token."""

    eos_token_id = 2

    def __call__(self, texto, truncation=False, add_special_tokens=True):
        return {"input_ids": list(range(1, len(texto.split()) + 1))}

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(f"t{i}" for i in ids)


def test_sufixo_nao_repete_o_que_o_prompt_ja_diz():
    prompt = "sentinela de guarda, game asset concept art"
    efetivo = sufixo_efetivo(prompt, SUFIXO_PADRAO)
    assert "game asset concept art" not in efetivo
    assert "front view" in efetivo


def test_sufixo_inteiro_quando_o_prompt_nao_repete():
    assert sufixo_efetivo("bule", SUFIXO_PADRAO) == SUFIXO_PADRAO


def test_prompt_curto_nao_e_truncado():
    mod = _concept_infer()
    texto, antes, depois = mod.truncar_prompt(_Tokenizador(), "um dois tres")
    assert (texto, antes, depois) == ("um dois tres", 3, 3)


def test_prompt_longo_e_truncado_no_limite_do_clip():
    mod = _concept_infer()
    longo = " ".join(f"p{i}" for i in range(120))
    texto, antes, depois = mod.truncar_prompt(_Tokenizador(), longo)
    assert antes == 120
    assert depois == mod.LIMITE_TOKENS_CLIP
    assert len(texto.split()) == mod.LIMITE_TOKENS_CLIP
