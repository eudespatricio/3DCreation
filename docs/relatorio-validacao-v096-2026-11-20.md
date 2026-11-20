# Relatório de validação — boss Iron Ram no pipeline **v0.9.6** (20/11/2026)

> **Para quem vai validar e corrigir.** Este documento descreve o que foi executado, o que funcionou, os
> defeitos encontrados com evidência reproduzível, a causa provável de cada um e o critério de aceite da
> correção. Todos os números foram medidos nesta máquina; nenhum é estimativa.
>
> **Veredito curto:** o pipeline **entrega o asset** (QC aprovado, 15 partes, 16 ossos, clipes com
> amplitude), mas o **consumo no Roblox não funciona**: a animação exportada usa `Pose` **aninhada**, que o
> `Animator` não consome, e o `.rbxlx` referencia `MeshId`/texturas por **caminho local**, então o lugar
> abre sem geometria. O asset é bonito no render e invisível no Studio.

## 1. Ambiente

| Item | Valor |
|---|---|
| Forge3D | **0.9.6** (`pyproject.toml`, `__init__`, `post.PIPELINE_VERSION`), alterações **não commitadas** |
| SO / FS | WSL Ubuntu, repo em ext4 (`/home/eudespatricio/3DCreation`) |
| GPU | RTX 3060 Laptop 6 GB; outro daemon (`dark_studio_platform`) usando ~1,2–1,5 GB |
| Blender | 4.2.0 (pinado) |
| Roblox Studio | versão `version-8d7a1009c17e4ff8`, MCP via `tools/mcp_studio.py` |

## 2. O que foi executado

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate
forge3d validate ~/.local/state/forge3d/b_iron_ram/lote_iron_ram_v096.yaml      # ok
forge3d run     ~/.local/state/forge3d/b_iron_ram/lote_iron_ram_v096.yaml \
                --clean-dest --json                                            # exit 0
forge3d export-r15 ~/.local/state/forge3d/b_iron_ram/lote_iron_ram_v096.yaml \
  --item boss.iron_ram_colossus.v096.01 --modo-rig motor6d \
  --texturas-dir ~/.local/state/forge3d/saida/muralha_iron_ram_v096 \
  --saida       ~/.local/state/forge3d/saida/muralha_iron_ram_v096/iron_ram_v096.rbxlx
```

Lote: rota `mesh`, `origem` = concept aprovado (Gemini, 1376×768), `perfil: roblox-aa-80`,
`auto_rig: true`, `esqueleto: r15@1`, `clipes: [idle, walk]`, `partes` = 15 nomes R15,
`rig.modo: motor6d`, `colisao: convex`, `altura_metros: 3.3`. Caminho completo do lote no §8.

## 3. Resultados medidos

| Medida | Valor |
|---|---|
| `run` | **exit 0**, 1 publicado, QC **aprovado**, `pipeline 0.9.6` |
| Malha | **15.920 tris**, 15 partes watertight, 23 arquivos no destino |
| Rig | `r15@1`, **16 ossos**, 15 `Motor6D` |
| Clipes | `idle` 2,0 s (48 frames, 5 ossos) e `walk` 2,0 s (48 frames, 13 ossos) |
| Poses por clipe | **400** (`Pose` aninhadas; 25 keyframes × 16 ossos) |
| Amplitude | `idle` **5,3°**, `walk` **39,0°** (máx. rotação na árvore de poses) |
| Translação nas poses | máx. **0,099 studs** (não explica deformação) |
| Skinning no GLB | **1 skin, 16 joints**, `JOINTS_0` + `WEIGHTS_0` presentes |
| `export-r15` | `partes: 16`, `motores: 15`, `.rbxlx` 425.641 B |
| UV/bake (v0.9.6) | `smart_project` **66°** + `pack_islands` margem 0,004 — atlas com ilhas grandes (render aprovado) |
| G7/G12 | **aprovados** (a v0.9.5 reprovava: colisor côncavo e 2,291 mm mão×coxa) |

Render do asset (o pipeline entrega o visual): `docs/preview/` e `/tmp/preview_mobs/iron_v096_tres_quartos.png`.

## 4. Defeitos

### DEF-01 — `Pose` aninhada não é consumida pelo `Animator` — **crítico**

- **Sintoma:** no Studio, o `AnimationController`/`Animator` toca o clipe (`IsPlaying=true`, `len=2,00 s`)
  e **nada se move**: `Bone.Transform` permanece identidade (medido: `[demo8] nativo transform=0.0000`).
- **Evidência no artefato:** o `.rbxlx` traz a árvore
  `Pose HumanoidRootPart → Pose LowerTorso → Pose UpperTorso → Pose Head/LeftUpperArm/RightUpperArm`
  (e `LowerTorso → LeftUpperLeg → …`). `Keyframe:GetPoses()` do Roblox devolve **só o filho direto** —
  na prática, 1 pose de 400.
- **Código:** `src/forge3d/rbx_anim.py:50` — `_sequencia_xml` com docstring *“KeyframeSequence do Roblox
  com arvore aninhada de Pose R15 (D69 / F05)”*.
- **Causa provável:** o formato canônico do Roblox é **plano** — cada `Keyframe` tem `Pose` **irmãs**, uma
  por junta `Motor6D` (`Root`, `Waist`, `Neck`, `LeftShoulder`, …), sem aninhamento. A árvore aninhada
  descreve hierarquia de *bones*, não de *juntas*, e o `Animator` não a percorre.
- **Correção sugerida:** emitir `Pose` planas (uma por junta), com `CFrame` relativo ao repouso da junta;
  manter `Loop`, `Priority` e a conversão `m`→studs; remover o aninhamento.
- **Aceite:** no Play com `tools/r15_play_g14.py --clipe walk`, `G14_PLAY_PASS` com
  `max_ang_deg >= 5` e `max_pos_studs` compatível; braços sem achatamento.

### DEF-02 — G14 valida o aninhamento, não o playback — **alto**

- **Sintoma:** o `run` aprovou o asset (G14 “ok”) e o Play não move nada.
- **Evidência:** `src/forge3d/qc_roblox_anim.py:113` — o gate exige `pose_aninhada` verdadeiro e amplitude
  ≥ 5°, mas **não executa** o `Animator`. O gate premeia o formato do DEF-01.
- **Correção sugerida:** (a) trocar a asserção para `pose_plana` (todas as poses irmãs sob o `Keyframe`) e
  (b) rodar o harness Play (`tools/r15_play_g14.py`) quando houver Studio/MCP, marcando `skip` explícito
  quando não houver — nunca “ok” por omissão.
- **Aceite:** um asset com `Pose` aninhada **reprova** G14; um asset com `Pose` plana e Play verde passa.

### DEF-03 — `.rbxlx` sem `MeshId`/texturas válidos — **alto (bloqueia visual)**

- **Sintoma:** abrir o `.rbxlx` no Studio mostra só `HumanoidRootPart` invisível; o boss **não renderiza**.
- **Evidência:** no XML, `<Content name="MeshId"><null></null></Content>` em todas as 15 `MeshPart`; no
  `SurfaceAppearance`, `ColorMap = boss..._baseColor.png` (nome de arquivo). Logs do Studio:
  - `SurfaceAppearance.ColorMapContent has invalid texture '..._baseColor.png'. TexturePack only supports rbxassetid.`
  - `MeshContentProvider failed to process Head.glb because 'could not fetch'` (idem 15 partes).
- **Código:** `src/forge3d/rbx_r15_rig.py:106` — `_resolver_parte_mesh_uri` cai para `mesh_arquivo`
  (caminho local) quando não há `asset_ids`/ledger; `upload.py` só publica **Model/Image/Decal/Animation**
  (não existe `Mesh` no Open Cloud), então o id de mesh nunca é produzido pelo caminho atual.
- **Correção sugerida (uma das):**
  1. emitir o lugar com `Model` inserido por id (`InsertService:LoadAsset`) em vez de `MeshPart` solto; ou
  2. publicar as 15 partes como `Model` e gerar um módulo Luau com os ids (já existe
     `rbx_meshpart.py` que emite `MeshId + 4 mapas`), consumindo no Studio; ou
  3. **falhar** o `export-r15` com `FORGE-E-SPEC` quando `MeshId` não resolver, em vez de emitir `<null>`
     silencioso.
- **Aceite:** abrir o `.rbxlx` mostra as 15 partes com textura **sem passo manual**, ou o comando falha
  com mensagem acionável.

### DEF-04 — `Bone.Transform` não replica (informativo, para o validador não repetir o erro)

- `Bone.Transform` é **Not Replicated**. Pose aplicada em `Script` (servidor) não chega ao cliente;
  precisa ser `LocalScript`. Evidência: demo com pose no server não moveu; com `LocalScript` moveu.
- Consequência: qualquer solução de animação que dependa de `Transform` manual deve rodar no cliente —
  mais um motivo para o caminho nativo (`Animator`) ser o único aceitável.

### DEF-05 — Poses manuais não reproduzem o skinning (evidência de que o nativo é obrigatório)

Tentativas de animar por `Bone.CFrame` (para contornar DEF-01), com o clipe `walk`:

| Fórmula | Resultado visual |
|---|---|
| `rest × pose` | anima, mas **braços achatados/esticados** |
| `pose` absoluto | não testado |
| `rest × pose × rest⁻¹` | **malha colapsa** (boss vira bloco) |

Isso não é proposta de solução: é a prova de que o consumidor deve ser o `Animator` com o formato certo.

## 5. Verificado como corrigido nesta versão (não regredir)

| Item | v0.9.5 | v0.9.6 |
|---|---|---|
| UV/bake | `angle_limit=25°` → atlas fragmentado (milhares de micro-ilhas) | `66°` + `pack_islands` (`blender/postprocess_normals_uv.py:192`) → atlas com ilhas grandes, render aprovado |
| G7 colisor | reprovava (1 concavidade após hull) | aprovado |
| G12 separação | reprovava (`RightHand × RightUpperLeg`, 2,291 mm) | aprovado |
| Escala/pivô | — | G2 ok (`altura_export 11,78562`, delta 0 %) |

## 6. O que funciona (para o validador confirmar)

1. Concept → i23d → Forge3D → QC → 15 partes → manifesto com `partes`/`rig.ancoras` (23 arquivos).
2. `export-r15` monta 15 `MeshPart` + 15 `Motor6D` + `Humanoid` + `Animator` + 2 `KeyframeSequence`.
3. Geometria e skinning existem no GLB (`JOINTS_0`/`WEIGHTS_0`, 16 joints).
4. Visual: boss renderiza no Studio via `Model` publicado (demo) e **anima** por pose manual (com DEF-05).

## 7. Artefatos

| O que | Caminho |
|---|---|
| Lote | `~/.local/state/forge3d/b_iron_ram/lote_iron_ram_v096.yaml` |
| Destino publicado | `~/.local/state/forge3d/saida/muralha_iron_ram_v096/` (23 arquivos) |
| Place exportado | `.../muralha_iron_ram_v096/iron_ram_v096.rbxlx` (425.641 B) |
| Demos (workaround visual) | `.../iron_ram_v096_demo7.rbxlx` (pose A, anima), `demo8` (nativo+fallback), `demo9` (colapsa) |
| Model publicado | `120880990771470` (`Muralha_Boss_iron_ram_v096`, Approved) |
| Render | `/tmp/preview_mobs/iron_v096_tres_quartos.png`; atlas `docs/preview/bake_v3_vs_v095.png` |

## 8. Reprodução mínima do defeito crítico

1. Abrir `iron_ram_v096.rbxlx` no Studio → observar os erros de `MeshId`/`TexturePack` (DEF-03).
2. No `Forge3DR15`, `Play` e executar `tools/r15_play_g14.py --place <rbxlx> --clipe walk`.
3. Observar `transform=0.0000` (DEF-01) e o G14 estrutural verde (DEF-02).

## 9. Critérios de aceite da correção (ordem sugerida)

1. **DEF-01/02:** `Pose` plana por junta + G14 medindo Play real; `r15_play_g14.py` → `G14_PLAY_PASS`.
2. **DEF-03:** `.rbxlx` abre com geometria e textura sem passo manual **ou** `export-r15` falha explícito.
3. **Regressão:** `run` continua `exit 0`, QC aprovado, 15 partes, 16 ossos, 39° de amplitude; suíte verde.
4. **Visual:** o boss no Studio anda com braços corretos (sem DEF-05).

## 10. Perguntas em aberto

1. O consumidor final (jogo) vai tocar `Animation` nativa ou posar `Motor6D` por CFrame? Isso decide se
   DEF-01 é bloqueante ou só do exportador.
2. `Pose` aninhada foi decisão do D125 ou efeito colateral? O gate G14 e o exportador precisam concordar
   com **um** formato.
3. O `export-r15` deve exigir upload prévio de mesh (ledger) e falhar sem ele, ou gerar lugar com
   `Model` por id?


## 11. Resolução empírica no Studio MCP (v0.9.7)

Testes empíricos executados ao vivo no Roblox Studio via StudioMCP refutaram a hipótese inicial do DEF-01 (que atribuía a ausência de movimento ao aninhamento de `Pose`) e confirmaram o comportamento real do `Animator` com `KeyframeSequence`:

| Alvo no Studio | Formato `Pose` | Ângulo máx. medido | Juntas/Ossos movidos | Conclusão |
|---|---|---|---|---|
| Rig `Motor6D` R15 (`walk`) | **Aninhada** (`rbx_anim.py`) | **38,8°** | ativo | Mantido (`rbx_anim.py` intacto) |
| Rig `Motor6D` R15 (`walk`) | Plana (irmãs sob `Keyframe`) | **0,0°** | 0 | Descartado |
| Skinned `Bone` Model `120880990771470` | **Aninhada** (`rbx_anim.py`) | **38,8°** | **13 bones** | Funciona nativamente via `Animator` |
| Skinned `Bone` Model `120880990771470` | Plana (irmãs sob `Keyframe`) | **0,0°** | **0 bones** | Descartado |

### Correções aplicadas (v0.9.7)

1. **DEF-01 (resolvido por evidência):** `src/forge3d/rbx_anim.py` e a exigência `pose_aninhada=True` em `src/forge3d/qc_roblox_anim.py` foram mantidos intactos porque a hierarquia aninhada (`HumanoidRootPart → LowerTorso → ...`) é o formato que o `Animator` consome em `Motor6D` e `Bone` skinned (38,8° medidos vs 0,0° no plano).
2. **DEF-02 (`qc_roblox_anim.py` + `tools/r15_play_g14.{lua,py}`):**
   - `verificar_g14_animacao_roblox` agora aceita `play_report` opcional e registra `medido.play_studio` explicitamente (`{"status": "skip", "motivo": "studio_mcp_nao_executado"}` quando offline).
   - `tools/r15_play_g14.lua` passou a suportar `Humanoid` e `AnimationController`, aguardar 25 frames de `RunService.Heartbeat`, medir `Motor6D.Transform`, `Bone.Transform` e `BasePart.CFrame` e reportar `moved=<N>` (`G14_PLAY_PASS/FAIL max_ang_deg=... max_pos_studs=... moved=...`).
   - `tools/r15_play_g14.py` ganhou `--auto-play` (`start_stop_play` com parada no `finally`) e `--model-id` (carrega `_G14TestModel` no `Server` via `InsertService:LoadAsset` com `AnimationController`+`Animator` antes da probe no `Client`, removendo no `finally`).
3. **DEF-03 (`rbx_r15_model.py`, `rbx_r15.py`, `cli/parsers.py`, `cli/handlers_export.py`):**
   - `export-r15` passa a aceitar `--model-id <id|auto>` (gerando `.rbxlx` pronto para Play com `Forge3DLoadModel` no `ServerScriptService` e `Forge3DPlayAnim` em `StarterPlayerScripts` sem fallback manual de `Bone.CFrame`), `--asset-ids <json>` e `--rascunho-local`.
   - Para rotas não-blocky sem `--model-id` nem `--rascunho-local`, o CLI passa `exigir_asset_ids=True` e falha com `FORGE-E-SPEC` se alguma `MeshPart` ou canal de `SurfaceAppearance` não resolver para `rbxassetid://`.

## 12. Re-teste na v0.9.7 (20/11/2026) e novo defeito DEF-06

### 12.1 O que a v0.9.7 fechou

- `run` com o mesmo lote: **exit 0**, QC aprovado, 15 partes, 16 ossos, 23 arquivos.
- `export-r15 --model-id <id>`: `.rbxlx` com `Forge3DLoadModel` (ServerScriptService) e
  `Forge3DPlayAnim` (StarterPlayerScripts); sem `MeshPart` solto e sem `MeshId` nulo — **DEF-03
  endereçado** no fluxo com `--model-id`.
- **Play nativo medido:** `tools/r15_play_g14.py --place <rbxlx> --clipe walk --auto-play
  --model-id 72623231126473` →
  **`G14_PLAY_PASS max_ang_deg=38.75 max_pos_studs=0.0930 moved=13`**.
- **DEF-01 retirado:** a hipótese de que `Pose` aninhada era o problema está **refutada** — este teste
  confirma o §11: aninhada move (38,75°), plana move 0°, e a falha anterior era da demo que posava
  `Bone.CFrame` na mão. `rbx_anim.py` e a exigência de aninhamento em `qc_roblox_anim.py` estão corretos.

### 12.2 DEF-06 — pesos de skin dos membros (braços) — **alto**

- **Sintoma:** com a animação nativa tocando (13 juntas, 38,75°), os **braços deformam/esticam**; o resto
  do corpo anda normalmente.
- **Reprodução fora do Roblox:** o mesmo GLB, importado no Blender 4.2, com a ação `walk_Armature`,
  deforma igual — logo **não é o Roblox**: é o asset.
  - Repouso: `docs/preview/pose3q_repouso.png`
  - Frame 20 do walk: `docs/preview/pose3q_walk_20.png`
- **Medida objetiva (arestas, mesma topologia, frame 1 × frame 20):**
  - arestas: **28.264** · razão média **1,03** · **maior 10,98×** · **644 arestas > 1,5×**
  - 10 piores, com os grupos dominantes de cada vértice:

    | Razão | Vértices | Grupos |
    |---|---|---|
    | 10,98× | v8440/v9343 · v8439/v9342 | `LeftUpperLeg` ↔ `LeftHand` |
    | 8,51× | v7370/v7767 | `RightUpperArm` ↔ `UpperTorso` |
    | 8,09× | v4717/v4953 | `UpperTorso` ↔ `LeftLowerArm` |
    | 7,30× | v5847/v6383 | `RightUpperArm` ↔ `UpperTorso` |
    | 7,18× | v11672/v11673 | `LeftLowerArm` ↔ `UpperTorso` |
    | 6,49× | v12693/v12873 | `LeftHand` ↔ `LeftUpperLeg` |
- **Causa provável:** pesos automáticos (`autorig`) numa malha gerada e **fundida**: vértices vizinhos
  recebem ossos distantes (mão e coxa encostam na pose; antebraço e tronco idem). Quando a junta gira,
  a aresta entre eles estica até 11×. É o mesmo fenômeno que produziu o G12 de 2,291 mm na v0.9.5.
- **Correções sugeridas (ordem de custo):**
  1. **segmentar antes de rigar** e rigar por parte (rigidez por peça) — é o caminho R15/Motor6D e elimina
     esticamento por construção;
  2. manter skin, mas gerar pesos por **distância geodésica** com limite de influências (2–3), suavização e
     rejeição de pares que não têm aresta no mesmo grupo;
  3. **gate novo G16**: maior esticamento de aresta sob a animação ≤ 1,5× (medido no Blender, no mesmo
     passo do `run`), para o QC não aprovar pele que rasga.
- **Aceite:** com `walk` tocando, `max_ratio <= 1,5` e braços sem deformação visível; G16 verde no `run`.

### 12.3 Estado dos artefatos

| O que | Caminho |
|---|---|
| Destino v0.9.7 | `~/.local/state/forge3d/saida/muralha_iron_ram_v097/` |
| Place (model-id) | `.../iron_ram_v097.rbxlx` |
| Variante de visualização | `.../iron_ram_v097_view.rbxlx` (sem avatar + câmera orbitando) |
| Model publicado | `72623231126473` (`Muralha_Boss_iron_ram_v097`, Approved) |
| Renders do defeito | `docs/preview/pose3q_repouso.png`, `docs/preview/pose3q_walk_20.png` |
