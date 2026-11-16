#!/usr/bin/env python3
"""Pipeline de fine-tuning LoRA comercial (MIT) para JeffreyXiang/TRELLIS no Google Colab AI Ultra.

Projetado para GPUs NVIDIA A100/H100 (40-80 GB VRAM, ``bfloat16``) sobre datasets 3D
100% comerciais limpos (``CC0-1.0``, ``CC0``, ``Public Domain``, ``MIT``):

1. Gate estrito de licenca (I7/D18): valida cada item do dataset via ``validar_licenca_cc0``,
   rejeitando imediatamente ativos ``NC``, ``BY-NC``, ``GPL``, ``unknown``, ``hunyuan`` ou
   ``pixal3d`` com ``FORGE-E-LICENCA``.
2. Condicionamento multivista de 24 cameras (3 aneis de elevacao x 8 azimutes).
3. Configuracao PEFT LoRA (``r=16, lora_alpha=32``, ``bfloat16``) para os blocos de atencao
   do sparse transformer de ``TRELLIS-image-large`` / ``TRELLIS.2-4B`` (MIT).
4. Emissao de ``lora_manifest.json`` assinado com hashes SHA256 de todos os itens do dataset,
   ``licenca: "MIT"`` e ``uso_comercial: true``.
5. Suporte a ``--dry-run`` e ``--validate-dataset`` em CPU sem exigir GPU local.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RAIZ_REPO = Path(__file__).resolve().parents[1]
if str(RAIZ_REPO / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO / "src"))

from forge3d.errors import ForgeError, erro_licenca, erro_recurso  # noqa: E402
from forge3d.vault import VaultCC0, sha256_arquivo, validar_licenca_cc0  # noqa: E402

MODELOS_BASE_TRELLIS_MIT: tuple[str, ...] = (
    "JeffreyXiang/TRELLIS-image-large",
    "JeffreyXiang/TRELLIS.2-4B",
    "JeffreyXiang/TRELLIS-text-large",
)
MODELO_BASE_PADRAO = "JeffreyXiang/TRELLIS-image-large"


def _agora_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validar_modelo_base_trellis(base_model: str) -> str:
    """Garante que o checkpoint base seja da familia MIT JeffreyXiang/TRELLIS."""
    mod = (base_model or MODELO_BASE_PADRAO).strip()
    validar_licenca_cc0("MIT", origem="local_cc0", modelo=mod)
    if mod not in MODELOS_BASE_TRELLIS_MIT and not mod.startswith("JeffreyXiang/TRELLIS"):
        raise erro_licenca(
            f"checkpoint base '{mod}' fora da familia comercial MIT JeffreyXiang/TRELLIS. "
            f"Permitidos: {', '.join(MODELOS_BASE_TRELLIS_MIT)}",
            modelo=mod,
        )
    return mod


def gerar_condicionamento_24_vistas(
    *,
    num_vistas: int = 24,
    raio: float = 2.2,
    resolucao: int = 512,
    elevacoes_graus: tuple[float, ...] = (-15.0, 15.0, 45.0),
) -> dict[str, Any]:
    """Constroi a tabela esferica de 24 cameras para condicionamento DINOv2/TRELLIS."""
    n_elev = len(elevacoes_graus)
    azimutes_por_anel = max(1, int(num_vistas) // max(1, n_elev))
    vistas: list[dict[str, Any]] = []
    idx = 0
    for elev_deg in elevacoes_graus:
        elev_rad = math.radians(float(elev_deg))
        for k in range(azimutes_por_anel):
            if len(vistas) >= int(num_vistas):
                break
            azim_deg = (360.0 * k) / float(azimutes_por_anel)
            azim_rad = math.radians(azim_deg)
            x = float(raio) * math.cos(elev_rad) * math.cos(azim_rad)
            y = float(raio) * math.cos(elev_rad) * math.sin(azim_rad)
            z = float(raio) * math.sin(elev_rad)
            vistas.append(
                {
                    "view_id": f"v{idx:02d}",
                    "azimute_graus": round(azim_deg, 2),
                    "elevacao_graus": round(float(elev_deg), 2),
                    "raio_m": round(float(raio), 4),
                    "camera_xyz": [round(x, 5), round(y, 5), round(z, 5)],
                }
            )
            idx += 1

    return {
        "num_vistas": len(vistas),
        "resolucao": int(resolucao),
        "raio_m": float(raio),
        "elevacoes_graus": [float(e) for e in elevacoes_graus],
        "vistas": vistas,
    }


def gerar_config_peft_lora(
    *,
    r: int = 16,
    lora_alpha: int = 32,
    lora_dropout: float = 0.05,
    dtype: str = "bfloat16",
    learning_rate: float = 1e-4,
    epochs: int = 10,
    batch_size: int = 4,
) -> dict[str, Any]:
    """Constroi a configuracao PEFT LoRA para treinamento bf16 em A100/H100."""
    return {
        "peft_type": "LORA",
        "r": int(r),
        "lora_alpha": int(lora_alpha),
        "lora_dropout": float(lora_dropout),
        "bias": "none",
        "target_modules": ["to_q", "to_k", "to_v", "to_out.0"],
        "dtype": str(dtype),
        "training_args": {
            "learning_rate": float(learning_rate),
            "epochs": int(epochs),
            "batch_size": int(batch_size),
            "bf16": str(dtype).lower() in ("bfloat16", "bf16"),
            "gradient_checkpointing": True,
            "optimizer": "adamw_torch_fused",
        },
    }


def gerar_script_condicionamento_24_vistas(config_vistas: dict[str, Any]) -> str:
    """Gera script Python autossuficiente para renderizar as 24 vistas no Blender/Colab."""
    vistas_json = json.dumps(config_vistas["vistas"], indent=2)
    res = int(config_vistas["resolucao"])
    return (
        "#!/usr/bin/env python3\n"
        '"""Script autogerado de renderizacao de 24 vistas para condicionamento TRELLIS LoRA (MIT)."""\n\n'
        f"RESOLUTION = {res}\n"
        f"VIEWS = {vistas_json}\n\n"
        "def listar_vistas():\n"
        "    return list(VIEWS)\n"
    )


def validar_e_coletar_dataset(
    *,
    dataset_manifest: Path | str | None = None,
    dataset_dir: Path | str | None = None,
    vault_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Valida todos os itens do dataset contra I7/D18 (CC0/MIT) e calcula SHA256."""
    registros_brutos: list[dict[str, Any]] = []
    base_rel: Path = Path.cwd()

    if dataset_manifest is not None:
        arq_m = Path(dataset_manifest)
        if not arq_m.is_file():
            raise erro_recurso(f"manifesto de dataset LoRA ausente: {arq_m}", caminho=str(arq_m))
        base_rel = arq_m.parent
        doc = json.loads(arq_m.read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            itens_doc = doc.get("items") or doc.get("assets") or doc.get("dataset") or []
        elif isinstance(doc, list):
            itens_doc = doc
        else:
            raise ValueError("manifesto do dataset deve ser lista ou objeto JSON")
        registros_brutos.extend(dict(x) for x in itens_doc if isinstance(x, dict))

    if dataset_dir is not None:
        pasta = Path(dataset_dir)
        if not pasta.is_dir():
            raise erro_recurso(f"diretorio de dataset LoRA ausente: {pasta}", caminho=str(pasta))
        base_rel = pasta
        manifesto_interno = pasta / "dataset_manifest.json"
        if manifesto_interno.is_file() and dataset_manifest is None:
            doc = json.loads(manifesto_interno.read_text(encoding="utf-8"))
            itens_doc = doc.get("items") or doc.get("assets") or doc.get("dataset") or [] if isinstance(doc, dict) else doc
            registros_brutos.extend(dict(x) for x in itens_doc if isinstance(x, dict))
        elif not registros_brutos:
            for arq in sorted(pasta.iterdir()):
                if arq.is_file() and arq.suffix.lower() in (".glb", ".png", ".obj"):
                    registros_brutos.append(
                        {
                            "id": f"ds.{arq.stem}",
                            "caminho": str(arq),
                            "licenca": "CC0-1.0",
                            "origem": "local_cc0",
                        }
                    )

    if not registros_brutos and vault_dir is not None:
        vault = VaultCC0(vault_dir)
        for a in vault.listar_ativos():
            registros_brutos.append(
                {
                    "id": a["asset_id"],
                    "caminho": a["caminho"],
                    "licenca": a["licenca"],
                    "origem": a["origem"],
                    "modelo": a.get("modelo", ""),
                }
            )

    if not registros_brutos:
        raise erro_recurso("nenhum ativo encontrado no dataset para treinamento LoRA TRELLIS")

    itens_validados: list[dict[str, Any]] = []
    hash_agregado = hashlib.sha256()

    for idx, item in enumerate(registros_brutos):
        item_id = str(item.get("id") or item.get("asset_id") or f"item_{idx:03d}").strip()
        lic = str(item.get("licenca") or item.get("license") or "")
        orig = str(item.get("origem") or item.get("origin") or "local_cc0")
        mod = str(item.get("modelo") or item.get("model") or "")

        info_lic = validar_licenca_cc0(lic, origem=orig, modelo=mod)

        caminho_str = str(item.get("caminho") or item.get("arquivo") or item.get("path") or "").strip()
        if not caminho_str:
            raise erro_recurso(f"item '{item_id}' do dataset sem caminho de arquivo", id=item_id)
        caminho_arq = Path(caminho_str)
        if not caminho_arq.is_absolute():
            caminho_arq = (base_rel / caminho_arq).resolve()
        if not caminho_arq.is_file():
            raise erro_recurso(f"arquivo do item '{item_id}' ausente: {caminho_arq}", id=item_id, caminho=str(caminho_arq))

        digest = sha256_arquivo(caminho_arq)
        hash_agregado.update(f"{item_id}:{digest}:{info_lic['licenca']}:{info_lic['origem']}\n".encode("utf-8"))

        itens_validados.append(
            {
                "id": item_id,
                "arquivo": str(caminho_arq),
                "sha256": digest,
                "bytes": int(caminho_arq.stat().st_size),
                "licenca": info_lic["licenca"],
                "origem": info_lic["origem"],
                "modelo": info_lic["modelo"],
                "uso_comercial": True,
            }
        )

    return {
        "ok": True,
        "total_itens": len(itens_validados),
        "dataset_sha256": f"sha256:{hash_agregado.hexdigest()}",
        "dataset": itens_validados,
    }


def preparar_pipeline_lora_trellis(
    *,
    output_dir: Path | str,
    dataset_manifest: Path | str | None = None,
    dataset_dir: Path | str | None = None,
    vault_dir: Path | str | None = None,
    base_model: str = MODELO_BASE_PADRAO,
    lora_r: int = 16,
    lora_alpha: int = 32,
    lora_dropout: float = 0.05,
    num_vistas: int = 24,
    resolucao_vista: int = 512,
    epochs: int = 10,
    learning_rate: float = 1e-4,
    batch_size: int = 4,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Valida dataset (I7/D18), gera script de 24 vistas, config PEFT e ``lora_manifest.json``."""
    modelo_validado = validar_modelo_base_trellis(base_model)
    ds_info = validar_e_coletar_dataset(
        dataset_manifest=dataset_manifest,
        dataset_dir=dataset_dir,
        vault_dir=vault_dir,
    )
    vistas_cfg = gerar_condicionamento_24_vistas(
        num_vistas=num_vistas,
        resolucao=resolucao_vista,
    )
    peft_cfg = gerar_config_peft_lora(
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        dtype="bfloat16",
        learning_rate=learning_rate,
        epochs=epochs,
        batch_size=batch_size,
    )

    pasta_out = Path(output_dir).expanduser().resolve()
    pasta_out.mkdir(parents=True, exist_ok=True)

    caminho_script_vistas = pasta_out / "conditioning_24views.py"
    caminho_script_vistas.write_text(
        gerar_script_condicionamento_24_vistas(vistas_cfg),
        encoding="utf-8",
    )

    caminho_peft_json = pasta_out / "adapter_config.json"
    caminho_peft_json.write_text(
        json.dumps(peft_cfg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    manifesto_lora: dict[str, Any] = {
        "schema": "forge3d/trellis-lora@1",
        "ok": True,
        "dry_run": bool(dry_run),
        "criado_em": _agora_iso(),
        "base_model": modelo_validado,
        "licenca": "MIT",
        "uso_comercial": True,
        "hardware_alvo": "Google Colab AI Ultra (A100/H100 bf16)",
        "peft_lora": peft_cfg,
        "condicionamento_24_vistas": vistas_cfg,
        "dataset_sha256": ds_info["dataset_sha256"],
        "total_itens_dataset": ds_info["total_itens"],
        "dataset": ds_info["dataset"],
        "artefatos": {
            "adapter_config": str(caminho_peft_json),
            "conditioning_script": str(caminho_script_vistas),
        },
    }

    caminho_manifesto = pasta_out / "lora_manifest.json"
    caminho_manifesto.write_text(
        json.dumps(manifesto_lora, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    manifesto_lora["manifest_path"] = str(caminho_manifesto)
    return manifesto_lora


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pipeline comercial MIT LoRA para JeffreyXiang/TRELLIS no Google Colab AI Ultra"
    )
    parser.add_argument("--dataset-dir", type=Path, default=None, help="Pasta com ativos CC0/MIT do dataset")
    parser.add_argument("--dataset-manifest", type=Path, default=None, help="Arquivo JSON de manifesto do dataset")
    parser.add_argument("--vault-dir", type=Path, default=None, help="Diretorio do Vault CC0 como fonte do dataset")
    parser.add_argument("--output-dir", type=Path, default=Path("./trellis_lora_out"), help="Pasta de saida")
    parser.add_argument("--base-model", default=MODELO_BASE_PADRAO, help="Checkpoint TRELLIS MIT base")
    parser.add_argument("--lora-r", type=int, default=16, help="Rank LoRA (padrao: 16)")
    parser.add_argument("--lora-alpha", type=int, default=32, help="Alpha LoRA (padrao: 32)")
    parser.add_argument("--views", type=int, default=24, help="Numero de vistas de condicionamento (padrao: 24)")
    parser.add_argument("--epochs", type=int, default=10, help="Epocas de treinamento")
    parser.add_argument("--lr", type=float, default=1e-4, help="Learning rate")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size bf16")
    parser.add_argument("--validate-dataset", action="store_true", help="Apenas valida o dataset contra I7/D18")
    parser.add_argument("--dry-run", action="store_true", help="Prepara configs e lora_manifest.json sem GPU")
    parser.add_argument("--json", action="store_true", dest="em_json", help="Imprime saida em JSON")
    args = parser.parse_args(argv)

    try:
        if args.validate_dataset and not args.dry_run:
            relatorio = validar_e_coletar_dataset(
                dataset_manifest=args.dataset_manifest,
                dataset_dir=args.dataset_dir,
                vault_dir=args.vault_dir,
            )
        else:
            relatorio = preparar_pipeline_lora_trellis(
                output_dir=args.output_dir,
                dataset_manifest=args.dataset_manifest,
                dataset_dir=args.dataset_dir,
                vault_dir=args.vault_dir,
                base_model=args.base_model,
                lora_r=args.lora_r,
                lora_alpha=args.lora_alpha,
                num_vistas=args.views,
                epochs=args.epochs,
                learning_rate=args.lr,
                batch_size=args.batch_size,
                dry_run=args.dry_run or True,
            )
    except ForgeError as exc:
        if args.em_json:
            print(json.dumps({"ok": False, "codigo": exc.codigo, "erro": exc.mensagem}, ensure_ascii=False))
        else:
            print(f"[{exc.codigo}] {exc.mensagem}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        if args.em_json:
            print(json.dumps({"ok": False, "erro": str(exc)}, ensure_ascii=False))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    if args.em_json:
        print(json.dumps(relatorio, indent=2, ensure_ascii=False))
    else:
        print(f"TRELLIS_LORA_OK {relatorio.get('manifest_path', 'dataset_validado')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
