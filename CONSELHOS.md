# CONSELHOS — quando e como este projeto decide

> Conselho não é reunião. É o **último recurso** antes de uma decisão que não tem oráculo.
> Com teste, lint, schema ou benchmark, um modelo + um verificador resolve — e custa menos.

## 1. Gatilho: convocar só se ≥ 1 for verdadeiro

| # | Condição | Exemplo neste projeto |
|---|---|---|
| T1 | Decisão **irreversível** ou de custo de troca alto | formato do contrato de spec; escolha de modelo generativo |
| T2 | Não existe **oráculo determinístico** que responda | "qual modelo de 3D cabe em 6 GB?" |
| T3 | A resposta depende de **licença/Direito**, não de código | Hunyuan3D fora da UE; Stability Community License |
| T4 | Evidência **conflitante** entre fontes | D1 byte-idêntico vs D2 semeado |
| T5 | O custo do erro é **maior** que o custo de deliberar | perder semanas com Rota C sem validar P1 |

Se a pergunta é "como implementar X", **não é conselho** — é execução. Se é "este teste passa?",
**não é conselho** — é oráculo.

## 2. Papéis

| Papel | Função | Pode ser modelo local? |
|---|---|---|
| Operador | juiz final, dono do critério | humano, sempre |
| Arquiteto | propõe o desenho e o pré-registro | sim |
| Cético (red team) | ataca a proposta; obrigatório | sim |
| Operador de runtime | VRAM, tempo, disco, falha | sim |
| Licenças/IP | o que impede publicar | não — exige fonte citada |
| Pesquisa | números com fonte e rótulo | sim, com `[medido]`/`[estimado]` |

Juiz **nunca** é o modelo mais fraco da mesa (herdado de D4 do `conselho`).

## 3. Protocolo

1. **Pré-registro** — a pergunta, o critério de aceitação e o custo máximo são escritos **antes**.
2. **Rodada cega** — cada papel responde sem ver a resposta do outro.
3. **Crítica anonimizada** — respostas embaralhadas e sem autor; ordem trocada entre rodadas.
4. **Mudança de opinião sem evidência nova = conformidade**, e é registrada como tal.
5. **Síntese** — o juiz escolhe, e o que ele escolhe entra em `DECISOES.md` como `D<n>`.
6. **Dissenso não morre** — vai para §7 como "não resolvido", com a condição que o reabre.

## 4. Saída canônica

O artefato durável é **decisão, não conversa**: `D<n>` em `DECISOES.md`, `Q<n>` para o que ficou
aberto, e — quando for o caso — patch no schema. Transcript não é entregável.

## 5. Anti-padrões

- Convocar conselho para escolher nome de variável.
- Deixar o mesmo modelo propor, criticar e julgar.
- Rodada "cega" onde o segundo vê o primeiro.
- Deliberar sem pré-registro e depois escolher o critério que confirma a preferência.
- Trocar evidência por consenso: três modelos concordando não medem nada.

---

## 6. Registro — Conselho de arquitetura #1 (10/11/2026)

**Pergunta:** o desenho da esteira (orquestrador → rotas A/B/C → Blender → GLB) é suficiente para
ser chamado por projetos de jogo dentro dos seus pipes?

**Quórum:** operador (juiz) · arquiteto (agente) · pesquisa (arm com fontes) · cético.
**Pré-registro:** servir como recurso de pipe, por demanda, sem quebrar build de jogo.
**Custo máximo:** esta sessão.

**Respostas do operador ao questionário (4 perguntas):**
contrato = CLI + arquivo de lote · alvos = Godot 4 **e** Roblox R15 · escopo = **só arquitetura e
documentos** · GPU = instalar depois, provider plugável.

**Achado central:** o desenho está certo no *o quê* e incompleto no *como plugar*. Das 14 lacunas
levantadas ([`docs/avaliacao.md`](docs/avaliacao.md)), **11 não são de IA** — são de contrato,
contabilidade, verificação e recurso. A geração é ~20% do problema; o resto é engenharia de
pipeline. Sem `plan`, o pipe gasta GPU às cegas; sem cache, todo build regenera; sem QC, asset ruim
entra calado; sem manifesto, licença e origem se perdem.

**Veredito:**

1. Aprovado o fluxo `plan → run → verify → publish`, com **QC como portão** e publicação atômica.
2. Aprovado contratar por **CLI + lote versionado** (`spec@1`), sem HTTP e sem import de biblioteca.
3. Aprovado **não contratar** Rota C, animação/retarget e ComfyUI nesta fase (D14, D22).
4. Reprovado o ponto único de falha "um script que chama modelo": rota `import` entra no mesmo QC,
   porque asset feito à mão também precisa de escala, pivô e manifesto.
5. Reprovado nome de franquia no produto (`minecraft_bedrock` → `blocky_voxel`, D19).

**Dissensos não resolvidos (reabrem com evidência):**

| # | Dissenso | Reabre se |
|---|---|---|
| X1 | **SF3D** (qualidade/UV/PBR, licença Stability com registro e teto US$ 1 M) × **TripoSR** (MIT, topologia pior) | teste A/B com 10 assets reais em P3 |
| X2 | **ComfyUI** (nós oficiais, stack pesada) × **`sd.cpp`/CLI** (leve, sem Python, sem ecossistema) | necessidade de nó específico que a CLI não cobre |
| X3 | **TRELLIS.2 Q4** como upgrade de qualidade: só há medição pública em 16 GB, em 6 GB é experimental | benchmark próprio em P3 com tempo e falha medidos |
| X4 | Escala Roblox (1 stud ≈ 0,28 m) e formato de rig R15 | teste com o importador do Roblox Studio |
| X5 | Nome do produto `forge3d` | decisão do operador |

**Custo deste conselho:** uma sessão, zero código de pipeline. Nenhum número novo foi medido — os
da pesquisa entram com rótulo em [`docs/riscos-e-licencas.md`](docs/riscos-e-licencas.md).

## 7. Quando não convocar

Mudança de naming interno, escolha de biblioteca com benchmark óbvio, correção de bug com teste
vermelho, refactor com cobertura. Nesses casos o oráculo já respondeu — chamar conselho é gastar
contexto para produzir opinião.
