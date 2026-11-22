---
name: forge3d-blender-pitfalls
description: >-
  Use when editing Blender 4.2 bpy scripts (UV unwrap, lightmap, PBR bake,
  convex colliders, R15 bone split, geodesic skinning, G16 deformation),
  running headless Blender diagnostics, or editing Forge3D multiview/i23d
  providers and QC gates in 3DCreation to avoid measured regressions and slow loops.
---

# Forge3D Blender 4.2 & Multiview Pitfalls

## 1. Blender `bpy` RNA Use-After-Free (`mode_set`)
- `bpy.ops.object.mode_set(mode="EDIT" | "OBJECT")` realoca arrays `CustomData` em C e invalida referências Python anteriores (ex.: `lm = obj.data.uv_layers.new(...)`).
- **Regra**: capture strings/primitivos (`nome_lm = lm.name`) **antes** de `mode_set()` ou rebusque por nome após voltar a `OBJECT`. Caso contrário, acessar `lm.name` explode com `UnicodeDecodeError` por memória liberada.

## 2. UV Unwrap & Cobertura (`G3`)
- `smart_project` com `angle_limit=25°` estilhaça malhas i23d (~16k tris) em milhares de micro-ilhas (`uv_area_total < 1%`).
- **Regra**: mantenha `angle_limit_graus=66.0`, `margem=0.004` + `uv.pack_islands()`; `G3` exige `uv_area_total >= 0.20` para malhas com `>= 200` tris UV0 (excluindo materiais `armor_*`).

## 3. Colisor Convexo (`G7`) & Escala Roblox (Studs)
- **Nunca** execute `bmesh.ops.dissolve_degenerate` **após** `bmesh.ops.convex_hull` (reintroduz concavidades).
- Escale `dist_solda` proporcionalmente à diagonal `diag_n` (`max(0.015, diag_n * 0.03)`) **sem** teto fixo em metros (ex.: `0.06` falha em escala de studs ~19 u).

## 4. Split R15 (`G12`/`G13`)
- Interpenetração ocorre também entre pares **não pai-filho** (ex.: `RightHand × RightUpperLeg`). `bisectar_sobrepostos` deve cobrir todos os pares com sobreposição de AABB, só comitando se estanque (`>= 4` faces) e sem mover cabeças de osso (`G13`).

## 5. 4-Vistas Gemini, `delight` & Chave de Cache (`D6`)
- Remova frases conflitantes (`"front view"`) nas vistas `back/left/right`, detecte sheets multi-figura (`_detectar_multiplas_figuras`), rode recorte 2D + `delight` em todas as vistas e priorize `origem_textura` (`input_delit.png` com alpha) para `front` mesmo em `vistas=4`.
- Sempre proteja acesso a `img.pixels` contra comprimento zero/`RuntimeError`.
- Qualquer nova variável de ambiente que altere saída de provider remoto (`FORGE3D_I23D_ENDPOINT`, modelo, `FORGE3D_I23D_SIMPLIFY`) **deve** entrar na chave de cache `D6`.

## 6. Skinning Geodésico, Pauldrons Soldados (`TRELLIS.2-4B`) & Gate `G16`
- **Costuras distantes (`autorig_pesos_coerencia.mediar_costuras_distantes`)**: nunca injete peso no ancestral `anc` quando `anc in (di, dj)` (extremos da aresta) — isso apenas desloca o degrau 1 anel (`10,16×` → `2,20×` ao restringir).
- **Fronteiras anatômicas em malhas i23d soldadas**: cortes rígidos `continue` em `chest_z_max`/`neck_z_max`/`head_z_min`/`head_max_x` criam penhascos `> 20×` em ombreiras/golas soldadas (`Kragor`). Use rampas suaves de distância, mantenha guarda Z de `LowerArm`/`Hand` acima de `shoulder_z - 0.02*h`, e restrinja altura de colarinho `Chest` a `abs_x > head_max_x * 0.9` (não `neck_max_x * 0.8`, que vaza em orelhas/bochechas).
- **Armadilhas descartadas (não repetir)**:
  1. Adicionar `hips_z_min` quebra capas longas nas costas (`test_autorig_geodesico_capa_solta`).
  2. Abaixar piso suave de `Head` sem `if tem_neck:` vaza para o dorso em `r15@1` (`tem_neck=False`).
  3. Cortar `UpperArm` de forma rígida acima do ombro (`17,17×`) ou suavização Laplaciana `passos >= 4` piora `run`/`death`.
- **Agregação `G16`**: use sempre o **pico do pior clipe** (nunca união de arestas entre clipes) para invariância ao número de clipes e paridade exata entre Blender (`postprocess_deform.py`) e `verify` (`qc_deformacao.py` `glb_lbs`).

## 7. Diagnóstico Rápido & Pirâmide de Testes no `3DCreation`
- **Varredura em lote (1 boot Blender, N variantes)**: em vez de disparar dezenas de invocações frias de Blender, resolva o binário com `forge3d.post.binario()`, gere os clipes com `forge3d.animacao.clipes(perfil, esqueleto, pedidos)`, carregue a malha/rig **uma vez** em um único script Blender headless e teste todas as variantes em memória (`~35 min → ~2 min`).
- **Baseline realista antes de codar**: inclua ao menos 1 malha i23d soldada (ex.: saída `TRELLIS.2-4B` tipo `Kragor`) junto de rigs modulares (`HeroWardenAA`) na medição inicial, evitando descobrir falhas de malha soldada só no E2E final.
- **Pirâmide de testes em 3 camadas** (não rode `pytest -m "not gpu"` monolítico durante iteração):
  1. **Camada 1 (~8 s)**: `bash tools/ci.sh` (`pytest -m "not gpu and not blender"`, `ruff`, `mypy`, contexto, `P0`).
  2. **Camada 2 (~45–90 s)**: `pytest` Blender **direcionado** apenas aos arquivos ligados à mudança (ex.: `test_v099_def06_g16.py`, `test_autorig_geodesico.py`, `test_smart_fit_rig56_blender.py`).
  3. **Camada 3 (aceite final ou edição de núcleo compartilhado)**: suíte Blender completa / `forge3d run` + `verify` E2E.
- **Higiene de artefatos gerados**: grave renders diagnósticos, specs temporárias e previews ad-hoc apenas em `~/.local/state/forge3d/saida/` ou no diretório `scratch/` da sessão — nunca deixe arquivos não referenciados em `docs/preview/` ou `docs/plano-*.md` no repo.
