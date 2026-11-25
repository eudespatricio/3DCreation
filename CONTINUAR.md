# CONTINUAR — handoff de sessão

**Data:** 25/11/2026 · **`v0.9.12` (Ondas 7–9 ✔): Rigging R15/Godot ~14° assada, paridade Godot 4 (sidecars emissive, 22 clipes, `plugin.cfg 0.8.0`) e Throughput (`pipeline_overlap`, `steps=12` standard, warm worker TRELLIS.2 e diagnóstico de cache no `plan`).** Contratos `spec@6` e `manifest@7` (`PIPELINE_VERSION = "0.9.12"`, `@1`–`@6` compatíveis na leitura). Entrega game-ready para **Roblox R15** (rest-pose ~14° assada pós-Cycles s/ perda de UV/pesos, `Pose` aninhada c/ ground-clamp, `--modo-rig bone` s/ `partes[]` + `rig.ancoras`, `export-anim --modo-rig --manifesto`, `StreamingEnabled=false`, `SurfaceAppearance`, `G12–G14`, `G16`), **Godot 4** (`ORMMaterial3D=1.0` + `emissive_tex` sidecar/embutido, `.png.import` linear/sRGB, `fix_silhouette`, `BoneMap` 56 ossos, `UV2`+`GI_MODE_STATIC`, `UCX_`, 22 clipes) e **i23d** (`TRELLIS.2-4B`).

Verificação rápida: `.venv/bin/python -m pytest -m "not gpu and not blender" -q` e `bash tools/ci.sh`.

---

## O que é este projeto

**Forge3D** transforma um **lote declarativo** (YAML/JSON) em assets 3D verificáveis — `.glb` com
escala, pivô, LOD, colisão, rig, QC e manifesto — e publica de forma atômica num destino autorizado.

Requisito duro do operador (10/11/2026): **o utilitário é independente de projeto**. Não lê config do
diretório onde roda, não escreve fora do próprio estado, não importa código de jogo (D25).

## Onde estamos, por fase

| Fase / Onda | Estado | Entrega |
|---|---|---|
| **P0–P1** | ✔ | arquitetura, `spec@1`/`spec@2`, `manifest@1`, allowlist (D23), estado central (D24), `blocky`/`import` |
| **P2–P3.5** | ✔ | R15 16 ossos/upload Open Cloud/`manifest@2` (D62), i23d TripoSR + bake Cycles + SD1.5 concept + híbrido A/B |
| **P4–P5** | ✔ | `spec@3` WFC 10 setores/1 draw call (D74–D79); animação `idle` 24 fps no `.glb`/`.rbxlx` e LOD por silhueta (D66–D71) |
| **P6** | ✔ | `migrate` (D80), `verify` no CI com Blender 4.2.0 pinado por sha256 e wheel instalável (D81) |
| **Ondas A–D (`v0.6.0`–`v0.9.4`)** | ✔ | `spec@4..@6`/`manifest@4..@6`, `godot4-aa`/`roblox-aa-80`, G11, `smart_fit`, Vault CC0, Pixal3D MIT, `referencia_estilo`, `partes[]`/`split_por_ossos.py` (D85–D124) |
| **Ondas 0–3 (`M1–M5`, `v0.9.5`)** | ✔ | CI/P0 + 54 RED (M1), Roblox R15 + G12–G14 (M2/D125), Godot 4 (M3/D126), 4-vistas/Cycles/TRELLIS.2/G15 sem `fal.run` (M4/D127), G1–G11 + `verify` G11 + zero `except` silencioso + `0.9.5` (M5/D128) |
| **M6 (E2E Tiers 1–4)** | ✔ | **97/97** E2E (`Tiers 1–4`), `GAP-050`/`051`/`062` fechados, `UCX_` preservado, `ci.sh`/`ci_verify.sh` verdes (`D129`; Tier 5 dispensado por Opção A) |
| **Onda 1 (`v0.9.6`–`v0.9.8`)** | ✔ | `TRELLIS.2-4B` local (`tools/trellis2_infer.py`, `BF16/512`), `EMIT` PBR nativo, `Solidify+Voxel+Shrinkwrap`, fallback UV0, remoção Colab (`D130`–`D133`) |
| **Onda 2 (`v0.9.9`)** | ✔ | `manifest@7`, R15 rígido `partes_combinadas` + `Motor6D`, coerência geodésica e Gate `G16` (`D134`) |
| **Onda 3 (`v0.9.10`)** | ✔ | `F-01`–`F-08`: marcos/skinning/R15 split, roll sagital + `F-08` caimento natural, emissive/AO PBR, `StreamingEnabled=false`, E2E 3 bosses (`D135`) |
| **Onda 4 (`v0.9.11`)** | ✔ | `C1` PBR nativo/`delight`, `C2`/`C2b` casca dupla + UV/Quadriflow, Opção 1 `vista_back` + `C2c` projeção frontal rosto, `C3`/`C3b` R15 contínuo (`D136`) |
| **Ondas 5–7 (`v0.9.11`)** | ✔ | Ondas 5–6 (`EMIT`/UV/QC/`GAP-052..055/060..062`) + Onda 7 (rest-pose ~14° assada, presets `seed`, `idle` aterrado, `walk`/`run` aduzidos, `export-r15 --modo-rig bone`, `GAP-064/065/067` fechados, `GAP-066` mitigado) |
| **Onda 8 (`v0.9.11`)** | ✔ | Godot 4 parity: sidecar `_emissive.png` em `post_import_materials.gd`/`sync_godot*.py`, `.png.import` linear/sRGB, 22 clipes (`8` cíclicos / `14` não-cíclicos), `plugin.cfg` `0.8.0` e E2E Blender→Godot 4.7.2 |
| **Onda 9 (`v0.9.12`)** | ✔ | Throughput & Release `0.9.12`: overlap GPU/CPU (`pipeline_overlap.py`), `steps=12` standard, warm worker (`trellis2_worker.py`) e diagnóstico de miss no `plan` (`cache_diag.py`) |

## O que foi entregue nesta janela

- **Baseline P0–P6 e `v0.6.0`–`v0.9.4` (D1–D124)** — rotas `blocky`/`import`/`mesh`/`modular`,
  contratos `spec@6`/`manifest@6` (`partes[]`, `rig`, `animacoes`, `requisicao`, `referencia_estilo`),
  perfis `godot4-aa`/`roblox-aa-80` + Gate `G11`, `smart_fit.py`, Vault CC0 + `kitbash_composer.py`,
  Pixal3D MIT (D112), `split_por_ossos.py` (D124) e correções P0 `v0.9.3` (D114–D122).
- **Onda 0 (M1)** — higiene de `tools/check-p0.py`, `tools/ci_verify.sh` (`tools/godot_rig_axes_check.gd`),
  `doctor.py` (`spec@1..@6`, `manifest@1..@6`) e 54 testes RED independentes (`test_red_r2..r5_*`).
- **Onda 1A — Roblox R15 (`M2`, `D125`)** — `_sequencia_xml` com árvore aninhada `<Item class="Pose">`
  (`Weight=0` no `HumanoidRootPart`, `deslocamento_m / 0.28`), segmentação R15 15 partes watertight em
  `blender/split_por_ossos.py` + `segmentacao.py` (Y-up `(x,z,-y)`), `export-r15` em rota `mesh`
  (`15 MeshPart + 15 Motor6D` + `SurfaceAppearance` 4 canais), remoção de swap Y/Z falso em `bbox_m` e
  dupla divisão `/ 0.28` em sockets, `upload.py` limpando `BIN` (`--strip-embedded-textures`),
  `CAMPOS_CANONICOS_ITEM` + `sync --rojo-lua` com ledger isolado, e `G12–G14` + `tools/r15_play_g14.py`.
- **Onda 1B — Godot 4 (`M3`, `D126`)** — `ORMMaterial3D` (`metallic=1.0`, `roughness=1.0`),
  `ResourceLoader.load()` + sidecars `.png.import`/`.glb.import`, guarda idempotente `forge3d_post_imported`
  (sem `_source_queue`), `BoneMap` (`Root`/`UpperChest`) + sockets Y-up, `export_tangents=True`, `UV2` +
  `GI_MODE_STATIC`, LODs sem texturas embutidas duplicadas + distâncias por AABB, `UCX_` agrupado, cápsula
  quadrúpede, roll de asas, 17 clipes (`slash_combo`, `cast`, `bite`) e `godot_visual_qa.gd`/`godot_draw_calls_bench.gd`.
- **Onda 2 — Qualidade Visual & G15 (`M4`, `D127`)** — sub-rotas explícitas em `mesh.py` (sem descarte
  silencioso de `prompt`/`origem`; `template_body.py` encaixado), 4 vistas Gemini Nano Banana 2.1 +
  `referencia_estilo` (zero `fal.run`), bake 4-vistas Cycles com cage real (sem Sobel/Taubin cumulativo/256px;
  normal pós-suavização), `tools/colab_trellis_worker.py` (`TRELLIS.2-4B`/`Pixal3D` MIT → `spec@6`; removido em D133),
  `quadriflow`/`smart_fit`/boss rig e Gate **`G15`** (`qc_fidelidade.py`, `visual_qa_fidelidade.py`).
- **Onda 3 — QC G1–G11, Limpeza & Governança (`M5`, `D128`)** — 9 pontos cegos `G1–G10` fechados (`qc_geom`,
  `qc_orientacao`, `qc_uv`, `qc_midia`, `qc_gates`, `qc_skin`, `qc_gates_ext`), `verify` reexecutando `G11`
  (`verify_g11.py`), zero `except Exception` silenciosos via AST (`tests/test_f27_silent_except.py`), UV/orientação
  em `blender/{modular_armor.py,extrude_2d.py,postprocess_normals_uv.py}` e `PIPELINE_VERSION = "0.9.5"`.

- **Onda 1 `v0.9.8` (`D132`)** — skip `BEVEL+SUBSURF` `>60k` tris (`bake_pbr_config.py`),
  `SOLIDIFY+VOXEL+SHRINKWRAP` (`postprocess_repair.py`), bake PBR nativo `EMIT` (`bake_pbr_nativo.py`),
  `frente_origem="-Y"` (`mesh_i23d.py`, `postprocess_canon.py`, `postprocess_bruto.py`), fallback angular
  UV0 (`tem_uv_sobreposta`) e Kragor + Iron Ram aprovados (`G1–G15` ok: Kragor `15.760` tris, `uv=0,3431`,
  `DEF-06` `8,21×/230`; Iron Ram `15.758` tris, `0` NM, `uv=0,3268`, `G15` `0,8669`/`0,8803`, `pbr_nativo=true`,
  `DEF-06` `20,62×/901`).
- **Integração local `TRELLIS.2-4B` (`D133`)** — PoC local na RTX 3060 6 GB (`BF16/512 tuned`, `low_vram=True` + 24 GB WSL2: `301,01 s`, `4488 MiB` VRAM, `87.839` faces, `11,9×` vs Colab T4; `mv4` 4-vistas descartada após rasgos em `604,65 s`) promovido para `~/.cache/forge3d/trellis2` com `tools/trellis2_infer.py`, `mesh_diag.VERSAO="0.1.11"` (D6 `tr2<sha8>`), fail-fast sem fallback quando `FORGE3D_MODELO_MESH=trellis2`, remoção de `tools/colab_trellis_*.py` e HTTP `/jobs`; `postprocess_canon.py` (eixo fixo com `frente_origem="-Y"` sem tombar criatura larga) e `postprocess_bruto.py` (Cycles `EMIT` + fallback UV0).
- **Onda 2 `v0.9.9` (`D134`)** — `schemas/manifest.v7.schema.json` (`manifest@7`, `partes_combinadas`, `G1–G16`), `export-r15 --model-id` `Motor6D` rígido padrão, coerência geodésica e Gate `G16` validados em Kragor e Iron Ram.
- **Onda 3 `v0.9.10` (`D135`)** — consolida `F-01`–`F-08` sem bump em `manifest@7`: poda axila + trava pescoço/dorsal (`autorig_marcos_tronco.py`, `autorig_marcos.py`, `autorig_grafo.py`, `autorig_pesos_*.py`), `qc_roblox_partes.py` (`0` antebraço em perna), roll sagital + sync `qc_orientacao.py` (`F-05`), caimento gravitacional natural (`autorig_pose_natural.py`, `autorig_anim_sockets.py`, `animacao_pose.py`, `rbx_anim.py`), emissive GLB + lift `_baseColor` + AO `0,45` + `TRELLIS` 1-vista (`bake_pbr_emissive.py`, `bake_pbr_nativo_blend.py`), `adiar_reparo_high > limite_triangulos` (`postprocess_bruto.py`), `<bool name="StreamingEnabled">false</bool>` e `run` 31 kf. E2E `--no-cache` + `verify` verdes (`Tomb Warden` `7,3152×`, `Iron Ram` `G12=0,0mm` / rígido `1,0×` / skinned `6,9853×` / `.rbxlx`, `Kragor` `6,3406×`), DeepSeek review (`GAP-065`).
- **Onda 4 `v0.9.11` (`D136`)** — `C1` PBR nativo/`delight_pbr` sem falso metálico; `C2`/`C2b` `filtrar_casca_interna_high` + solda in-place Quadriflow + UV cabeça `1,50`; Opção 1 `vista_back` Gemini + `C2c` projeção frontal `+Y` para olhos/sobrancelhas; `C3`/`C3b` âncora ombro + `arm_hip_block_z` (`autorig_pesos_limites.py`), `mesh_diag.VERSAO="0.1.12"`.

- **Onda 7 (`v0.9.11`)** — `rig.postura` nos perfis (`roblox-*`: `natural_relaxada` 14° pós-skin A-pose 45°; `godot4*`: `apose` + `fix_silhouette/enable`), `assar_pose_rest_natural` (`blender/autorig_pose_natural.py`, `postprocess_export_pipe.py` c/ `_g15_apose_ref.glb`), modularização `animacao.py`/`animacao_motores.py`/`animacao_presets.py` (5 presets por `seed`, `idle` sem Z-roll e aterrado, `walk`/`run` adução Z de quadril + paridade Bone/Motor6D em `rbx_anim.py`), `export-r15 --modo-rig bone` s/ `partes[]` + `rig.ancoras` em `SkinnedMesh` + `export-anim --modo-rig --manifesto`, e fechamento de `GAP-064`/`GAP-065`/`GAP-067` (#4/#5) + mitigação de `GAP-066`.
- **Onda 8 (`v0.9.11`)** — `post_import_materials.gd` com `emissive_tex` opcional em `_processar_material` (compatível c/ 5 args) e descoberta `_emissive.png`; `sync_godot.py` emitindo `"emissive"` em `Forge3DAssets.gd`; `sync_godot_sidecars.py` com `.png.import` linear (`process/hdr_as_srgb=false` em `_orm/_roughness/_metalness/_ao`) + 22 clipes sincronizados com `post_import.gd`/`godot_anim_check.gd`/`godot_visual_qa.gd`; `plugin.cfg` `0.8.0` e E2E Blender→Godot 4.7.2 (`tests/test_onda8_godot4.py`).
- **Onda 9 (`v0.9.12`, `D137`)** — bump `PIPELINE_VERSION = "0.9.12"`, overlap 1-slot GPU/CPU (`pipeline_overlap.py`, `post.py` `env_extra`, `--overlap`/`--no-overlap`), `steps=12` em `standard`/props (`mesh_trellis.py`, `mesh.py`), warm worker residente (`tools/trellis2_worker.py`, `mesh_trellis_worker.py`, `--warm-worker`) e diagnóstico de cache miss no `plan --json` (`cache_diag.py`, `.por_id` ignorado no `gc.py`).

## Números medidos nesta máquina

| Medida | Valor |
|---|---|
| Suíte & E2E (`v0.9.11`) | `ci.sh` (`exit=0`) + `v0.9.11`/`v0.9.10`/Blender verdes; NPC R15 Pass A (`512 BF16`) `11.820` tris, `met=0,0015`, `casca=-21.144`, `G16 walk=3,67×` (`verify exit=0`); Pass B (`1024_cascade Q8_0`) reprovado (`walk=14,79×`) |
| Suíte Onda 3 (`v0.9.10`) | `bash tools/ci.sh` (`exit=0`) + `test_v0910_fixes` (`10/10`) + `test_v0910_blender` (`6/6`) + `test_v099_def06_g16` (`11/11`) + `test_autorig_geodesico` (`6/6`) verdes |
| E2E 3 Bosses (`v0.9.10` `--no-cache`) | `Tomb Warden` (`7,3152×`/`0,009032`), `Iron Ram` (`G12=0,0mm`, rígido `1,0×`, skinned `6,9853×`/`0,009227`, `export-r15`), `Kragor` (`6,3406×`/`0,008434`): todos `verify exit=0` |
| Descoberta RED→GREEN (`R2`–`R5`) | **54/54 verdes** (`16/16` R2 Roblox, `11/11` R3 Godot, `11/11` R4 Visual, `16/16` R5 QC) |
| Suíte E2E (`tests/e2e/`) | **97/97 verdes** (`Tier 1: 41/41` · `Tier 2: 44/44` · `Tier 3: 6/6` · `Tier 4: 6/6`; `D129`) |
| Hardening M5 (`F26`/`F27`/Blender UV) | `test_f27_silent_except` `7/7` · `test_qc_f26_hardening` `10/10` · `test_invariantes_e2e` `12/12` · `80/80` `modular_armor` + `15/15` `smart_fit` (`topo=(0,0,0)` `uv=(0,0,0,0)`) |
| Estáticos & CI (`v0.9.5`) | `ruff` `0` erros · `mypy src` `0` erros · `check-p0.py`, `conformidade.py`, `check-contexto.sh`, `ci.sh`, `ci_verify.sh`, `verify` tamper `exit=3` e Godot 4.7.2 (`GODOT_POST_IMPORT_OK`, `RIG_AXES_OK`) todos `exit=0` |
| AA `v0.9.1` (`lote_13`–`lote_15`) | `godot4-aa` `5/5` (`53.188` tris / `24` dc == Godot Vulkan `24` / `47,67 MB`) · `roblox-aa-80` `3/3` (`16.688` tris / `14` dc `[estimado]`) · `lote_13` `10/10` (`15.516` tris / `10` dc) |
| Showcase `v0.8.0` (`v08_showcase`) | 8 itens `manifest@5` (`nao_manifold=0`, `GODOT_VISUAL_QA_OK count=8`, `11.892`–`15.920` tris) |
| P4 layout 5x2 + Kit/LOD | 10 setores `24–48` tris (`1` mesh/`1` mat, `nao_manifold=0`); LOD mesh `0,993` bule / `0,980` corpo |
| Roblox R15 (Studio MCP / client) | rig `.rbxlx` `6,6071 × 2,7086 × 1,5196` studs == package (`134628989553440`); anim `116049702979137` (`Core`, Head `0,066–0,095` studs); `PreloadAsync` OK |
| Repo por UNC (sessão Windows) | criar/apagar/`mv` OK; **modificar existente falha** (`GetFileSecurityW EIO`); 200 arquivos: **906 ms** vs 12 ms em ext4 |

## Decidido (não reabrir)

`D3` CLI-only · `D9` QC sem bypass · `D11` GPU serializada · `D18` licença é gate · `D23` allowlist ·
`D24` estado central · `D25` isolamento · `D26` núcleo leve · `D27` SF3D encerrado · `D32` verify G1–G9 ·
`D35` concept interno · `D47` pivô por bone head · `D48` `.rbxlx` nativo · `D49–D51` Open Cloud ·
`D52–D53` colisor convex hull · `D54` CLIP 77 · `D55` rembg auto · `D57` agentapi · `D58` empunhadura 20% ·
`D59` `flock` GPU · `D60` Studio MCP · `D62–D69` escala `manifest@2`, hull nuvem, 1 mm/m, `idle` retarget,
`manifest@3`, Part Y/Z, `Priority=Core` · `D71–D84` LOD silhueta, `forge3d` fica, LFS, WFC/P4, I15, WSL/UNC,
`migrate`, CI Blender 4.2.0, doc testada, sola · `D85–D93` `sync`, qualidade 3D, request contract, armadura
modular, ondas A–D, eixos · `D94–D102` `spec@5`, CC0 camadas, AA props/vidro, dragão, Godot zero-click,
Interactions + TRELLIS MIT · `D103–D113` `spec@6`, G11, Cycles High→Low, `smart_fit`, Vault CC0, `plan`
calibrado, `GAP-019`, Pixal3D MIT, `referencia_estilo` · `D114–D124` B23/B24, fonte única esqueleto,
`{asset}_concept.json`, `partes[]`/B25/`split_por_ossos.py` · **`D125` Onda 1A Roblox R15 (`Pose` aninhada,
15 partes watertight, `export-r15` mesh, `BIN` strip, `G12–G14`)** · **`D126` Onda 1B Godot 4 (`ORMMaterial3D`,
sidecars, `forge3d_post_imported`, `BoneMap`, `UCX_`, 17 clipes)** · **`D127` Onda 2 Visual (sub-rotas
explícitas, 4 vistas Gemini/Cycles, zero `fal.run`, `TRELLIS.2-4B`/`Pixal3D`, `G15`)** · **`D128` Onda 3
(`G1–G11`, `verify` `G11`, zero `except` silencioso, `PIPELINE_VERSION = "0.9.5"`)** · **`D129` Portão E2E `M6`
(`97/97` E2E Tiers 1–4, Opção A Tier 5 dispensado, `GAP-050/051/062` fechados, `ci.sh`/`ci_verify.sh` `exit=0`)** · **`D130` Hardening `v0.9.6`** · **`D131` Fine-Tune `v0.9.7`** · **`D132` Onda 1 `v0.9.8` (`TRELLIS.2-4B` `o_voxel`, `EMIT`, `Solidify+Voxel+Shrinkwrap`, fallback UV0)** · **`D133` `TRELLIS.2-4B` local (`tools/trellis2_infer.py`, `BF16/512`, zero Colab)** · **`D134` Onda 2 `v0.9.9` (`manifest@7`, R15 rígido `Motor6D`, coerência geodésica, `G16`)** · **`D135` Onda 3 `v0.9.10` (`F-01`–`F-08` feedback Godot/Roblox + caimento natural dos braços, `GAP-065`)** · **`D136` Fine-tuning `v0.9.11` (`C1`–`C3b`, Opção 1 `vista_back`, `C2c` projeção frontal, `GAP-066`–`GAP-067`)**.

## Aberto

`Q1` (D72) e `Q7` (D73) fechadas; `Q8` permanece em `DECISOES.md` §4. Plano P0–P6 e portões `M1–M6`
completos (D83, D129); lacunas de backlog (`GAP-052`–`GAP-067`) vivem em `docs/gaps.md` e §Depois da
P6 de `docs/roadmap.md`.

## Próximos passos — em ordem

| # | Ação | Custo | Ataca |
|---|---|---|---|
| **1** | Priorizar itens de backlog em `docs/gaps.md` (`GAP-004..068`) conforme demanda dos projetos consumidores | sob demanda | débitos pós-`v0.9.12` |
| **2** | Avaliar E2E GPU opcional de lote com `--overlap --warm-worker` e `steps=12` quando hardware NVIDIA livre | sob demanda | benchmark em campo `v0.9.12` |

## Comandos

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate

forge3d doctor
forge3d validate examples/lote_01.yaml
forge3d plan examples/lote_13_scene_budget_aa.yaml --scene-budget
forge3d run examples/lote_01.yaml              # blocky, sem GPU
forge3d run examples/lote_09_r15.yaml          # R15 blocky, glb em studs
forge3d export-r15 examples/lote_09_r15.yaml --item personagem.r15.guard.01
forge3d verify ~/.local/state/forge3d/saida/r15
forge3d upload-model <glb> --creator-id 11966727684 --dry-run --strip-embedded-textures
forge3d gc --dry-run --manter-dias 30

python -m pytest -m "not gpu and not blender" -q
python -m pytest tests/test_v099_def06_g16.py -v
bash tools/ci.sh                               # pytest não-Blender + ruff + mypy + contexto + P0
bash tools/ci_verify.sh                        # Blender 4.2.0 + verify + Godot headless QA
bash tools/ci_dist.sh                          # wheel 0.9.10 em venv limpo
bash tools/check-contexto.sh && python tools/check-p0.py && python tools/conformidade.py
python tools/r15_play_g14.py --help            # harness Play Studio G14
godot --headless --path tools/godot_project --script "$PWD/tools/godot_anim_check.gd" -- <glb> idle
```

## Armadilhas pagas (não repetir)

1. **Repo em ext4 visto por UNC no Windows** (`AGENTS.md` §Ambiente): criar/apagar/`mv` funcionam; modificar
   existente falha (`GetFileSecurityW EIO`); em lote UNC é ~75× mais lento → rode comandos no WSL.
2. **`convex_hull` do bmesh herda faces** → hull sobre nuvem de pontos (D64) com tolerância 1 mm/m (D65).
3. **Mudou saída? Suba `PIPELINE_VERSION`** (D6), senão o cache serve artefato velho.
4. **Roblox**: 1 unidade glTF = 1 stud (`escala_saida`, D62); não faça swap Y/Z falso em `bbox_m` nem dupla
   divisão `/ 0.28` em sockets; no `.rbxlx`, tamanho de Part permuta `(x, z, -y)` (D68) e `Pose` é aninhada com `Weight=0` no `HumanoidRootPart`.
5. **Studio**: Command Bar colapsa multi-linha → use `tools/mcp_studio.py` (`FORGE3D_STUDIOMCP`).
6. **Joelho e cotovelo** giram em sentidos opostos; **Diffusers** trunca prompt em 77 tokens.
7. **Blender `--factory-startup`** carrega o cubo default → chame `read_factory_settings(use_empty=True)`.
8. **Godot 4**: `ORMMaterial3D` com `orm_texture` exige `metallic=1.0` e `roughness=1.0`; `PostImport.aplicar()`
   exige guarda `forge3d_post_imported` para evitar `StaticBody3D` duplicado.
9. **QC G3/G4/G6**: G3 rejeita UV colapsada/sobreposta; G4 exige normal OpenGL `+Y` (`>= 32px`); G6 exige peso
   não-raiz e deformação real em pose (30° LBS).

## Como retomar

> **Estado**: `v0.9.12` (**Ondas 7–9 completas**): postura relaxada ~14° no `roblox-*`, `godot4*` em A-pose + `fix_silhouette`, `idle` aterrado, `walk`/`run` aduzidos, `SkinnedMesh` R15 `--modo-rig bone`, paridade Godot 4 (`0.8.0`, 22 clipes, `_emissive.png`), pipeline 1-slot overlap, `steps=12` standard, warm worker TRELLIS.2 e diagnóstico de miss no `plan` (`spec@6`, `manifest@7`, `PIPELINE_VERSION="0.9.12"`).
> **Próximo passo**: Priorizar débitos pós-`v0.9.12` em `docs/gaps.md` conforme demanda dos jogos consumidores.
> Sessão no Windows? Leia `AGENTS.md` §Ambiente **antes** de editar arquivo.
