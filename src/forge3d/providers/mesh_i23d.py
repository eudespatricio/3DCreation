"""Execucao i23d (cutout 2D, delight com emissive e inferencia TripoSR)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import mesh_diag as _diag
from .mesh_templates import anexar_concept_vistas, ler_json_obrigatorio


def resolver_imagem_origem(item: dict) -> Path:
    from ..errors import erro_provider_run

    raw_orig = str(item.get("origem") or "").strip()
    if not raw_orig:
        raise erro_provider_run("imagem de concept vazia", id=item.get("id"))
    imagem = Path(raw_orig).expanduser()
    if not imagem.is_file():
        raise erro_provider_run(f"imagem de concept inexistente: {imagem}", id=item.get("id"))
    if imagem.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise erro_provider_run(
            f"formato de concept não suportado: {imagem.suffix}", id=item.get("id")
        )
    return imagem


def executar_cutout_2d(
    imagem: Path, destino: Path, env: dict[str, str], item_id: Any
) -> tuple[Path, dict[str, Any]]:
    from ..errors import erro_provider_run

    cutout_png = destino / "input_cutout.png"
    cutout_json = destino / "cutout_resultado.json"
    pg_script = _diag.facade_attr("script_pose_guard", _diag.script_pose_guard)()
    py_img = _diag.facade_attr("_python_imagem", _diag._python_imagem)()
    if not pg_script.is_file():
        raise erro_provider_run(f"pose_guard.py ausente em {pg_script}", id=item_id)

    timeout_s = _diag.facade_attr("TIMEOUT_S", _diag.TIMEOUT_S)
    try:
        proc = _diag.subproc_run(
            [
                str(py_img),
                str(pg_script),
                "--acao",
                "decompor",
                "--imagem",
                str(imagem),
                "--saida-png",
                str(cutout_png),
                "--resultado",
                str(cutout_json),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
    except subprocess.TimeoutExpired:
        raise erro_provider_run(f"timeout de {timeout_s}s no recorte 2D", id=item_id) from None
    except OSError as exc:
        raise erro_provider_run(f"falha ao executar recorte 2D: {exc}", id=item_id) from exc

    if proc.returncode != 0:
        raise erro_provider_run(
            "falha no recorte 2D (pose_guard --acao decompor)",
            id=item_id,
            exit=proc.returncode,
            stderr=(proc.stderr or proc.stdout or "")[-1500:],
        )
    info: dict[str, Any] = {}
    if cutout_json.is_file():
        info = ler_json_obrigatorio(cutout_json, "recorte 2D", item_id)
        if not info.get("ok"):
            raise erro_provider_run(f"recorte 2D falhou: {info.get('erro')}", id=item_id)
    if not cutout_png.is_file():
        raise erro_provider_run(
            f"recorte 2D nao produziu {cutout_png.name} em {destino}", id=item_id
        )
    return cutout_png, info


def executar_delight(
    entrada_png: Path, destino: Path, env: dict[str, str]
) -> dict[str, Any]:
    dl_script = _diag.facade_attr("script_delight", _diag.script_delight)()
    py_img = _diag.facade_attr("_python_imagem", _diag._python_imagem)()
    albedo_png = destino / "input_delit.png"
    metallic_png = destino / "metallic_hint.png"
    roughness_png = destino / "roughness_hint.png"
    emissive_png = destino / "emissive_hint.png"
    delight_json = destino / "delight_resultado.json"

    proc = _diag.subproc_run(
        [
            str(py_img),
            str(dl_script),
            "--imagem",
            str(entrada_png),
            "--saida-albedo",
            str(albedo_png),
            "--saida-metallic",
            str(metallic_png),
            "--saida-roughness",
            str(roughness_png),
            "--saida-emissive",
            str(emissive_png),
            "--resultado",
            str(delight_json),
        ],
        capture_output=True,
        text=True,
        timeout=_diag.facade_attr("TIMEOUT_S", _diag.TIMEOUT_S),
        env=env,
    )
    report: dict[str, Any] = {"ativo": True, "executado": False}
    if delight_json.is_file():
        try:
            report.update(json.loads(delight_json.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            report["erro_leitura_json"] = str(exc)
            sys.stderr.write(f"[mesh] aviso delight_resultado.json invalido: {exc}\n")
    if proc.returncode != 0:
        report["returncode"] = proc.returncode
        report.setdefault(
            "erro",
            (proc.stderr or proc.stdout or f"exit {proc.returncode}")[-500:],
        )

    arquivos_extras: list[Path] = []
    if proc.returncode == 0:
        for candidato in (albedo_png, metallic_png, roughness_png, emissive_png):
            if candidato.is_file():
                arquivos_extras.append(candidato)
        if albedo_png in arquivos_extras:
            report["executado"] = True

    return {
        "report": report,
        "albedo": "input_delit.png" if albedo_png in arquivos_extras else "",
        "metallic_hint": "metallic_hint.png" if metallic_png in arquivos_extras else "",
        "roughness_hint": "roughness_hint.png" if roughness_png in arquivos_extras else "",
        "emissive_hint": "emissive_hint.png" if emissive_png in arquivos_extras else "",
        "arquivos": arquivos_extras,
    }


def executar_extrude_2d(
    item: dict,
    destino: Path,
    imagem: Path,
    concept_meta: dict | None,
    env: dict[str, str],
    t0: float,
    cutout_fn: Callable[[Path, Path, dict[str, str], Any], tuple[Path, dict[str, Any]]],
    delight_fn: Callable[[Path, Path, dict[str, str]], dict[str, Any]],
) -> tuple[str, list[Path], dict[str, Any]]:
    delight_ativo = _diag.facade_attr("_delight_ativo", _diag._delight_ativo)(item)
    dl_script = _diag.facade_attr("script_delight", _diag.script_delight)()
    cutout_png, cutout_info = cutout_fn(imagem, destino, env, item.get("id"))
    delight_meta: dict[str, Any] = {"ativo": delight_ativo, "executado": False}
    arquivos_extras: list[Path] = []
    metallic_hint = ""
    roughness_hint = ""
    emissive_hint = ""
    origem_textura = ""
    if delight_ativo and dl_script.is_file() and cutout_png.is_file():
        dl = delight_fn(cutout_png, destino, env)
        delight_meta = dl["report"]
        origem_textura = dl["albedo"]
        metallic_hint = dl["metallic_hint"]
        roughness_hint = dl["roughness_hint"]
        emissive_hint = dl.get("emissive_hint", "")
        arquivos_extras = dl["arquivos"]

    modelo: dict[str, Any] = {
        "schema": "forge3d/bruto-extrude@1",
        "modo": str(item.get("parte") or "arma"),
        "imagem": "input_cutout.png",
        "origem_nome": imagem.name,
        "pivos": {},
        "concept": concept_meta,
    }
    if origem_textura:
        modelo["origem_textura"] = origem_textura
    if metallic_hint:
        modelo["metallic_hint"] = metallic_hint
    if roughness_hint:
        modelo["roughness_hint"] = roughness_hint
    if emissive_hint:
        modelo["emissive_hint"] = emissive_hint

    arq_modelo = destino / "modelo.json"
    resultado_path = destino / "i23d_resultado.json"
    arquivos = [arq_modelo, cutout_png, resultado_path, *arquivos_extras]
    meta_raw: dict[str, Any] = {
        "modelo": "procedural",
        "modo": modelo["modo"],
        "cutout": cutout_info,
        "delight": delight_meta,
        "concept": concept_meta,
    }
    anexar_concept_vistas(modelo, meta_raw, arquivos, destino, item, concept_meta)
    arq_modelo.write_text(
        json.dumps(modelo, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    resultado: dict[str, Any] = {
        "ok": True,
        "modo": "extrude_2d",
        "modelo": "procedural",
        "parte": modelo["modo"],
        "cutout": cutout_info,
        "delight": delight_meta,
        "tempo_provider_s": round(time.monotonic() - t0, 3),
    }
    resultado_path.write_text(
        json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return "forge3d/bruto-extrude@1", arquivos, meta_raw


def executar_i23d_step(
    item: dict,
    destino: Path,
    imagem: Path,
    concept_meta: dict | None,
    env: dict[str, str],
    t0: float,
    pose_guard_fn: Callable[[dict, Path, Path, dict[str, str]], tuple[Path, dict[str, Any]]],
    delight_fn: Callable[[Path, Path, dict[str, str]], dict[str, Any]],
) -> dict[str, Any]:
    from ..errors import erro_provider_run

    dir_venv_fn = _diag.facade_attr("dir_venv", _diag.dir_venv)
    infer_fn = _diag.facade_attr("script_inferencia", _diag.script_inferencia)
    qualidade_fn = _diag.facade_attr("_qualidade", _diag._qualidade)
    rembg_mod_fn = _diag.facade_attr("_rembg_modelo", _diag._rembg_modelo)
    device_fn = _diag.facade_attr("_device", _diag._device)
    decidir_rembg = _diag.facade_attr("_decidir_rembg", _diag._decidir_rembg)
    delight_ativo_fn = _diag.facade_attr("_delight_ativo", _diag._delight_ativo)
    dl_script_fn = _diag.facade_attr("script_delight", _diag.script_delight)

    resultado_path = destino / "i23d_resultado.json"
    imagem, pose_guard_report = pose_guard_fn(item, imagem, destino, env)
    mc_default = "320" if qualidade_fn(item) == "hero" else "256"
    resolucao = os.environ.get("FORGE3D_MC_RESOLUTION", mc_default)
    timeout_s = _diag.facade_attr("TIMEOUT_S", _diag.TIMEOUT_S)
    modelo_hf = _diag.facade_attr("MODELO_HF", _diag.MODELO_HF)
    comando = [
        str(dir_venv_fn() / "bin" / "python"),
        str(infer_fn()),
        "--imagem",
        str(imagem),
        "--saida-dir",
        str(destino),
        "--resultado",
        str(resultado_path),
        "--modelo",
        modelo_hf,
        "--mc-resolution",
        str(int(resolucao)),
        "--device",
        device_fn(),
    ]
    remover_fundo, motivo_rembg = decidir_rembg(imagem, concept_meta)
    if remover_fundo:
        comando.extend(["--remover-fundo", "--rembg-modelo", rembg_mod_fn()])

    try:
        proc = _diag.subproc_run(
            comando, capture_output=True, text=True, timeout=timeout_s, env=env
        )
    except subprocess.TimeoutExpired:
        raise erro_provider_run(
            f"timeout de {timeout_s}s na inferência i23d", id=item.get("id")
        ) from None
    except OSError as exc:
        raise erro_provider_run(f"falha ao executar a venv de i23d: {exc}", id=item.get("id")) from exc

    if not resultado_path.is_file():
        raise erro_provider_run(
            "i23d não escreveu resultado.json",
            id=item.get("id"),
            exit=proc.returncode,
            stderr=(proc.stderr or proc.stdout or "")[-2000:],
        )
    resultado = ler_json_obrigatorio(resultado_path, "i23d", item.get("id"))
    if not resultado.get("ok"):
        raise erro_provider_run(
            f"i23d falhou: {resultado.get('erro')}",
            id=item.get("id"),
            stderr=(resultado.get("traceback") or "")[-2000:],
        )

    glb = destino / "modelo.glb"
    if not glb.is_file():
        raise erro_provider_run(f"i23d não produziu modelo.glb em {destino}", id=item.get("id"))

    input_png = destino / "input.png"
    input_rgba_png = destino / "input_rgba.png"
    entrada_tex = input_rgba_png if input_rgba_png.is_file() else input_png
    delight_ativo = delight_ativo_fn(item)
    delight_report: dict[str, Any] = {"ativo": delight_ativo, "executado": False}
    origem_textura = entrada_tex.name
    metallic_hint = ""
    roughness_hint = ""
    emissive_hint = ""
    arquivos_extras = [input_rgba_png] if input_rgba_png.is_file() else []
    if delight_ativo and dl_script_fn().is_file() and entrada_tex.is_file():
        dl = delight_fn(entrada_tex, destino, env)
        delight_report = dl["report"]
        if dl["albedo"]:
            origem_textura = dl["albedo"]
        metallic_hint = dl["metallic_hint"]
        roughness_hint = dl["roughness_hint"]
        emissive_hint = dl.get("emissive_hint", "")
        arquivos_extras = [*arquivos_extras, *dl["arquivos"]]

    tex_default = (
        ("1024" if item.get("material_procedural") else "2048")
        if qualidade_fn(item) == "hero"
        else "1024"
    )
    tex_max_lim = 2048 if qualidade_fn(item) == "hero" else 1024
    textura_px = int(os.environ.get("FORGE3D_TEX_PX", tex_default))
    modelo: dict[str, Any] = {
        "schema": "forge3d/bruto-arquivo@1",
        "arquivo": "modelo.glb",
        "origem_nome": imagem.name,
        "canonicalizar": True,
        "textura_px": max(64, min(textura_px, tex_max_lim)),
        "retopologia": str(item.get("retopologia") or "auto"),
        "pivos": {},
        "concept": concept_meta,
        "proteger_decimate": item.get("tipo")
        in (
            "personagem_humanoide",
            "criatura",
            "criatura_quadrupede",
            "criatura_alada",
            "montaria",
        ),
    }
    if item.get("material_procedural"):
        modelo["material_procedural"] = str(item["material_procedural"])
    if item.get("quadriflow_faces"):
        modelo["quadriflow_faces"] = int(item["quadriflow_faces"])
    if entrada_tex.is_file() or not delight_ativo:
        modelo["origem_textura"] = origem_textura
    if metallic_hint:
        modelo["metallic_hint"] = metallic_hint
    if roughness_hint:
        modelo["roughness_hint"] = roughness_hint
    if emissive_hint:
        modelo["emissive_hint"] = emissive_hint

    arq_modelo = destino / "modelo.json"
    arquivos = [arq_modelo, glb, resultado_path, input_png, *arquivos_extras]
    vistas_meta: dict[str, Any] = {}
    vistas = anexar_concept_vistas(modelo, vistas_meta, arquivos, destino, item, concept_meta)
    arq_modelo.write_text(
        json.dumps(modelo, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    resultado["rembg"] = remover_fundo
    resultado["rembg_motivo"] = motivo_rembg
    resultado["pose_guard"] = pose_guard_report
    resultado["delight"] = delight_report
    resultado["tempo_provider_s"] = round(time.monotonic() - t0, 3)
    resultado_path.write_text(
        json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return {
        "schema": str(modelo["schema"]),
        "arquivos": arquivos,
        "resultado": resultado,
        "remover_fundo": remover_fundo,
        "motivo_rembg": motivo_rembg,
        "pose_guard_report": pose_guard_report,
        "delight_report": delight_report,
        "vistas_ortograficas": vistas or None,
    }
