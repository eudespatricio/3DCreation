"""Pendências e correções que demandam atenção.

> Regra: item sem critério de aceitação não entra aqui — vira conversa.
> Prioridade: **A** = destrava a fase seguinte · **B** = correção que já morde · **C** = dívida aceitável.

Última revisão: 10/11/2026 (transição de janela).

## 1. Bloqueiam a próxima fase (P3 fechar)

| # | Pendência | Por que importa | Aceitação | Prio |
|---|---|---|---|---|
| P1 | **UV + bake próprios** no `blender/postprocess.py` para malha com cor por vértice | é o que falta para asset gerado entrar em jogo; TripoSR só entrega `COLOR_0` (GAP-028) | asset gerado com `TEXCOORD_0` + PNG no manifesto, QC G3/G5 verdes | **A** |
| P2 | Provider `i23d` de verdade: chama a venv de GPU por `subprocess`, normaliza frame, mede e publica | hoje `mesh` bloqueia com "torch ausente" porque checa a venv errada | `forge3d run` com rota `mesh` publicando 1 asset; `doctor` dizendo "pronto" | **A** |
| P3 | Consolidar venvs de torch (`~/.venvs/triposr` 2.5.1 × `~/.cache/forge3d/venv-gpu` 2.4.1) | 2,5 GB duplicados e dois lugares para "onde está o modelo" (GAP-031) | uma única venv de i23d, selecionada por `FORGE3D_VENV_I23D` | **A** |
| P4 | **Separar o asset**: corpo / capa / arma como `id` distintos | é a causa raiz medida da oclusão (capa funde o corpo no reconstructor) | lote com 3 itens do mesmo personagem publicados e montados no Godot | **A** |

## 2. Correções que já mordem

| # | Correção | Sintoma hoje | Aceitação | Prio |
|---|---|---|---|---|
| C1 | `doctor` do provider `mesh` olha a venv do núcleo | diz "torch ausente" mesmo com torch instalado na venv de GPU | `doctor` reporta `mesh: pronto` quando a venv de GPU existe | **B** |
| C2 | `verify` não reexecuta os gates G1–G9 | pega hash/schema, mas não revalida escala/pivô contra o perfil atual | `verify` reprova asset cujo GLB foi trocado por outro válido | **B** |
| C3 | Sem `gc` de cache e ledger | cache cresce sem teto (orçamento declarado: 20 GB) | `forge3d gc --manter-dias 30` testado | **B** |
| C4 | `MAPA.md` em 59/60 linhas | qualquer ferramenta nova estoura o teto e o gate falha | mapa reorganizado com folga ≥ 3 linhas | **B** |
| C5 | Flake não reproduzido na suíte e2e (GAP-019) | uma execução deu `ERROR` em 3 fixtures e não repetiu | 10 execuções seguidas verdes, ou causa identificada | **C** |
| C6 | `tools/delegar.py` depende da IDE aberta | falha com mensagem clara, mas não tem caminho sem IDE | decisão entre chave de API e `agentapi` registrada (Q9) | **C** |

## 3. Decisões que precisam do operador

| # | Pergunta | Contexto medido | Prio |
|---|---|---|---|
| Q8 | SF3D × TripoSR | SF3D: geometria OK, **~8 min/imagem** e bake exige CUDA toolkit. TripoSR: 1,8–3,6 s, sem UV. **Recomendação registrada: encerrar SF3D em 6 GB (GAP-035)** | **A** |
| Q9 | delegação: chave de API × `agentapi` | `agentapi` é sessão agêntica com execução de ferramenta (GAP-030) | B |
| Q3 | escala/rig Roblox | perfil escrito, nunca validado no Studio | B |
| Q1 | nome definitivo do produto | `forge3d` é provisório | C |
| Q7 | assets no git do jogo: normal × LFS | primeiro asset real ainda não integrado | C |

## 4. Fechado nesta janela (não reabrir)

- acesso gated do HF resolvido e documentado (`docs/dependencias.md` §4);
- `texture_baker` compila em CPU sem `nvcc` (limitação registrada em GAP-034);
- `gpytoolbox` contornado por import opcional (GAP-033);
- frame canônico de malha gerada resolvido em `tools/normalize_mesh.py`;
- canal `agentapi` mapeado e testado (`docs/delegacao.md` §9).

## 5. Como usar este documento

1. Item concluído sai daqui e vira linha em `DECISOES.md` §1 (fato medido) + commit.
2. Item que cresce vira `GAP` em `docs/gaps.md`.
3. Revisão obrigatória no fim de cada fase — documento de pendência que ninguém poda vira ficção.
