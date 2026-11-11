# GOAL — próxima janela (executado em 11/11/2026)

> **Status:** executado em 11/11/2026 — a P2 fechou com `Size.Y = 6,6071` studs no Studio (asset
> 134628989553440) e `manifest@2` com `unidades_export`. O estado atual mora em `CONTINUAR.md`;
> este arquivo fica como registro do briefing daquela janela.
>
> Copie o bloco do §9 como *objetivo da sessão* (Goal) na janela nova. Este arquivo é o briefing
> completo: objetivo, contexto medido, ordem de execução, armadilhas, critério de aceitação.

## 1. Objetivo

Fechar a **P2** implementando a **opção A**: o perfil `roblox-r15` passa a exportar o `glb` em
**studs**, e o manifesto passa a **declarar a unidade** (`unidades_export`), para que o package
importado no Roblox e o `.rbxlx` nativo fiquem na **mesma escala**.

## 2. O problema, medido (não reabrir a diagnose)

| Fato | Valor | Onde foi medido |
|---|---|---|
| Package importado no Studio | `size = 0,758 × 1,850 × 0,426` **studs** | MCP, `execute_luau` |
| Rig `.rbxlx` | **6,478 studs** de extensão vertical | parser do `.rbxlx` |
| Divergência | **3,57×** = 1 / 0,28 | — |
| Regra do importador | **1 unidade glTF = 1 stud** (não converte metros) | U1 fechada |
| `geometry.bbox_m` do `manifest@1` | em **metros** → mentiria com o GLB em studs | contrato |

Por isso a correção exige declarar a unidade no manifesto: é **bump de contrato**, como foi
`spec@1 → @2` no D30. A opção B (importar com escala 3,5714 na UI) foi **descartada** — passo manual
que o próximo consumidor esquece.

## 3. Regras duras (não reabrir)

`D3` CLI-only · `D9` QC sem bypass · `D11` GPU serializada · `D23` allowlist · `D24` estado central ·
`D25` isolamento · `D26` núcleo leve · `D32` `verify` reexecuta G1–G9 · `D52` colisor hull fechado ·
`D53` G7 convexidade · `D54` CLIP 77 · `D55` rembg por alfa · `D56` CI · `D57` delegar só com IDE ·
`D58` empunhadura 20 % · `D59` `flock` dono do lock · `D60` validar no Roblox via MCP.

Proibido: mudar `schemas/` sem bump documentado · mexer no `blender/postprocess.py` sem subir
`PIPELINE_VERSION` · rebaixar gate para "passar".

## 4. Ordem de execução

| # | Tarefa | Detalhe |
|---|---|---|
| **1** | **Schema** | `schemas/manifest.v2.schema.json` com `unidades_export: {metros_por_unidade, escala_saida}`. `manifest@1` continua aceito na leitura (`verify` dos destinos antigos). Registrar em `DECISOES` §2 (`D62`). |
| **2** | **Perfil** | `profiles/roblox-r15.yaml`: `unidades.escala_saida: 3.5714` (e `metros_por_unidade: 0.28`); `godot4` fica `1.0`. |
| **3** | **Post-processo** | `blender/postprocess.py` multiplica a escala final por `escala_saida` e devolve o fator no relatório. **Atenção**: pivô e bbox escalam junto. |
| **4** | **QC** | `qc.py`: G2 compara `altura / escala_saida` com `altura_metros` e grava `escala_saida` no `medido`; `_desvio_pivo` divide pela mesma escala. Perfil sem o campo = 1.0 (nada muda). |
| **5** | **Manifesto** | `publish.montar_manifesto` emite `schema: forge3d/manifest@2` + `unidades_export`; `publish.verificar` aceita `@1` e `@2` e reexecuta com a escala declarada. |
| **6** | **Testes** | escala 1.0 não altera nada; 3.5714 multiplica o bbox; G2 divide e passa; manifesto `@2` sem `unidades_export` reprova; `verify` de manifesto `@1` antigo continua com o erro de `pivo_regra` (C7). |
| **7** | **Republicar** | `forge3d run examples/lote_09_r15.yaml` (subir `PIPELINE_VERSION`), `export-r15`; `verify` nos dois. |
| **8** | **Re-upload + medir** | `upload-model` do novo `.glb` (asset novo), inserir no Studio e medir `Size.Y` **via MCP** (`tools/mcp_studio.py`), sem Command Bar. |
| **9** | **Fechar P8** | `Size.Y` do package dentro de `6,607 ± 0,02` studs; GAP-006 e P8 fechados com o número; `DECISOES` §1 e §4 (Q3); `CONTINUAR`. |

## 5. O que registrar sempre

fato medido → `DECISOES` §1 com rótulo · lacuna → `docs/gaps.md` · pendência → `docs/pendencias.md` ·
decisão → `DECISOES` §2 · mudança de contrato → `schemas/` + bump + linha em `DECISOES`.

## 6. Portões (antes de cada commit)

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate
python -m pytest tests/test_e2e_rapido.py -q   # < 30 s
python -m pytest                               # 86 verdes + 1 GPU
bash tools/ci.sh                               # o que o GitHub roda (71 testes)
bash tools/check-contexto.sh
python tools/check-p0.py
```

## 7. Armadilhas

1. **`edit`/`write` sobre UNC falham** → edite por WSL/ext4.
2. **Cache (D6)**: mudou a saída → `PIPELINE_VERSION` ou `VERSAO` do provider, senão o `run` serve o
   artefato antigo e o `verify` aprova o que a pipeline nova não geraria.
3. **Não escalar duas vezes**: o `.rbxlx` já sai em studs (`rbx.py` usa `metros_por_stud`); só o
   `glb` do perfil Roblox precisa do fator.
4. **`bbox_m` continua em metros**; quem quiser a unidade do arquivo lê `unidades_export`.
5. **MCP**: o proxy precisa ficar vivo alguns segundos; o binário muda por versão do Studio
   (`FORGE3D_STUDIOMCP`); Command Bar é linha única e colapsa script multi-linha.
6. **Re-upload** cria asset novo — atualizar o id em `docs/preview/r15_upload_test.log` e no GAP-006.

## 8. Orçamento

Uma janela. Se o schema se mostrar mais caro que o previsto, **entregar 1–6 e registrar 7–9** em
`docs/pendencias.md` com critério de aceitação. Não deixar teste vermelho ao encerrar.

## 9. Bloco para colar como Goal

```
Objetivo: continuar o Forge3D em /home/eudespatricio/3DCreation e fechar a P2 implementando a opcao A
do docs/goal-proxima-janela.md: manifest@2 com unidades_export, glb do roblox-r15 exportado em studs,
republicar o r15, reenviar o Model e medir o Size no Studio via tools/mcp_studio.py.

Leia, nesta ordem: CONTINUAR.md, docs/goal-proxima-janela.md, MAPA.md, DECISOES.md §2 e §4, docs/gaps.md.
P0/P0.5/P1/P3/P3.5 e C5-C11 estao fechados; suite em 86 verdes + 1 GPU e CI verde no GitHub.
Nao reabra D3-D27 nem D52-D60; SF3D esta encerrado (GAP-035).

Medido que fundamenta a tarefa: package = 1,850 studs, .rbxlx = 6,478 studs, divergencia 3,57x;
o importador do Roblox usa 1 unidade glTF = 1 stud; o manifest@1 declara bbox_m em metros, entao o
glb em studs exige declarar a unidade no manifesto (bump de contrato).

Ordem: 1) schema manifest@2; 2) perfil com escala_saida; 3) postprocess aplica; 4) G2 divide e grava
o fator; 5) publish emite @2 e verify aceita @1 e @2; 6) testes; 7) republish do r15 com
PIPELINE_VERSION novo; 8) export-r15 + upload + medir Size.Y via MCP; 9) fechar GAP-006/P8 e Q3.

Registre sempre: fato medido em DECISOES §1, lacuna em docs/gaps.md, pendencia em docs/pendencias.md,
decisao em DECISOES §2. Mudanca de schema exige bump de versao.

Portoes antes de cada commit: python -m pytest tests/test_e2e_rapido.py -q (<30 s), python -m pytest,
bash tools/ci.sh, bash tools/check-contexto.sh, python tools/check-p0.py.

Aceitacao final: Size.Y do package no Studio em 6,607 +- 0,02 studs; .rbxlx e package na mesma escala;
verify verde nos dois; manifesto @2 valido; suite e CI verdes; GAP-006 e P8 fechados com o numero.

Comece rodando os portoes e o `python tools/mcp_studio.py --estado` para confirmar o Studio.
```
