#!/usr/bin/env python3
"""Worker autossuficiente para rodar TRELLIS.2-4B e Pixal3D (MIT) no Google Colab AI Ultra.

Pensado para GPUs de 24-40 GB VRAM (NVIDIA L4 / A100 no Colab) sobre uma pasta com
conceitos PNG individuais (single-view) ou subpastas 4-vistas ortograficas
(``front.png``, ``back.png``, ``left.png``, ``right.png``), exportando ativos ``.glb``
e um snippet YAML ``forge3d/spec@6`` (ou ``spec@5``) com ``requisicao.base_externa``
e hashes ``sha256`` pronto para ``rota: "import"`` no Forge3D.

Setup rapido no Google Colab (GPU L4/A100)::

    !git clone --recurse-submodules https://github.com/microsoft/TRELLIS.2.git
    %cd TRELLIS.2
    !pip install -q pillow pyyaml imageio trimesh xatlas easydict
    !python colab_trellis_worker.py \\
        --input-dir ./concepts \\
        --output-dir ./glbs \\
        --yaml-out ./spec_trellis.yaml

O YAML gerado segue o contrato ``forge3d/spec@6`` sem caminhos pessoais fixos ou
nomes de projeto especificos (I15).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

MODELO_TRELLIS_PADRAO = "microsoft/TRELLIS.2-4B"

MODELOS_TRELLIS_MIT: dict[str, str] = {
    "microsoft/TRELLIS.2-4B": "microsoft/TRELLIS.2-4B",
    "TRELLIS.2-4B": "microsoft/TRELLIS.2-4B",
    "microsoft/TRELLIS.2": "microsoft/TRELLIS.2-4B",
    "JeffreyXiang/TRELLIS.2-4B": "JeffreyXiang/TRELLIS.2-4B",
    "TencentARC/Pixal3D": "TencentARC/Pixal3D",
    "Pixal3D": "TencentARC/Pixal3D",
    "microsoft/TRELLIS-image-large": "microsoft/TRELLIS-image-large",
    "JeffreyXiang/TRELLIS-image-large": "JeffreyXiang/TRELLIS-image-large",
    "TRELLIS-image-large": "microsoft/TRELLIS-image-large",
}

VISTAS_MULTIVIEW = ("front.png", "back.png", "left.png", "right.png")


def validar_modelo_trellis(modelo: str) -> str:
    """Valida que ``modelo`` pertence a allowlist comercial MIT/Apache suportada."""
    chave = str(modelo or "").strip()
    if chave in MODELOS_TRELLIS_MIT:
        return MODELOS_TRELLIS_MIT[chave]
    aceitos = ", ".join(sorted(MODELOS_TRELLIS_MIT))
    raise ValueError(
        f"modelo '{modelo}' fora da allowlist comercial MIT (TRELLIS.2-4B / Pixal3D). Aceitos: {aceitos}"
    )


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as fh:
        while True:
            bloco = fh.read(65536)
            if not bloco:
                break
            h.update(bloco)
    return f"sha256:{h.hexdigest()}"


def _validar_seed(seed: int) -> int:
    val = int(seed)
    if val < 0 or val > 4294967295:
        raise ValueError(f"seed fora do intervalo valido [0, 4294967295]: {seed}")
    return val


def _slug_item(stem: str) -> str:
    limpo = re.sub(r"[^a-z0-9_]+", "_", stem.lower()).strip("_")
    limpo = limpo[:64].strip("_")
    return limpo or "asset"


def _deduplicar_stem(stem: str, usados_lower: set[str]) -> str:
    base = stem.strip() or "asset"
    cand = base
    sufixo = 2
    while cand.lower() in usados_lower:
        cand = f"{base}_{sufixo}"
        sufixo += 1
    usados_lower.add(cand.lower())
    return cand


def _yaml_str(valor: Any) -> str:
    return json.dumps(str(valor), ensure_ascii=False)


def gerar_yaml_spec(
    entradas: list[dict[str, Any]],
    *,
    schema_version: int = 6,
    perfil: str = "godot4",
    tipo: str = "personagem_humanoide",
    altura_metros: float = 1.8,
    destino_exportacao: str = "~/.local/state/forge3d/saida/trellis",
    projeto: str = "trellis_colab",
    qualidade: str = "standard",
) -> str:
    """Constroi documento ``forge3d/spec@6`` ou ``forge3d/spec@5`` valido com ``requisicao.base_externa``."""
    ver = int(schema_version)
    if ver not in (5, 6):
        raise ValueError(f"schema_version invalido: {schema_version} (aceitos: 5, 6)")
    if not entradas:
        raise ValueError("entradas nao pode ser vazio para gerar spec YAML")

    primeira = entradas[0]
    seed_base = _validar_seed(primeira["seed"])
    linhas: list[str] = [
        f'schema: "forge3d/spec@{ver}"',
        f"projeto: {_yaml_str(projeto)}",
        f"perfil: {_yaml_str(perfil)}",
        f"destino_exportacao: {_yaml_str(destino_exportacao)}",
        "requisicao:",
        "  base_externa:",
        f"    tipo: {_yaml_str(tipo)}",
        f"    origem: {_yaml_str(primeira['glb_rel'])}",
        f"    sha256: {_yaml_str(primeira['sha256'])}",
        f"    seed: {seed_base}",
        "lote:",
    ]
    slugs_usados: set[str] = set()
    for ent in entradas:
        if "seed" in ent:
            _validar_seed(ent["seed"])
        base_slug = _slug_item(str(ent["stem"]))
        slug = base_slug
        sufixo = 2
        while slug in slugs_usados:
            suf_str = f"_{sufixo}"
            raiz_slug = (base_slug[: max(1, 72 - len(suf_str))].rstrip("_")) or "asset"
            slug = f"{raiz_slug}{suf_str}"
            sufixo += 1
        slugs_usados.add(slug)

        linhas.extend(
            [
                f"  - id: {_yaml_str(f'trellis.{slug}')}  # {ent['sha256']}",
                f"    tipo: {_yaml_str(tipo)}",
                '    rota: "import"',
                f"    origem: {_yaml_str(ent['glb_rel'])}",
                f"    altura_metros: {float(altura_metros):.2f}",
                '    estilo: "stylized_pbr"',
            ]
        )
        if ver == 6 and qualidade and qualidade != "standard":
            linhas.append(f"    qualidade: {_yaml_str(qualidade)}")
    return "\n".join(linhas) + "\n"


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
    return gerar_yaml_spec(
        entradas, schema_version=5, perfil=perfil, tipo=tipo,
        altura_metros=altura_metros, destino_exportacao=destino_exportacao, projeto=projeto,
    )


def gerar_yaml_spec_v6(
    entradas: list[dict[str, Any]],
    *,
    perfil: str = "godot4-aa",
    tipo: str = "personagem_humanoide",
    altura_metros: float = 1.8,
    destino_exportacao: str = "~/.local/state/forge3d/saida/trellis",
    projeto: str = "trellis_colab",
    qualidade: str = "hero",
) -> str:
    """Constroi documento ``forge3d/spec@6`` valido com ``requisicao.base_externa``."""
    return gerar_yaml_spec(
        entradas, schema_version=6, perfil=perfil, tipo=tipo,
        altura_metros=altura_metros, destino_exportacao=destino_exportacao, projeto=projeto, qualidade=qualidade,
    )


def _candidatos_pipeline(modelo_id: str) -> list[tuple[str, str]]:
    baixo = modelo_id.lower()
    if "pixal3d" in baixo:
        return [("pixal3d.pipelines", "Pixal3DPipeline"), ("trellis.pipelines", "Pixal3DPipeline"), ("trellis.pipelines", "TrellisImageTo3DPipeline")]
    if "trellis.2" in baixo:
        return [("trellis2.pipelines", "Trellis2ImageTo3DPipeline"), ("trellis.pipelines", "Trellis2ImageTo3DPipeline"), ("trellis.pipelines", "TrellisImageTo3DPipeline")]
    return [("trellis.pipelines", "TrellisImageTo3DPipeline")]


def carregar_pipeline_trellis(modelo: str) -> Any:
    """Importa e instancia pipeline MIT (``TRELLIS.2-4B``, ``Pixal3D`` ou fallback ``TRELLIS``)."""
    modelo_id = validar_modelo_trellis(modelo)
    os.environ.setdefault("SPCONV_ALGO", "native")
    ultimo_erro: Exception | None = None
    for mod_nome, cls_nome in _candidatos_pipeline(modelo_id):
        try:
            modulo = importlib.import_module(mod_nome)
            cls = getattr(modulo, cls_nome, None)
            if cls is None:
                ultimo_erro = AttributeError(f"{mod_nome}.{cls_nome} ausente")
                continue
            pipeline = cls.from_pretrained(modelo_id)
        except ImportError as exc:
            ultimo_erro = exc
            continue
        if hasattr(pipeline, "cuda"):
            pipeline.cuda()
        return pipeline
    raise RuntimeError(
        f"Nenhum pipeline compativel encontrado para '{modelo_id}' (instale TRELLIS.2, Pixal3D ou TRELLIS)."
    ) from ultimo_erro


def _resolver_postprocessing(modelo_id: str) -> Any:
    baixo = modelo_id.lower()
    if "pixal3d" in baixo:
        modulos = ("pixal3d.utils.postprocessing_utils", "trellis.utils.postprocessing_utils", "trellis2.utils.postprocessing_utils")
    elif "trellis.2" in baixo:
        modulos = ("trellis2.utils.postprocessing_utils", "trellis.utils.postprocessing_utils", "pixal3d.utils.postprocessing_utils")
    else:
        modulos = ("trellis.utils.postprocessing_utils", "trellis2.utils.postprocessing_utils", "pixal3d.utils.postprocessing_utils")
    ultimo_erro: Exception | None = None
    for mod_nome in modulos:
        try:
            return importlib.import_module(mod_nome)
        except ImportError as exc:
            ultimo_erro = exc
    raise RuntimeError("Modulo 'postprocessing_utils' indisponivel.") from ultimo_erro


def executar_pipeline_trellis(
    pipe: Any,
    imagens: list[Any],
    seed: int,
    *,
    preferir_single_sem_multi: bool = False,
) -> Any:
    """Despacha 1-vista ou multivista compativel com TRELLIS v1, TRELLIS.2 e Pixal3D."""
    if not imagens:
        raise ValueError("lista de imagens vazia para pipeline TRELLIS")
    if len(imagens) == 1:
        return pipe.run(imagens[0], seed=seed)
    fn_multi = getattr(pipe, "run_multi_image", None)
    if callable(fn_multi):
        return fn_multi(imagens, seed=seed)
    cls_pipe = type(pipe)
    mod_pipe = (getattr(cls_pipe, "__module__", "") or "").lower()
    if preferir_single_sem_multi or cls_pipe.__name__ == "Trellis2ImageTo3DPipeline" or "trellis2" in mod_pipe:
        sys.stderr.write(
            f"[colab_trellis_worker] aviso: {cls_pipe.__name__} sem run_multi_image; "
            f"usando vista frontal ({len(imagens)} vistas recebidas)\n"
        )
        return pipe.run(imagens[0], seed=seed)
    try:
        return pipe.run(imagens, seed=seed)
    except (TypeError, AttributeError) as exc:
        sys.stderr.write(
            f"[colab_trellis_worker] aviso: {cls_pipe.__name__}.run(lista) indisponivel ({exc}); usando vista frontal\n"
        )
        return pipe.run(imagens[0], seed=seed)


def _exportar_saida_pipeline(
    outputs: Any,
    modelo_id: str,
    *,
    simplify: float,
    texture_size: int,
    decimation_target: int | None = None,
) -> Any:
    if isinstance(outputs, dict) and "gaussian" in outputs and "mesh" in outputs:
        pp = _resolver_postprocessing(modelo_id)
        return pp.to_glb(
            outputs["gaussian"][0],
            outputs["mesh"][0],
            simplify=float(simplify),
            texture_size=int(texture_size),
        )
    if hasattr(outputs, "export"):
        return outputs
    mesh_out = outputs[0] if isinstance(outputs, (list, tuple)) and outputs else outputs
    if hasattr(mesh_out, "export"):
        return mesh_out
    if (
        hasattr(mesh_out, "vertices")
        and hasattr(mesh_out, "faces")
        and all(hasattr(mesh_out, k) for k in ("attrs", "coords", "layout"))
    ):
        try:
            ov_pp = importlib.import_module("o_voxel.postprocess")
        except ImportError as exc:
            raise RuntimeError("Modulo 'o_voxel.postprocess' indisponivel para TRELLIS.2.") from exc
        return ov_pp.to_glb(
            vertices=mesh_out.vertices,
            faces=mesh_out.faces,
            attr_volume=mesh_out.attrs,
            coords=mesh_out.coords,
            attr_layout=mesh_out.layout,
            voxel_size=getattr(mesh_out, "voxel_size", None),
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=int(decimation_target or 80_000),
            texture_size=int(texture_size),
            remesh=True,
        )
    raise RuntimeError(f"Saida inesperada do pipeline '{modelo_id}': {type(outputs).__name__}")


def _coletar_jobs(input_dir: Path) -> list[tuple[str, list[Path]]]:
    if not input_dir.is_dir():
        raise FileNotFoundError(f"pasta de entrada inexistente: {input_dir}")

    jobs: list[tuple[str, list[Path]]] = []
    stems_usados: set[str] = set()
    for entry in sorted(input_dir.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_file() and entry.suffix.lower() == ".png":
            stem = _deduplicar_stem(entry.stem, stems_usados)
            jobs.append((stem, [entry]))
        elif entry.is_dir():
            por_nome = {p.name.lower(): p for p in entry.iterdir() if p.is_file()}
            encontradas = [por_nome[vista] for vista in VISTAS_MULTIVIEW if vista in por_nome]
            if len(encontradas) == 4:
                stem = _deduplicar_stem(entry.name, stems_usados)
                jobs.append((stem, encontradas))
            elif encontradas:
                faltando = [v for v in VISTAS_MULTIVIEW if v not in por_nome]
                raise FileNotFoundError(
                    f"pasta multivista incompleta '{entry}': faltando {', '.join(faltando)}"
                )
            elif any(p.suffix.lower() == ".png" for p in por_nome.values()):
                raise FileNotFoundError(
                    f"pasta multivista '{entry}' sem vistas padrao ({', '.join(VISTAS_MULTIVIEW)})"
                )

    if not jobs:
        raise FileNotFoundError(
            f"nenhum PNG ou subpasta 4-vistas ({', '.join(VISTAS_MULTIVIEW)}) encontrado em {input_dir}"
        )
    return jobs


def processar_pasta(
    input_dir: Path,
    output_dir: Path,
    *,
    modelo: str = MODELO_TRELLIS_PADRAO,
    seed: int = 1,
    simplify: float = 0.95,
    texture_size: int = 1024,
    decimation_target: int | None = None,
    pipeline: Any = None,
) -> list[dict[str, Any]]:
    """Converte PNGs (1-view) e subpastas 4-vistas de ``input_dir`` em ``.glb`` via TRELLIS.2/Pixal3D (MIT)."""
    from PIL import Image

    modelo_id = validar_modelo_trellis(modelo)
    seed_inicial = _validar_seed(seed)
    jobs = _coletar_jobs(input_dir)
    _validar_seed(seed_inicial + len(jobs) - 1)

    jobs_carregados: list[tuple[str, list[Path], list[Any]]] = []
    for stem, paths in jobs:
        imagens: list[Any] = []
        for p in paths:
            with Image.open(p) as im:
                im.load()
                imagens.append(im.convert("RGBA"))
        jobs_carregados.append((stem, paths, imagens))

    output_dir.mkdir(parents=True, exist_ok=True)
    if pipeline is None:
        pipeline = carregar_pipeline_trellis(modelo_id)

    resultados: list[dict[str, Any]] = []
    glbs_escritos: set[Path] = set()
    for idx, (stem, paths, imagens) in enumerate(jobs_carregados):
        item_seed = seed_inicial + idx
        outputs = executar_pipeline_trellis(
            pipeline, imagens, seed=item_seed, preferir_single_sem_multi=False
        )
        glb = _exportar_saida_pipeline(
            outputs, modelo_id, simplify=simplify, texture_size=texture_size, decimation_target=decimation_target
        )
        stem_final = stem
        sufixo = 2
        while (output_dir / f"{stem_final}.glb") in glbs_escritos:
            stem_final = f"{stem}_{sufixo}"
            sufixo += 1
        destino_glb = output_dir / f"{stem_final}.glb"
        glbs_escritos.add(destino_glb)
        glb.export(str(destino_glb))
        digest = sha256_arquivo(destino_glb)
        resultados.append({
            "stem": stem_final, "png": str(paths[0]), "vistas": [str(p) for p in paths],
            "glb": str(destino_glb), "glb_rel": str(destino_glb),
            "sha256": digest, "seed": item_seed, "modelo": modelo_id,
        })
    return resultados


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Batch TRELLIS.2-4B / Pixal3D (MIT) para Google Colab AI Ultra -> GLB + forge3d/spec@6"
    )
    parser.add_argument("--input-dir", type=Path, required=True, help="Pasta com PNGs ou subpastas 4-vistas")
    parser.add_argument("--output-dir", type=Path, required=True, help="Pasta de saida dos GLBs")
    parser.add_argument("--yaml-out", type=Path, default=None, help="Arquivo YAML spec de saida")
    parser.add_argument("--model", default=MODELO_TRELLIS_PADRAO, help="Modelo comercial MIT (TRELLIS.2-4B/Pixal3D)")
    parser.add_argument("--seed", type=int, default=1, help="Seed inicial deterministica")
    parser.add_argument("--simplify", type=float, default=0.95, help="Taxa de simplificacao da malha")
    parser.add_argument("--texture-size", type=int, default=1024, help="Resolucao da textura bakeada")
    parser.add_argument("--perfil", default="godot4", help="Perfil Forge3D alvo no snippet YAML")
    parser.add_argument("--tipo", default="personagem_humanoide", help="Tipo Forge3D no snippet YAML")
    parser.add_argument("--altura", type=float, default=1.8, help="Altura em metros no snippet YAML")
    parser.add_argument("--schema-version", type=int, choices=(5, 6), default=6, help="Versao do schema YAML (5 ou 6)")
    parser.add_argument("--qualidade", default="standard", choices=("standard", "hero", "ultra"), help="Tier no spec@6")
    args = parser.parse_args(argv)

    try:
        validar_modelo_trellis(args.model)
        _validar_seed(args.seed)
        entradas = processar_pasta(
            args.input_dir, args.output_dir, modelo=args.model,
            seed=args.seed, simplify=args.simplify, texture_size=args.texture_size,
        )
        yaml_txt = gerar_yaml_spec(
            entradas, schema_version=args.schema_version, perfil=args.perfil,
            tipo=args.tipo, altura_metros=args.altura, qualidade=args.qualidade,
        )
    except ValueError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    if args.yaml_out is not None:
        args.yaml_out.parent.mkdir(parents=True, exist_ok=True)
        args.yaml_out.write_text(yaml_txt, encoding="utf-8")
        print(f"SPEC_V{args.schema_version}_OK {args.yaml_out} ({len(entradas)} ativos)")
    else:
        sys.stdout.write(yaml_txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
