"""Rota ``blocky`` — geometria declarativa determinística, sem GPU (D8, P1).

A saida e um arquivo de caixas + atlas de paleta. O Blender consome esse JSON e constroi a malha:
o provider nao exporta e nao aprova nada.

Por que nao usar Blockbench: ``.bbmodel`` exige Electron/Node e nao tem CLI de export estavel.
Aqui o mesmo JSON de caixas gera a geometria direto no ``bpy`` — menos runtime, mais determinismo.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from .base import RawAsset

VERSAO = "0.1.1"
PX_CELULA = 16
MAX_CAIXAS = 256

PALETA_PADRAO = {
    "prop_equipavel": ["#3a3a40", "#c9a227", "#ff5a1f"],
    "prop_estatico": ["#2a2a30", "#b23b2e", "#c9a227"],
    "prop_estatico_alt": ["#4a5a3a", "#8a8f7a", "#d9d2b0"],
    "personagem_humanoide": ["#8a8f7a", "#5a5f52", "#c9a227", "#3a3a40"],
    "criatura": ["#4a5a3a", "#8a8f7a", "#b23b2e"],
    "modulo_cenario": ["#2a2a30", "#4a4438", "#6a5a4a"],
    "mapa_setor": ["#2a2a30", "#4a4438", "#6a5a4a"],
    "textura": ["#3a3a40", "#c9a227"],
}

#: (nome, pai, cabeca, cauda) em fracao de altura, eixo Z para cima, frente +Y
OSSOS_HUMANOIDE = [
    ("Root", None, (0.0, 0.0, 0.0), (0.0, 0.0, 0.05)),
    ("Hips", "Root", (0.0, 0.0, 0.48), (0.0, 0.0, 0.54)),
    ("Spine", "Hips", (0.0, 0.0, 0.54), (0.0, 0.0, 0.62)),
    ("Spine1", "Spine", (0.0, 0.0, 0.62), (0.0, 0.0, 0.70)),
    ("Chest", "Spine1", (0.0, 0.0, 0.70), (0.0, 0.0, 0.80)),
    ("Neck", "Chest", (0.0, 0.0, 0.80), (0.0, 0.0, 0.86)),
    ("Head", "Neck", (0.0, 0.0, 0.86), (0.0, 0.0, 1.00)),
    ("Shoulder.L", "Chest", (0.06, 0.0, 0.78), (0.16, 0.0, 0.78)),
    ("UpperArm.L", "Shoulder.L", (0.16, 0.0, 0.78), (0.18, 0.0, 0.58)),
    ("LowerArm.L", "UpperArm.L", (0.18, 0.0, 0.58), (0.18, 0.0, 0.40)),
    ("Hand.L", "LowerArm.L", (0.18, 0.0, 0.40), (0.18, 0.0, 0.34)),
    ("Shoulder.R", "Chest", (-0.06, 0.0, 0.78), (-0.16, 0.0, 0.78)),
    ("UpperArm.R", "Shoulder.R", (-0.16, 0.0, 0.78), (-0.18, 0.0, 0.58)),
    ("LowerArm.R", "UpperArm.R", (-0.18, 0.0, 0.58), (-0.18, 0.0, 0.40)),
    ("Hand.R", "LowerArm.R", (-0.18, 0.0, 0.40), (-0.18, 0.0, 0.34)),
    ("UpperLeg.L", "Hips", (0.06, 0.0, 0.48), (0.06, 0.0, 0.26)),
    ("LowerLeg.L", "UpperLeg.L", (0.06, 0.0, 0.26), (0.06, 0.0, 0.06)),
    ("Foot.L", "LowerLeg.L", (0.06, 0.0, 0.06), (0.06, 0.10, 0.02)),
    ("Toe.L", "Foot.L", (0.06, 0.10, 0.02), (0.06, 0.14, 0.015)),
    ("UpperLeg.R", "Hips", (-0.06, 0.0, 0.48), (-0.06, 0.0, 0.26)),
    ("LowerLeg.R", "UpperLeg.R", (-0.06, 0.0, 0.26), (-0.06, 0.0, 0.06)),
    ("Foot.R", "LowerLeg.R", (-0.06, 0.0, 0.06), (-0.06, 0.10, 0.02)),
    ("Toe.R", "Foot.R", (-0.06, 0.10, 0.02), (-0.06, 0.14, 0.015)),
]


# ---------------------------------------------------------------- templates


def _caixas(tipo: str, altura: float, item: dict) -> list[dict]:
    """Caixas em metros. Fracao de altura × altura, arredondada para 1e-4 (determinismo)."""

    def cx(nome: str, osso: str | None, x0, y0, z0, x1, y1, z1) -> dict:
        def m(v: float) -> float:
            return round(v * altura, 4)

        return {
            "nome": nome,
            "osso": osso,
            "min": [m(x0), m(y0), m(z0)],
            "max": [m(x1), m(y1), m(z1)],
        }

    if tipo == "prop_equipavel":
        return [
            cx("grip", None, -0.022, -0.022, 0.00, 0.022, 0.022, 0.20),
            cx("guard", None, -0.110, -0.035, 0.20, 0.110, 0.035, 0.24),
            cx("blade", None, -0.045, -0.014, 0.24, 0.045, 0.014, 1.00),
        ]
    if tipo == "prop_estatico":
        return [
            cx("corpo", None, -0.30, -0.30, 0.00, 0.30, 0.30, 0.62),
            cx("gargalo", None, -0.12, -0.12, 0.62, 0.12, 0.12, 0.78),
            cx("tampa", None, -0.15, -0.15, 0.78, 0.15, 0.15, 1.00),
        ]
    if tipo in ("personagem_humanoide", "criatura"):
        return [
            cx("cabeca", "Head", -0.09, -0.09, 0.84, 0.09, 0.09, 1.00),
            cx("tronco", "Chest", -0.14, -0.08, 0.48, 0.14, 0.08, 0.82),
            cx("braco_L", "UpperArm.L", 0.14, -0.06, 0.34, 0.22, 0.06, 0.80),
            cx("braco_R", "UpperArm.R", -0.22, -0.06, 0.34, -0.14, 0.06, 0.80),
            cx("perna_L", "UpperLeg.L", 0.02, -0.06, 0.00, 0.10, 0.06, 0.48),
            cx("perna_R", "UpperLeg.R", -0.10, -0.06, 0.00, -0.02, 0.06, 0.48),
        ]
    if tipo in ("modulo_cenario", "mapa_setor"):
        return [
            cx("piso", None, -0.50, -0.50, 0.00, 0.50, 0.50, 0.10),
            cx("bloco", None, -0.35, -0.35, 0.10, 0.35, 0.35, 1.00),
        ]
    # textura e tipos desconhecidos: uma face plana
    return [cx("plano", None, -0.50, -0.005, 0.00, 0.50, 0.005, 1.00)]


# ---------------------------------------------------------------- atlas


def _rgb(hex_cor: str) -> tuple[int, int, int]:
    h = hex_cor.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _escurecer(cor: tuple[int, int, int], fator: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * fator))) for c in cor)  # type: ignore[return-value]


def _atlas(caixas: list[dict], cores: list[tuple[int, int, int]], destino: Path) -> tuple[str, int]:
    n = min(len(caixas), MAX_CAIXAS)
    cols = max(2, math.ceil(math.sqrt(n)))
    # G4 exige potencia de 2: arredonda para cima e recalcula as colunas
    tam = 32
    while tam < min(256, cols * PX_CELULA):
        tam *= 2
    cols = tam // PX_CELULA

    img = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(img)

    for indice, caixa in enumerate(caixas[:MAX_CAIXAS]):
        col = indice % cols
        linha = indice // cols
        x0 = col * PX_CELULA
        y0 = linha * PX_CELULA
        base = cores[indice % len(cores)]
        desenho.rectangle([x0, y0, x0 + PX_CELULA - 1, y0 + PX_CELULA - 1], fill=(*base, 255))
        borda = _escurecer(base, 0.72)
        desenho.rectangle(
            [x0, y0, x0 + PX_CELULA - 1, y0 + PX_CELULA - 1], outline=(*borda, 255)
        )
        # 1 px de margem contra sangramento; v invertido (Blender tem origem embaixo)
        caixa["uv"] = [
            round((x0 + 1) / tam, 6),
            round(1.0 - (y0 + PX_CELULA - 1) / tam, 6),
            round((x0 + PX_CELULA - 1) / tam, 6),
            round(1.0 - y0 / tam, 6),
        ]

    caminho = destino / "atlas.png"
    img.save(caminho, format="PNG", optimize=False)
    return "atlas.png", tam


# ---------------------------------------------------------------- pivos


def _pivos(caixas: list[dict], tipo: str) -> dict:
    xs = [c["min"][0] for c in caixas] + [c["max"][0] for c in caixas]
    ys = [c["min"][1] for c in caixas] + [c["max"][1] for c in caixas]
    zs = [c["min"][2] for c in caixas] + [c["max"][2] for c in caixas]
    cx, cy = round((min(xs) + max(xs)) / 2, 6), round((min(ys) + max(ys)) / 2, 6)
    zmin, zmax = min(zs), max(zs)

    pivos = {
        "base": [cx, cy, zmin],
        "centro": [cx, cy, round((zmin + zmax) / 2, 6)],
        "topo": [cx, cy, zmax],
        "origem": [0.0, 0.0, 0.0],
    }
    if tipo == "prop_equipavel":
        cabo = next((c for c in caixas if c["nome"] == "grip"), caixas[0])
        pivos["empunhadura"] = [
            round((cabo["min"][0] + cabo["max"][0]) / 2, 6),
            round((cabo["min"][1] + cabo["max"][1]) / 2, 6),
            round((cabo["min"][2] + cabo["max"][2]) / 2, 6),
        ]
    else:
        pivos["empunhadura"] = pivos["base"]
    return pivos


# ---------------------------------------------------------------- provider


class BlockyProvider:
    nome = "blocky"
    versao = VERSAO
    determinism = "D1"
    usa_gpu = False
    licenca = {
        "modelo": "procedural (sem modelo de terceiro)",
        "uso_comercial": True,
        "notice": "Asset gerado proceduralmente por Forge3D na rota blocky.",
    }

    def capabilities(self) -> set[str]:
        return {"blocky", "riggable", "voxel"}

    def custo(self, item: dict, perfil: dict) -> dict:
        return {"segundos_estimados": 3.0, "vram_mb": 0, "disco_mb": 1}

    def preflight(self) -> tuple[bool, str]:
        return True, "pronto"

    def gerar(self, item: dict, perfil: dict, destino: Path) -> RawAsset:
        import json

        destino.mkdir(parents=True, exist_ok=True)
        altura = float(item["altura_metros"])
        tipo = item["tipo"]

        caixas = _caixas(tipo, altura, item)
        cores = [_rgb(c) for c in (item.get("_paleta") or PALETA_PADRAO.get(tipo, PALETA_PADRAO["prop_estatico"]))]
        nome_atlas, atlas_px = _atlas(caixas, cores, destino)

        ossos: list[dict] = []
        if item.get("auto_rig"):
            ossos = [
                {
                    "nome": nome,
                    "pai": pai,
                    "cabeca": [round(v * altura, 4) for v in cabeca],
                    "cauda": [round(v * altura, 4) for v in cauda],
                }
                for (nome, pai, cabeca, cauda) in OSSOS_HUMANOIDE
            ]

        modelo = {
            "schema": "forge3d/bruto-blocky@1",
            "tipo": tipo,
            "altura_m": altura,
            "atlas": nome_atlas,
            "atlas_px": atlas_px,
            "caixas": caixas,
            "ossos": ossos,
            "pivos": _pivos(caixas, tipo),
        }
        arq = destino / "modelo.json"
        arq.write_text(
            json.dumps(modelo, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        return RawAsset(
            dir=destino,
            schema=modelo["schema"],
            determinism=self.determinism,
            arquivos=[arq, destino / nome_atlas],
            meta={"caixas": len(caixas), "ossos": len(ossos), "atlas_px": atlas_px},
        )
