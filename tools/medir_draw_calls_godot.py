#!/usr/bin/env python3
"""Medidor reprodutivel de draw calls, primitivas (tris) e VRAM no Godot 4.x vs Gate G11.

Por que nao usa ``--headless``:
  No Godot 4.x, ``--headless`` ativa o ``dummy`` RenderingServer, que descarta
  comandos graficos e reporta ``0`` draw calls e ``0`` bytes de VRAM. Este
  utilitario exige um driver grafico real (``vulkan`` Forward+ ou ``opengl3``
  Compatibility) sobre X11/Wayland/WSLg ou ``xvfb-run``, nunca inventando numeros.

Exemplos:
  .venv/bin/python tools/medir_draw_calls_godot.py \\
    examples/lote_13_scene_budget_aa.yaml \\
    ~/.local/state/forge3d/saida/v09_aa_godot

  .venv/bin/python tools/medir_draw_calls_godot.py \\
    examples/lote_13_scene_budget_aa.yaml --include-shadows --json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

from forge3d import profiles, qc, spec  # noqa: E402


def localizar_godot(explicito: str | None = None) -> Path | None:
    """Localiza o binario do Godot 4.x seguindo FORGE3D_GODOT, tools locais e PATH."""
    candidatos: list[Path] = []
    if explicito:
        candidatos.append(Path(explicito).expanduser())
    env_bin = os.environ.get("FORGE3D_GODOT")
    if env_bin:
        candidatos.append(Path(env_bin).expanduser())

    home = Path.home()
    candidatos.extend(
        [
            home / "tools" / "godot" / "Godot_v4.7.2-stable_linux.x86_64",
            home / ".local" / "bin" / "godot",
            home / ".gemini" / "antigravity" / "bin" / "godot",
            home / "tools" / "godot" / "Godot_v4.3-stable_linux.x86_64",
        ]
    )
    for nome_cmd in ("godot", "godot4"):
        achado = shutil.which(nome_cmd)
        if achado:
            candidatos.append(Path(achado))

    for c in candidatos:
        if c.is_file() and os.access(c, os.X_OK):
            return c.resolve()
    return None


def detectar_display() -> tuple[list[str], str] | None:
    """Detecta servidor grafico ativo (X11/Wayland/WSLg) ou fallback ``xvfb-run``."""
    disp = os.environ.get("DISPLAY", "").strip()
    wayland = os.environ.get("WAYLAND_DISPLAY", "").strip()
    if disp or wayland:
        etiqueta = f"DISPLAY={disp}" if disp else f"WAYLAND_DISPLAY={wayland}"
        return [], etiqueta

    xvfb = shutil.which("xvfb-run")
    if xvfb:
        return [xvfb, "-a", "-s", "-screen 0 640x480x24"], "xvfb-run"

    return None


def _reconstruir_item_g11_de_manifesto(
    pasta: Path,
    manifesto: dict[str, Any],
    item_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconstroi o dicionario de entrada de ``qc.verificar_g11_orcamento_cena`` a partir do publicado."""
    iid = str(manifesto.get("asset_id") or (item_spec or {}).get("id") or "?")
    glb_path = pasta / f"{iid}.glb"
    gltf, binario = qc.ler_glb_bin(glb_path)
    info = qc.analisar(gltf, binario)

    texturas: list[dict[str, Any]] = []
    for arq in manifesto.get("files") or []:
        papel = str(arq.get("papel") or "")
        if papel not in qc.PAPEIS_TEXTURA:
            continue
        p_tex = pasta / str(arq.get("caminho") or "")
        px = 1024
        if p_tex.is_file():
            dims = qc._validar_bytes_imagem(p_tex.read_bytes())
            if dims:
                px = max(dims)
        canais = 1 if papel in ("roughness", "metallic") else 4
        texturas.append({"id": f"{iid}:{arq['caminho']}", "px": px, "canais": canais})

    gates = (manifesto.get("qc") or {}).get("gates") or []
    g4 = next((g for g in gates if isinstance(g, dict) and g.get("id") == "G4"), None)
    embutidas = ((g4 or {}).get("medido") or {}).get("embutidas")
    if embutidas is None:
        embutidas = qc._imagens_embutidas(gltf, binario, 8192)
    for idx, emb in enumerate(embutidas or []):
        px_list = emb.get("px")
        if isinstance(px_list, list) and px_list:
            texturas.append(
                {"id": f"{iid}:emb:{idx}", "px": max(int(x) for x in px_list), "canais": 4}
            )

    qtd = int(
        (item_spec or {}).get(
            "quantidade_cena",
            manifesto.get("quantidade_cena", 1),
        )
    )
    skinned = bool(
        (item_spec or {}).get("auto_rig")
        or (item_spec or {}).get("skinned")
        or manifesto.get("rig") is not None
        or ((manifesto.get("anexo") or {}).get("skinned"))
        or int(info.get("ossos", 0)) > 0
    )

    if item_spec is not None:
        eh_pbr = (
            item_spec.get("material") == "pbr"
            or bool(item_spec.get("pbr_zonas"))
            or bool(item_spec.get("material_procedural"))
        )
    else:
        eh_pbr = bool(
            manifesto.get("pbr_zonas")
            or int(info.get("com_textura", 0)) > 0
            or any((a.get("papel") in qc.PAPEIS_TEXTURA) for a in (manifesto.get("files") or []))
        )

    return {
        "id": iid,
        "glb": str(glb_path.resolve()),
        "tris": int(info["triangulos"]),
        "primitivas": int(info["primitivas"]),
        "materiais": int(info["materiais"]),
        "quantidade_cena": qtd,
        "mesh_key": str((item_spec or {}).get("mesh_key") or iid),
        "material_key": f"pbr:{iid}" if eh_pbr else "palette_padrao",
        "skinned": skinned,
        "texturas": texturas,
    }


def carregar_alvo(caminho_str: str) -> dict[str, Any]:
    """Carrega um lote YAML/JSON (resolvendo seu destino publicado) ou uma pasta publicada direta."""
    caminho = Path(caminho_str).expanduser().resolve()
    if not caminho.exists():
        raise FileNotFoundError(f"alvo nao encontrado: {caminho}")

    if caminho.is_file():
        doc_bruto = spec.carregar_arquivo(caminho)
        spec_doc, perfil, _ = spec.preparar(doc_bruto)
        destino = Path(str(spec_doc["destino_exportacao"])).expanduser().resolve()
        if not destino.is_dir():
            raise FileNotFoundError(
                f"destino publicado ausente para {caminho.name}: {destino} (rode forge3d run primeiro)"
            )
        limite_cena = profiles.orcamento_cena_perfil(perfil, spec_doc)
        itens_g11: list[dict[str, Any]] = []
        for it in spec_doc["lote"]:
            iid = str(it["id"])
            man_path = destino / f"{iid}.manifest.json"
            if not man_path.is_file():
                raise FileNotFoundError(f"manifesto ausente em {destino}: {man_path.name}")
            manifesto = json.loads(man_path.read_text(encoding="utf-8"))
            itens_g11.append(_reconstruir_item_g11_de_manifesto(destino, manifesto, it))
        nome = caminho.stem
        perfil_nome = str(spec_doc.get("perfil") or "")
    else:
        destino = caminho
        manifestos_paths = sorted(destino.glob("*.manifest.json"))
        if not manifestos_paths:
            raise FileNotFoundError(f"nenhum *.manifest.json encontrado em {destino}")
        primeiro_man = json.loads(manifestos_paths[0].read_text(encoding="utf-8"))
        perfil_nome = str(primeiro_man.get("perfil") or "godot4-aa")
        perfil = profiles.carregar(perfil_nome)
        orc_override = primeiro_man.get("orcamento_cena")
        spec_stub = {"orcamento_cena": orc_override} if isinstance(orc_override, dict) else {}
        limite_cena = profiles.orcamento_cena_perfil(perfil, spec_stub)
        itens_g11 = []
        for mp in manifestos_paths:
            man = json.loads(mp.read_text(encoding="utf-8"))
            itens_g11.append(_reconstruir_item_g11_de_manifesto(destino, man, None))
        nome = destino.name

    rel_g11 = qc.verificar_g11_orcamento_cena(itens_g11, limite_cena=limite_cena)
    itens_legado = [
        {k: v for k, v in it.items() if k not in ("primitivas", "materiais")}
        for it in itens_g11
    ]
    rel_g11_legado = qc.verificar_g11_orcamento_cena(itens_legado, limite_cena=limite_cena)
    return {
        "nome": nome,
        "origem": str(caminho),
        "destino": str(destino),
        "perfil": perfil_nome,
        "itens": itens_g11,
        "g11": rel_g11,
        "g11_legado": rel_g11_legado,
    }


def executar_godot_bench(
    *,
    godot_bin: Path,
    prefixo_display: list[str],
    itens: list[dict[str, Any]],
    driver: str,
    mode: str,
    shadows: bool,
    timeout_s: int = 90,
) -> dict[str, Any]:
    """Invoca ``tools/godot_draw_calls_bench.gd`` por canal de arquivo JSON (I9)."""
    projeto_godot = RAIZ / "tools" / "godot_project"
    script_gd = RAIZ / "tools" / "godot_draw_calls_bench.gd"

    with tempfile.TemporaryDirectory(prefix="forge3d_dcbench_") as tmp:
        tmp_dir = Path(tmp)
        in_json = tmp_dir / "in.json"
        out_json = tmp_dir / "out.json"
        payload_in = {
            "mode": mode,
            "shadows": shadows,
            "frames_baseline": 4,
            "frames_measure": 6,
            "items": [
                {
                    "id": it["id"],
                    "glb": it["glb"],
                    "qtd": it["quantidade_cena"],
                }
                for it in itens
                if int(it.get("quantidade_cena", 0)) > 0
            ],
        }
        in_json.write_text(json.dumps(payload_in, indent=2), encoding="utf-8")

        cmd = [
            *prefixo_display,
            str(godot_bin),
            "--path",
            str(projeto_godot),
            "--rendering-driver",
            driver,
            "--windowed",
            "--resolution",
            "320x240",
            "--script",
            str(script_gd),
            "--",
            "--input",
            str(in_json),
            "--output",
            str(out_json),
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(RAIZ),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if not out_json.is_file():
            raise RuntimeError(
                f"Godot ({driver}/{mode}) nao gerou JSON de saida (rc={proc.returncode}):\n"
                f"stderr={proc.stderr[-800:]}\nstdout={proc.stdout[-800:]}"
            )
        dados = json.loads(out_json.read_text(encoding="utf-8"))
        if not dados.get("ok"):
            raise RuntimeError(f"Godot bench falhou ({driver}/{mode}): {dados.get('erro')}")
        dados["exit_code"] = proc.returncode
        return dados


def _fmt_dc(runs: dict[str, Any], chave: str, chave_sh: str, incluir_sombras: bool) -> str:
    base = runs.get(chave)
    if not base:
        return "n/a"
    dc = base["measured"]["perf_draw_calls"]
    if incluir_sombras and chave_sh in runs:
        dc_sh = runs[chave_sh]["measured"]["perf_draw_calls"]
        return f"{dc} (c/ sombra: {dc_sh})"
    return str(dc)


def formatar_tabela_markdown(resultados: list[dict[str, Any]], incluir_sombras: bool) -> str:
    """Formata tabela comparativa G11 vs Godot 4.x (Forward+ Vulkan e Compatibility OpenGL3)."""
    linhas = [
        "| Alvo (`perfil`) | Instâncias | Primitivas/item (soma) | Tris G11 | Tris Godot (vis) | G11 legado (1/item) | G11 por primitiva (`qc.py`) | Godot `vulkan` (Forward+) Naive | Godot `vulkan` (Forward+) MultiMesh | Godot `opengl3` (Compat) Naive | Godot `opengl3` (Compat) MultiMesh | VRAM G11 (BC7/ASTC) | VRAM Godot Δ tex (RGBA8 runtime) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in resultados:
        g11_med = r["g11"]["medido"]
        g11_leg = r["g11_legado"]["medido"]
        inst_total = sum(int(i["quantidade_cena"]) for i in r["itens"])
        prims_soma = sum(int(i["primitivas"]) for i in r["itens"])
        runs = r["godot_runs"]

        ref_run = (
            runs.get("vulkan_naive_noshadow")
            or runs.get("opengl3_naive_noshadow")
            or next(iter(runs.values()))
        )
        vis_tris = ref_run["measured"]["vp_visible_primitives"]
        vram_delta = ref_run["delta"]["texture_mem_mb"]
        vram_total = ref_run["delta"]["total_texture_mem_mb"]

        linhas.append(
            f"| `{r['nome']}` (`{r['perfil']}`) | {inst_total} | {prims_soma} | "
            f"{g11_med['triangulos_cena']} | {vis_tris} | "
            f"{g11_leg['draw_calls_estimados']} | **{g11_med['draw_calls_estimados']}** | "
            f"{_fmt_dc(runs, 'vulkan_naive_noshadow', 'vulkan_naive_shadow', incluir_sombras)} | "
            f"{_fmt_dc(runs, 'vulkan_multimesh_noshadow', 'vulkan_multimesh_shadow', incluir_sombras)} | "
            f"{_fmt_dc(runs, 'opengl3_naive_noshadow', 'opengl3_naive_shadow', incluir_sombras)} | "
            f"{_fmt_dc(runs, 'opengl3_multimesh_noshadow', 'opengl3_multimesh_shadow', incluir_sombras)} | "
            f"{g11_med['vram_texturas_mb']:.2f} MB | "
            f"{vram_delta:.2f} MB (tot {vram_total:.2f} MB) |"
        )
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mede draw calls, primitivas e VRAM reais no Godot 4.x e compara com o Gate G11."
    )
    parser.add_argument(
        "alvos",
        nargs="+",
        help="Arquivos de lote YAML/JSON ou pastas publicadas com *.manifest.json.",
    )
    parser.add_argument(
        "--godot",
        default=None,
        help="Caminho explicito para o binario do Godot 4.x.",
    )
    parser.add_argument(
        "--drivers",
        default="vulkan,opengl3",
        help="Drivers reais do Godot separados por virgula (default: vulkan,opengl3).",
    )
    parser.add_argument(
        "--include-shadows",
        action="store_true",
        help="Mede tambem passe com DirectionalLight3D shadow_enabled=true (4 cascatas).",
    )
    parser.add_argument(
        "--saida-json",
        default=None,
        help="Grava relatorio completo em arquivo JSON.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime JSON completo em stdout em vez da tabela Markdown.",
    )
    args = parser.parse_args(argv)

    godot_bin = localizar_godot(args.godot)
    if godot_bin is None:
        print(
            "ERRO: binario do Godot 4.x nao encontrado (defina FORGE3D_GODOT ou instale no PATH).",
            file=sys.stderr,
        )
        return 2

    disp_info = detectar_display()
    if disp_info is None:
        print(
            "ERRO: nenhum servidor grafico (DISPLAY/WAYLAND_DISPLAY) nem xvfb-run disponivel; "
            "--headless usa driver dummy (0 draw calls) e nao pode ser usado para medir.",
            file=sys.stderr,
        )
        return 2
    prefixo_display, etiqueta_display = disp_info

    drivers = [d.strip() for d in args.drivers.split(",") if d.strip()]
    modos = ["naive", "multimesh"]
    shadow_flags = [False, True] if args.include_shadows else [False]

    resultados: list[dict[str, Any]] = []
    for alvo_str in args.alvos:
        alvo = carregar_alvo(alvo_str)
        runs: dict[str, Any] = {}
        for drv in drivers:
            for modo in modos:
                for sh in shadow_flags:
                    chave = f"{drv}_{modo}_{'shadow' if sh else 'noshadow'}"
                    runs[chave] = executar_godot_bench(
                        godot_bin=godot_bin,
                        prefixo_display=prefixo_display,
                        itens=alvo["itens"],
                        driver=drv,
                        mode=modo,
                        shadows=sh,
                    )
        alvo["godot_runs"] = runs
        resultados.append(alvo)

    primeiro_run = next(iter(resultados[0]["godot_runs"].values()))
    relatorio_final = {
        "ok": True,
        "ambiente": {
            "godot_bin": str(godot_bin),
            "godot_version": primeiro_run["engine"]["godot_version"],
            "video_adapter": primeiro_run["engine"]["video_adapter"],
            "display": etiqueta_display,
            "nota_roblox": "[estimado] Roblox Studio headless indisponivel no Linux/WSL; sem medicao de profiler nativo Roblox.",
        },
        "resultados": resultados,
    }

    if args.saida_json:
        p_out = Path(args.saida_json).expanduser().resolve()
        p_out.parent.mkdir(parents=True, exist_ok=True)
        p_out.write_text(json.dumps(relatorio_final, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(relatorio_final, indent=2, ensure_ascii=False))
    else:
        print(
            f"# Medição Real Godot {relatorio_final['ambiente']['godot_version']} "
            f"({relatorio_final['ambiente']['video_adapter']}, `{etiqueta_display}`)\n"
        )
        print(formatar_tabela_markdown(resultados, args.include_shadows))
        print(f"\n- **Roblox runtime:** {relatorio_final['ambiente']['nota_roblox']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
