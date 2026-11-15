#!/usr/bin/env python3
"""Worker autossuficiente para rodar JeffreyXiang/TRELLIS (MIT) no Google Colab AI Ultra.

Pensado para GPUs de 24-40 GB VRAM (NVIDIA L4 / A100 no Colab) sobre uma pasta de
conceitos PNG, exportando ativos ``.glb`` e um snippet YAML ``forge3d/spec@5`` com
``requisicao.base_externa`` e hashes ``sha256`` pronto para importacao no Forge3D.

Setup rapido no Google Colab (GPU L4/A100)::

    !git clone --recurse-submodules https://github.com/JeffreyXiang/TRELLIS.git
    %cd TRELLIS
    !pip install -q pillow pyyaml imageio trimesh xatlas easydict
    !python colab_trellis_worker.py \\
        --input-dir ./concepts \\
        --output-dir ./glbs \\
        --yaml-out ./spec_trellis.yaml

O YAML gerado segue o contrato ``forge3d/spec@5`` sem caminhos pessoais fixos ou
nomes de projeto especificos (I15).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any

MODELO_TRELLIS_PADRAO = "JeffreyXiang/TRELLIS-image-large"


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as fh:
        while True:
            bloco = fh.read(65536)
            if not bloco:
                break
            h.update(bloco)
    return f"sha256:{h.hexdigest()}"


def _slug_item(stem: str) -> str:
    limpo = re.sub(r"[^a-z0-9_]+", "_", stem.lower()).strip("_")
    return limpo or "asset"


def gerar_yaml_spec_v5(
    entradas: list[dict[str, Any]],
    *,
    perfil: str = "godot4",
    tipo: str = "personagem_humanoide",
    altura_metros: float = 1.8,
    destino_exportacao: str = "~/.local/state/forge3d/saida/trellis",
    projeto: str = "trellis_colab",
) -> str:
    """Constroi documento ``forge3d/spec@5`` valido com ``requisicao.base_externa``."""
    linhas: list[str] = [
        'schema: "forge3d/spec@5"',
        f'projeto: "{projeto}"',
        f'perfil: "{perfil}"',
        f'destino_exportacao: "{destino_exportacao}"',
    ]
    if entradas:
        primeira = entradas[0]
        linhas.extend(
            [
                "requisicao:",
                "  base_externa:",
                f'    tipo: "{tipo}"',
                f'    origem: "{primeira["glb_rel"]}"',
                f'    sha256: "{primeira["sha256"]}"',
                f'    seed: {int(primeira["seed"])}',
            ]
        )
    linhas.append("lote:")
    for ent in entradas:
        slug = _slug_item(ent["stem"])
        linhas.extend(
            [
                f'  - id: "trellis.{slug}"  # {ent["sha256"]}',
                f'    tipo: "{tipo}"',
                '    rota: "import"',
                f'    origem: "{ent["glb_rel"]}"',
                f"    altura_metros: {float(altura_metros):.2f}",
                '    estilo: "stylized_pbr"',
            ]
        )
    return "\n".join(linhas) + "\n"


def carregar_pipeline_trellis(modelo: str) -> Any:
    """Importa e instancia ``TrellisImageTo3DPipeline`` sob demanda no ambiente Colab."""
    os.environ.setdefault("SPCONV_ALGO", "native")
    try:
        from trellis.pipelines import TrellisImageTo3DPipeline  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depende de ambiente GPU Colab
        raise RuntimeError(
            "Pacote 'trellis' nao encontrado. Clone JeffreyXiang/TRELLIS e adicione ao PYTHONPATH."
        ) from exc
    pipeline = TrellisImageTo3DPipeline.from_pretrained(modelo)
    pipeline.cuda()
    return pipeline


def processar_pasta(
    input_dir: Path,
    output_dir: Path,
    *,
    modelo: str = MODELO_TRELLIS_PADRAO,
    seed: int = 1,
    simplify: float = 0.95,
    texture_size: int = 1024,
    pipeline: Any = None,
) -> list[dict[str, Any]]:
    """Converte todos os ``*.png`` de ``input_dir`` em ``.glb`` via TRELLIS (MIT)."""
    from PIL import Image

    pngs = sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".png")
    if not pngs:
        raise FileNotFoundError(f"nenhum PNG encontrado em {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    if pipeline is None:
        pipeline = carregar_pipeline_trellis(modelo)

    try:
        from trellis.utils import postprocessing_utils  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depende de ambiente GPU Colab
        raise RuntimeError("Modulo 'trellis.utils.postprocessing_utils' indisponivel.") from exc

    resultados: list[dict[str, Any]] = []
    for idx, png_path in enumerate(pngs):
        item_seed = int(seed) + idx
        with Image.open(png_path) as im:
            imagem = im.convert("RGBA")
        outputs = pipeline.run(imagem, seed=item_seed)
        glb = postprocessing_utils.to_glb(
            outputs["gaussian"][0],
            outputs["mesh"][0],
            simplify=float(simplify),
            texture_size=int(texture_size),
        )
        destino_glb = output_dir / f"{png_path.stem}.glb"
        glb.export(str(destino_glb))
        digest = sha256_arquivo(destino_glb)
        resultados.append(
            {
                "stem": png_path.stem,
                "png": str(png_path),
                "glb": str(destino_glb),
                "glb_rel": str(destino_glb),
                "sha256": digest,
                "seed": item_seed,
            }
        )
    return resultados


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Batch JeffreyXiang/TRELLIS (MIT) para Google Colab AI Ultra -> GLB + spec@5"
    )
    parser.add_argument("--input-dir", type=Path, required=True, help="Pasta com imagens PNG")
    parser.add_argument("--output-dir", type=Path, required=True, help="Pasta de saida dos GLBs")
    parser.add_argument("--yaml-out", type=Path, default=None, help="Arquivo YAML spec@5 de saida")
    parser.add_argument("--model", default=MODELO_TRELLIS_PADRAO, help="Checkpoint HuggingFace TRELLIS")
    parser.add_argument("--seed", type=int, default=1, help="Seed inicial deterministica")
    parser.add_argument("--simplify", type=float, default=0.95, help="Taxa de simplificacao da malha")
    parser.add_argument("--texture-size", type=int, default=1024, help="Resolucao da textura bakeada")
    parser.add_argument("--perfil", default="godot4", help="Perfil Forge3D alvo no snippet YAML")
    parser.add_argument("--tipo", default="personagem_humanoide", help="Tipo Forge3D no snippet YAML")
    parser.add_argument("--altura", type=float, default=1.8, help="Altura em metros no snippet YAML")
    args = parser.parse_args(argv)

    entradas = processar_pasta(
        args.input_dir,
        args.output_dir,
        modelo=args.model,
        seed=args.seed,
        simplify=args.simplify,
        texture_size=args.texture_size,
    )
    yaml_txt = gerar_yaml_spec_v5(
        entradas,
        perfil=args.perfil,
        tipo=args.tipo,
        altura_metros=args.altura,
    )
    if args.yaml_out is not None:
        args.yaml_out.parent.mkdir(parents=True, exist_ok=True)
        args.yaml_out.write_text(yaml_txt, encoding="utf-8")
        print(f"SPEC_V5_OK {args.yaml_out} ({len(entradas)} ativos)")
    else:
        sys.stdout.write(yaml_txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
