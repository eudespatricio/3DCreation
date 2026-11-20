---
name: forge3d-blender-pitfalls
description: >-
  Use when editing Blender 4.2 bpy scripts (UV unwrap, lightmap, PBR bake,
  convex colliders, R15 bone split) or Forge3D multiview/i23d providers and QC
  gates in 3DCreation to avoid measured regressions.
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
