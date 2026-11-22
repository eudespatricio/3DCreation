# Plano de Fixes — Feedback Godot `v0.9.9` (`tomb_warden`)

- **Data**: 21/11/2026 · **Baseline**: `v0.9.9` (`D134`, `manifest@7`)
- **Status**: **`EXECUTADO EM v0.9.10 (D135)`** (`22/11/2026`) — wave consolidada com [`plano-fixes-v099-feedback-roblox.md`](file:///home/eudespatricio/3DCreation/docs/plano-fixes-v099-feedback-roblox.md) (`F-01`–`F-08`), validada E2E `--no-cache` + `verify` (`exit=0`) em `tomb_warden` e `kragor`.
- **Caso diagnóstico**: boss humanoide `humanoide.chefe.tomb_warden.v099` (`godot4-aa`, `godot-humanoid-aa@1`, `56` ossos, `8` clipes, `altura_metros: 2.4`, `15.760` tris / `20.882` vértices no GLB, PBR `2048 px`, `G1–G15` aprovados com `G15` IoU `0.843`, reprovado em `G16` com pico `102.6491` no clipe `jump` f21).

---

## 1. Avaliação Técnica do Feedback (Fatos Medidos × Correções de Diagnóstico)

### A. Itens do Forge3D (`src/` e `blender/`)

1. **`[P0-1]` Colapso de skinning em ombros/braços (`Shoulder.L/R` e `UpperArm.L/R` com `0` vértices) — CONFIRMADO + CAUSA RAIZ EXATA**
   - **Medição direta no GLB (`2.400 m`, `bbox X=[-1.040, +1.040]`, `Z_gltf=[-0.347, +0.347]`)**:
     - Em `f = 0.46..0.59` (`z = 1.10..1.42 m`), existe vão limpo (`gaps_x`) separando tronco (`0.27–0.33 m`, `0.11–0.14 h`) e braços em A-pose `45°` (`0.39–1.04 m`).
     - Em `f = 0.62` (`z = 1.49 m`), a axila fecha (`gaps_x = []`), `max|x| = 0.853 m` (`0.356 h`), `dy_core = 0.562 m` e `dy_out = 0.291 m >= req_dy (0.197 m)` — logo `_trim_slab_braco` (`blender/autorig_marcos.py:40-61`) não poda a fatia.
     - Como `blender/autorig_marcos.py:143` calcula `torso_hw = max(...)` na faixa `0.55..0.63` e o filtro anti-salto da linha `158` só atua acima de `f > 0.63`, `torso_hw` é inflado para **`0.853 m`** (maior até que os ombros reais em `f = 0.71..0.77`, que medem `0.658..0.667 m`).
   - **Cascata no rig e skinning**:
     - `blender/autorig_grafo.py:65,67` deriva `arm_root_x = 1.06 * 0.853 = 0.904 m` (maior que `UpperArm.L = 0.694 m`, `LowerArm.L = 0.716 m` e `Hand.L = 0.900 m`) e `ombro_min_x = 0.85 * 0.853 = 0.725 m` (maior que `UpperArm.L = 0.694 m`).
     - `blender/autorig_pesos_geo.py:176-183` deixa `Shoulder.L/R` e `UpperArm.L/R` com `0` vértices; `Chest` (`5.704` v) e `Spine` (`4.081` v) engolem o braço superior e encostam direto em `LowerArm.L/R` (`196` arestas `Spine <-> LowerArm`, `dist_hier = 4`).
     - `blender/autorig_pesos_coerencia.py:143-146` aciona `bloq = True` (`len(v_dist) > 0.12 * n_distal`) e cancela a mediação de costuras, causando `G16` `max_stretch = 102.6491` no `jump` f21 e reprovando `7/8` clipes (`idle` único verde em `3.9560`).

2. **`[P0-2]` Enterramento de pernas em `death` (`-1.173 m`) + `[P1-3]` `toe_r` perfurando solo — CONFIRMADO**
   - `src/forge3d/animacao.py:317-334` (`MOTORES_DEATH`) roda `quadril` apenas em `Z` (`+24°`, zero pitch `X`) e mantém pernas quase retas (`perna=2°`, `canela=-4°`, `pe=-20°`), enquanto a linha `475` (`_DESLOCAMENTO_QUADRIL_Z["death"]`) baixa `Hips` `-0.75 m` fixos (`-1.125 m` em `model_scale=1.5` no consumidor -> `foot_r = -0.927 m`, `toe_r = -1.173 m`).
   - `blender/autorig_anim_sockets.py:191-197` aplica `deslocamento_m` direto sem escalar pela altura do rig nem fazer passe FK de contato mínimo com o piso (`Foot`/`Toe >= 0.0`), originando também `toe_r_min = -0.018..-0.096 m` em `walk`, `run`, `jump`, `attack` e `block`.
   - **Nota de ciclo (`run`)**: `SEGUNDOS_RUN = 1.667 s` usa `ciclos = 2` (`0.833 s`/ciclo), porém com `20` chaves divididas por `2` ciclos (`10` chaves/ciclo em `src/forge3d/animacao.py:630`); avaliar normalizar para 1 ciclo denso ou preservar compatibilidade com `tests/test_animacao.py`.

3. **`[P1-1]` Osso `Cape` fora da malha (`Z_gltf = +0.458 m`) — CONFIRMADO (MESMA RAIZ + FÓRMULA ERRADA)**
   - `blender/autorig_ossos.py:144` usa `cape_y = cy - max(0.055 * h, 0.55 * torso_hw)`, misturando meia-largura lateral (`X`) com profundidade dorsal (`Y`). Com `torso_hw = 0.853 m`, posiciona `Cape` em `gltf_pos = (0.0, 1.848, +0.458)`, fora da AABB `Z_gltf = [-0.347, +0.347]`.

4. **`[P1-2]` `ORMMaterial3D` com `metallic = 0.0` — DIAGNÓSTICO CORRIGIDO POR PROVA EM GODOT 4.7.2 + MEDIÇÃO DO `_orm.png`**
   - **Falso positivo de leitura no Godot 4.7.2**: testado diretamente no binário `godot 4.7.2` — em `ORMMaterial3D`, `metallic` e `roughness` possuem `usage=0` (`PROPERTY_USAGE_NONE`), não são salvos em `.scn`/`.tres` (`RELOAD metallic=0.0` mesmo após `orm_mat.metallic = 1.0` do `D126`) e no shader `ORMMaterial3D` lê diretamente `METALLIC = orm_tex.b`, `ROUGHNESS = orm_tex.g`, `AO = orm_tex.r`.
   - **Pendência real no consumidor**: o plugin `addons/forge3d/` no consumidor data de versão anterior a `D126` (`.glb.import` veio com `animation/fps=30` e `_subresources={}`); é necessário sincronizar `addons/forge3d/` e ajustar a inspeção do consumidor para verificar `orm_texture` / canal B em vez de `mat.metallic`.
   - **Causa real de contraste metálico/escuro no Forge3D (`_orm.png`)**: medido em `_orm.png` e no `metallicRoughnessTexture` de `bruto/modelo.glb`:
     - `_orm.png`: `B_Metal` veio saturado (`p10=254, p50=254, mean=235.0, frac>128=0.924`), `G_Rough` quase plano (`p10=141, p50=141, p90=142, mean=140.5`) e `R_AO` escuro (`p50=70, mean=95.9`).
     - `bruto/modelo.glb` já saiu do `TRELLIS.2` com `B_Metal p50=254 (mean=253.1)` e `G_Rough p50=141`, enquanto `bruto/metallic_hint.png` (`p50=0, p90=186, mean=31.9`) e `bruto/roughness_hint.png` (`p10=100, p50=209, mean=187.0`) não modulam o material `pbr_nativo` em `blender/bake_pbr_nativo.py`.

5. **`[P2-1]` Leve eco frontal nas costas + custo ocioso de `vistas: 4` no `TRELLIS.2` — CONFIRMADO**
   - `resultado.json` registra `cor_atributo: "pbr_nativo"`, `pbr_nativo_preservado: true` e `vistas_ortograficas_aplicadas: []`, mesmo com `concept_back/left/right` gerados e tratados com `rembg`+`delight` em `bruto/`. Como o `TRELLIS.2` local opera em single-view (`D133`), as 3 vistas auxiliares não entraram na projeção final.

---

### B. Itens Exclusivos do Projeto Consumidor Godot (fora do repo Forge3D por `I15`)

- **`[P0-3]` Truncamento de one-shots via `phase_seed`**: `entity_visual_pool.gd:3938-3943` aplica `ap.seek(fposmod(w13_phase, w13_len), true)` em toda troca de estado (`ATTACK` `0.413/0.875s`, `HIT` `0.413/0.542s`, `DEATH` `0.413/1.292s`).
- **`[P1-4]` `TELEGRAPH` tocando `"block"`**: `entity_visual_pool.gd:3929-3930` mapeia `TELEGRAPH -> "block"`.
- **`[P1-5]` `BossAuraOmniLight` dentro do peito em verde**: `entity_visual_pool.gd:3806-3815` coloca a luz em `(0, 1.8, 0)` com cor verde de perfil errado.
- **`[P1-6]` Offsets de arma/escudo de 23 ossos em rig de 56 ossos**: `hero_visual_assembler.gd:642-740` usa poses hardcoded de `godot-humanoid@1` em vez de ler `sockets` do `manifest@7` (`Hand.R`, `Hand.L`, `Back`, `Head`) / `Socket_*`.

---

## 2. Plano de Fixes Detalhado com Estimativas `[estimado]`

### Trilha A — Forge3D (`/home/eudespatricio/3DCreation`)

| ID | Ataca | Arquivos / Símbolos | Mudança Técnica Proposta | Critério de Aceite | Tempo `[estimado]` |
|---|---|---|---|---|---|
| **`F-01`** | `P0-1`, `P1-1` | `blender/autorig_marcos.py` (`_perfil_tronco_fatias`, `_trim_slab_braco`), `blender/autorig_grafo.py` (`_limites_anatomicos`, `_osso_permitido_semente`), `blender/autorig_pesos_geo.py` (`_sementes_osso_ilha`), `blender/autorig_pesos_coerencia.py` (`mediar_costuras_distantes`), `blender/autorig_ossos.py` (`_construir_ossos`) | 1) Calcular `torso_hw` pela faixa de cintura/axila separada (`f=0.46..0.59` ou mediana/mínimo com `gaps_x` e limite de profundidade Y da malha), sem englobar braços A-pose em `f=0.62`; 2) limitar `arm_root_x`/`ombro_min_x` em relação ao ombro detectado garantindo sementes > 0 em `Shoulder.L/R` e `UpperArm.L/R`; 3) substituir o corte total `bloq = True` por mediação restrita via `Chest`/`Shoulder` (ou fallback de semente proximal) para zerar arestas ilegais `Spine <-> LowerArm`; 4) calcular `cape_y` pela profundidade dorsal real do tronco (`min(v.y)` no tórax) em vez de `0.55 * torso_hw`. | `Shoulder.L/R > 0` e `UpperArm.L/R > 0` vértices; `0` arestas `Spine <-> LowerArm` (`dist_hier >= 3`); `Cape` dentro da AABB dorsal; `G16` verde em `tomb_warden`, Kragor e `test_autorig_geodesico`. | **`1h45 – 2h30`** `[estimado]` |
| **`F-02`** | `P0-2`, `P1-3` | `src/forge3d/animacao.py` (`MOTORES_DEATH`, `_DESLOCAMENTO_QUADRIL_Z`, ciclos/duração), `blender/autorig_anim_sockets.py` (`aplicar_animacoes_multi`) | 1) Reformular `MOTORES_DEATH` com tombamento em pitch `X` + flexão de joelho/tornozelo mantendo pés sem enterrar; 2) escalar `deslocamento_m` pela razão de altura do rig (`altura / 1.75` ou `leg_len`) e aplicar passe de ground-clamp FK por frame (`min_z(Foot, ToeBase) >= z_chao`) em todos os clipes no chão (`idle`, `walk`, `run`, `attack`, `block`, `hit`, `death`); 3) revisar cadência/chaves do `run` preservando paridade com `rbx_anim.py` e `tests/test_animacao.py`. | `death` sem penetração abaixo do piso (`foot_min >= 0.0`, `toe_min >= -0.005`); `walk`/`run`/`attack`/`block` sem afundamento do `Toe.R`; `G10` e `G16` verdes; `test_animacao.py` + `test_rbx.py` verdes. | **`1h15 – 1h50`** `[estimado]` |
| **`F-03`** | `P1-2`, `P2-1` | `blender/bake_pbr_nativo.py` (`configurar_saida_orm_emit_nativos`), `blender/bake_pbr_passes.py`, `src/forge3d/providers/mesh_i23d.py` | 1) No caminho `pbr_nativo`, combinar/modular `Metallic` e `Roughness` do `TRELLIS.2` com os hints `delight` (`metallic_hint`/`roughness_hint`) e calibrar piso mínimo de `R_AO` para evitar armadura 100% saturada em metal + fenda preta; 2) definir para `vistas: 4` com `TRELLIS.2` (**Opção A**: aplicar projeção dorsal/lateral de `concept_back/left/right` sobre `pbr_nativo` quando `vistas == 4`; ou **Opção B**: pular geração/delight de vistas extras quando backend single-view não as consome). | `_orm.png` com separação clara entre placa metálica e pedra/tecido e `R_AO` sem esmagamento; costas sem eco frontal (Opção A) ou zero tempo gasto em vistas não usadas (Opção B). | **`0h45 – 1h30`** `[estimado]` |
| **`F-04`** | Regressão & D6 | `pyproject.toml`, `src/forge3d/__init__.py`, `src/forge3d/post.py`, `tests/` | Bump `PIPELINE_VERSION = "0.9.10"` (`D6`); executar `bash tools/ci.sh`, `bash tools/ci_verify.sh`, testes Blender `autorig`/`animacao`/`deform` e re-geração E2E de `tomb_warden` + regressão Kragor (`godot4-aa`) e Iron Ram (`roblox-aa-80`). | `ci.sh` (`exit=0`), `ci_verify.sh` (`exit=0`), `tomb_warden` aprovado em `G1–G16` com `forge3d verify` `exit=0`. | **`0h35 – 0h50`** `[estimado]` |

### Trilha B — Projeto Consumidor Godot (`<repo-consumidor>`)

| ID | Ataca | Arquivos / Símbolos | Mudança Técnica Proposta | Critério de Aceite | Tempo `[estimado]` |
|---|---|---|---|---|---|
| **`G-01`** | `P0-3`, `P1-4`, `P1-5` | `<repo-consumidor>/src/presentation_3d/entity_visual_pool.gd` (`_on_mob_state_changed`, spawn do boss) | 1) Aplicar `ap.seek(fposmod(w13_phase, w13_len), true)` **apenas** em clipes em loop (`idle`, `walk`, `run`), iniciando `attack`/`block`/`hit`/`death`/`jump` em `t = 0.0`; 2) remover mapeamento `TELEGRAPH -> "block"` (usar antecipação de ataque/idle combat); 3) posicionar `BossAuraOmniLight` fora do tronco (`(0, 1.8 * scale + z_offset)`) com cor alinhada ao perfil `tomb_warden` (safira/azul, sem verde `drowned_blight`). | `ATTACK`/`HIT`/`DEATH` iniciam em `0.000s` (`runtime_state_transition_seek_audit`); `TELEGRAPH` não toca `"block"`; sem banho verde no tronco. | **`0h25 – 0h40`** `[estimado]` |
| **`G-02`** | `P1-2`, `P1-6` | `<repo-consumidor>/addons/forge3d/`, `<repo-consumidor>/src/presentation_3d/hero_visual_assembler.gd`, `<repo-consumidor>/tests/visual_boss_v099_anim_audit.gd` | 1) Sincronizar `addons/forge3d/` com a versão `v0.9.9` (`D126`, `post_import_materials.gd`, `fps=24`, `BoneMap` 56 ossos); 2) ajustar telemetria do audit para checar `orm_texture` + amostra do canal B (em vez de `mat.metallic` em Godot 4.7.2); 3) em `compute_weapon_socket_transform`, consumir `sockets` de `manifest@7` (`Socket_HandR`, `Socket_HandL`, `Socket_Back`, `Socket_Head`) quando presentes. | `addon` sincronizado; arma/escudo alinhados em `Hand.R`/`LowerArm.L`/`Hand.L` no rig de 56 ossos; telemetria ORM sem falso negativo. | **`0h45 – 1h15`** `[estimado]` |
| **`G-03`** | Aceite Godot | `<repo-consumidor>/assets/forge3d_v099/`, `<repo-consumidor>/tests/` | Reimportar asset `v0.9.10` aprovado em `G1–G16`, rodar suíte headless de contrato e re-capturar os `17` PNGs + `animation_audit.json` em Vulkan Win64. | `58/58` + suítes headless verdes; `17` PNGs sem asas rasgadas, pés no chão e um único ciclo completo de `attack`/`death`. | **`0h20 – 0h30`** `[estimado]` |

### Resumo de Estimativas `[estimado]`

- **Forge3D críticos (`F-01 + F-02 + F-04`)**: **`3h35 – 5h10`** `[estimado]`
- **Forge3D completo (`F-01..F-04`)**: **`4h20 – 6h40`** `[estimado]`
- **Consumidor Godot (`G-01..G-03`)**: **`1h30 – 2h25`** `[estimado]` (G-01/G-02 paralelizáveis com F-01/F-02)
- **Total E2E**: **`5h50 – 9h05`** `[estimado]` sequencial (**`4h30 – 6h45`** `[estimado]` com trilhas em paralelo)

### Riscos e Armadilhas Mapeados

- **Roblox R15 (`autorig_marcos.py` + `animacao.py`)**: mudanças nos marcos de `torso_hw`/`ombro` e nos clipes base alteram `split_por_ossos.py` (`G12`/`G13`) e `KeyframeSequence` (`G14`/`test_rbx.py`). Executar regressão de `lote_09_r15` e `lote_15_v09_aa_roblox` antes de fechar `F-04`.
- **Blender 4.2 RNA (`forge3d-blender-pitfalls`)**: capturar nomes/primitivos antes de `mode_set()` em scripts `bpy`; nunca introduzir `except Exception: pass` (`tests/test_f27_silent_except.py`).
- **Cache (`D6`)**: toda alteração em `autorig_*.py`, `animacao.py` ou `bake_pbr_nativo.py` exige bump de `PIPELINE_VERSION` (`0.9.10`).

---

## 3. Consolidação com Feedback de Roblox (Aguardando Operador)

Quando o feedback de Roblox chegar, anexar abaixo antes de abrir a execução da onda `v0.9.10`:

- [ ] **Rig & Split R15 (`partes_combinadas`, `Motor6D`, `G12`/`G13`)**: verificar se o mesmo colapso de `torso_hw` em A-pose `45°` afeta `LeftUpperArm`/`RightUpperArm` em bosses largos no `split_por_ossos.py`.
- [ ] **Animações Roblox (`G14`, `KeyframeSequence`, `deslocamento_m / 0.28`)**: verificar se `death` e `run` precisam de ajuste conjunto em `rbx_anim.py` (`HipHeight` / `LowerTorso`) além de `animacao.py`.
- [ ] **Decisões pendentes pré-código**:
  - `F-03` (`vistas: 4` no `TRELLIS.2` local): escolher **Opção A** (aplicar projeção multi-vista dorsal/lateral sobre `pbr_nativo`) vs **Opção B** (economizar chamadas/delight descartando vistas extras em single-view).
  - `F-02` (`SEGUNDOS_RUN`): confirmar se reduzimos para `1` ciclo denso (`~0.833 s`) ou mantemos `1.667 s` dobrando `n_segs` para `32..40` chaves.
