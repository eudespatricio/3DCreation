"""Rota `modular`: um setor de dungeon como asset (D74).

O provider roda o WFC (`forge3d.modular`) com a seed do item e emite **o setor pedido** no mesmo
bruto do blocky (`bruto-blocky@1`): caixas + atlas + pivôs. O pós-processo não sabe a diferença —
exporta malha, colisor `box`, pivot `centro`, tudo pelo perfil.

Por que um setor por item: o portão da P4 exige "sem infinito de draw calls por setor". Cada setor
publicado é uma malha + um material (1 draw call); se o jogo quiser o andar inteiro, junta os setores
na engine, não numa malha gigante.

Determinismo: a seed + grade + catálogo dão o mesmo layout; o setor é recortado dele. O `modelo.json`
leva o layout inteiro (provenance), então o mesmo setor pode ser reexportado isolado.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import modular as catalogo_modular
from .base import RawAsset
from .blocky import _atlas, _pivos

VERSAO = "0.2.1"

#: altura de pé-direito quando o item não declara `altura_metros` (mapa_setor não exige no schema)
ALTURA_PADRAO = 2.4
#: lado do módulo em metros
TAMANHO_PADRAO = 4.0

#: papel da caixa -> padrão de superfície (a cor vem da paleta do lote)
PADRAO = {"piso": "junta", "parede": "chapa", "pilar": "chapa"}

#: paleta de reserva quando o lote nao declara nenhuma (mesma familia do blocky)
PALETA_PADRAO = ("#7d858f", "#3b4048", "#1d2024")


def _luminancia(hexadecimal: str) -> float:
    valor = hexadecimal.lstrip("#")
    r, g, b = (int(valor[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _cores(item: dict) -> dict[str, str]:
    """Piso = cor mais escura, parede = mais clara, pilar = do meio (ordem fixa = determinismo)."""
    paleta = [c for c in (item.get("_paleta") or []) if isinstance(c, str) and c.startswith("#")]
    if not paleta:
        paleta = list(PALETA_PADRAO)
    ordenada = sorted(paleta, key=_luminancia)
    return {
        "piso": ordenada[0],
        "parede": ordenada[-1],
        "pilar": ordenada[len(ordenada) // 2],
    }


class ModularProvider:
    nome = "modular"
    versao = VERSAO
    determinism = "D1"
    usa_gpu = False
    licenca = {
        "modelo": "procedural (sem modelo de terceiro)",
        "uso_comercial": True,
        "notice": "Asset gerado proceduralmente por Forge3D na rota modular.",
    }

    def capabilities(self) -> set[str]:
        return {"modular", "cenario", "setor"}

    def custo(self, item: dict, perfil: dict) -> dict:
        return {"segundos_estimados": 1.0, "vram_mb": 0, "disco_mb": 1}

    def preflight(self) -> tuple[bool, str]:
        return True, "pronto"

    def gerar(self, item: dict, perfil: dict, destino: Path) -> RawAsset:
        destino.mkdir(parents=True, exist_ok=True)
        bloco = item.get("modular") or {}
        grade_lista = [int(v) for v in (bloco.get("grade") or [2, 2])]
        grade: tuple[int, int] = (grade_lista[0], grade_lista[1])
        nomes = [str(m) for m in (bloco.get("modulos") or sorted(catalogo_modular.CATALOGO))]
        setor = tuple(int(v) for v in (bloco.get("setor") or [0, 0]))
        tamanho = float(bloco.get("tamanho_modulo") or TAMANHO_PADRAO)
        altura = float(item.get("altura_metros") or ALTURA_PADRAO)
        seed = int(item.get("seed") or 0)

        layout = catalogo_modular.gerar_layout(grade, nomes, seed)
        if not (0 <= setor[0] < grade[0] and 0 <= setor[1] < grade[1]):
            raise ValueError(f"setor {setor} fora da grade {grade}")
        nome_modulo = layout[setor[1]][setor[0]]

        caixas = catalogo_modular.caixas_do_modulo(nome_modulo, tamanho, altura)
        cores = _cores(item)
        for caixa in caixas:
            papel = caixa.pop("papel")
            caixa["cor"] = cores[papel]
            caixa["padrao"] = PADRAO[papel]
            caixa["osso"] = None
        nome_atlas, atlas_px = _atlas(caixas, destino)
        pivos = _pivos(caixas, item["tipo"])

        modelo = {
            "schema": "forge3d/bruto-blocky@1",
            "tipo": item["tipo"],
            "altura_m": round(altura, 4),
            "atlas": nome_atlas,
            "atlas_px": atlas_px,
            "caixas": caixas,
            "ossos": [],
            "pivos": pivos,
            "parte": item.get("parte"),
            "modular": {
                "seed": seed,
                "grade": list(grade),
                "setor": list(setor),
                "modulo": nome_modulo,
                "tamanho_modulo": tamanho,
                "layout": layout,
            },
        }
        caminho = destino / "modelo.json"
        caminho.write_text(json.dumps(modelo, ensure_ascii=False, indent=1), encoding="utf-8")
        return RawAsset(
            dir=destino,
            schema="forge3d/bruto-blocky@1",
            determinism="D1",
            arquivos=[caminho, destino / nome_atlas],
            meta={
                "custo": self.custo(item, perfil),
                "modular": modelo["modular"],
                "caixas": len(caixas),
            },
        )
