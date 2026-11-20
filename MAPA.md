# MAPA — onde cada responsabilidade mora
> Teto: 60 linhas. Se um caminho não estiver aqui, procure antes de editar.

| Caminho | O que tem | Quando carregar |
|---|---|---|
| `CONTINUAR.md` | fase, próximos passos, como retomar | sessão nova, sempre primeiro |
| `DECISOES.md` §1–§2 | fatos medidos + decisões firmadas | antes de propor mudança de rumo |
| `DECISOES.md` §4 | perguntas ainda abertas (Q1–Q8) | quando a resposta não estiver decidida |
| `INVARIANTES.md` | regras cujo desrespeito é bug, com comando de verificação | antes de concluir qualquer tarefa |
| `CONSELHOS.md` | quando convocar conselho e como ele decide | decisão irreversível ou sem oráculo |
| `docs/arquitetura.md` | fluxo, camadas, fronteiras | desenhar/alterar etapa do pipeline |
| `docs/contratos.md` | `spec@1`–`spec@6`, `manifest@1`–`@6`, G11, exit codes, códigos de erro | mexer na fronteira com o jogo |
| `docs/rotas-e-providers.md` | as 4 rotas, interface de provider, roteamento | adicionar gerador novo |
| `docs/perfis-export.md` | `godot4`, `godot4-aa`, `roblox-r15`, `roblox-aa-80`: eixos, escala, rig 56 ossos, PBR | exportar ou integrar no jogo |
| `docs/qc-e-verificacao.md` | gates G1–G15 (G1–G11, G12–G14 Roblox, G15 concept→3D), severidade, remediação e `verify` reexecutando G1–G13 + G11 | asset ou cena reprovada no QC |
| `docs/dependencias.md` | versões pinadas, venv i23d, o que instalar, o que não instalar | `doctor` falhou / montar ambiente |
| `docs/riscos-e-licencas.md` · `docs/avaliacao-qualidade-3d.md` | VRAM, licenças de modelo, IP, tabela de modelos 6 GB; opções de escala de qualidade (conexões existentes) | escolher modelo ou publicar |
| `docs/auditoria-mobs-roblox.md` | como nascem os mobs e bosses do projeto Roblox (Blender → Forge3D → Open Cloud → HordeKit), números medidos e gaps | investigar o processo de asset de um projeto consumidor |
| `docs/plano-mobs-game-ready.md` | benchmark (Tripo/Meshy/Hunyuan/Roblox), contrato `spec@7` com partes/rig/âncoras e fases F0–F5 | planejar mobs game-ready |
| `docs/handoff-mobs-roblox-2026-11-18.md` | pausa da janela: decisões, entregas, evidências, pendências e como retomar | retomar em sessão nova |
| `docs/roadmap.md` | P0–P6 com portão de saída por fase; §Depois da P6 = backlog sem fase nova | planejar próxima fase |
| `docs/integracao.md` | como outro projeto chama a CLI: instalar, allowlist, lote, exit codes, manifesto | integrar num projeto de jogo |
| `docs/gaps.md` | lacunas abertas com dono e condição de fechamento | fim de fase |
| `schemas/spec.v1.schema.json` · `schemas/spec.v2.schema.json` · `schemas/spec.v3.schema.json` · `schemas/spec.v4.schema.json` · `schemas/spec.v5.schema.json` · `schemas/spec.v6.schema.json` | contrato de entrada (corrente = `spec@6`; `@1`–`@5` aceitos) | validar lote |
| `schemas/manifest.v1.schema.json` · `schemas/manifest.v2.schema.json` · `schemas/manifest.v3.schema.json` · `schemas/manifest.v4.schema.json` · `schemas/manifest.v5.schema.json` · `schemas/manifest.v6.schema.json` | contrato de saída (corrente = `manifest@6`; `@1`–`@5` aceitos) | consumir asset no jogo |
| `profiles/godot4.yaml` · `profiles/godot4-aa.yaml` · `profiles/roblox-r15.yaml` · `profiles/roblox-aa-80.yaml` | perfis de export padrão e AA (80 %) | exportar para Godot/Roblox |
| `examples/lote_01.yaml` · `lote_03_kit` · `lote_04_mesh` · `lote_05_mesh_concept` · `lote_06_mesh_split` · `lote_07_cape` · `lote_08_ab_hybrid` · `lote_09_r15` · `lote_11_hero_armor_set` · `lote_12_creatures_mounts` · `lote_13_scene_budget_aa` · `lote_14_v09_aa_godot` · `lote_15_v09_aa_roblox` (prefixo `examples/`) | fixtures: blocky, kit, mesh, armadura, criaturas e showcases AA | exemplo canônico e fixture de teste |
| `examples/concepts/` | PNGs de entrada da rota `mesh` (teapot MIT) | rodar o exemplo mesh |
| `tools/check-p0.py` | portão do P0: schemas, exemplos, tetos, I12, I14 | antes de dizer "P0 fechada" |
| `tools/render_preview.py` · `docs/preview/` · `docs/goal-qualidade-3d.md` | preview Cycles (`--turntable --square`), renders e goal de qualidade | revisar qualidade do asset |
| `tools/i23d_infer.py` · `tools/concept_infer.py` · `tools/pose_guard.py` · `tools/delight.py` · `tools/bench_i23d.py` · `tools/setup_concept_venv.sh` · `tools/normalize_mesh.py` · `tools/ci.sh` · `tools/configurar_roblox.sh` · `tools/r15_studio_test.lua` · `tools/r15_texture_apply_test.lua` · `tools/r15_rbxlx_test.lua` · `tools/mcp_studio.py` · `tools/r15_escala_studio.py` · `tools/r15_anim_studio.py` · `tools/r15_play_g14.py` · `tools/lod_qualidade.py` + `docs/preview/lod/` · `tools/ci_verify.sh` · `tools/ci_dist.sh` · `tools/conformidade.py` · `src/forge3d/modular.py` (WFC) · `src/forge3d/providers/modular.py` · `examples/lote_10_modular.yaml` · `tools/godot_anim_check.gd` · `tools/godot_visual_qa.gd` · `tools/godot_rig_axes_check.gd` · `tools/godot_draw_calls_bench.gd` + `tools/godot_project/` · `tools/visual_qa_critic.py` · `tools/visual_qa_fidelidade.py` · `tools/vault_sync_cc0.py` · `tools/kitbash_composer.py` · `tools/colab_trellis_worker.py` · `tools/colab_trellis_lora.py` · `docs/preview/p5_anim_idle.log` | inferência, concept, vault CC0, kitbash, TRELLIS/LoRA, QA visual/Godot headless, Play G14 e CI | depurar rota mesh / qualidade / portão de PR |
| `src/forge3d/` + `src/forge3d/cli/` | `spec` `plan` `qc` `publish` (`cache` `index` `verify`) `pipeline` `doctor` `locks` `canonical` `config` `paths` `gc` `rbx` `upload` `migrate` `sync` `vault` `mcp_server` + 18 subcomandos | implementação |
| `src/forge3d/qc_uv.py` · `src/forge3d/qc_skin.py` · `src/forge3d/qc_fidelidade.py` · `src/forge3d/verify_g11.py` · `src/forge3d/segmentacao.py` | submódulos QC (`qc_geom`, `qc_orientacao`, `qc_midia`, `qc_gates`, `qc_gates_ext`, `qc_roblox`), reexecução G11 + `partes[]` no `verify` e split R15 (`rbx_*`, `sync_*`, `upload_*`, `spec_*`, `plan_*`, `pipeline_*`) | depurar G1–G15, `verify` ou R15 |
| `addons/forge3d/` | plugin Godot 4 (`plugin.cfg`, `plugin.gd`, `scene_post_import_plugin.gd`, `post_import.gd`): import zero-click, `BoneMap` 23/56 ossos, `UCX_`, `_LOD1`, sockets, montaria e guarda de vidro/emissão | importar no Godot 4 |
| `src/forge3d/providers/` | `base` `blocky` `importer` `mesh` (`mesh_*`) `concept` (`concept_*`) `modular` `cloud_ai` (`cloud_gemini_*`) | adicionar rota / conector IA |
| `src/forge3d/post.py` + `blender/postprocess.py` | subprocesso + `bpy` (`blender/template_body.py`, `blender/textures_pbr/`, `blender/smart_fit.py`, `blender/split_por_ossos.py`, `extrude_2d.py`, `bake_pbr`, `procedural_pbr`, `organic_sculpt`, `autorig`, `modular_armor` + submódulos `*_`) | pós-processo, Smart-Fit BVH, camadas CC0, PBR, rig 56 ossos, split R15 |
| `tests/` | `test_unidade` · `test_spec_v6_g11` · `test_cc0_vault_llm` · `test_smart_fit_rig56` · `test_pbr_zonas_roblox_v09` · `test_animacao` · `test_autorig_blender` · `test_autorig_geodesico` · `test_creatures_mounts` · `test_humanoid_layers_grip` · `test_props_premium_v08` · `test_cloud_connectors` · `test_extrude_e_uv_proj` · `test_onda3_split_contrato` · `test_pose_guard_delight` · `test_rig_axes` · `test_pbr_bake` · `test_cutout_halo` · `test_godot_addon` · `test_concept` · `test_rbx` · `test_sync` · `test_rojo_assets` · `test_mcp_server` · `test_publish_split` · `test_doc_comandos` · `test_qc_f26_hardening` · `test_f27_silent_except` · `test_red_r2_roblox`..`test_red_r5_qc` · `test_spec_partes_b25` · `test_partes_manifesto` · `invariants/` · `e2e/` (97 testes Tiers 1–4) | portão de CI |
| `~/.venvs/concept` | venv do SD1.5/diffusers (cópia da i23d; pin de transformers diferente) | gerar concept |
| `$FORGE3D_HOME` | `cache` `runs` `staging` `locks` `indice.sqlite` `ledger.jsonl` `saida/` | depurar run |
| `~/.config/forge3d/allowlist.yaml` | destinos autorizados (D23) | publicar em projeto de jogo |

## Armadilhas conhecidas

1. **Blender 4.2 usa Python 3.11 embutido.** `pip install` nele contamina o DCC e quebra na próxima atualização; scripts `bpy` recebem dados por arquivo JSON, nunca por stdout (I9).
2. **O repo mora em ext4 e a sessão Windows o vê por UNC — isso é o normal (I12), não um alerta de sessão.** Medido: criar/apagar/`mv` funcionam, mas **modificar existente falha** com `GetFileSecurityW EIO`; em lote o UNC é ~75× mais lento (200 arquivos: 906 ms vs 12 ms). Receita em `AGENTS.md` §Ambiente.
3. **Python 3.14 é o do sistema e não serve** para o stack ML (`torch` não publica wheel); use 3.12 do `uv`.
4. **6 GB de VRAM não comportam dois modelos residentes;** sem o lock (I6) o sintoma é `CUDA OOM` intermitente que parece bug.
5. **`ollama` mede 4.096 tokens de contexto efetivo**, não 32k; prompt de `draft` tem que caber nisso.
6. **Diffusion não é determinístico entre versões de driver/modelo;** só `blocky` pode ser byte-idêntico (I1).
7. **Nome de franquia é passivo jurídico;** `blocky_voxel`, nunca `minecraft_*` no manifesto (I14).
8. **Alterou a saída de um provider sem subir `VERSAO`?** O cache serve o artefato velho e o QC passa; a versão entra na chave (D6).
9. **G1 solda antes de contar não-manifold.** glTF divide vértice em cada costura de UV; sem soldar, todo asset importado parece ter borda aberta. O gate mede topologia soldada de propósito.
10. **Sobreponha o pivô, nunca compartilhe canto exato:** encostar abre fenda ao animar e canto exato vira não-manifold no G1 após a solda. **Joelho e cotovelo giram ao contrário:** local X negativo dobra o joelho, positivo dobra o cotovelo — sinal igual nos dois inverte o membro.
11. **`convex_hull` herda faces de entrada** (D64): o hull tem que ser feito sobre nuvem de pontos, sem faces. E convexidade é medida com 1 mm/m de tolerância (D65) — colisor gerado desvia sub-milímetro e é convexo na prática.
12. **Decimate cria ilha de uma face.** O TripoSR a 7.960 tris deixou um triângulo solto de 5,1e-6 m²; `reparar_malha` remove **toda** ilha de 1 face.
13. **Rota `mesh` gera concept interno quando sem `origem` (D35, 4 vistas D113+, zero `fal.run`)** e separa sub-rotas explícitas (`i23d`/`template`/`procedural`/`extrude_2d`). Normais exigem OpenGL `+Y` (G4), UV sem colapso/sobreposição (G3) e skin com deformação não-raiz (G6).
