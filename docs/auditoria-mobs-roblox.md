# Auditoria — processo de criação dos mobs do jogo Roblox (18/11/2026)

> **Escopo.** Como nascem os mobs (horda e bosses) do projeto `jogo-roblox` — "Muralha" —, com o boss do
> Ato 1 (`iron_ram_colossus`) como caso de ponta a ponta. Espelha a auditoria do GameOne
> (`docs/avaliacao-qualidade-3d.md` §6): o objetivo é saber **o que a esteira garante e o que ela não
> garante**, não opinar sobre o jogo.
>
> **Método.** Somente leitura no repo do jogo: código, specs, manifestos, ledgers e recálculo de hashes
> nesta sessão. Nenhum asset foi gerado, modificado ou publicado. Número sem fonte é `[estimado]`;
> todo o resto é `[medido]` com o arquivo citado.

## 1. O processo em seis elos

| # | Elo | Ferramenta / arquivo | Saída | Garante |
|---|---|---|---|---|
| 1 | Geometria | Blender headless por script (`art/scripts/make_horde.py`, `make_bosses.py`, `lowpoly_lib.py`) | `.glb` em `art/export/`, 1 unidade Blender = 1 stud | silhueta, orçamento por peça, pivô |
| 2 | Lote | o próprio script escreve `art/forge/lote_*_import.yaml` (`spec@6`) | spec versionado | reprodutibilidade do pedido |
| 3 | QC + PBR | `forge3d validate` → `run` → `verify` (G1–G11, `detalhe_alto`, `pbr_zonas`) | `~/.local/state/forge3d/saida/muralha_<grupo>/` + `manifest@6` | geometria, PBR, orçamento de cena, proveniência |
| 4 | Sincronização | `tools/art-pipeline.sh` (SHA-256 `saida/` → `art/export/`) | GLB pós-processado no repo (LFS) | o que está no git é o que passou no QC |
| 5 | Publicação | `tools/publish-v09-opencloud.py` (Open Cloud, `strip_embedded_textures=true`) | ids no ledger + catálogos Luau patchados | identidade do asset publicado |
| 6 | Runtime | `MeshAssetsBoot` (InsertService) → `HordeKit` (5 slots + posing procedural) | boss articulado em cena | escala e estado de combate (encaixe de junta **não** — G-01) |

## 2. Elo por elo

### 2.1 Geometria — Blender por script

- Horda: 8 classes (`make_horde.py`), 1 malha por classe, `1.650–4.628` tris. Boss: corpo completo + 5
  sub-malhas (`torso`, `arm_r`, `arm_l`, `leg_l`, `leg_r`) por boss, com `SCALE` 2,4–2,75 × 1,8.
- Regras de calibração do repo (`art/README.md`): 1 BU = 1 stud, pivô na base (corpo/torso) ou na origem
  (membros), frente `-Y` no Blender = `-Z` no Studio, transforms aplicados.
- Os membros usam `center_xy=False` + `pivot: origem` de propósito: é o encaixe de junta que o runtime
  procura na âncora. Trocado isso, a peça "flutua" ou afunda.
- Orçamento por peça: corpo ≤ 17.900, torso ≤ 5.800, braço ≤ 3.700, perna ≤ 2.500 tris.

### 2.2 Lote — `spec@6`, perfil `roblox-aa-80`

- O script mede a altura do GLB e grava `altura_metros = studs × 0,28` (1 stud = 0,28 m). Não se edita o
  lote à mão: regenera-se.
- Corpo e torso recebem `detalhe_alto` (bevel 8 mm, crease 40°) e 6–11 `pbr_zonas`; **membros não têm
  `pbr_zonas`** (`material: opaque`) e por isso saem do Forge3D sem mapas próprios — no runtime caem no
  `MASTER_ATLAS` (tier Atlas). É o "PBR em 2 tiers" documentado em `docs/ferramentas.md` §4.2.

### 2.3 QC e PBR — Forge3D 0.9.0 (o que o log diz) [medido]

- `art/renders/_logs/run_bosses.json`: `publicados=30`, `reprovados=0`, `falhas=0`, `pipeline_version=0.9.0`,
  `perfil=roblox-aa-80`, `spec_hash=sha256:684a6f…`, `exit=0`.
- `verify_bosses.json`: 30/30 com `manifest@6`, `qc_reexecutado=true`, `escala_saida=3,5714` (= 1/0,28),
  `licenca="asset de autoria propria"`, `ok=true`.
- G11 (orçamento de cena): 25 lotes (5 bosses × 5 partes), **80.782 tris**, **25 draw calls** estimados,
  **60 texturas únicas**, **93,33 MB** de VRAM → **20,2 %** do teto de 80 % AA (400 mil tris).
- Proveniência conferida nesta auditoria: para os 30 manifestos, o `sha256` do mesh é **igual** ao
  `sha256` do `.glb` em `art/export/` — 30/30. A cadeia local não está furada.

### 2.4 Sincronização e publicação

- `art/export/` é o ponto de verdade do repo; o pipeline só copia para lá depois do `verify` e confere
  SHA-256 de cada par (30 GLBs por grupo).
- `publish-v09-opencloud.py`: **97 Model + 141 Image** no ledger [medido]; a chave de cache é
  `sha256(bytes) + "|strip=1"` — **não** é o hash do arquivo, então comparar com `art/export` exige
  recalcular com o mesmo sufixo. Os 30 modelos de boss estão `Approved`.
- Os ids vão para `MeshAssets.luau` (`BOSSES`, `BOSS_PARTS`), e `sim/visual-contract.luau` assegura 5
  bosses, 25 slots, ids únicos, labels e cores.

### 2.5 Carga e montagem — o que acontece no jogo

- `MeshAssetsBoot.server.luau` carrega, via `InsertService:LoadAsset`, **os 5 corpos completos e as 25
  partes** (além de traps/horda/props/fauna/portais), aplica `SurfaceAppearance` (Hero ou Atlas) e
  `RenderFidelity.Precise`. Sem place publicado/moderação aprovada, cai no fallback em blocos com `warn`.
- `HordeKit.createBoss` monta a criatura em **5 slots**: torso escalado a `0,58 × height`, pernas a
  `0,42 × height`, braços herdando a escala do torso. A âncora de cada junta é uma fração do bounding box
  (`computeBossPartAnchor`), não um dado exportado do Blender.
- Animação: **posing procedural por CFrame** a cada `stepBoss` (`sampleBossLegStride`, ataque, stagger,
  enrage e morte por boss). `grep -c Motor6D` no `HordeKit` = **0**; `Motor6D` só aparece em `Vfx.luau`
  (ragdoll/projéteis). Os 30 manifestos têm `animacoes: []`.
- Fallback: `buildBossFallbackRig` monta blocos enquanto o mesh não chega; quando as 5 partes montam, o
  fallback é destruído (`HasMeshVisual = true`).

### 2.6 Combate e campanha

- `src/shared/sim/core.luau` `BOSS_SPECS.iron_ram_colossus`: `hp 420·MILLI`, `armorMilli 150`, `speedMilli 800`,
  `laneSpan 3`, `staggerCapMilli 600`, `abilityCdTicks 240`, `wallDmg 60·MILLI`, `wallAttackCdTicks 30`.
- `CampaignCatalog`: 5 atos × 5 estágios; o estágio `1-5` é "Colosso Aríete de Ferro" com
  `bossId = iron_ram_colossus` — o boss da primeira campanha.
- `RaidClient` cria o boss no cliente a partir do replay; a simulação é server-authoritative — o visual
  não decide dano. A fala do print ("Stone and timber? …") é `boss_quote_iron_ram_colossus_intro`.

## 3. Números por boss [medido]

| Boss | Ato | Corpo | Torso | Braço D | Braço E | Perna D | Perna E | Σ partes |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `iron_ram_colossus` | 1 | 16.596 | 5.468 | 3.220 | 3.512 | 2.198 | 2.198 | 16.596 |
| `slag_juggernaut` | 2 | 16.410 | 5.546 | 3.394 | 3.158 | 2.156 | 2.156 | 16.410 |
| `rime_matriarch` | 3 | 17.068 | 5.324 | 3.280 | 3.240 | 1.966 | 1.966 | 15.776 |
| `powder_baron` | 4 | 16.396 | 5.508 | 3.152 | 3.156 | 2.044 | 2.044 | 15.904 |
| `rift_titan` | 5 | 16.096 | 5.316 | 3.384 | 3.236 | 2.080 | 2.080 | 16.096 |

## 4. O que a esteira garante — e o que ela não garante

**Garante:** orçamento por peça e de cena (G11), topologia/UV/material (G1–G5), orientação (G2), PBR em
dois tiers consistente, escala de export recíproca, proveniência (sha256 manifesto ↔ `art/export`),
identidade do asset publicado (ledger ↔ `MeshAssets`) e um contrato que exige 5 bosses × 5 slots.

**Não garante:**

1. **Encaixe de junta.** A âncora é recalculada no Luau por fração de bbox; o QC julga cada peça isolada.
   Mudar a proporção de um membro no Blender não quebra gate nenhum e não acende teste nenhum.
2. **Proporção do boss montado.** O runtime reescala cada peça para o esqueleto dele, não para o modelo:
   o torso autoral entra a `0,63–0,69×` e a perna a `0,98–1,13×` (§5, G-02). A silhueta em jogo é mais
   baixa de tronco e mais alta de perna que o GLB e que o card.
3. **Corpo × partes.** Em 3 dos 5 bosses a soma das partes é exatamente o corpo; em `rime_matriarch`
   (+1.292) e `powder_baron` (+492) o corpo tem triângulos que nenhuma parte carrega.
4. **Arte de card.** Os 15 PNG 512×768 estão no git e publicados, mas não há gerador no repo — só o
   publicador. O card não é reproduzível pela esteira.
5. **Frescor Cloud × repo no merge.** O ledger tem digest recalculável, mas nenhum teste compara.

## 5. Gaps com evidência (ordenados por risco)

| ID | Risco | Evidência | Correção |
|---|---|---|---|
| **G-01** | **Alto** — âncoras de junta duplicadas no Luau (`computeBossPartAnchor`, `computeBossRigMetrics`), sem contrato; geometria nova desalinha em silêncio | `HordeKit.luau:1003-1063`; `sim/visual-contract.luau:400-416` valida só ids/labels/cores/escala | exportar âncoras do Blender em JSON, gerar tabela Luau e validar faixa no contrato |
| **G-02** | **Alto** — proporção in-game ≠ autoral: torso `0,63–0,69×`, pernas `0,98–1,13×`; `height` do `VisualTheme` é a única fonte e não é testada contra o GLB | §3 e tabela abaixo; `HordeKit.luau:1003-1051` e `1193-1269` | decidir: aceitar o fit (e renderizar o card na proporção de jogo) ou alinhar `0,58/0,42` ao autorado |
| **G-03** | **Médio** — os 5 corpos completos são carregados no boot e replicados, **sem consumidor de runtime** (só card e contrato): 82.566 tris e 5 conjuntos PBR de "carga morta" por join | `MeshAssetsBoot.server.luau:150-152`; nenhum uso de `MeshAssets.BOSSES` no `HordeKit` | marcar `uso=card` e não carregar no boot, ou remover do conjunto publicado |
| **G-04** | **Médio** — corpo ≠ união das partes em 2 de 5; o card pode mostrar detalhe que o boss em jogo não tem | tabela §3 | decidir se o corpo é "versão de card" (e documentar) ou se deve ser a união exata |
| **G-05** | **Médio** — cards sem gerador: mesma classe do gap de textura do GameOne (`_v09b_256`); 15 PNG publicados, e o docstring do publicador ainda diz 10 | `grep -rni cards` em `art/`, `tools/`, `scripts/`: só o publicador; ledger tem 15 entradas `cards.*` | script de render 512×768 + upload |
| **G-06** | **Baixo** — doc drift: `docs/animacoes-fisica-real-e-vfx.md` §2.1 diz "rigs articulados usam `Motor6D.Transform` via molas"; o `HordeKit` tem 0 `Motor6D` | `grep -c Motor6D src/client/visual/HordeKit.luau` = 0 | corrigir o §2.1 (posing por CFrame; `Motor6D` só em VFX) |
| **G-07** | **Baixo** — os 97 modelos da leva v1.9 estão publicados com nome `_v18` | ledger: `Counter({'v18': 97})` | nomear pela leva (ou declarar que o nome não versiona) |
| **G-08** | **Médio** — nada no CI compara Cloud × `art/export`; o digest do ledger existe mas ninguém o recalcula | `publish-v09-opencloud.py:252-255`; conferência manual desta auditoria: 68/68 dos mapeáveis batem | check de digest no `check.sh` + tabela de nomes compartilhada |

**Escala autorada × escala de jogo [medido]**

| Boss | `height` (studs) | Torso autoral | Torso no jogo (`0,58×h`) | Fator | Perna E autoral | Perna E no jogo (`0,42×h`) | Fator |
|---|---:|---:|---:|---:|---:|---:|---:|
| `iron_ram_colossus` | 11,5 | 9,81 | 6,67 | 0,68 | 4,77 | 4,83 | 1,01 |
| `slag_juggernaut` | 12,0 | 10,04 | 6,96 | 0,69 | 4,63 | 5,04 | 1,09 |
| `rime_matriarch` | 12,4 | 11,45 | 7,19 | 0,63 | 4,94 | 5,21 | 1,06 |
| `powder_baron` | 11,8 | 10,36 | 6,84 | 0,66 | 4,40 | 4,96 | 1,13 |
| `rift_titan` | 13,6 | 12,12 | 7,89 | 0,65 | 5,80 | 5,71 | 0,98 |

> O `altura_metros` do lote (`12,959` studs no Ato 1) é referência de autoria, **não** a altura no jogo
> (`11,5`). São três réguas: lote, esqueleto de runtime e bbox da peça.

## 6. Receita para o próximo mob

```bash
cd ~/jogo-roblox

# 1. geometria: novo script (ou função no script do grupo) usando lowpoly_lib; 1 BU = 1 stud, pivô base/origem
# 2. esteira completa do grupo (Blender -> Forge3D -> verify -> sync -> lineup)
FORGE_JOBS=4 bash tools/art-pipeline.sh --only bosses

# 3. conferir os três logs e o orçamento
python3 - <<'PY'
import json
for n in ("validate", "run", "verify"):
    d = json.load(open(f"art/renders/_logs/{n}_bosses.json"))
    print(n, d.get("resumo") or d.get("ok"), d.get("orcamento_cena", {}).get("medido", {}).get("triangulos_cena"))
PY

# 4. publicar (dry-run primeiro: imprime o plano e nao sobe nada)
python3 tools/publish-v09-opencloud.py --dry-run
python3 tools/publish-v09-opencloud.py     # atualiza o ledger e patcha MeshAssets.luau

# 5. contrato visual + build
luau sim/visual-contract.luau
bash scripts/check.sh
```

Depois do passo 4, o elo que **continua manual** é a ligação com o jogo: `VisualTheme.BOSSES`,
`core.luau` `BOSS_SPECS`, `CampaignCatalog` (estágio de boss), i18n e o teste no Studio publicado
(`InsertService` exige moderação aprovada).

## 7. Correções propostas, em ordem de custo/valor

1. **Âncoras como dado (G-01/G-02).** `make_bosses.py` já sabe onde põe cada junta: exportar um JSON por
   boss (posição local de cada pivô + offsets de encaixe), gerar `BossRigAnchors.luau` na esteira e fazer
   o `HordeKit` ler dele. O `visual-contract` passa a validar faixa, não só id. É a correção que impede o
   defeito silencioso do próximo mob.
2. **Digest no CI (G-08).** Um check de ~20 linhas no `check.sh`, com a tabela de nomes que hoje só existe
   dentro do publicador.
3. **Destino do corpo completo (G-03/G-04).** Decidir: card-only (não carregar no boot) ou união exata das
   partes. Hoje ele é meio-termo: existe, pesa e não aparece em jogo.
4. **Script de cards (G-05).** Renderizar 512×768 a partir do mesmo corpo, com câmera fixa, para o card ser
   regenerável como o resto.
5. **Doc (G-06) e nome (G-07).** Baratos; evitam que a próxima sessão "descubra" que não há `Motor6D`.

## 8. Evidências e como refazer

| O quê | Onde |
|---|---|
| Lote e PBR por boss | `art/forge/lote_bosses_import.yaml` (gerado por `art/scripts/make_bosses.py`) |
| Run/QC/G11 | `art/renders/_logs/run_bosses.json`, `verify_bosses.json`, `validate_bosses.json` |
| Manifestos e mapas | `~/.local/state/forge3d/saida/muralha_bosses/` |
| Publicação | `art/renders/_logs/opencloud_v09_ledger.json` (97 Model + 141 Image) |
| Contrato de asset | `src/shared/visual/MeshAssets.luau`, `sim/visual-contract.luau` |
| Montagem/posing | `src/client/visual/HordeKit.luau` (1003–1063, 1179–1281, 1756–1792, 3115–3189) |
| Carga no jogo | `src/server/world/MeshAssetsBoot.server.luau` (150–160) |
| Combate/campanha | `src/shared/sim/core.luau` (182–251), `src/shared/campaign/CampaignCatalog.luau` (120, 329) |

Recálculo feito nesta auditoria (somente leitura): `sha256` dos 30 GLBs × manifesto (30/30 iguais) e
digest `sha256(bytes)+"|strip=1"` dos 68 modelos mapeáveis × ledger (68/68 iguais).

## 9. Perguntas para o operador

1. **Corpo completo:** fica como arte de card (e sai do boot) ou vira a união exata das partes?
2. **Proporção:** aceitar o fit do runtime (`0,58/0,42`) e passar a renderizar o card nessa proporção, ou
   ajustar as peças para o autorado?
3. **Animação:** os mobs seguem 100 % procedurais (sem clip) ou vale abrir a rota `rig`/`animacoes` do
   Forge3D para um mob com ciclo real? Hoje `animacoes: []` em todos os 30 — não há retarget a perder, mas
   adotar clip custa `Motor6D` + replicação.

## 10. Teste v2 — prompt → concept → malha → Studio (18/11/2026)

> **O que este teste responde.** A v1 nasceu de script procedural, sem prompt. Este teste percorre a cadeia
> que o jogo nunca usou: prompt → concept (Gemini) → i23d → Forge3D (`mesh`, `roblox-aa-80`, rig `r15@1`)
> → Studio → segmentação. Rodado nesta sessão; nada foi escrito no repo do jogo.

### 10.1 Concept [medido]

- Prompt (campo `prompt` + sufixo padrão da esteira):
  > Boss concept art of the IRON RAM COLOSSUS, a colossal bipedal siege golem: dark riveted iron plates,
  > ram skull head with two huge curved ivory horns, a battering-ram head embedded in the chest, amber
  > furnace light glowing through armor seams and vents, ember sparks, soot-stained steel, heavy armored
  > legs, oversized fists, small amber eyes, imposing wide silhouette, full body, front view.
- Negative: `background scenery, multiple characters, text, watermark, extra limbs, thin weak legs,
  cartoon mascot, blurry, cropped head, horns cut off`.
- Provider `gemini-nano-banana-2.1`, seed `20261118`, **24,65 s**, **1376×768 reais** (pedido 512×512 —
  o provider ignora a dimensão; `largura_real`/`altura_real` registrados, D-05).
- PNG `~/.local/state/forge3d/b_iron_ram/concept.png` (sha256 `b8835dec1161aafe…`), licença comercial ok.

### 10.2 Malha [medido]

- Lote `~/.local/state/forge3d/b_iron_ram/lote_iron_ram_v2.yaml` (`spec@6`, `origem` = concept,
  `auto_rig: true`, `esqueleto: r15@1`, `clipes: [idle, walk]`, `altura_metros: 3.3`).
- `forge3d run` 0.9.3: **1/1 publicado**, QC **aprovado**, **15.920 tris**, GLB 3,2 MB, 5 mapas 1024²,
  BBOX **11,79 studs** (o slot do jogo é 11,5).
- Rig `r15@1` com **16 ossos**; clipes `idle` e `walk` de 2,042 s; amplitude máxima no `.rbxmx`:
  **idle 2,4°**, **walk 39°** (joelho).
- Godot 4.7.2 (`tools/godot_anim_check.gd`): `GODOT_ANIM_OK` — idle 6 tracks / **0,0698 rad**;
  walk 14 tracks / **0,6282 rad**; ambos com loop.

### 10.3 Studio [medido]

- Upload Open Cloud: Model **`74299415034262`** (`Muralha_Test_iron_ram_v2`), moderação **Approved**.
- `insert_asset` no Baseplate: **1 MeshPart + 16 Bone + AnimationController + SurfaceAppearance**,
  tamanho **12,98 × 11,79 × 7,60 studs**.
- Girar `Head`/`LeftUpperArm`/`RightUpperArm` por Luau **deforma a malha** — a pele é válida.
- **Animação por asset não aplica:** `KeyframeSequenceProvider:RegisterKeyframeSequence` +
  `AnimationController:LoadAnimation` toca o track (`t=1,896 s`, `len=2,00 s`, `IsPlaying=true`), mas
  `Bone.Transform` fica identidade nas duas nomenclaturas testadas (R15 e junta). `upload-animation`
  também falha (`FORGE-E-UPLOAD: Unknown Error`).

### 10.4 Segmentação [medido]

- `segment_mesh` (AI do Studio): **40,1 s**, 5 partes com os nomes do `HordeKit`
  (`torso`, `arm_l`, `arm_r`, `leg_l`, `leg_r`), **0 ossos**, `SurfaceAppearance` preservado
  (ColorMap `139615929752439`).
- Tamanhos: torso `10,71 × 8,60 × 7,17` · arm_l `3,55 × 6,05 × 4,33` · arm_r `3,40 × 6,37 × 4,28` ·
  leg_l `3,13 × 5,25 × 3,92` · leg_r `2,90 × 5,05 × 4,22`.
- Frente em `-Z` (câmera em `+Z` mostra as costas), igual à convenção do perfil.

### 10.5 Fit com o runtime [medido]

- Reescala do `HordeKit` (`h = 11,5`; `torsoH = 6,67`, `hipY = 4,83`, `hipX = 1,84`, `shoulderX = 2,60`):
  torso **8,31 × 6,67 × 5,57**; braços `2,75 × 4,70` / `2,64 × 4,94`; pernas `2,89 × 4,83` /
  `2,77 × 4,83`; BBOX montada **8,31 × 11,31 × 5,57**.
- **Penetração dos braços no torso: 2,93 / 2,87 studs** — o ombro precisaria de ~**5,5**, não 2,60.
  Na pose parada a interseção fica dentro do volume; ao girar o braço, ele corta o torso.

### 10.6 Gaps novos

| ID | Risco | Evidência | Correção |
|---|---|---|---|
| **G-09** | **Alto** — animação por asset não chega ao Roblox | §10.3: track toca, osso não move; `upload-animation` inexistente | importar `.rbxmx` no Animation Editor (manual) ou corrigir export/nomes; ou animar por osso |
| **G-10** | **Alto** — as 5 partes não assentam no esqueleto atual | §10.5: 2,9 studs de penetração nos braços | métricas por boss (`shoulderX`/`hipX` do asset) ou mesh mais estreito |
| **G-11** | **Médio** — `export-anim` grava nomes de junta (`Root`, `LeftKnee`) enquanto o mesh tem ossos R15; Open Cloud não publica Animation | §10.2/§10.3 | mapear nomes no exportador e documentar o caminho de publicação |

### 10.7 Opções de runtime (medidas, não implementadas)

1. **5 partes + métricas por boss** — sem mudar o asset; exige `computeBossRigMetrics`/
   `computeBossPartAnchor` lerem o asset (código).
2. **Posing por ossos** — o `HordeKit` posa `Bone.Transform` (já provado que deforma); dispensa asset de
   `Animation`; código novo no cliente.
3. **Animation nativa** — importar os clipes no Animation Editor e usar `AnimationController`; depende do
   G-09.

### 10.8 Artefatos do teste

- Concept/meta: `~/.local/state/forge3d/b_iron_ram/concept.png`, `concept_resultado.json`.
- Saída: `~/.local/state/forge3d/saida/muralha_iron_ram_v2/` (GLB, `manifest@6`, 5 mapas, `.rbxmx` dos clipes).
- Asset: Model `74299415034262`; Baseplate de teste com o modelo e o `FIT_TEST`.
- Imagens: `docs/preview/v2_iron_ram_cadeia.png`, `v1_v2_distancia.png`, `studio_v2_rig.png`,
  `v1_ingame_vs_v2_play.png`, `v2_rig_vs_segmentada.png`.
- Nada foi escrito no repo do jogo; o place usado foi o Baseplate novo, não o playtest.
