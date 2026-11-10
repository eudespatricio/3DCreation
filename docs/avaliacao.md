# Avaliação crítica do desenho original

> Escopo: o desenho da esteira (orquestrador → rotas A/B/C → Blender headless → GLB no `/assets`).
> Objetivo do desenho: ser **recurso de pipe**, chamado sob demanda por projetos de jogo.
> Data: 10/11/2026. Método: `CONSELHOS.md` §6.

## Resumo

O desenho está **certo no `o quê`** e **incompleto no `como plugar`**. Ele descreve um *script
poderoso*, não um *utilitário de build*. Das 14 lacunas abaixo, **11 não são de IA** — são de
contrato, estado, verificação, recurso e licença.

A proporção real de esforço num pipeline desses é ~**20 % geração** e ~**80 % contabilidade**:
saber o que já foi gerado, com qual entrada, se ainda vale, se pode entrar no jogo, e como provar
isso depois. O desenho investe 100 % no primeiro e 0 % no segundo.

## 1. O que o desenho acerta

| # | Acerto | Por que é bom |
|---|---|---|
| A1 | Separa por **rota estética**, não por "um modelo para tudo" | voxel por IA derrete quina de cubo: a intuição está correta |
| A2 | **Pós-processo obrigatório** em Blender headless | é exatamente onde asset bruto vira asset de jogo |
| A3 | **Lote declarativo** (YAML) em vez de comando interativo | é a pré-condição para virar passo de build |
| A4 | **Saída padronizada** (`.glb` + metadados) | glTF é o denominador comum de Godot/Unity/Unreal/Web |
| A5 | O LLM produz **estrutura** (Pydantic/JSON Schema), não arquivo solto | reduz o dano clássico de LLM gerando binário |

## 2. Lacunas

| # | Lacuna | Grav. | O que quebra na prática |
|---|---|---|---|
| L1 | **Sem contrato de integração**: nenhum CLI, exit code, formato de stdout ou versão de schema | **Bloqueante** | o pipe do jogo não tem como ramificar sucesso/falha; cada projeto cola um script |
| L2 | **Sem passo de plano** (dry-run com custo e cache) | **Bloqueante** | CI e dev gastam GPU para descobrir que o lote não mudou |
| L3 | **Sem estado entre execuções**: nada sabe o que já foi gerado | **Bloqueante** | todo build regenera tudo; git do jogo vira diff de binário; custo linear eterno |
| L4 | **Sem QC**: nenhum portão entre "gerou" e "entrou no jogo" | **Bloqueante** | mesh não-manifold, escala errada e textura faltando entram calados |
| L5 | **Sem governança de VRAM** | Alto | ComfyUI + modelo 3D + Blender não coexistem em 6 GB → `CUDA OOM` intermitente |
| L6 | **Determinismo não declarado** | Alto | impossível testar em CI: o mesmo lote gera hash diferente e "verde" não significa nada |
| L7 | **Sem manifesto/proveniência** | Alto | em 3 meses ninguém sabe com qual prompt, seed e modelo o asset nasceu |
| L8 | **Sem política de licença** | Alto | Hunyuan3D-2.x exclui UE/UK/Coreia; Pixal3D é não-comercial — passivo jurídico no jogo publicado |
| L9 | **Sem índice consultável** | Médio | "by demand" vira `ls`; achar "espada com menos de 800 tri" exige abrir arquivo |
| L10 | **LOD, colisão e pivô não estão no contrato** — só citados | Médio | cada projeto reimplementa a convenção de nome (`UCX_`) e erra |
| L11 | **Sem modelo de falha**: ComfyUI fora, OOM, Blender crash | Médio | uma falha no item 7 mata o lote inteiro sem checkpoint |
| L12 | **Sem drop-in de asset manual** | Médio | quem modela no Blockbench fica fora do QC e do manifesto |
| L13 | **Sem versionamento de prompt/spec/modelo** | Baixo | não se reproduz nem se compara versão de asset |
| L14 | **Naming depende do LLM** | Baixo | `id` e tags são justamente a parte que **precisa** ser determinística |

## 3. Contradições no lote de exemplo (concreto)

1. **`animacoes_base: ["idle","walk","attack_slash"]`** — nada no desenho gera animação. UniRig entrega
   esqueleto, não clipe. A chave promete o que a pipeline não entrega → ou sai da v0, ou vira escopo
   próprio com retarget. **Resolvido**: reservada, sem promessa (D14).
2. **`destino_exportacao: "C:/MeusJogos/..."`** — caminho Windows, mas tudo roda no WSL. Escrever em
   `/mnt/c` é I/O lento e o `edit` já falhou em UNC no projeto `conselho`. **Resolvido**: destino em
   ext4, sob allowlist (I12, I13).
3. **`estilo_global`** aplicado ao lote inteiro — um mapa modular e uma espada não têm o mesmo estilo
   nem a mesma rota. Estilo global deve ser **default**, rota é **por item**. **Resolvido**: `estilo_global`
   + `rota` por item, com override.
4. **`pivot: "empunhadura"`** — "empunhadura" não é um ponto: é uma **regra** que depende do tipo de
   objeto. Para mesh gerada, a empunhadura não é conhecida. **Resolvido**: pivô como par
   `{regra, eixo}` resolvido por perfil + heurística declarada, não string solta.
5. **`auto_rig: true` + compatibilidade Mixamo** — Mixamo, humanoid do Godot e R15 do Roblox são três
   esqueletos diferentes. "Compatível com Mixamo" não é um alvo verificável. **Resolvido**: esqueleto
   nomeado e versionado por perfil (`godot-humanoid@1`, `r15@1`).
6. **`minecraft_bedrock`** como valor de estilo — marca registrada em nome de produto e de tag.
   **Resolvido**: `blocky_voxel`, com alias legado aceito na entrada (D19, I14).

## 4. Excesso de escopo no v0

| # | Item | Por que sai | Volta em |
|---|---|---|---|
| E1 | Rota C completa (WFC + geometry nodes + fusão por setor) | é um produto inteiro; sem P1 validado, não há módulo aprovado para encaixar | P4 |
| E2 | Animação e retarget (Mixamo/UniRig) | em 6 GB é caro e instável, e o ganho por asset é baixo | P5, com critério visual |
| E3 | TRELLIS.2 / Hunyuan3D-2.1 como alvo | licença e VRAM: 16–24 GB e cláusula territorial | P3, só com benchmark próprio |
| E4 | ComfyUI como dependência obrigatória | a maior stack do ambiente para gerar imagem de concept; `sd.cpp`/`sf3d` cobrem | P3, atrás de provider |
| E5 | LLM no caminho crítico | o lote já é estruturado; LLM ali só adiciona não-determinismo e 4k de contexto | já existe como `draft`, opcional |

## 5. O desenho corrigido

```
ANTES (script linear)                 DEPOIS (pipeline com estado)
─────────────────────                 ─────────────────────────────
lote ──► LLM ──► rota ──► Blender     lote ──► validar(schema)
        ──► GLB no /assets                     ──► planejar (custo, cache)  ◄── CI roda aqui
                                                ──► gerar (staging, lock)
                                                ──► pós-processar (bpy)
                                                ──► verificar (QC G1–G9)
                                                ──► publicar (atômico)
                                                       │
                                          manifesto + índice + ledger
```

A diferença não é tecnológica, é de **propriedade**: no desenho antigo, rodar duas vezes produz dois
resultados e nenhuma memória. No corrigido, rodar duas vezes produz **zero trabalho** e o mesmo hash.

## 6. Veredito

1. **Aprovar** `plan → run → verify → publish` com QC como portão e publicação atômica.
2. **Aprovar** CLI + lote versionado como único contrato de integração na v0.
3. **Reprovar** geração acoplada: sem `plan`, sem cache e sem QC, a esteira não é chamável por outro
   pipe — é um script pessoal com boa propaganda.
4. **Adiar** Rota C, animação e dependência de ComfyUI (E1–E5).
5. **Fechar antes de P1**: Q2 (allowlist de destino) e Q6 (onde mora o cache).

Detalhamento em [`arquitetura.md`](arquitetura.md); números de modelo em
[`riscos-e-licencas.md`](riscos-e-licencas.md).
