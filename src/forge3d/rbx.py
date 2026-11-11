"""Export nativo R15 para Roblox Studio (``.rbxlx``), sem import manual.

O ``blocky`` já conhece as caixas e os 16 ossos R15. Este módulo monta um **place** com 16
``Part``s (uma por parte R15, agregando as caixas daquele osso) e 15 ``Motor6D`` com pivô no
joint. Não há upload nem ``MeshPart``: o arquivo é aberto direto no Studio, com as cores do
blocky. A textura/atlas e o GLB continuam sendo o caminho de mesh; aqui é o rig nativo.
"""

from __future__ import annotations

import json
import tempfile
from html import escape
from pathlib import Path
from xml.etree import ElementTree

from . import paths, spec
from .errors import erro_spec
from .providers import blocky

__all__ = ["exportar_r15"]


def _cor_int(hexcor: str) -> int:
    valor = int(str(hexcor).lstrip("#"), 16)
    r, g, b = (valor >> 16) & 0xFF, (valor >> 8) & 0xFF, valor & 0xFF
    return (r << 16) | (g << 8) | b


def _vec(tag: str, x: float, y: float, z: float) -> list[str]:
    return [
        f'<Vector3 name="{tag}">',
        f"<X>{x:.6f}</X>",
        f"<Y>{y:.6f}</Y>",
        f"<Z>{z:.6f}</Z>",
        "</Vector3>",
    ]


def _cframe(tag: str, x: float, y: float, z: float) -> list[str]:
    return [
        f'<CoordinateFrame name="{tag}">',
        f"<X>{x:.6f}</X>",
        f"<Y>{y:.6f}</Y>",
        f"<Z>{z:.6f}</Z>",
        "<R00>1</R00><R01>0</R01><R02>0</R02>",
        "<R10>0</R10><R11>1</R11><R12>0</R12>",
        "<R20>0</R20><R21>0</R21><R22>1</R22>",
        "</CoordinateFrame>",
    ]


def _roblox(p, mps: float) -> tuple[float, float, float]:
    """metros (x, y, z) do blocky -> studs (x, z, -y) no Roblox."""
    return (p[0] / mps, p[2] / mps, -p[1] / mps)


def _parte_xml(nome: str, ref: str, centro, tamanho, cor: int, motores: list[list[str]]) -> list[str]:
    linhas = [
        f'<Item class="Part" referent="{ref}">',
        "<Properties>",
        f'<string name="Name">{escape(nome)}</string>',
        '<bool name="Anchored">true</bool>',
        '<bool name="CanCollide">false</bool>',
        f'<Color3uint8 name="Color3uint8">{cor}</Color3uint8>',
    ]
    linhas += _vec("size", *tamanho)
    linhas += _cframe("CFrame", *centro)
    linhas += ["</Properties>"]
    for motor in motores:
        linhas += motor
    linhas += ["</Item>"]
    return linhas


def exportar_r15(
    lote: str | Path,
    item_id: str,
    saida: str | Path | None = None,
    metros_por_stud: float | None = None,
) -> dict:
    """Gera um place ``.rbxlx`` com o rig R15 (Parts + Motor6D) do item blocky."""
    doc = spec.carregar_arquivo(lote)
    doc, perfil, _avisos = spec.preparar(doc)
    item = next((i for i in doc["lote"] if i.get("id") == item_id), None)
    if item is None:
        raise erro_spec(f"export-r15: item '{item_id}' nao existe no lote")
    if item.get("rota") != "blocky":
        raise erro_spec("export-r15: so a rota blocky gera .rbxlx nativo")
    if not item.get("auto_rig") or item.get("esqueleto") != "r15@1":
        raise erro_spec("export-r15: item precisa de auto_rig: true e esqueleto: r15@1")

    mps = float(metros_por_stud or (perfil.get("unidades") or {}).get("metros_por_stud", 0.28))
    if mps <= 0:
        raise erro_spec("export-r15: metros_por_stud precisa ser > 0")

    with tempfile.TemporaryDirectory(prefix="forge3d-r15-") as td:
        blocky.BlockyProvider().gerar(item, perfil, Path(td))
        modelo = json.loads((Path(td) / "modelo.json").read_text(encoding="utf-8"))

    caixas = modelo.get("caixas") or []
    ossos = modelo.get("ossos") or []
    if len(ossos) != 16:
        raise erro_spec(f"export-r15: esperava 16 ossos R15, achei {len(ossos)}")

    # GAP-044: o blocky nasce com a altura dele (1,906 m neste R15) e o pos-processo normaliza a
    # malha para `altura_metros`. O .rbxlx tem que aplicar a MESMA transformacao — escala uniforme
    # e pivo na base — senao o rig fica 3% acima do package no Studio.
    alvo_m = float(item["altura_metros"])
    minimo = [min(c["min"][i] for c in caixas) for i in range(3)]
    maximo = [max(c["max"][i] for c in caixas) for i in range(3)]
    altura_bruta = maximo[2] - minimo[2]
    if altura_bruta <= 0:
        raise erro_spec("export-r15: geometria com altura zero")
    fator = alvo_m / altura_bruta
    pivo = [(minimo[0] + maximo[0]) / 2, (minimo[1] + maximo[1]) / 2, minimo[2]]

    def _normalizar(ponto: list[float]) -> list[float]:
        return [round((ponto[i] - pivo[i]) * fator, 6) for i in range(3)]

    caixas = [{**c, "min": _normalizar(c["min"]), "max": _normalizar(c["max"])} for c in caixas]
    ossos = [
        {
            **o,
            "cabeca": _normalizar(o["cabeca"]),
            **({"cauda": _normalizar(o["cauda"])} if o.get("cauda") else {}),
        }
        for o in ossos
    ]

    partes: dict[str, dict] = {}
    for osso in ossos:
        nome = osso["nome"]
        minhas = [c for c in caixas if c.get("osso") == nome]
        if minhas:
            mn = [min(c["min"][i] for c in minhas) for i in range(3)]
            mx = [max(c["max"][i] for c in minhas) for i in range(3)]
            centro_m = [(mn[i] + mx[i]) / 2 for i in range(3)]
            tamanho_m = [max(0.02, mx[i] - mn[i]) for i in range(3)]
            maior = max(minhas, key=lambda c: (c["max"][0] - c["min"][0]) * (c["max"][1] - c["min"][1]) * (c["max"][2] - c["min"][2]))
            cor = _cor_int(maior["cor"])
        else:
            # GAP-044: caixa de 0,20 m centrada em 5% da altura passava da base (min z<0)
            centro_m = [0.0, 0.0, max(0.10, 0.05 * alvo_m)]
            tamanho_m = [0.20, 0.20, 0.20]
            cor = 0x7D858F
        partes[nome] = {
            "centro": _roblox(centro_m, mps),
            # GAP-044: o TAMANHO tambem permuta, como o centro. Antes ele ia (x, y, z) direto e a
            # Part saia com altura = profundidade, esticando o rig em Y (6,8086 em vez de 6,6071).
            "tamanho": (tamanho_m[0] / mps, tamanho_m[2] / mps, tamanho_m[1] / mps),
            "cor": cor,
            "centro_m": centro_m,
        }

    motores: list[dict] = []
    for osso in ossos:
        pai = osso.get("pai")
        if not pai:
            continue
        nome = osso["nome"]
        p0 = partes[pai]["centro_m"]
        p1 = partes[nome]["centro_m"]
        joint = osso["cabeca"]
        c0 = _roblox([joint[i] - p0[i] for i in range(3)], mps)
        c1 = _roblox([joint[i] - p1[i] for i in range(3)], mps)
        motores.append({"nome": f"{pai}_{nome}", "parte0": pai, "parte1": nome, "c0": c0, "c1": c1})

    # referents deterministas: Workspace=RBX0, Model=RBX1, partes=RBX2.., motores=RBX18.., Humanoid
    refs = {"workspace": "RBX0", "model": "RBX1"}
    for i, osso in enumerate(ossos):
        refs[osso["nome"]] = f"RBX{2 + i}"
    for i, motor in enumerate(motores):
        motor["ref"] = f"RBX{2 + len(ossos) + i}"
    humanoid_ref = f"RBX{2 + len(ossos) + len(motores)}"
    base_ref = f"RBX{3 + len(ossos) + len(motores)}"

    motores_por_parte: dict[str, list[list[str]]] = {}
    for motor in motores:
        linhas = [
            f'<Item class="Motor6D" referent="{motor["ref"]}">',
            "<Properties>",
            f'<string name="Name">{escape(motor["nome"])}</string>',
            f'<Ref name="Part0">{refs[motor["parte0"]]}</Ref>',
            f'<Ref name="Part1">{refs[motor["parte1"]]}</Ref>',
        ]
        linhas += _cframe("C0", *motor["c0"])
        linhas += _cframe("C1", *motor["c1"])
        linhas += ["</Properties>", "</Item>"]
        motores_por_parte.setdefault(motor["parte0"], []).append(linhas)

    linhas = ['<?xml version="1.0" encoding="utf-8"?>', '<roblox version="4">', f'<Item class="Workspace" referent="{refs["workspace"]}">', "<Properties>", '<string name="Name">Workspace</string>', "</Properties>"]
    linhas += [
        f'<Item class="Model" referent="{refs["model"]}">',
        "<Properties>",
        '<string name="Name">Forge3DR15</string>',
        f'<Ref name="PrimaryPart">{refs["HumanoidRootPart"]}</Ref>',
        "</Properties>",
    ]
    for osso in ossos:
        nome = osso["nome"]
        linhas += _parte_xml(
            nome,
            refs[nome],
            partes[nome]["centro"],
            partes[nome]["tamanho"],
            partes[nome]["cor"],
            motores_por_parte.get(nome, []),
        )
    linhas += [
        f'<Item class="Humanoid" referent="{humanoid_ref}">',
        "<Properties>",
        '<string name="Name">Humanoid</string>',
        '<token name="RigType">1</token>',
        "</Properties>",
        "</Item>",
        "</Item>",
    ]
    linhas += [
        f'<Item class="Part" referent="{base_ref}">',
        "<Properties>",
        '<string name="Name">Baseplate</string>',
        '<bool name="Anchored">true</bool>',
        '<Color3uint8 name="Color3uint8">5404741</Color3uint8>',
    ]
    linhas += _vec("size", 40.0, 1.0, 40.0)
    linhas += _cframe("CFrame", 0.0, -0.5, 0.0)
    linhas += ["</Properties>", "</Item>", "</Item>", "</roblox>"]
    xml = "\n".join(linhas) + "\n"
    ElementTree.fromstring(xml)  # falha cedo se o XML estiver quebrado

    if saida is None:
        destino = paths.dir_saida() / "r15" / f"{item_id}.rbxlx"
    else:
        destino = Path(saida).expanduser()
        if str(destino).startswith("/mnt/") or str(destino).startswith("//"):
            raise erro_spec("export-r15: nao escreve em /mnt ou UNC")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(xml, encoding="utf-8")
    return {
        "ok": True,
        "saida": str(destino),
        "bytes": destino.stat().st_size,
        "partes": len(ossos),
        "motores": len(motores),
        "metros_por_stud": mps,
        "textura": False,
    }
