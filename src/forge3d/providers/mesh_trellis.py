"""Cliente HTTP stdlib para inferencia remota TRELLIS.2-4B / Pixal3D / TRELLIS-image-large (MIT, D18/D26)."""

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..errors import erro_licenca, erro_provider_run
from . import mesh_diag as _diag

MODELO_TRELLIS_PADRAO = "microsoft/TRELLIS.2-4B"

MODELOS_TRELLIS_MIT: dict[str, str] = {
    "microsoft/TRELLIS.2-4B": "microsoft/TRELLIS.2-4B",
    "TRELLIS.2-4B": "microsoft/TRELLIS.2-4B",
    "microsoft/TRELLIS.2": "microsoft/TRELLIS.2-4B",
    "TRELLIS.2": "microsoft/TRELLIS.2-4B",
    "trellis2": "microsoft/TRELLIS.2-4B",
    "trellis": "microsoft/TRELLIS.2-4B",
    "JeffreyXiang/TRELLIS.2-4B": "JeffreyXiang/TRELLIS.2-4B",
    "TencentARC/Pixal3D": "TencentARC/Pixal3D",
    "Pixal3D": "TencentARC/Pixal3D",
    "microsoft/TRELLIS-image-large": "microsoft/TRELLIS-image-large",
    "JeffreyXiang/TRELLIS-image-large": "JeffreyXiang/TRELLIS-image-large",
    "TRELLIS-image-large": "microsoft/TRELLIS-image-large",
}

_MAPA_MIT_NORM: dict[str, str] = {k.lower(): v for k, v in MODELOS_TRELLIS_MIT.items()}


def endpoint_trellis_configurado() -> str:
    """Retorna ``FORGE3D_I23D_ENDPOINT`` limpo ou string vazia quando desativado."""
    return os.environ.get("FORGE3D_I23D_ENDPOINT", "").strip()


def exige_i23d_remoto() -> bool:
    """Indica se ``FORGE3D_I23D_REQUIRE_REMOTE`` bloqueia fallback silencioso para TripoSR local."""
    return os.environ.get("FORGE3D_I23D_REQUIRE_REMOTE", "").strip().lower() in ("1", "true", "sim", "on")


def calcular_decimation_target(item: dict[str, Any]) -> int:
    """Calcula ``decimation_target`` para ``o_voxel.postprocess.to_glb`` no TRELLIS.2."""
    env_raw = os.environ.get("FORGE3D_I23D_DECIMATION_TARGET", "").strip()
    if env_raw:
        val = int(env_raw)
        if val <= 0:
            raise ValueError(f"FORGE3D_I23D_DECIMATION_TARGET deve ser > 0: {env_raw!r}")
        return max(8_000, min(300_000, val))
    lim_item = int(item.get("limite_triangulos") or 0)
    alvo = min(max(int(item.get("limite_triangulos") or 16_000) * 4, 48_000), 100_000)
    return max(alvo, lim_item)


def validar_modelo_trellis_licenca(modelo: str | None = None) -> str:
    """Valida ``FORGE3D_I23D_TRELLIS_MODEL`` contra a allowlist comercial MIT (D18/I7)."""
    bruto = modelo if modelo is not None else os.environ.get("FORGE3D_I23D_TRELLIS_MODEL", MODELO_TRELLIS_PADRAO)
    chave = str(bruto or "").strip() or MODELO_TRELLIS_PADRAO
    canon = _MAPA_MIT_NORM.get(chave.lower())
    if canon is None:
        raise erro_licenca(
            f"FORGE3D_I23D_TRELLIS_MODEL={chave!r} fora da allowlist comercial MIT (D18). Aceitos: {', '.join(sorted(MODELOS_TRELLIS_MIT))}",
            modelo=chave,
        )
    return canon


def validar_endpoint_trellis(endpoint: str | None = None) -> tuple[str, str]:
    """Valida esquema HTTP(S) do endpoint e modelo MIT configurado."""
    ep = (endpoint if endpoint is not None else endpoint_trellis_configurado()).strip()
    partes = urllib.parse.urlsplit(ep)
    if partes.scheme not in ("http", "https") or not partes.netloc:
        raise erro_provider_run(f"FORGE3D_I23D_ENDPOINT invalido (use http:// ou https://): {ep!r}", modelo="trellis")
    return ep, validar_modelo_trellis_licenca()


def _resolver_url_generate(endpoint: str) -> str:
    return endpoint.rstrip("/") + "/generate" if urllib.parse.urlsplit(endpoint).path in ("", "/") else endpoint


def _preparar_inputs_locais(imagem: Path, destino: Path, env: dict[str, str]) -> tuple[Path, Path | None]:
    input_png = destino / "input.png"
    if imagem.resolve() != input_png.resolve():
        shutil.copyfile(imagem, input_png)
    input_rgba = destino / "input_rgba.png"
    if _diag.facade_attr("_alfa_util", _diag._alfa_util)(imagem)[0]:
        if imagem.resolve() != input_rgba.resolve():
            shutil.copyfile(imagem, input_rgba)
        return input_png, input_rgba

    pg_script = _diag.facade_attr("script_pose_guard", _diag.script_pose_guard)()
    py_img = _diag.facade_attr("_python_imagem", _diag._python_imagem)()
    if not py_img.is_file():
        py_img = Path(sys.executable)
    if not pg_script.is_file():
        sys.stderr.write(f"[mesh_trellis] aviso pose_guard.py ausente ({pg_script}); mantendo input opaco\n")
        return input_png, None
    try:
        proc = _diag.subproc_run(
            [str(py_img), str(pg_script), "--acao", "decompor", "--imagem", str(imagem), "--saida-png", str(input_rgba), "--resultado", str(destino / "cutout_front_resultado.json")],
            capture_output=True, text=True, timeout=_diag.facade_attr("TIMEOUT_S", _diag.TIMEOUT_S), env=env,
        )
        if proc.returncode == 0 and input_rgba.is_file():
            return input_png, input_rgba
        sys.stderr.write(f"[mesh_trellis] aviso recorte 2D falhou (exit {proc.returncode}); mantendo input opaco\n")
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        sys.stderr.write(f"[mesh_trellis] aviso recorte 2D indisponivel ({exc}); mantendo input opaco\n")
    return input_png, None


def executar_i23d_remoto(
    item: dict[str, Any],
    destino: Path,
    imagem: Path,
    vistas_paths: dict[str, str] | None,
    env: dict[str, str],
) -> dict[str, Any]:
    """Executa inferencia 3D remota via HTTP (Colab TRELLIS.2-4B / Pixal3D) com 0 MB de VRAM local."""
    from . import LICENCAS, cloud_ai

    cloud_ai.registrar_licencas_cloud()
    ep, modelo_canon = validar_endpoint_trellis()
    destino.mkdir(parents=True, exist_ok=True)
    input_png, input_rgba = _preparar_inputs_locais(imagem, destino, env)

    front_src = input_rgba if (input_rgba and input_rgba.is_file()) else input_png
    imagens_b64: dict[str, str] = {
        "front": base64.b64encode(front_src.read_bytes()).decode("ascii")
    }
    if isinstance(vistas_paths, dict):
        for chave in ("back", "left", "right"):
            cam = vistas_paths.get(chave)
            if cam and Path(cam).is_file():
                imagens_b64[chave] = base64.b64encode(Path(cam).read_bytes()).decode("ascii")

    qual = _diag.facade_attr("_qualidade", _diag._qualidade)(item)
    tex_def = "2048" if qual in ("hero", "ultra") else "1024"
    try:
        seed_raw = item.get("seed")
        seed = int(seed_raw) if seed_raw is not None else 1
        tex_size = int(os.environ.get("FORGE3D_TEX_PX", tex_def))
        simplify = float(os.environ.get("FORGE3D_I23D_SIMPLIFY", "0.95"))
        decimation_target = calcular_decimation_target(item)
        timeout_s = max(1, int(os.environ.get("FORGE3D_I23D_TIMEOUT", "600")))
    except (TypeError, ValueError) as exc:
        raise erro_provider_run(f"parametro invalido para TRELLIS remoto: {exc}", id=item.get("id"), modelo="trellis") from exc

    token = os.environ.get("FORGE3D_I23D_TOKEN", "").strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "model": modelo_canon,
        "seed": seed,
        "images": imagens_b64,
        "texture_size": tex_size,
        "simplify": simplify,
        "decimation_target": decimation_target,
    }
    req = urllib.request.Request(
        _resolver_url_generate(ep),
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    t0 = time.monotonic()
    segredos = [token] if token else []
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            ctype = str(getattr(resp, "headers", {}).get("Content-Type", "")).lower()
            raw_resp = resp.read()
    except urllib.error.HTTPError as exc:
        try:
            det = exc.read().decode("utf-8", errors="replace")[:500]
        except (OSError, ValueError, AttributeError) as r_exc:
            det = f"{exc} ({r_exc})"
        limpo = cloud_ai._sanitizar_texto_erro(f"HTTP {exc.code}: {det}", segredos)
        raise erro_provider_run(f"falha HTTP TRELLIS remoto ({modelo_canon}): {limpo}", id=item.get("id"), modelo="trellis") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        limpo = cloud_ai._sanitizar_texto_erro(str(exc), segredos)
        raise erro_provider_run(f"falha de rede TRELLIS remoto ({modelo_canon}): {limpo}", id=item.get("id"), modelo="trellis") from None

    if "application/octet-stream" in ctype or "model/gltf-binary" in ctype or raw_resp[:4] == b"glTF":
        glb_bytes = raw_resp
        faces: int | None = None
        modelo_final = modelo_canon
        tempo_s = round(time.monotonic() - t0, 3)
    else:
        try:
            dados = json.loads(raw_resp.decode("utf-8"))
            if not isinstance(dados, dict):
                raise ValueError("resposta JSON nao e objeto")
            if dados.get("ok") is False:
                raise ValueError(str(dados.get("erro") or "servidor retornou ok=false"))
            b64_glb = dados.get("glb_base64") or dados.get("glb")
            if not isinstance(b64_glb, str) or not b64_glb.strip():
                raise ValueError("resposta JSON sem glb_base64")
            glb_bytes = base64.b64decode(b64_glb)
        except (UnicodeDecodeError, ValueError, binascii.Error) as exc:
            limpo = cloud_ai._sanitizar_texto_erro(str(exc), segredos)
            raise erro_provider_run(f"resposta invalida TRELLIS remoto: {limpo}", id=item.get("id"), modelo="trellis") from None
        modelo_final = validar_modelo_trellis_licenca(str(dados.get("modelo") or modelo_canon))
        faces = int(dados["faces"]) if isinstance(dados.get("faces"), (int, float)) else None
        tempo_s = float(dados.get("tempo_s", round(time.monotonic() - t0, 3)))

    if not glb_bytes:
        raise erro_provider_run("TRELLIS remoto retornou GLB vazio", id=item.get("id"), modelo="trellis")

    (destino / "modelo.glb").write_bytes(glb_bytes)
    resultado: dict[str, Any] = {
        "ok": True,
        "provedor": "trellis_remoto",
        "modelo": modelo_final,
        "faces": faces,
        "tempo_s": round(tempo_s, 3),
        "vistas_enviadas": sorted(imagens_b64.keys()),
        "licenca": dict(LICENCAS["trellis"]),
    }
    (destino / "i23d_resultado.json").write_text(json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return resultado
