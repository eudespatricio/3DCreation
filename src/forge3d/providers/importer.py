"""Rota ``import`` — asset feito a mao entra no mesmo trilho (P1).

Existe porque o asset mais importante do jogo e o que o artista fez a mao, e ele nao pode ficar
fora do QC, da escala padronizada e do manifesto.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .base import RawAsset

VERSAO = "0.1.0"
EXTENSOES = {".glb", ".gltf", ".obj", ".fbx", ".blend"}


class ImportProvider:
    nome = "import"
    versao = VERSAO
    determinism = "D1"
    usa_gpu = False
    licenca = {
        "modelo": "asset de autoria propria",
        "uso_comercial": True,
        "notice": "Asset fornecido pelo projeto; autoria e licenca sao responsabilidade do projeto.",
    }

    def capabilities(self) -> set[str]:
        return {"import", "manual"}

    def custo(self, item: dict, perfil: dict) -> dict:
        return {"segundos_estimados": 4.0, "vram_mb": 0, "disco_mb": 2}

    def preflight(self) -> tuple[bool, str]:
        return True, "pronto"

    def gerar(self, item: dict, perfil: dict, destino: Path) -> RawAsset:
        from ..errors import erro_provider

        origem = Path(item["origem"]).expanduser()
        if not origem.is_file():
            raise erro_provider(f"origem inexistente: {origem}", origem=str(origem))
        if origem.suffix.lower() not in EXTENSOES:
            raise erro_provider(
                f"extensao nao suportada: {origem.suffix} (aceitas: {', '.join(sorted(EXTENSOES))})",
                origem=str(origem),
            )

        destino.mkdir(parents=True, exist_ok=True)
        nome = f"fonte{origem.suffix.lower()}"
        shutil.copyfile(origem, destino / nome)

        modelo = {
            "schema": "forge3d/bruto-arquivo@1",
            "arquivo": nome,
            "origem_nome": origem.name,
            "pivos": {},
        }
        arq = destino / "modelo.json"
        arq.write_text(
            json.dumps(modelo, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return RawAsset(
            dir=destino,
            schema=modelo["schema"],
            determinism=self.determinism,
            arquivos=[arq, destino / nome],
            meta={"origem": str(origem)},
        )
