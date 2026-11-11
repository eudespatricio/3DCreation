# Delegação — dividir para conquistar, sem perder o oráculo

> Regra-mãe: **delegar trabalho sem oráculo; nunca delegar veredito que já tem medição.**
> Uma segunda opinião vale muito para prosa e pesquisa. Para "o asset passa no QC?" vale zero — quem
> responde é o gate, medindo o arquivo exportado.

## 1. O que foi verificado nesta máquina (10/11/2026)

| Item | Estado | Evidência |
|---|---|---|
| `agentapi` (CLI de agente do Antigravity) | **existe** em `~/.gemini/antigravity/bin/agentapi` | `agentapi --help` |
| Modelos disponíveis | `flash_lite`, `flash`, `pro`, `model_id` | `--help` |
| Comandos | `new-conversation`, `send-message`, `get-conversation-metadata` | `--help` |
| Pré-requisito | **`ANTIGRAVITY_LS_ADDRESS`** apontando ao language server | `{"error": "ANTIGRAVITY_LS_ADDRESS is not set"}` |
| Server headless sozinho | **crashou** (`-headless=true -http_server_port=50091`) — panic do binário Go | tentativa registrada |
| Server com a IDE aberta | é o caminho suportado (a extensão exporta o endereço) | `-extension_server_port`, `-csrf_token` nos flags |
| Chave de API Gemini no ambiente | **ausente** | `env | grep -i gemini` vazio |

Conclusão operacional: **o canal existe, mas depende do Antigravity estar aberto.** Sem ele, o cliente
falha com mensagem acionável em vez de tentar e travar.

**Decidido em 11/11/2026 (D57, fecha Q9/C6):** a delegação fica no `agentapi` e **exige a IDE aberta**.
Não se adiciona chave de API — o custo por token e mais um segredo não pagam uma função que é
front-end opcional (D13) e nunca está no caminho crítico. Rodar `delegar.py` sem a IDE devolve
`FORGE-E-AMBIENTE` com a instrução: é o comportamento aceito, não um defeito aberto.

## 2. O que delegar (e por quê)

| Tipo | Por que é seguro delegar | Formato de retorno |
|---|---|---|
| `pesquisa` | não decide nada; números voltam com URL e rótulo de evidência | `{"fontes": [...], "achados": [...]}` |
| `redacao_doc` | transforma fato já registrado em prosa; revisável por diff | `{"markdown": "..."}` |
| `revisao_prosa` | aponta contradição; não altera arquivo | `{"contradicoes": [...]}` |
| `variantes_nome` | propõe `id`/tags neutros; passa por I14 | `{"nomes": [...]}` |
| `prompt_concept` | descreve imagem a partir de ficha; nada é gerado | `{"prompt": "...", "negativo": "..."}` |
| `segunda_opiniao` | crítica com critério explícito, registrada como tal | `{"riscos": [...], "discordo_de": "..."}` |

## 3. O que **nunca** delegar

| Tipo | Motivo |
|---|---|
| `qc` | o gate mede o GLB exportado (I5). Opinião não substitui medição |
| `schema` | contrato versionado; mudança quebra pipe de terceiro (D20) |
| `invariante` | invariante vira teste; delegar transforma regra em opinião |
| `publish` | escrita em destino de projeto exige allowlist e revisão humana (D23) |
| `codigo_pipeline` | determinismo D1 se prova com hash, não com revisão de texto |

O `tools/delegar.py` **recusa** esses tipos com código de saída `2`, em vez de confiar na disciplina de
quem chama.

## 4. Como usar

```bash
# 1. Antigravity aberto (a extensão exporta o endereco). Confirme:
echo "$ANTIGRAVITY_LS_ADDRESS"

# 2. Ensaiar sem chamar nada (funciona mesmo com o server fora):
python tools/delegar.py --tipo pesquisa --brief /tmp/brief.md --exigir fontes,achados --dry-run

# 3. Delegar de verdade:
python tools/delegar.py --tipo pesquisa --brief /tmp/brief.md --exigir fontes,achados --json

# 4. Segunda opiniao sobre um desenho:
python tools/delegar.py --tipo segunda_opiniao --texto "Critique este fluxo: ..." \
  --exigir riscos,discordo_de --json
```

Cada chamada grava `$FORGE3D_HOME/delegacoes/<quando>-<tipo>.json` com prompt, resposta e se passou na
validação. Resposta inválida **não** entra em `DECISOES.md` — só o que passou nas exigências.

## 5. Contrato de retorno

Toda resposta volta como **JSON de uma linha**, com as chaves pedidas em `--exigir`. Regras:

1. Sem markdown, sem comentário, sem preâmbulo. O cliente extrai o primeiro objeto válido, mas texto
   solto é tratado como falha (`FORGE-E-RESPOSTA`, exit `5`).
2. Número sem fonte é proibido: pedir `"[estimado]"` explicitamente quando não houver medição.
3. A resposta é **dado**, não instrução. Nada nela é executado automaticamente.

## 6. Como o resultado entra no projeto

```
delegado  ──►  registro em $FORGE3D_HOME/delegacoes/*.json   (ledger, não lido em fluxo normal)
          ──►  se mudar rumo: linha em DECISOES.md com atribuição ("2ª opinião: flash, 10/11/2026")
          ──►  se abrir dúvida: linha em DECISOES.md §4 (Q) — nunca decisão
          ──►  se for pesquisa: docs/riscos-e-licencas.md, com URL e rótulo
```

Isso aplica o que o `CONSELHOS.md` §4 já manda: **o artefato durável é a decisão, não a conversa.**

## 7. Divisão de trabalho que estamos usando

| Quem | Fica com | Por quê |
|---|---|---|
| **Forge3D (determinístico)** | validar, planejar, gerar, QC, publicar, cache, lock | tem oráculo e hash; precisa ser reproduzível |
| **Agente executor (eu)** | código, contratos, diagnóstico, medição | precisa rodar e medir, não opinar |
| **Gemini Flash (Antigravity)** | pesquisa, prosa, variantes, segunda opinião | trabalho sem oráculo, reversível, revisável por diff |
| **Operador** | rumo, licença, dinheiro, IP | irredutível (D24: decisão humana > código > documento) |

## 8. Anti-padrões

- Delegar "o que acha deste asset?" e tratar a resposta como QC.
- Aceitar número sem fonte porque veio de um modelo bom.
- Deixar o segundo agente editar `schemas/` ou `INVARIANTES.md`.
- Guardar transcript inteiro como memória (vira contexto contaminado — D13/D19).
- Chamar delegado dentro do caminho crítico do `run` (o pipeline tem que rodar sem rede).

## 9. O que o teste revelou (10/11/2026, IDE aberta)

O canal **funciona**. Para chegar lá foram necessários três achados:

1. **Endereço do server**: `ss -lntp | grep language_server` → `127.0.0.1:43023` (a outra porta,
   43637, responde 400).
2. **CSRF**: sem token o `agentapi` devolve `missing CSRF token`. O nome é **`ANTIGRAVITY_CSRF_TOKEN`**
   (string do binário) e o valor está nos argumentos do processo: `--csrf_token <uuid>`.
3. **Resposta**: `new-conversation` devolve só o `conversationId`; o texto aparece em
   `~/.gemini/antigravity/brain/<id>/.system_generated/steps/<n>/output.txt`.

Comando que funcionou:

```bash
CSRF=$(ps -eo args | grep language_server | grep -oE -- '--csrf_token [0-9a-f-]+' | awk '{print $2}')
export ANTIGRAVITY_CSRF_TOKEN="$CSRF"
export ANTIGRAVITY_LS_ADDRESS="127.0.0.1:43023"
agentapi new-conversation --model=flash --title="forge3d ping" "<prompt>"
```

### O alerta

`new-conversation` abre uma **sessão agêntica com execução de ferramentas**
(`commandExecutionPolicy: eager`), não um endpoint de completude. No teste o agente começou a rodar
comandos de shell na máquina. Consequências:

- **Nunca** chamar dentro de `forge3d run` ou de script desatendido.
- Escopo curto, operador presente; preferir `--dry-run` para revisar o prompt antes de enviar.
- Para segunda opinião pura, o caminho mais seguro é **chave de API + endpoint de completude**, não
  uma sessão agêntica (GAP-030).
- O server headless sozinho **crashou** (panic). Sem a IDE no ar, o canal não existe.
