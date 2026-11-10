---
name: context-recovery
description: Auditoria determinística de repositório que transforma caos documental em testes executáveis e contexto residente enxuto. Use ao iniciar trabalho em projeto existente, ao assumir repositório herdado ou quando docs e código divergirem.
---

# context-recovery

Protocolo portátil para revisar um projeto antes de executar. A lente é sempre a mesma; a
implementação muda com a linguagem (aqui: **Python + Blender headless**).

## Princípio

> Markdown de auditoria é **artefato de transição**, não memória permanente.
> Contradição vira commit. Invariante vira teste. Só o contexto residente mínimo fica.

Memória passiva em `.md` no contexto do agente custa tokens, gera dupla verificação e apodrece.
O valor está em **compilar** a intenção em algo que o CI cobra sozinho.

## Camadas

| Camada | Portátil? | Destino |
|---|---|---|
| Protocolo (este arquivo + templates) | sim | pasta global de skills |
| Artefatos de transição (`CONTRADICOES.md`) | não | morre ao fechar as linhas |
| Contexto residente (`MAPA`, `CONTINUAR`, `INVARIANTES`) | template fixo, conteúdo local | raiz do repo, com teto de linhas |

## Fase 1 — Radiografia (zero LLM, custo zero)

```bash
git log -1 --format='%cs %h %s' -- <arquivo>   # idade real do que se lê
git ls-files | sed 's/.*\.//' | sort | uniq -c | sort -rn | head
wc -l *.md docs/*.md | sort -n                  # onde o contexto vai estourar
python -m compileall -q src/                     # quebrou? nem comece
grep -rn "\[verificar\]\|\[estimado\]\|TODO" --include=*.md . | wc -l
```

Coleta: topografia de código e docs, idade por último commit, símbolos, órfãos de teste, configs,
alertas (monolitos, docs defasados, zero oráculos). **Nenhuma inferência.**

Neste repo, o equivalente a "símbolos" em P0 é `schemas/`: se o schema não valida, não há contrato.

## Fase 2 — Triangulação (a IA entra)

Hierarquia de autoridade: **decisão humana > código + teste > documento por data**.

1. Compare cada doc com o que a radiografia provou (constantes, fluxos, assinaturas, exit codes).
2. Escreva a tabela `CONTRADICOES.md`: onde, o que diz, o que o código faz, gravidade.
3. Entreviste o autor com no máximo 5 perguntas — o agente **não adivinha** intenção.
4. Separe o que é contradição de doc (resolve sozinho) do que é decisão de produto (pergunta).

Neste repo, contradição de contrato é a mais grave: `docs/` dizendo um campo e `schemas/` dizendo
outro quebra o pipe do jogo consumidor.

## Fase 3 — Compilação (texto vira código)

- Cada linha de `CONTRADICOES.md` vira patch e é apagada.
- Cada invariante vira teste executável (`tests/invariants/test_i<n>_*.py`, roda com `pytest`).
- Regra que não dá para testar vira **pergunta**, não parágrafo.
- Teste que falha por estar errado também é achado: conserte o teste, não a regra.

**Neste repo, `INVARIANTES.md` é artefato de transição.** Ele existe porque a implementação ainda
não existe (P0). Cada item morre quando o teste correspondente entra em `tests/invariants/`, e sobra
só o comando de verificação. Um `INVARIANTES.md` que sobrevive à implementação virou dupla
verificação — e é o anti-padrão conhecido.

## Fase 4 — Contexto residente

| Arquivo | Teto | Regra |
|---|---|---|
| `MAPA.md` | 60 linhas | 1 linha por responsabilidade + armadilhas |
| `CONTINUAR.md` | 200 linhas | sobrescrito, nunca append — é o `ESTADO` + handoff deste repo |
| `INVARIANTES.md` | 200 linhas | toda linha morre ao virar teste |
| `AGENTS.md` | 80 linhas | ordem de leitura + regras duras |
| `DECISOES.md` | sem teto | **ledger append-only**; agente lê só §2 e §4 |

Nada além disso na raiz. `docs/` guarda profundidade que se lê **por demanda**, não por reflexo.

## Adaptação para Python + Blender

- `pytest` é o oráculo: não existe "verificado no olho".
- Schema (`jsonschema`) é o teste do contrato — valide o manifesto **de terceiro**, não só o próprio.
- Determinismo vira hash: `D1` compara bytes; `D2` compara faixa (tri, bbox, material). Nunca prometa
  `D1` para diffusion.
- Blender entra por `subprocess` (4.2 pinado) e sai por **arquivo JSON**; `stdout` do Blender não é API.
- Regras que **não** viram teste unitário: estética ("ficou bonito"), licença de modelo, escala do
  importador de engine. Viram checklist de PR com fonte citada, ou `[verificar]` no perfil.

## Critérios de saída

1. `CONTRADICOES.md` vazio ou inexistente.
2. `invariants` verde no CI.
3. Teto de linhas verde (`tools/check-contexto.sh`).
4. Radiografia sem "doc defasado" inexplicado.
5. `DECISOES.md` §3 (rejeitados) com data e condição de reabertura.

## Anti-padrões

- Manter `INVARIANTES.md` permanente depois da implementação: vira dupla verificação.
- Listar contradição sem dono/decisão: vira arquivo morto.
- Auditar sem scanner: opinião disfarçada de fato.
- Reescrever o mundo: a saída é o mínimo viável de contexto, não um manual.
- Prometer `D1` para modelo generativo e descobrir no CI.
