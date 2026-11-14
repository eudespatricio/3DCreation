"""Testes de integracao MakeHuman/MPFB2 (cabelo CC0, spec B18-B21, MeshProvider, PBR/iluminacao e Blender G1)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from forge3d import canonical, post, profiles, providers, qc, spec
from forge3d.errors import ForgeError
from forge3d.providers import mesh

RAIZ = Path(__file__).resolve().parents[1]


def _doc_mh(
    *,
    schema: str = "forge3d/spec@3",
    perfil: str = "godot4",
    item_extra: dict | None = None,
) -> dict:
    item: dict = {
        "id": "hero.mh.01",
        "tipo": "personagem_humanoide",
        "rota": "mesh",
        "prompt": "guerreiro estilizado",
        "altura_metros": 1.80,
        "seed": 42,
    }
    if item_extra:
        item.update(item_extra)
    return {
        "schema": schema,
        "projeto": "demo",
        "perfil": perfil,
        "destino_exportacao": "~/.local/state/forge3d/saida/mh",
        "lote": [item],
    }


# ---------------------------------------------------------------- contrato spec & regras B18-B21


@pytest.mark.parametrize("schema", ["forge3d/spec@2", "forge3d/spec@3"])
def test_spec_aceita_makehuman_cabelo_e_origem_uri(schema):
    doc_corpo = _doc_mh(
        schema=schema,
        item_extra={
            "parte": "corpo",
            "template_humanoide": True,
            "makehuman_cabelo": "long01",
            "cor_cabelo": "#3b2314",
            "macro": {"height": 0.55},
            "auto_rig": True,
        },
    )
    prep_c, _perfil, _avisos = spec.preparar(doc_corpo)
    assert prep_c["lote"][0]["makehuman_cabelo"] == "long01"
    assert prep_c["lote"][0]["cor_cabelo"] == "#3b2314"

    doc_cabelo = _doc_mh(
        schema=schema,
        perfil="roblox-r15",
        item_extra={
            "id": "hero.cabelo.01",
            "tipo": "prop_estatico",
            "parte": "cabelo",
            "origem": "makehuman://hair/long01",
            "cor_cabelo": "#1a1a1a",
            "altura_metros": 0.55,
            "auto_rig": False,
        },
    )
    prep_h, _perfil_r15, _ = spec.preparar(doc_cabelo)
    assert prep_h["lote"][0]["material"] == "alpha_clip"
    resolvido = spec.resolver_item(prep_h["lote"][0])
    assert resolvido["origem_makehuman"] == "makehuman://hair/long01"
    assert "origem_hash" not in resolvido


def test_chave_cache_muda_com_campos_makehuman():
    perfil = profiles.carregar("godot4")
    doc_a = _doc_mh(
        item_extra={
            "parte": "cabelo",
            "tipo": "prop_estatico",
            "altura_metros": 0.5,
            "makehuman_cabelo": "long01",
            "cor_cabelo": "#3b2314",
            "macro": {"height": 0.45},
        }
    )
    doc_b = _doc_mh(
        item_extra={
            "parte": "cabelo",
            "tipo": "prop_estatico",
            "altura_metros": 0.5,
            "makehuman_cabelo": "long01",
            "cor_cabelo": "#aa5522",
            "macro": {"height": 0.45},
        }
    )
    item_a = spec.preparar(doc_a)[0]["lote"][0]
    item_b = spec.preparar(doc_b)[0]["lote"][0]
    assert canonical.chave_cache(item_a, "0.1.8", {"mesh": "0.1.8"}, perfil) != canonical.chave_cache(
        item_b, "0.1.8", {"mesh": "0.1.8"}, perfil
    )


def test_regras_b18_b19_b20_b21_makehuman():
    # B18: makehuman_cabelo / makehuman:// apenas na rota mesh
    doc_b18 = _doc_mh(item_extra={"rota": "blocky", "parte": "corpo", "makehuman_cabelo": "long01"})
    with pytest.raises(ForgeError) as exc_b18:
        spec.preparar(doc_b18)
    assert any(e.get("regra") == "B18" for e in exc_b18.value.detalhes["erros"])

    # B19: makehuman_cabelo com parte arma
    doc_b19 = _doc_mh(
        item_extra={
            "tipo": "prop_equipavel",
            "parte": "arma",
            "altura_metros": 1.0,
            "makehuman_cabelo": "long01",
        }
    )
    with pytest.raises(ForgeError) as exc_b19:
        spec.preparar(doc_b19)
    assert any(e.get("regra") == "B19" for e in exc_b19.value.detalhes["erros"])

    # B19: makehuman://hair/... em personagem_humanoide exige parte 'cabelo'
    doc_b19_uri = _doc_mh(item_extra={"parte": "corpo", "origem": "makehuman://hair/long01"})
    with pytest.raises(ForgeError) as exc_b19_uri:
        spec.preparar(doc_b19_uri)
    assert any(e.get("regra") == "B19" for e in exc_b19_uri.value.detalhes["erros"])

    # B20: roblox-r15 (materiais_max == 1) bloqueia makehuman_cabelo em corpo
    doc_b20 = _doc_mh(
        perfil="roblox-r15",
        item_extra={"parte": "corpo", "template_humanoide": True, "makehuman_cabelo": "long01"},
    )
    with pytest.raises(ForgeError) as exc_b20:
        spec.preparar(doc_b20)
    assert any(e.get("regra") == "B20" for e in exc_b20.value.detalhes["erros"])

    # B21: origem makehuman:// invalida
    for bad_uri in ("makehuman://", "makehuman://hair", "makehuman://hair/", "makehuman://clothes/hat01"):
        doc_b21 = _doc_mh(
            item_extra={"tipo": "prop_estatico", "parte": "cabelo", "altura_metros": 0.5, "origem": bad_uri}
        )
        with pytest.raises(ForgeError) as exc_b21:
            spec.preparar(doc_b21)
        assert any(e.get("regra") == "B21" for e in exc_b21.value.detalhes["erros"])


# ---------------------------------------------------------------- provider mesh.py (sem TripoSR/GPU)


def test_mesh_provider_cabelo_makehuman_dispensa_triposr_e_gpu(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE3D_VENV_I23D", str(tmp_path / "venv-ausente"))
    monkeypatch.setenv("FORGE3D_MODELOS", str(tmp_path / "modelos-ausentes"))
    monkeypatch.setattr(post, "binario", lambda: "/usr/bin/blender")

    prov = mesh.MeshProvider()
    item = {
        "id": "hero.cabelo.01",
        "tipo": "prop_estatico",
        "rota": "mesh",
        "parte": "cabelo",
        "origem": "makehuman://hair/long01",
        "cor_cabelo": "#3b2314",
        "macro": {"height": 0.45},
        "limite_triangulos": 4000,
        "altura_metros": 0.55,
    }
    pronto, razao = prov.preflight_item(item)
    assert pronto is True
    assert "MakeHuman" in razao
    assert prov.custo(item, {"perfil": "godot4"})["vram_mb"] == 0

    chamadas: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        chamadas.append(cmd)
        if any("template_body.py" in str(c) for c in cmd):
            job = json.loads(Path(cmd[-1]).read_text(encoding="utf-8"))
            assert job["modo"] == "cabelo"
            assert job["makehuman_cabelo"] == "long01"
            assert job["cor_cabelo"] == "#3b2314"
            assert job["macro"] == {"height": 0.45}
            assert job["limite_triangulos"] == 4000
            out_dir = Path(job["saida"])
            (out_dir / "template_hair.glb").write_bytes(b"glTF")
            Image.new("RGBA", (64, 64), (59, 35, 20, 255)).save(out_dir / "baseColor.png")
            (out_dir / "relatorio.json").write_text(
                json.dumps({"estilo": "long01", "triangulos": 3716, "nao_manifold": 0}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"Nao deveria chamar TripoSR/Concept para cabelo MakeHuman: {cmd}")

    monkeypatch.setattr(mesh.subprocess, "run", fake_run)
    destino = tmp_path / "bruto_cabelo"
    raw = prov.gerar(item, {"perfil": "godot4", "material": {"textura_max": 1024}}, destino)

    assert raw.schema == "forge3d/bruto-arquivo@1"
    assert raw.meta["modelo"] == "mpfb2"
    assert raw.meta["modo"] == "mpfb2_cabelo"
    assert providers.LICENCAS[raw.meta["modelo"]]["uso_comercial"] is True
    assert "CC0" in providers.LICENCAS[raw.meta["modelo"]]["notice"]
    modelo = json.loads((destino / "modelo.json").read_text(encoding="utf-8"))
    assert modelo["arquivo"] == "template_hair.glb"
    assert modelo["suavizar"] is False
    assert not any("i23d_infer.py" in str(c) or "concept_infer.py" in str(c) for c in chamadas)


def test_mesh_provider_template_humanoide_repassa_cabelo_e_macro(monkeypatch, tmp_path):
    prov = mesh.MeshProvider()
    monkeypatch.setattr(prov, "preflight_item", lambda _item: (True, "ok"))

    foto = tmp_path / "hero.png"
    Image.new("RGBA", (64, 128), (200, 150, 120, 255)).save(foto)
    jobs_vistos: list[dict] = []

    def fake_run(cmd, **_kwargs):
        if any("template_prep.py" in str(c) for c in cmd):
            out_dir = Path(cmd[cmd.index("--saida-dir") + 1])
            res_json = Path(cmd[cmd.index("--resultado") + 1])
            tex = out_dir / "input_template.png"
            Image.new("RGBA", (64, 128), (195, 145, 118, 255)).save(tex)
            res_json.write_text(
                json.dumps({"ok": True, "foto_template": str(tex), "marcos": {}}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if any("template_body.py" in str(c) for c in cmd):
            job = json.loads(Path(cmd[-1]).read_text(encoding="utf-8"))
            jobs_vistos.append(job)
            out_dir = Path(job["saida"])
            (out_dir / "template_body.glb").write_bytes(b"glTF")
            Image.new("RGBA", (64, 64), (195, 145, 118, 255)).save(out_dir / "baseColor.png")
            (out_dir / "relatorio.json").write_text(
                json.dumps({"triangulos": 11000, "template": "mpfb2 (CC0)"}), encoding="utf-8"
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"Comando inesperado: {cmd}")

    monkeypatch.setattr(mesh.subprocess, "run", fake_run)
    raw = prov.gerar(
        {
            "id": "hero.corpo.01",
            "tipo": "personagem_humanoide",
            "parte": "corpo",
            "makehuman_cabelo": "long01",
            "cor_cabelo": "#3b2314",
            "macro": {"height": 0.45, "gender": 0.0},
            "limite_triangulos": 12000,
            "origem": str(foto),
        },
        {"perfil": "godot4", "material": {"textura_max": 1024}},
        tmp_path / "bruto_corpo",
    )
    assert raw.meta["modelo"] == "mpfb2"
    assert len(jobs_vistos) == 1
    assert jobs_vistos[0]["makehuman_cabelo"] == "long01"
    assert jobs_vistos[0]["cor_cabelo"] == "#3b2314"
    assert jobs_vistos[0]["macro"] == {"height": 0.45, "gender": 0.0}
    assert jobs_vistos[0]["limite_triangulos"] == 12000


# ---------------------------------------------------------------- calibracao iluminacao & PBR


def test_render_preview_e_bake_pbr_calibracao_sem_estouro():
    rp_src = (RAIZ / "tools" / "render_preview.py").read_text(encoding="utf-8")
    assert '"AgX"' in rp_src
    assert "65.0" in rp_src and "42.0" in rp_src and "45.0" in rp_src
    assert 'bsdf.inputs["Specular IOR Level"].default_value = 0.18' in rp_src

    bp_src = (RAIZ / "blender" / "bake_pbr.py").read_text(encoding="utf-8")
    assert 'bsdf.inputs["Roughness"].default_value = 0.78' in bp_src
    assert 'bsdf.inputs["Specular IOR Level"].default_value = 0.18' in bp_src


# ---------------------------------------------------------------- Blender headless: template_body + mhclo G1


@pytest.mark.blender
def test_blender_template_body_cabelo_mhclo_cc0_passa_g1(tmp_path):
    try:
        blender_bin = post.binario()
    except ForgeError:
        pytest.skip("Blender 4.2 ausente")

    xdg = os.environ.get("XDG_CONFIG_HOME")
    cfg_root = Path(xdg) if xdg else (Path.home() / ".config")
    mh_root = cfg_root / "blender" / "4.2" / "extensions" / ".user" / "user_default" / "mpfb" / "data" / "hair"
    if not (mh_root / "long01" / "long01.mhclo").is_file():
        pytest.skip("pacote MPFB2 hair/long01 nao instalado neste ambiente")

    saida = tmp_path / "mh_hair"
    saida.mkdir(parents=True, exist_ok=True)
    job_path = saida / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "modo": "cabelo",
                "makehuman_cabelo": "long01",
                "cor_cabelo": "#3b2314",
                "limite_triangulos": 4000,
                "textura": 512,
                "material": "alpha_clip",
                "saida": str(saida),
            }
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [blender_bin, "-b", "--python", str(RAIZ / "blender" / "template_body.py"), "--", str(job_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    rel = json.loads((saida / "relatorio.json").read_text(encoding="utf-8"))
    assert rel["nao_manifold"] == 0
    assert rel["degeneradas"] == 0
    assert rel["triangulos"] <= 4000
    assert "CC0" in rel["template"]

    glb = saida / "template_hair.glb"
    assert glb.is_file()
    gltf, binario = qc.ler_glb_bin(glb)
    topo = qc.topologia(gltf, binario)
    assert topo["nao_manifold"] == 0
    assert topo["degeneradas"] == 0
    assert len(gltf.get("materials", [])) == 1
    assert gltf["materials"][0].get("alphaMode") == "MASK"
