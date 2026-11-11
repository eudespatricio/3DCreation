# CONTINUAR — handoff de sessão

**Data:** 11/11/2026 · **P0, P0.5, P1, P3, P3.5 e C5–C11 fechadas. P2 tem UM item aberto: a escala
do package Roblox (3,57×).** 86 verdes + 1 GPU (skip) · CI no GitHub com 71 testes · 10 runs verdes.
**A próxima janela ataca a opção A** — `manifest@2` com `unidades_export`; briefing completo em
[`docs/goal-proxima-janela.md`](docs/goal-proxima-janela.md).

Verificação rápida: `python -m pytest tests/test_e2e_rapido.py -q` (~2 s) e `python -m pytest` (~17 s).

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
| **P3** | ✔ | provider `i23d` (TripoSR), bake UV/textura próprio, kit corpo/capa/arma |
| **P3.5** | ✔ | concept SD1.5 → TripoSR, split e A/B de 3 personagens híbridos |
| **P2** | **1 item** | R15 16 ossos, pivô, `.rbxlx`, Model/Image aprovados, **textura confirmada no Studio**, U1/U2/U4 fechadas; **falta a escala** (opção A) |
| **P4** | pendente | rota `modular` (WFC) |
| **P5** | pendente | animação e retarget |

## O que foi entregue nesta janela

- **C5–C11** — 10 execuções seguidas do e2e (C5); `verify` reprova manifesto sem `pivo_regra` (C7);
  G7 mede convexidade por componente (C8) e **achou defeito real**: 9 dos 14 colisores publicados
  eram não-manifold; `lock_gpu` mantém o `flock` como dono e PID/VRAM viram diagnóstico (D59);
  `rembg` por procedência/alfa (D55); `preflight` acha `FORGE3D_MODELOS` (C10); prompt do CLIP medido
  e truncado em 77 (D54).
- **GAP-008 / CI** — repo público `github.com/eudespatricio/3DCreation`; PR #1 verde em `push` e
  `pull_request`; job = `tools/ci.sh` com **71 testes** + contexto + P0.
- **D52–D53** — colisor `convex` passou a ser hull fechado (o `convex_hull` do bmesh não apagava a
  entrada) e o G7 mede convexidade.
- **D58** — `empunhadura` virou regra numérica única (20 % da altura) usada por `blocky` e `mesh`, e o
  G2 mede base/centro/topo/empunhadura. A regra do perfil ("menor secção") ficou em GAP-042.
- **C12** — `lote_01`, `kit_sentinel` e `r15` republicados do zero com `PIPELINE_VERSION` 0.2.4;
  `verify` **0 problemas** nos três. Faltam os destinos de malha (GPU).
- **P8 no Studio** — MCP ligado: `tools/mcp_studio.py` roda Luau no place. Medido:
  `preload=Enum.AssetFetchStatus.Success` para `rbxassetid://75934318775024`, **16 Bones**,
  `surface=false`, `humanoid=false`. **U1/U2/U4 fechadas** em `docs/perfis-export.md`.
- **GAP-014** — `tests/test_atomico.py`: thread observadora durante o publish, `spy` no
  `os.replace` e falha injetada; `tools/conformidade.py` (tetos, I14, I12) entrou no CI.

## Números medidos nesta máquina

| Medida | Valor |
|---|---|
| Suíte | **86 verdes + 1 GPU (skip)** em **17,2 s** |
| CI no GitHub | **71 testes**; 10 runs `success` (último `84025a6`) |
| E2E rápido | ~2,0 s (10 execuções seguidas verdes) |
| Package R15 no Studio | `size=0,758 × 1,850 × 0,426` studs · **16 Bones** · `surface=false` · `humanoid=false` |
| Rig `.rbxlx` | **6,478 studs** de extensão vertical (17 Parts, 15 Motor6D) |
| Divergência de escala | **3,57×** (1 / 0,28) entre package e `.rbxlx` |
| Textura no Studio | `PreloadAsync` = `Enum.AssetFetchStatus.Success` |
| MCP do Studio | proxy **stdio**, 38 ferramentas; Studio só aparece com o proxy vivo ~4 s |
| `empunhadura` medida | `arma.01` (blocky) 10,0 % da altura · `arma.02` (mesh) 20,0 % — **antes** do D58 |
| Asset R15 | Model `136741921517312` (39.068 B) · Image `75934318775024` — ambos Approved |

## Decidido (não reabrir)

`D3` CLI-only · `D9` QC sem bypass · `D11` GPU serializada · `D18` licença é gate · `D23` allowlist ·
`D24` estado central · `D25` isolamento · `D26` núcleo leve · `D27` SF3D encerrado ·
`D32` verify reexecuta G1–G9 · `D33` mesh exige `origem` · `D35` concept interno ao mesh ·
`D52` colisor é hull fechado · `D53` G7 mede convexidade · `D54` CLIP 77 · `D55` rembg por alfa ·
`D56` CI no GitHub · `D57` delegação no `agentapi` (exige IDE) · `D58` empunhadura 20 % ·
`D59` `flock` é o dono do lock · `D60` validação no Roblox via MCP.

## Aberto

| # | Pergunta | Trava |
|---|---|---|
| Q3 | **Escala do Roblox**: importador usa 1 unidade = 1 stud; resolver na opção A (`manifest@2`) | P2 |
| Q1 | nome definitivo do produto | publicar o pacote |
| Q7 | assets no git do jogo: normal × LFS | primeiro asset real |
| Q9 | ~~resolvida por D57~~ | — |

Gaps abertos que importam: **GAP-004** (scanner da skill em Luau), **GAP-006** (só a escala),
**GAP-013** (qualidade do LOD), **GAP-015** (`draft` em 4k), **GAP-042** (regra do "menor secção"),
**GAP-043** (`unidades_export` no manifesto).

## Próximos passos — em ordem

| # | Ação | Custo | Ataca |
|---|---|---|---|
| **1** | **Opção A**: `manifest@2` com `unidades_export`, GLB do Roblox em studs, republish + re-upload + medir no Studio via MCP | 1 sessão | P8/GAP-006/Q3 |
| **2** | C12 nos destinos de malha (`kit_mesh`, `sentinel_concept`, `teapot`, `lote_06`) | 1 sessão + GPU | C12 |
| **3** | **P5** animação/retarget (o MCP já permite validar clipes no Studio) | 2–3 sessões | percepção no jogo |
| **4** | **P4** rota `modular` (WFC) | 1–2 sessões | roadmap |

## Comandos

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate

forge3d doctor
forge3d run   examples/lote_01.yaml          # blocky, sem GPU
forge3d run   examples/lote_09_r15.yaml      # R15 blocky
forge3d export-r15 examples/lote_09_r15.yaml --item personagem.r15.guard.01
forge3d verify ~/.local/state/forge3d/saida/r15
forge3d upload-model <glb> --creator-id 11966727684 --dry-run
forge3d gc --dry-run --manter-dias 30

python -m pytest                          # 86 verdes + 1 GPU
bash tools/ci.sh                          # 71 testes + contexto + P0 (o que o GitHub roda)
bash tools/check-contexto.sh
python tools/check-p0.py
python tools/mcp_studio.py --estado       # Studio via MCP (precisa do MCP ligado)
python tools/conformidade.py              # tetos, I14, I12
```

## Armadilhas pagas (não repetir)

1. **`edit`/`write` sobre UNC falham** (`GetFileSecurityW EIO`) → edite por WSL/ext4.
2. **`convex_hull` do bmesh não apaga a entrada** → recorte só com `hull["geom"]` (D52).
3. **Mudou a saída? Suba `VERSAO`/`PIPELINE_VERSION`** — senão o cache serve o artefato velho (D6).
4. **Importador do Roblox: 1 unidade glTF = 1 stud** — metros não são convertidos.
5. **Command Bar do Studio é linha única**: script multi-linha colapsa e o `--` engole tudo → use MCP.
6. O **MCP** só lista o Studio com o proxy vivo alguns segundos; o binário muda por versão do Studio
   (`FORGE3D_STUDIOMCP`).
7. **Joelho e cotovelo giram em sentidos opostos**; peça de membro sobrepõe o pivô.
8. **Diffusers trunca prompt em 77 tokens em silêncio** (hoje medido em `tools/concept_infer.py`).

## Como retomar

> Leia `3DCreation/CONTINUAR.md`, `MAPA.md` e `DECISOES.md` §2 e §4. P0/P0.5/P1/P3/P3.5 e C5–C11
> fechados; **P2 depende só da escala** (opção A, `docs/goal-proxima-janela.md`). CI verde em
> `github.com/eudespatricio/3DCreation`; key do Roblox em `~/.config/forge3d/roblox.key`, fora do repo.
> Próximo: `manifest@2` com `unidades_export` → republish `r15` → re-upload → medir `Size.Y` ≈ 6,607
> studs no Studio via `tools/mcp_studio.py`. Não reabra D3–D27 nem D52–D60.
