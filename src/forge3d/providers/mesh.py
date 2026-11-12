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
import sys
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


def script_pose_guard() -> Path:
    env = os.environ.get("FORGE3D_POSE_GUARD_SCRIPT")
    if env:
        return Path(env).expanduser().resolve()
    return paths.raiz_dados() / "tools" / "pose_guard.py"


def script_delight() -> Path:
    env = os.environ.get("FORGE3D_DELIGHT_SCRIPT")
    if env:
        return Path(env).expanduser().resolve()
    return paths.raiz_dados() / "tools" / "delight.py"


def script_template_prep() -> Path:
    env = os.environ.get("FORGE3D_TEMPLATE_PREP_SCRIPT")
    if env:
        return Path(env).expanduser().resolve()
    return paths.raiz_dados() / "tools" / "template_prep.py"


def script_template_body() -> Path:
    env = os.environ.get("FORGE3D_TEMPLATE_BODY_SCRIPT")
    if env and Path(env).is_file():
        return Path(env).expanduser().resolve()
    for base in (paths.raiz_dados(), Path(__file__).resolve().parents[1] / "data"):
        alvo = base / "blender" / "template_body.py"
        if alvo.is_file():
            return alvo
    return paths.raiz_dados() / "blender" / "template_body.py"


def script_modular_armor() -> Path:
    env = os.environ.get("FORGE3D_MODULAR_ARMOR_SCRIPT")
    if env and Path(env).is_file():
        return Path(env).expanduser().resolve()
    for base in (paths.raiz_dados(), Path(__file__).resolve().parents[1] / "data"):
        alvo = base / "blender" / "modular_armor.py"
        if alvo.is_file():
            return alvo
    return paths.raiz_dados() / "blender" / "modular_armor.py"


def _python_imagem() -> Path:
    """Python da venv-i23d ou venv-concept (que ja possuem cv2/numpy/PIL)."""
    py_i23d = dir_venv() / "bin" / "python"
    if py_i23d.is_file():
        return py_i23d
    from . import concept as _concept

    py_concept = _concept.dir_venv() / "bin" / "python"
    if py_concept.is_file():
        return py_concept
    return Path(sys.executable)


def _rembg_modelo() -> str:
    return os.environ.get("FORGE3D_REMBG_MODELO", "birefnet-general").strip() or "birefnet-general"


def _pose_guard_modo(item: dict | None = None) -> str:
    raw = str((item or {}).get("pose_guard") or os.environ.get("FORGE3D_POSE_GUARD", "auto"))
    modo = raw.strip().lower()
    return modo if modo in ("off", "auto", "repose") else "auto"


def _qualidade(item: dict | None = None) -> str:
    raw = str((item or {}).get("qualidade") or os.environ.get("FORGE3D_QUALIDADE", "standard"))
    val = raw.strip().lower()
    return val or "standard"


def _delight_ativo(item: dict | None = None) -> bool:
    env = os.environ.get("FORGE3D_DELIGHT", "").strip().lower()
    if env in ("0", "false", "nao", "off"):
        return False
    if env in ("1", "true", "sim", "on"):
        return True
    return _qualidade(item) in ("standard", "hero")


def _usar_extrude_2d(item: dict) -> bool:
    if item.get("extrudir_2d") is True:
        return True
    if item.get("extrudir_2d") is False:
        return False
    return item.get("parte") in ("arma", "escudo")


def _extrair_estilo_makehuman(item: dict) -> str | None:
    bruto = str(item.get("makehuman_cabelo") or "").strip()
    if bruto:
        return bruto
    origem = str(item.get("origem") or "").strip()
    if origem.startswith("makehuman://"):
        corpo = origem[len("makehuman://"):].strip("/")
        if corpo.startswith("hair/"):
            corpo = corpo[len("hair/"):].strip("/")
        return corpo or None
    return None


def _usar_makehuman_cabelo(item: dict) -> bool:
    raw_origem = str(item.get("origem") or "").strip()
    if raw_origem.startswith("makehuman://hair/"):
        return True
    if raw_origem.startswith("makehuman://") and not raw_origem.startswith("makehuman://clothes/"):
        if item.get("parte") in ("cabelo", None):
            return True
    if bool(item.get("makehuman_cabelo")) and (
        item.get("parte") == "cabelo" or item.get("tipo") == "prop_estatico"
    ):
        return True
    return False


def _usar_modular_armor(item: dict) -> bool:
    if item.get("extrudir_2d") is True:
        return False
    raw_origem = str(item.get("origem") or "").strip()
    if raw_origem.startswith("makehuman://clothes/"):
        return True
    parte = str(item.get("parte") or "").strip().lower()
    if parte in ("elmo", "ombreiras", "peitoral", "luvas", "calcas", "calças", "botas"):
        return True
    return False


def _usar_template_humanoide(item: dict) -> bool:
    if _usar_makehuman_cabelo(item):
        return False
    if item.get("tipo") != "personagem_humanoide":
        return False
    if item.get("parte") and item.get("parte") != "corpo":
        return False
    if item.get("template_humanoide") is True:
        return True
    if item.get("template_humanoide") is False:
        return False
    if item.get("makehuman_cabelo"):
        return True
    return os.environ.get("FORGE3D_HUMANOIDE_TEMPLATE", "").strip() == "1"


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
        rembg_mod = _rembg_modelo().replace("/", "_").replace(":", "_")
        pg_mode = _pose_guard_modo(None)
        delight = "1" if _delight_ativo(None) else "0"
        qualidade = _qualidade(None)
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
        tmpl = "1" if os.environ.get("FORGE3D_HUMANOIDE_TEMPLATE", "").strip() == "1" else "0"
        dev = _device().replace(":", "").replace("/", "_")
        return (
            f"{VERSAO}+mc{mc}+tex{tex}+rembg{rembg}"
            f"+rm{rembg_mod}+pg{pg_mode}+dl{delight}+q{qualidade}"
            f"+concept{concept}@{c_ver}"
            f"+p{c_pose}+c{c_w}x{c_h}s{c_step}g{c_g}+cut2+tx2+tmpl2_{tmpl}+mh1+dev{dev}"
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
        if _usar_makehuman_cabelo(item):
            return {"segundos_estimados": 6.0, "vram_mb": 0, "disco_mb": 20}
        if _usar_template_humanoide(item):
            return {"segundos_estimados": 18.0 if item.get("origem") else 35.0, "vram_mb": 0, "disco_mb": 120}
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
        if _usar_makehuman_cabelo(item):
            from ..errors import ForgeError
            from ..post import binario

            try:
                binario()
            except ForgeError as exc:
                return False, exc.mensagem
            if not script_template_body().is_file():
                return False, "script blender/template_body.py ausente"
            estilo = _extrair_estilo_makehuman(item)
            if not estilo:
                return False, "makehuman_cabelo / origem makehuman://hair/<estilo> vazio"
            return True, f"pronto (cabelo MakeHuman/MPFB2 CC0: {estilo})"

        if _usar_modular_armor(item):
            from ..errors import ForgeError
            from ..post import binario

            try:
                binario()
            except ForgeError as exc:
                return False, exc.mensagem
            if not script_modular_armor().is_file():
                return False, "script blender/modular_armor.py ausente"
            return True, f"pronto (modular armor MakeHuman/MPFB2 CC0: {item.get('parte')})"

        if _usar_template_humanoide(item):
            from ..errors import ForgeError
            from ..post import binario

            try:
                binario()
            except ForgeError as exc:
                return False, exc.mensagem
            if not _python_imagem().is_file():
                return False, f"P3: venv de imagem ausente em {dir_venv()}"
            if not script_template_prep().is_file() or not script_template_body().is_file():
                return False, "scripts de template MPFB2 ausentes"
            if item.get("origem"):
                return True, "pronto (template MPFB2 com origem)"
            from .concept import ConceptProvider

            c_pronto, c_razao = ConceptProvider().preflight()
            if not c_pronto:
                return False, c_razao
            return True, f"pronto (template MPFB2); concept: {c_razao}"

        if _usar_extrude_2d(item):
            if item.get("origem"):
                return True, "pronto (extrude 2D com origem)"
            from .concept import ConceptProvider

            c_pronto, c_razao = ConceptProvider().preflight()
            if not c_pronto:
                return False, c_razao
            return True, f"pronto (extrude 2D); concept: {c_razao}"

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

    def _executar_pose_guard(
        self, item: dict, imagem: Path, destino: Path, env: dict[str, str]
    ) -> tuple[Path, dict[str, Any]]:
        from . import concept as _concept

        pg_mode = _pose_guard_modo(item)
        report: dict[str, Any] = {
            "modo": pg_mode,
            "executado": False,
            "repose_aplicado": False,
        }
        if not item.get("origem"):
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
        pg_script = script_pose_guard()
        if not pg_script.is_file():
            report["motivo"] = "pose_guard.py ausente"
            return imagem, report

        pg_json = destino / "pose_guard_resultado.json"
        proc = subprocess.run(
            [
                str(_python_imagem()),
                str(pg_script),
                "--imagem",
                str(imagem),
                "--resultado",
                str(pg_json),
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env=env,
        )
        if proc.returncode != 0 or not pg_json.is_file():
            report["motivo"] = f"falha pose_guard (exit {proc.returncode})"
            return imagem, report
        try:
            pg_data = json.loads(pg_json.read_text(encoding="utf-8"))
        except ValueError:
            report["motivo"] = "pose_guard_resultado.json ilegivel"
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
        prompt_final = _concept.combinar_prompt(prompt_base, sufixo)
        negative_final = _concept.negativo_efetivo(item)
        repose_png = destino / "origem_repose.png"
        repose_json = destino / "repose_resultado.json"
        strength = os.environ.get("FORGE3D_POSE_GUARD_STRENGTH", "0.45").strip() or "0.45"
        cn_scale = os.environ.get("FORGE3D_CONCEPT_CONTROLNET_SCALE", "0.85").strip() or "0.85"

        cmd_repose = [
            str(_concept.dir_venv() / "bin" / "python"),
            str(_concept.script_inferencia()),
            "--prompt",
            prompt_final,
            "--negative",
            negative_final,
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
            cn_scale,
            "--init-imagem",
            str(imagem),
            "--strength",
            strength,
        ]
        proc_rp = subprocess.run(
            cmd_repose, capture_output=True, text=True, timeout=TIMEOUT_S, env=env
        )
        if proc_rp.returncode == 0 and repose_png.is_file():
            report["repose_aplicado"] = True
            report["pose_alvo"] = pose_alvo
            report["origem_repose"] = str(repose_png)
            if repose_json.is_file():
                try:
                    report["repose_meta"] = json.loads(repose_json.read_text(encoding="utf-8"))
                except ValueError:
                    pass
            return repose_png, report

        report["repose_erro"] = (proc_rp.stderr or proc_rp.stdout or f"exit {proc_rp.returncode}")[
            -500:
        ]
        return imagem, report

    def _executar_cutout_2d(
        self, imagem: Path, destino: Path, env: dict[str, str], item_id: Any
    ) -> tuple[Path, dict[str, Any]]:
        from ..errors import erro_provider_run

        cutout_png = destino / "input_cutout.png"
        cutout_json = destino / "cutout_resultado.json"
        pg_script = script_pose_guard()
        if not pg_script.is_file():
            raise erro_provider_run(f"pose_guard.py ausente em {pg_script}", id=item_id)

        try:
            proc = subprocess.run(
                [
                    str(_python_imagem()),
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
                timeout=TIMEOUT_S,
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise erro_provider_run(
                f"timeout de {TIMEOUT_S}s no recorte 2D", id=item_id
            ) from None
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
            try:
                info = json.loads(cutout_json.read_text(encoding="utf-8"))
            except ValueError:
                info = {}
            if info and not info.get("ok"):
                raise erro_provider_run(
                    f"recorte 2D falhou: {info.get('erro')}", id=item_id
                )
        if not cutout_png.is_file():
            raise erro_provider_run(
                f"recorte 2D nao produziu {cutout_png.name} em {destino}", id=item_id
            )
        return cutout_png, info

    def _executar_delight(
        self, entrada_png: Path, destino: Path, env: dict[str, str]
    ) -> dict[str, Any]:
        dl_script = script_delight()
        albedo_png = destino / "input_delit.png"
        metallic_png = destino / "metallic_hint.png"
        roughness_png = destino / "roughness_hint.png"
        delight_json = destino / "delight_resultado.json"

        proc = subprocess.run(
            [
                str(_python_imagem()),
                str(dl_script),
                "--imagem",
                str(entrada_png),
                "--saida-albedo",
                str(albedo_png),
                "--saida-metallic",
                str(metallic_png),
                "--saida-roughness",
                str(roughness_png),
                "--resultado",
                str(delight_json),
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env=env,
        )
        report: dict[str, Any] = {"ativo": True, "executado": False}
        if delight_json.is_file():
            try:
                report.update(json.loads(delight_json.read_text(encoding="utf-8")))
            except ValueError:
                pass
        arquivos_extras: list[Path] = []
        if proc.returncode == 0 and albedo_png.is_file():
            report["executado"] = True
            arquivos_extras.append(albedo_png)
        if proc.returncode == 0 and metallic_png.is_file():
            arquivos_extras.append(metallic_png)
        if proc.returncode == 0 and roughness_png.is_file():
            arquivos_extras.append(roughness_png)
        return {
            "report": report,
            "albedo": "input_delit.png" if albedo_png in arquivos_extras else "",
            "metallic_hint": "metallic_hint.png" if metallic_png in arquivos_extras else "",
            "roughness_hint": "roughness_hint.png" if roughness_png in arquivos_extras else "",
            "arquivos": arquivos_extras,
        }

    def _gerar_template_humanoide(
        self,
        item: dict,
        perfil: dict,
        destino: Path,
        imagem: Path,
        concept_meta: dict | None,
        env: dict[str, str],
        t0: float,
    ) -> RawAsset:
        from ..errors import erro_provider_run
        from ..post import binario

        remover_fundo, motivo_rembg = _decidir_rembg(imagem, concept_meta)
        prep_json = destino / "template_prep.json"
        cmd_prep = [
            str(_python_imagem()),
            str(script_template_prep()),
            "--imagem",
            str(imagem),
            "--saida-dir",
            str(destino),
            "--resultado",
            str(prep_json),
        ]
        if remover_fundo:
            cmd_prep.extend(["--remover-fundo", "--rembg-modelo", _rembg_modelo()])
        if _delight_ativo(item):
            cmd_prep.append("--delight")

        try:
            proc_p = subprocess.run(
                cmd_prep, capture_output=True, text=True, timeout=TIMEOUT_S, env=env
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
        prep_data = json.loads(prep_json.read_text(encoding="utf-8"))

        tex_max = int((perfil.get("material") or {}).get("textura_max") or 1024)
        job_path = destino / "template_job.json"
        job_data: dict[str, Any] = {
            "foto": prep_data["foto_template"],
            "saida": str(destino),
            "marcos": prep_data.get("marcos") or {},
            "textura": max(256, min(tex_max, 2048)),
            "limite_triangulos": int(item.get("limite_triangulos") or 12000),
            "rig": False,
        }
        if item.get("macro"):
            job_data["macro"] = dict(item["macro"])
        mh_cabelo = _extrair_estilo_makehuman(item)
        if mh_cabelo:
            job_data["makehuman_cabelo"] = mh_cabelo
        if item.get("cor_cabelo"):
            job_data["cor_cabelo"] = str(item["cor_cabelo"]).strip()
        job_path.write_text(json.dumps(job_data, indent=1) + "\n", encoding="utf-8")

        try:
            proc_b = subprocess.run(
                [binario(), "-b", "--python", str(script_template_body()), "--", str(job_path)],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
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

        rel_tmpl = json.loads(rel_path.read_text(encoding="utf-8"))
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
        arq_modelo = destino / "modelo.json"
        arq_modelo.write_text(
            json.dumps(modelo, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        resultado_path = destino / "i23d_resultado.json"
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
        extras = [
            p
            for p in (
                destino / "baseColor.png",
                destino / "hair_baseColor.png",
                destino / "input_template.png",
            )
            if p.is_file()
        ]
        return RawAsset(
            dir=destino,
            schema=str(modelo["schema"]),
            determinism=self.determinism,
            arquivos=[arq_modelo, glb, resultado_path, *extras],
            meta={
                "modelo": "mpfb2",
                "modo": "mpfb2_template",
                "rembg": remover_fundo,
                "rembg_motivo": motivo_rembg,
                "rembg_modelo": prep_data.get("rembg_modelo"),
                "template": rel_tmpl,
                "concept": concept_meta,
            },
        )

    def _gerar_makehuman_cabelo(
        self,
        item: dict,
        perfil: dict,
        destino: Path,
        env: dict[str, str],
        t0: float,
    ) -> RawAsset:
        from ..errors import erro_provider_run
        from ..post import binario

        estilo = _extrair_estilo_makehuman(item)
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
            proc_b = subprocess.run(
                [binario(), "-b", "--python", str(script_template_body()), "--", str(job_path)],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
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

        rel_tmpl = json.loads(rel_path.read_text(encoding="utf-8"))
        estilo_norm = str(rel_tmpl.get("estilo") or estilo)
        modelo: dict[str, Any] = {
            "schema": "forge3d/bruto-arquivo@1",
            "arquivo": "template_hair.glb",
            "atlas": "baseColor.png",
            "origem_nome": f"makehuman://hair/{estilo_norm}",
            "canonicalizar": False,
            "suavizar": False,
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
        return RawAsset(
            dir=destino,
            schema=str(modelo["schema"]),
            determinism=self.determinism,
            arquivos=[arq_modelo, glb, resultado_path, *extras],
            meta={
                "modelo": "mpfb2",
                "modo": "mpfb2_cabelo",
                "estilo": estilo_norm,
                "template": rel_tmpl,
                "concept": None,
            },
        )

    def _gerar_modular_armor(
        self,
        item: dict,
        perfil: dict,
        destino: Path,
        env: dict[str, str],
        t0: float,
    ) -> RawAsset:
        from ..errors import erro_provider_run
        from ..post import binario

        parte = str(item.get("parte") or "peitoral").strip()
        if parte == "calças":
            parte = "calcas"

        limite_tri = int(item.get("limite_triangulos") or 10000)
        job_path = destino / "modular_armor_job.json"
        job_data: dict[str, Any] = {
            "saida": str(destino),
            "id": item.get("id"),
            "parte": parte,
            "origem": str(item.get("origem") or "").strip(),
            "altura_metros": float(item.get("altura_metros") or 1.72),
            "esqueleto": str(item.get("esqueleto") or "godot-humanoid@1"),
            "limite_triangulos": limite_tri,
            "pivot": str(item.get("pivot") or "base"),
        }
        if item.get("skinned") is not None:
            job_data["skinned"] = bool(item["skinned"])
        if item.get("macro"):
            job_data["macro"] = dict(item["macro"])
        if item.get("osso"):
            job_data["osso"] = str(item["osso"])

        job_path.write_text(json.dumps(job_data, indent=1) + "\n", encoding="utf-8")

        try:
            proc_b = subprocess.run(
                [binario(), "-b", "--python", str(script_modular_armor()), "--", str(job_path)],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
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

        rel_armor = json.loads(rel_path.read_text(encoding="utf-8"))
        modelo: dict[str, Any] = {
            "schema": "forge3d/bruto-arquivo@1",
            "arquivo": "template_armor.glb",
            "origem_nome": str(item.get("origem") or f"modular_armor://{parte}"),
            "canonicalizar": False,
            "suavizar": False,
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
            "modelo": "mpfb2_armor",
            "parte": parte,
            "skinned": rel_armor.get("skinned", False),
            "template": rel_armor,
            "tempo_provider_s": round(time.monotonic() - t0, 3),
        }
        resultado_path.write_text(
            json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8"
        )
        return RawAsset(
            dir=destino,
            schema=str(modelo["schema"]),
            determinism=self.determinism,
            arquivos=[arq_modelo, glb, resultado_path],
            meta={
                "modelo": "mpfb2_armor",
                "modo": "modular_armor",
                "parte": parte,
                "skinned": rel_armor.get("skinned", False),
                "template": rel_armor,
                "concept": None,
            },
        )

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

        t0 = time.monotonic()

        if _usar_makehuman_cabelo(item):
            return self._gerar_makehuman_cabelo(item, perfil, destino, env, t0)

        if _usar_modular_armor(item):
            return self._gerar_modular_armor(item, perfil, destino, env, t0)

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

        if _usar_template_humanoide(item):
            return self._gerar_template_humanoide(
                item, perfil, destino, imagem, concept_meta, env, t0
            )

        if _usar_extrude_2d(item):
            cutout_png, cutout_info = self._executar_cutout_2d(
                imagem, destino, env, item.get("id")
            )
            delight_ativo = _delight_ativo(item)
            delight_meta: dict[str, Any] = {"ativo": delight_ativo, "executado": False}
            arquivos_extras: list[Path] = []
            metallic_hint = ""
            roughness_hint = ""
            origem_textura = ""
            if delight_ativo and script_delight().is_file() and cutout_png.is_file():
                dl = self._executar_delight(cutout_png, destino, env)
                delight_meta = dl["report"]
                origem_textura = dl["albedo"]
                metallic_hint = dl["metallic_hint"]
                roughness_hint = dl["roughness_hint"]
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

            arq_modelo = destino / "modelo.json"
            arq_modelo.write_text(
                json.dumps(modelo, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            resultado: dict[str, Any] = {
                "ok": True,
                "modo": "extrude_2d",
                "parte": modelo["modo"],
                "cutout": cutout_info,
                "delight": delight_meta,
                "tempo_provider_s": round(time.monotonic() - t0, 3),
            }
            resultado_path.write_text(
                json.dumps(resultado, sort_keys=True, indent=1) + "\n", encoding="utf-8"
            )
            return RawAsset(
                dir=destino,
                schema="forge3d/bruto-extrude@1",
                determinism=self.determinism,
                arquivos=[arq_modelo, cutout_png, resultado_path, *arquivos_extras],
                meta={
                    "modelo": "extrude_2d",
                    "modo": modelo["modo"],
                    "cutout": cutout_info,
                    "delight": delight_meta,
                    "concept": concept_meta,
                },
            )

        imagem, pose_guard_report = self._executar_pose_guard(item, imagem, destino, env)

        resolucao = os.environ.get("FORGE3D_MC_RESOLUTION", "256")
        rembg_mod = _rembg_modelo()
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
            comando.extend(["--remover-fundo", "--rembg-modelo", rembg_mod])

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

        input_png = destino / "input.png"
        input_rgba_png = destino / "input_rgba.png"
        entrada_tex = input_rgba_png if input_rgba_png.is_file() else input_png
        delight_ativo = _delight_ativo(item)
        delight_report: dict[str, Any] = {"ativo": delight_ativo, "executado": False}
        origem_textura = entrada_tex.name
        metallic_hint = ""
        roughness_hint = ""
        arquivos_extras = [input_rgba_png] if input_rgba_png.is_file() else []
        if delight_ativo and script_delight().is_file() and entrada_tex.is_file():
            dl = self._executar_delight(entrada_tex, destino, env)
            delight_report = dl["report"]
            if dl["albedo"]:
                origem_textura = dl["albedo"]
            metallic_hint = dl["metallic_hint"]
            roughness_hint = dl["roughness_hint"]
            arquivos_extras = [*arquivos_extras, *dl["arquivos"]]

        textura_px = int(os.environ.get("FORGE3D_TEX_PX", "1024"))
        modelo = {
            "schema": "forge3d/bruto-arquivo@1",
            "arquivo": "modelo.glb",
            "origem_nome": imagem.name,
            "canonicalizar": True,
            "textura_px": max(64, min(textura_px, 1024)),
            "pivos": {},
            "concept": concept_meta,
            "proteger_decimate": item.get("tipo") in ("personagem_humanoide", "criatura"),
        }
        if entrada_tex.is_file() or not delight_ativo:
            modelo["origem_textura"] = origem_textura
        if metallic_hint:
            modelo["metallic_hint"] = metallic_hint
        if roughness_hint:
            modelo["roughness_hint"] = roughness_hint

        arq_modelo = destino / "modelo.json"
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
        return RawAsset(
            dir=destino,
            schema=str(modelo["schema"]),
            determinism=self.determinism,
            arquivos=[arq_modelo, glb, resultado_path, input_png, *arquivos_extras],
            meta={
                "modelo": MODELO_HF,
                "torch": resultado.get("torch"),
                "mc_resolution": resultado.get("mc_resolution"),
                "tempos_s": resultado.get("tempos_s"),
                "vram_pico_mb": resultado.get("vram_pico_mb"),
                "faces": resultado.get("faces"),
                "rembg": remover_fundo,
                "rembg_motivo": motivo_rembg,
                "rembg_modelo": resultado.get("rembg_modelo"),
                "rembg_fallback": resultado.get("rembg_fallback"),
                "pose_guard": pose_guard_report,
                "delight": delight_report,
                "concept": concept_meta,
            },
        )
