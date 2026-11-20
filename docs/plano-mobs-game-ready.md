# Plano — mobs game-ready no Roblox: benchmark, contrato e fases (18/11/2026)

> **Base.** Sai do teste v2 (`docs/auditoria-mobs-roblox.md` §10). Decisão do operador nesta rodada:
> manter a qualidade do concept até a entrega, animações game-ready que o Roblox entenda e boss/mobs
> entregues em 5 partes (ou mais, se o caso pedir). Nenhuma mudança de código foi feita aqui: este
> documento é diagnóstico + contrato proposto + fases com portão.
>
> Regra do projeto que vale para tudo abaixo: contrato primeiro (`spec`/`manifest`), depois código; e
> instalar modelo/peso exige autorização explícita (D1).

## 1. Diagnóstico — onde a qualidade caiu (medido no teste v2)

| Etapa | O que entra | O que sai | Perda observada |
|---|---|---|---|
| Concept | prompt + style sheet | PNG 1376×768 | — (o concept é a referência boa) |
| Geração | concept | malha 15.920 tris | detalhe amaciado (chifres/crânio), textura borrada em áreas grandes |
| Separação | malha única | **nada** | braços fundidos ao torso: não existe estágio de partes |
| Rig | malha | 16 ossos `r15@1` + 2 clipes | clipes não dirigem o rig no Studio (G-09); `export-anim` grava nomes de junta (G-11) |
| Entrega | 1 MeshPart | consumidor espera 5 | fit com 2,93/2,87 studs de penetração nos braços (G-10) |

**Causa raiz (contrato, não bug isolado).** O `spec@6` modela “1 item = 1 malha + acessórios”
(`parte`: capa/cabelo/arma) e não tem campo de **partes articuladas** nem de **modo de rig de jogo**.
O consumidor modela “1 criatura = N partes com juntas”. Sem campo, o pipe Roblox do Forge3D não tem como
saber que precisa segmentar — e o QC não tem gate para isso.

## 2. Benchmark — como os produtores resolvem

| Produtor / fonte | Estágios | Saída | Tempo / custo | Lição para o Forge3D |
|---|---|---|---|---|
| [Tripo Rigging](https://developers.tripo3d.com/en/models/rig) | generate → **rig** (skeleton + peso; 7 tipos de criatura) | GLB/FBX rigado, nomes Tripo/Mixamo/ActorCore/Unity/Unreal/VRM | ~30 s · 25 créditos (~¥1,75) + Rig Check grátis | rig é chamada separada e o *naming* é escolhido pelo consumidor |
| [Meshy Auto Rigging](https://help.meshy.cn/pt-BR/articles/16231707-how-to-create-3d-animation-with-auto-rigging) | generate → remesh → **rig** → **animação** (600+ clipes) | FBX/GLB/USDZ animado, nomes Mixamo | ~30 s por rig | guia oficial: geometria fundida → **regenerar com separação explícita entre membros**; T/A-pose, simetria |
| [Hunyuan 3D-Part (P3-SAM)](https://www.tencentcloud.com/techpedia/146878) | generate → **segmentação semântica** (nomes de parte como prompt, por vértice) → X-Part | malha rotulada + partes; GLB multi-parte | 15 s para segmentar (90 s gerar, 40 s por parte nova) | “malha monolítica não articula”: segmentar é estágio próprio e nomear partes é input |
| [Roblox — rigging](https://create.roblox.com/docs/en-us/art/modeling/rigging) | importar rigado | R15 = 15 malhas + rig (padrão de avatar); R1 = 1 malha com ossos (bom p/ NPC, mas sem todos os recursos de animação/humanoid) | — | o alvo nativo do Roblox é **R15 por partes/juntas**; R1 com Bone é válido, mas de segunda classe |
| Roblox `segment_mesh` (nosso teste) | malha → partes nomeadas | 5 `MeshPart` + `SurfaceAppearance`, **0 ossos** | **40,1 s** [medido] | segmentação com nomes é viável dentro do Studio e preserva material |
| [Rodin for Game Development](https://rodin3ds.com/rodin-for-game-development/) | generate → assets para engine | GLB/FBX | — | posiciona-se como pipeline de produção por peça, não item único |

**Padrão do mercado:** três estágios separados e explícitos — **gerar**, **segmentar por nome**, **rigar/animar
com esqueleto padrão** — e o consumidor escolhe o *naming* (Mixamo/Tripo/R15). O Forge3D hoje faz gerar +
rigar genérico, e **não faz segmentar**; o consumidor dele (o jogo) já sabe o que quer receber.

## 3. Contrato proposto — aditivo ao `spec@6` / `manifest@6` (precedente D87/D113)

Campos aditivos (sem quebrar `@6`, precedente D87):

```yaml
# no item do lote
partes:                      # N partes; vazio = malha única (comportamento atual)
  - {nome: torso,  papel: corpo}
  - {nome: arm_l,  papel: membro, junta: LeftUpperArm}
  - {nome: arm_r,  papel: membro, junta: RightUpperArm}
  - {nome: leg_l,  papel: membro, junta: LeftUpperLeg}
  - {nome: leg_r,  papel: membro, junta: RightUpperLeg}
rig:
  modo: motor6d              # motor6d | skinned | none
  esqueleto: r15@1
  juntas: [HumanoidRootPart, LowerTorso, UpperTorso, Head, ...]
animacoes:
  - {nome: idle, formato: keyframe, alvo: motor6d, loop: true}
  - {nome: walk, formato: keyframe, alvo: motor6d, loop: true}
```

No `manifest@6` (aditivo):

- `partes[]`: `nome`, `papel`, `junta`, `pivo`, `ancora` (posição da junta no espaço do rig), `bbox`,
  `triangulos`, `arquivos` (GLB + mapas) — é o que o consumidor precisa para montar sem adivinhar.
- `rig.ancoras`: uma por junta, no espaço do rig. **Mata o G-01** (âncora recalculada por bbox no Luau).
- `animacoes[].formato` e `alvo`: hoje o manifesto diz `animacoes` sem dizer **em que** ela age.

**Regra de negócio nova (B25):** `partes` declarado e o perfil de destino com `partes_alvo` exige
correspondência 1:1 de nomes; nome ausente = falha (mesmo princípio do D-04 para sockets).

## 4. Pipeline alvo

1. **Concept** com `referencia_estilo` (D113) — o estilo entra como imagem, não só texto.
2. **Geração** — manter o gerador atual como piso; A/B TRELLIS × TripoSR por classe (ver §6, F4).
3. **Segmentação semântica** — recebe a lista de nomes de §3 e devolve N sub-malhas com juntas; pode ser
   local (P3-SAM-like) ou via MCP do Studio (`segment_mesh`), medindo as duas.
4. **Rig de jogo** — Motor6D por junta (R15) ou N juntas custom; âncoras exportadas para o manifesto.
5. **Animação** — `KeyframeSequence` com nomes de junta; validação em Play mode (não em Edit, onde o
   relógio não anda).
6. **QC** — G1–G15 (§5) com `verify` reexecutando.
7. **Publish** — Model com N partes + manifesto; o consumidor monta com `ancoras`, não com bbox.
8. **Consumidor** — fora do Forge3D (o jogo lê `partes`/`ancoras`).

## 5. Gates novos (QC)

| Gate | Mede | Critério inicial |
|---|---|---|
| **G12 separação** | partes disjuntas | interseção ≤ 2 mm nos vãos; nenhuma parte “colada” no torso |
| **G13 fit** | âncora ≠ junta | erro ≤ 1 mm entre `manifesto.ancoras` e o rig exportado |
| **G14 animação** | clipe move junta | ≥ 1 clipe com amplitude ≥ 5° e loop; playback medido em Play |
| **G15 fidelidade** | render × concept | SSIM/perceptual ≥ baseline medido no lote v2 (calibrar antes, sem inventar número) |

## 6. Fases, com portão de saída

| Fase | Escopo | Portão | Custo |
|---|---|---|---|
| **F0** | `partes`/`rig`/`animacoes` aditivos ao `spec@6` + `partes`/`rig.ancoras` no `manifest@6` + B25 + G12–G15 sem GPU | `check-p0` verde com schema novo; `pytest` verde | 1 sessão |
| **F1** | estágio de segmentação (nomes → N partes) | G12 verde em 3 bosses; 5 nomes exatos | 1–2 sessões |
| **F2** | rig de jogo com âncoras no manifesto | G13 verde; `verify` reexecuta | 1 sessão |
| **F3** | animação game-ready + playback no Studio | G14 verde medido no Studio (Play) | 1 sessão |
| **F4** | fidelidade: A/B TRELLIS × TripoSR + G15 | G15 com baseline; decisão documentada | precisa autorização (D1) |
| **F5** | integração no jogo (consumidor) | fora do Forge3D | projeto do jogo |

## 7. Critérios de aceite “game ready” (todos medíveis)

- **Partes:** N nomeadas, interseção 0 (≤ 2 mm), vãos visíveis, pivô na junta.
- **Rig:** juntas com os nomes do consumidor; âncoras com erro ≤ 1 mm.
- **Animação:** clipe com amplitude ≥ 5°, loop e playback real (Play mode), não só “IsPlaying”.
- **Fidelidade:** render × concept no baseline; a perda do i23d precisa aparecer no número, não no olho.
- **Orçamento:** ≤ 16.000 tris por parte, GLB ≤ 16 MB, texturas ≤ 2k (perfil `roblox-aa-80`).

## 8. Riscos e decisões abertas

1. **5 partes × R15 (15 partes):** o jogo usa 5 slots; o Roblox nativo é R15. R15 dá animação e
   `Humanoid` de graça, mas exige mudança no consumidor. Decidir antes da F2.
2. **TRELLIS/P3-SAM:** melhoram fidelidade/segmentação, mas instalar peso é D1 — só com autorização e
   A/B medido.
3. **Publicação de `Animation`:** o Open Cloud não aceita esse tipo (`FORGE-E-UPLOAD`). Ou o caminho é
   importar `.rbxmx` no Animation Editor, ou animar por Motor6D com clipe embutido no Model.
4. **Segmentação AI pode errar a junta:** medir IoU de junta contra o rig; sem número, não vale.
5. **Nada disso muda o pipeline sem contrato:** F0 vem antes de qualquer código (regra do repo).

## 9. Fontes

- Tripo Rigging — <https://developers.tripo3d.com/en/models/rig>
- Meshy Auto Rigging — <https://help.meshy.cn/pt-BR/articles/16231707-how-to-create-3d-animation-with-auto-rigging>
- Hunyuan 3D-Part (P3-SAM / X-Part) — <https://www.tencentcloud.com/techpedia/146878>
- Roblox — Rigging and skinning — <https://create.roblox.com/docs/en-us/art/modeling/rigging>
- Roblox — Bone — <https://create.roblox.com/docs/reference/engine/classes/Bone>
- Rodin for Game Development — <https://rodin3ds.com/rodin-for-game-development/>

## 10. Decisão (18/11/2026): modelo **A — R15 nativo (15 partes)**

**Decidido pelo operador:** adotar o padrão R15 do Roblox como alvo do contrato — 15 partes + 15 juntas
`Motor6D` — em vez do rig custom de 5 slots. Critério declarado: **qualidade de animação**; o custo de
trocar o consumidor de 5 para 15 slots é aceito agora. O Forge3D já tem o naming (`rig.mapas."r15@1"`),
o mapa `JOINT_R15` (`src/forge3d/rbx.py:47-63`) e o exportador Motor6D (`export-r15`).

### 10.0 Implementação do contrato (18/11/2026)

F0 executada como **aditivo ao `spec@6`/`manifest@6`** (precedente D87/D113), sem bump de versão:
`partes[]`, `rig{modo,esqueleto}` e `animacoes[]` no spec; `partes[]` e `rig.ancoras` no manifesto; regra
**B25** em `spec.py`; 5 testes em `tests/test_spec_partes_b25.py`. Suíte completa verde; `check-p0` segue
vermelho só pela falha pré-existente (`concept.json`).

**Re-teste pós-F0 (18/11, medido):** o mesmo concept, rodado com `partes` R15 + `rig.modo: motor6d` +
`animacoes`, **passou no `validate`/B25** e no `run` (1 publicado, QC aprovado, 15.920 tris) — mas o
**manifesto saiu sem `partes`, sem `rig.modo`/`ancoras` e sem `animacoes.formato/alvo`**: o pedido é aceito
e descartado na publicação (o produtor não os emite). No Studio o asset continua **1 MeshPart + 16 ossos +
AnimationController**, sem parte alguma e sem Motor6D; as texturas novas levam **~75 s** para aparecer
(moderação), então validar no Studio logo após o upload mostra o modelo branco. Conclusão: F0 fechou o
**contrato**, não a **entrega** — F1 (partes), F2 (manifesto/Motor6D) e F3 (animação) seguem abertas.

### 10.1 O que muda no contrato

- `partes` passa a ser a lista fixa R15 (15 nomes): `Head`, `UpperTorso`, `LowerTorso`,
  `LeftUpperArm`, `LeftLowerArm`, `LeftHand`, `RightUpperArm`, `RightLowerArm`, `RightHand`,
  `LeftUpperLeg`, `LeftLowerLeg`, `LeftFoot`, `RightUpperLeg`, `RightLowerLeg`, `RightFoot`.
- `rig.modo: motor6d`; `rig.juntas` = `JOINT_R15` (Root, Waist, Neck, LeftShoulder…RightAnkle).
- `animacoes[].alvo: motor6d` e os clipes já saem com nome de **junta** — o `export-anim` atual está
  correto para este alvo; quem estava errado era o rig skinned com nome de **parte**.
- `manifest.partes[].junta` + `rig.ancoras` obrigatórios (G13).

### 10.2 Restrições descobertas (medidas ou de contrato do tool)

1. **`segment_mesh` aceita no máximo 5 nomes por chamada** (schema do MCP). Para 15 partes é preciso
   **segmentação hierárquica**: 1ª chamada nos 5 grupos (torso/arm_l/arm_r/leg_l/leg_r) e mais 1 chamada
   por grupo para abrir em 3 (upper/lower/hand ou foot), total **6 chamadas** por boss.
   **Spike de 18/11 [medido]:** 6 chamadas, **218 s**, 15 nomes R15 exatos e `SurfaceAppearance` em todas
   — mas o corte é semântico e grosseiro: `Head` saiu com **6,84 studs** de altura contra `UpperTorso`
   **6,25**, sobrepostos em y≈8,4, e as pernas ficam escondidas sob o torso. **Nome certo não é junta
   certa.** Consequência para a F1: cortar por **posição de osso** (determinístico — o rig já tem as
   posições) em vez de por semântica AI; o `segment_mesh` fica como exploração, não como estágio de
   produção.
2. **`export-r15` recusa rota `mesh`** (`rbx.py:1685`, “so a rota blocky gera .rbxlx nativo”). Para o
   modelo A ele precisa aceitar o resultado da segmentação e montar 15 `MeshPart` + `Motor6D`.
3. **Custo de cena:** 15 partes = **15 draw calls por boss** (hoje 5). Com 5 bosses em cena: 75 dc —
   dentro do teto de 400 do perfil, mas entra no G11 e no `plan --scene-budget`.
4. **Material por parte:** cada uma das 15 partes precisa de `SurfaceAppearance` (o `segment_mesh`
   preservou o SA nas 5; com 15 é preciso conferir em todas).
5. **Moderação/upload:** 15 Models por boss (ou 1 Model com 15 partes — decidir no contrato).

### 10.3 Fases ajustadas ao modelo A

| Fase | Escopo com R15 | Portão |
|---|---|---|
| **F0** | `partes` R15, `rig.modo: motor6d`, `juntas`, `ancoras`, `animacoes.alvo` aditivos ao `@6`; B25; G12–G15 | `check-p0` verde com schema novo; `pytest` verde |
| **F1** | segmentação hierárquica até 15 partes (6 chamadas) **ou** segmentador local; medir IoU de junta | G12 verde em 3 bosses; 15 nomes exatos |
| **F2** | `export-r15` aceitar `mesh` + 15 `MeshPart` + `Motor6D` com `JOINT_R15` | G13 verde; `.rbxlx` abre no Studio com 15 juntas |
| **F3** | animação nativa: `KeyframeSequence` de junta no rig `Motor6D`, playback em Play mode | G14 verde medido no Studio |
| **F4** | fidelidade: A/B TRELLIS × TripoSR + G15 | precisa autorização (D1) |
| **F5** | consumidor: `HordeKit` 5 → 15 slots (fora do Forge3D) | projeto do jogo |

### 10.4 Risco principal do A

O ganho de animação só se realiza se o consumidor migrar para 15 slots. Até lá, o asset R15 fica pronto
mas sem uso no jogo — e o `HordeKit` atual continua com 5 partes e posing por CFrame. A F5 é pré-requisito
para o ganho aparecer em tela.

### 10.9 F1+F2 executados (18/11/2026)

- **Segmentação por osso** (`blender/split_por_ossos.py` + `src/forge3d/segmentacao.py`): cada triângulo
  vai para o osso mais próximo do seu centroide; nenhum triângulo é perdido — **15.920 = 15.920** [medido]
  no boss v3. Pivô de cada parte na cabeça do osso; âncora, bbox e tris vão para o manifesto.
- **Manifesto**: `partes[]` (15), `rig.modo: motor6d`, `rig.ancoras` (15) e **15 arquivos** com
  `papel: parte`; o `manifest@6` passou a aceitar `papel: parte` e `partes[].arquivo`.
- **Portões**: `verify` verde no destino v3; suíte **539 passed, 1 skipped**; `conformidade` e
  `contexto` verdes; `check-p0` segue vermelho só pela falha pré-existente (`concept.json`).
- **Versão**: `PIPELINE_VERSION` **0.9.4** (D6/D124).
- **O que ainda falta para o Roblox**: montar os `MeshPart` + `Motor6D` num `.rbxlx`
  (`export-r15` ainda recusa `mesh`), testar o playback do clipe nesse rig (F3) e migrar o consumidor
  de 5 para 15 slots (F5).

### 10.10 F2b — montagem Motor6D no Studio (18/11/2026)

- **Feito:** as 15 partes foram combinadas num GLB (1 upload, Model `101811909002145`) e inseridas no
  Studio; com as `ancoras` do manifesto, o Luau criou **15 `Motor6D`** com os nomes de junta corretos
  (`Root`, `Waist`, `Neck`, `LeftShoulder`…`RightAnkle`) — medido, não presumido.
- **Não funciona ainda:** o clipe de junta não move as partes. Três tentativas, sempre `t≈0,85 s`,
  `len=2,00 s`, delta **0,000** em `LeftLowerLeg`: (1) `AnimationController:LoadAnimation` com partes
  ancoradas; (2) idem com só a raiz ancorada; (3) `Animator:LoadAnimation`. O `KeyframeSequence` carrega,
  o relógio anda e nada se move.
- **Duas lacunas visíveis no teste:** o GLB combinado sai sem textura (as partes não têm
  `SurfaceAppearance` — os mapas são do asset, não das partes) e o rig montado flutua/acomoda errado ao
  desancorar, porque o pivô é a junta e a raiz é um `Part` invisível.
- **Leitura:** o problema não é mais o asset nem o contrato — é o **mecanismo de playback** de um
  `KeyframeSequence` registrado por `KeyframeSequenceProvider`. O caminho sancionado pela Roblox é o
  Animation Editor (importar/autorar e publicar), que o Open Cloud não cobre para `Animation`.

**Próximo teste decisivo:** autorar/importar UM clipe curto pelo Animation Editor no rig montado. Se
mover, o Forge3D precisa emitir o `.rbxmx` no formato que o editor aceita; se não mover, o problema é o
rig/`Motor6D` e volta para a mesa de montagem.
