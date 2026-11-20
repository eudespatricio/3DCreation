#!/usr/bin/env python3
"""Compositor 3D Kitbash guiado por LLM (Gemini) e Vault CC0 — I7, I9, D18.

Fluxo:
1. Consulta ``VaultCC0.buscar_semantico`` para recuperar pecas CC0 e texturas PBR.
2. Gera plano de montagem via ``cloud_ai.planejar_kitbash_gemini`` (ou ``--plan-json``).
3. Executa o Blender 4.2.x headless via arquivo JSON em disco (I9), aplicando encaixe
   de superficie ``BVHTree`` com folga de ``1.5 mm`` (``0.0015 m``) e calculo de pegada
   cilindrica (``smart_fit`` ou fallback ``BVHTree`` embutido).
4. Exporta ``.glb`` 100% manifold (``nao_manifold == 0``).
5. Opcionalmente (``--render``) gera turntable 2x2 via ``tools/render_preview.py`` e
   valida via ``tools/visual_qa_critic.py``.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

RAIZ_REPO = Path(__file__).resolve().parents[1]
if str(RAIZ_REPO / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO / "src"))
if str(RAIZ_REPO / "tools") not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO / "tools"))


def _executar_worker_blender(job_in_path: Path, job_out_path: Path) -> int:
    """Roda dentro do Python 3.11 embutido do Blender 4.2.x (I9: JSON in -> JSON out)."""
    import bmesh  # type: ignore[import-not-found]
    import bpy  # type: ignore[import-not-found]
    from mathutils import Vector  # type: ignore[import-not-found]
    from mathutils.bvhtree import BVHTree  # type: ignore[import-not-found]

    dir_blender = str(RAIZ_REPO / "blender")
    if dir_blender not in sys.path:
        sys.path.insert(0, dir_blender)

    smart_fit_mod: Any = None
    smart_fit_erro: str | None = None
    try:
        import smart_fit as _sf  # type: ignore[import-not-found]

        smart_fit_mod = _sf
    except (ImportError, RuntimeError) as exc:
        smart_fit_mod = None
        smart_fit_erro = f"{type(exc).__name__}: {exc}"
        print(
            f"[kitbash_composer] aviso smart_fit indisponivel ({smart_fit_erro}); usando fallback BVH",
            file=sys.stderr,
        )

    job = json.loads(job_in_path.read_text(encoding="utf-8"))
    out_glb = Path(job["out_glb"])
    pecas_spec = list(job.get("pecas") or [])

    bpy.ops.wm.read_factory_settings(use_empty=True)

    def _bbox_mundo(obj: Any) -> tuple[Vector, Vector]:
        bpy.context.view_layer.update()
        mn = Vector((1e9, 1e9, 1e9))
        mx = Vector((-1e9, -1e9, -1e9))
        for v in obj.data.vertices:
            co = obj.matrix_world @ v.co
            for i in range(3):
                mn[i] = min(mn[i], co[i])
                mx[i] = max(mx[i], co[i])
        return mn, mx

    def _aplicar_transformacao_malha(obj: Any) -> None:
        bpy.context.view_layer.update()
        mat = obj.matrix_world.copy()
        obj.data.transform(mat)
        obj.matrix_world.identity()
        obj.data.update()
        bpy.context.view_layer.update()

    def _encaixar_bvh_fallback(
        peca_obj: Any,
        alvo_obj: Any,
        direcao: tuple[float, float, float] = (0.0, 0.0, 1.0),
        folga_m: float = 0.0015,
    ) -> dict[str, Any]:
        _aplicar_transformacao_malha(peca_obj)
        _aplicar_transformacao_malha(alvo_obj)

        bm_alvo = bmesh.new()
        bm_alvo.from_mesh(alvo_obj.data)
        bm_alvo.transform(alvo_obj.matrix_world)
        bvh_alvo = BVHTree.FromBMesh(bm_alvo)

        mn_a, mx_a = _bbox_mundo(alvo_obj)
        centro_a = (mn_a + mx_a) * 0.5
        dir_vec = Vector(direcao)
        if dir_vec.length <= 1e-6:
            dir_vec = Vector((0.0, 0.0, 1.0))
        dir_vec.normalize()

        # Raycast de fora para o centro do alvo ao longo de -dir_vec para achar ponto de contato exato
        origem_ray = centro_a + dir_vec * 5.0
        hit_loc, _hit_norm, _hit_idx, _hit_dist = bvh_alvo.ray_cast(origem_ray, -dir_vec, 10.0)
        bm_alvo.free()

        if hit_loc is None:
            # Fallback para extremidade do bbox do alvo na direcao
            hit_loc = Vector(
                (
                    centro_a.x + dir_vec.x * ((mx_a.x - mn_a.x) * 0.5),
                    centro_a.y + dir_vec.y * ((mx_a.y - mn_a.y) * 0.5),
                    mx_a.z if dir_vec.z >= 0.0 else mn_a.z,
                )
            )

        mn_p, mx_p = _bbox_mundo(peca_obj)
        centro_p = (mn_p + mx_p) * 0.5
        # Ponto da peca que deve encostar no alvo (face oposta a dir_vec)
        if abs(dir_vec.z) >= max(abs(dir_vec.x), abs(dir_vec.y)):
            z_ancora = mn_p.z if dir_vec.z >= 0.0 else mx_p.z
            ponto_ancora = Vector((centro_p.x, centro_p.y, z_ancora))
        else:
            ponto_ancora = centro_p - Vector(
                (
                    dir_vec.x * (mx_p.x - mn_p.x) * 0.5,
                    dir_vec.y * (mx_p.y - mn_p.y) * 0.5,
                    dir_vec.z * (mx_p.z - mn_p.z) * 0.5,
                )
            )

        ponto_destino = hit_loc + dir_vec * float(folga_m)
        delta = ponto_destino - ponto_ancora
        for v in peca_obj.data.vertices:
            v.co += delta
        peca_obj.data.update()
        bpy.context.view_layer.update()
        return {
            "metodo": "bvh_raycast_fallback",
            "folga_m": float(folga_m),
            "contato": [round(float(c), 5) for c in hit_loc],
            "deslocamento": [round(float(c), 5) for c in delta],
        }

    def _auto_grip_fallback(arma_obj: Any, fracao_cabo: tuple[float, float] = (0.05, 0.35)) -> dict[str, Any]:
        mn, mx = _bbox_mundo(arma_obj)
        alt = max(1e-4, float(mx.z - mn.z))
        z0 = float(mn.z) + fracao_cabo[0] * alt
        z1 = float(mn.z) + fracao_cabo[1] * alt
        pts = [
            arma_obj.matrix_world @ v.co
            for v in arma_obj.data.vertices
            if z0 <= (arma_obj.matrix_world @ v.co).z <= z1
        ]
        if not pts:
            pts = [arma_obj.matrix_world @ v.co for v in arma_obj.data.vertices]
        cx = sum(p.x for p in pts) / len(pts)
        cy = sum(p.y for p in pts) / len(pts)
        cz = sum(p.z for p in pts) / len(pts)
        raios = [math.hypot(p.x - cx, p.y - cy) for p in pts]
        raio_m = sum(raios) / len(raios) if raios else 0.04
        return {
            "centro": [round(cx, 5), round(cy, 5), round(cz, 5)],
            "eixo": [0.0, 0.0, 1.0],
            "raio_m": round(max(0.015, float(raio_m)), 5),
            "comprimento_m": round(max(0.08, z1 - z0), 5),
            "socket_offset": [round(-cx, 5), round(-cy, 5), round(-cz, 5)],
        }

    objetos_por_id: dict[str, Any] = {}
    ordem_objetos: list[Any] = []
    relatorio_pecas: list[dict[str, Any]] = []

    for idx, p_spec in enumerate(pecas_spec):
        pid = str(p_spec.get("id") or f"kb.part_{idx}")
        caminho_glb = p_spec.get("caminho")
        antes = set(bpy.context.scene.objects)

        if caminho_glb and Path(caminho_glb).is_file():
            bpy.ops.import_scene.gltf(filepath=str(caminho_glb))
        novos = [o for o in bpy.context.scene.objects if o not in antes and o.type == "MESH"]
        for o in [o for o in bpy.context.scene.objects if o not in antes and o.type != "MESH"]:
            bpy.data.objects.remove(o, do_unlink=True)

        if not novos:
            bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.06, depth=0.35)
            novos = [bpy.context.active_object]

        if len(novos) > 1:
            bpy.ops.object.select_all(action="DESELECT")
            for o in novos:
                o.select_set(True)
            bpy.context.view_layer.objects.active = novos[0]
            bpy.ops.object.join()
            peca_obj = bpy.context.active_object
        else:
            peca_obj = novos[0]

        peca_obj.name = f"kitbash_{idx}_{pid.replace('.', '_')}"
        _aplicar_transformacao_malha(peca_obj)

        escala = p_spec.get("escala", 1.0)
        if isinstance(escala, (int, float)):
            sx = sy = sz = float(escala)
        elif isinstance(escala, list) and len(escala) == 3:
            sx, sy, sz = float(escala[0]), float(escala[1]), float(escala[2])
        else:
            sx = sy = sz = 1.0
        if (sx, sy, sz) != (1.0, 1.0, 1.0):
            for v in peca_obj.data.vertices:
                v.co.x *= sx
                v.co.y *= sy
                v.co.z *= sz
            peca_obj.data.update()

        # Centraliza X/Y e apoia a base em Z=0 antes do snap
        mn0, mx0 = _bbox_mundo(peca_obj)
        cx0 = (mn0.x + mx0.x) * 0.5
        cy0 = (mn0.y + mx0.y) * 0.5
        for v in peca_obj.data.vertices:
            v.co.x -= cx0
            v.co.y -= cy0
            v.co.z -= mn0.z
        peca_obj.data.update()

        snap_id = p_spec.get("snap_para")
        folga_m = float(p_spec.get("folga_m", 0.0015))
        dir_raw = p_spec.get("direcao_snap") or [0.0, 0.0, 1.0]
        direcao = (float(dir_raw[0]), float(dir_raw[1]), float(dir_raw[2]))

        info_snap: dict[str, Any] = {"metodo": "raiz_base", "folga_m": 0.0}
        alvo_obj = objetos_por_id.get(str(snap_id)) if snap_id else (ordem_objetos[-1] if idx > 0 and ordem_objetos else None)
        if idx > 0 and alvo_obj is not None:
            # Se a direcao e +Z e ja encaixamos outra peca em +Z, empilha no topo atual da montagem
            if direcao[2] > 0.0 and len(ordem_objetos) > 1:
                alvo_topo = max(ordem_objetos, key=lambda o: _bbox_mundo(o)[1].z)
                alvo_obj = alvo_topo
            elif direcao[2] < 0.0 and len(ordem_objetos) > 1:
                alvo_base = min(ordem_objetos, key=lambda o: _bbox_mundo(o)[0].z)
                alvo_obj = alvo_base

            usou_smart_fit = False
            snap_fallback_motivo: str | None = smart_fit_erro
            if smart_fit_mod is not None and hasattr(smart_fit_mod, "encaixar_contato_bvh"):
                try:
                    _aplicar_transformacao_malha(peca_obj)
                    _aplicar_transformacao_malha(alvo_obj)
                    mn_a_sf, mx_a_sf = _bbox_mundo(alvo_obj)
                    mn_p_sf, mx_p_sf = _bbox_mundo(peca_obj)
                    centro_a_sf = (mn_a_sf + mx_a_sf) * 0.5
                    centro_p_sf = (mn_p_sf + mx_p_sf) * 0.5
                    dir_sf = Vector(direcao)
                    if dir_sf.length <= 1e-6:
                        dir_sf = Vector((0.0, 0.0, 1.0))
                    dir_sf.normalize()
                    alcance = max(
                        (mx_a_sf - mn_a_sf).length,
                        (mx_p_sf - mn_p_sf).length,
                        0.2,
                    )
                    pos_inicial = centro_a_sf + dir_sf * (alcance + 0.15)
                    delta_pre = pos_inicial - centro_p_sf
                    for v_p in peca_obj.data.vertices:
                        v_p.co += delta_pre
                    peca_obj.data.update()
                    bpy.context.view_layer.update()
                    res_sf = smart_fit_mod.encaixar_contato_bvh(
                        peca_obj,
                        alvo_obj,
                        direcao=(-dir_sf.x, -dir_sf.y, -dir_sf.z),
                        folga_m=folga_m,
                    )
                    _aplicar_transformacao_malha(peca_obj)
                    info_snap = res_sf if isinstance(res_sf, dict) else {"metodo": "smart_fit", "folga_m": folga_m}
                    usou_smart_fit = True
                except (RuntimeError, ValueError, TypeError, AttributeError, ZeroDivisionError) as exc:
                    usou_smart_fit = False
                    snap_fallback_motivo = f"{type(exc).__name__}: {exc}"
                    print(
                        f"[kitbash_composer] aviso smart_fit.encaixar_contato_bvh falhou para {pid} "
                        f"({snap_fallback_motivo}); usando fallback BVH",
                        file=sys.stderr,
                    )
            if not usou_smart_fit:
                info_snap = _encaixar_bvh_fallback(peca_obj, alvo_obj, direcao=direcao, folga_m=folga_m)
                if snap_fallback_motivo:
                    info_snap["smart_fit_erro"] = snap_fallback_motivo

        objetos_por_id[pid] = peca_obj
        ordem_objetos.append(peca_obj)
        relatorio_pecas.append(
            {
                "id": pid,
                "papel": p_spec.get("papel", "attachment"),
                "pbr_zona": p_spec.get("pbr_zona", "aco_forjado"),
                "snap": info_snap,
            }
        )

    bpy.ops.object.select_all(action="DESELECT")
    for o in ordem_objetos:
        o.select_set(True)
    bpy.context.view_layer.objects.active = ordem_objetos[0]
    if len(ordem_objetos) > 1:
        bpy.ops.object.join()
    obj_final = bpy.context.active_object
    obj_final.name = "kitbash_assembled"
    _aplicar_transformacao_malha(obj_final)

    # Limpeza e garantia de topologia 100% manifold (nao_manifold == 0)
    bm = bmesh.new()
    bm.from_mesh(obj_final.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    arestas_abertas = [e for e in bm.edges if not e.is_manifold]
    if arestas_abertas:
        bmesh.ops.holes_fill(bm, edges=arestas_abertas, sides=16)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    nao_manifold = sum(1 for e in bm.edges if not e.is_manifold)
    n_verts = len(bm.verts)
    n_tris = len(bm.faces)
    bm.to_mesh(obj_final.data)
    bm.free()
    obj_final.data.update()

    # Apoia o ativo final em Z=0.0 e centraliza X/Y
    mn_f, mx_f = _bbox_mundo(obj_final)
    cx_f = (mn_f.x + mx_f.x) * 0.5
    cy_f = (mn_f.y + mx_f.y) * 0.5
    for v in obj_final.data.vertices:
        v.co.x -= cx_f
        v.co.y -= cy_f
        v.co.z -= mn_f.z
    obj_final.data.update()
    bpy.context.view_layer.update()

    # Material PBR limpo e uniforme para exportacao glTF e turntable QA
    mat = bpy.data.materials.new("kitbash_pbr")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (0.64, 0.67, 0.72, 1.0)
        bsdf.inputs["Metallic"].default_value = 0.55
        bsdf.inputs["Roughness"].default_value = 0.42
    obj_final.data.materials.clear()
    obj_final.data.materials.append(mat)

    grip_info: dict[str, Any]
    if smart_fit_mod is not None and hasattr(smart_fit_mod, "auto_grip_cilindrico"):
        try:
            res_grip = smart_fit_mod.auto_grip_cilindrico(obj_final)
            grip_info = res_grip if isinstance(res_grip, dict) else _auto_grip_fallback(obj_final)
        except (RuntimeError, ValueError, TypeError, AttributeError, ZeroDivisionError) as exc:
            motivo_grip = f"{type(exc).__name__}: {exc}"
            print(
                f"[kitbash_composer] aviso smart_fit.auto_grip_cilindrico falhou ({motivo_grip}); "
                "usando _auto_grip_fallback",
                file=sys.stderr,
            )
            grip_info = _auto_grip_fallback(obj_final)
            grip_info["fallback_motivo"] = motivo_grip
    else:
        grip_info = _auto_grip_fallback(obj_final)
        if smart_fit_erro:
            grip_info["fallback_motivo"] = smart_fit_erro

    out_glb.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(out_glb),
        export_format="GLB",
        use_selection=False,
    )

    saida = {
        "ok": True,
        "out_glb": str(out_glb),
        "vertices": int(n_verts),
        "triangulos": int(n_tris),
        "nao_manifold": int(nao_manifold),
        "snap_folga_m": 0.0015,
        "grip_info": grip_info,
        "pecas_montadas": relatorio_pecas,
    }
    job_out_path.parent.mkdir(parents=True, exist_ok=True)
    job_out_path.write_text(json.dumps(saida, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


def _resolver_plano_explicito_ou_gemini(
    prompt: str,
    pecas_catalogo: list[dict[str, Any]],
    plan_json: str | Path | None = None,
) -> dict[str, Any]:
    from forge3d.providers import cloud_ai

    if plan_json is not None and str(plan_json).strip():
        cand = Path(str(plan_json))
        if cand.is_file():
            texto = cand.read_text(encoding="utf-8")
        else:
            texto = str(plan_json)
        parcial = cloud_ai._parsear_plano_kitbash_json(texto, prompt, pecas_catalogo)
        return {
            "ok": True,
            "modo": "plan_json",
            "modelo": "explicit_plan_json",
            "prompt": prompt,
            "estilo": parcial["estilo"],
            "pecas": parcial["pecas"],
            "pbr_zonas": parcial["pbr_zonas"],
            "licenca": dict(cloud_ai.LICENCAS_CLOUD["gemini_kitbash"]),
        }
    return cloud_ai.planejar_kitbash_gemini(prompt, pecas_catalogo)


def compor_kitbash(
    prompt: str,
    *,
    vault_dir: Path | str | None = None,
    out_glb: Path | str | None = None,
    out_dir: Path | str | None = None,
    plan_json: str | Path | None = None,
    render: bool = False,
    size: int = 320,
    samples: int = 16,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Executa o pipeline completo de composicao Kitbash CC0 + LLM."""
    from forge3d import paths, post
    from forge3d.vault import VaultCC0, sha256_arquivo, validar_licenca_cc0
    from vault_sync_cc0 import seed_local_cc0

    vault = VaultCC0(vault_dir)
    if not vault.listar_ativos():
        seed_local_cc0(vault, gerar_embeddings=True)

    verif = vault.validar_integridade(levantar=True)
    candidatos = vault.buscar_semantico(prompt, top_k=8)
    pecas_malha = [c for c in candidatos if c.get("tipo") in ("kitbash_part", "mesh")]
    if not pecas_malha:
        pecas_malha = vault.listar_ativos(tipo="kitbash_part") or vault.listar_ativos(tipo="mesh")

    plano = _resolver_plano_explicito_ou_gemini(prompt, pecas_malha, plan_json=plan_json)

    pasta_saida = Path(out_dir) if out_dir else (paths.dir_saida() / "kitbash")
    pasta_saida.mkdir(parents=True, exist_ok=True)
    caminho_glb = Path(out_glb) if out_glb else (pasta_saida / "kitbash_assembled.glb")
    if not caminho_glb.is_absolute():
        caminho_glb = (pasta_saida / caminho_glb).resolve()

    mapa_ativos = {a["asset_id"]: a for a in vault.listar_ativos()}
    pecas_job: list[dict[str, Any]] = []
    for idx, p in enumerate(plano["pecas"]):
        pid = str(p.get("id") or "")
        ativo_vault = mapa_ativos.get(pid)
        if ativo_vault is None and pecas_malha:
            ativo_vault = pecas_malha[idx % len(pecas_malha)]
            pid = ativo_vault["asset_id"]
        if ativo_vault is not None:
            validar_licenca_cc0(
                ativo_vault["licenca"],
                origem=ativo_vault["origem"],
                modelo=ativo_vault.get("modelo", ""),
            )
            caminho_peca = ativo_vault["caminho"]
            sha_peca = ativo_vault["sha256"]
        else:
            caminho_peca = ""
            sha_peca = ""

        pecas_job.append(
            {
                "id": pid,
                "papel": p.get("papel", "base" if idx == 0 else "attachment"),
                "snap_para": p.get("snap_para"),
                "escala": p.get("escala", 1.0),
                "pbr_zona": p.get("pbr_zona", "aco_forjado"),
                "direcao_snap": p.get("direcao_snap", [0.0, 0.0, 1.0]),
                "folga_m": float(p.get("folga_m", 0.0015)),
                "caminho": caminho_peca,
                "sha256": sha_peca,
            }
        )

    job_in_path = pasta_saida / "kitbash_job_in.json"
    job_out_path = pasta_saida / "kitbash_job_out.json"
    plan_out_path = pasta_saida / "kitbash_plan.json"

    job_payload = {
        "prompt": prompt,
        "estilo": plano["estilo"],
        "out_glb": str(caminho_glb),
        "snap_folga_m": 0.0015,
        "pecas": pecas_job,
        "pbr_zonas": plano["pbr_zonas"],
    }
    job_in_path.write_text(json.dumps(job_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    plan_out_path.write_text(json.dumps(plano, indent=2, ensure_ascii=False), encoding="utf-8")

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "prompt": prompt,
            "vault_dir": str(vault.vault_dir),
            "integridade_vault": verif,
            "plano": plano,
            "job_in": str(job_in_path),
            "plan_json": str(plan_out_path),
            "out_glb": str(caminho_glb),
        }

    bl_bin = post.binario()
    cmd = [
        bl_bin,
        "--background",
        "--factory-startup",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        "--blender-worker",
        str(job_in_path),
        str(job_out_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
    if proc.returncode != 0 or not job_out_path.is_file():
        raise RuntimeError(
            f"falha na composicao kitbash no Blender (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '')[-400:]}"
        )

    res_blender = json.loads(job_out_path.read_text(encoding="utf-8"))
    if int(res_blender.get("nao_manifold", 1)) != 0:
        raise RuntimeError(f"malha kitbash exportada nao e manifold: {res_blender}")

    digest_glb = sha256_arquivo(caminho_glb)
    relatorio: dict[str, Any] = {
        "ok": True,
        "dry_run": False,
        "prompt": prompt,
        "vault_dir": str(vault.vault_dir),
        "out_glb": str(caminho_glb),
        "sha256": digest_glb,
        "plano": plano,
        "geometria": {
            "vertices": res_blender["vertices"],
            "triangulos": res_blender["triangulos"],
            "nao_manifold": res_blender["nao_manifold"],
            "snap_folga_m": res_blender["snap_folga_m"],
        },
        "grip_info": res_blender["grip_info"],
        "pecas_montadas": res_blender["pecas_montadas"],
    }

    if render:
        import visual_qa_critic

        turntable_png = pasta_saida / f"{caminho_glb.stem}_turntable.png"
        cmd_render = [
            bl_bin,
            "--background",
            "--factory-startup",
            "--python",
            str(RAIZ_REPO / "tools" / "render_preview.py"),
            "--",
            "--turntable",
            str(caminho_glb),
            str(turntable_png),
            "--size",
            str(int(size)),
            "--samples",
            str(int(samples)),
        ]
        proc_r = subprocess.run(cmd_render, capture_output=True, text=True, timeout=240, check=False)
        if proc_r.returncode != 0 or not turntable_png.is_file():
            raise RuntimeError(
                f"falha ao renderizar turntable do kitbash (rc={proc_r.returncode}): "
                f"{(proc_r.stderr or proc_r.stdout or '')[-400:]}"
            )
        qa_rel = visual_qa_critic.avaliar_turntable_png(turntable_png)
        relatorio["turntable_png"] = str(turntable_png)
        relatorio["qa_visual"] = qa_rel

    return relatorio


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if "--" in raw_argv:
        pos_sep = raw_argv[raw_argv.index("--") + 1 :]
        if pos_sep and pos_sep[0] == "--blender-worker":
            return _executar_worker_blender(Path(pos_sep[1]), Path(pos_sep[2]))
    if raw_argv and raw_argv[0] == "--blender-worker":
        return _executar_worker_blender(Path(raw_argv[1]), Path(raw_argv[2]))

    parser = argparse.ArgumentParser(
        description="Compositor 3D Kitbash guiado por Gemini e Vault CC0"
    )
    parser.add_argument("--prompt", required=True, help="Descricao do ativo a montar via kitbash CC0")
    parser.add_argument("--vault-dir", type=Path, default=None, help="Diretorio do Vault CC0")
    parser.add_argument("--out-glb", type=Path, default=None, help="Caminho do arquivo .glb de saida")
    parser.add_argument("--out-dir", type=Path, default=None, help="Pasta de trabalho e artefatos de saida")
    parser.add_argument("--plan-json", default=None, help="Caminho ou JSON inline de plano de montagem")
    parser.add_argument("--render", action="store_true", help="Renderiza turntable 2x2 e roda visual_qa_critic")
    parser.add_argument("--size", type=int, default=320, help="Resolucao por vista no turntable (padrao: 320)")
    parser.add_argument("--samples", type=int, default=16, help="Samples Cycles no turntable (padrao: 16)")
    parser.add_argument("--dry-run", action="store_true", help="Gera plano e job JSON sem invocar o Blender")
    parser.add_argument("--json", action="store_true", dest="em_json", help="Imprime relatorio em JSON")
    args = parser.parse_args(raw_argv)

    try:
        relatorio = compor_kitbash(
            args.prompt,
            vault_dir=args.vault_dir,
            out_glb=args.out_glb,
            out_dir=args.out_dir,
            plan_json=args.plan_json,
            render=args.render,
            size=args.size,
            samples=args.samples,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        if args.em_json:
            print(json.dumps({"ok": False, "erro": str(exc)}, ensure_ascii=False))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    if args.em_json:
        print(json.dumps(relatorio, indent=2, ensure_ascii=False))
    else:
        print(f"KITBASH_OK {relatorio['out_glb']} (dry_run={relatorio['dry_run']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
