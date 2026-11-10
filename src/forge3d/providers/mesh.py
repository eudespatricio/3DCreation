"""Rota ``mesh`` — image-to-3D local na venv de GPU (P3).

O núcleo não importa ``torch``: a inferência roda em **subprocesso** dentro da venv de i23d,
selecionável por ``FORGE3D_VENV_I23D``. O canal é JSON em disco (mesma regra do Blender, I9).

Cadeia implementada nesta fase:

    imagem PNG ──► TripoSR (GPU) ──► GLB com COLOR_0 ──► bake de UV/textura no bpy
                                                   ──► pós-processo/QC/publicação

O provider de *concept* (text-to-image) continua em GAP-026: por isso a rota exige ``origem``
(uma imagem) enquanto o prompt é proveniência, não entrada. A licença é gate (D18) e a GPU é
serializada pelo lock do pipeline (D11).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .. import paths
from .base import RawAsset

VERSAO = "0.1.0"
MODELO_PADRAO = "triposr"
MODELO_HF = "stabilityai/TripoSR"
VRAM_MINIMA_MB = 3500
TIMEOUT_S = 900

#: diagnóstico da venv é caro (importa torch); cache por processo e por venv
_DIAGNOSTICO: dict[tuple[str, str], dict] = {}


def modelo_escolhido() -> str:
    """Modelo de image-to-3D. Env permite trocar sem tocar em código; licença é gate (D18)."""
    return os.environ.get("FORGE3D_MODELO_MESH", MODELO_PADRAO).strip().lower()


def dir_venv() -> Path:
    """Venv única de i23d. GAP-031: uma só, selecionada por ``FORGE3D_VENV_I23D``."""
    env = os.environ.get("FORGE3D_VENV_I23D")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".cache" / "forge3d" / "venv-i23d"


def dir_vendor() -> Path:
    env = os.environ.get("FORGE3D_TRIPOSR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".cache" / "forge3d" / "vendor" / "TripoSR"


def dir_modelos() -> Path:
    env = os.environ.get("FORGE3D_MODELOS")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".cache" / "forge3d" / "modelos"


def _cache_hf() -> Path:
    env = os.environ.get("HF_HOME")
    base = Path(env).expanduser().resolve() if env else Path.home() / ".cache" / "huggingface"
    return base / "hub"


def script_inferencia() -> Path:
    """Script que roda dentro da venv. Vive no repo, não no pacote instalado."""
    env = os.environ.get("FORGE3D_I23D_SCRIPT")
    if env:
        return Path(env).expanduser().resolve()
    return paths.raiz_dados() / "tools" / "i23d_infer.py"


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
    """Importa ``torch`` e ``tsr`` NA venv, via subprocesso. Nunca no processo do núcleo."""
    venv = dir_venv()
    vendor = dir_vendor()
    chave = (str(venv), str(vendor))
    if chave in _DIAGNOSTICO:
        return _DIAGNOSTICO[chave]

    python = venv / "bin" / "python"
    if not python.is_file():
        resultado = {
            "ok": False,
            "razao": (
                f"P3: venv de i23d ausente em {venv} — defina FORGE3D_VENV_I23D "
                "(docs/dependencias.md §4)"
            ),
        }
    elif not vendor.is_dir():
        resultado = {"ok": False, "razao": f"P3: vendor do TripoSR ausente em {vendor}"}
    elif not script_inferencia().is_file():
        resultado = {
            "ok": False,
            "razao": f"P3: script de inferência ausente em {script_inferencia()}",
        }
    else:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(vendor) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        codigo = (
            "import json, torch, tsr; "
            "print(json.dumps({'torch': torch.__version__, "
            "'cuda': bool(torch.cuda.is_available())}))"
        )
        try:
            proc = subprocess.run(
                [str(python), "-c", codigo],
                capture_output=True,
                text=True,
                timeout=180,
                env=env,
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
                        "P3: falha ao importar torch/tsr na venv de i23d: "
                        + (detalhe[-1] if detalhe else f"exit {proc.returncode}")
                    ),
                }
            elif not info.get("cuda"):
                resultado = {"ok": False, "razao": "P3: venv de i23d sem CUDA disponível"}
            else:
                resultado = {"ok": True, "torch": info.get("torch"), "cuda": True}
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            resultado = {"ok": False, "razao": f"P3: falha ao diagnosticar a venv de i23d: {exc}"}

    _DIAGNOSTICO[chave] = resultado
    return resultado


class MeshProvider:
    nome = "mesh"
    determinism = "D2"  # image-to-3D nunca é D1 (D7)
    usa_gpu = True

    @property
    def versao(self) -> str:
        """Versao efetiva: entra na chave de cache (D6) e muda com as opcoes de env."""
        rembg = os.environ.get("FORGE3D_I23D_REMOVER_FUNDO", "").strip().lower() in (
            "1",
            "true",
            "sim",
        )
        mc = os.environ.get("FORGE3D_MC_RESOLUTION", "256").strip()
        tex = os.environ.get("FORGE3D_TEX_PX", "512").strip()
        return f"{VERSAO}+mc{mc}+tex{tex}+rembg{int(rembg)}"

    def _licenca(self) -> dict:
        from . import LICENCAS

        modelo = modelo_escolhido()
        if modelo not in LICENCAS:
            from ..errors import erro_licenca

            raise erro_licenca(
                f"FORGE3D_MODELO_MESH='{modelo}' fora da allowlist comercial. "
                f"Permitidos: {', '.join(sorted(LICENCAS))}",
                modelo=modelo,
            )
        return dict(LICENCAS[modelo])

    @property
    def licenca(self) -> dict:
        return self._licenca()

    def capabilities(self) -> set[str]:
        return {"organic", "riggable", "pbr", "detail"}

    def custo(self, item: dict, perfil: dict) -> dict:
        # medido em 10/11/2026: TripoSR ~18 s de provider (12,6 s de inferencia) + bake 2,8 s + Blender ~2 s
        return {"segundos_estimados": 25.0, "vram_mb": 3200, "disco_mb": 250}

    def preflight(self) -> tuple[bool, str]:
        """Diagnóstico nomeado: cada falta vira uma frase que diz o que instalar."""
        from ..errors import ForgeError

        try:
            self._licenca()
        except ForgeError as exc:
            return False, exc.mensagem

        modelo = modelo_escolhido()
        if modelo == "sf3d":
            return False, (
                "P3: SF3D encerrado em 6 GB (GAP-035: ~8 min/imagem); "
                "use FORGE3D_MODELO_MESH=triposr"
            )
        if modelo != "triposr":
            return False, f"P3: modelo '{modelo}' reconhecido na licença, mas sem provider implementado"

        diagnostico = _diagnostico()
        if not diagnostico["ok"]:
            return False, diagnostico["razao"]

        livre = _vram_livre_mb()
        if livre is not None and livre < VRAM_MINIMA_MB:
            return False, f"P3: VRAM livre {livre} MiB < {VRAM_MINIMA_MB} MiB exigidos"

        pesos = _cache_hf() / "models--stabilityai--TripoSR"
        if not pesos.is_dir():
            return False, f"P3: pesos do TripoSR ausentes em {pesos}"

        return True, (
            f"pronto (TripoSR, torch {diagnostico.get('torch', '?')}, venv {dir_venv().name})"
        )

    def gerar(self, item: dict, perfil: dict, destino: Path) -> RawAsset:
        from ..errors import erro_provider_run

        pronto, razao = self.preflight()
        if not pronto:
            if "VRAM" in razao:
                from ..errors import erro_recurso

                raise erro_recurso(
                    f"rota mesh sem VRAM: {razao}",
                    id=item.get("id"),
                    modelo=modelo_escolhido(),
                )
            raise erro_provider_run(
                f"rota mesh indisponivel: {razao}",
                id=item.get("id"),
                modelo=modelo_escolhido(),
            )

        origem = item.get("origem")
        if not origem:
            raise erro_provider_run(
                "rota mesh exige 'origem' (PNG de concept) enquanto o provider de concept "
                "text-to-image não existe (GAP-026)",
                id=item.get("id"),
                modelo=modelo_escolhido(),
            )
        imagem = Path(str(origem)).expanduser()
        if not imagem.is_file():
            raise erro_provider_run(
                f"imagem de concept inexistente: {imagem}", id=item.get("id")
            )
        if imagem.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise erro_provider_run(
                f"formato de concept não suportado: {imagem.suffix}", id=item.get("id")
            )

        destino.mkdir(parents=True, exist_ok=True)
        resultado_path = destino / "i23d_resultado.json"
        if resultado_path.exists():
            resultado_path.unlink()

        env = dict(os.environ)
        env["PYTHONPATH"] = str(dir_vendor()) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        env.setdefault("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
        env.setdefault("TORCH_HOME", str(Path.home() / ".cache" / "torch"))
        env.setdefault("PYTHONUNBUFFERED", "1")

        resolucao = os.environ.get("FORGE3D_MC_RESOLUTION", "256")
        comando = [
            str(dir_venv() / "bin" / "python"),
            str(script_inferencia()),
            "--imagem",
            str(imagem),
            "--saida-dir",
            str(destino),
            "--resultado",
            str(resultado_path),
            "--modelo",
            MODELO_HF,
            "--mc-resolution",
            str(int(resolucao)),
        ]
        if os.environ.get("FORGE3D_I23D_REMOVER_FUNDO", "").strip() in ("1", "true", "sim"):
            comando.append("--remover-fundo")

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                comando, capture_output=True, text=True, timeout=TIMEOUT_S, env=env
            )
        except subprocess.TimeoutExpired:
            raise erro_provider_run(
                f"timeout de {TIMEOUT_S}s na inferência i23d", id=item.get("id")
            ) from None
        except OSError as exc:
            raise erro_provider_run(
                f"falha ao executar a venv de i23d: {exc}", id=item.get("id")
            ) from exc

        if not resultado_path.is_file():
            raise erro_provider_run(
                "i23d não escreveu resultado.json",
                id=item.get("id"),
                exit=proc.returncode,
                stderr=(proc.stderr or proc.stdout or "")[-2000:],
            )
        try:
            resultado = json.loads(resultado_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise erro_provider_run(f"resultado.json do i23d ilegível: {exc}") from exc
        if not resultado.get("ok"):
            raise erro_provider_run(
                f"i23d falhou: {resultado.get('erro')}",
                id=item.get("id"),
                stderr=(resultado.get("traceback") or "")[-2000:],
            )

        glb = destino / "modelo.glb"
        if not glb.is_file():
            raise erro_provider_run(
                f"i23d não produziu modelo.glb em {destino}", id=item.get("id")
            )

        textura_px = int(os.environ.get("FORGE3D_TEX_PX", "512"))
        modelo = {
            "schema": "forge3d/bruto-arquivo@1",
            "arquivo": "modelo.glb",
            "origem_nome": imagem.name,
            "canonicalizar": True,
            "textura_px": max(64, min(textura_px, 1024)),
            "pivos": {},
        }
        arq_modelo = destino / "modelo.json"
        arq_modelo.write_text(
            json.dumps(modelo, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        resultado["tempo_provider_s"] = round(time.monotonic() - t0, 3)
        resultado_path.write_text(
            json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8"
        )
        return RawAsset(
            dir=destino,
            schema=modelo["schema"],
            determinism=self.determinism,
            arquivos=[arq_modelo, glb, resultado_path, destino / "input.png"],
            meta={
                "modelo": MODELO_HF,
                "torch": resultado.get("torch"),
                "mc_resolution": resultado.get("mc_resolution"),
                "tempos_s": resultado.get("tempos_s"),
                "vram_pico_mb": resultado.get("vram_pico_mb"),
                "faces": resultado.get("faces"),
            },
        )
