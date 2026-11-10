# Forge3D — esteira de assets 3D por demanda

> Utilitário de linha de comando que transforma um **lote declarativo** (YAML/JSON) em assets
> finais prontos para o jogo — glTF/GLB com escala, pivô, LOD, colisão, rig e manifesto — e
> publica de forma atômica na pasta do projeto consumidor.

**Estado:** `P0` — escopo, arquitetura e contratos fechados. **Ainda não existe código de pipeline.**
Leia [`AGENTS.md`](AGENTS.md) antes de qualquer ação.

---

## O problema

Cada projeto de jogo precisa de assets. Hoje cada projeto resolve isso do seu jeito: modela à mão,
baixa pack, ou cola um script de geração. O resultado é sempre o mesmo:

- o asset chega com escala errada e alguém conserta no editor;
- o pivô está na origem do mundo e a arma flutua na mão;
- são 50 mil triângulos para uma espada;
- não se sabe com qual prompt, modelo ou licença aquilo foi gerado;
- rodar o build de novo gera arquivos diferentes e suja o git do jogo.

**Forge3D existe para tornar a geração de asset um passo de build**: reprodutível, verificável,
barato de repetir e seguro de plugar em pipe de terceiros.

## Como um projeto de jogo usa isto

O contrato é **um comando, um arquivo, um código de saída**. Nada de importar código, nada de daemon.

```bash
# O que seria feito — não gasta GPU, não escreve nada. É o que roda no CI de pull request.
forge3d plan   lote_01.yaml --json

# Executa: gera, pós-processa, verifica QC e publica no destino do jogo.
forge3d run    lote_01.yaml --json

# Portão de CI sobre o que já está publicado: valida manifesto, QC e integridade.
forge3d verify res://assets/importados --json

# "by demand": o que já existe, filtrável, sem gerar nada.
forge3d query  --tag weapon --max-tris 800 --json

# Diagnóstico do ambiente antes de culpar a pipeline.
forge3d doctor
```

Branching no pipe é por **código de saída estável** (§5 de [`docs/contratos.md`](docs/contratos.md)):
`0` ok · `2` spec inválida · `3` QC reprovado · `4` ambiente · `5` provider · `6` recurso bloqueado · `7` parcial.

## O lote

[`examples/lote_01.yaml`](examples/lote_01.yaml) é a referência executável do schema.
Cada item declara rota, altura, pivô, orçamento de triângulos, colisão e LOD; o perfil decide o resto.

```yaml
schema: forge3d/spec@1
projeto: RPG_Dungeon
perfil: godot4
destino_exportacao: /home/eudespatricio/Games/GameZero/assets/importados
paleta: ["#0d0d0f", "#ff5a1f", "#c9a227"]

lote:
  - id: weapon.sword.fire.01
    tipo: prop_equipavel
    rota: blocky
    prompt: "Espada larga de ferro negro com runas de lava na lâmina, cabo de couro gasto"
    altura_metros: 1.10
    pivot: empunhadura
    limite_triangulos: 800
```

## As quatro rotas

| Rota | Para quê | Determinismo | Custo | Estado |
|---|---|---|---|---|
| `blocky` | voxel/blocky, item, personagem de blocos | **D1** (byte-idêntico) | segundos, sem GPU | P1 |
| `import` | asset feito à mão (Blockbench/Blender) entra no mesmo QC | D1 | zero | P1 |
| `mesh` | 3D orgânico/detalhado via modelo local | D2 (semeado) | 10 s–15 min em 6 GB | P3 |
| `modular` | dungeon/cenário por WFC + montagem | D1 (seed fixa) | segundos | P4 |

Detalhe em [`docs/rotas-e-providers.md`](docs/rotas-e-providers.md). A GPU é **opcional**:
o sistema é útil sem ela e é isso que o mantém barato de rodar no seu pipe.

## Por que não é só "um script que chama um modelo"

Porque o modelo é a parte fácil. O que faz a diferença em produção:

1. **Plano antes da execução** — custo, cache e bloqueio de recurso calculados sem gastar GPU.
2. **Cache por conteúdo** — `sha256(spec + versão da pipeline + versões dos providers)`; rerun sem
   mudança não toca um único arquivo.
3. **Governança de VRAM** — em 6 GB, um job de GPU por vez, com descarregamento explícito.
4. **QC como portão** — manifold, orçamento de triângulos, escala ±0,5 %, pivô 1 mm, UV, materiais,
   rig, licença. Reprovou, não publica.
5. **Publicação atômica** — staging → *rename*; nunca se escreve direto na pasta do jogo.
6. **Manifesto e proveniência** — modelo, seed, versões, hash do spec e licença de cada asset.
7. **Degradação explícita** — GPU fora do ar bloqueia só as tarefas que precisam dela.

## Verificar esta entrega

O P0 é verificável — não é opinião. Um comando:

```bash
uv run --no-project --python 3.12 --with pyyaml --with jsonschema python tools/check-p0.py
```

Valida os dois schemas, os lotes de exemplo, o manifesto de exemplo, os perfis, os tetos de
contexto e os invariantes I12/I14. Sai `0` em silêncio ou lista exatamente o que falhou.

## Documentos

| Quero saber | Leia |
|---|---|
| onde cada coisa mora e as armadilhas | [`MAPA.md`](MAPA.md) |
| o que foi decidido e por quê | [`DECISOES.md`](DECISOES.md) |
| regras que quebram o projeto se violadas | [`INVARIANTES.md`](INVARIANTES.md) |
| avaliação crítica do desenho original | [`docs/avaliacao.md`](docs/avaliacao.md) |
| arquitetura completa | [`docs/arquitetura.md`](docs/arquitetura.md) |
| como retomar uma sessão | [`CONTINUAR.md`](CONTINUAR.md) |
| método de decisão por conselho | [`CONSELHOS.md`](CONSELHOS.md) |

## Escopo explicitamente fora da v0

Animação/retarget automático, geração de mapa completo (Rota C), servidor HTTP, MCP, e qualquer
modelo fechado por API. A lista com motivos está em [`DECISOES.md`](DECISOES.md) §3.
