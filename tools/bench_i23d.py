"""Benchmark harness standalone de image-to-3D (Setup Onda 2).

Mede tempo por fase, pico de VRAM (``nvidia-smi`` + ``torch.cuda``), pico RSS de host,
contagem de triangulos, G1 nao-manifold, nitidez Laplaciana da ``baseColor`` e
cobertura de silhueta em 4 vistas ortograficas.

Uso:
    python tools/bench_i23d.py --imagem conceito.png --saida-dir /tmp/bench --modo baseline --json
    python tools/bench_i23d.py --modo triposg_probe --json
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import io
import json
import os
import resource
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

from forge3d import qc  # noqa: E402

try:  # noqa: SIM105 - opcional em .venv leve sem numpy/cv2
    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    _TEM_CV2 = True
except ImportError:
    cv2 = None
    np = None
    _TEM_CV2 = False


def _carregar_lod_qualidade():
    caminho = RAIZ / "tools" / "lod_qualidade.py"
    spec = importlib.util.spec_from_file_location("forge3d_lod_qualidade", caminho)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"nao foi possivel carregar {caminho}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class VramMonitor:
    """Thread daemon de polling em ``nvidia-smi`` para medir pico real de VRAM."""

    def __init__(self, intervalo_s: float = 0.15) -> None:
        self.intervalo_s = intervalo_s
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self.amostras_mb: list[int] = []
        self.base_mb: int | None = None

    @staticmethod
    def _ler_nvidia_smi() -> int | None:
        exe = shutil.which("nvidia-smi")
        if not exe:
            return None
        try:
            proc = subprocess.run(
                [exe, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            linha = next((ln.strip() for ln in proc.stdout.splitlines() if ln.strip()), "")
            return int(linha) if linha else None
        except (OSError, ValueError, subprocess.SubprocessError):
            return None

    def __enter__(self) -> VramMonitor:
        self.base_mb = self._ler_nvidia_smi()
        if self.base_mb is not None:
            self.amostras_mb.append(self.base_mb)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._parar.wait(self.intervalo_s):
            val = self._ler_nvidia_smi()
            if val is not None:
                self.amostras_mb.append(val)

    def __exit__(self, *_args: object) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def resumo(self) -> dict[str, int | None]:
        if not self.amostras_mb:
            return {"vram_base_mb": None, "vram_pico_nvml_mb": None, "vram_delta_nvml_mb": None}
        pico = max(self.amostras_mb)
        delta = pico - self.base_mb if self.base_mb is not None else None
        return {
            "vram_base_mb": self.base_mb,
            "vram_pico_nvml_mb": pico,
            "vram_delta_nvml_mb": delta,
        }


def laplacian_sharpness(imagem_ou_caminho: Image.Image | str | Path) -> float:
    """Variancia do Laplaciano (3x3) da luminancia — quanto maior, mais nitida a textura."""
    if isinstance(imagem_ou_caminho, (str, Path)):
        with Image.open(imagem_ou_caminho) as img:
            gray = img.convert("L")
    else:
        gray = imagem_ou_caminho.convert("L")

    if _TEM_CV2:
        arr = np.array(gray, dtype=np.uint8)
        return round(float(cv2.Laplacian(arr, cv2.CV_64F).var()), 4)

    w, h = gray.size
    if w < 3 or h < 3:
        return 0.0
    px = gray.tobytes()
    soma = 0.0
    soma2 = 0.0
    n = 0
    for y in range(1, h - 1):
        row = y * w
        up = (y - 1) * w
        dn = (y + 1) * w
        for x in range(1, w - 1):
            val = (
                px[up + x]
                + px[dn + x]
                + px[row + x - 1]
                + px[row + x + 1]
                - 4 * px[row + x]
            )
            soma += val
            soma2 += val * val
            n += 1
    if n == 0:
        return 0.0
    media = soma / n
    return round(max(0.0, (soma2 / n) - media * media), 4)


def extrair_basecolor_glb(glb_caminho: str | Path) -> Image.Image | None:
    """Extrai a primeira textura ``baseColor`` embutida (ou URI relativa) do GLB."""
    caminho = Path(glb_caminho)
    gltf, binario = qc.ler_glb_bin(caminho)
    imagens = gltf.get("images") or []
    texturas = gltf.get("textures") or []
    materiais = gltf.get("materials") or []

    img_idx: int | None = None
    for mat in materiais:
        pbr = mat.get("pbrMetallicRoughness") or {}
        bc = pbr.get("baseColorTexture") or {}
        if "index" in bc:
            tex_idx = int(bc["index"])
            if 0 <= tex_idx < len(texturas) and "source" in texturas[tex_idx]:
                img_idx = int(texturas[tex_idx]["source"])
                break
    if img_idx is None and imagens:
        img_idx = 0
    if img_idx is None or not (0 <= img_idx < len(imagens)):
        return None

    img_def = imagens[img_idx]
    if "bufferView" in img_def:
        bv = gltf["bufferViews"][int(img_def["bufferView"])]
        off = int(bv.get("byteOffset", 0))
        length = int(bv["byteLength"])
        return Image.open(io.BytesIO(binario[off : off + length])).convert("RGBA")

    uri = str(img_def.get("uri") or "")
    if uri.startswith("data:"):
        _, b64 = uri.split(",", 1)
        return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
    if uri:
        arq = caminho.parent / uri
        if arq.is_file():
            return Image.open(arq).convert("RGBA")
    return None


def silhouette_4view(glb_caminho: str | Path, resolucao: int = 256) -> dict[str, Any]:
    """Cobertura ortografica em 4 vistas reutilizando ``lod_qualidade._mascara``."""
    lq = _carregar_lod_qualidade()
    gltf, binario = qc.ler_glb_bin(Path(glb_caminho))
    posicoes, triangulos = qc.malha(gltf, binario)
    if not posicoes or not triangulos:
        vistas_vazias = {"frente": 0.0, "lado": 0.0, "topo": 0.0, "tres_quartos": 0.0}
        return {
            "vistas": vistas_vazias,
            "media": 0.0,
            "min": 0.0,
            "max": 0.0,
            "resolucao": resolucao,
        }

    caixa = lq._bbox(posicoes)
    pos_topo = [(p[0], p[2], p[1]) for p in posicoes]
    c = 0.7071067811865476
    pos_34 = [(c * p[0] + c * p[2], p[1], -c * p[0] + c * p[2]) for p in posicoes]

    mascaras = {
        "frente": lq._mascara(posicoes, triangulos, "frente", caixa, resolucao),
        "lado": lq._mascara(posicoes, triangulos, "lado", caixa, resolucao),
        "topo": lq._mascara(pos_topo, triangulos, "frente", lq._bbox(pos_topo), resolucao),
        "tres_quartos": lq._mascara(pos_34, triangulos, "frente", lq._bbox(pos_34), resolucao),
    }

    total = max(resolucao * resolucao, 1)
    vistas: dict[str, float] = {}
    for nome, mask in mascaras.items():
        cobertos = sum(1 for v in mask.tobytes() if v > 0)
        vistas[nome] = round(cobertos / total, 4)

    vals = list(vistas.values())
    return {
        "vistas": vistas,
        "media": round(sum(vals) / len(vals), 4),
        "min": min(vals),
        "max": max(vals),
        "resolucao": resolucao,
    }


def medir_glb(glb_caminho: str | Path, resolucao: int = 256) -> dict[str, Any]:
    """Mede geometria, G1, nitidez da textura baseColor e silhueta 4 vistas de um GLB."""
    caminho = Path(glb_caminho)
    gltf, binario = qc.ler_glb_bin(caminho)
    topo = qc.topologia(gltf, binario)
    basecolor = extrair_basecolor_glb(caminho)
    nitidez = laplacian_sharpness(basecolor) if basecolor is not None else None
    silhueta = silhouette_4view(caminho, resolucao=resolucao)
    return {
        "glb": str(caminho),
        "glb_bytes": caminho.stat().st_size,
        "triangulos": topo["triangulos"],
        "vertices": topo["vertices"],
        "g1_nao_manifold": topo["nao_manifold"],
        "g1_degeneradas": topo["degeneradas"],
        "basecolor_laplacian_var": nitidez,
        "silhouette_4view": silhueta,
    }


def _python_venv_i23d() -> Path:
    env = os.environ.get("FORGE3D_VENV_I23D")
    if env:
        return Path(env).expanduser().resolve() / "bin" / "python"
    padrao = Path.home() / ".cache" / "forge3d" / "venv-i23d" / "bin" / "python"
    return padrao if padrao.is_file() else Path(sys.executable)


def _vendor_triposr() -> Path:
    env = os.environ.get("FORGE3D_TRIPOSR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".cache" / "forge3d" / "vendor" / "TripoSR"


def probe_triposg() -> dict[str, Any]:
    """Sonda viabilidade de TripoSG (deps, VRAM livre, RAM de host e disco) sem falhar."""
    deps = ("torch", "diffusers", "huggingface_hub", "trimesh", "pymcubes", "diso")
    instalados: dict[str, bool] = {}
    for mod in deps:
        instalados[mod] = importlib.util.find_spec(mod) is not None

    # Sonda tambem na venv-i23d caso exista.
    py_i23d = _python_venv_i23d()
    instalados_i23d: dict[str, bool] = {}
    if py_i23d.is_file() and str(py_i23d) != sys.executable:
        codigo = (
            "import importlib.util, json; "
            f"mods = {list(deps)!r}; "
            "print(json.dumps({m: importlib.util.find_spec(m) is not None for m in mods}))"
        )
        try:
            proc = subprocess.run(
                [str(py_i23d), "-c", codigo], capture_output=True, text=True, timeout=20, check=False
            )
            if proc.returncode == 0 and proc.stdout.strip():
                instalados_i23d = json.loads(proc.stdout.strip().splitlines()[-1])
        except (OSError, ValueError, subprocess.SubprocessError):
            instalados_i23d = {}

    ram_total_mb: int | None = None
    ram_disp_mb: int | None = None
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for ln in meminfo.read_text(encoding="utf-8").splitlines():
            if ln.startswith("MemTotal:"):
                ram_total_mb = int(ln.split()[1]) // 1024
            elif ln.startswith("MemAvailable:"):
                ram_disp_mb = int(ln.split()[1]) // 1024

    vram_total_mb: int | None = None
    vram_livre_mb: int | None = None
    exe_smi = shutil.which("nvidia-smi")
    if exe_smi:
        try:
            proc = subprocess.run(
                [exe_smi, "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                t_s, f_s = proc.stdout.strip().splitlines()[0].split(",")
                vram_total_mb = int(t_s.strip())
                vram_livre_mb = int(f_s.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    uso_disco = shutil.disk_usage(Path.home())
    cache_hf = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    pesos_presentes = (cache_hf / "models--VAST-AI--TripoSG").is_dir()

    vram_ok = vram_total_mb is not None and vram_total_mb >= 7500
    ram_ok = ram_disp_mb is not None and ram_disp_mb >= 10000
    deps_ok = all(instalados_i23d.get(d, instalados.get(d, False)) for d in deps)
    return {
        "ok": True,
        "modo": "triposg_probe",
        "viavel_local": bool(vram_ok and ram_ok and deps_ok and pesos_presentes),
        "dependencias_atual": instalados,
        "dependencias_venv_i23d": instalados_i23d,
        "pesos_cache_hf": pesos_presentes,
        "vram_total_mb": vram_total_mb,
        "vram_livre_mb": vram_livre_mb,
        "ram_total_mb": ram_total_mb,
        "ram_disponivel_mb": ram_disp_mb,
        "disco_livre_gb": round(uso_disco.free / (1024**3), 2),
        "requisitos_estimados": {"vram_min_mb": 8000, "ram_min_mb": 12000, "disco_gb": 8.0},
    }


def _rodar_hf_trellis(imagem: Path, saida_dir: Path) -> dict[str, Any]:
    token_path = Path.home() / ".cache" / "huggingface" / "token"
    token = token_path.read_text(encoding="utf-8").strip() if token_path.is_file() else None
    try:
        from gradio_client import Client, handle_file  # type: ignore[import-not-found]
    except ImportError as exc:
        return {
            "ok": False,
            "modo": "hf_trellis",
            "erro": f"gradio_client ausente no ambiente: {exc}",
        }

    t0 = time.monotonic()
    ultimo_erro = ""
    for space in ("microsoft/TRELLIS", "microsoft/TRELLIS.2"):
        try:
            client = Client(space, hf_token=token) if token else Client(space)
            saida = client.predict(handle_file(str(imagem)))
            return {
                "ok": True,
                "modo": "hf_trellis",
                "space": space,
                "saida_bruta": str(saida),
                "phases_s": {"hf_trellis": round(time.monotonic() - t0, 3)},
                "total_s": round(time.monotonic() - t0, 3),
            }
        except Exception as exc:  # noqa: BLE001 - Space remoto pode oscilar ou exigir fila
            ultimo_erro = f"{space}: {type(exc).__name__}: {exc}"
    return {
        "ok": False,
        "modo": "hf_trellis",
        "erro": ultimo_erro,
        "phases_s": {"hf_trellis": round(time.monotonic() - t0, 3)},
    }


def _rodar_local_i23d(
    imagem: Path,
    saida_dir: Path,
    *,
    modo: str,
    resolucao_silhueta: int,
    sem_blender: bool,
) -> dict[str, Any]:
    saida_dir.mkdir(parents=True, exist_ok=True)
    phases_s: dict[str, float] = {}
    py = _python_venv_i23d()
    env = dict(os.environ)
    vendor = _vendor_triposr()
    if vendor.is_dir():
        env["PYTHONPATH"] = str(vendor) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )

    imagem_entrada = imagem
    pose_info: dict[str, Any] | None = None
    if modo == "hq" and (RAIZ / "tools" / "pose_guard.py").is_file():
        t_pg = time.monotonic()
        pg_json = saida_dir / "pose_guard.json"
        subprocess.run(
            [
                str(py),
                str(RAIZ / "tools" / "pose_guard.py"),
                "--imagem",
                str(imagem),
                "--resultado",
                str(pg_json),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )
        phases_s["pose_guard"] = round(time.monotonic() - t_pg, 3)
        if pg_json.is_file():
            pose_info = json.loads(pg_json.read_text(encoding="utf-8"))

    t_i23d = time.monotonic()
    i23d_dir = saida_dir / "bruto"
    i23d_dir.mkdir(parents=True, exist_ok=True)
    i23d_json = i23d_dir / "i23d_resultado.json"
    rembg_modelo = "u2net" if modo == "baseline" else "birefnet-general"
    cmd_i23d = [
        str(py),
        str(RAIZ / "tools" / "i23d_infer.py"),
        "--imagem",
        str(imagem_entrada),
        "--saida-dir",
        str(i23d_dir),
        "--resultado",
        str(i23d_json),
        "--remover-fundo",
        "--rembg-modelo",
        rembg_modelo,
    ]
    proc = subprocess.run(cmd_i23d, capture_output=True, text=True, env=env, timeout=600, check=False)
    phases_s["i23d"] = round(time.monotonic() - t_i23d, 3)

    if proc.returncode != 0 or not i23d_json.is_file():
        return {
            "ok": False,
            "modo": modo,
            "phases_s": phases_s,
            "erro": (proc.stderr or proc.stdout or f"exit {proc.returncode}")[-1500:],
        }

    i23d_res = json.loads(i23d_json.read_text(encoding="utf-8"))
    if not i23d_res.get("ok"):
        return {"ok": False, "modo": modo, "phases_s": phases_s, "erro": i23d_res.get("erro")}

    input_png = i23d_dir / "input.png"
    delight_info: dict[str, Any] | None = None
    origem_textura = "input.png"
    metallic_hint = ""
    roughness_hint = ""
    if modo == "hq" and input_png.is_file() and (RAIZ / "tools" / "delight.py").is_file():
        t_dl = time.monotonic()
        dl_json = i23d_dir / "delight_resultado.json"
        subprocess.run(
            [
                str(py),
                str(RAIZ / "tools" / "delight.py"),
                "--imagem",
                str(input_png),
                "--saida-albedo",
                str(i23d_dir / "input_delit.png"),
                "--saida-metallic",
                str(i23d_dir / "metallic_hint.png"),
                "--saida-roughness",
                str(i23d_dir / "roughness_hint.png"),
                "--resultado",
                str(dl_json),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )
        phases_s["delight"] = round(time.monotonic() - t_dl, 3)
        if dl_json.is_file():
            delight_info = json.loads(dl_json.read_text(encoding="utf-8"))
            if (i23d_dir / "input_delit.png").is_file():
                origem_textura = "input_delit.png"
            if (i23d_dir / "metallic_hint.png").is_file():
                metallic_hint = "metallic_hint.png"
            if (i23d_dir / "roughness_hint.png").is_file():
                roughness_hint = "roughness_hint.png"

    glb_final = i23d_dir / "modelo.glb"
    blender_exe = None if sem_blender else shutil.which("blender")
    if blender_exe and (RAIZ / "blender" / "postprocess.py").is_file():
        t_bl = time.monotonic()
        modelo_meta: dict[str, Any] = {
            "schema": "forge3d/bruto-arquivo@1",
            "arquivo": "modelo.glb",
            "canonicalizar": True,
            "textura_px": 1024,
            "pivos": {},
        }
        if origem_textura and (i23d_dir / origem_textura).is_file():
            modelo_meta["origem_textura"] = origem_textura
        if metallic_hint:
            modelo_meta["metallic_hint"] = metallic_hint
        if roughness_hint:
            modelo_meta["roughness_hint"] = roughness_hint
        (i23d_dir / "modelo.json").write_text(
            json.dumps(modelo_meta, sort_keys=True, indent=1) + "\n", encoding="utf-8"
        )
        post_dir = saida_dir / "final"
        post_dir.mkdir(parents=True, exist_ok=True)
        job_json = saida_dir / "job.json"
        post_res = post_dir / "resultado.json"
        job_json.write_text(
            json.dumps(
                {
                    "bruto_dir": str(i23d_dir),
                    "bruto_arquivo": "modelo.json",
                    "saida_dir": str(post_dir),
                    "saida_resultado": str(post_res),
                    "perfil": {"perfil": "godot4", "unidades": {"escala_saida": 1.0}, "colisao": {"max_partes": 4}},
                    "item": {
                        "id": "bench.asset.01",
                        "tipo": "prop_estatico",
                        "altura_metros": 1.0,
                        "pivot": "base",
                        "limite_triangulos": 12000 if modo == "hq" else 6000,
                        "colisao": "none",
                        "lod": [100],
                    },
                    "nome_base": "bench.asset.01",
                    "nome_arquivo": "bench.asset.01.glb",
                    "clipes": [],
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        bp = subprocess.run(
            [
                blender_exe,
                "--background",
                "--factory-startup",
                "--python",
                str(RAIZ / "blender" / "postprocess.py"),
                "--",
                str(job_json),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        phases_s["blender_postprocess"] = round(time.monotonic() - t_bl, 3)
        candidato = post_dir / "bench.asset.01.glb"
        if bp.returncode == 0 and candidato.is_file():
            glb_final = candidato

    metricas_glb = medir_glb(glb_final, resolucao=resolucao_silhueta)
    return {
        "ok": True,
        "modo": modo,
        "phases_s": phases_s,
        "total_s": round(sum(phases_s.values()), 3),
        "vram_torch_max_allocated_mb": i23d_res.get("vram_pico_mb"),
        "vram_torch_reserved_mb": i23d_res.get("vram_reservada_mb"),
        "rembg_modelo": i23d_res.get("rembg_modelo"),
        "rembg_fallback": i23d_res.get("rembg_fallback"),
        "pose_guard": pose_info,
        "delight": delight_info,
        **metricas_glb,
    }


def _args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark standalone image-to-3D (Forge3D)")
    p.add_argument("--imagem", default="", help="imagem de entrada PNG/JPG")
    p.add_argument("--saida-dir", default="/tmp/forge3d_bench_i23d")
    p.add_argument(
        "--modo",
        default="baseline",
        choices=["baseline", "hq", "hf_trellis", "triposg_probe"],
    )
    p.add_argument("--resolucao-silhueta", type=int, default=256)
    p.add_argument("--sem-blender", action="store_true")
    p.add_argument("--json", action="store_true", help="imprime resultado JSON no stdout")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    saida_dir = Path(args.saida_dir).expanduser().resolve()

    if args.modo == "triposg_probe":
        relatorio = probe_triposg()
    else:
        if not args.imagem:
            raise SystemExit(f"erro: --imagem e obrigatorio no modo {args.modo}")
        imagem = Path(args.imagem).expanduser().resolve()
        if not imagem.is_file():
            raise SystemExit(f"erro: imagem nao encontrada: {imagem}")

        t0 = time.monotonic()
        with VramMonitor() as mon:
            if args.modo == "hf_trellis":
                relatorio = _rodar_hf_trellis(imagem, saida_dir)
            else:
                relatorio = _rodar_local_i23d(
                    imagem,
                    saida_dir,
                    modo=args.modo,
                    resolucao_silhueta=args.resolucao_silhueta,
                    sem_blender=args.sem_blender,
                )
        relatorio.update(mon.resumo())
        relatorio["wall_total_s"] = round(time.monotonic() - t0, 3)

    rss_children_mb = round(
        resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0, 2
    )
    rss_self_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 2)
    relatorio["host_peak_rss_children_mb"] = rss_children_mb
    relatorio["host_peak_rss_self_mb"] = rss_self_mb

    if args.modo != "triposg_probe":
        saida_dir.mkdir(parents=True, exist_ok=True)
        (saida_dir / "bench_resultado.json").write_text(
            json.dumps(relatorio, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(relatorio, sort_keys=True, indent=1, ensure_ascii=False))
    else:
        print(
            f"modo={relatorio.get('modo')} ok={relatorio.get('ok')} "
            f"total_s={relatorio.get('total_s', relatorio.get('wall_total_s'))} "
            f"tris={relatorio.get('triangulos')} g1={relatorio.get('g1_nao_manifold')} "
            f"rss_mb={rss_children_mb}"
        )
    return 0 if relatorio.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
