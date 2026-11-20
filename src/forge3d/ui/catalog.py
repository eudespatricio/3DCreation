"""Consultas somente-leitura de catalogo, metadados, destinos, runs e ledger da UI."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from .. import PIPELINE_VERSION, __version__, config, doctor, index, paths, profiles, publish, rbx
from ..errors import ForgeError
from .state import (
    erro_nao_encontrado,
    erro_proibido,
    erro_requisicao,
    raizes_leitura_permitidas,
    resolver_caminho_leitura,
    validar_identificador_segmento,
)

_PAPEIS_TEXTURA = frozenset({"textura", "normal", "orm", "roughness", "metallic"})
_EXTS_IMAGEM = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_EXTS_EXPORT_ADJ = frozenset({".rbxlx", ".rbxmx", ".lua", ".gd"})


def _iso_mtime(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _caminho_confinado(base_dir: Path, rel_raw: str) -> Path:
    limpo = str(rel_raw or "").strip()
    if not limpo or "\x00" in limpo:
        raise erro_proibido("caminho relativo invalido no manifesto")
    base_res = base_dir.resolve(strict=False)
    alvo = (base_res / limpo).resolve(strict=False)
    if alvo == base_res or not alvo.is_relative_to(base_res):
        raise erro_proibido(f"arquivo referenciado escapa do destino ({limpo!r})", destino=str(base_res), caminho=limpo)
    raiz_cfg = paths.raiz_config().resolve(strict=False)
    if alvo == raiz_cfg or alvo.is_relative_to(raiz_cfg):
        raise erro_proibido("acesso negado a raiz_config")
    return alvo


def _url_arquivo(caminho: Path, *, download: bool = False) -> str:
    q = quote(str(caminho), safe="")
    return f"/api/file?path={q}&download=1" if download else f"/api/file?path={q}"


def _ler_json_opcional(arq: Path) -> dict[str, Any] | None:
    if not arq.is_file():
        return None
    try:
        doc = json.loads(arq.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[ui] aviso ao ler {arq}: {exc}", file=sys.stderr)
        return None


def obter_health() -> dict[str, Any]:
    return {
        "ok": True, "versao": __version__, "pipeline_version": PIPELINE_VERSION,
        "estado": str(paths.raiz_estado()), "config": str(paths.raiz_config()),
    }


def obter_doctor() -> dict[str, Any]:
    return {"ok": True, "doctor": doctor.checar()}


def obter_meta() -> dict[str, Any]:
    schema_doc = _ler_json_opcional(paths.raiz_dados() / "schemas" / "spec.v6.schema.json") or {}
    top_props = schema_doc.get("properties") or {}
    item_props = ((schema_doc.get("$defs") or {}).get("item") or {}).get("properties") or {}
    sockets_enum = list(
        ((item_props.get("sockets") or {}).get("items") or {}).get("enum")
        or ["Hand.R", "Hand.L", "Back", "Head", "Shoulder.L", "Shoulder.R", "MountSeat"]
    )
    clipes_lista = list(profiles.ANIMACOES_SUPORTADAS)
    partes_r15 = [p for p in rbx.PARENT_R15.keys() if p != "HumanoidRootPart"]
    _enum = lambda obj, ch, pad=None: list((obj.get(ch) or {}).get("enum") or (pad or []))  # noqa: E731
    pol_p = (top_props.get("politica") or {}).get("properties") or {}
    req_p = (top_props.get("requisicao") or {}).get("properties") or {}
    rbx_p = (top_props.get("roblox_render") or {}).get("properties") or {}
    rig_p_s = (item_props.get("rig") or {}).get("properties") or {}
    schema_enums: dict[str, Any] = {
        "tipos": _enum(item_props, "tipo"), "rotas": _enum(item_props, "rota"),
        "estilos": _enum(top_props, "estilo_global"), "pivots": _enum(item_props, "pivot"),
        "materiais": _enum(item_props, "material"), "materiais_procedurais": _enum(item_props, "material_procedural"),
        "providers_conceito": _enum(item_props, "provider_conceito"), "vistas": _enum(item_props, "vistas", [1, 4]),
        "colisoes": _enum(item_props, "colisao"), "qualidades": _enum(item_props, "qualidade", ["standard", "hero", "ultra"]),
        "clipes": clipes_lista, "sockets": sockets_enum, "pecas_kit": _enum(item_props, "parte"),
        "rig_modos": _enum(rig_p_s, "modo", ["motor6d", "skinned", "none"]),
        "modos_rig_roblox": _enum(item_props, "modo_rig_roblox", ["motor6d", "bone"]),
        "politica_falha": _enum(pol_p, "falha", ["continuar", "abortar"]),
        "isolamento": _enum(req_p, "isolamento", ["padrao", "estrito"]),
        "lighting_technology": _enum(rbx_p, "lighting_technology"),
        "render_fidelity": _enum(rbx_p, "render_fidelity_padrao"),
        "esqueletos": ["godot-humanoid@1", "godot-humanoid-aa@1", "r15@1", "quadruped@1", "winged_mount@1"],
        "verify_aspectos": list(publish.VERIFY_ASPECTOS),
    }

    perfis_out: list[dict[str, Any]] = []
    for nome in profiles.perfis_disponiveis():
        try:
            doc_p = profiles.carregar(nome)
        except (ForgeError, OSError, ValueError, KeyError) as exc:
            print(f"[ui] aviso ao carregar perfil {nome}: {exc}", file=sys.stderr)
            continue
        rig_p = doc_p.get("rig") or {}
        esq_pad = str(rig_p.get("esqueleto_padrao") or "")
        esqueletos_p = sorted({s for s in [esq_pad, *(rig_p.get("retarget") or {}), *(rig_p.get("mapas") or {})] if s})
        resumo_p = {
            "unidades": doc_p.get("unidades") or {}, "escala_saida": profiles.escala_saida(doc_p),
            "orcamento_triangulos": doc_p.get("orcamento_triangulos") or {},
            "orcamento_triangulos_hero": doc_p.get("orcamento_triangulos_hero") or {},
            "orcamento_triangulos_ultra": doc_p.get("orcamento_triangulos_ultra") or {},
            "orcamento_cena": profiles.orcamento_cena_perfil(doc_p),
            "esqueleto_padrao": esq_pad, "esqueletos": esqueletos_p, "formato": doc_p.get("formato") or ["glb"],
        }
        perfis_out.append({"nome": nome, **resumo_p, "resumo": resumo_p})

    exemplos: list[dict[str, Any]] = []
    dir_ex = paths.raiz_dados() / "examples"
    for arq in (sorted(dir_ex.glob("lote_*.yaml")) if dir_ex.is_dir() else []):
        try:
            doc_ex = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            print(f"[ui] aviso ao ler exemplo {arq}: {exc}", file=sys.stderr)
            continue
        if isinstance(doc_ex, dict):
            exemplos.append({
                "nome": arq.name, "caminho": str(arq), "projeto": str(doc_ex.get("projeto") or ""),
                "perfil": str(doc_ex.get("perfil") or ""), "schema": str(doc_ex.get("schema") or ""),
                "itens": len(doc_ex.get("lote") or []),
            })

    return {
        "ok": True, "schema_atual": "forge3d/spec@6", "schema": schema_doc, "schema_enums": schema_enums,
        "perfis": perfis_out, "clipes": clipes_lista, "sockets": sockets_enum, "partes_r15": partes_r15, "exemplos": exemplos,
    }


def obter_exemplo(nome_raw: str) -> dict[str, Any]:
    limpo = (nome_raw or "").strip()
    if not limpo:
        raise erro_requisicao("nome do exemplo ausente")
    if "/" in limpo or "\\" in limpo or ".." in limpo or "\x00" in limpo or limpo.startswith("."):
        raise erro_proibido(f"nome de exemplo proibido: {limpo!r}", nome=limpo)
    dir_ex = (paths.raiz_dados() / "examples").resolve(strict=False)
    sufixo = Path(limpo).suffix.lower()
    if sufixo and sufixo not in (".yaml", ".yml"):
        raise erro_proibido(f"extensao de exemplo nao permitida: {sufixo!r}", nome=limpo)

    candidatos = [dir_ex / limpo] if sufixo else [dir_ex / f"{limpo}.yaml", dir_ex / f"{limpo}.yml"]
    for c in candidatos:
        if not c.resolve(strict=False).is_relative_to(dir_ex):
            raise erro_proibido("tentativa de escape em examples/", nome=limpo)
    alvo = next((c.resolve(strict=False) for c in candidatos if c.is_file()), None)
    if alvo is None:
        raise erro_nao_encontrado(f"exemplo nao encontrado: {limpo}", nome=limpo)

    texto = alvo.read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(texto)
    except yaml.YAMLError as exc:
        raise erro_requisicao(f"exemplo YAML ilegivel ({alvo.name}): {exc}") from exc
    return {"ok": True, "nome": alvo.name, "caminho": str(alvo), "yaml": texto, "doc": doc}


def _coletar_pastas_destino() -> list[Path]:
    vistos: dict[str, Path] = {}
    raiz_cfg = paths.raiz_config().resolve(strict=False)

    def _add(p: Path) -> None:
        res = p.resolve(strict=False)
        if res != raiz_cfg and not res.is_relative_to(raiz_cfg):
            vistos.setdefault(str(res), res)

    saida = paths.dir_saida()
    _add(saida)
    if saida.is_dir():
        for sub in sorted(saida.iterdir()):
            if sub.is_dir() and not sub.name.startswith("."):
                _add(sub)
        for arq_m in sorted(saida.rglob("*.manifest.json")):
            _add(arq_m.parent)
    for raiz_al in config.carregar():
        _add(raiz_al)
        if raiz_al.is_dir():
            for sub in sorted(raiz_al.iterdir()):
                if sub.is_dir() and not sub.name.startswith(".") and any(sub.glob("*.manifest.json")):
                    _add(sub)
    for row in index.consultar():
        if row.get("destino"):
            _add(Path(str(row["destino"])).expanduser())
    return list(vistos.values())


def listar_destinos() -> dict[str, Any]:
    destinos_out: list[dict[str, Any]] = []
    for pasta in _coletar_pastas_destino():
        manifestos = sorted(pasta.glob("*.manifest.json")) if pasta.is_dir() else []
        ultimo_mod: str | None = None
        try:
            if manifestos:
                ultimo_mod = _iso_mtime(max(m.stat().st_mtime for m in manifestos))
            elif pasta.exists():
                ultimo_mod = _iso_mtime(pasta.stat().st_mtime)
        except OSError:
            ultimo_mod = None
        destinos_out.append({
            "caminho": str(pasta), "nome": pasta.name or str(pasta), "ativos": len(manifestos),
            "ultimo_mod": ultimo_mod, "na_allowlist": config.destino_permitido(pasta),
        })
    destinos_out.sort(key=lambda d: (-int(d["ativos"]), str(d["nome"])))
    return {"ok": True, "sandbox": str(paths.dir_saida()), "allowlist": config.listar(), "destinos": destinos_out}


def _resumir_manifesto_item(
    destino_dir: Path, asset_id: str, base_row: dict[str, Any] | None, man: dict[str, Any] | None
) -> dict[str, Any]:
    row = dict(base_row or {})
    cand_glb = destino_dir / f"{asset_id}.glb"
    existe_glb = cand_glb.is_file()
    res: dict[str, Any] = {
        "asset_id": asset_id, "projeto": str(row.get("projeto") or ""), "perfil": str(row.get("perfil") or ""),
        "rota": str(row.get("rota") or ""), "tipo": "", "tags": [],
        "determinism": str(row.get("determinism") or ""), "triangulos": int(row.get("triangulos") or 0),
        "bytes": int(row.get("bytes") or 0), "materiais": int(row.get("materiais") or 0),
        "ossos": int(row.get("ossos") or 0), "licenca": str(row.get("licenca") or ""),
        "destino": str(destino_dir), "publicado_em": str(row.get("publicado_em") or ""),
        "qc_aprovado": True, "gates_ok": 0, "gates_warn": 0, "gates_total": 0,
        "tem_glb": existe_glb, "tem_lod": False, "tem_colisao": False, "tem_partes": False,
        "tem_texturas": False, "tem_concept": False,
        "glb_path": str(cand_glb) if existe_glb else None,
        "glb_url": _url_arquivo(cand_glb) if existe_glb else None, "preview_image_url": None,
    }
    if man is None:
        return res

    geom, qc_obj = man.get("geometry") or {}, man.get("qc") or {}
    files = [f for f in (man.get("files") or []) if isinstance(f, dict)]
    gates = [g for g in (qc_obj.get("gates") or []) if isinstance(g, dict)]
    papeis = {str(f.get("papel") or "") for f in files}
    glb_abs: Path | None = None
    preview_abs: Path | None = None
    fallback_tex: Path | None = None
    for f in files:
        rel = str(f.get("caminho") or "").strip()
        if not rel:
            continue
        try:
            cand = _caminho_confinado(destino_dir, rel)
        except ForgeError:
            continue
        papel = str(f.get("papel") or "")
        if papel == "mesh" and cand.suffix.lower() == ".glb" and glb_abs is None:
            glb_abs = cand
        if cand.suffix.lower() in _EXTS_IMAGEM and cand.is_file():
            if papel == "concept" and preview_abs is None:
                preview_abs = cand
            elif papel == "textura" and fallback_tex is None:
                fallback_tex = cand

    preview_final = preview_abs or fallback_tex
    lic = man.get("licenca")
    lic_modelo = lic.get("modelo", "") if isinstance(lic, dict) else str(lic or "")
    res.update(
        projeto=str(man.get("projeto") or res["projeto"]), perfil=str(man.get("perfil") or res["perfil"]),
        rota=str(man.get("rota") or res["rota"]), tipo=str(man.get("tipo") or ""), tags=list(man.get("tags") or []),
        determinism=str(man.get("determinism") or res["determinism"]),
        triangulos=int(geom.get("triangulos") or res["triangulos"]),
        bytes=sum(int(f.get("bytes") or 0) for f in files) or res["bytes"],
        materiais=int(geom.get("materiais") or res["materiais"]),
        ossos=int(((man.get("rig") or {}).get("ossos")) or res["ossos"]),
        licenca=lic_modelo or res["licenca"], publicado_em=str(man.get("created_at") or res["publicado_em"]),
        qc_aprovado=bool(qc_obj.get("aprovado", True)),
        gates_ok=sum(1 for g in gates if g.get("status") == "ok"),
        gates_warn=sum(1 for g in gates if g.get("status") == "warn"), gates_total=len(gates),
        tem_glb=bool(glb_abs is not None and glb_abs.is_file()), tem_lod=bool(man.get("lod")) or ("lod" in papeis),
        tem_colisao=("colisor" in papeis) or bool((man.get("colisao") or {}).get("arquivo")),
        tem_partes=bool(man.get("partes")) or ("parte" in papeis), tem_texturas=bool(papeis & _PAPEIS_TEXTURA),
        tem_concept=("concept" in papeis) or (destino_dir / f"{asset_id}_concept.json").is_file(),
        glb_path=str(glb_abs) if glb_abs is not None else None,
        glb_url=_url_arquivo(glb_abs) if (glb_abs is not None and glb_abs.is_file()) else None,
        preview_image_url=_url_arquivo(preview_final) if preview_final is not None else None,
    )
    return res


def listar_ativos(
    *, q: str = "", projeto: str = "", perfil: str = "", rota: str = "",
    destino: str = "", tag: str = "", max_tris: int | None = None, limit: int = 200, offset: int = 0,
) -> dict[str, Any]:
    destino_filtro = resolver_caminho_leitura(destino) if destino.strip() else None
    raizes_ok = raizes_leitura_permitidas()
    mapa: dict[tuple[str, str], dict[str, Any]] = {}

    for row in index.consultar():
        aid, raw_dest = str(row.get("asset_id") or "").strip(), str(row.get("destino") or "").strip()
        if not aid or not raw_dest:
            continue
        dest_p = Path(raw_dest).expanduser().resolve(strict=False)
        if any(dest_p == r or dest_p.is_relative_to(r) for r in raizes_ok):
            mapa[(aid, str(dest_p))] = _resumir_manifesto_item(dest_p, aid, row, _ler_json_opcional(dest_p / f"{aid}.manifest.json"))

    for pasta in ([destino_filtro] if destino_filtro is not None else _coletar_pastas_destino()):
        if pasta is None or not pasta.is_dir():
            continue
        pasta_res = pasta.resolve(strict=False)
        if not any(pasta_res == r or pasta_res.is_relative_to(r) for r in raizes_ok):
            continue
        for arq_man in sorted(pasta_res.glob("*.manifest.json")):
            aid = arq_man.name[: -len(".manifest.json")]
            if (aid, str(pasta_res)) not in mapa:
                man_doc = _ler_json_opcional(arq_man)
                if man_doc is not None:
                    mapa[(aid, str(pasta_res))] = _resumir_manifesto_item(pasta_res, aid, None, man_doc)

    todos = sorted(mapa.values(), key=lambda x: (str(x["asset_id"]), str(x["destino"])))
    filtros = {
        "projetos": sorted({str(a["projeto"]) for a in todos if a["projeto"]}),
        "perfis": sorted({str(a["perfil"]) for a in todos if a["perfil"]}),
        "rotas": sorted({str(a["rota"]) for a in todos if a["rota"]}),
    }
    q_low, tag_clean = q.strip().lower(), tag.strip().lower()
    filtrados: list[dict[str, Any]] = []
    for item in todos:
        if (projeto and item["projeto"] != projeto) or (perfil and item["perfil"] != perfil) or (rota and item["rota"] != rota):
            continue
        if destino_filtro is not None and Path(item["destino"]).resolve(strict=False) != destino_filtro:
            continue
        if max_tris is not None and int(item["triangulos"]) > int(max_tris):
            continue
        if tag_clean and tag_clean not in {str(t).lower() for t in (item.get("tags") or [])}:
            continue
        if q_low and q_low not in f"{item['asset_id']} {item['projeto']} {item['perfil']} {item['rota']} {item.get('tipo', '')} {' '.join(item.get('tags') or [])}".lower():
            continue
        filtrados.append(item)

    off, lim = max(0, int(offset)), max(1, min(1000, int(limit)))
    return {"ok": True, "total": len(filtrados), "filtros": filtros, "ativos": filtrados[off : off + lim]}


def _ref_arquivo(destino_dir: Path, rel: str) -> dict[str, Any]:
    abs_p = _caminho_confinado(destino_dir, rel)
    return {
        "caminho_abs": str(abs_p), "existe": abs_p.is_file(),
        "url": _url_arquivo(abs_p), "download_url": _url_arquivo(abs_p, download=True),
    }


def obter_ativo(destino_raw: str, asset_id_raw: str) -> dict[str, Any]:
    destino_dir = resolver_caminho_leitura(destino_raw)
    asset_id = validar_identificador_segmento(asset_id_raw, "id")
    arq_man = _caminho_confinado(destino_dir, f"{asset_id}.manifest.json")
    if not arq_man.is_file():
        raise erro_nao_encontrado(f"manifesto nao encontrado para '{asset_id}'", destino=str(destino_dir), asset_id=asset_id)
    manifesto = _ler_json_opcional(arq_man)
    if manifesto is None:
        raise erro_requisicao(f"manifesto ilegivel: {arq_man.name}")

    arquivos: list[dict[str, Any]] = []
    mesh_principal: dict[str, Any] | None = None
    for f in manifesto.get("files") or []:
        if not isinstance(f, dict) or not str(f.get("caminho") or "").strip():
            continue
        rel = str(f["caminho"]).strip()
        ref = _ref_arquivo(destino_dir, rel)
        abs_p = Path(ref["caminho_abs"])
        entrada = {
            "caminho": rel, "papel": str(f.get("papel") or ""), "sha256": str(f.get("sha256") or ""),
            "bytes": int(f.get("bytes") or (abs_p.stat().st_size if ref["existe"] else 0)), **ref,
        }
        arquivos.append(entrada)
        if entrada["papel"] == "mesh" and abs_p.suffix.lower() == ".glb" and mesh_principal is None:
            mesh_principal = entrada
    arquivos.sort(key=lambda a: (0 if a["papel"] == "mesh" else 1, str(a["caminho"])))

    lods: list[dict[str, Any]] = []
    for ld in (ld for ld in (manifesto.get("lod") or []) if isinstance(ld, dict)):
        rel_l = str(ld.get("arquivo") or "").strip()
        niv = int(ld.get("nivel") or 0)
        if rel_l:
            lods.append({"nivel": niv, "papel": f"LOD{niv}", "triangulos": int(ld.get("triangulos") or 0), "arquivo": rel_l, "caminho": rel_l, **_ref_arquivo(destino_dir, rel_l)})

    partes_out: list[dict[str, Any]] = []
    for pt in manifesto.get("partes") or []:
        if not isinstance(pt, dict):
            continue
        copia_pt = dict(pt)
        rel_pt = str(pt.get("arquivo") or ((pt.get("arquivos") or [""])[0] if isinstance(pt.get("arquivos"), list) else "") or "").strip()
        if rel_pt:
            copia_pt.update(arquivo=rel_pt, **_ref_arquivo(destino_dir, rel_pt))
        partes_out.append(copia_pt)

    raw_col = manifesto.get("colisao")
    col_meta: dict[str, Any] = dict(raw_col) if isinstance(raw_col, dict) else {}
    arq_col: dict[str, Any] | None = next((a for a in arquivos if a["papel"] == "colisor"), None)
    if arq_col is None and col_meta.get("arquivo"):
        arq_col = {"caminho": str(col_meta["arquivo"]), **_ref_arquivo(destino_dir, str(col_meta["arquivo"]))}
    colisor: dict[str, Any] | None = {**col_meta, **(arq_col or {})} if (col_meta or arq_col) else None

    exports_adj = [
        {"nome": cx.name, "caminho": cx.name, "caminho_abs": str(cx), "papel": "export", "ext": cx.suffix.lower(), "bytes": cx.stat().st_size, "existe": True, "url": _url_arquivo(cx), "download_url": _url_arquivo(cx, download=True)}
        for cx in (sorted(destino_dir.iterdir()) if destino_dir.is_dir() else [])
        if cx.is_file() and cx.name.startswith(asset_id) and cx.suffix.lower() in _EXTS_EXPORT_ADJ
    ]
    return {
        "ok": True, "destino": str(destino_dir), "asset_id": asset_id, "manifesto": manifesto,
        "arquivos": arquivos, "lods": lods, "partes": partes_out, "colisor": colisor,
        "texturas": [a for a in arquivos if a["papel"] in (_PAPEIS_TEXTURA | {"concept"})],
        "concept_json": _ler_json_opcional(_caminho_confinado(destino_dir, f"{asset_id}_concept.json")),
        "exports_adjacentes": exports_adj,
        "bundle_zip_url": f"/api/asset/bundle.zip?destino={quote(str(destino_dir), safe='')}&id={quote(asset_id, safe='')}",
    }


def gerar_bundle_zip(destino_raw: str, asset_id_raw: str) -> tuple[str, bytes]:
    destino_dir = resolver_caminho_leitura(destino_raw)
    asset_id = validar_identificador_segmento(asset_id_raw, "id")
    arq_man = _caminho_confinado(destino_dir, f"{asset_id}.manifest.json")
    if not arq_man.is_file():
        raise erro_nao_encontrado(f"manifesto nao encontrado: {asset_id}", asset_id=asset_id)
    manifesto = _ler_json_opcional(arq_man) or {}
    buf = io.BytesIO()
    vistos: set[str] = {arq_man.name}
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(arq_man, arcname=arq_man.name)
        for f in manifesto.get("files") or []:
            rel = str(f.get("caminho") or "").strip() if isinstance(f, dict) else ""
            if not rel:
                continue
            abs_p = _caminho_confinado(destino_dir, rel)
            arc = abs_p.relative_to(destino_dir.resolve(strict=False)).as_posix()
            if arc not in vistos and abs_p.is_file():
                zf.write(abs_p, arcname=arc)
                vistos.add(arc)
    return f"{asset_id}.bundle.zip", buf.getvalue()


def listar_runs(limit: int = 50) -> dict[str, Any]:
    pasta = paths.dir_runs()
    if not pasta.is_dir():
        return {"ok": True, "total": 0, "runs": []}
    subdirs = sorted([d for d in pasta.iterdir() if d.is_dir() and not d.name.startswith(".")], key=lambda d: d.name, reverse=True)
    saida: list[dict[str, Any]] = []
    for d in subdirs[: max(1, min(500, int(limit)))]:
        arq_p, arq_r = d / "plano.json", d / "relatorio.json"
        plano, rel = _ler_json_opcional(arq_p), _ler_json_opcional(arq_r)
        fonte = rel or plano or {}
        saida.append({
            "run_id": d.name, "comando": fonte.get("comando", "run" if rel else "plan"),
            "projeto": fonte.get("projeto", ""), "perfil": fonte.get("perfil", ""), "destino": fonte.get("destino", ""),
            "exit": rel.get("exit") if isinstance(rel, dict) else None,
            "resumo": rel.get("resumo") if isinstance(rel, dict) else (plano.get("resumo") if isinstance(plano, dict) else None),
            "orcamento_cena": fonte.get("orcamento_cena"), "tem_plano": arq_p.is_file(), "tem_relatorio": arq_r.is_file(),
        })
    return {"ok": True, "total": len(subdirs), "runs": saida}


def obter_run(run_id_raw: str) -> dict[str, Any]:
    rid = validar_identificador_segmento(run_id_raw, "run_id")
    pasta = (paths.dir_runs() / rid).resolve(strict=False)
    if not pasta.is_relative_to(paths.dir_runs().resolve(strict=False)) or not pasta.is_dir():
        raise erro_nao_encontrado(f"run nao encontrado: {rid}", run_id=rid)
    return {"ok": True, "run_id": rid, "plano": _ler_json_opcional(pasta / "plano.json"), "relatorio": _ler_json_opcional(pasta / "relatorio.json")}


def listar_ledger(limit: int = 100) -> dict[str, Any]:
    arq = paths.arquivo_ledger()
    if not arq.is_file():
        return {"ok": True, "total": 0, "eventos": []}
    eventos: list[dict[str, Any]] = []
    for idx, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1):
        bruto = linha.strip()
        if not bruto:
            continue
        try:
            ev = json.loads(bruto)
            if isinstance(ev, dict):
                eventos.append(ev)
        except json.JSONDecodeError as exc:
            print(f"[ui] aviso ledger.jsonl:{idx}: {exc}", file=sys.stderr)
    eventos.reverse()
    return {"ok": True, "total": len(eventos), "eventos": eventos[: max(1, min(2000, int(limit)))]}
