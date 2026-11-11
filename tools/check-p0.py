#!/usr/bin/env python3
"""Portao do P0 — nao e codigo de pipeline, e o oraculo dos documentos.

Verifica: os dois JSON Schemas, os lotes de exemplo, o manifesto de exemplo, os perfis,
os tetos de contexto e os invariantes checaveis hoje (I12, I14).

Uso:
    uv run --no-project --python 3.12 --with pyyaml --with jsonschema python tools/check-p0.py

Exit 0 = P0 verde. Substituido por tools/check-contexto.sh + tests/invariants/ em P1.
"""
import json
import pathlib
import re
import sys

import yaml
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parents[1]
erros = []


def ok(msg):
    print(f"  ok   {msg}")


def fail(msg):
    erros.append(msg)
    print(f"  FAIL {msg}")


print("== schemas ==")
schemas = {}
for rel in (
    "schemas/spec.v1.schema.json",
    "schemas/spec.v2.schema.json",
    "schemas/manifest.v1.schema.json",
    "schemas/manifest.v2.schema.json",
):
    try:
        s = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(s)
        schemas[rel] = s
        ok(f"{rel} valido (Draft 2020-12)")
    except Exception as e:  # noqa: BLE001
        fail(f"{rel}: {e}")

print("== exemplos yaml ==")
LOTES = (
    ("examples/lote_01.yaml", "schemas/spec.v1.schema.json", "spec@1"),
    ("examples/lote_02_rotas.yaml", "schemas/spec.v1.schema.json", "spec@1"),
    ("examples/lote_04_mesh.yaml", "schemas/spec.v1.schema.json", "spec@1"),
    ("examples/lote_05_mesh_concept.yaml", "schemas/spec.v1.schema.json", "spec@1"),
    ("examples/lote_06_mesh_split.yaml", "schemas/spec.v1.schema.json", "spec@1"),
    ("examples/lote_07_cape.yaml", "schemas/spec.v1.schema.json", "spec@1"),
    ("examples/lote_09_r15.yaml", "schemas/spec.v1.schema.json", "spec@1"),
    ("examples/lote_03_kit.yaml", "schemas/spec.v2.schema.json", "spec@2"),
)
for rel, schema_rel, rotulo in LOTES:
    try:
        doc = yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))
        validador = Draft202012Validator(schemas[schema_rel])
        errs = sorted(validador.iter_errors(doc), key=lambda e: list(e.path))
        if errs:
            for e in errs[:5]:
                fail(f"{rel}: {'/'.join(map(str, e.path))}: {e.message}")
        else:
            ok(f"{rel} valida contra {rotulo} ({len(doc['lote'])} itens)")
            ids = [i["id"] for i in doc["lote"]]
            if len(ids) != len(set(ids)):
                fail(f"{rel}: B1 id duplicado")
            for item in doc["lote"]:
                lod = item.get("lod")
                if lod and (lod[0] != 100 or any(a <= b for a, b in zip(lod, lod[1:]))):
                    fail(f"{rel}: B4 lod invalido em {item['id']} -> {lod}")
                if item.get("rota") == "mesh" and "seed" not in item:
                    fail(f"{rel}: B2 seed ausente em {item['id']}")
                if item.get("rota") == "import" and "origem" not in item:
                    fail(f"{rel}: B3 origem ausente em {item['id']}")
                parte = item.get("parte")
                if parte:
                    esperado = {
                        "corpo": "personagem_humanoide",
                        "capa": "personagem_humanoide",
                        "arma": "prop_equipavel",
                    }[parte]
                    if item.get("tipo") != esperado:
                        fail(f"{rel}: B12 parte {parte} com tipo {item.get('tipo')}")
                    if parte == "capa" and item.get("auto_rig"):
                        fail(f"{rel}: B13 capa com auto_rig")
    except Exception as e:  # noqa: BLE001
        fail(f"{rel}: {e}")

print("== manifestos de exemplo ==")
for rel_man, rel_schema, rotulo in (
    ("examples/manifest.exemplo.json", "schemas/manifest.v1.schema.json", "manifest@1"),
    ("examples/manifest.exemplo.v2.json", "schemas/manifest.v2.schema.json", "manifest@2"),
):
    try:
        man = json.loads((ROOT / rel_man).read_text(encoding="utf-8"))
        validador = Draft202012Validator(schemas[rel_schema])
        errs = sorted(validador.iter_errors(man), key=lambda e: list(e.path))
        if errs:
            for e in errs[:5]:
                fail(f"{rel_man}: {'/'.join(map(str, e.path))}: {e.message}")
        else:
            ok(f"{rel_man} valida contra {rotulo}")
    except Exception as e:  # noqa: BLE001
        fail(f"{rel_man}: {e}")

print("== perfis yaml ==")
for rel in ("profiles/godot4.yaml", "profiles/roblox-r15.yaml"):
    try:
        p = yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))
        assert p["schema"] == "forge3d/profile@1", "schema do perfil"
        for k in ("unidades", "eixos", "pivot", "colisao", "rig", "material", "validacao"):
            assert k in p, f"bloco ausente: {k}"
        ok(f"{rel} carregavel e com os blocos obrigatorios")
    except Exception as e:  # noqa: BLE001
        fail(f"{rel}: {e}")

print("== tetos de contexto ==")
tetos = {"MAPA.md": 60, "AGENTS.md": 80, "INVARIANTES.md": 200, "CONTINUAR.md": 200, "CONSELHOS.md": 140}
for rel, teto in tetos.items():
    n = len((ROOT / rel).read_text(encoding="utf-8").splitlines())
    if n > teto:
        fail(f"{rel}: {n} linhas > teto {teto}")
    else:
        ok(f"{rel}: {n}/{teto}")

print("== I12 caminhos proibidos ==")
proibido = re.compile(r"/mnt/[a-z]/|\\\\wsl")
achou = []
for base in ("examples", "profiles", "schemas", "docs"):
    for p in (ROOT / base).rglob("*"):
        if p.is_file() and p.suffix in {".yaml", ".yml", ".json", ".md"}:
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if proibido.search(line):
                    achou.append(f"{p.relative_to(ROOT)}:{i}")
if achou:
    for a in achou:
        fail(f"I12 caminho proibido em {a}")
else:
    ok("nenhum caminho /mnt ou UNC em examples/profiles/schemas/docs")

print("== I14 franquias em artefatos de contrato ==")
franquia = re.compile(r"minecraft|fortnite|zelda|mario|pokemon|call of duty", re.I)
achou = []
for base in ("examples", "profiles", "schemas"):
    for p in (ROOT / base).rglob("*"):
        if p.is_file() and p.suffix in {".yaml", ".yml", ".json"}:
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if franquia.search(line):
                    achou.append(f"{p.relative_to(ROOT)}:{i}")
if achou:
    for a in achou:
        fail(f"I14 franquia em {a}")
else:
    ok("nenhuma franquia em examples/profiles/schemas")

print("== coerencia de doc ==")
texto = "\n".join(
    p.read_text(encoding="utf-8") for p in [ROOT / n for n in ("README.md", "CONTINUAR.md", "MAPA.md")]
)
for caminho in re.findall(r"`([a-zA-Z0-9_./-]+\.(?:md|json|yaml))`", texto):
    alvo = ROOT / caminho
    if not alvo.exists() and caminho.startswith("3DCreation/"):
        alvo = ROOT / caminho[len("3DCreation/") :]
    if not alvo.exists() and not caminho.endswith((".py",)):
        fail(f"referencia a arquivo inexistente: {caminho}")
if not [e for e in erros if "inexistente" in e]:
    ok("referencias de arquivo em README/CONTINUAR/MAPA existem")

print()
if erros:
    print(f"RESULTADO: {len(erros)} falha(s)")
    sys.exit(1)
print("RESULTADO: P0 verde")
sys.exit(0)
