"""Planejamento — puro, sem GPU, sem escrita de asset (D5, L2).

``plan`` e o passo que transforma um script em utilitario: responde "o que seria feito, quanto custa,
quanto vem do cache" sem gastar recurso. E o que roda no CI de pull request.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

from . import __version__, modular, profiles, providers, qc
from .canonical import chave_cache
from .errors import ForgeError
from .providers import blocky as blocky_provider
from .providers import mesh as mesh_provider
from .spec import ALIASES_ESTILO, ROTEAMENTO, resolver_item

__all__ = ["estimar_orcamento_cena", "montar", "perfil_resolvido", "resumo"]

_TRIS_MODULAR_ARMOR: dict[str, int] = {
    "luvas": 2400,
    "peitoral": 2800,
    "elmo": 2200,
    "ombreiras": 1800,
    "calcas": 2200,
    "calças": 2200,
    "botas": 2000,
    "capa": 2000,
    "arma": 1500,
    "escudo": 1000,
    "mochila": 1700,
    "orbe": 1850,
    "sela": 1200,
}

_SKINNED_MODULAR_PADRAO: dict[str, bool] = {
    "peitoral": True,
    "luvas": True,
    "calcas": True,
    "calças": True,
    "botas": True,
    "corpo": True,
    "ombreiras": True,
}

_EXTS_3D = {".glb", ".gltf", ".obj"}


def perfil_resolvido(perfil: dict) -> dict:
    """Perfil sem metadados de origem: entra na chave de cache so o que muda a saida."""
    return {k: v for k, v in perfil.items() if not k.startswith("_")}


def montar(
    spec_doc: dict,
    perfil: dict,
    cache_disponivel,
    *,
    no_cache: bool = False,
) -> list[dict]:
    """Lista de tarefas resolvidas. Rota nao implementada vira ``bloqueada``, nao erro fatal."""
    tarefas: list[dict] = []
    perfil_para_chave = perfil_resolvido(perfil)
    isolamento = (spec_doc.get("requisicao") or {}).get("isolamento", "padrao")
    ignorar_cache = no_cache or (isolamento == "estrito")

    for item in spec_doc["lote"]:
        tarefa = {
            "id": item["id"],
            "tipo": item["tipo"],
            "rota": item["rota"],
            "estado_previsto": "pronto",
            "razao": None,
            "chave": None,
            "cache_hit": False,
            "provedor": None,
            "estimativa": None,
        }
        try:
            provider = providers.obter(item["rota"])
        except ForgeError as exc:
            tarefa["estado_previsto"] = "bloqueada"
            tarefa["razao"] = exc.mensagem
            tarefa["codigo"] = exc.codigo
            tarefas.append(tarefa)
            continue

        chave = chave_cache(
            resolver_item(item),
            __version__,
            {item["rota"]: provider.versao},
            perfil_para_chave,
        )
        tarefa["chave"] = chave
        tarefa["provedor"] = {"nome": provider.nome, "versao": provider.versao}
        tarefa["estimativa"] = provider.custo(item, perfil)
        tarefa["cache_hit"] = False if ignorar_cache else bool(cache_disponivel(chave))

        avaliar = getattr(provider, "preflight_item", None)
        pronto, razao = avaliar(item) if callable(avaliar) else provider.preflight()
        if not pronto:
            if tarefa["cache_hit"]:
                tarefa["aviso_preflight"] = razao
            else:
                tarefa["estado_previsto"] = "bloqueada"
                tarefa["razao"] = razao
                if "VRAM" in razao:
                    # D11/I6: falta de VRAM e recurso (exit 6), nao falha de provider (exit 5)
                    tarefa["codigo"] = "FORGE-E-RECURSO"
        tarefas.append(tarefa)

    return tarefas


def resumo(tarefas: list[dict]) -> dict:
    total = len(tarefas)
    bloqueadas = sum(1 for t in tarefas if t["estado_previsto"] == "bloqueada")
    hits = sum(1 for t in tarefas if t["cache_hit"])
    a_executar = sum(
        1 for t in tarefas if t["estado_previsto"] != "bloqueada" and not t["cache_hit"]
    )
    segundos = sum(
        float((t["estimativa"] or {}).get("segundos_estimados", 0))
        for t in tarefas
        if not t["cache_hit"]
    )
    vram = max(
        [
            int((t["estimativa"] or {}).get("vram_mb", 0))
            for t in tarefas
            if t["estado_previsto"] != "bloqueada" and not t["cache_hit"]
        ],
        default=0,
    )
    return {
        "total": total,
        "prontas": total - bloqueadas,
        "bloqueadas": bloqueadas,
        "cache_hits": hits,
        "a_executar": a_executar,
        "segundos_estimados": round(segundos, 1),
        "vram_pico_mb": vram,
    }


def _resolver_rota(item: dict, spec_doc: dict) -> str:
    rota = str(item.get("rota") or "").strip().lower()
    if rota:
        return rota
    estilo = str(item.get("estilo") or spec_doc.get("estilo_global") or "").strip()
    if estilo in ALIASES_ESTILO:
        estilo = ALIASES_ESTILO[estilo]
    tabela = ROTEAMENTO.get(estilo, {})
    return str(tabela.get(str(item.get("tipo") or ""), tabela.get("*", "blocky")))


def _eh_pbr(item: dict) -> bool:
    return (
        item.get("material") == "pbr"
        or bool(item.get("pbr_zonas"))
        or bool(item.get("material_procedural"))
    )


def _detalhe_alto_ativo(item: dict) -> bool:
    det = item.get("detalhe_alto")
    return isinstance(det, dict) and bool(det.get("ativo", True))


def _tex_max_perfil(perfil: dict, qualidade: str) -> int:
    tex_max = int(
        (perfil.get("material") or {}).get("textura_max")
        or (perfil.get("validacao") or {}).get("textura_max")
        or 0
    )
    if qualidade in ("hero", "ultra") and tex_max > 0:
        tex_max = max(tex_max, 2048)
    return tex_max


def _px_bake_estimado(qualidade: str, perfil: dict) -> tuple[int, int]:
    """Espelha ``bake_pbr.px_bake_recomendado`` para estimar resolucao real sem Blender."""
    teto_perfil = _tex_max_perfil(perfil, qualidade)
    teto_max = 4096 if teto_perfil >= 4096 else 2048
    if teto_perfil > 0:
        teto_max = max(64, min(teto_max, teto_perfil))
    if qualidade == "ultra" and teto_perfil >= 4096:
        px = 4096
    elif qualidade in ("hero", "ultra"):
        px = min(2048, teto_max)
    else:
        px = min(1024, teto_max)

    if px >= 4096:
        px_sub = 4096 if qualidade == "ultra" else 2048
    elif px >= 2048:
        px_sub = 2048 if qualidade == "ultra" else 1024
    elif px >= 1024:
        px_sub = 1024
    else:
        px_sub = max(64, px)
    return px, px_sub


def _texturas_bake_pbr(iid: str, item: dict, perfil: dict, qualidade: str) -> list[dict]:
    """Lista mapas externos + embutidos emitidos por ``bake_pbr.executar_bake_high_low``."""
    px, px_sub = _px_bake_estimado(qualidade, perfil)
    perfil_nome = str(perfil.get("perfil") or perfil.get("_nome") or "").strip().lower()
    texturas = [
        {"id": f"{iid}:baseColor", "px": px, "canais": 4},
        {"id": f"{iid}:normal", "px": px_sub, "canais": 4},
        {"id": f"{iid}:orm", "px": px_sub, "canais": 4},
        {"id": f"{iid}:emb:0", "px": px, "canais": 4},
        {"id": f"{iid}:emb:1", "px": px_sub, "canais": 4},
        {"id": f"{iid}:emb:2", "px": px_sub, "canais": 4},
    ]
    if perfil_nome.startswith("roblox") or bool(item.get("pbr_zonas")) or _detalhe_alto_ativo(item):
        texturas.extend(
            [
                {"id": f"{iid}:roughness", "px": px_sub, "canais": 1},
                {"id": f"{iid}:metallic", "px": px_sub, "canais": 1},
            ]
        )
    return texturas


def _contar_tris_gltf_json(gltf: dict[str, Any]) -> int:
    accessors = gltf.get("accessors") or []
    tris = 0
    for mesh in gltf.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            mode = int(prim.get("mode", 4))
            count = 0
            if "indices" in prim:
                idx = int(prim["indices"])
                if 0 <= idx < len(accessors):
                    count = int(accessors[idx].get("count") or 0)
            else:
                pos_idx = (prim.get("attributes") or {}).get("POSITION")
                if pos_idx is not None and 0 <= int(pos_idx) < len(accessors):
                    count = int(accessors[int(pos_idx)].get("count") or 0)
            if mode == 4:
                tris += count // 3
            elif mode in (5, 6):
                tris += max(0, count - 2)
    return tris


def _inspecionar_gltf(gltf: dict[str, Any], bin_data: bytes = b"", base_dir: Path | None = None) -> dict[str, Any]:
    meshes = gltf.get("meshes") or []
    tem_uv = any(
        "TEXCOORD_0" in (prim.get("attributes") or {})
        for mesh in meshes
        for prim in (mesh.get("primitives") or [])
    )
    tem_cor = any(
        "COLOR_0" in (prim.get("attributes") or {})
        for mesh in meshes
        for prim in (mesh.get("primitives") or [])
    )
    buffer_views = gltf.get("bufferViews") or []
    imagens_px: list[int] = []
    for img in gltf.get("images") or []:
        px = 1024
        if "bufferView" in img and bin_data:
            bv_idx = int(img["bufferView"])
            if 0 <= bv_idx < len(buffer_views):
                bv = buffer_views[bv_idx]
                off = int(bv.get("byteOffset") or 0)
                ln = int(bv.get("byteLength") or 0)
                dims = qc._validar_bytes_imagem(bin_data[off : off + ln])
                if dims:
                    px = max(dims)
        elif isinstance(img.get("uri"), str) and base_dir is not None and not img["uri"].startswith("data:"):
            p_img = base_dir / img["uri"]
            if p_img.is_file():
                dims = qc._validar_bytes_imagem(p_img.read_bytes())
                if dims:
                    px = max(dims)
        imagens_px.append(px)
    return {
        "tris": _contar_tris_gltf_json(gltf),
        "materiais": len(gltf.get("materials") or []),
        "skinned": len(gltf.get("skins") or []) > 0,
        "tem_uv": tem_uv,
        "tem_cor_vertice": tem_cor,
        "imagens_px": imagens_px,
    }


def _inspecionar_arquivo_3d(caminho: Path) -> dict[str, Any] | None:
    """Le metadados baratos de GLB/GLTF/OBJ sem invocar Blender ou GPU."""
    if not caminho.is_file():
        return None
    suf = caminho.suffix.lower()
    try:
        if suf == ".glb":
            data = caminho.read_bytes()
            if len(data) < 20 or data[:4] != b"glTF":
                return None
            ljson = struct.unpack_from("<I", data, 12)[0]
            if 20 + ljson > len(data):
                return None
            gltf = json.loads(data[20 : 20 + ljson].decode("utf-8"))
            bin_data = b""
            pos = 20 + ljson
            if pos + 8 <= len(data):
                lbin, ctype = struct.unpack_from("<II", data, pos)
                if ctype == 0x004E4942:
                    bin_data = data[pos + 8 : pos + 8 + lbin]
            return {**_inspecionar_gltf(gltf, bin_data, caminho.parent), "formato": "glb"}
        if suf == ".gltf":
            gltf = json.loads(caminho.read_text(encoding="utf-8"))
            return {**_inspecionar_gltf(gltf, b"", caminho.parent), "formato": "gltf"}
        if suf == ".obj":
            tris = 0
            mats: set[str] = set()
            tem_uv = False
            with caminho.open("r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    line = raw.strip()
                    if line.startswith("f "):
                        verts = line.split()[1:]
                        if len(verts) >= 3:
                            tris += len(verts) - 2
                    elif line.startswith("vt "):
                        tem_uv = True
                    elif line.startswith("usemtl "):
                        mats.add(line[7:].strip())
            return {
                "tris": tris,
                "materiais": max(1, len(mats)),
                "skinned": False,
                "tem_uv": tem_uv,
                "tem_cor_vertice": False,
                "imagens_px": [],
                "formato": "obj",
            }
    except (OSError, ValueError, struct.error, KeyError, TypeError):
        return None
    return None


def _atlas_px_blocky(caixas: list[dict]) -> int:
    pares: set[tuple[str, str]] = {(str(c.get("cor")), str(c.get("padrao"))) for c in caixas}
    celulas = max(1, len(pares) * 2)
    colunas = max(2, math.ceil(math.sqrt(celulas)))
    tam = 32
    while tam < min(256, colunas * blocky_provider.PX_CELULA):
        tam *= 2
    return tam


def _estimar_modular_tris(item: dict) -> tuple[int, str]:
    bloco = item.get("modular")
    if isinstance(bloco, dict):
        try:
            grade_lista = [int(v) for v in (bloco.get("grade") or [2, 2])]
            grade = (grade_lista[0], grade_lista[1])
            nomes = [str(m) for m in (bloco.get("modulos") or sorted(modular.CATALOGO))]
            setor = (int((bloco.get("setor") or [0, 0])[0]), int((bloco.get("setor") or [0, 0])[1]))
            tamanho = float(bloco.get("tamanho_modulo") or 4.0)
            altura = float(item.get("altura_metros") or 2.4)
            seed = int(item.get("seed") or 0)
            if 0 <= setor[0] < grade[0] and 0 <= setor[1] < grade[1]:
                layout = modular.gerar_layout(grade, nomes, seed)
                caixas = modular.caixas_do_modulo(layout[setor[1]][setor[0]], tamanho, altura)
                return len(caixas) * 12, "modular_wfc"
        except (ValueError, KeyError, IndexError, TypeError):
            pass
    return 36, "modular_heuristica"


def _estimar_item_teto(item: dict, perfil: dict) -> dict:
    iid = str(item.get("id") or "?")
    tipo = str(item.get("tipo") or "prop_estatico")
    qualidade = str(item.get("qualidade") or "standard").strip().lower()
    tris = int(item.get("limite_triangulos") or profiles.limite_tri_qualidade(perfil, tipo, qualidade))
    qtd = int(item.get("quantidade_cena", 1))
    skinned = bool(item.get("auto_rig")) or bool(item.get("skinned"))
    eh_pbr = _eh_pbr(item)
    tex_max_perfil = int((perfil.get("material") or {}).get("textura_max") or 1024)
    px_base = min(tex_max_perfil, 2048 if qualidade in ("hero", "ultra") else 1024)
    px_sub = min(tex_max_perfil, 2048 if qualidade == "ultra" else 1024)
    if eh_pbr:
        texturas = [
            {"id": f"{iid}:color", "px": px_base, "canais": 4},
            {"id": f"{iid}:normal", "px": px_sub, "canais": 3},
            {"id": f"{iid}:roughness", "px": px_sub, "canais": 1},
            {"id": f"{iid}:metallic", "px": px_sub, "canais": 1},
        ]
    else:
        texturas = [{"id": f"{iid}:albedo", "px": min(px_base, 1024), "canais": 4}]
    return {
        "id": iid,
        "tris": tris,
        "quantidade_cena": qtd,
        "mesh_key": str(item.get("mesh_key") or iid),
        "material_key": f"pbr:{iid}" if eh_pbr else "palette_padrao",
        "skinned": skinned,
        "texturas": texturas,
    }


def _estimar_item_calibrado(item: dict, spec_doc: dict, perfil: dict) -> dict:
    """Estimador calibrado por rota usando apenas sinais baratos pre-run (sem Blender/GPU)."""
    iid = str(item.get("id") or "?")
    tipo = str(item.get("tipo") or "prop_estatico")
    qualidade = str(item.get("qualidade") or "standard").strip().lower()
    limite_tri = int(
        item.get("limite_triangulos") or profiles.limite_tri_qualidade(perfil, tipo, qualidade)
    )
    qtd = int(item.get("quantidade_cena", 1))
    rota = _resolver_rota(item, spec_doc)
    eh_pbr = _eh_pbr(item)
    retopologia = str(item.get("retopologia") or "padrao").strip().lower()
    detalhe_alto = _detalhe_alto_ativo(item)
    skinned = bool(item.get("auto_rig")) or bool(item.get("skinned"))

    tris_est: int
    fonte: str
    texturas: list[dict]

    if rota == "blocky":
        altura = float(item.get("altura_metros") or 1.0)
        paleta = item.get("paleta") or spec_doc.get("paleta")
        caixas = blocky_provider._caixas(tipo, altura, {**item, "_paleta": paleta})
        tris_est = min(limite_tri, len(caixas) * 12)
        atlas_px = _atlas_px_blocky(caixas)
        texturas = [
            {"id": f"{iid}:baseColor", "px": atlas_px, "canais": 4},
            {"id": f"{iid}:emb:0", "px": atlas_px, "canais": 4},
        ]
        fonte = "blocky_template"

    elif rota == "modular":
        tris_mod, fonte = _estimar_modular_tris(item)
        tris_est = min(limite_tri, tris_mod)
        texturas = [
            {"id": f"{iid}:baseColor", "px": 32, "canais": 4},
            {"id": f"{iid}:emb:0", "px": 32, "canais": 4},
        ]

    elif rota == "import":
        raw_origem = str(item.get("origem") or "").strip()
        info = _inspecionar_arquivo_3d(Path(raw_origem).expanduser()) if raw_origem else None
        if info and info["tris"] > 0:
            tris_est = min(limite_tri, int(info["tris"]))
            fonte = f"{info['formato']}_header"
        else:
            tris_est = min(limite_tri, max(12, round(limite_tri * 0.35)))
            fonte = "import_heuristica"
        if info and info["skinned"]:
            skinned = True
        tem_uv = bool(info["tem_uv"]) if info else True
        tem_mat = (int(info["materiais"]) > 0) if info else True
        tem_cor = bool(info["tem_cor_vertice"]) if info else False
        deve_bake = (
            tem_cor
            or bool(item.get("material_procedural"))
            or bool(item.get("pbr_zonas"))
            or (str(item.get("material") or "").strip().lower() == "pbr" and (tem_uv or tem_mat))
            or (detalhe_alto and (tem_uv or tem_mat))
            or (retopologia == "quadriflow" and tem_uv and tem_mat)
        )
        if deve_bake:
            texturas = _texturas_bake_pbr(iid, item, perfil, qualidade)
        elif info and info["imagens_px"]:
            texturas = [
                {"id": f"{iid}:emb:{idx}", "px": px_img, "canais": 4}
                for idx, px_img in enumerate(info["imagens_px"])
            ]
        else:
            px_fb = min(_tex_max_perfil(perfil, qualidade) or 1024, 1024)
            texturas = [{"id": f"{iid}:emb:0", "px": px_fb, "canais": 4}]

    else:
        raw_origem = str(item.get("origem") or "").strip()
        origem_path = Path(raw_origem).expanduser() if raw_origem else None
        info = (
            _inspecionar_arquivo_3d(origem_path)
            if origem_path is not None and origem_path.suffix.lower() in _EXTS_3D
            else None
        )
        if info and info["tris"] > 0:
            tris_est = min(limite_tri, int(info["tris"]))
            fonte = f"mesh_{info['formato']}_header"
            if info["skinned"]:
                skinned = True
            texturas = _texturas_bake_pbr(iid, item, perfil, qualidade)
        elif mesh_provider._usar_makehuman_cabelo(item):
            tris_est = min(limite_tri, 2500)
            fonte = "mesh_makehuman_cabelo"
            texturas = [{"id": f"{iid}:emb:0", "px": 1024, "canais": 4}]
        elif mesh_provider._usar_modular_armor(item):
            parte = str(item.get("parte") or "peitoral").strip().lower()
            tris_est = min(limite_tri, _TRIS_MODULAR_ARMOR.get(parte, round(limite_tri * 0.75)))
            fonte = "mesh_modular_armor"
            if item.get("skinned") is None and not item.get("auto_rig"):
                skinned = _SKINNED_MODULAR_PADRAO.get(parte, False)
            if bool(item.get("material_procedural")) or bool(item.get("pbr_zonas")) or detalhe_alto:
                texturas = _texturas_bake_pbr(iid, item, perfil, qualidade)
            else:
                texturas = [
                    {"id": f"{iid}:emb:0", "px": 1024, "canais": 4},
                    {"id": f"{iid}:emb:1", "px": 1024, "canais": 4},
                    {"id": f"{iid}:emb:2", "px": 512, "canais": 4},
                    {"id": f"{iid}:emb:3", "px": 512, "canais": 4},
                ]
        elif mesh_provider._usar_template_criatura(item):
            tris_est = min(limite_tri, round(limite_tri * 0.95))
            fonte = "mesh_template_criatura"
            skinned = bool(item.get("auto_rig", True)) or bool(item.get("skinned"))
            texturas = _texturas_bake_pbr(iid, item, perfil, qualidade)
        elif (
            item.get("template_humanoide") is True
            or bool(item.get("makehuman_cabelo"))
            or mesh_provider._usar_template_humanoide(item)
        ):
            tris_est = min(limite_tri, round(limite_tri * 0.98))
            fonte = "mesh_template_humanoide"
            skinned = bool(item.get("auto_rig", True)) or bool(item.get("skinned"))
            mat_proc = str(item.get("material_procedural") or "").strip()
            if (mat_proc and mat_proc != "pele_humana") or bool(item.get("pbr_zonas")) or detalhe_alto:
                texturas = _texturas_bake_pbr(iid, item, perfil, qualidade)
            else:
                tex_perfil_base = int((perfil.get("material") or {}).get("textura_max") or 1024)
                tex_cap = max(256, min(tex_perfil_base, 2048))
                texturas = [
                    {"id": f"{iid}:baseColor", "px": tex_cap, "canais": 4},
                    {"id": f"{iid}:emb:0", "px": tex_cap, "canais": 4},
                    {"id": f"{iid}:emb:1", "px": tex_cap, "canais": 4},
                    {"id": f"{iid}:emb:2", "px": 1024, "canais": 4},
                    *[
                        {"id": f"{iid}:emb:{k}", "px": 512, "canais": 4}
                        for k in range(3, 8)
                    ],
                ]
        elif mesh_provider._usar_extrude_2d(item):
            tris_est = min(limite_tri, round(limite_tri * 0.90))
            fonte = "mesh_extrude_2d"
            texturas = [
                {"id": f"{iid}:baseColor", "px": 1024, "canais": 4},
                {"id": f"{iid}:emb:0", "px": 1024, "canais": 4},
            ]
        else:
            tris_est = min(limite_tri, round(limite_tri * 0.95))
            fonte = "mesh_heuristica"
            texturas = _texturas_bake_pbr(iid, item, perfil, qualidade)

    vram_item = round(
        sum(qc._vram_mapa_mb(int(t["px"]), int(t["canais"])) for t in texturas),
        2,
    )
    return {
        "id": iid,
        "tris": tris_est,
        "quantidade_cena": qtd,
        "mesh_key": str(item.get("mesh_key") or iid),
        "material_key": f"pbr:{iid}" if eh_pbr else "palette_padrao",
        "skinned": skinned,
        "texturas": texturas,
        "_meta": {
            "rota": rota,
            "fonte": fonte,
            "skinned": skinned,
            "draw_calls": (qtd if skinned else (1 if qtd > 0 else 0)),
            "vram_mb": vram_item,
        },
    }


def estimar_orcamento_cena(spec_doc: dict, perfil: dict) -> dict:
    """Estima o orcamento de cena (Gate G11) separando ``teto_pior_caso`` e ``estimativa`` calibrada."""
    lote = spec_doc.get("lote") or []
    itens_teto = [_estimar_item_teto(item, perfil) for item in lote]
    itens_est = [_estimar_item_calibrado(item, spec_doc, perfil) for item in lote]

    limite = profiles.orcamento_cena_perfil(perfil, spec_doc)
    rel_teto = qc.verificar_g11_orcamento_cena(itens_teto, limite_cena=limite)
    rel_est = qc.verificar_g11_orcamento_cena(itens_est, limite_cena=limite)

    meta_por_id = {it["id"]: it["_meta"] for it in itens_est}
    itens_est_detalhados = [
        {**entry, **meta_por_id.get(entry["id"], {})}
        for entry in (rel_est["medido"].get("itens") or [])
    ]
    est_medido = {**rel_est["medido"], "itens": itens_est_detalhados}

    return {
        "id": rel_teto["id"],
        "status": rel_teto["status"],
        "medido": rel_teto["medido"],
        "limite": rel_teto["limite"],
        "codigo": rel_teto["codigo"],
        "nao_bloqueante": True,
        "teto_pior_caso": {
            "status": rel_teto["status"],
            "codigo": rel_teto["codigo"],
            **rel_teto["medido"],
        },
        "estimativa": {
            "status": rel_est["status"],
            "codigo": rel_est["codigo"],
            **est_medido,
        },
    }
