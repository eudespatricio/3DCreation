# CONTINUAR — handoff de sessão

**Data:** 20/11/2026 · **`v0.9.5`: P0–P6, Ondas A–D, Ondas 0–3 (`M1–M5`) e Portão E2E `M6` fechados.** Contratos
correntes `spec@6` e `manifest@6` (`D94–D129`; `@1`–`@5` compatíveis na leitura). Entrega game-ready
para **Roblox R15** (`_sequencia_xml` `Pose` aninhada, 15 partes watertight, `export-r15`
mesh/segmentada `Motor6D` + `SurfaceAppearance` 4 canais, `--strip-embedded-textures`, `G12–G14`) e
**Godot 4** (`ORMMaterial3D=1.0`, `ResourceLoader.load()` + sidecars `.png.import`/`.glb.import`,
guarda idempotente `forge3d_post_imported`, `BoneMap` `Root`/`UpperChest`, `UV2`+`GI_MODE_STATIC`,
LOD sem texturas duplicadas, `UCX_` agrupado/preservado, 17 clipes), mais **4 vistas Gemini + bake Cycles**
(sem `fal.run`), `TRELLIS.2-4B`/`Pixal3D` MIT, **G15** e hardening **G1–G11** + `verify` G11 + zero
`except` silencioso. **781 verdes + 1 GPU (skip)** na suíte completa (**684** não-E2E + **97/97** E2E
Tiers 1–4); `ci.sh` e `ci_verify.sh` verdes (`exit=0`).

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
  normal pós-suavização), `tools/colab_trellis_worker.py` (`TRELLIS.2-4B`/`Pixal3D` MIT → `spec@6`),
  `quadriflow`/`smart_fit`/boss rig e Gate **`G15`** (`qc_fidelidade.py`, `visual_qa_fidelidade.py`).
- **Onda 3 — QC G1–G11, Limpeza & Governança (`M5`, `D128`)** — 9 pontos cegos `G1–G10` fechados (`qc_geom`,
  `qc_orientacao`, `qc_uv`, `qc_midia`, `qc_gates`, `qc_skin`, `qc_gates_ext`), `verify` reexecutando `G11`
  (`verify_g11.py`), zero `except Exception` silenciosos via AST (`tests/test_f27_silent_except.py`), UV/orientação
  em `blender/{modular_armor.py,extrude_2d.py,postprocess_normals_uv.py}` e `PIPELINE_VERSION = "0.9.5"`.

## Números medidos nesta máquina

| Medida | Valor |
|---|---|
| Suíte completa (`pytest`) | **781 verdes + 1 GPU (skip)** em **782 testes** (**684** não-E2E + **97/97** E2E Tiers 1–4) |
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
(`97/97` E2E Tiers 1–4, Opção A Tier 5 dispensado, `GAP-050/051/062` fechados, `ci.sh`/`ci_verify.sh` `exit=0`)**.

## Aberto

`Q1` (D72) e `Q7` (D73) fechadas; `Q8` permanece em `DECISOES.md` §4. Plano P0–P6 e portões `M1–M6`
completos (D83, D129); lacunas de backlog (`GAP-052`–`GAP-063`) vivem em `docs/gaps.md` e §Depois da
P6 de `docs/roadmap.md`.

## Próximos passos — em ordem

| # | Ação | Custo | Ataca |
|---|---|---|---|
| **1** | Validação final nos projetos consumidores (Studio Play G14 `tools/r15_play_g14.py` e Godot 4 `tools/godot_visual_qa.gd`) | 1 sessão manual | entrega |
| **2** | Republicar destinos legados para `manifest@6`/`v0.9.5` após validação final | minutos | consistência |

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

python -m pytest -q                            # 781 verdes + 1 GPU (skip)
python -m pytest tests/e2e -m "not gpu" -v     # 97/97 E2E Tiers 1–4 verdes
bash tools/ci.sh                               # pytest não-Blender + ruff + mypy + contexto + P0
bash tools/ci_verify.sh                        # Blender 4.2.0 + verify + Godot headless QA
bash tools/ci_dist.sh                          # wheel 0.9.5 em venv limpo
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

> **Estado**: `v0.9.5` — P0–P6, Ondas A–D, Ondas 0–3 (`M1–M5`) e Portão E2E **`M6`** (`D125–D129`) fechados.
> `781` testes verdes (`+1` GPU skip; `97/97` E2E Tiers 1–4), `ci.sh`, `ci_verify.sh`, `ruff`/`mypy`/`check-p0`/`conformidade` verdes.
> **Próximo passo**: validação manual opcional nos projetos consumidores (`r15_play_g14.py` / `godot_visual_qa.gd`) e republicação de destinos legados.
> Sessão no Windows? Leia `AGENTS.md` §Ambiente **antes** de editar arquivo.
