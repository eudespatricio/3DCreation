# CONTINUAR — handoff de sessão

**Data:** 11/11/2026 · **P0, P0.5, P1, P2, P3, P3.5, C5–C11 e C12 fechadas.** A P2 fechou pela
escala: `manifest@2` com `unidades_export` (D62) e o glb do `roblox-r15` sai em studs — package medido
no Studio em **6,6071 studs**, contra 6,8086 de extensão do `.rbxlx` (mesma escala; os 3,05 % ficam em
GAP-044). A C12 fechou o passivo dos destinos: **7 destinos, 16 manifestos** em `manifest@2` 0.2.6,
`verify` **0 problemas**. **101 verdes + 1 GPU (skip)** em 102 testes · CI no GitHub com **86 testes**
(run 42956720067 verde em `a21e944`).

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
| **P4** | pendente | rota `modular` (WFC) |
| **P5** | pendente | animação e retarget |

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

## Números medidos nesta máquina

| Medida | Valor |
|---|---|
| Suíte | **101 verdes + 1 GPU (skip)** em **102 testes** |
| CI no GitHub | **86 testes** (`tools/ci.sh`) + contexto + P0 |
| Destinos no sandbox | **7 destinos, 16 manifestos**, todos `manifest@2` 0.2.6, `verify` **0 problemas** |
| Colisor após D64/D65 | desvio máximo **4,3e-4 m** num hull de 2,2 m (tolerância 1 mm/m); face interior do defeito desviava 1,8 m |
| Package R15 v2 no Studio | `size=2,7086 × 6,6071 × 1,5196` studs · **16 Bones** · `surface=false` · `humanoid=false` |
| glb do R15 | `bbox = 2,70855 × 6,60709 × 1,519631` studs para `bbox_m = [0,7584; 1,85; 0,4255]` m |
| Rig `.rbxlx` | **6,8086 studs** de extensão (base `-0,3302`, topo `6,4784`; 16 Parts + Baseplate) |
| Resíduo rig × package | **3,05 %** — caixas brutas do blocky (1,906 m) vs malha normalizada (1,850 m) → GAP-044 |
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
unidade** · **`D64` hull sobre nuvem de pontos** · **`D65` convexidade com tolerância de 1 mm/m**.

## Aberto

| # | Pergunta | Trava |
|---|---|---|
| Q1 | nome definitivo do produto | publicar o pacote |
| Q7 | assets no git do jogo: normal × LFS | primeiro asset real |

Gaps abertos que importam: **GAP-004** (scanner da skill em Luau), **GAP-013** (qualidade do LOD),
**GAP-015** (`draft` em 4k), **GAP-042** (regra do "menor secção"), **GAP-044** (rig 3,05 % acima do
glb).

## Próximos passos — em ordem

| # | Ação | Custo | Ataca |
|---|---|---|---|
| **1** | **P5** animação/retarget: clipe base no glb + retarget `godot-humanoid@1` × `r15@1` + validação no Godot e no Studio | 2–3 sessões | GAP-007/GAP-020/D14 |
| **2** | **P4** rota `modular` (WFC) | 1–2 sessões | roadmap |
| **3** | GAP-044: normalizar as caixas do `export-r15` | 1 sessão | coerência rig × glb |

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

python -m pytest                          # 101 verdes + 1 GPU
bash tools/ci.sh                          # 86 testes + contexto + P0 (o que o GitHub roda)
bash tools/check-contexto.sh
python tools/check-p0.py
python tools/mcp_studio.py --estado       # Studio via MCP (precisa do MCP ligado)
python tools/r15_escala_studio.py         # Size/bones/textura do package R15 no Studio
python tools/conformidade.py              # tetos, I14, I12
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
10. **O `.rbxlx` não passa pela normalização do pós-processo**: ele usa as caixas brutas do `blocky` e
    por isso é 3,05 % mais alto que o glb (GAP-044). Não é erro de escala.
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
