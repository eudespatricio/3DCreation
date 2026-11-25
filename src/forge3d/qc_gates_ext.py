"""Avaliadores individuais dos portoes G6-G10 e G15 para manter ``qc.py`` e ``qc_fidelidade.py`` enxutos."""

from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Any

from .errors import ForgeError, erro_qc
from .profiles import esqueleto_para_item
from .qc_fidelidade import (
    LIMIAR_ASPECT_G15,
    LIMIAR_IOU_G15,
    _EXTS_IMAGEM,
    _carregar_mascara_arquivo,
    _comparar_mascaras,
    avaliar_fidelidade_concept_3d,
    rasterizar_silhueta_frontal_glb,
)
from .qc_geom import convexidade, topologia
from .qc_glb import analisar, ler_glb_bin, malha
from .qc_glb_mat import _eh_int
from .qc_midia import _silhueta_iou_lod, _skin_status, _uv_status, animacoes
from .qc_volumetria import avaliar_volumetria_glb

logger = logging.getLogger(__name__)


def _avaliar_g6(
    gltf: dict, binario: bytes, item: dict, perfil: dict, info: dict, medidas: dict, anexo_item: dict
) -> dict:
    eh_skinned = bool(item.get("auto_rig")) or bool(anexo_item.get("skinned"))
    if not eh_skinned:
        return {"id": "G6", "status": "ok", "medido": {"ossos": info["ossos"], "rig": False}}
    esqueleto = medidas.get("esqueleto") or esqueleto_para_item(perfil, item)
    mapa = set(perfil["rig"].get("mapas", {}).get(esqueleto, []))
    presentes = set(info["nomes_ossos"])
    fora = sorted(presentes - mapa) if mapa else []
    faltando = sorted(mapa - presentes) if (mapa and item.get("auto_rig")) else []
    skin_info = _skin_status(gltf, binario)
    rig_ok = (
        info["ossos"] > 0
        and info["ossos"] <= int(perfil["rig"]["max_ossos"])
        and not fora
        and not faltando
        and bool(skin_info["ok"])
    )
    return {
        "id": "G6",
        "status": "ok" if rig_ok else "falhou",
        "medido": {
            "ossos": info["ossos"],
            "fora_do_mapa": fora,
            "faltando_no_mapa": faltando,
            "esqueleto": esqueleto,
            "skin": skin_info,
        },
        "limite": {"max_ossos": perfil["rig"]["max_ossos"]},
        "codigo": None if rig_ok else "FORGE-E-QC",
    }


def _avaliar_g7(
    gltf: dict,
    item: dict,
    perfil: dict,
    info: dict,
    medidas: dict,
    pasta: Path,
    arquivos: list[dict],
    escala: float,
) -> dict:
    if item.get("colisao", "none") == "none":
        return {"id": "G7", "status": "ok", "medido": {"colisao": "none"}}
    arquivo_col = next((a for a in arquivos if a["papel"] == "colisor"), None)
    partes_decl = int(medidas.get("partes_colisao", 0))
    nomes: list[str] = []
    convexo: dict[str, Any] = {"medida": False, "partes": 0, "concavas": 0, "degeneradas": 0, "convexo": False}
    dentro_da_aabb = True
    cobertura_aabb = 1.0
    if arquivo_col is not None and (pasta / arquivo_col["caminho"]).is_file():
        try:
            gltf_col, binario_col = ler_glb_bin(pasta / arquivo_col["caminho"])
            if (
                not gltf_col.get("meshes")
                or ("nodes" in gltf_col and not isinstance(gltf_col["nodes"], list))
                or ("meshes" in gltf_col and not isinstance(gltf_col["meshes"], list))
            ):
                raise erro_qc("colisor sem malhas ou nodes invalidos")
            info_col = analisar(gltf_col, binario_col)
            erros_col = list(info_col.get("erros") or ())
            if erros_col:
                raise erro_qc(f"colisor malformado: {', '.join(erros_col)}")
            nomes = [
                str(n.get("name") or "")
                for n in (gltf_col.get("nodes") or [])
                if isinstance(n, dict) and "mesh" in n
            ]
            convexo = convexidade(gltf_col, binario_col)
            if gltf.get("meshes"):
                margem_aabb = max(0.05 * escala, 0.15 * max(info["bbox_m"] or [0.0]))
                dentro_da_aabb = all(
                    info_col["min"][d] >= info["min"][d] - margem_aabb
                    and info_col["max"][d] <= info["max"][d] + margem_aabb
                    for d in range(3)
                )
                vol_malha = info["bbox_m"][0] * info["bbox_m"][1] * info["bbox_m"][2]
                vol_col = info_col["bbox_m"][0] * info_col["bbox_m"][1] * info_col["bbox_m"][2]
                if vol_malha > 1e-9:
                    cobertura_aabb = round(vol_col / vol_malha, 6)
        except (ForgeError, OSError, OverflowError, struct.error, ValueError, IndexError, TypeError) as exc:
            logger.debug("falha ao ler colisor '%s' em G7: %s", arquivo_col["caminho"], exc)
            nomes = []
            convexo = {**convexo, "erro": str(exc)}
    partes = int(convexo["partes"]) if convexo.get("medida") and int(convexo["partes"]) > 0 else partes_decl
    col_ok = (
        arquivo_col is not None
        and partes >= 1
        and partes <= int(perfil["colisao"]["max_partes"])
        and (pasta / arquivo_col["caminho"]).is_file()
    )
    prefixo = perfil["colisao"].get("prefixo")
    prefixo_ok = bool(nomes) and all(n.startswith(prefixo) for n in nomes) if prefixo else True
    exigir_dentro_aabb = bool(perfil["colisao"].get("dentro_da_aabb", True))
    cobertura_ok = cobertura_aabb >= 0.01
    convexo_ok = bool(convexo["convexo"]) and (dentro_da_aabb or not exigir_dentro_aabb) and cobertura_ok
    ok = col_ok and prefixo_ok and convexo_ok
    return {
        "id": "G7",
        "status": "ok" if ok else "falhou",
        "medido": {
            "partes": partes,
            "nos": nomes,
            "convexidade": convexo,
            "dentro_da_aabb": dentro_da_aabb,
            "cobertura_aabb": cobertura_aabb,
        },
        "limite": {
            "max_partes": perfil["colisao"]["max_partes"],
            "prefixo": prefixo,
            "convexo": True,
        },
        "codigo": None if ok else "FORGE-E-QC",
    }


def _avaliar_g8(resultado: dict) -> dict:
    licenca = resultado.get("licenca") or {}
    lic_ok = bool(licenca.get("uso_comercial"))
    return {
        "id": "G8",
        "status": "ok" if lic_ok else "falhou",
        "medido": {"modelo": licenca.get("modelo"), "uso_comercial": licenca.get("uso_comercial")},
        "limite": {"uso_comercial": True},
        "codigo": None if lic_ok else "FORGE-E-LICENCA",
    }


def _avaliar_g9(
    gltf: dict,
    binario: bytes,
    item: dict,
    v: dict,
    info: dict,
    pasta: Path,
    arquivos: list[dict],
    permite_alpha_cards: bool,
) -> dict:
    limite_tri = int(item["limite_triangulos"])
    qualidade_item = str(item.get("qualidade") or "standard").strip().lower()
    bytes_max_kb = int(v["bytes_max_kb"])
    if qualidade_item == "hero":
        bytes_max_kb = max(bytes_max_kb, 4096)
    elif qualidade_item == "ultra":
        bytes_max_kb = max(bytes_max_kb, 16384)
    bytes_max = bytes_max_kb * 1024
    maiores = []
    for arq in arquivos:
        caminho = pasta / arq["caminho"]
        tamanho = caminho.stat().st_size if caminho.is_file() else 0
        if tamanho > bytes_max:
            maiores.append({"arquivo": arq["caminho"], "bytes": tamanho})
    partes_max = v.get("partes_max")
    tri_parte_max = (
        v.get("triangulos_por_parte_max_ultra")
        if qualidade_item == "ultra" and v.get("triangulos_por_parte_max_ultra") is not None
        else v.get("triangulos_por_parte_max")
    )
    prim_tris = info.get("prim_tris") or []
    partes_ok = True if (partes_max is None or not gltf.get("meshes")) else info["primitivas"] <= int(partes_max)
    tri_parte_ok = (
        True
        if (tri_parte_max is None or not prim_tris)
        else max(prim_tris) <= int(tri_parte_max)
    )
    raw_lod = item.get("lod")
    niveis_pedidos: list[int] = []
    arquivos_pedidos: set[str] = set()
    if isinstance(raw_lod, list):
        if any(isinstance(x, dict) for x in raw_lod):
            for entry in raw_lod:
                if isinstance(entry, dict) and _eh_int(entry.get("nivel")) and entry["nivel"] >= 1:
                    niveis_pedidos.append(int(entry["nivel"]))
                    if entry.get("arquivo"):
                        arquivos_pedidos.add(str(entry["arquivo"]))
        else:
            ints_lod = [x for x in raw_lod if _eh_int(x) or isinstance(x, float)]
            if len(ints_lod) > 1:
                niveis_pedidos = list(range(1, len(ints_lod)))

    lods_arq = [a for a in arquivos if a.get("papel") == "lod"]
    lods_ok = True
    detalhes_lods: list[dict] = []
    if niveis_pedidos:
        caminhos_lods = {str(a.get("caminho") or "") for a in lods_arq}
        if len(lods_arq) < len(niveis_pedidos) or not (arquivos_pedidos <= caminhos_lods):
            lods_ok = False
            detalhes_lods.append(
                {
                    "ok": False,
                    "motivo": "lod_ausente",
                    "esperados": len(niveis_pedidos),
                    "encontrados": len(lods_arq),
                }
            )
    if lods_arq and gltf.get("meshes"):
        pos0, tris0 = malha(gltf, binario)
        lod0_tem_uv = info["primitivas"] > 0 and info["sem_uv"] == 0
        lod0_tem_skin = bool(gltf.get("skins")) and info["ossos"] > 0
        for arq_lod in lods_arq:
            caminho_lod = pasta / arq_lod["caminho"]
            if not caminho_lod.is_file():
                lods_ok = False
                detalhes_lods.append({"arquivo": arq_lod["caminho"], "ok": False})
                continue
            try:
                gltf_lod, bin_lod = ler_glb_bin(caminho_lod)
                if (
                    not gltf_lod.get("meshes")
                    or ("nodes" in gltf_lod and not isinstance(gltf_lod["nodes"], list))
                    or ("meshes" in gltf_lod and not isinstance(gltf_lod["meshes"], list))
                ):
                    raise erro_qc("LOD sem malhas ou nodes invalidos")
                info_lod = analisar(gltf_lod, bin_lod)
                erros_lod = list(info_lod.get("erros") or ())
                if erros_lod:
                    raise erro_qc(f"LOD malformado: {', '.join(erros_lod)}")
                topo_lod = topologia(gltf_lod, bin_lod)
                pos_lod, tris_lod = malha(gltf_lod, bin_lod)
                if len(tris_lod) == 0:
                    raise erro_qc("LOD sem triangulos")
            except (ForgeError, OSError, OverflowError, struct.error, ValueError, IndexError, TypeError) as exc:
                logger.debug("falha ao ler LOD '%s' em G9: %s", arq_lod["caminho"], exc)
                lods_ok = False
                detalhes_lods.append({"arquivo": arq_lod["caminho"], "ok": False, "erro": str(exc)})
                continue
            bordas_lod = int(topo_lod.get("bordas_abertas", 0))
            arestas_t_lod = int(
                topo_lod.get("arestas_t", max(0, int(topo_lod.get("nao_manifold", 0)) - bordas_lod))
            )
            lod_manifold_ok = (
                arestas_t_lod <= int(v["nao_manifold_max"])
                if permite_alpha_cards
                else int(topo_lod["nao_manifold"]) <= int(v["nao_manifold_max"])
            )
            topo_lod_ok = (
                lod_manifold_ok
                and int(topo_lod.get("degeneradas", 0)) <= int(v["faces_degeneradas_max"])
                and int(topo_lod.get("invertidas", 0)) == 0
            )
            reducao_ok = len(tris_lod) < len(tris0) if len(tris0) > 12 else len(tris_lod) <= len(tris0)
            iou_min: float | None = None
            silhueta_ok = True
            if len(tris0) >= 12 and len(tris_lod) >= 4:
                iou_min = _silhueta_iou_lod(pos0, tris0, pos_lod, tris_lod)
                limiar_iou = 0.78 if len(tris_lod) < 200 else 0.85
                silhueta_ok = iou_min >= limiar_iou
            lod_uv_ok = True
            if lod0_tem_uv:
                uv_lod = _uv_status(
                    gltf_lod, bin_lod, permitir_tiling=True, eh_blocky=True, forcar_area=True
                )
                lod_uv_ok = (
                    info_lod["primitivas"] > 0
                    and info_lod["sem_uv"] == 0
                    and uv_lod["fora_intervalo"] == 0
                    and uv_lod["uv_colapsada"] == 0
                )
            lod_skin_ok = True
            if lod0_tem_skin:
                skin_lod = _skin_status(gltf_lod, bin_lod)
                lod_skin_ok = (
                    bool(gltf_lod.get("skins"))
                    and info_lod["ossos"] > 0
                    and bool(skin_lod["ok"])
                )
            lod_ok = topo_lod_ok and silhueta_ok and reducao_ok and lod_uv_ok and lod_skin_ok
            lods_ok = lods_ok and lod_ok
            detalhes_lods.append(
                {
                    "arquivo": arq_lod["caminho"],
                    "nao_manifold": topo_lod["nao_manifold"],
                    "degeneradas": topo_lod.get("degeneradas", 0),
                    "invertidas": topo_lod.get("invertidas", 0),
                    "iou_min": None if iou_min is None else round(iou_min, 4),
                    "uv_ok": lod_uv_ok,
                    "skin_ok": lod_skin_ok,
                    "ok": lod_ok,
                }
            )
    tri_ok = info["triangulos"] <= limite_tri and not maiores and partes_ok and tri_parte_ok and lods_ok
    return {
        "id": "G9",
        "status": "ok" if tri_ok else "falhou",
        "medido": {
            "triangulos": info["triangulos"],
            "limite": limite_tri,
            "primitivas": info["primitivas"],
            "max_tris_primitiva": max(prim_tris) if prim_tris else 0,
            "acima_do_tamanho": maiores,
            "qualidade": item.get("qualidade", "standard"),
            **({"lods": detalhes_lods} if detalhes_lods else {}),
        },
        "limite": {
            "limite_triangulos": limite_tri,
            "bytes_max_kb": bytes_max_kb,
            **({"partes_max": int(partes_max)} if partes_max is not None else {}),
            **(
                {"triangulos_por_parte_max": int(tri_parte_max)}
                if tri_parte_max is not None
                else {}
            ),
        },
        "codigo": None if tri_ok else "FORGE-E-QC",
    }


def _avaliar_g10(
    gltf: dict, binario: bytes, item: dict, info: dict, exigir_orientacao: bool
) -> tuple[dict, list[dict]]:
    clipes = animacoes(gltf, binario)
    pedidos = [str(a) for a in (item.get("animacoes_base") or [])]
    por_nome = {c["nome"]: c for c in clipes}
    faltando = [n for n in pedidos if n not in por_nome]
    invalidos = [
        c["nome"]
        for c in clipes
        if c["duracao_s"] <= 0.2
        or c["canais"] < 1
        or not c["movendo"]
        or (
            exigir_orientacao
            and (
                not bool(c.get("loop_fechado", True))
                or (info["ossos"] >= 6 and len(c["movendo"]) < 2)
            )
        )
    ]
    anim_ok = not faltando and not invalidos
    gate = {
        "id": "G10",
        "status": "ok" if anim_ok else "falhou",
        "medido": {
            "clipes": clipes,
            "pedidos": pedidos,
            "faltando": faltando,
            "invalidos": invalidos,
        },
        "limite": {"duracao_min_s": 0.2, "canais_min": 1},
        "codigo": None if anim_ok else "FORGE-E-QC",
    }
    return gate, clipes


def _resolver_arquivo_rel(raw: object, base: Path, bruto: Path | None = None) -> Path | None:
    if not raw:
        return None
    if (p := Path(str(raw)).expanduser()).is_absolute():
        return p
    return next((c for c in (base / p, *((bruto / p,) if bruto is not None else ()), p) if c.exists()), base / p)


def _resolver_caminhos_g15(item: dict, pasta: Path, resultado: dict) -> tuple[Path | None, Path | None, bool]:
    bruto_dir = pasta.parent / "bruto" if (pasta.parent / "bruto").is_dir() else None
    render_path = _resolver_arquivo_rel(resultado.get("render_png") or resultado.get("turntable_png") or item.get("render_png"), pasta, bruto_dir)
    if explicit_c := (resultado.get("concept_png") or item.get("concept_png")):
        return _resolver_arquivo_rel(explicit_c, pasta, bruto_dir), render_path, False
    for arq in resultado.get("arquivos") or []:
        if isinstance(arq, dict) and arq.get("papel") == "concept" and Path(str(arq.get("caminho") or "")).suffix.lower() in _EXTS_IMAGEM:
            return _resolver_arquivo_rel(arq.get("caminho"), pasta, bruto_dir), render_path, False
    if isinstance(c_meta := resultado.get("concept"), dict):
        vistas = c_meta.get("vistas")
        for raw_c in ([vistas.get("front")] if isinstance(vistas, dict) else []) + [c_meta.get(k) for k in ("front", "imagem", "caminho")]:
            if raw_c and (cand := _resolver_arquivo_rel(raw_c, pasta, bruto_dir)) is not None and cand.is_file():
                return cand, render_path, False
    item_id = str(item.get("id") or "").strip()
    nomes_cand, dirs_cand = ["concept_front", "concept"] + ([f"{item_id}_concept"] if item_id else []), [pasta] + ([bruto_dir] if bruto_dir is not None else [])
    if found := next((c for c in (d / f"{b}{ext}" for d in dirs_cand for b in nomes_cand for ext in (".png", ".jpg", ".jpeg", ".webp")) if c.is_file()), None):
        return found, render_path, False
    eh_tmpl_ou_proc = str(item.get("rota") or "") in ("template", "procedural") or bool(item.get("template_humanoide"))
    if bruto_dir is not None and not eh_tmpl_ou_proc and str(item.get("rota") or "") in ("mesh", "i23d", "extrude_2d"):
        if found_in := next((bruto_dir / n for n in ("input.png", "input_rgba.png") if (bruto_dir / n).is_file()), None):
            return found_in, render_path, False
    if (origem := item.get("origem")) and (p_orig := Path(str(origem)).expanduser()).suffix.lower() in _EXTS_IMAGEM and p_orig.is_file():
        return p_orig, render_path, eh_tmpl_ou_proc
    return None, render_path, False


def _eh_stub_sintetico(gltf: dict, info: dict) -> bool:
    tris = int(info.get("triangulos", 0))
    gen = str((gltf.get("asset") or {}).get("generator") or "").lower()
    return tris <= 24 or (tris <= 48 and (gen.startswith("forge3d-e2e") or gen.startswith("forge3d-test")))


def _resp_g15(status: str, limite: dict[str, float], codigo: str | None = None, **medido: Any) -> dict[str, Any]:
    return {"id": "G15", "status": status, "medido": medido, "limite": limite, **({"codigo": codigo} if codigo is not None else {})}


def _resolver_vista_back_g15(pasta: Path, resultado: dict) -> Path | None:
    if not isinstance(c_meta := resultado.get("concept"), dict) or not isinstance(vistas := c_meta.get("vistas"), dict):
        return None
    raw_back = vistas.get("back")
    if not isinstance(raw_back, str) or not raw_back.strip():
        return None
    bruto_dir = pasta.parent / "bruto" if (pasta.parent / "bruto").is_dir() else None
    cand = _resolver_arquivo_rel(raw_back, pasta, bruto_dir)
    return cand if cand is not None and cand.is_file() else None


def _mask_apose_g15(pasta: Path, resultado: dict) -> dict[str, Any] | None:
    ref = resultado.get("g15_apose_ref") or (resultado.get("medidas") or {}).get("g15_apose_ref")
    if not isinstance(ref, str) or not ref.strip() or Path(ref).is_absolute():
        return None
    raiz = pasta.resolve(strict=False)
    cand = (raiz / ref).resolve(strict=False)
    if cand == raiz or not cand.is_relative_to(raiz) or not cand.is_file():
        return None
    try:
        g_ref, b_ref = ler_glb_bin(cand)
        m_ap = rasterizar_silhueta_frontal_glb(g_ref, b_ref)
        return None if m_ap["vazia"] else m_ap
    except (ForgeError, OSError, OverflowError, struct.error, ValueError, IndexError, TypeError) as exc:
        logger.debug("falha ao ler ref apose G15 '%s': %s", cand, exc)
        return None


def _avaliar_g15(gltf: dict, binario: bytes, item: dict, perfil: dict, info: dict, pasta: Path, resultado: dict) -> dict[str, Any]:
    del perfil
    estrito = bool(item.get("g15_estrito") or resultado.get("g15_estrito"))
    limite = {"iou_min": LIMIAR_IOU_G15, "aspect_ratio_min": LIMIAR_ASPECT_G15}
    concept_path, render_path, via_origem_apenas = _resolver_caminhos_g15(item, pasta, resultado)
    vol_res = avaliar_volumetria_glb(gltf, binario, item, info, concept_back=_resolver_vista_back_g15(pasta, resultado))
    vol_extra = {"volumetrico": vol_res} if vol_res["aplicavel"] else {}
    vol_falhou = bool(vol_res["aplicavel"] and not vol_res["aprovado"])
    if concept_path is None and render_path is None:
        if estrito:
            return _resp_g15("falhou", limite, "FORGE-E-QC", aplicavel=True, erro="concept ausente com g15_estrito=True")
        if vol_falhou:
            return _resp_g15("falhou", limite, "FORGE-E-QC", aplicavel=True, modo="volumetrico", motivo="volumetria_g15b_reprovada", volumetrico=vol_res)
        return _resp_g15("ok", limite, None, aplicavel=bool(vol_res["aplicavel"]), **vol_extra)
    if concept_path is None:
        return _resp_g15("falhou", limite, "FORGE-E-QC", aplicavel=True, erro="render_png informado sem concept_png")
    if render_path is not None:
        try:
            res = avaliar_fidelidade_concept_3d(concept_path, render_path)
            if res["aprovado"] and vol_falhou:
                return _resp_g15("falhou", limite, "FORGE-E-QC", aplicavel=True, modo="render_pair", **{**res, "aprovado": False, "motivo": "volumetria_g15b_reprovada"}, volumetrico=vol_res)
            return _resp_g15("ok" if res["aprovado"] else "falhou", limite, None if res["aprovado"] else "FORGE-E-QC", aplicavel=True, modo="render_pair", **res, **vol_extra)
        except ForgeError as exc:
            return _resp_g15("falhou", limite, "FORGE-E-QC", aplicavel=True, concept=str(concept_path), render=str(render_path), erro=str(exc))
    try:
        m_concept = _carregar_mascara_arquivo(concept_path)
    except ForgeError as exc:
        return _resp_g15("falhou", limite, "FORGE-E-QC", aplicavel=True, concept=str(concept_path), erro=str(exc))
    if m_concept["vazia"]:
        return _resp_g15("falhou", limite, "FORGE-E-QC", aplicavel=True, concept=str(concept_path), motivo="concept_vazio_sem_silhueta")
    if m_concept["uniforme"]:
        if not estrito and vol_falhou:
            return _resp_g15("falhou", limite, "FORGE-E-QC", aplicavel=True, concept=str(concept_path), motivo="volumetria_g15b_reprovada", volumetrico=vol_res)
        return _resp_g15("falhou" if estrito else "warn", limite, "FORGE-E-QC" if estrito else "FORGE-W-FIDELIDADE", aplicavel=True, concept=str(concept_path), motivo="concept_uniforme_sem_silhueta", **vol_extra)
    if (m_modelo := rasterizar_silhueta_frontal_glb(gltf, binario))["vazia"]:
        return _resp_g15("falhou" if estrito else "warn", limite, "FORGE-E-QC" if estrito else "FORGE-W-FIDELIDADE", aplicavel=True, concept=str(concept_path), motivo="glb_sem_silhueta", **vol_extra)
    if (comp := _comparar_mascaras(m_concept, m_modelo))["aprovado"]:
        if vol_falhou:
            return _resp_g15("falhou", limite, "FORGE-E-QC", aplicavel=True, modo="glb_frontal", concept=str(concept_path), **{**comp, "aprovado": False, "motivo": "volumetria_g15b_reprovada"}, volumetrico=vol_res)
        return _resp_g15("ok", limite, None, aplicavel=True, modo="glb_frontal", concept=str(concept_path), **comp, **vol_extra)
    if (m_apose := _mask_apose_g15(pasta, resultado)) is not None and (comp_ap := _comparar_mascaras(m_concept, m_apose))["aprovado"]:
        if vol_falhou:
            return _resp_g15("falhou", limite, "FORGE-E-QC", aplicavel=True, modo="glb_frontal", concept=str(concept_path), comparado_em_apose=True, **{**comp_ap, "aprovado": False, "motivo": "volumetria_g15b_reprovada"}, volumetrico=vol_res)
        return _resp_g15("ok", limite, None, aplicavel=True, modo="glb_frontal", concept=str(concept_path), comparado_em_apose=True, **comp_ap, **vol_extra)
    eh_extrude2d = (bool(item.get("extrudir_2d")) or str(item.get("rota") or "") == "extrude_2d") and str(item.get("pivot") or "empunhadura") == "empunhadura" and str(item.get("parte") or "arma") == "arma"
    if not estrito and eh_extrude2d and (comp_180 := _comparar_mascaras({**m_concept, "mask": m_concept["mask"][::-1]}, m_modelo))["aprovado"]:
        return _resp_g15("ok", limite, None, aplicavel=True, modo="glb_frontal", concept=str(concept_path), rotacionado_180=True, **comp_180)
    if not estrito and (_eh_stub_sintetico(gltf, info) or via_origem_apenas):
        if not _eh_stub_sintetico(gltf, info) and vol_falhou:
            return _resp_g15("falhou", limite, "FORGE-E-QC", aplicavel=True, modo="glb_frontal", concept=str(concept_path), **{**comp, "motivo": "volumetria_g15b_reprovada"}, volumetrico=vol_res)
        return _resp_g15("warn", limite, "FORGE-W-FIDELIDADE", aplicavel=True, modo="glb_frontal", concept=str(concept_path), **{**comp, "motivo": "divergencia_stub_sintetico"}, **vol_extra)
    return _resp_g15("falhou", limite, "FORGE-E-QC", aplicavel=True, modo="glb_frontal", concept=str(concept_path), **{**comp, "motivo": "baixa_fidelidade_concept_3d"}, **vol_extra)
