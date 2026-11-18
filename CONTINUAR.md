# CONTINUAR — handoff de sessão

**Data:** 18/11/2026 · **P0–P6, C5–C15, Ondas A–D e releases `v0.7.0`–`v0.9.3` fechadas.** Contratos
correntes `spec@6` e `manifest@6` (D94–D122; `@1`–`@5` compatíveis na leitura). Perfis AA (`godot4-aa`
56 ossos `godot-humanoid-aa@1` + PBR 4K e `roblox-aa-80` 16k tris/parte + `SurfaceAppearance` 4 canais)
com Gate `G11` de orçamento de cena 80 % AA (`<= 400k` tris, `<= 400` draw calls, `<= 200 MB` VRAM),
bake Cycles High→Low (`detalhe_alto` + `pbr_zonas`), `smart_fit.py` (BVH/Laplacian/PCA), Vault CC0
(`vault.py` + `gemini-embedding-2-preview` + `kitbash_composer.py` + `colab_trellis_lora.py`) e 6 albedos
PBR 1024px. **533 verdes + 1 GPU (skip)** em 534 testes · CI com **442 + 78 testes** em 3 jobs (`portoes`,
`verificar`, `distribuicao`).

Verificação rápida: `python -m pytest tests/test_e2e_rapido.py -q` (~2 s) e `python -m pytest` (~20 s).

---

## O que é este projeto

**Forge3D** transforma um **lote declarativo** (YAML/JSON) em assets 3D verificáveis — `.glb` com
escala, pivô, LOD, colisão, rig, QC e manifesto — e publica de forma atômica num destino autorizado.

Requisito duro do operador (10/11/2026): **o utilitário é independente de projeto**. Não lê config do
diretório onde roda, não escreve fora do próprio estado, não importa código de jogo (D25).

## Onde estamos, por fase

| Fase | Estado | Entrega |
|---|---|---|
| **P0** | ✔ | arquitetura, `spec@1`/`spec@2`, `manifest@1`, 2 perfis |
| **P0.5** | ✔ | D23 allowlist · D24 estado central · `tools/check-contexto.sh` |
| **P1** | ✔ | rotas `blocky` e `import` de ponta a ponta |
| **P2** | ✔ | R15 16 ossos, pivô por membro, `.rbxlx` nativo, upload Open Cloud, textura no Studio e a **escala** (`manifest@2`/D62) |
| **P3** | ✔ | provider `i23d` (TripoSR), bake UV/textura próprio, kit corpo/capa/arma |
| **P3.5** | ✔ | concept SD1.5 → TripoSR, split e A/B de 3 personagens híbridos |
| **P4** | ✔ | `spec@3` + WFC + 7 módulos + 10 setores, colisão por peça e 1 draw call (D74/D75/D77); parede cheia do lado fechado (D79) |
| **P5** | ✔ | animação base tocando no Roblox (D66/D67/D69) e LOD medido por critério (D71: blocky sem LOD, mesh com LOD no prop e no personagem) |
| **P6** | ✔ | `migrate` (D80), `verify` no CI de PR com Blender pinado e wheel instalável (D81) |

## O que foi entregue nesta janela

- **Janela P2/P4 (C12–C15)** — escala declarada no `manifest@2` (D62), hull sobre nuvem de pontos
  (D64), convexidade de 1 mm/m (D65) e 7 destinos/16 manifestos republicados; detalhe em
  `DECISOES.md` §2 e `docs/gaps.md`.
- **P5 (D66/D67/D69/D71) + GAP-047 (D79)** — `idle` procedural 24 fps embutido no `.glb` e `.rbxlx`
  (`Priority=Core`, asset `116049702979137` Approved), `tools/lod_qualidade.py` por silhueta (blocky sem
  LOD; malha gerada aprovada no bule 0,993 e personagem 0,980) e parede cheia no lado fechado (`nao_manifold=0`).
- **P6 + Doc (D80–D84)** — `forge3d migrate`, CI com Blender 4.2.0 pinado por sha256 (`tools/ci_verify.sh`,
  `tools/ci_dist.sh`), `tests/test_doc_comandos.py`, `verify --only`, `docs/integracao.md` e orientação por sola.
- **Ondas A–D (`v0.6.0`, D89–D92) + Eixos (`0.6.1`, D93)** — `spec@4`/`manifest@4`, paridade Godot 4
  (`UV2`, `sync --godot-gd`) e Roblox (`export-r15 --modo-rig bone`, `export-surface`, `export-acessorio`,
  `sync --rojo-lua`), armadura modular manifold, bake PBR 360°, QC V2 e correção de eixos/orientação.
- **Releases `v0.7.0` (`D94–D98`) e `v0.8.0` (`D99–D102`)** — `spec@5`/`manifest@5`, humanoide 3D CC0
  vestido (`grip`/`cupped`), props AA multi-zona + vidro refrativo `KHR_materials_transmission` + capa
  `CLOTH` 35f, dragão esmeralda (`winged_mount@1`, 17 clipes 24fps C1), Gemini Interactions + `visual_qa_critic.py` + TRELLIS MIT.
- **Release `v0.9.0` (`D103–D107`)** — `spec@6`/`manifest@6`, perfis `godot4-aa` (`godot-humanoid-aa@1` 56 ossos)
  e `roblox-aa-80` + Gate `G11` (`orcamento_cena` 80 % AA + `plan --scene-budget`), bake Cycles High→Low
  (`detalhe_alto` + `pbr_zonas`), isolamento `_orm`→`OrmPacked` + strip seguro de GLB, `blender/smart_fit.py`
  (BVH/Laplacian/PCA), Vault CC0 (`vault.py` + `gemini-embedding-2-preview` + `kitbash_composer.py` +
  `colab_trellis_lora.py`), 6 albedos PBR 1024px e 3 turntables Cycles 1600×1600 aprovados.
- **Hardening `v0.9.1` (`D108–D111`)** — `plan --scene-budget` separa `teto_pior_caso` e `estimativa` calibrada
  (< 1 % tris), G11 multi-superfície validado no Godot 4.7.2 (`tools/medir_draw_calls_godot.py`), `GAP-019`
  fechado (180/180 e2e, I9) e correções visuais `V1`–`V4` + `lote_14`/`lote_15` + crítico visual determinístico.
- **Qualidade sem conexões novas `v0.9.2` (`D112–D113`)** — Pixal3D passa a MIT e sai do bloqueio do
  D18 (LICENSE verificada em 18/11/2026) e `referencia_estilo` no concept via Gemini (`spec@6` aditivo
  + regra B23): o style sheet entra como imagem de referência no payload do Nano Banana já conectado,
  com hash na chave de cache e na versão do `providers.texture` (`+ref<12>`); auditoria do GameOne
  confirma pipeline 100 % Godot (81 manifestos `godot4`/`godot4-aa`).
- **Correções P0 do handoff `v0.9.3` (`D114–D122`)** — D-01 `origem`×`referencia_estilo` exclusivos; D-02
  auto-rig honra esqueleto explícito + B24; D-03 esqueleto real + run falha se pedido≠real; D-04 socket
  ausente vira falha; D-05 concept PNG real + dims reais; D-06 sidecar `concept.json`. `mob_rig_v1` `verify` verde.

## Números medidos nesta máquina

| Medida | Valor |
|---|---|
| Suíte | **523 verdes + 1 GPU (skip)** em **524 testes** (`524/524` verdes com `FORGE3D_CONCEPT_E2E=1`) |
| CI no GitHub | **442 testes** em `portoes` + **78 testes Blender** em `verificar` (com Godot 4.7.2 headless) + `distribuicao` |
| Instalação | wheel de **0.9.1** instalado em venv limpo; `validate`/`migrate`/`plan` rodam **fora do repo** (`tools/ci_dist.sh`) |
| `forge3d migrate` | `@1..@5`→`@6` textual com comentários intactos; `--saida`/`--em-lugar` |
| AA `v0.9.1` (`lote_14` / `lote_15` / `lote_13`) | `godot4-aa` `5/5` (`hero` 56 ossos `15.872 tris`, `gauntlets` `2.486 tris` `smart_fit`, `GODOT_VISUAL_QA_OK count=5`, G11 `53.188` tris / `24` draw calls == Godot Vulkan `24` / `47,67 MB` VRAM) · `roblox-aa-80` `3/3` (`16.688` tris / `14` dc `[estimado]` Roblox / `34,68 MB` VRAM) · `lote_13` `10/10` (`15.516` tris / `10` dc) · `kitbash` `328 tris` `nao_manifold=0` · 3 turntables `docs/preview/v091_aa_hero_1600.png` / `docs/preview/v091_aa_prop_1600.png` / `docs/preview/v091_aa_roblox_1600.png` (`aprovado: true`) |
| Showcase `v0.8.0` (`v08_showcase`) | 8 itens `manifest@5` (`nao_manifold=0`, `verify` **0 problemas**, `GODOT_VISUAL_QA_OK count=8`): herói `11.892 tris`, espada `1.430 tris`, orbe `1.860 tris`, mochila `1.672 tris`, capa `2.016 tris`, escudo `948 tris`, sela `1.200 tris`, dragão `15.920 tris` |
| Repo por UNC (sessão Windows) | criar/apagar/`mv` funcionam; **modificar existente falha** (`GetFileSecurityW EIO`); 200 arquivos: **906 ms** vs 12 ms em ext4 || Destinos no sandbox | **23 destinos** em `manifest@4` `0.6.0`, `verify` **0 problemas** |
| Clipe `idle` | **2,042 s**; move 5 ossos nos dois esqueletos; 48 canais no glb do R15 |
| Godot 4.3 (headless) | `GODOT_ANIM_OK` no R15 (5 tracks) e no android (7 tracks), movimento **0,0697 rad** |
| Clipe no rig Roblox (MCP) | Head anda **0,1091 studs** entre t=0 e t=0,5; maior delta de parte 0,1253 |
| Animation no Roblox | asset **116049702979137** (30.229 B, Approved, `Priority=Core`); `GetKeyframeSequenceAsync` = 5 keyframes, 15 poses |
| Playback no client | Head anda **0,0949 / 0,0662 studs** no rig Motor6D do `.rbxlx`; com `Idle` (v2/v3) 0,0002 |
| LOD do blocky (decimate) | LOD1 IoU **0,76** frente / 0,98 lado; LOD2 **0,55** / 0,81 + espinhos no render → reprovado |
| LOD de malha gerada | bule a 50%: IoU **0,993** frente / **0,994** lado, faixa **0,948**, bbox ≤ 0,09% → aprovado |
| LOD de personagem mesh | `corpo.02` a 50%: IoU **0,980** frente / **0,987** lado, faixa **0,971**, bbox ≤ 0,11% → aprovado |
| P4 — layout 5x2 (seed 20261111) | 10 setores de **24–48 tris**, **1 mesh/1 material** e **2–4 hulls** de colisão por setor (chão 0,20 m, parede 2,00 m); `verify` 0 problemas · parede do lado fechado de vão inteiro (0,40 m do limite, 0,20→2,40 m) com G1 **nao_manifold=0** |
| Client do Studio | personagem padrão usa **Bone**, não Motor6D: a validação usa o rig do `.rbxlx` replicado do server |
| Colisor após D64/D65 | desvio máximo **4,3e-4 m** num hull de 2,2 m (tolerância 1 mm/m); face interior do defeito desviava 1,8 m |
| Package R15 v2 no Studio | `size=2,7086 × 6,6071 × 1,5196` studs · **16 Bones** · `surface=false` · `humanoid=false` |
| glb do R15 | `bbox = 2,70855 × 6,60709 × 1,519631` studs para `bbox_m = [0,7584; 1,85; 0,4255]` m |
| Rig `.rbxlx` | **6,6071 × 2,7086 × 1,5196 studs** (base 0, topo 6,6071; 16 Parts + Baseplate) — igual ao package |
| Resíduo rig × package | **0** — o antigo 3,05 % era tamanho de Part com Y/Z trocado (D68) |
| Textura no Studio | `PreloadAsync` = `Enum.AssetFetchStatus.Success` (`rbxassetid://75934318775024`) |
| MCP do Studio | proxy **stdio**, 38 ferramentas; Studio 16c88345 respondeu na primeira tentativa |
| Assets R15 | Model `134628989553440` (39.004 B) · Image `75934318775024` — ambos Approved |

## Decidido (não reabrir)

`D3` CLI-only · `D9` QC sem bypass · `D11` GPU serializada · `D18` licença é gate · `D23` allowlist ·
`D24` estado central · `D25` isolamento · `D26` núcleo leve · `D27` SF3D encerrado ·
`D32` verify reexecuta G1–G9 · `D33` mesh exige `origem` · `D35` concept interno ao mesh ·
`D47` pivô por bone head · `D48` `.rbxlx` nativo · `D49`/`D50`/`D51` upload Open Cloud e textura
separada · `D52` colisor é hull fechado · `D53` G7 mede convexidade · `D54` CLIP 77 ·
`D55` rembg por alfa · `D56` CI no GitHub · `D57` delegação no `agentapi` · `D58` empunhadura 20 % ·
`D59` `flock` é o dono do lock · `D60` validação no Roblox via MCP · **`D62` `manifest@2` declara a
unidade** · **`D64` hull sobre nuvem de pontos** · **`D65` convexidade com tolerância de 1 mm/m** ·
**`D66` animação base por retarget** · **`D67` `manifest@3` declara `animacoes`** · **`D68` Part
permuta tamanho como centro** · **`D69` clipe do Roblox com `Priority=Core`** · **`D71` LOD medido por
silhueta** · **`D72` o nome fica `forge3d`** · **`D73` LFS nos repos de jogo** · **`D74` WFC próprio** ·
**`D75` P4 fatiada: `spec@3` + um setor por asset** · **`D76`/I15 projeto não entra no pipeline** ·
**`D77` portão da P4** · **`D78` ambiente WSL/UNC é o normal** ·
**`D79` parede cheia no lado fechado** · **`D80` `migrate` textual, sem inventar valor** ·
**`D81` CI de PR com Blender pinado por sha256 e `verify`** · **`D82` comando citado na doc é testado** · **`D83` a P6 é a última fase; o resto é backlog** ·
**`D84` orientação por contato da sola** · **`D85–D93` sync, qualidade 3D, request contract, armadura modular, ondas A–D e eixos (`v0.6.1`)** · **`D94–D102` releases `v0.7.0`/`v0.8.0` (`spec@5`/`manifest@5`, humanoide 3D CC0 vestido, props AA + vidro refrativo, dragão/montaria, Godot zero-click, Gemini Interactions + `visual_qa_critic` e TRELLIS MIT)** · **`D103–D107` release `v0.9.0` (`spec@6`/`manifest@6`, perfis `godot4-aa`/`roblox-aa-80` + Gate G11 80 % AA, bake Cycles High→Low `detalhe_alto` + `pbr_zonas`, Smart-Fit BVH + rig 56 ossos `godot-humanoid-aa@1`, Vault CC0 + `gemini-embedding-2` + kitbash + TRELLIS LoRA)** · **`D108–D111` release `v0.9.1` (`plan` calibrado, G11 multi-superfície validado no Godot 4.7.2, `GAP-019` e correções visuais `V1`–`V4`)** · **`D112–D113` release `v0.9.2` (Pixal3D MIT fora do bloqueio D18; `referencia_estilo` no concept, B23)**.

## Aberto

Nada em aberto: Q1 fechou em **D72** (`forge3d` fica) e Q7 em **D73** (LFS no repo do jogo).

**Plano de fases completo (P0–P6).** O que sobra é **backlog, não fase**: os 8 gaps de
`docs/gaps.md` (os de fase vencida valem como backlog) e a seção §Depois da P6 do `docs/roadmap.md`.

## Próximos passos — em ordem

| # | Ação | Custo | Ataca |
|---|---|---|---|
| **1** | Operação real: rodar a esteira num projeto de jogo e medir custo por asset (o adaptador HTTP só com consumidor não-Python) | 1 sessão | P6/roadmap |
| **2** | Revisão visual dos LODs no Godot e o `.rbxlx` com o clipe no Studio (cliente real) | 1 sessão manual | consistência |
| **3** | C12 nos destinos de malha que ganharam LOD (`kit_mesh` já republicado) | minutos | consistência |

## Comandos

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate

forge3d doctor
forge3d run   examples/lote_01.yaml          # blocky, sem GPU
forge3d run   examples/lote_09_r15.yaml      # R15 blocky, glb em studs
forge3d export-r15 examples/lote_09_r15.yaml --item personagem.r15.guard.01
forge3d verify ~/.local/state/forge3d/saida/r15
forge3d upload-model <glb> --creator-id 11966727684 --dry-run
forge3d gc --dry-run --manter-dias 30

python -m pytest                          # 523 verdes + 1 GPU
bash tools/ci.sh                          # 442 testes + ruff + mypy + contexto + P0 (job `portoes`)
bash tools/ci_verify.sh                   # 78 testes Blender + pipeline real + verify + Godot QA (job `verificar`)
bash tools/ci_dist.sh                     # wheel em venv limpo (job `distribuicao`)
bash tools/check-contexto.sh
python tools/check-p0.py
python tools/mcp_studio.py --estado       # Studio via MCP (precisa do MCP ligado)
python tools/r15_escala_studio.py         # Size/bones/textura do package R15 no Studio
python tools/conformidade.py              # tetos, I14, I12

# clipe base no Godot 4.3 headless (precisa de --path com o projeto minimo)
godot --headless --path tools/godot_project \
  --script "$PWD/tools/godot_anim_check.gd" -- <glb> idle

# clipe do .rbxlx medido no rig dentro do Studio (MCP ligado)
python tools/r15_anim_studio.py --clipe idle --tempo 0.5
```

## Armadilhas pagas (não repetir)

1. **O repo é ext4 e a sessão Windows o vê por UNC — não é alerta novo de cada sessão.** Medido em
   11/11/2026: criar arquivo novo, apagar e `mv` funcionam; **modificar arquivo existente falha**
   (`GetFileSecurityW EIO`), inclusive sobrescrever com `write`. Receita única: grave `<arquivo>.new`
   e troque com `mv` por WSL. Em lote o UNC é ~75× mais lento — por isso comando roda por `wsl.exe`.
2. **`convex_hull` do bmesh herda faces de entrada** → hull sobre **nuvem de pontos**, sem faces
   (D64). Recortar `hull["geom"]` não bastava: a face interior sobrevivia e o G7 reprovava.
3. **Mudou a saída? Suba `VERSAO`/`PIPELINE_VERSION`** — senão o cache serve o artefato velho (D6).
4. **Importador do Roblox: 1 unidade glTF = 1 stud** — resolvido por `escala_saida` no perfil (D62);
   não multiplique à mão no Studio.
5. **`escala_saida` é contrato**: mudou o perfil → republicar; `verify` reprova `@2` cuja escala
   declarada divirja do perfil atual, e reprova `unidades_export` que não seja recíproca.
6. **Command Bar do Studio é linha única**: script multi-linha colapsa e o `--` engole tudo → use MCP.
7. O **MCP** só lista o Studio com o proxy vivo alguns segundos; o binário muda por versão do Studio
   (`FORGE3D_STUDIOMCP`).
8. **Joelho e cotovelo giram em sentidos opostos**; peça de membro sobrepõe o pivô.
9. **Diffusers trunca prompt em 77 tokens em silêncio** (medido em `tools/concept_infer.py`).
10. **No `.rbxlx`, tamanho de Part permuta como o centro** (`x, z, −y`) — D68. Esquecer isso estica o
    rig em Y e o defeito se disfarça de "3 % de diferença".
11. **Blender com `--factory-startup` carrega o cubo default**: script de teste que importa e hull antes
    de limpar a cena junta o cubo ao asset e o resultado mente. `read_factory_settings(use_empty=True)`
    no começo.
12. **Tolerância de convexidade é de escala**: 1 mm/m (D65). Comparar hull de malha gerada com 1e-6 do
    diâmetro reprova colisor bom — foi o que a C12 achou.

## Como retomar

> **Estado**: P0–P6 + Ondas A–D + `v0.9.0`–`v0.9.3` fechadas (`spec@6`/`manifest@6`, `@1`–`@5` compatíveis).
> Correções P0 do handoff em `v0.9.3` (D114–D122); `mob_rig_v1` `verify` verde. Sobram do plano: D-07 (decisão
> template×concept), D-08 (retry de seed no G2), D-10 (doc do GameOne, fora do repo) e P1-4/P1-5/P2-* (A/B e
> medições). Próximo: operar num projeto de jogo e medir custo por asset. Não reabra D3–D111 sem fato novo.
> Sessão no Windows? Leia `AGENTS.md` §Ambiente **antes** de editar arquivo.
