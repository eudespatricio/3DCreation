"""Validacao de partes segmentadas e reexecucao de G11 (orcamento de cena) no verify."""

from __future__ import annotations

import struct
from pathlib import Path

from .errors import ForgeError


def _validar_partes_manifesto(
    man: dict,
    destino: Path,
    perfil: dict,
    alpha_cards: bool,
    caminho_name: str,
    erros: list[dict],
) -> tuple[int, int]:
    """Valida referencias ``partes[]`` e abre/checa topologia de cada GLB ``papel == 'parte'``."""
    from . import qc
    from .publish import _caminho_seguro

    arqs_parte = [f for f in man["files"] if f.get("papel") == "parte"]
    nomes_parte_files = {f["caminho"] for f in arqs_parte}

    for parte in man.get("partes") or []:
        if not isinstance(parte, dict):
            continue
        refs: list[str] = []
        if parte.get("arquivo"):
            refs.append(str(parte["arquivo"]))
        for extra in parte.get("arquivos") or []:
            refs.append(str(extra))
        for ref in refs:
            if ref not in nomes_parte_files:
                erros.append(
                    {
                        "manifesto": caminho_name,
                        "erro": f"parte '{parte.get('nome')}' referencia '{ref}' ausente em files (papel=parte)",
                    }
                )

    v = perfil["validacao"]
    prim_partes = 0
    tris_partes = 0
    for f in arqs_parte:
        try:
            alvo = _caminho_seguro(destino, f["caminho"])
        except ForgeError as exc:
            erros.append({"manifesto": caminho_name, "erro": str(exc)})
            continue
        if not alvo.is_file():
            erros.append({"manifesto": caminho_name, "erro": f"parte ausente: {f['caminho']}"})
            continue
        try:
            gltf_p, bin_p = qc.ler_glb_bin(alvo)
            if not (gltf_p.get("meshes") or []):
                erros.append({"manifesto": caminho_name, "erro": f"parte sem malha: {f['caminho']}"})
                continue
            info_p = qc.analisar(gltf_p, bin_p)
            if info_p.get("erros"):
                erros.append(
                    {
                        "manifesto": caminho_name,
                        "erro": f"parte '{f['caminho']}' ilegivel: {'; '.join(info_p['erros'])}",
                    }
                )
                continue
            tris_p = int(info_p.get("triangulos") or 0)
            if tris_p <= 0:
                erros.append({"manifesto": caminho_name, "erro": f"parte sem triangulos: {f['caminho']}"})
                continue
            topo_p = qc.topologia(gltf_p, bin_p)
        except (ForgeError, OSError, ValueError, struct.error, IndexError, KeyError, TypeError, AttributeError) as exc:
            erros.append({"manifesto": caminho_name, "erro": f"parte '{f['caminho']}' ilegivel: {exc}"})
            continue

        prim_p = sum(
            len(m.get("primitives") or [])
            for m in (gltf_p.get("meshes") or [])
            if isinstance(m, dict)
        )
        prim_partes += max(1, prim_p)
        tris_partes += tris_p
        nm_eff = int(topo_p.get("arestas_t", 0)) if alpha_cards else int(topo_p.get("nao_manifold", 0))
        if (
            nm_eff > int(v["nao_manifold_max"])
            or int(topo_p.get("degeneradas", 0)) > int(v["faces_degeneradas_max"])
            or int(topo_p.get("invertidas", 0)) != 0
        ):
            erros.append(
                {
                    "manifesto": caminho_name,
                    "erro": f"parte '{f['caminho']}' reprovou topologia",
                    "medido": topo_p,
                }
            )
    return prim_partes, tris_partes


def _medir_manifesto_g11(
    man: dict,
    destino: Path,
    revalidado: dict,
    item: dict,
    prim_partes: int = 0,
    tris_partes: int = 0,
) -> dict:
    """Extrai metricas por item a partir do manifesto e QC revalidado para G11."""
    from . import qc

    iid = str(man["asset_id"])
    medidas = revalidado.get("medidas") or {}
    texturas: list[dict] = []

    for arq in man.get("files") or []:
        papel = str(arq.get("papel") or "")
        if papel not in qc.PAPEIS_TEXTURA:
            continue
        caminho = destino / str(arq.get("caminho") or "")
        px = 1024
        if caminho.is_file():
            try:
                dims = qc._validar_bytes_imagem(caminho.read_bytes())
                if dims is not None:
                    px = max(dims)
            except OSError:
                px = 1024
        canais = 1 if papel in ("roughness", "metallic") else 4
        texturas.append({"id": f"{iid}:{arq['caminho']}", "px": px, "canais": canais})

    g4 = next((g for g in revalidado.get("gates") or [] if g.get("id") == "G4"), None)
    for emb in ((g4 or {}).get("medido") or {}).get("embutidas") or []:
        px_list = emb.get("px") if isinstance(emb, dict) else None
        if isinstance(px_list, list) and px_list:
            texturas.append(
                {
                    "id": f"{iid}:emb:{emb.get('indice', len(texturas))}",
                    "px": max(int(x) for x in px_list),
                    "canais": 4,
                }
            )

    partes_res = man.get("partes") or []
    prim_main = int(medidas.get("primitivas") or 1)
    if prim_partes == 0 and partes_res:
        prim_partes = len(partes_res)
    primitivas = max(1, prim_main, prim_partes)

    tris = int(medidas.get("triangulos") or (man.get("geometry") or {}).get("triangulos") or 0)
    if tris_partes > 0:
        tris = max(tris, tris_partes)
    elif partes_res:
        tris = max(
            tris,
            sum(int(p.get("triangulos") or 0) for p in partes_res if isinstance(p, dict)),
        )

    eh_pbr = (
        item.get("material") == "pbr"
        or bool(man.get("pbr_zonas"))
        or bool(man.get("detalhe_alto"))
    )
    skinned = (
        int(medidas.get("ossos") or 0) > 0
        or bool((man.get("anexo") or {}).get("skinned"))
        or bool((man.get("rig") or {}).get("modo"))
        or bool(man.get("rig"))
    )
    return {
        "id": iid,
        "tris": tris,
        "primitivas": primitivas,
        "quantidade_cena": int(man.get("quantidade_cena", 1)),
        "mesh_key": iid,
        "material_key": f"pbr:{iid}" if eh_pbr else "palette_padrao",
        "skinned": skinned,
        "texturas": texturas,
    }


def _verificar_g11_destino(
    avaliados: list[tuple[dict, dict, dict]],
    destino_nome: str,
    erros: list[dict],
) -> dict | None:
    """Reexecuta G11 no agregado dos manifestos avaliados no destino."""
    from . import profiles, qc

    if not avaliados:
        return None
    limites = [profiles.orcamento_cena_perfil(perfil, man) for man, perfil, _ in avaliados]
    limite_cena = {
        "triangulos_max": min(int(lim["triangulos_cena_max"]) for lim in limites),
        "draw_calls_max": min(int(lim["draw_calls_cena_max"]) for lim in limites),
        "vram_mb_max": min(float(lim["vram_texturas_mb_max"]) for lim in limites),
        "capacidade_referencia_tris": max(int(lim["capacidade_referencia_tris"]) for lim in limites),
        "fator_alvo": min(float(lim["fator_alvo"]) for lim in limites),
    }
    rel_g11 = qc.verificar_g11_orcamento_cena([m for _, _, m in avaliados], limite_cena=limite_cena)
    if rel_g11["status"] == "falhou":
        manifesto_ref = (
            f"{avaliados[0][0]['asset_id']}.manifest.json"
            if len(avaliados) == 1
            else destino_nome
        )
        erros.append(
            {
                "manifesto": manifesto_ref,
                "erro": "Gate G11 reprovou orcamento_cena",
                "codigo": rel_g11.get("codigo") or "FORGE-E-QC-SCENE",
                "gates": [rel_g11],
            }
        )
    return rel_g11
