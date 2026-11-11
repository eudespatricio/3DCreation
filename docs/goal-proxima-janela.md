# GOAL — próxima janela

> Copie o bloco do §9 como *objetivo da sessão* (Goal) na janela nova. Este arquivo é o briefing
> completo: objetivo, contexto, regras, ordem de execução, o que registrar e os portões.

## 1. Objetivo

Fechar a **P2** de forma utilizável — R15 aprovado **no Studio GUI logado** — e deixar o repositório
em dia: `C6/Q9` decidido pelo operador e os destinos antigos republicados. O que não couber entra em
`docs/pendencias.md` com critério de aceitação, não como promessa.

## 2. Contexto mínimo (ler nesta ordem)

1. `CONTINUAR.md` — estado, números, armadilhas
2. `docs/pendencias.md` — o que falta (P8 e C6 são os únicos itens abertos de código)
3. `MAPA.md` — onde cada coisa mora
4. `DECISOES.md` §2 (decisões, hoje até `D56`) e §4 (abertas)
5. `docs/gaps.md` — lacunas com condição de fechamento

## 3. O que já está fechado (não reabrir)

`D3` CLI-only · `D7` D1 byte-idêntico, D2 semeado, D3 fora do CI · `D9` QC sem bypass ·
`D11` GPU serializada · `D14` animação fora da v0 · `D18` licença é gate · `D23` allowlist ·
`D24` estado central · `D25` isolamento · `D26` núcleo leve · `D27` SF3D encerrado ·
`D52` colisor é hull fechado · `D53` G7 mede convexidade · `D54` prompt em 77 tokens ·
`D55` rembg por procedência/alfa · `D56` CI no GitHub.

P3, P3.5 e **C5–C11** fecharam. Suíte em **68 verdes + 1 GPU (skip)**. CI verde no GitHub
(run `42942191684`). Não reabra SF3D (GAP-035: ~8 min/imagem).

## 4. Ordem de execução

| # | Tarefa | Aceitação |
|---|---|---|
| **1** | **P8/GAP-006 — Studio GUI logado**: inserir o package `136741921517312` (Toolbox/Asset Manager) e conferir a textura `75934318775024` no `forge3d_mesh` | textura visível no Studio GUI, sem `No asset content representation` |
| **2** | **P8 — pivôs e escala**: girar os 16 Bones (pivô por membro), medir escala/stud (`1 stud ≈ 0,28 m`) e validar U1–U4 | U1–U4 sem `[verificar]` no perfil `roblox-r15`; rotação por membro correta |
| **3** | **P8 — rig**: conferir se o `Humanoid`/R15 do `.rbxlx` (`saida/r15/personagem.r15.guard.01.rbxlx`, 16 partes, 15 Motor6D) anima; decidir se o asset skinned substitui o rig de pivôs | `R15` jogável ou decisão registrada em `DECISOES.md` §2 |
| **4** | **C6/Q9**: decidir delegação — chave de API × `agentapi` | decisão em `DECISOES.md` §4 e `tools/delegar.py` com caminho sem IDE |
| **5** | **C12**: republicar destinos antigos (`lote_01`, `lote_03_kit`, `lote_06`, `r15`) | `forge3d verify` verde nos destinos republicados |
| **6** | Se sobrar janela: **P5** animação/retarget; **P4** rota `modular` (WFC) | portão da fase em `docs/roadmap.md` |

## 5. O que registrar sempre

| Achado | Onde |
|---|---|
| número medido | `DECISOES.md` §1, com rótulo `[medido]` |
| lacuna nova | `docs/gaps.md`, com condição objetiva de fechamento |
| pendência/correção | `docs/pendencias.md`, com prioridade e aceitação |
| decisão | `DECISOES.md` §2 (`D<n>`) — só com critério escrito antes |
| mudança de contrato | `schemas/` + bump de versão + linha em `DECISOES.md` |

## 6. Portões (rodar antes de qualquer commit)

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate
python -m pytest tests/test_e2e_rapido.py -q   # ciclo completo, < 30 s
python -m pytest -q                            # suíte completa: 68 + 1 GPU
bash tools/check-contexto.sh                   # tetos
python tools/check-p0.py                       # docs, schemas, I12/I14
```

O CI do GitHub roda `tools/ci.sh` (53 testes + contexto + P0, sem GPU/Blender). Blender 4.2, GPU,
TripoSR e SD1.5 são **locais** e não rodam no CI.

## 7. Armadilhas já pagas (não repetir)

1. **`edit`/`write` em caminho UNC falham** (`GetFileSecurityW EIO`) → edite por WSL/ext4.
2. **`convex_hull` do `bmesh` não apaga a entrada** → recorte só com `hull["geom"]` (D52).
3. **Blender 4.2 usa Python 3.11** — nunca `pip install` nele (I9).
4. **glTF divide vértice por costura de UV** → G1 solda antes de contar não-manifold.
5. Peça de membro precisa **sobrepor o pivô**, e nunca compartilhar canto exato.
6. **Joelho e cotovelo giram em sentidos opostos** (X negativo dobra joelho, positivo cotovelo).
7. Mudou a saída de um provider? **Suba `VERSAO`** — senão o cache serve o artefato velho.
8. **Diffusers trunca prompt em 77 tokens em silêncio** — hoje medido em `tools/concept_infer.py`.
9. **`nvidia-smi` vive em `/usr/lib/wsl/lib`**; **CMake 4.x quebra builds antigos** (`<4`).
10. **Servidor headless do `run-in-roblox` não carrega asset privado** — só o Studio GUI logado.

## 8. Orçamento

Uma janela. Se não couber, entregar **1 e 2** (textura e pivôs/escala no Studio) e registrar 3–6 em
`docs/pendencias.md`. Não deixar teste vermelho ao encerrar.

## 9. Bloco para colar como Goal

```
Objetivo: continuar o Forge3D em /home/eudespatricio/3DCreation e fechar a P2 (Roblox R15) no Studio
GUI logado, executando tudo o que couber nesta janela; o que não couber entra em docs/pendencias.md
com critério de aceitação.

Leia, nesta ordem: CONTINUAR.md, docs/pendencias.md, MAPA.md, DECISOES.md §2 e §4, docs/gaps.md.
P3, P3.5 e C5-C11 estão fechados; suíte em 68 verdes + 1 GPU e CI verde no GitHub (run 42942191684).
Não reabra D3-D26 nem D52-D56; SF3D está encerrado (GAP-035).

Ordem de execução:
1) P8/GAP-006: inserir o package 136741921517312 e conferir a textura 75934318775024 no Studio GUI;
2) P8: girar os 16 Bones (pivô por membro), medir escala/stud e validar U1-U4;
3) P8: conferir Humanoid/rig do .rbxlx (saida/r15/personagem.r15.guard.01.rbxlx, 16 partes, 15 Motor6D);
4) C6/Q9: decidir delegacao (chave de API x agentapi);
5) C12: republicar destinos antigos e passar forge3d verify;
6) se sobrar janela: P5 animacao/retarget ou P4 rota modular.

Registre sempre: fato medido em DECISOES §1 com rotulo, lacuna em docs/gaps.md, pendencia em
docs/pendencias.md, decisao em DECISOES §2. Mudanca de schema exige bump de versao.

Portoes antes de cada commit: python -m pytest tests/test_e2e_rapido.py -q (tem que passar em <30 s),
python -m pytest -q, bash tools/check-contexto.sh, python tools/check-p0.py.

Aceitacao final da janela: textura visivel no Studio GUI, pivos dos 16 Bones e escala/stud validados,
U1-U4 sem [verificar] no perfil roblox-r15; suite verde; pendencias registradas.

Comece rodando os quatro portoes para confirmar a base verde, e entao siga para o item 1.
```
