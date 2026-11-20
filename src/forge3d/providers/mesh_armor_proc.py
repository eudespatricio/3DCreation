"""Geradores modulares de armadura e criatura procedural da rota ``mesh``."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from . import mesh_diag as _diag
from .mesh_templates import ler_json_obrigatorio


def gerar_modular_armor(
    item: dict,
    perfil: dict,
    destino: Path,
    env: dict[str, str],
    t0: float,
) -> tuple[str, list[Path], dict[str, Any]]:
    from .. import post
    from ..errors import erro_provider_run

    qualidade_fn = _diag.facade_attr("_qualidade", _diag._qualidade)
    armor_script_fn = _diag.facade_attr("script_modular_armor", _diag.script_modular_armor)
    parte = str(item.get("parte") or "peitoral").strip()
    if parte == "calças":
        parte = "calcas"

    limite_tri = int(item.get("limite_triangulos") or 10000)
    tex_teto = 2048 if qualidade_fn(item) == "hero" else 1024
    tex_max = int((perfil.get("material") or {}).get("textura_max") or tex_teto)
    if qualidade_fn(item) == "hero":
        tex_max = max(tex_max, 2048)
    esqueleto = str(
        item.get("esqueleto")
        or (perfil.get("rig") or {}).get("esqueleto_padrao")
        or "godot-humanoid@1"
    )
    job_path = destino / "modular_armor_job.json"
    job_data: dict[str, Any] = {
        "saida": str(destino),
        "id": item.get("id"),
        "parte": parte,
        "origem": str(item.get("origem") or "").strip(),
        "altura_metros": float(item.get("altura_metros") or 1.72),
        "esqueleto": esqueleto,
        "limite_triangulos": limite_tri,
        "textura": max(64, min(tex_max, 2048)),
        "pivot": str(item.get("pivot") or "base"),
    }
    for chave_opt in ("prompt", "cor"):
        if item.get(chave_opt):
            job_data[chave_opt] = str(item[chave_opt]).strip()
    if item.get("paleta"):
        job_data["paleta"] = list(item["paleta"])
    if item.get("skinned") is not None:
        job_data["skinned"] = bool(item["skinned"])
    if item.get("macro"):
        job_data["macro"] = dict(item["macro"])
    if item.get("osso"):
        job_data["osso"] = str(item["osso"])
    job_path.write_text(json.dumps(job_data, indent=1) + "\n", encoding="utf-8")

    try:
        proc_b = _diag.subproc_run(
            [post.binario(), "-b", "--python", str(armor_script_fn()), "--", str(job_path)],
            capture_output=True,
            text=True,
            timeout=_diag.facade_attr("TIMEOUT_S", _diag.TIMEOUT_S),
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise erro_provider_run(f"falha blender modular_armor: {exc}", id=item.get("id")) from exc

    glb = destino / "template_armor.glb"
    rel_path = destino / "relatorio.json"
    if proc_b.returncode != 0 or not glb.is_file() or not rel_path.is_file():
        raise erro_provider_run(
            f"blender modular_armor nao produziu template_armor.glb para parte '{parte}'",
            id=item.get("id"),
            exit=proc_b.returncode,
            stderr=(proc_b.stderr or proc_b.stdout or "")[-2000:],
        )

    rel_armor = ler_json_obrigatorio(rel_path, "modular_armor", item.get("id"))
    orig_limpa = str(item.get("origem") or "").strip()
    modelo: dict[str, Any] = {
        "schema": "forge3d/bruto-arquivo@1",
        "arquivo": "template_armor.glb",
        "origem_nome": orig_limpa or f"modular_armor://{parte}",
        "canonicalizar": False,
        "suavizar": False,
        "armadura_modular": bool(rel_armor.get("armadura_modular", True)),
        "escala_preservada": bool(rel_armor.get("escala_preservada", False)),
        "retopologia": str(item.get("retopologia") or "auto"),
        "pivos": {},
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
        "modo": "modular_armor",
        "modelo": "mpfb2",
        "parte": parte,
        "skinned": rel_armor.get("skinned", False),
        "armadura_modular": True,
        "template": rel_armor,
        "tempo_provider_s": round(time.monotonic() - t0, 3),
    }
    resultado_path.write_text(
        json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    meta_raw: dict[str, Any] = {
        "modelo": "mpfb2",
        "modo": "modular_armor",
        "parte": parte,
        "skinned": rel_armor.get("skinned", False),
        "armadura_modular": True,
        "template": rel_armor,
        "concept": None,
    }
    return str(modelo["schema"]), [arq_modelo, glb, resultado_path], meta_raw


def gerar_criatura_anatomica(
    item: dict,
    _perfil: dict,
    destino: Path,
    env: dict[str, str],
    t0: float,
) -> tuple[str, list[Path], dict[str, Any]]:
    from .. import post
    from ..errors import erro_provider_run

    sculpt_script_fn = _diag.facade_attr("script_organic_sculpt", _diag.script_organic_sculpt)
    tipo = str(item.get("tipo") or "criatura_alada").strip()
    esqueleto = str(item.get("esqueleto") or "").strip()
    com_asas = bool(
        item.get("asas", tipo == "criatura_alada" or esqueleto == "winged_mount@1")
    )
    glb = destino / "bruto.glb"
    arq_modelo = destino / "modelo.json"
    job_path = destino / "criatura_anatomica_job.json"
    job_data: dict[str, Any] = {
        "acao": "gerar_criatura",
        "id": item.get("id"),
        "tipo": tipo,
        "esqueleto": esqueleto,
        "asas": com_asas,
        "saida_dir": str(destino),
        "saida_glb": str(glb),
        "saida_meta": str(arq_modelo),
    }
    job_path.write_text(json.dumps(job_data, indent=1) + "\n", encoding="utf-8")

    try:
        proc_b = _diag.subproc_run(
            [
                post.binario(),
                "-b",
                "--factory-startup",
                "--python",
                str(sculpt_script_fn()),
                "--",
                "--modo",
                "criatura",
                str(job_path),
            ],
            capture_output=True,
            text=True,
            timeout=_diag.facade_attr("TIMEOUT_S", _diag.TIMEOUT_S),
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise erro_provider_run(
            f"falha blender organic_sculpt: {exc}", id=item.get("id")
        ) from exc

    if proc_b.returncode != 0 or not glb.is_file() or not arq_modelo.is_file():
        raise erro_provider_run(
            f"blender organic_sculpt nao produziu bruto.glb para tipo '{tipo}'",
            id=item.get("id"),
            exit=proc_b.returncode,
            stderr=(proc_b.stderr or proc_b.stdout or "")[-2000:],
        )

    meta_criatura = ler_json_obrigatorio(arq_modelo, "organic_sculpt", item.get("id"))
    resultado_path = destino / "i23d_resultado.json"
    resultado = {
        "ok": True,
        "modo": "anatomical_creature_sculpt",
        "modelo": "procedural",
        "tipo": tipo,
        "asas": com_asas,
        "criatura": meta_criatura,
        "tempo_provider_s": round(time.monotonic() - t0, 3),
    }
    resultado_path.write_text(
        json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    meta_raw: dict[str, Any] = {
        "modelo": "procedural",
        "modo": "anatomical_creature_sculpt",
        "tipo": tipo,
        "asas": com_asas,
        "criatura": meta_criatura,
        "concept": None,
    }
    return (
        str(meta_criatura.get("schema", "forge3d/bruto-arquivo@1")),
        [arq_modelo, glb, resultado_path],
        meta_raw,
    )
