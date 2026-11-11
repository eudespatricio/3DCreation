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
import subprocess
import time
from pathlib import Path
from typing import Any

from .. import locks, paths
from .base import RawAsset

VERSAO = "0.1.8"
MODELO_PADRAO = "triposr"
MODELO_HF = "stabilityai/TripoSR"
VRAM_MINIMA_MB = 3500
TIMEOUT_S = 900

#: diagnóstico da venv é caro (importa torch); cache por processo e por venv
_DIAGNOSTICO: dict[tuple[str, str], dict] = {}


def _device() -> str:
    """cuda:0 (default) ou cpu; CPU e fallback lento para quando a GPU esta ocupada."""
    return os.environ.get(
        "FORGE3D_I23D_DEVICE", os.environ.get("FORGE3D_DEVICE", "cuda:0")
    ).strip().lower()


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


def pesos_triposr() -> Path | None:
    """Onde os pesos do TripoSR estao de fato (GAP-040/C10).

    O preflight olhava so o cache HF e dizia "ausentes" com os pesos no disco apontado
    por ``FORGE3D_MODELOS``. A ordem e: caminho explicito do env, cache HF e, por
    ultimo, o diretorio padrao de modelos do Forge3D.
    """
    candidatos: list[Path] = []
    explicito = os.environ.get("FORGE3D_MODELOS")
    if explicito:
        base = dir_modelos()
        candidatos += [base / "TripoSR", base / "models--stabilityai--TripoSR"]
        candidatos += sorted(p for p in base.glob("*TripoSR*") if p.is_dir())
    candidatos.append(_cache_hf() / "models--stabilityai--TripoSR")
    if not explicito:
        base = dir_modelos()
        candidatos += [base / "TripoSR", base / "models--stabilityai--TripoSR"]
    vistos: set[Path] = set()
    for caminho in candidatos:
        if caminho in vistos:
            continue
        vistos.add(caminho)
        if caminho.is_dir():
            return caminho
    return None


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
    return locks.vram_livre_mb()


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
            elif not info.get("cuda") and not _device().startswith("cpu"):
                resultado = {"ok": False, "razao": "P3: venv de i23d sem CUDA disponível"}
            else:
                resultado = {"ok": True, "torch": info.get("torch"), "cuda": True}
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            resultado = {"ok": False, "razao": f"P3: falha ao diagnosticar a venv de i23d: {exc}"}

    _DIAGNOSTICO[chave] = resultado
    return resultado


def _politica_rembg() -> str:
    """Politica de remocao de fundo que entra na versao/cache (C9).

    ``auto2`` decide por procedencia e canal alfa; ``on``/``off`` sao override explicito
    por ``FORGE3D_I23D_REMOVER_FUNDO``.
    """
    bruto = os.environ.get("FORGE3D_I23D_REMOVER_FUNDO", "").strip().lower()
    if bruto in ("1", "true", "sim"):
        return "on"
    if bruto in ("0", "false", "nao"):
        return "off"
    return "auto2"


def _alfa_util(imagem: Path) -> tuple[bool, str]:
    """A imagem ja tem fundo transparente? Le o canal alfa e o metadado do PNG (GAP-039)."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow e dependencia do nucleo (D26)
        return False, "sem-pillow"
    try:
        with Image.open(imagem) as img:
            tem_alfa = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
            if not tem_alfa:
                return False, "sem-alfa"
            alfa = img.convert("RGBA").getchannel("A")
            histograma = alfa.histogram()
            total = sum(histograma) or 1
            fracao = sum(histograma[:250]) / total
    except (OSError, ValueError):
        return False, "ilegivel"
    return fracao >= 0.01, f"alfa={fracao:.1%}"


def _decidir_rembg(imagem: Path, concept_meta: dict | None) -> tuple[bool, str]:
    """Decide remover fundo por procedencia/alfa, com override explicito por env (C9)."""
    politica = _politica_rembg()
    if politica == "on":
        return True, "env=1"
    if politica == "off":
        return False, "env=0"
    if concept_meta is not None:
        return True, "concept"
    tem_alfa, detalhe = _alfa_util(imagem)
    if tem_alfa:
        return False, f"imagem com fundo transparente ({detalhe})"
    return True, f"fundo opaco ({detalhe})"


class MeshProvider:
    nome = "mesh"
    determinism = "D2"  # image-to-3D nunca é D1 (D7)
    usa_gpu = True

    @property
    def versao(self) -> str:
        """Versao efetiva: entra na chave de cache (D6) e muda com as opcoes de env."""
        rembg = _politica_rembg()
        mc = os.environ.get("FORGE3D_MC_RESOLUTION", "256").strip()
        tex = os.environ.get("FORGE3D_TEX_PX", "1024").strip()
        from . import concept as _concept

        concept = (
            os.environ.get("FORGE3D_MODELO_CONCEPT", "sd15").strip().replace("/", "_")
        )
        c_ver = _concept.VERSAO
        c_pose = os.environ.get("FORGE3D_CONCEPT_POSE", "").strip().lower() or "auto"
        c_step = os.environ.get("FORGE3D_CONCEPT_PASSOS", "25").strip()
        c_w = os.environ.get("FORGE3D_CONCEPT_LARGURA", "512").strip()
        c_h = os.environ.get("FORGE3D_CONCEPT_ALTURA", "512").strip()
        c_g = os.environ.get("FORGE3D_CONCEPT_GUIDANCE", "7.5").strip()
        dev = _device().replace(":", "").replace("/", "_")
        return (
            f"{VERSAO}+mc{mc}+tex{tex}+rembg{rembg}+concept{concept}@{c_ver}"
            f"+p{c_pose}+c{c_w}x{c_h}s{c_step}g{c_g}+cut2+dev{dev}"
        )

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
        # [estimado] mesh medido (23,3 s) + concept SD1.5 (a medir); vram no pico do i23d
        if _device().startswith("cpu"):
            return {"segundos_estimados": 220.0 if not item.get("origem") else 200.0, "vram_mb": 0, "disco_mb": 4500}
        if not item.get("origem"):
            return {"segundos_estimados": 40.0, "vram_mb": 3500, "disco_mb": 4500}
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

        if not _device().startswith("cpu"):
            livre = _vram_livre_mb()
            if livre is not None and livre < VRAM_MINIMA_MB:
                return False, f"P3: VRAM livre {livre} MiB < {VRAM_MINIMA_MB} MiB exigidos"

        pesos = pesos_triposr()
        if pesos is None:
            return False, (
                f"P3: pesos do TripoSR ausentes em "
                f"{_cache_hf() / 'models--stabilityai--TripoSR'} e em {dir_modelos()} "
                "(GAP-040: o preflight respeita FORGE3D_MODELOS)"
            )

        return True, (
            f"pronto (TripoSR, torch {diagnostico.get('torch', '?')}, venv {dir_venv().name})"
        )

    def preflight_item(self, item: dict) -> tuple[bool, str]:
        """Preflight do item: sem `origem`, o estagio concept tambem precisa estar pronto."""
        pronto, razao = self.preflight()
        if not pronto:
            return pronto, razao
        if item.get("origem"):
            return True, razao
        from .concept import ConceptProvider

        c_pronto, c_razao = ConceptProvider().preflight()
        if not c_pronto:
            return False, c_razao
        return True, f"{razao}; concept: {c_razao}"

    def gerar(self, item: dict, perfil: dict, destino: Path) -> RawAsset:
        from ..errors import erro_provider_run

        pronto, razao = self.preflight_item(item)
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
        concept_meta = None
        if origem:
            imagem = Path(str(origem)).expanduser()
            if not imagem.is_file():
                raise erro_provider_run(
                    f"imagem de concept inexistente: {imagem}", id=item.get("id")
                )
            if imagem.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                raise erro_provider_run(
                    f"formato de concept não suportado: {imagem.suffix}", id=item.get("id")
                )
        else:
            from .concept import ConceptProvider

            concept = ConceptProvider().gerar(item, destino)
            imagem = concept["png"]
            concept_meta = concept["meta"]

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
            "--device",
            _device(),
        ]
        remover_fundo, motivo_rembg = _decidir_rembg(imagem, concept_meta)
        if remover_fundo:
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

        textura_px = int(os.environ.get("FORGE3D_TEX_PX", "1024"))
        modelo: dict[str, Any] = {
            "schema": "forge3d/bruto-arquivo@1",
            "arquivo": "modelo.glb",
            "origem_nome": imagem.name,
            "canonicalizar": True,
            "textura_px": max(64, min(textura_px, 1024)),
            "pivos": {},
            "concept": concept_meta,
        }
        arq_modelo = destino / "modelo.json"
        arq_modelo.write_text(
            json.dumps(modelo, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        resultado["rembg"] = remover_fundo
        resultado["rembg_motivo"] = motivo_rembg
        resultado["tempo_provider_s"] = round(time.monotonic() - t0, 3)
        resultado_path.write_text(
            json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8"
        )
        return RawAsset(
            dir=destino,
            schema=str(modelo["schema"]),
            determinism=self.determinism,
            arquivos=[arq_modelo, glb, resultado_path, destino / "input.png"],
            meta={
                "modelo": MODELO_HF,
                "torch": resultado.get("torch"),
                "mc_resolution": resultado.get("mc_resolution"),
                "tempos_s": resultado.get("tempos_s"),
                "vram_pico_mb": resultado.get("vram_pico_mb"),
                "faces": resultado.get("faces"),
                "rembg": remover_fundo,
                "rembg_motivo": motivo_rembg,
                "concept": concept_meta,
            },
        )
