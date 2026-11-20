"""Geradores template humanoide/cabelo e helpers de JSON/vistas da rota ``mesh``."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from . import mesh_diag as _diag

VISTAS_ORTO_CHAVES = ("front", "back", "left", "right")


def ler_json_obrigatorio(path: Path, contexto: str, item_id: Any) -> dict[str, Any]:
    from ..errors import erro_provider_run

    try:
        dados = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise erro_provider_run(
            f"{contexto}: JSON invalido em {path.name}: {exc}", id=item_id
        ) from exc
    if not isinstance(dados, dict):
        raise erro_provider_run(
            f"{contexto}: esperado objeto JSON em {path.name}", id=item_id
        )
    return dados


def extrair_vistas_ortograficas(item: dict, concept_meta: dict | None) -> dict[str, str]:
    fontes = []
    if isinstance(concept_meta, dict) and isinstance(concept_meta.get("vistas"), dict):
        fontes.append(concept_meta["vistas"])
    if isinstance(item.get("vistas_ortograficas"), dict):
        fontes.append(item["vistas_ortograficas"])
    for bruto in fontes:
        vistas: dict[str, str] = {}
        for chave in VISTAS_ORTO_CHAVES:
            raw_val = bruto.get(chave)
            if not raw_val:
                continue
            p = Path(str(raw_val)).expanduser()
            if p.is_file():
                vistas[chave] = str(p)
        if vistas:
            return vistas
    return {}


def anexar_concept_vistas(
    modelo: dict[str, Any],
    meta_raw: dict[str, Any],
    arquivos: list[Path],
    destino: Path,
    item: dict,
    concept_meta: dict | None,
) -> dict[str, str]:
    vistas = extrair_vistas_ortograficas(item, concept_meta)
    if vistas:
        modelo["vistas_ortograficas"] = dict(vistas)
        meta_raw["vistas_ortograficas"] = dict(vistas)
        for cam_str in vistas.values():
            p = Path(cam_str)
            if p.is_file() and p not in arquivos:
                arquivos.append(p)
    concept_json = destino / "concept.json"
    if concept_json.is_file() and concept_json not in arquivos:
        arquivos.append(concept_json)
    return vistas


def gerar_template_humanoide(
    item: dict,
    perfil: dict,
    destino: Path,
    imagem: Path,
    concept_meta: dict | None,
    env: dict[str, str],
    t0: float,
) -> tuple[str, list[Path], dict[str, Any]]:
    from .. import post
    from ..errors import erro_provider_run

    decidir_rembg = _diag.facade_attr("_decidir_rembg", _diag._decidir_rembg)
    py_img_fn = _diag.facade_attr("_python_imagem", _diag._python_imagem)
    prep_script_fn = _diag.facade_attr("script_template_prep", _diag.script_template_prep)
    body_script_fn = _diag.facade_attr("script_template_body", _diag.script_template_body)
    rembg_mod_fn = _diag.facade_attr("_rembg_modelo", _diag._rembg_modelo)
    delight_fn = _diag.facade_attr("_delight_ativo", _diag._delight_ativo)
    qualidade_fn = _diag.facade_attr("_qualidade", _diag._qualidade)
    estilo_fn = _diag.facade_attr("_extrair_estilo_makehuman", _diag._extrair_estilo_makehuman)

    remover_fundo, motivo_rembg = decidir_rembg(imagem, concept_meta)
    prep_json = destino / "template_prep.json"
    cmd_prep = [
        str(py_img_fn()),
        str(prep_script_fn()),
        "--imagem",
        str(imagem),
        "--saida-dir",
        str(destino),
        "--resultado",
        str(prep_json),
    ]
    if remover_fundo:
        cmd_prep.extend(["--remover-fundo", "--rembg-modelo", rembg_mod_fn()])
    if delight_fn(item):
        cmd_prep.append("--delight")

    timeout_s = _diag.facade_attr("TIMEOUT_S", _diag.TIMEOUT_S)
    try:
        proc_p = _diag.subproc_run(
            cmd_prep, capture_output=True, text=True, timeout=timeout_s, env=env
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise erro_provider_run(f"falha template_prep: {exc}", id=item.get("id")) from exc
    if proc_p.returncode != 0 or not prep_json.is_file():
        raise erro_provider_run(
            "template_prep falhou",
            id=item.get("id"),
            exit=proc_p.returncode,
            stderr=(proc_p.stderr or proc_p.stdout or "")[-2000:],
        )
    prep_data = ler_json_obrigatorio(prep_json, "template_prep", item.get("id"))

    tex_max = int((perfil.get("material") or {}).get("textura_max") or 1024)
    mat_max = int((perfil.get("validacao") or {}).get("materiais_max") or 8)
    qualidade = qualidade_fn(item)
    usar_grip_padrao = bool(
        qualidade == "hero" or item.get("sockets") or item.get("auto_rig", True)
    )
    pose_mao_r = str(
        item.get("pose_mao_r") or ("grip" if usar_grip_padrao else "relaxed")
    ).strip()
    pose_mao_l = str(
        item.get("pose_mao_l") or ("cupped" if usar_grip_padrao else "relaxed")
    ).strip()
    job_path = destino / "template_job.json"
    job_data: dict[str, Any] = {
        "foto": prep_data["foto_template"],
        "saida": str(destino),
        "marcos": prep_data.get("marcos") or {},
        "textura": max(256, min(tex_max, 2048)),
        "materiais_max": mat_max,
        "limite_triangulos": int(item.get("limite_triangulos") or 12000),
        "rig": False,
        "projetar_foto_2d": bool(item.get("projetar_foto_2d") is True),
        "corpo_nu": bool(item.get("corpo_nu") is True),
        "qualidade": qualidade,
        "pose_mao_r": pose_mao_r,
        "pose_mao_l": pose_mao_l,
    }
    if item.get("macro"):
        job_data["macro"] = dict(item["macro"])
    mh_cabelo = estilo_fn(item)
    if mh_cabelo:
        job_data["makehuman_cabelo"] = mh_cabelo
    for chave_opt in ("cor_cabelo", "prompt", "cor"):
        if item.get(chave_opt):
            job_data[chave_opt] = str(item[chave_opt]).strip()
    if item.get("paleta"):
        job_data["paleta"] = list(item["paleta"])
    job_path.write_text(json.dumps(job_data, indent=1) + "\n", encoding="utf-8")

    try:
        proc_b = _diag.subproc_run(
            [post.binario(), "-b", "--python", str(body_script_fn()), "--", str(job_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise erro_provider_run(f"falha blender template_body: {exc}", id=item.get("id")) from exc

    glb = destino / "template_body.glb"
    rel_path = destino / "relatorio.json"
    if proc_b.returncode != 0 or not glb.is_file() or not rel_path.is_file():
        raise erro_provider_run(
            "blender template_body nao produziu template_body.glb",
            id=item.get("id"),
            exit=proc_b.returncode,
            stderr=(proc_b.stderr or proc_b.stdout or "")[-2000:],
        )

    rel_tmpl = ler_json_obrigatorio(rel_path, "template_body", item.get("id"))
    metallic_hint = str(prep_data.get("metallic_hint") or "").strip()
    if not metallic_hint and (destino / "metallic_hint.png").is_file():
        metallic_hint = "metallic_hint.png"
    roughness_hint = str(prep_data.get("roughness_hint") or "").strip()
    if not roughness_hint and (destino / "roughness_hint.png").is_file():
        roughness_hint = "roughness_hint.png"

    modelo: dict[str, Any] = {
        "schema": "forge3d/bruto-arquivo@1",
        "arquivo": "template_body.glb",
        "atlas": "baseColor.png",
        "origem_nome": imagem.name,
        "canonicalizar": False,
        "suavizar": True,
        "pivos": {},
        "concept": concept_meta,
        "proteger_decimate": True,
    }
    if metallic_hint:
        modelo["metallic_hint"] = metallic_hint
    if roughness_hint:
        modelo["roughness_hint"] = roughness_hint

    extras = [
        p
        for p in (
            destino / "baseColor.png",
            destino / "hair_baseColor.png",
            destino / "input_template.png",
            destino / "metallic_hint.png",
            destino / "roughness_hint.png",
        )
        if p.is_file()
    ]
    arq_modelo = destino / "modelo.json"
    resultado_path = destino / "i23d_resultado.json"
    arquivos = [arq_modelo, glb, resultado_path, *extras]
    meta_raw: dict[str, Any] = {
        "modelo": "mpfb2",
        "modo": "mpfb2_template",
        "rembg": remover_fundo,
        "rembg_motivo": motivo_rembg,
        "rembg_modelo": prep_data.get("rembg_modelo"),
        "template": rel_tmpl,
        "concept": concept_meta,
    }
    anexar_concept_vistas(modelo, meta_raw, arquivos, destino, item, concept_meta)
    arq_modelo.write_text(
        json.dumps(modelo, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    resultado = {
        "ok": True,
        "modo": "mpfb2_template",
        "modelo": "mpfb2",
        "rembg": remover_fundo,
        "rembg_motivo": motivo_rembg,
        "rembg_modelo": prep_data.get("rembg_modelo"),
        "rembg_fallback": prep_data.get("rembg_fallback", False),
        "delight": prep_data.get("delight", {}),
        "template": rel_tmpl,
        "tempo_provider_s": round(time.monotonic() - t0, 3),
    }
    resultado_path.write_text(
        json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return str(modelo["schema"]), arquivos, meta_raw


def gerar_makehuman_cabelo(
    item: dict,
    perfil: dict,
    destino: Path,
    env: dict[str, str],
    t0: float,
) -> tuple[str, list[Path], dict[str, Any]]:
    from .. import post
    from ..errors import erro_provider_run

    estilo_fn = _diag.facade_attr("_extrair_estilo_makehuman", _diag._extrair_estilo_makehuman)
    body_script_fn = _diag.facade_attr("script_template_body", _diag.script_template_body)
    estilo = estilo_fn(item)
    if not estilo:
        raise erro_provider_run("makehuman_cabelo vazio", id=item.get("id"))

    tex_max = int((perfil.get("material") or {}).get("textura_max") or 1024)
    job_path = destino / "template_job.json"
    job_data: dict[str, Any] = {
        "modo": "cabelo",
        "makehuman_cabelo": estilo,
        "saida": str(destino),
        "limite_triangulos": int(item.get("limite_triangulos") or 6000),
        "textura": max(256, min(tex_max, 2048)),
        "material": str(item.get("material") or "alpha_clip"),
    }
    if item.get("cor_cabelo"):
        job_data["cor_cabelo"] = str(item["cor_cabelo"]).strip()
    if item.get("macro"):
        job_data["macro"] = dict(item["macro"])
    job_path.write_text(json.dumps(job_data, indent=1) + "\n", encoding="utf-8")

    try:
        proc_b = _diag.subproc_run(
            [post.binario(), "-b", "--python", str(body_script_fn()), "--", str(job_path)],
            capture_output=True,
            text=True,
            timeout=_diag.facade_attr("TIMEOUT_S", _diag.TIMEOUT_S),
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise erro_provider_run(f"falha blender makehuman_cabelo: {exc}", id=item.get("id")) from exc

    glb = destino / "template_hair.glb"
    rel_path = destino / "relatorio.json"
    if proc_b.returncode != 0 or not glb.is_file() or not rel_path.is_file():
        raise erro_provider_run(
            "blender template_body (modo cabelo) nao produziu template_hair.glb",
            id=item.get("id"),
            exit=proc_b.returncode,
            stderr=(proc_b.stderr or proc_b.stdout or "")[-2000:],
        )

    rel_tmpl = ler_json_obrigatorio(rel_path, "makehuman_cabelo", item.get("id"))
    estilo_norm = str(rel_tmpl.get("estilo") or estilo)
    pivos_cabelo: dict[str, Any] = {}
    if isinstance(rel_tmpl.get("pivos"), dict):
        pivos_cabelo.update(rel_tmpl["pivos"])
    for chave_pivo in ("cabeca", "encaixe_cabeca"):
        if rel_tmpl.get(chave_pivo):
            pivos_cabelo[chave_pivo] = rel_tmpl[chave_pivo]

    modelo: dict[str, Any] = {
        "schema": "forge3d/bruto-arquivo@1",
        "arquivo": "template_hair.glb",
        "atlas": "baseColor.png",
        "origem_nome": f"makehuman://hair/{estilo_norm}",
        "canonicalizar": False,
        "suavizar": False,
        "pivos": pivos_cabelo,
        "concept": None,
        "proteger_decimate": False,
    }
    arq_modelo = destino / "modelo.json"
    arq_modelo.write_text(
        json.dumps(modelo, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    resultado_path = destino / "i23d_resultado.json"
    resultado = {
        "ok": True,
        "modo": "mpfb2_cabelo",
        "modelo": "mpfb2",
        "estilo": estilo_norm,
        "template": rel_tmpl,
        "tempo_provider_s": round(time.monotonic() - t0, 3),
    }
    resultado_path.write_text(
        json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    extras = [p for p in (destino / "baseColor.png",) if p.is_file()]
    meta_raw: dict[str, Any] = {
        "modelo": "mpfb2",
        "modo": "mpfb2_cabelo",
        "estilo": estilo_norm,
        "template": rel_tmpl,
        "concept": None,
    }
    return str(modelo["schema"]), [arq_modelo, glb, resultado_path, *extras], meta_raw
