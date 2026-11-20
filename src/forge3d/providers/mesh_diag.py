"""Diagnosticos, resolvedores de ambiente/scripts e predicados da rota ``mesh``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .. import locks, paths

VERSAO = "0.1.10"
MODELO_PADRAO = "triposr"
MODELO_HF = "stabilityai/TripoSR"
VRAM_MINIMA_MB = 4200
TIMEOUT_S = 900
SUBROTAS_EXPLICITAS = ("i23d", "template", "procedural", "extrude_2d")

#: diagnostico da venv e caro (importa torch); cache por processo e por venv
_DIAGNOSTICO: dict[tuple[str, str], dict] = {}


def facade_attr(nome: str, fallback: Any) -> Any:
    """Resolve atributos dinamicamente via ``forge3d.providers.mesh`` para preservar monkeypatches."""
    mod = sys.modules.get("forge3d.providers.mesh")
    if mod is not None:
        return getattr(mod, nome, fallback)
    return fallback


def subproc_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Executa ``subprocess.run`` atraves da fachada ``mesh.subprocess``."""
    sub_mod = facade_attr("subprocess", subprocess)
    return sub_mod.run(*args, **kwargs)


def _device() -> str:
    """cuda:0 (default) ou cpu; CPU e fallback lento para quando a GPU esta ocupada."""
    return os.environ.get(
        "FORGE3D_I23D_DEVICE", os.environ.get("FORGE3D_DEVICE", "cuda:0")
    ).strip().lower()


def modelo_escolhido() -> str:
    """Modelo de image-to-3D. Env permite trocar sem tocar em codigo; licenca e gate (D18)."""
    return os.environ.get(
        "FORGE3D_MODELO_MESH", facade_attr("MODELO_PADRAO", MODELO_PADRAO)
    ).strip().lower()


def dir_venv() -> Path:
    """Venv unica de i23d. GAP-031: uma so, selecionada por ``FORGE3D_VENV_I23D``."""
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


def pesos_triposr() -> Path | None:
    """Onde os pesos do TripoSR estao de fato (GAP-040/C10)."""
    candidatos: list[Path] = []
    explicito = os.environ.get("FORGE3D_MODELOS")
    if explicito:
        base = facade_attr("dir_modelos", dir_modelos)()
        candidatos += [base / "TripoSR", base / "models--stabilityai--TripoSR"]
        candidatos += sorted(p for p in base.glob("*TripoSR*") if p.is_dir())
    cache_hf_fn = facade_attr("_cache_hf", _cache_hf)
    candidatos.append(cache_hf_fn() / "models--stabilityai--TripoSR")
    if not explicito:
        base = facade_attr("dir_modelos", dir_modelos)()
        candidatos += [base / "TripoSR", base / "models--stabilityai--TripoSR"]
    vistos: set[Path] = set()
    for caminho in candidatos:
        if caminho in vistos:
            continue
        vistos.add(caminho)
        if caminho.is_dir():
            return caminho
    return None


def script_inferencia() -> Path:
    """Script que roda dentro da venv. Vive no repo, nao no pacote instalado."""
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


def _resolver_blender_script(env_var: str, nome_arquivo: str) -> Path:
    env = os.environ.get(env_var)
    if env and Path(env).is_file():
        return Path(env).expanduser().resolve()
    for base in (paths.raiz_dados(), Path(__file__).resolve().parents[1] / "data"):
        alvo = base / "blender" / nome_arquivo
        if alvo.is_file():
            return alvo
    return paths.raiz_dados() / "blender" / nome_arquivo


def script_template_body() -> Path:
    return _resolver_blender_script("FORGE3D_TEMPLATE_BODY_SCRIPT", "template_body.py")


def script_modular_armor() -> Path:
    return _resolver_blender_script("FORGE3D_MODULAR_ARMOR_SCRIPT", "modular_armor.py")


def script_organic_sculpt() -> Path:
    return _resolver_blender_script("FORGE3D_ORGANIC_SCULPT_SCRIPT", "organic_sculpt.py")


def _python_imagem() -> Path:
    """Python da venv-i23d ou venv-concept (que ja possuem cv2/numpy/PIL)."""
    py_i23d = facade_attr("dir_venv", dir_venv)() / "bin" / "python"
    if os.environ.get("FORGE3D_VENV_I23D", "").strip():
        return py_i23d
    if py_i23d.is_file():
        return py_i23d
    from . import concept as _concept

    py_concept = _concept.dir_venv() / "bin" / "python"
    if os.environ.get("FORGE3D_VENV_CONCEPT", "").strip():
        return py_concept
    if py_concept.is_file():
        return py_concept
    return Path(sys.executable)


def _rembg_modelo() -> str:
    env = os.environ.get("FORGE3D_REMBG_MODELO", "").strip()
    if env:
        return env
    u2net_home = Path(os.environ.get("U2NET_HOME", str(Path.home() / ".u2net"))).expanduser()
    if (u2net_home / "birefnet-general-lite.onnx").is_file():
        return "birefnet-general-lite"
    return "birefnet-general"


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
    return facade_attr("_qualidade", _qualidade)(item) in ("standard", "hero")


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


_PARTES_ROUPA_MH = ("elmo", "ombreiras", "peitoral", "luvas", "calcas", "calças", "botas", "escudo", "capa")


def _usar_makehuman_cabelo(item: dict) -> bool:
    raw_origem = str(item.get("origem") or "").strip()
    parte_raw = item.get("parte")
    parte = (str(parte_raw).strip().lower() or None) if parte_raw is not None else None
    tipo = str(item.get("tipo") or "").strip()
    if raw_origem.startswith("makehuman://"):
        if not raw_origem.startswith("makehuman://hair/"):
            return False
        return parte == "cabelo" or (parte is None and tipo in ("", "prop_estatico"))
    if str(item.get("makehuman_cabelo") or "").strip() and (
        parte == "cabelo" or (tipo == "prop_estatico" and parte is None)
    ):
        return True
    return False


def _usar_modular_armor(item: dict) -> bool:
    if item.get("extrudir_2d") is True or str(item.get("makehuman_cabelo") or "").strip():
        return False
    raw_origem = str(item.get("origem") or "").strip()
    parte = str(item.get("parte") or "").strip().lower()
    if raw_origem.startswith("makehuman://"):
        return raw_origem.startswith("makehuman://clothes/") and parte in _PARTES_ROUPA_MH
    if parte in (*_PARTES_ROUPA_MH[:-1], "mochila", "orbe", "sela"):
        return True
    if parte in ("capa", "arma") and item.get("extrudir_2d") is False and not raw_origem:
        return True
    return False


def mpfb2_cc0_disponivel() -> tuple[bool, str]:
    """Verifica se o addon MPFB2 e o pacote CC0 (makehuman_system_assets_cc0.zip) estao instalados."""
    zip_env = os.environ.get("FORGE3D_MPFB_ASSETS_ZIP", "").strip()
    if zip_env:
        zip_path = Path(zip_env).expanduser()
    else:
        zip_path = (
            Path.home()
            / ".cache"
            / "forge3d"
            / "mpfb_assets"
            / "makehuman_system_assets_cc0.zip"
        )
    if not zip_path.is_file():
        return False, f"pacote CC0 ausente em {zip_path}"

    mpfb_env = os.environ.get("FORGE3D_MPFB_DIR", "").strip()
    raizes_ext: list[Path] = []
    if mpfb_env:
        raizes_ext.append(Path(mpfb_env).expanduser())
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        raizes_ext.append(Path(xdg).expanduser() / "blender" / "4.2" / "extensions")
    raizes_ext.append(Path.home() / ".config" / "blender" / "4.2" / "extensions")

    tem_addon = any(
        raiz.is_dir() and ((raiz / "__init__.py").is_file() or any(raiz.glob("**/mpfb/__init__.py")))
        for raiz in raizes_ext
    )
    if not tem_addon:
        return False, "extensao Blender MPFB2 ausente em ~/.config/blender/4.2/extensions"
    return True, f"pronto (MPFB2 + {zip_path.name})"


def _usar_template_humanoide(item: dict) -> bool:
    if facade_attr("_usar_makehuman_cabelo", _usar_makehuman_cabelo)(item):
        return False
    if item.get("tipo") != "personagem_humanoide":
        return False
    if str(item.get("rota") or "").strip().lower() == "i23d":
        return False
    if item.get("parte") and item.get("parte") != "corpo":
        return False
    if item.get("template_humanoide") is True:
        return True
    if item.get("template_humanoide") is False:
        return False
    if item.get("vistas") == 4 or str(item.get("vistas") or "").strip() == "4":
        return False
    if item.get("makehuman_cabelo"):
        return True
    env_flag = os.environ.get("FORGE3D_HUMANOIDE_TEMPLATE", "").strip().lower()
    if env_flag in ("0", "false", "nao", "off"):
        return False
    if env_flag in ("1", "true", "sim", "on"):
        return True
    if "pose_guard" in item:
        return False
    ok_mpfb, _ = facade_attr("mpfb2_cc0_disponivel", mpfb2_cc0_disponivel)()
    return ok_mpfb


def _usar_template_criatura(item: dict) -> bool:
    tipo = str(item.get("tipo") or "").strip()
    if tipo not in ("criatura_alada", "criatura_quadrupede", "montaria"):
        return False
    if str(item.get("origem") or "").strip():
        return False
    if item.get("template_humanoide") is False:
        return False
    env_flag = os.environ.get("FORGE3D_CRIATURA_TEMPLATE", "").strip().lower()
    if env_flag in ("0", "false", "nao", "off"):
        return False
    return True


def _vram_minima_mb() -> int:
    raw = os.environ.get("FORGE3D_VRAM_MINIMA_MB", "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            sys.stderr.write(
                f"[mesh] FORGE3D_VRAM_MINIMA_MB invalido ({raw!r}); usando {VRAM_MINIMA_MB}\n"
            )
    return int(facade_attr("VRAM_MINIMA_MB", VRAM_MINIMA_MB))


def _vram_livre_mb() -> int | None:
    from . import mesh_trellis

    if mesh_trellis.endpoint_trellis_configurado():
        return None
    return locks.vram_livre_mb()


def _diagnostico() -> dict:
    """Importa ``torch`` e ``tsr`` NA venv, via subprocesso. Nunca no processo do nucleo."""
    from ..errors import ForgeError
    from . import mesh_trellis

    ep_remoto = mesh_trellis.endpoint_trellis_configurado()
    if ep_remoto:
        try:
            ep_val, mod_val = mesh_trellis.validar_endpoint_trellis(ep_remoto)
        except ForgeError as exc:
            return {"ok": False, "razao": exc.mensagem}
        return {"ok": True, "remoto": ep_val, "modelo": mod_val, "cuda": False}

    venv = facade_attr("dir_venv", dir_venv)()
    vendor = facade_attr("dir_vendor", dir_vendor)()
    cache_diag: dict[tuple[str, str], dict] = facade_attr("_DIAGNOSTICO", _DIAGNOSTICO)
    chave = (str(venv), str(vendor))
    if chave in cache_diag:
        return cache_diag[chave]

    python = venv / "bin" / "python"
    infer_script = facade_attr("script_inferencia", script_inferencia)()
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
    elif not infer_script.is_file():
        resultado = {
            "ok": False,
            "razao": f"P3: script de inferência ausente em {infer_script}",
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
            proc = subproc_run(
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
            elif not info.get("cuda") and not facade_attr("_device", _device)().startswith("cpu"):
                resultado = {"ok": False, "razao": "P3: venv de i23d sem CUDA disponível"}
            else:
                resultado = {"ok": True, "torch": info.get("torch"), "cuda": True}
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            resultado = {"ok": False, "razao": f"P3: falha ao diagnosticar a venv de i23d: {exc}"}

    cache_diag[chave] = resultado
    return resultado


def _politica_rembg() -> str:
    """Politica de remocao de fundo que entra na versao/cache (C9)."""
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
    politica = facade_attr("_politica_rembg", _politica_rembg)()
    if politica == "on":
        return True, "env=1"
    if politica == "off":
        return False, "env=0"
    if concept_meta is not None:
        return True, "concept"
    tem_alfa, detalhe = facade_attr("_alfa_util", _alfa_util)(imagem)
    if tem_alfa:
        return False, f"imagem com fundo transparente ({detalhe})"
    return True, f"fundo opaco ({detalhe})"


def _preflight_concept_item(item: dict) -> tuple[bool, str]:
    from .concept import ConceptProvider

    cp = ConceptProvider()
    if item.get("provider_conceito") or os.environ.get("FORGE3D_PROVIDER_CONCEITO"):
        try:
            return cp.preflight(item)
        except TypeError:
            return cp.preflight()
    return cp.preflight()
