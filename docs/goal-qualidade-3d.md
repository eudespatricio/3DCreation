# GOAL — Qualidade 3D Real no Forge3D (`Onda 3 -> Onda 1 -> Setup Onda 2`)

> **Status:** implementado e verificado (2026-11-11, `PIPELINE_VERSION 0.5.0`). `pytest` completo, CI, `verify` na Lyra E2E (`11.936` tris + arma extrudida `184` tris) e Godot 4.3 `GODOT_ANIM_OK` verdes; comparativos `TripoSG`/`hf_trellis` disponíveis sob demanda em `tools/bench_i23d.py`.
> **Ordem obrigatória:** `Onda 3` (Split + Pose + Rig) → `Onda 1` (BiRefNet + UV Proj + Decimate Protegido + Preset Hero) → `Setup Onda 2` (Delighting + PBR Metallic/Roughness + Harness `tools/bench_i23d.py` + Probing 6 GB).

## 1. Problema medido (diagnóstico Lyra, `11.934` tris)

1. **Rosto derretido e microdetalhe perdido:** `rembg` padrão (`u2net`), `TripoSR` single-view apenas com `COLOR_0`, `bake_pbr` sem projeção 2D e `DECIMATE` uniforme sem preservar cabeça/mãos.
2. **Peça única fundida:** `B11` em `src/forge3d/spec.py` e nos schemas proibia `parte` na rota `mesh`; capa, saia e espada entravam juntas no voxel/SDF e colapsavam numa malha só.
3. **Pose ruim em `origem` + vazamento de skinning:** quando o item traz `origem`, o pipeline pulava `ConceptProvider` (`FORGE3D_CONCEPT_POSE` / ControlNet) e o `blender/autorig.py` usava distância euclidiana inversa `1/(d+eps)^4`, vazando peso entre braços baixos, tronco, saia e capa.
4. **Iluminação pré-assada e `Metallic = 0.0` fixo:** `blender/bake_pbr.py` (`_empacotar_orm`) derivava apenas roughness do AO e travava `Metallic = 0.0`, sem delighting prévio.

## 2. Regras duras (não reabrir)

- `D3` CLI-only · `D6` cache por versão efetiva · `D9` QC sem bypass · `D11`/`I6` GPU serializada
- `D18`/`G8` allowlist comercial (`Zero123++` com pesos CC-BY-NC fora; `TripoSR`/`TripoSG`/`TRELLIS` MIT aprovados; `SF3D` permanece encerrado por `D27`)
- `D26` núcleo leve (`src/forge3d/` sem `torch`, `numpy` ou `cv2`) · `I9` scripts `blender/*.py` em Python puro + `bpy`/`bmesh`/`mathutils` (sem `PIL`, sem `numpy`)
- `I12`/`I14`/`I15` sem `/mnt/`, UNC, franquia ou projeto consumidor em código/schemas/docs
- Manter os `244` testes + `tools/ci.sh` + `tools/conformidade.py` + `tools/check-contexto.sh` verdes a cada etapa.

## 3. Fases e Divisão de Atividades

### Etapa 1 — Onda 3: Split na Rota `mesh`, Extrusão 2D Limpa, Pose Guard e AutoRig Topológico

| Trilha | Dono | Arquivos exclusivos | Entrega e portão de saída |
|---|---|---|---|
| **1A — Contratos Split & Anexos** | `split-contracts` | `schemas/spec.v2.schema.json`, `schemas/spec.v3.schema.json`, `schemas/manifest.v3.schema.json`, `src/forge3d/spec.py`, `src/forge3d/profiles.py`, `src/forge3d/publish.py`, `src/forge3d/rbx.py`, `tests/test_onda3_split_contrato.py` | `parte` (`corpo`/`capa`/`arma`) liberado em `mesh`; `capa` aceita `prop_estatico` ou `personagem_humanoide`; `qualidade: hero` / `pose_guard` / `extrudir_2d` opcionais em `spec@3`; `manifest@3` emite `anexo` opcional; `rbx.py` inclui `RightGripAttachment` e `BodyBackAttachment`. |
| **1B — AutoRig Geodésico** | `autorig-geodesic` | `blender/autorig.py`, `tests/test_autorig_geodesico.py` | Partição por componente conexo + Dijkstra geodésico (`heapq` + arestas `bmesh`) a partir dos ossos semente; teste headless prova zero vazamento braço↔quadril em pose de braços baixos, com `test_autorig_blender.py` e `test_rig_axes.py` verdes. |
| **1C — Extrusão 2D + Decimate** | `blender-uv-extrude` | `blender/extrude_2d.py`, `blender/postprocess.py`, `tests/test_extrude_e_uv_proj.py` | `forge3d/bruto-extrude@1` gera `arma` (seção chanfrada/lenticular + pivô `empunhadura` 20%) e `capa` curva com `0` não-manifold em `bpy`/`bmesh` puro; `decimar` protege grupo `Head`/mãos. |

### Etapa 2 — Onda 1: Cutout `BiRefNet`, Camera UV Projection e Preset `hero`

| Trilha | Dono | Arquivos exclusivos | Entrega e portão de saída |
|---|---|---|---|
| **2A — Camera UV Projection + ORM Hook** | `blender-uv-extrude` | `blender/bake_pbr.py` | `UV_PROJECT` frontal + blend por produto escalar (`Dot Product`) entre `origem_textura` (frente/3-4) e `VertexColor` (traseira/rasante) direto no shader Cycles; zero `PIL`/`numpy`; suporta `metallic_hint_png` e `roughness_hint_png`. |
| **2B — Pose Guard, BiRefNet & Mesh Hook** | `pose-cutout-bench` | `tools/pose_guard.py`, `tools/concept_infer.py`, `tools/i23d_infer.py`, `src/forge3d/providers/mesh.py`, `tests/test_pose_guard_delight.py` | Detector de silhueta `arms_down` (`cv2`) + modo Img2Img ControlNet OpenPose em `concept_infer.py`; decomposição 2D auxiliar; `--rembg-modelo birefnet-general` com fallback offline `u2net`; `MeshProvider.versao` atualizado (D6). |

### Etapa 3 — Setup da Onda 2: Delighting, Heurística PBR e Harness `bench_i23d.py`

| Trilha | Dono | Arquivos exclusivos | Entrega e portão de saída |
|---|---|---|---|
| **3A — Delight + PBR + Harness** | `pose-cutout-bench` | `tools/delight.py`, `tools/bench_i23d.py` | Retinex/Bilateral luminance flattening + estimador Metallic/Roughness (prata/dourado vs tecido/pele) gerando mapas alinhados para o `bake_pbr`; `tools/bench_i23d.py` mede tempo por fase, pico VRAM (`torch` + `nvidia-smi`), pico RSS RAM do host, tris, G1, nitidez Laplaciana e completude 4 vistas, com baseline medido e gancho opt-in para `TripoSG` / `HF Space`. |

## 4. Portões finais (antes de fechar e commitar)

1. `pytest` completo (unitários + Blender 4.2 headless) sem regressões;
2. `bash tools/ci.sh`, `bash tools/ci_verify.sh`, `bash tools/ci_dist.sh`, `bash tools/check-contexto.sh` e `python tools/conformidade.py` todos exit `0`;
3. `uv run --with ruff ruff check --select F,I src blender tools tests` + `uv run --with mypy mypy` limpos;
4. Benchmark A/B cronometrado na RTX 3060 (`ollama` parado antes de rodar GPU) com preview visual comparativo antes vs depois.
