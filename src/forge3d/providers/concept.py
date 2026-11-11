"""Estagio ``concept`` — text-to-image local (Stable Diffusion 1.5) na venv de concept.

Nao e uma rota do lote: e a primeira etapa do provider ``mesh`` quando o item **nao** declara
``origem``. O nucleo nao importa ``torch``/``diffusers``; a inferencia roda em subprocesso na
``FORGE3D_VENV_CONCEPT`` e o canal e JSON em disco (I9).

Por que uma venv separada da i23d (D29/GAP-031): o TripoSR prende ``transformers==4.35`` e o
``diffusers`` moderno exige ``transformers>=4.44``. Sao modelos diferentes, nao duas copias do
mesmo i23d. O doc `docs/dependencias.md` registra a escolha.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

VERSAO = "0.1.1"
MODELO_PADRAO = "stable-diffusion-v1-5/stable-diffusion-v1-5"
VRAM_MINIMA_MB = 3000
TIMEOUT_S = 900

_DIAGNOSTICO: dict[tuple[str, str], dict] = {}

SUFIXO_PADRAO = (
    "isolated object, front view, centered, plain neutral light gray background, "
    "game asset concept art, soft studio lighting, high detail"
)
def _device() -> str:
    """cuda (default) ou cpu; CPU e fallback lento, mas mantem a rota utilizavel."""
    return os.environ.get(
        "FORGE3D_CONCEPT_DEVICE", os.environ.get("FORGE3D_DEVICE", "cuda")
    ).strip().lower()


NEGATIVO_PADRAO = (
    "blurry, low quality, cropped, text, watermark, logo, multiple views, "
    "busy background, extra limbs, deformed, duplicate, frame"
)


def sufixo_efetivo(prompt: str, sufixo: str) -> str:
    """Sufixo sem os trechos que o prompt ja repete (C11).

    O sufixo padrao termina em ``game asset concept art`` e varios prompts do lote tambem
    dizem isso. Duplicar nao muda a imagem e gasta tokens do CLIP, cujo limite e 77.
    """
    alvo = (prompt or "").lower()
    partes = []
    for fragmento in (sufixo or "").split(","):
        limpo = fragmento.strip()
        if not limpo or limpo.lower() in alvo:
            continue
        partes.append(limpo)
    return ", ".join(partes)


def modelo_escolhido() -> str:
    return os.environ.get("FORGE3D_MODELO_CONCEPT", MODELO_PADRAO).strip()


def dir_venv() -> Path:
    env = os.environ.get("FORGE3D_VENV_CONCEPT")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".venvs" / "concept"


def script_inferencia() -> Path:
    env = os.environ.get("FORGE3D_CONCEPT_SCRIPT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "tools" / "concept_infer.py"


def _cache_hf() -> Path:
    env = os.environ.get("HF_HOME")
    base = Path(env).expanduser().resolve() if env else Path.home() / ".cache" / "huggingface"
    return base / "hub"


def _modelo_no_cache() -> Path:
    return _cache_hf() / ("models--" + modelo_escolhido().replace("/", "--"))


def _vram_livre_mb() -> int | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        saida = subprocess.run(
            [exe, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
        return int(saida.splitlines()[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _diagnostico() -> dict:
    venv = dir_venv()
    script = script_inferencia()
    chave = (str(venv), str(script))
    if chave in _DIAGNOSTICO:
        return _DIAGNOSTICO[chave]

    python = venv / "bin" / "python"
    if not python.is_file():
        resultado = {
            "ok": False,
            "razao": (
                f"P3.5: venv de concept ausente em {venv} — defina FORGE3D_VENV_CONCEPT "
                "(docs/dependencias.md §4)"
            ),
        }
    elif not script.is_file():
        resultado = {"ok": False, "razao": f"P3.5: script de concept ausente em {script}"}
    else:
        codigo = (
            "import json, torch, diffusers, transformers; "
            "print(json.dumps({'torch': torch.__version__, "
            "'diffusers': diffusers.__version__, 'transformers': transformers.__version__, "
            "'cuda': bool(torch.cuda.is_available())}))"
        )
        try:
            proc = subprocess.run(
                [str(python), "-c", codigo],
                capture_output=True,
                text=True,
                timeout=180,
            )
            linha = next(
                (ln for ln in reversed(proc.stdout.splitlines()) if ln.strip().startswith("{")),
                "",
            )
            info = json.loads(linha) if linha else {}
            if proc.returncode != 0 or not info:
                detalhe = (proc.stderr or proc.stdout or "").strip().splitlines()
                resultado = {
                    "ok": False,
                    "razao": (
                        "P3.5: falha ao importar torch/diffusers na venv de concept: "
                        + (detalhe[-1] if detalhe else f"exit {proc.returncode}")
                    ),
                }
            elif not info.get("cuda") and not _device().startswith("cpu"):
                resultado = {"ok": False, "razao": "P3.5: venv de concept sem CUDA disponível"}
            else:
                resultado = {"ok": True, **info}
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            resultado = {"ok": False, "razao": f"P3.5: falha ao diagnosticar a venv de concept: {exc}"}

    _DIAGNOSTICO[chave] = resultado
    return resultado


def preflight() -> tuple[bool, str]:
    """Checa venv, script, CUDA e pesos. Nao baixa nada: o erro diz o que fazer."""
    diagnostico = _diagnostico()
    if not diagnostico["ok"]:
        return False, diagnostico["razao"]

    if not _device().startswith("cpu"):
        livre = _vram_livre_mb()
        if livre is not None and livre < VRAM_MINIMA_MB:
            return False, f"P3.5: VRAM livre {livre} MiB < {VRAM_MINIMA_MB} MiB exigidos pelo concept"

    pesos = _modelo_no_cache()
    if not pesos.is_dir():
        return False, (
            f"P3.5: pesos de '{modelo_escolhido()}' ausentes em {pesos}; "
            "rode tools/concept_infer.py uma vez com --modelo para baixar"
        )
    return True, (
        f"pronto (SD1.5, diffusers {diagnostico.get('diffusers', '?')}, "
        f"venv {dir_venv().name})"
    )


class ConceptProvider:
    nome = "concept"
    versao = VERSAO
    determinism = "D2"  # diffusion nunca e D1 (D7)
    usa_gpu = True

    @property
    def licenca(self) -> dict:
        from . import LICENCAS

        return dict(LICENCAS["sd15"])

    def capabilities(self) -> set[str]:
        return {"concept", "text-to-image", "image"}

    def custo(self, item: dict, perfil: dict) -> dict:
        # [estimado] a partir do SD1.5 fp16 em 6 GB; medir na primeira execucao
        if _device().startswith("cpu"):
            return {"segundos_estimados": 180.0, "vram_mb": 0, "disco_mb": 4000}
        return {"segundos_estimados": 15.0, "vram_mb": 3000, "disco_mb": 4000}

    def preflight(self) -> tuple[bool, str]:
        return preflight()

    def gerar(self, item: dict, destino: Path) -> dict:
        from ..errors import erro_provider_run, erro_recurso

        pronto, razao = preflight()
        if not pronto:
            if "VRAM" in razao:
                raise erro_recurso(
                    f"concept sem VRAM: {razao}",
                    id=item.get("id"),
                    modelo=modelo_escolhido(),
                )
            raise erro_provider_run(
                f"concept indisponivel: {razao}",
                id=item.get("id"),
                modelo=modelo_escolhido(),
            )

        prompt = (item.get("prompt") or "").strip()
        if not prompt:
            raise erro_provider_run("concept exige 'prompt' no item", id=item.get("id"))
        seed = int(item.get("seed", 20261110))
        destino.mkdir(parents=True, exist_ok=True)
        png = destino / "concept.png"
        resultado_path = destino / "concept_resultado.json"
        if resultado_path.exists():
            resultado_path.unlink()

        sufixo = os.environ.get("FORGE3D_CONCEPT_SUFIXO", SUFIXO_PADRAO).strip()
        negative = os.environ.get("FORGE3D_CONCEPT_NEGATIVO", NEGATIVO_PADRAO).strip()
        efetivo = sufixo_efetivo(prompt, sufixo)
        prompt_final = prompt if not efetivo else f"{prompt}, {efetivo}"

        env = dict(os.environ)
        env.setdefault("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
        env.setdefault("PYTHONUNBUFFERED", "1")
        comando = [
            str(dir_venv() / "bin" / "python"),
            str(script_inferencia()),
            "--prompt",
            prompt_final,
            "--negative",
            negative,
            "--seed",
            str(seed),
            "--saida",
            str(png),
            "--resultado",
            str(resultado_path),
            "--modelo",
            modelo_escolhido(),
            "--largura",
            os.environ.get("FORGE3D_CONCEPT_LARGURA", "512"),
            "--altura",
            os.environ.get("FORGE3D_CONCEPT_ALTURA", "512"),
            "--passos",
            os.environ.get("FORGE3D_CONCEPT_PASSOS", "25"),
            "--guidance",
            os.environ.get("FORGE3D_CONCEPT_GUIDANCE", "7.5"),
            "--device",
            _device(),
        ]

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                comando, capture_output=True, text=True, timeout=TIMEOUT_S, env=env
            )
        except subprocess.TimeoutExpired:
            raise erro_provider_run(
                f"timeout de {TIMEOUT_S}s na geracao de concept", id=item.get("id")
            ) from None
        except OSError as exc:
            raise erro_provider_run(
                f"falha ao executar a venv de concept: {exc}", id=item.get("id")
            ) from exc

        if not resultado_path.is_file():
            raise erro_provider_run(
                "concept nao escreveu resultado.json",
                id=item.get("id"),
                exit=proc.returncode,
                stderr=(proc.stderr or proc.stdout or "")[-2000:],
            )
        try:
            resultado = json.loads(resultado_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise erro_provider_run(f"resultado.json do concept ilegivel: {exc}") from exc
        if not resultado.get("ok"):
            raise erro_provider_run(
                f"concept falhou: {resultado.get('erro')}",
                id=item.get("id"),
                stderr=(resultado.get("traceback") or "")[-2000:],
            )
        if not png.is_file():
            raise erro_provider_run(f"concept nao produziu PNG em {destino}", id=item.get("id"))

        if resultado.get("prompt_truncado"):
            print(
                "aviso: prompt do concept truncado de "
                f"{resultado.get('prompt_tokens')} para "
                f"{resultado.get('prompt_tokens_efetivo')} tokens (limite CLIP 77)",
                file=sys.stderr,
            )

        resultado["tempo_provider_s"] = round(time.monotonic() - t0, 3)
        resultado["versao"] = VERSAO
        resultado["licenca"] = self.licenca
        resultado["prompt_final"] = prompt_final
        resultado_path.write_text(
            json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8"
        )
        return {"png": png, "meta": resultado}
