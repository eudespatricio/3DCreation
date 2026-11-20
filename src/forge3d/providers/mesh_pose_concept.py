"""Pose Guard e Concept Retry com propagacao de 4 vistas ortograficas."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import mesh_diag as _diag


def executar_pose_guard(
    item: dict, imagem: Path, destino: Path, env: dict[str, str]
) -> tuple[Path, dict[str, Any]]:
    from ..errors import erro_provider_run
    from . import concept as _concept

    timeout_s = _diag.facade_attr("TIMEOUT_S", _diag.TIMEOUT_S)
    pg_mode = _diag.facade_attr("_pose_guard_modo", _diag._pose_guard_modo)(item)
    pg_script_fn = _diag.facade_attr("script_pose_guard", _diag.script_pose_guard)
    py_img_fn = _diag.facade_attr("_python_imagem", _diag._python_imagem)
    report: dict[str, Any] = {
        "modo": pg_mode,
        "executado": False,
        "repose_aplicado": False,
    }
    if not str(item.get("origem") or "").strip():
        report["motivo"] = "sem origem (concept direto)"
        return imagem, report
    if item.get("tipo") != "personagem_humanoide":
        report["motivo"] = "tipo nao humanoide"
        return imagem, report
    if pg_mode not in ("auto", "repose"):
        report["motivo"] = "pose_guard desabilitado"
        return imagem, report
    if not _concept.controlnet_disponivel():
        report["motivo"] = "controlnet indisponivel"
        return imagem, report
    pg_script = pg_script_fn()
    if not pg_script.is_file():
        report["motivo"] = "pose_guard.py ausente"
        return imagem, report

    pg_json = destino / "pose_guard_resultado.json"
    try:
        proc = _diag.subproc_run(
            [
                str(py_img_fn()),
                str(pg_script),
                "--imagem",
                str(imagem),
                "--resultado",
                str(pg_json),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise erro_provider_run(f"falha pose_guard: {exc}", id=item.get("id")) from exc
    if proc.returncode != 0 or not pg_json.is_file():
        report["motivo"] = f"falha pose_guard (exit {proc.returncode})"
        return imagem, report
    try:
        pg_data = json.loads(pg_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        report["motivo"] = f"pose_guard_resultado.json ilegivel: {exc}"
        sys.stderr.write(f"[mesh] aviso {report['motivo']}\n")
        return imagem, report

    report.update(pg_data)
    report["executado"] = bool(pg_data.get("ok"))

    deve_repose = (pg_mode == "repose") or (
        pg_mode == "auto"
        and os.environ.get("FORGE3D_POSE_GUARD_REPOSE", "").strip() == "1"
    )
    if pg_data.get("pose") != "arms_down" or not deve_repose:
        return imagem, report

    pose_raw = os.environ.get("FORGE3D_CONCEPT_POSE", "tpose").strip().lower().replace("-", "")
    pose_alvo = pose_raw if pose_raw in ("tpose", "apose") else "tpose"
    largura = int(os.environ.get("FORGE3D_CONCEPT_LARGURA", "512").strip() or "512")
    altura = int(os.environ.get("FORGE3D_CONCEPT_ALTURA", "512").strip() or "512")
    pose_png = destino / f"pose_{pose_alvo}.png"
    _concept._gerar_pose_png(pose_alvo, pose_png, largura, altura)

    prompt_base = (item.get("prompt") or "").strip() or (
        "full body front view of game character, T-pose, arms extended"
    )
    sufixo = os.environ.get("FORGE3D_CONCEPT_SUFIXO", _concept.SUFIXO_PADRAO).strip()
    repose_png = destino / "origem_repose.png"
    repose_json = destino / "repose_resultado.json"
    cmd_repose = [
        str(_concept.dir_venv() / "bin" / "python"),
        str(_concept.script_inferencia()),
        "--prompt",
        _concept.combinar_prompt(prompt_base, sufixo),
        "--negative",
        _concept.negativo_efetivo(item),
        "--seed",
        str(int(item.get("seed", 20261110))),
        "--saida",
        str(repose_png),
        "--resultado",
        str(repose_json),
        "--modelo",
        _concept.modelo_escolhido(),
        "--largura",
        str(largura),
        "--altura",
        str(altura),
        "--passos",
        os.environ.get("FORGE3D_CONCEPT_PASSOS", "25").strip() or "25",
        "--guidance",
        os.environ.get("FORGE3D_CONCEPT_GUIDANCE", "7.5").strip() or "7.5",
        "--device",
        _concept._device(),
        "--controlnet",
        _concept.controlnet_modelo_escolhido(),
        "--pose-imagem",
        str(pose_png),
        "--controlnet-scale",
        os.environ.get("FORGE3D_CONCEPT_CONTROLNET_SCALE", "0.85").strip() or "0.85",
        "--init-imagem",
        str(imagem),
        "--strength",
        os.environ.get("FORGE3D_POSE_GUARD_STRENGTH", "0.45").strip() or "0.45",
    ]
    try:
        proc_rp = _diag.subproc_run(
            cmd_repose, capture_output=True, text=True, timeout=timeout_s, env=env
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise erro_provider_run(f"falha pose_guard repose: {exc}", id=item.get("id")) from exc
    if proc_rp.returncode == 0 and repose_png.is_file():
        report["repose_aplicado"] = True
        report["pose_alvo"] = pose_alvo
        report["origem_repose"] = str(repose_png)
        if repose_json.is_file():
            try:
                report["repose_meta"] = json.loads(repose_json.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                report["repose_meta_erro"] = str(exc)
                sys.stderr.write(f"[mesh] aviso repose_resultado.json invalido: {exc}\n")
        return repose_png, report

    report["repose_erro"] = (proc_rp.stderr or proc_rp.stdout or f"exit {proc_rp.returncode}")[
        -500:
    ]
    return imagem, report


def gerar_concept_com_retry(
    item: dict,
    destino: Path,
    env: dict[str, str],
    max_tentativas: int = 3,
) -> tuple[Path, dict[str, Any]]:
    from . import concept as _concept

    prov = _concept.ConceptProvider()
    eh_rigged = item.get("tipo") == "personagem_humanoide" and bool(item.get("auto_rig"))
    tentativas = max(1, int(max_tentativas)) if eh_rigged else 1
    if tentativas == 1:
        res = prov.gerar(item, destino)
        return res["png"], res["meta"]

    pg_script = _diag.facade_attr("script_pose_guard", _diag.script_pose_guard)()
    py_img = _diag.facade_attr("_python_imagem", _diag._python_imagem)()
    melhor_score = -1.0
    melhor: tuple[Path, dict[str, Any]] | None = None
    seed_base = int(item.get("seed", 20261110))
    historico: list[dict[str, Any]] = []

    for i in range(tentativas):
        sub_dir = destino / f"concept_try_{i}"
        sub_item = dict(item)
        sub_item["seed"] = seed_base + i * 101
        res = prov.gerar(sub_item, sub_dir)
        png_i: Path = res["png"]
        meta_i: dict[str, Any] = dict(res["meta"])

        score = 0.0
        apto = False
        pose_erro: str | None = None
        if pg_script.is_file() and py_img.is_file():
            res_pg = sub_dir / "pose_detect.json"
            try:
                proc = _diag.subproc_run(
                    [
                        str(py_img),
                        str(pg_script),
                        "--acao",
                        "detectar",
                        "--imagem",
                        str(png_i),
                        "--resultado",
                        str(res_pg),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=env,
                    check=False,
                )
                if proc.returncode == 0 and res_pg.is_file():
                    info_pg = json.loads(res_pg.read_text(encoding="utf-8"))
                    score = float(info_pg.get("score_pose", 0.0))
                    apto = bool(info_pg.get("apto_rig", False))
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                pose_erro = str(exc)
                sys.stderr.write(f"[mesh] aviso pose_guard detect (tentativa {i + 1}): {exc}\n")

        hist_entry: dict[str, Any] = {
            "tentativa": i + 1,
            "seed": sub_item["seed"],
            "score_pose": score,
            "apto_rig": apto,
        }
        if pose_erro:
            hist_entry["pose_detect_erro"] = pose_erro
        historico.append(hist_entry)
        if melhor is None or score > melhor_score:
            melhor_score = score
            melhor = (png_i, meta_i)
        if apto or score >= 0.72:
            break

    assert melhor is not None
    png_escolhido, meta_escolhido = melhor
    destino.mkdir(parents=True, exist_ok=True)
    destino_png = destino / png_escolhido.name
    if png_escolhido != destino_png:
        shutil.copyfile(png_escolhido, destino_png)
    if isinstance(meta_escolhido.get("vistas"), dict):
        vistas_destino: dict[str, str] = {}
        for vista, raw_p in meta_escolhido["vistas"].items():
            src_v = Path(str(raw_p))
            if src_v.is_file():
                dst_v = destino / src_v.name
                if src_v != dst_v:
                    shutil.copyfile(src_v, dst_v)
                vistas_destino[str(vista)] = str(dst_v)
        meta_escolhido["vistas"] = vistas_destino
    src_concept_json = png_escolhido.parent / "concept.json"
    dst_concept_json = destino / "concept.json"
    if src_concept_json.is_file() and src_concept_json != dst_concept_json:
        try:
            concept_data = json.loads(src_concept_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"[mesh] aviso concept.json invalido em {src_concept_json}: {exc}\n")
            shutil.copyfile(src_concept_json, dst_concept_json)
        else:
            if isinstance(concept_data, dict) and isinstance(concept_data.get("vistas"), dict):
                if isinstance(meta_escolhido.get("vistas"), dict):
                    concept_data["vistas"] = dict(meta_escolhido["vistas"])
                else:
                    concept_data["vistas"] = {
                        str(k): str(destino / Path(str(v)).name)
                        for k, v in concept_data["vistas"].items()
                    }
            dst_concept_json.write_text(
                json.dumps(concept_data, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
    meta_escolhido["concept_tentativas"] = len(historico)
    meta_escolhido["concept_score_pose"] = round(max(0.0, melhor_score), 4)
    meta_escolhido["concept_historico"] = historico
    return destino_png, meta_escolhido
