# CONTINUAR — handoff de sessão

**Data:** 11/11/2026 · **P0, P0.5, P1, P2, P3, P3.5, P5 e C5–C12 fechadas.** A P2 fechou pela
escala (`manifest@2`, D62): package e `.rbxlx` medem **6,6071 studs** (D68). A C12 republicou
**7 destinos, 16 manifestos** com `verify` **0 problemas**. A P5 fechou: clipe `idle` por retarget
(D66) em `manifest@3` (D67), tocando no Godot e no Roblox (D69), e LOD medido por silhueta (D71).
**138 verdes + 1 GPU (skip)** em 139 testes · CI no GitHub com **123 testes**.

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
| **P4** | ✔ | `spec@3` + WFC + 7 módulos + 10 setores, colisão por peça e 1 draw call (D74/D75/D77); parede cheia fica em GAP-047 |
| **P5** | ✔ | animação base tocando no Roblox (D66/D67/D69) e LOD medido por critério (D71: blocky sem LOD, mesh com LOD no prop e no personagem) |

## O que foi entregue nesta janela

- **Opção A da P2 (D62/C15)** — `schemas/manifest.v2.schema.json` com `unidades_export`;
  `roblox-r15` com `escala_saida: 3,5714` e `metros_por_unidade: 0,28` (`godot4` fica em 1.0);
  `blender/postprocess.py` multiplica a escala final e devolve o fator; `qc.py` divide a AABB e o pivô
  pela escala no G2 e grava `altura_export`/`escala_saida`; `publish` emite `@2` e `verify` aceita `@1`
  (escala 1.0) e `@2`, reprovando `unidades_export` inconsistente ou divergente do perfil atual.
- **13 testes novos** em `tests/test_unidades.py` + o invariante R15 medindo 6,607 studs no glb; o CI
  passou a rodar o arquivo. `PIPELINE_VERSION` **0.2.5**.
- **Republicado o `r15`** e reenviado o Model (asset **134628989553440**, 39.004 B, Approved); medido
  no Studio via MCP: `2,7086 × 6,6071 × 1,5196` studs, 16 Bones, `AssetFetchStatus.Success`.
- **`verify` em 0 problemas** no `r15`; `lote_01` e `kit_sentinel` (`manifest@1`) continuam 0 problemas.
- **Doc**: `DECISOES` §1/§4 (Q3 fechada) e a tabela D57–D62 consertada; `docs/contratos.md` §3.1;
  GAP-006/GAP-043 fechados, GAP-044 aberto; `docs/pendencias.md` e `README` sem "P2 parcial".
- **C12 — destinos republicados** (7 destinos, 16 manifestos, `verify` 0 problemas) e a C12 achou dois
  defeitos reais: o `convex_hull` herdava **faces de entrada** e o colisor saía com face interior
  (desvio de 1,8 m; **D64** — hull em nuvem de pontos) e a convexidade media com tolerância apertada
  demais (1e-6 do diâmetro; **D65** — 1 mm/m). O colisor do concept caiu de "concavo" para desvio
  máximo de **4,3e-4 m**. `PIPELINE_VERSION` **0.2.6**.
- **P5-A — animação base (D66/D67)** — `rig.retarget` nos perfis mapeia osso semântico → osso do
  esqueleto; o `idle` é gerado no `bpy` (5 chaves, 2 s a 24 fps) e embutido no glb; G10 mede
  **movimento real**; `manifest@3` declara `animacoes`; `tests/test_animacao.py` + e2e do R15 com o
  clipe; Godot 4.3 headless confirma nos dois esqueletos. `PIPELINE_VERSION` **0.2.7**.
- **P5-C — LOD (GAP-013/GAP-046/D71)** — `tools/lod_qualidade.py` mede IoU de silhueta
  (frente/lado), pior faixa vertical e bbox contra o LOD0. O LOD do blocky foi reprovado (decimate:
  0,76/0,55 e espinhos; ilha: 0,865 global mas faixa 0,654, sem antebraço) e os exemplos deixam de
  pedir LOD de blocky; a malha gerada passa no prop (bule 0,993/0,994, faixa 0,948) e no personagem
  (`corpo.02` 0,980/0,987, faixa 0,971). `publicar` agora remove órfão do manifesto antigo.
- **P5-B — clipe no Roblox (D69)** — `animacao.py` é a definição única; o `export-r15` grava um
  `KeyframeSequence` (5 chaves, pose completa com as 15 juntas, nome de junta R15) no `.rbxlx`, o
  `export-anim` gera o `.rbxmx` e o `upload-animation` sobe como `Animation`
  (**116049702979137**, Approved). **Playback medido no client do Play mode**: a Head anda
  **0,0949 / 0,0662 studs** em duas execuções. O que destravou foi `Priority=Core` — com `Idle` a track
  carrega (`Weight=1`, `Length=2.0`) e não aplica; o nome da pose (parte × junta) não era o problema.

## Números medidos nesta máquina

| Medida | Valor |
|---|---|
| Suíte | **138 verdes + 1 GPU (skip)** em **139 testes** |
| CI no GitHub | **123 testes** (`tools/ci.sh`) + contexto + P0 |
| Destinos no sandbox | **7 destinos, 16 manifestos** em `manifest@3` 0.2.7, `verify` **0 problemas** |
| Clipe `idle` | **2,042 s**; move 5 ossos nos dois esqueletos; 48 canais no glb do R15 |
| Godot 4.3 (headless) | `GODOT_ANIM_OK` no R15 (5 tracks) e no android (7 tracks), movimento **0,0697 rad** |
| Clipe no rig Roblox (MCP) | Head anda **0,1091 studs** entre t=0 e t=0,5; maior delta de parte 0,1253 |
| Animation no Roblox | asset **116049702979137** (30.229 B, Approved, `Priority=Core`); `GetKeyframeSequenceAsync` = 5 keyframes, 15 poses |
| Playback no client | Head anda **0,0949 / 0,0662 studs** no rig Motor6D do `.rbxlx`; com `Idle` (v2/v3) 0,0002 |
| LOD do blocky (decimate) | LOD1 IoU **0,76** frente / 0,98 lado; LOD2 **0,55** / 0,81 + espinhos no render → reprovado |
| LOD de malha gerada | bule a 50%: IoU **0,993** frente / **0,994** lado, faixa **0,948**, bbox ≤ 0,09% → aprovado |
| LOD de personagem mesh | `corpo.02` a 50%: IoU **0,980** frente / **0,987** lado, faixa **0,971**, bbox ≤ 0,11% → aprovado |
| P4 — layout 5x2 (seed 20261111) | 10 setores de **24–48 tris**, **1 mesh/1 material** e **2–4 hulls** de colisão por setor (chão 0,20 m, parede 2,00 m); `verify` 0 problemas |
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
**`D75` P4 fatiada: `spec@3` + um setor por asset** · **`D76`/I15 projeto não entra no pipeline**.

## Aberto

Nada em aberto: Q1 fechou em **D72** (`forge3d` fica) e Q7 em **D73** (LFS no repo do jogo).

Gaps abertos que importam: **GAP-004** (scanner da skill em Luau), **GAP-013** (qualidade do LOD),
**GAP-015** (`draft` em 4k) e **GAP-042** (regra do "menor secção").

## Próximos passos — em ordem

| # | Ação | Custo | Ataca |
|---|---|---|---|
| **1** | **P4** — polimento visual: parede cheia do lado fechado (GAP-047) ou próxima fase (P6/produto) | 1 sessão | roadmap |
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

python -m pytest                          # 138 verdes + 1 GPU
bash tools/ci.sh                          # 123 testes + contexto + P0 (o que o GitHub roda)
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

1. **`edit`/`write` sobre UNC falham em arquivo que já existe** (`GetFileSecurityW EIO`) → o `write`
   cria arquivo novo; para alterar, grave `<arquivo>.new` e `mv` por WSL.
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

> Leia `3DCreation/CONTINUAR.md`, `MAPA.md` e `DECISOES.md` §2 e §4. P0–P3.5, C5–C12 e a escala da P2
> (D62) fechadas: 7 destinos/16 manifestos em `manifest@2` 0.2.6, `verify` 0 problemas. CI verde em
> `github.com/eudespatricio/3DCreation`; key do Roblox em `~/.config/forge3d/roblox.key`, fora do repo.
> Próximo: **P5** (animação/retarget). Não reabra D3–D27 nem D52–D65.
