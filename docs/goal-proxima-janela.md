# GOAL — próxima janela

> Copie o bloco do §9 como *objetivo da sessão* (Goal) na janela nova. Este arquivo é o briefing
> completo: objetivo, contexto, regras, ordem de execução, o que registrar e os portões.

## 1. Objetivo

Fechar a **P3** de forma utilizável: asset gerado com **UV + textura**, provider `i23d` publicando de
verdade, e **import validado no Godot 4.3**. Executar tudo o que couber na janela; o que não couber
entra em `docs/pendencias.md` com critério de aceitação — não como promessa.

## 2. Contexto mínimo (ler nesta ordem)

1. `CONTINUAR.md` — estado, números, armadilhas
2. `docs/pendencias.md` — o que falta, correções e decisões pendentes
3. `MAPA.md` — onde cada coisa mora
4. `DECISOES.md` §2 (decisões) e §4 (abertas)
5. `docs/gaps.md` — lacunas com condição de fechamento

## 3. Regras duras (não reabrir)

`D3` CLI-only · `D7` D1 byte-idêntico, D2 semeado, D3 fora do CI · `D9` QC sem bypass ·
`D11` GPU serializada · `D18` licença é gate · `D23` allowlist de destino · `D24` estado central em
`$FORGE3D_HOME` · `D25` isolamento (nada escrito no repo do jogo) · `D26` núcleo leve.

Proibido: modelo fechado por API · **SF3D em 6 GB** (GAP-035: ~8 min/imagem) ·
mudar `schemas/` sem bump `@2` · mexer em `INVARIANTES.md` sem virar teste.

## 4. Ordem de execução

| # | Tarefa | Aceitação |
|---|---|---|
| **1** | **P3-A — bake próprio**: em `blender/postprocess.py`, quando o bruto vier com cor por vértice e sem UV: `smart_project` por peça → bake da cor para PNG → material com textura | asset com `TEXCOORD_0` + PNG no manifesto; G3 e G5 verdes |
| **2** | **P3-B — provider `i23d`**: subprocesso na venv de GPU (`FORGE3D_VENV_I23D`), normalização canônica, medição, caminho `mesh` publicando | `forge3d run` com rota `mesh` publica 1 asset; `doctor` diz "pronto" |
| **3** | **P3-C — consolidar venvs** de torch (GAP-031) | uma venv de i23d; TripoSR continua rodando |
| **4** | **P3-D — separar asset**: corpo / capa / arma como `id` distintos, com teste | lote de 3 itens publicados |
| **5** | **C1** `doctor` do `mesh` olhar a venv certa · **C2** `verify` reexecutar gates G1–G9 | ambos com teste |
| **6** | Se sobrar janela: sondar **P2 Roblox** (importar no Studio, fechar U1–U4) | perfil sem `[verificar]` |

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
python -m pytest -q                            # suíte completa
bash tools/check-contexto.sh                   # tetos
python tools/check-p0.py                       # docs, schemas, I12/I14
```

## 7. Armadilhas já pagas (não repetir)

1. **`edit`/`write` em caminho UNC falha** (`GetFileSecurityW EIO`) → escreva por WSL.
2. **Blender 4.2 usa Python 3.11** — nunca `pip install` nele (I9).
3. **glTF divide vértice por costura de UV** → G1 solda antes de contar não-manifold.
4. **Peça de membro precisa sobrepor o pivô**, e nunca compartilhar canto exato (senão G1 reprova).
5. **Joelho e cotovelo giram em sentidos opostos**: local X negativo dobra o joelho, positivo do cotovelo.
6. **Mudou a saída de um provider? Suba `VERSAO`** — senão o cache serve o artefato velho.
7. **Três "torch ausente" diferentes**: núcleo (`.venv`), GPU (`~/.cache/forge3d/venv-gpu`),
   TripoSR (`~/.venvs/triposr`). O `doctor` precisa dizer qual.
8. **`nvidia-smi` vive em `/usr/lib/wsl/lib`** — script que sobrescreve `PATH` precisa incluí-lo.
9. **CMake 4.x quebra builds antigos** (use `<4`) e **`scipy` ≥1.14 exige numpy 2**.

## 8. Orçamento

Uma janela. Se não couber, entregar **1 e 2** (UV/bake + provider) e registrar 3–6 em
`docs/pendencias.md`. Não deixar teste vermelho ao encerrar.

## 9. Bloco para colar como Goal

```
Objetivo: continuar o Forge3D em /home/eudespatricio/3DCreation e fechar a P3 de forma utilizável,
executando tudo o que couber nesta janela; o que não couber entra em docs/pendencias.md com critério
de aceitação.

Leia, nesta ordem: CONTINUAR.md, docs/pendencias.md, MAPA.md, DECISOES.md §2 e §4, docs/gaps.md.
Não reabra D3–D26 nem o escopo (CLI-only, sem modelo fechado por API). SF3D está encerrado em 6 GB
(GAP-035: ~8 min/imagem); não reinstale.

Ordem de execução:
1) bake próprio de UV+textura em blender/postprocess.py para malha com cor por vértice (P3-A);
2) provider i23d real, chamando a venv de GPU por subprocess (FORGE3D_VENV_I23D), com normalização
   canônica e publicação (P3-B);
3) consolidar as venvs de torch (GAP-031);
4) separar o asset em corpo / capa / arma (P3-D);
5) corrigir doctor do mesh (C1) e verify reexecutando G1–G9 (C2);
6) se sobrar janela, sondar o perfil Roblox (P2).

Registre sempre: fato medido em DECISOES §1 com rótulo, lacuna em docs/gaps.md, pendência em
docs/pendencias.md, decisão em DECISOES §2. Mudança de schema exige bump de versão.

Portões antes de cada commit: python -m pytest tests/test_e2e_rapido.py -q (tem que passar em <30 s),
python -m pytest -q, bash tools/check-contexto.sh, python tools/check-p0.py.

Aceitação final da janela: 1 asset gerado com UV+textura aprovado no QC e importado no Godot 4.3 sem
ajuste manual; suíte verde; pendências registradas.

Comece rodando os quatro portões para confirmar a base verde, e então siga para o item 1.
```
