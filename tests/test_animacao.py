"""D66 — animação base: retarget por perfil, G10 e `manifest@3` com `animacoes`."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import jsonschema
import pytest

from forge3d import profiles, publish, qc
from forge3d.errors import ForgeError

RAIZ = Path(__file__).resolve().parents[1]
GODOT = profiles.carregar("godot4")
ROBLOX = profiles.carregar("roblox-r15")


# ------------------------------------------------------------------ retarget


def test_retarget_cobre_os_dois_esqueletos():
    for perfil, esqueleto in ((GODOT, "godot-humanoid@1"), (ROBLOX, "r15@1")):
        mapa = profiles.retarget(perfil, esqueleto)
        assert set(mapa) == {"tronco", "coluna", "cabeca", "braco_e", "braco_d"}
        assert all(v in perfil["rig"]["mapas"][esqueleto] for v in mapa.values()), mapa


def test_retarget_de_esqueleto_desconhecido_e_vazio():
    assert profiles.retarget(GODOT, "r15@1") == {}


# ------------------------------------------------------------------ spec


def _doc(extra: dict | None = None) -> dict:
    item = {
        "id": "personagem.teste.01",
        "tipo": "personagem_humanoide",
        "rota": "blocky",
        "prompt": "boneco de teste",
        "altura_metros": 1.85,
        "auto_rig": True,
        "colisao": "convex",
    }
    item.update(extra or {})
    return {
        "schema": "forge3d/spec@1",
        "projeto": "demo",
        "perfil": "godot4",
        "destino_exportacao": "~/.local/state/forge3d/saida/x",
        "lote": [item],
    }


def test_spec_aceita_idle_sem_aviso_de_animacao():
    spec_doc, _perfil, avisos = __import__("forge3d.spec", fromlist=["preparar"]).preparar(
        _doc({"animacoes_base": ["idle"]})
    )
    assert spec_doc["lote"][0]["animacoes_base"] == ["idle"]
    assert not [a for a in avisos if a["codigo"] == "FORGE-W-ANIM"], avisos


def test_spec_avisa_clipe_sem_gerador():
    from forge3d import spec

    _spec_doc, _perfil, avisos = spec.preparar(_doc({"animacoes_base": ["walk"]}))
    assert any(a["codigo"] == "FORGE-W-ANIM" and "walk" in a["mensagem"] for a in avisos), avisos


def test_spec_reprova_animacao_sem_rig():
    from forge3d import spec

    with pytest.raises(ForgeError) as exc:
        spec.preparar(_doc({"auto_rig": False, "animacoes_base": ["idle"]}))
    assert any(e.get("regra") == "B14" for e in exc.value.detalhes["erros"])


# ------------------------------------------------------------------ definicao do clipe


def test_clipe_e_deterministico_e_resolve_os_ossos():
    from forge3d import animacao

    a = animacao.clipes(GODOT, "godot-humanoid@1", ["idle"])
    b = animacao.clipes(GODOT, "godot-humanoid@1", ["idle"])
    assert a == b
    clipe = a[0]
    assert clipe["nome"] == "idle"
    assert clipe["duracao_s"] == 2.0
    assert [c["segundos"] for c in clipe["chaves"]] == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert clipe["ossos"] == ["Chest", "Head", "Spine1", "UpperArm.L", "UpperArm.R"]


def test_clipe_materializa_os_dois_esqueletos():
    from forge3d import animacao

    r15 = animacao.clipes(ROBLOX, "r15@1", ["idle"])[0]
    assert r15["ossos"] == ["Head", "LeftUpperArm", "LowerTorso", "RightUpperArm", "UpperTorso"]
    # mesma amplitude no eixo X nos dois esqueletos: o clipe e o mesmo, o osso muda
    godot = animacao.clipes(GODOT, "godot-humanoid@1", ["idle"])[0]
    meio_r15 = {p["osso"]: p["graus"] for p in r15["chaves"][2]["poses"]}
    meio_godot = {p["osso"]: p["graus"] for p in godot["chaves"][2]["poses"]}
    assert meio_r15["UpperTorso"] == pytest.approx(meio_godot["Chest"])
    assert meio_r15["LowerTorso"] == pytest.approx(meio_godot["Spine1"])


def test_clipe_sem_retarget_ou_sem_gerador_e_vazio():
    from forge3d import animacao

    assert animacao.clipes(GODOT, "r15@1", ["idle"]) == []
    assert animacao.clipes(GODOT, "godot-humanoid@1", []) == []
    assert animacao.clipes(GODOT, "godot-humanoid@1", ["walk"]) == []


# ------------------------------------------------------------------ G10


def _pacote_animado(rotacoes: list[tuple[float, float, float, float]]) -> tuple[dict, bytes]:
    """glTF minimo com skin de 2 joints e um clipe `idle` de 2 s."""
    dados = b""
    views: list[dict] = []
    acessores: list[dict] = []

    tempos = b"".join(struct.pack("<f", t) for t in (0.0, 1.0, 2.0))
    views.append({"buffer": 0, "byteOffset": len(dados), "byteLength": len(tempos)})
    dados += tempos
    acessores.append(
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": 3,
            "type": "SCALAR",
            "min": [0.0],
            "max": [2.0],
        }
    )

    valores = b"".join(struct.pack("<4f", *r) for r in rotacoes)
    views.append({"buffer": 0, "byteOffset": len(dados), "byteLength": len(valores)})
    dados += valores
    acessores.append({"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC4"})

    gltf = {
        "nodes": [
            {"name": "body"},
            {"name": "Armature"},
            {"name": "Chest"},
            {"name": "Head"},
            {"name": "objeto_solto"},
        ],
        "skins": [{"joints": [2, 3]}],
        "accessors": acessores,
        "bufferViews": views,
        "animations": [
            {
                "name": "idle",
                "channels": [
                    {"sampler": 0, "target": {"node": 2, "path": "rotation"}},
                    {"sampler": 0, "target": {"node": 3, "path": "rotation"}},
                    {"sampler": 0, "target": {"node": 4, "path": "rotation"}},
                ],
                "samplers": [{"input": 0, "output": 1}],
            }
        ],
    }
    return gltf, dados


def test_animacoes_le_clipe_duracao_e_ossos_do_rig():
    gltf, binario = _pacote_animado([(0.0, 0.0, 0.0, 1.0), (0.05, 0.0, 0.0, 0.999), (0.0, 0.0, 0.0, 1.0)])
    clipes = qc.animacoes(gltf, binario)
    assert len(clipes) == 1
    clipe = clipes[0]
    assert clipe["nome"] == "idle"
    assert clipe["duracao_s"] == pytest.approx(2.0)
    # o canal do objeto solto nao e osso do skin: fica fora
    assert clipe["ossos"] == ["Chest", "Head"]
    assert clipe["canais"] == 2
    assert clipe["movendo"] == ["Chest", "Head"]


def test_animacao_so_com_identidade_nao_move():
    gltf, binario = _pacote_animado([(0.0, 0.0, 0.0, 1.0)] * 3)
    clipe = qc.animacoes(gltf, binario)[0]
    assert clipe["movendo"] == []


# ------------------------------------------------------------------ manifesto @3


def _schema(versao: str) -> dict:
    return json.loads((RAIZ / "schemas" / f"manifest.v{versao}.schema.json").read_text(encoding="utf-8"))


def _manifesto(clipes: list[dict]) -> dict:
    relatorio = {
        "aprovado": True,
        "gates": [
            {"id": "G1", "status": "ok", "medido": {"nao_manifold": 0, "degeneradas": 0}},
            {
                "id": "G2",
                "status": "ok",
                "medido": {"altura_m": 1.85, "esperado_m": 1.85, "delta_pct": 0.0, "pivo_regra": "base"},
            },
            {"id": "G9", "status": "ok", "medido": {"limite": 3000}},
        ],
        "medidas": {
            "triangulos": 40,
            "vertices": 8,
            "bbox_m": [0.52, 1.85, 0.4],
            "escala_saida": 1.0,
            "materiais": 1,
            "ossos": 23,
            "partes_colisao": 0,
            "animacoes": clipes,
        },
    }
    resultado = {
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
    }
    return publish.montar_manifesto(
        item={"id": "personagem.teste.01", "rota": "blocky"},
        spec_doc={"projeto": "demo", "perfil": "godot4", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4",
        perfil=GODOT,
        provider={"nome": "blocky", "versao": "x", "determinism": "D1"},
        resultado=resultado,
        relatorio_qc=relatorio,
        licenca={"modelo": "Blocky", "uso_comercial": True, "notice": "template proprio"},
        run_id="run-teste",
    )


CLIPES = [
    {
        "nome": "idle",
        "duracao_s": 2.042,
        "ossos": ["Chest", "Head", "Spine1", "UpperArm.L", "UpperArm.R"],
        "movendo": ["Chest", "Head", "Spine1", "UpperArm.L", "UpperArm.R"],
        "canais": 69,
    }
]


def test_manifesto_v3_declara_os_clipes():
    man = _manifesto(CLIPES)
    assert man["schema"] == "forge3d/manifest@3"
    assert man["animacoes"] == [
        {
            "nome": "idle",
            "duracao_s": 2.042,
            "ossos": ["Chest", "Head", "Spine1", "UpperArm.L", "UpperArm.R"],
        }
    ]
    jsonschema.validate(man, _schema("3"))


def test_manifesto_v3_sem_animacoes_reprova():
    man = _manifesto(CLIPES)
    man.pop("animacoes")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(man, _schema("3"))


def test_manifesto_v3_com_animacao_vazia_e_valido():
    man = _manifesto([])
    assert man["animacoes"] == []
    jsonschema.validate(man, _schema("3"))
