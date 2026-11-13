"""Rota ``blocky`` — geometria declarativa determinística, sem GPU (D8, P1).

A saída é um arquivo de caixas + atlas de paleta. O Blender consome esse JSON e constrói a malha:
o provider não exporta e não aprova nada.

Por que não usar Blockbench: ``.bbmodel`` exige Electron/Node e não tem CLI de export estável.
Aqui o mesmo JSON de caixas gera a geometria direto no ``bpy`` — menos runtime, mais determinismo.

Qualidade: cada caixa declara **papel** (chassi, junta, visor, accent) e **padrão de superfície**.
O atlas pinta uma célula por (cor, padrão) e uma variante clara usada só na face de cima — é o que
faz o bloco ler como peça e não como cubo colorido, sem custar textura maior.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from ..profiles import FRACAO_EMPUNHADURA
from .base import RawAsset

VERSAO = "0.2.3"
PX_CELULA = 16
MAX_CAIXAS = 256

#: papéis semânticos por tipo — a paleta do lote entra nesta ordem
PAPEIS = {
    "personagem_humanoide": ("chassi", "chassi_escuro", "junta", "accent", "visor"),
    "criatura": ("chassi", "chassi_escuro", "junta", "accent", "visor"),
    "prop_equipavel": ("aco", "guarda", "cabo", "accent", "visor"),
    "prop_estatico": ("corpo", "tampa", "rotulo", "accent", "visor"),
    "modulo_cenario": ("chassi", "chassi_escuro", "junta", "accent", "visor"),
    "mapa_setor": ("chassi", "chassi_escuro", "junta", "accent", "visor"),
    "textura": ("chassi", "chassi_escuro", "junta", "accent", "visor"),
}

PALETA_PADRAO = {
    "personagem_humanoide": ("#7d858f", "#3b4048", "#1d2024", "#ff6a1f", "#38e8ff"),
    "criatura": ("#6d7a5f", "#3f4736", "#20241c", "#b23b2e", "#d9d2b0"),
    "prop_equipavel": ("#9aa3ad", "#c9a227", "#4a3728", "#ff5a1f", "#38e8ff"),
    "prop_estatico": ("#8a9099", "#5a6068", "#e8e2d0", "#b23b2e", "#38e8ff"),
    "modulo_cenario": ("#5a5f66", "#3b4048", "#1d2024", "#ff6a1f", "#38e8ff"),
    "mapa_setor": ("#5a5f66", "#3b4048", "#1d2024", "#ff6a1f", "#38e8ff"),
    "textura": ("#7d858f", "#3b4048", "#1d2024", "#ff6a1f", "#38e8ff"),
}

#: (nome, pai, cabeça, cauda) em fração de altura; Z para cima, frente +Y
OSSOS_HUMANOIDE = [
    ("Root", None, (0.0, 0.0, 0.0), (0.0, 0.0, 0.05)),
    ("Hips", "Root", (0.0, 0.0, 0.47), (0.0, 0.0, 0.52)),
    ("Spine", "Hips", (0.0, 0.0, 0.52), (0.0, 0.0, 0.555)),
    ("Spine1", "Spine", (0.0, 0.0, 0.555), (0.0, 0.0, 0.62)),
    ("Chest", "Spine1", (0.0, 0.0, 0.62), (0.0, 0.0, 0.78)),
    ("Neck", "Chest", (0.0, 0.0, 0.78), (0.0, 0.0, 0.845)),
    ("Head", "Neck", (0.0, 0.0, 0.845), (0.0, 0.0, 1.00)),
    ("Shoulder.L", "Chest", (0.10, 0.0, 0.76), (0.15, 0.0, 0.76)),
    ("UpperArm.L", "Shoulder.L", (0.17, 0.0, 0.76), (0.17, 0.0, 0.60)),
    ("LowerArm.L", "UpperArm.L", (0.17, 0.0, 0.60), (0.17, 0.0, 0.44)),
    ("Hand.L", "LowerArm.L", (0.17, 0.0, 0.44), (0.17, 0.0, 0.36)),
    ("Shoulder.R", "Chest", (-0.10, 0.0, 0.76), (-0.15, 0.0, 0.76)),
    ("UpperArm.R", "Shoulder.R", (-0.17, 0.0, 0.76), (-0.17, 0.0, 0.60)),
    ("LowerArm.R", "UpperArm.R", (-0.17, 0.0, 0.60), (-0.17, 0.0, 0.44)),
    ("Hand.R", "LowerArm.R", (-0.17, 0.0, 0.44), (-0.17, 0.0, 0.36)),
    ("UpperLeg.L", "Hips", (0.065, 0.0, 0.44), (0.065, 0.0, 0.235)),
    ("LowerLeg.L", "UpperLeg.L", (0.065, 0.0, 0.235), (0.065, 0.0, 0.065)),
    ("Foot.L", "LowerLeg.L", (0.065, 0.0, 0.065), (0.065, 0.12, 0.02)),
    ("Toe.L", "Foot.L", (0.065, 0.12, 0.02), (0.065, 0.16, 0.012)),
    ("UpperLeg.R", "Hips", (-0.065, 0.0, 0.44), (-0.065, 0.0, 0.235)),
    ("LowerLeg.R", "UpperLeg.R", (-0.065, 0.0, 0.235), (-0.065, 0.0, 0.065)),
    ("Foot.R", "LowerLeg.R", (-0.065, 0.0, 0.065), (-0.065, 0.12, 0.02)),
    ("Toe.R", "Foot.R", (-0.065, 0.12, 0.02), (-0.065, 0.16, 0.012)),
]


#: R15 (Roblox) — 16 partes. O blocky usa os mesmos templates de caixa, remapeando o osso.
OSSOS_R15 = [
    ("HumanoidRootPart", None, (0.0, 0.0, 0.0), (0.0, 0.0, 0.05)),
    ("LowerTorso", "HumanoidRootPart", (0.0, 0.0, 0.44), (0.0, 0.0, 0.52)),
    ("UpperTorso", "LowerTorso", (0.0, 0.0, 0.52), (0.0, 0.0, 0.78)),
    ("Head", "UpperTorso", (0.0, 0.0, 0.78), (0.0, 0.0, 1.00)),
    ("LeftUpperArm", "UpperTorso", (0.10, 0.0, 0.76), (0.17, 0.0, 0.60)),
    ("LeftLowerArm", "LeftUpperArm", (0.17, 0.0, 0.60), (0.17, 0.0, 0.44)),
    ("LeftHand", "LeftLowerArm", (0.17, 0.0, 0.44), (0.17, 0.0, 0.36)),
    ("RightUpperArm", "UpperTorso", (-0.10, 0.0, 0.76), (-0.17, 0.0, 0.60)),
    ("RightLowerArm", "RightUpperArm", (-0.17, 0.0, 0.60), (-0.17, 0.0, 0.44)),
    ("RightHand", "RightLowerArm", (-0.17, 0.0, 0.44), (-0.17, 0.0, 0.36)),
    ("LeftUpperLeg", "LowerTorso", (0.065, 0.0, 0.44), (0.065, 0.0, 0.235)),
    ("LeftLowerLeg", "LeftUpperLeg", (0.065, 0.0, 0.235), (0.065, 0.0, 0.065)),
    ("LeftFoot", "LeftLowerLeg", (0.065, 0.0, 0.065), (0.065, 0.12, 0.02)),
    ("RightUpperLeg", "LowerTorso", (-0.065, 0.0, 0.44), (-0.065, 0.0, 0.235)),
    ("RightLowerLeg", "RightUpperLeg", (-0.065, 0.0, 0.235), (-0.065, 0.0, 0.065)),
    ("RightFoot", "RightLowerLeg", (-0.065, 0.0, 0.065), (-0.065, 0.12, 0.02)),
]

#: osso do template godot -> parte R15 que recebe a caixa
MAPA_OSSO_R15 = {
    "Hips": "LowerTorso",
    "Spine": "UpperTorso",
    "Spine1": "UpperTorso",
    "Chest": "UpperTorso",
    "Neck": "Head",
    "Head": "Head",
    "Shoulder.L": "LeftUpperArm",
    "UpperArm.L": "LeftUpperArm",
    "LowerArm.L": "LeftLowerArm",
    "Hand.L": "LeftHand",
    "Shoulder.R": "RightUpperArm",
    "UpperArm.R": "RightUpperArm",
    "LowerArm.R": "RightLowerArm",
    "Hand.R": "RightHand",
    "UpperLeg.L": "LeftUpperLeg",
    "LowerLeg.L": "LeftLowerLeg",
    "Foot.L": "LeftFoot",
    "UpperLeg.R": "RightUpperLeg",
    "LowerLeg.R": "RightLowerLeg",
    "Foot.R": "RightFoot",
    "Toe.L": "LeftFoot",
    "Toe.R": "RightFoot",
}


# ---------------------------------------------------------------- cores


def _rgb(hex_cor: str) -> tuple[int, int, int]:
    h = hex_cor.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _ajustar(cor: tuple[int, int, int], fator: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * fator))) for c in cor)  # type: ignore[return-value]


def _cores(tipo: str, item: dict) -> dict[str, str]:
    """Mapeia a paleta do lote nos papéis do tipo. Ordem fixa = determinismo."""
    papeis = PAPEIS.get(tipo, PAPEIS["textura"])
    padrao = PALETA_PADRAO.get(tipo, PALETA_PADRAO["textura"])
    bruta = list(item.get("_paleta") or [])
    valores = {}
    for indice, papel in enumerate(papeis):
        if indice < len(bruta):
            valores[papel] = bruta[indice]
        else:
            valores[papel] = padrao[indice]
    return valores


# ---------------------------------------------------------------- templates


def _template_humanoide(cores: dict) -> list[dict]:
    """Androide humanoide em peças: 26 caixas, uma por segmento visível."""

    def caixa(nome, osso, x0, y0, z0, x1, y1, z1, cor, padrao) -> dict:
        return {
            "nome": nome,
            "osso": osso,
            "min": [min(x0, x1), min(y0, y1), min(z0, z1)],
            "max": [max(x0, x1), max(y0, y1), max(z0, z1)],
            "cor": cor,
            "padrao": padrao,
        }

    pecas = [
        caixa("pelve", "Hips", -0.11, -0.075, 0.44, 0.11, 0.075, 0.50, cores["junta"], "junta"),
        caixa(
            "abdomen", "Spine", -0.095, -0.07, 0.50, 0.095, 0.07, 0.555,
            cores["chassi_escuro"], "junta",
        ),
        caixa("peito", "Chest", -0.135, -0.085, 0.555, 0.135, 0.085, 0.78, cores["chassi"], "chapa"),
        caixa(
            "nucleo", "Chest", -0.035, 0.085, 0.63, 0.035, 0.098, 0.71,
            cores["accent"], "accent",
        ),
        caixa("pescoco", "Neck", -0.045, -0.05, 0.78, 0.045, 0.05, 0.845, cores["junta"], "junta"),
        caixa("cabeca", "Head", -0.085, -0.085, 0.815, 0.085, 0.085, 1.00, cores["chassi"], "chapa"),
        caixa("visor", "Head", -0.065, 0.085, 0.90, 0.065, 0.096, 0.935, cores["visor"], "visor"),
    ]

    for lado, sinal in (("L", 1.0), ("R", -1.0)):
        pecas += [
            caixa(
                f"ombro_{lado}", f"Shoulder.{lado}", 0.135 * sinal, -0.085, 0.72,
                0.205 * sinal, 0.085, 0.80, cores["chassi_escuro"], "chapa",
            ),
            caixa(
                f"braco_{lado}", f"UpperArm.{lado}", 0.148 * sinal, -0.06, 0.555,
                0.192 * sinal, 0.06, 0.735, cores["chassi"], "chapa",
            ),
            caixa(
                f"cotovelo_{lado}", f"UpperArm.{lado}", 0.150 * sinal, -0.062, 0.525,
                0.192 * sinal, 0.062, 0.56, cores["junta"], "junta",
            ),
            caixa(
                f"antebraco_{lado}", f"LowerArm.{lado}", 0.148 * sinal, -0.065, 0.395,
                0.196 * sinal, 0.065, 0.530, cores["chassi"], "chapa",
            ),
            caixa(
                f"mao_{lado}", f"Hand.{lado}", 0.148 * sinal, -0.068, 0.335,
                0.196 * sinal, 0.068, 0.40, cores["chassi_escuro"], "junta",
            ),
            caixa(
                # menor que a pelve e sobreposta a ela: sem canto exato e sem fenda ao girar
                f"coxa_{lado}", f"UpperLeg.{lado}", 0.018 * sinal, -0.072, 0.210,
                0.105 * sinal, 0.072, 0.455, cores["chassi"], "chapa",
            ),
            caixa(
                f"joelho_{lado}", f"UpperLeg.{lado}", 0.025 * sinal, -0.078, 0.195,
                0.108 * sinal, 0.078, 0.235, cores["junta"], "junta",
            ),
            caixa(
                f"canela_{lado}", f"LowerLeg.{lado}", 0.025 * sinal, -0.08, 0.045,
                0.105 * sinal, 0.08, 0.215, cores["chassi_escuro"], "chapa",
            ),
            caixa(
                f"pe_{lado}", f"Foot.{lado}", 0.018 * sinal, -0.02, 0.0,
                0.112 * sinal, 0.145, 0.065, cores["chassi_escuro"], "chapa",
            ),
        ]
    return pecas


def _template_arma(cores: dict) -> list[dict]:
    return [
        {
            "nome": "cabo",
            "osso": None,
            "min": [-0.022, -0.022, 0.00],
            "max": [0.022, 0.022, 0.20],
            "cor": cores["cabo"],
            "padrao": "junta",
        },
        {
            "nome": "guarda",
            "osso": None,
            "min": [-0.110, -0.035, 0.20],
            "max": [0.110, 0.035, 0.24],
            "cor": cores["guarda"],
            "padrao": "chapa",
        },
        {
            "nome": "lamina",
            "osso": None,
            "min": [-0.045, -0.014, 0.24],
            "max": [0.045, 0.014, 1.00],
            "cor": cores["aco"],
            "padrao": "chapa",
        },
    ]


def _template_capa(cores: dict) -> list[dict]:
    """Capa longa atras do corpo. Peca estatica: no Godot e filha do osso Chest."""

    def caixa(nome, osso, x0, y0, z0, x1, y1, z1, cor, padrao) -> dict:
        return {
            "nome": nome,
            "osso": osso,
            "min": [min(x0, x1), min(y0, y1), min(z0, z1)],
            "max": [max(x0, x1), max(y0, y1), max(z0, z1)],
            "cor": cor,
            "padrao": padrao,
        }

    return [
        caixa(
            "gola", "Chest", -0.13, -0.16, 0.76, 0.13, -0.075, 0.82,
            cores["chassi_escuro"], "chapa",
        ),
        caixa(
            "capa_superior", "Chest", -0.17, -0.18, 0.60, 0.17, -0.075, 0.78,
            cores["chassi"], "chapa",
        ),
        caixa(
            "capa_meio", "Spine1", -0.20, -0.19, 0.40, 0.20, -0.075, 0.62,
            cores["chassi"], "chapa",
        ),
        caixa(
            "capa_inferior", "Spine", -0.23, -0.20, 0.18, 0.23, -0.075, 0.42,
            cores["chassi_escuro"], "chapa",
        ),
        caixa(
            "capa_ponta", "Hips", -0.20, -0.19, 0.02, 0.20, -0.075, 0.20,
            cores["accent"], "accent",
        ),
    ]


def _template_frasco(cores: dict) -> list[dict]:
    return [
        {
            "nome": "corpo",
            "osso": None,
            "min": [-0.30, -0.30, 0.00],
            "max": [0.30, 0.30, 0.62],
            "cor": cores["corpo"],
            "padrao": "chapa",
        },
        {
            "nome": "rotulo",
            "osso": None,
            "min": [-0.24, -0.32, 0.22],
            "max": [0.24, 0.32, 0.40],
            "cor": cores["rotulo"],
            "padrao": "accent",
        },
        {
            "nome": "gargalo",
            "osso": None,
            "min": [-0.12, -0.12, 0.62],
            "max": [0.12, 0.12, 0.78],
            "cor": cores["tampa"],
            "padrao": "junta",
        },
        {
            "nome": "tampa",
            "osso": None,
            "min": [-0.15, -0.15, 0.78],
            "max": [0.15, 0.15, 1.00],
            "cor": cores["chassi"] if "chassi" in cores else cores["tampa"],
            "padrao": "chapa",
        },
    ]


def _template_bloco(cores: dict) -> list[dict]:
    return [
        {
            "nome": "piso",
            "osso": None,
            "min": [-0.50, -0.50, 0.00],
            "max": [0.50, 0.50, 0.10],
            "cor": cores["junta"],
            "padrao": "junta",
        },
        {
            "nome": "bloco",
            "osso": None,
            "min": [-0.35, -0.35, 0.10],
            "max": [0.35, 0.35, 1.00],
            "cor": cores["chassi"],
            "padrao": "chapa",
        },
    ]


def _caixas(tipo: str, altura: float, item: dict) -> list[dict]:
    cores = _cores(tipo, item)
    parte = item.get("parte")
    if parte == "capa":
        pecas = _template_capa(cores)
    elif parte == "arma":
        pecas = _template_arma(cores)
    elif parte == "corpo":
        pecas = _template_humanoide(cores)
    elif tipo in ("personagem_humanoide", "criatura"):
        pecas = _template_humanoide(cores)
    elif tipo == "prop_equipavel":
        pecas = _template_arma(cores)
    elif tipo == "prop_estatico":
        pecas = _template_frasco(cores)
    elif tipo in ("modulo_cenario", "mapa_setor"):
        pecas = _template_bloco(cores)
    else:
        pecas = _template_bloco(cores)

    for peca in pecas:
        for campo in ("min", "max"):
            peca[campo] = [round(v * altura, 4) for v in peca[campo]]
    return pecas


# ---------------------------------------------------------------- atlas


def _pintar(padrao: str, desenho: ImageDraw.ImageDraw, x0: int, y0: int, cor, claro: bool) -> None:
    """Uma célula = um padrão de superfície. `claro` gera a variante da face de cima."""
    base = _ajustar(cor, 1.12) if claro else cor
    p, q = PX_CELULA, PX_CELULA
    desenho.rectangle([x0, y0, x0 + p - 1, y0 + q - 1], fill=(*base, 255))

    if padrao == "junta":
        escuro = _ajustar(base, 0.45)
        for yy in (y0 + 5, y0 + 10):
            desenho.line([x0, yy, x0 + p - 1, yy], fill=(*escuro, 255))
        desenho.rectangle([x0, y0, x0 + p - 1, y0 + q - 1], outline=(*_ajustar(base, 0.6), 255))
    elif padrao == "visor":
        luz = _ajustar(base, 1.35)
        desenho.rectangle([x0 + 1, y0 + 6, x0 + p - 2, y0 + 9], fill=(*luz, 255))
        desenho.rectangle([x0, y0, x0 + p - 1, y0 + q - 1], outline=(*_ajustar(base, 0.5), 255))
    elif padrao == "accent":
        desenho.rectangle([x0 + 2, y0 + 2, x0 + p - 3, y0 + q - 3], fill=(*base, 255))
        desenho.rectangle([x0, y0, x0 + p - 1, y0 + q - 1], outline=(*_ajustar(base, 0.55), 255))
        desenho.line([x0 + 2, y0 + 3, x0 + p - 3, y0 + 3], fill=(*_ajustar(base, 1.3), 255))
    else:  # chapa
        desenho.rectangle([x0, y0, x0 + p - 1, y0 + q - 1], outline=(*_ajustar(base, 0.68), 255))
        desenho.line([x0 + 1, y0 + 1, x0 + p - 2, y0 + 1], fill=(*_ajustar(base, 1.10), 255))
        desenho.line([x0 + 1, y0 + 1, x0 + 1, y0 + q - 2], fill=(*_ajustar(base, 1.05), 255))


def _atlas(caixas: list[dict], destino: Path) -> tuple[str, int]:
    """Aloca duas células por (cor, padrão): face lateral e face de cima clareada."""
    pares: list[tuple[tuple[int, int, int], str]] = []
    for caixa in caixas:
        chave = (_rgb(caixa["cor"]), caixa["padrao"])
        if chave not in pares:
            pares.append(chave)
    pares = pares[: MAX_CAIXAS // 2]

    celulas = max(1, len(pares) * 2)
    colunas = max(2, math.ceil(math.sqrt(celulas)))
    tam = 32
    while tam < min(256, colunas * PX_CELULA):
        tam *= 2
    colunas = tam // PX_CELULA

    img = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(img)
    regioes: dict[tuple[tuple[int, int, int], str], tuple[list[float], list[float]]] = {}

    def uv(coluna: int, linha: int) -> list[float]:
        x0 = coluna * PX_CELULA
        y0 = linha * PX_CELULA
        return [
            round((x0 + 1) / tam, 6),
            round(1.0 - (y0 + PX_CELULA - 1) / tam, 6),
            round((x0 + PX_CELULA - 1) / tam, 6),
            round(1.0 - y0 / tam, 6),
        ]

    for indice, (cor, padrao) in enumerate(pares):
        col_lado, lin_lado = (indice * 2) % colunas, (indice * 2) // colunas
        col_topo, lin_topo = (indice * 2 + 1) % colunas, (indice * 2 + 1) // colunas
        _pintar(padrao, desenho, col_lado * PX_CELULA, lin_lado * PX_CELULA, cor, False)
        _pintar(padrao, desenho, col_topo * PX_CELULA, lin_topo * PX_CELULA, cor, True)
        regioes[(cor, padrao)] = (uv(col_lado, lin_lado), uv(col_topo, lin_topo))

    for caixa in caixas:
        chave = (_rgb(caixa["cor"]), caixa["padrao"])
        lado, topo = regioes.get(chave, ([0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 1.0, 1.0]))
        caixa["uv"] = lado
        caixa["uv_topo"] = topo

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
    # D58: empunhadura e uma fracao fixa da altura, igual nas duas rotas. Antes o blocky
    # usava o centro da caixa 'cabo' e 10% no fallback, enquanto o postprocesso usava 20%:
    # a mesma regra gerava pivos fisicos diferentes e o G2 nao media nenhum dos dois.
    pivos["empunhadura"] = [cx, cy, round(zmin + FRACAO_EMPUNHADURA * (zmax - zmin), 6)]
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
        nome_atlas, atlas_px = _atlas(caixas, destino)

        ossos: list[dict] = []
        if item.get("auto_rig"):
            if item.get("esqueleto") == "r15@1":
                # R15: 16 partes; as caixas do template godot sao remapeadas para as partes R15
                for caixa in caixas:
                    osso_caixa = caixa.get("osso")
                    caixa["osso"] = (
                        MAPA_OSSO_R15.get(osso_caixa, osso_caixa)
                        if isinstance(osso_caixa, str)
                        else osso_caixa
                    )
                tabela = OSSOS_R15
            else:
                tabela = OSSOS_HUMANOIDE
            ossos = [
                {
                    "nome": nome,
                    "pai": pai,
                    "cabeca": [round(v * altura, 4) for v in cabeca],
                    "cauda": [round(v * altura, 4) for v in cauda],
                }
                for (nome, pai, cabeca, cauda) in tabela
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
            "parte": item.get("parte"),
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
