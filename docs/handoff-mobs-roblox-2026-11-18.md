# Pausa 18/11/2026 — mobs Roblox: estado, entregas e retomada

> Documento de pausa. Complementa `CONTINUAR.md` (que está no teto de 200 linhas) e os dois documentos
> temáticos desta janela: `docs/auditoria-mobs-roblox.md` (v1 e teste v2) e
> `docs/plano-mobs-game-ready.md` (benchmark, contrato e fases). Nada aqui é estimativa sem rótulo:
> todo número foi medido nesta máquina.

## 1. O que foi pedido

1. Investigar o processo de criação dos mobs do projeto Roblox (boss do Ato 1, `iron_ram_colossus`).
2. Testar a cadeia do **prompt ao Roblox**, com exemplos em PNG por etapa.
3. Corrigir o pipe para entregar **game-ready**: 15 partes R15, animação que o Roblox entende, sem perder
   a qualidade do concept.

## 2. O que foi descoberto (e mudou a direção)

- O boss v1 **nunca teve prompt**: nasceu de script procedural (`art/scripts/make_bosses.py`) e o
  "tratamento interno" era bevel + PBR do Forge3D. O "look ruim" vinha do desenho, não do pós-processo.
- A v2 (prompt → concept → i23d → Forge3D) provou que a cadeia gera qualidade; a perda estava em
  **contrato**: o `spec@6` não tinha partes e o consumidor espera 5+ partes.
- O Forge3D **não tinha** o padrão R15 como saída de malha: tinha o *naming* (`r15@1`), o mapa
  `JOINT_R15` (`src/forge3d/rbx.py:47`) e um `export-r15` que só aceita rota `blocky`.
- O motivo de a animação não tocar: o `Animator` casa a pose pelo nome da **junta**; o GLB skinned tinha
  ossos com nome de **parte**. E, depois, verificou-se que nem o `KeyframeSequence` registrado nem o
  `Animation` publicado pelo nosso `.rbxmx` movem o rig — enquanto animações públicas R15 movem.

## 3. Decisões tomadas nesta janela

| ID | Decisão |
|---|---|
| **D123** | Contrato aditivo ao `spec@6`/`manifest@6`: `partes[]`, `rig{modo,esqueleto}`, `animacoes[]`, `rig.ancoras`; regra **B25** (motor6d exige a lista R15 sem `HumanoidRootPart`) |
| **D124** | F1+F2: segmentação por posição de osso (`blender/split_por_ossos.py`) e manifesto com partes/âncoras; `PIPELINE_VERSION` **0.9.4** |
| — | Decisão do operador: **modelo A — R15 nativo (15 partes)**, aceitando o custo de migrar o consumidor de 5 para 15 slots (registrada em `docs/plano-mobs-game-ready.md` §10) |

## 4. O que está no repo (não commitado)

| Arquivo | O que faz |
|---|---|
| `schemas/spec.v6.schema.json` | `partes`, `rig`, `animacoes` (aditivo) |
| `schemas/manifest.v6.schema.json` | `partes` (junta/âncora/bbox/tris/arquivo), `rig.modo`, `rig.ancoras`, `papel: parte` |
| `src/forge3d/spec.py` | regra **B25** |
| `src/forge3d/segmentacao.py` | wrapper da segmentação (subprocesso, I9) |
| `blender/split_por_ossos.py` | divide por osso mais próximo; exporta 15 GLBs + combinado |
| `src/forge3d/pipeline.py` | aciona a segmentação quando `rig.modo: motor6d` |
| `src/forge3d/publish.py` | emite `partes`, `rig.modo`, `rig.ancoras` |
| `tests/test_spec_partes_b25.py` | 5 testes da B25 |
| `tests/test_partes_manifesto.py` | 1 teste do manifesto com partes/âncoras |
| `pyproject.toml`, `src/forge3d/__init__.py`, `src/forge3d/post.py` | versão **0.9.4** |
| `docs/auditoria-mobs-roblox.md` | auditoria da v1 + teste v2 (§10) |
| `docs/plano-mobs-game-ready.md` | benchmark, contrato, fases, F0/F1+F2/F2b (§10.0–10.10) |
| `docs/preview/*.png` | 8 imagens de evidência (v1, concept, v2, Studio, segmentação) |

## 5. O que foi entregue fora do repo (assets e estado)

| Artefato | Id / caminho |
|---|---|
| Concept aprovado | `~/.local/state/forge3d/b_iron_ram/concept.png` (1376×768, 24,65 s) |
| Lote v2 / v3 | `~/.local/state/forge3d/b_iron_ram/lote_iron_ram_v2.yaml` · `lote_iron_ram_v3.yaml` |
| Saída v3 com partes | `~/.local/state/forge3d/saida/muralha_iron_ram_v3/` (15 partes + 4 mapas + manif) |
| Model v2 | `74299415034262` (Approved) |
| Model v3 | `74876679963395` (Approved) |
| Model 15 partes | `101811909002145` (Approved) |
| Animation walk (juntas) | `136721710982508` (Approved) |
| Animation walk (partes) | `115776315489842` (Approved) |
| Studio | Baseplate novo com `BOSS_v3_partes` (15 `Motor6D`) e o `KeyframeSequence "walk"` importado |

> `203785492` **não é nosso**: é um áudio de 2015 ("Pop Close Sound") — foi o id que gerou o erro
> "asset type does not match requested type".

## 6. Evidências medidas

| Medida | Valor |
|---|---|
| v1 auditada | 30/30 manifestos `manifest@6`, QC aprovado, G11 80.782 tris / 25 dc |
| Concept v2 | 1376×768 reais (pedido 512×512), 24,65 s, licença comercial ok |
| Malha v2/v3 | 15.920 tris, 16 ossos `r15@1`, clipes `idle`/`walk` 2,042 s |
| Godot 4.7.2 | `GODOT_ANIM_OK`: idle 6 tracks/0,0698 rad; walk 14 tracks/0,6282 rad |
| Segmentação por osso | 15 partes, **15.920 = 15.920** tris (nenhum perdido), âncora na cabeça do osso |
| Manifesto v3 | 15 `partes`, `rig.modo: motor6d`, 15 `ancoras`, 22 arquivos (15 `papel: parte`) |
| `verify` v3 | verde |
| Suíte | **539 passed, 1 skipped**; `conformidade` e `contexto` verdes |
| `check-p0` | **vermelho** só pela falha pré-existente (`concept.json` em `docs/plano-handoff-2026-11-18.md`) |
| Spike `segment_mesh` | 6 chamadas, 218 s, 15 nomes R15 e SA preservado — mas cortes errados: `Head` 6,84 vs `UpperTorso` 6,25, pernas escondidas |
| Fit das 5 partes | penetração dos braços no torso **2,93/2,87 studs** (`shoulderX` 2,60 vs ~5,5) |
| Rig no Studio | 15 `Motor6D` com nomes de junta; `BOSS_v3_partes` 12,98 × 11,79 × 7,60 |
| Playback — clipes públicos R15 | **movem**: delta 6,0 / 16,2 / 16,7 studs |
| Playback — nosso asset publicado | carrega `len=2,00`, **delta 0,000** (juntas e partes) |
| Playback — KFS importado pelo editor | carrega, `Priority=Movement`, **delta 0,000** |

## 7. O que funciona e o que não funciona

**Funciona:** concept (Gemini) → i23d → Forge3D → QC → rig `r15@1` → segmentação por osso → manifesto
com partes/âncoras → publish → `verify`. Import no Studio: 15 partes, `SurfaceAppearance` no asset,
`Motor6D` montados com as âncoras do manifesto.

**Não funciona:** tocar o clipe do Forge3D no Roblox. O dado carrega (2,00 s) e não move as juntas;
clipes públicos da Roblox movem. O caminho sancionado (Animation Editor + Publish) não foi concluído —
o editor não foi localizado pelo operador e o Studio ficou com o rig preso no editor (Play recusado).

## 8. Pendências, em ordem

1. **F3 — playback.** Abrir o Animation Editor pela aba **Avatar** (não fica em View), dar Play no
   `walk` importado e responder se o rig anda na viewport. Se andar, publicar e testar o id; se não, o
   `export-anim` está gerando dado incompatível e é ele que muda.
2. **F2b — fechar o export.** Montar o `.rbxlx` com 15 `MeshPart` + `Motor6D` (hoje a montagem foi feita
   por Luau no Studio; o writer `export-r15` continua só `blocky`).
3. **G12–G15** — implementar os gates (separação, fit, animação, fidelidade) com dado real; hoje só a
   B25 e o teste de manifesto existem.
4. **F5 — consumidor** no jogo: migrar `HordeKit` de 5 para 15 slots (fora do Forge3D).
5. **Qualidade do concept** — o i23d amacia detalhe; A/B TRELLIS × TripoSR continua pendente (exige
   autorização D1 para instalar peso).

## 9. Como retomar

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate
python -m pytest -q                      # 539 passed, 1 skipped
python tools/conformidade.py && bash tools/check-contexto.sh
# caso de teste da janela (deve ficar verde com as partes):
forge3d verify ~/.local/state/forge3d/saida/muralha_iron_ram_v3
forge3d run ~/.local/state/forge3d/b_iron_ram/lote_iron_ram_v3.yaml --json
```

- Contrato: `schemas/spec.v6.schema.json` / `manifest.v6.schema.json` (aditivo; B25 em `spec.py`).
- Segmentação: `blender/split_por_ossos.py` + `src/forge3d/segmentacao.py`.
- Studio: MCP por `tools/mcp_studio.py` (place aberto é pré-requisito; editor de animação aberto
  bloqueia o Play).

## 10. Armadilhas pagas nesta janela

1. **`spec@6` não tinha partes** — o consumidor esperava 5 e o pipeline entregava 1; o fit falhou por
   2,9 studs de penetração. Contrato antes de código (D123).
2. **`segment_mesh` (Studio) tem limite de 5 nomes por chamada** e cortes semânticos errados: 6 chamadas,
   218 s, `Head` de 6,84 studs. Nome certo ≠ junta certa.
3. **Textura nova leva ~75 s** para liberar no Studio após upload; validar antes mostra modelo branco.
4. **`upload-animation` falha com `.rbxmx` de duas sequências**; com uma, publica (`136721710982508`).
5. **`AnimationId` só aceita asset Animation** — um áudio (203785492) gera "asset type does not match".
6. **Play mode bloqueado** quando o Animation Editor está aberto com o rig (`Client datamodel is not
   available`).
7. **Parte ancorada não gira nem por `Motor6D`** — só a raiz pode ficar ancorada.
8. **Aba certa do editor é Avatar** (ou Window → Avatar), não View.

## 11. Inventário de artefatos

- Docs: `docs/auditoria-mobs-roblox.md`, `docs/plano-mobs-game-ready.md`, este arquivo.
- Imagens: `docs/preview/iron_ram_etapas.png`, `v1_v2_distancia.png`, `v2_iron_ram_cadeia.png`,
  `v2_rig_vs_segmentada.png`, `studio_v2_rig.png`, `v1_ingame_vs_v2_play.png`,
  `v1_ingame_vs_v2_studio.png`, `iron_ram_v1_vs_concept.png`.
- Estado: `~/.local/state/forge3d/b_iron_ram/` e `~/.local/state/forge3d/saida/muralha_iron_ram_v3/`.
- Working tree: 12 arquivos modificados + 8 novos (ver `git status`); nada foi commitado.
