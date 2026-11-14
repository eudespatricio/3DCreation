# Arquitetura — Forge3D

> Documento de desenho. Contratos exatos em [`contratos.md`](contratos.md); rotas em
> [`rotas-e-providers.md`](rotas-e-providers.md); perfis em [`perfis-export.md`](perfis-export.md).

## 1. Problema

Transformar uma **intenção declarativa** ("5 espadas elementais, 2 guardas esqueletos, tema de lava")
em **arquivos de jogo verificáveis** — escala certa, pivô certo, topologia dentro do orçamento, LOD,
colisão, esqueleto, licença registrada — de modo que qualquer projeto de jogo possa chamar isso como
**passo de build**, sob demanda, sem que o resultado dependa de sorte.

Duas exigências dominam o desenho:

1. **Barato de repetir.** Build de jogo roda muitas vezes por dia. Se gerar asset custa caro a cada
   vez, ninguém usa.
2. **Seguro de confiar.** Um asset que entrou errado no jogo custa mais caro do que um asset que não
   entrou. Logo, reprovar tem que ser fácil e barato.

## 2. Princípios

| # | Princípio | Consequência prática |
|---|---|---|
| P1 | **Plano e execução são separados** | `plan` é puro, rápido e roda em CI sem GPU |
| P2 | **O que é determinístico é testado como determinístico** | D1 tem hash; D2 tem faixa; D3 não entra em CI |
| P3 | **Fronteira única com o mundo**: CLI + lote + exit code | nada de importar código do Forge3D dentro do jogo |
| P4 | **Estado é explícito**: cache, índice, ledger, manifesto | nenhuma decisão depende de "o que está na pasta" |
| P5 | **Publicação é o único momento de escrita no destino** | staging + `rename`; nada parcial |
| P6 | **Falha é local ao item** | um asset ruim não derruba o lote; bloqueio é estado, não exceção |
| P7 | **Recurso é restrição de primeira classe** | 6 GB de VRAM entram no desenho, não no runbook |
| P8 | **Engine não entra na lógica** | engine entra em perfil (declarativo) |
| P9 | **Todo artefato é rastreável** | `spec_hash` + provider + versão + seed + licença |
| P10 | **Degradar é preferível a falhar** | GPU fora → `blocky` continua, `mesh` fica `blocked` |
| P11 | **Isolamento por padrão** | sem config do cwd, sem escrita fora do estado próprio ou de destino autorizado (D23–D25) |

## 3. Fluxo

```
                 lote.yaml / lote.json
                          │
        ┌─────────────────▼──────────────────┐
        │ 1. VALIDAR       spec@1/spec@2     │  JSON Schema + regras de negócio
        │                   + normalização   │  defaults por perfil, aliases legados
        └─────────────────┬──────────────────┘  exit 2 se inválido
                          │  Spec canônica (JSON ordenado)
        ┌─────────────────▼──────────────────┐
        │ 2. PLANEJAR      puro, sem GPU     │  expande itens → tarefas
        │                   sem escrita      │  chave de cache, miss/hit
        │                                    │  estima tempo/VRAM/disco
        └─────────────────┬──────────────────┘  Plano (JSON) — revisável e auditável
                          │
        ┌─────────────────▼──────────────────┐
        │ 3. GERAR         staging apenas    │  blocky | import | mesh | modular
        │                  lock de GPU       │  bruto em staging/<asset>/
        └─────────────────┬──────────────────┘  exit 5/6 por item
                          │  RawAsset (bruto + declaração de determinismo)
        ┌─────────────────▼──────────────────┐
        │ 4. PÓS-PROCESSAR blender 4.2 -b    │  normaliza escala/pivô
        │                  subprocess        │  LOD, colisor, rig-transfer
        │                  canal = JSON      │  export por perfil
        └─────────────────┬──────────────────┘
                          │  Candidato (.glb + texturas)
        ┌─────────────────▼──────────────────┐
        │ 5. VERIFICAR     QC G1..G10        │  mede o arquivo exportado
        │                                    │  reprovou → exit 3, nada publica
        └─────────────────┬──────────────────┘
                          │  Candidato aprovado + manifesto
        ┌─────────────────▼──────────────────┐
        │ 6. PUBLICAR      atômico           │  staging → destino (rename)
        │                                    │  índice SQLite + ledger JSONL
        └─────────────────┬──────────────────┘
                          ▼
        destino/ + .forge/runs/<run_id>/manifest.json
                └── exit 0 | 7 (parcial) | 3 | 5 | 6
```

**O passo 2 é o que faz isto ser um utilitário e não um script.** Sem ele, cada chamada paga o custo
inteiro e o CI não tem como perguntar "mudou algo?".

## 4. O que existe em disco em cada passo

| Passo | Entrada | Saída | Persistente? |
|---|---|---|---|
| 1 validar | `lote.yaml` | spec canônica em memória | não |
| 2 planejar | spec canônica | `.forge/runs/<id>/plano.json` | sim (auditoria) |
| 3 gerar | tarefa do plano | `.forge/staging/<asset_id>/bruto/` | sim até publicar |
| 4 pós-processar | bruto + perfil | `.forge/staging/<asset_id>/final/` | sim até publicar |
| 5 verificar | final + perfil | `relatorio_qc.json` (dentro do staging) | sim (vai no manifesto) |
| 6 publicar | aprovado + manifesto | `destino/` + índice + ledger | sim |

`staging` e `destino` **precisam estar no mesmo sistema de arquivos** para o `rename` ser atômico. Se
estiverem em mounts diferentes, `publish` faz `copia + fsync + rename` dentro do diretório de destino —
e isso é detectado e registrado no relatório, não ignorado.

## 5. Camadas e fronteiras

| Camada | Módulo (P1) | Responsabilidade | Pode importar | **Não pode** |
|---|---|---|---|---|
| Interface | `cli/` | parse de argumentos, exit codes, stdout JSON | tudo, só como orquestração | conter regra de negócio |
| Contrato | `spec/` | schema, normalização, aliases, validação | stdlib, jsonschema, PyYAML | tocar em provider ou disco de asset |
| Planejamento | `plan/` | expandir, hash, cache lookup, estimativa | `spec/`, `profiles/` | executar provider, escrever em destino |
| Geração | `providers/` | produzir bruto; declarar determinismo e custo | sdk do modelo, `resources/` | exportar, publicar, medir QC |
| Pós-processo | `post/` | orquestrar `blender/*.py`; perfil | `subprocess`, `spec/` | decidir aprovação |
| Verificação | `qc/` | medir artefato, emitir gates | leitor de glTF/bpy | corrigir o asset |
| Publicação | `publish/` | manifesto, índice, ledger, rename atômico | `spec/`, `qc/` | gerar ou corrigir |
| Recurso | `resources/` | lock de GPU, VRAM, disco, `doctor` | sistema | conhecer rota ou spec |

Regra de dependência: **para baixo, sempre; para cima, nunca**. `providers` não chama `publish`;
`qc` não chama `providers`. Ciclo de import é bug de arquitetura.

## 6. Determinismo

Três classes, declaradas pelo provider e validada pelo pipeline (D7):

| Classe | Significa | Como o CI trata | Rotas |
|---|---|---|---|
| **D1** | mesma entrada ⇒ mesmo `sha256` | teste de hash exato | `blocky`, `import`, `modular` |
| **D2** | mesma entrada + mesmo ambiente ⇒ mesmo asset "na forma" | faixa de triângulos, bbox, materiais, e hash opcional com `seed` fixa | `mesh` |
| **D3** | não reprodutível (modelo remoto, sampler livre) | **não entra em CI**; exige aprovação humana antes de `publish` | nenhuma na v0 |

Consequência honesta: **não se promete D1 para diffusion**. Driver, versão de biblioteca e GPU mudam
o resultado. Prometer isso produz um CI que falha por motivo irrelevante — e um CI assim é desligado
na segunda semana.

## 7. Governança de recursos (o chão de 6 GB)

Três restrições reais: **6.144 MiB de VRAM**, **15 GB de RAM**, **um usuário**.

1. **Lock de GPU** — arquivo `.forge/locks/gpu.lock` com `pid`, `run_id`, `criado_em`. Segundo
   processo espera (padrão) ou sai `6` (`--sem-espera`). Lock órfão é detectado por `pid` morto e
   por idade máxima configurada.
2. **Residência de modelo** — cada provider declara `vram_estimada_mb` e `descarregar_apos_idle_s`.
   O pipeline agrupa tarefas por provider para pagar o carregamento uma vez, e descarrega ao trocar.
3. **Serialização, não paralelismo** — em 6 GB, paralelizar modelos é receita de OOM. Paralelismo
   existe só entre *itens do mesmo provider* e apenas quando ele declara suportar (`lote_min`).
4. **Preflight** — `doctor` mede VRAM livre **agora**, não a nominal. Falta de recurso vira `blocked`
   com razão, não traceback.
5. **Blender não é GPU-bound** para a rota `blocky`: ele pode rodar em paralelo ao passo 3, mas o
   pós-processo de `mesh` compete por VRAM e entra na mesma fila.

## 8. Falha e degradação

| Falha | Comportamento | Exit | Código |
|---|---|---|---|
| Spec inválida | aborta antes de qualquer trabalho | 2 | `FORGE-E-SPEC` |
| Ambiente quebrado (Blender, perfil, schema, disco) | aborta no preflight | 4 | `FORGE-E-AMBIENTE` |
| Provider ausente (modelo não instalado) | item `blocked`, lote segue | 7 | `FORGE-E-PROVIDER` |
| Provider falhou (crash, resposta inválida) | item `failed`, lote segue conforme `politica.falha` | 5 | `FORGE-E-PROVIDER-RUN` |
| VRAM insuficiente / lock ocupado | item `blocked` (não `failed`) | 6 | `FORGE-E-RECURSO` |
| Blender crash no pós-processo | retry 1× em processo novo; depois `failed` | 5 | `FORGE-E-BPY` |
| QC reprovou | item `rejected`, nada publicado | 3 | `FORGE-E-QC` |
| Manifesto inválido no destino | `verify` falha | 3 | `FORGE-E-MANIFEST` |
| Licença não permite uso comercial | item `blocked` | 5 | `FORGE-E-LICENCA` |
| Destino fora da allowlist | aborta | 2 | `FORGE-E-DESTINO` |
| Caminho em `/mnt/c` ou UNC | aborta | 2 | `FORGE-E-PATH` |

`politica.falha: continuar` (padrão) executa o que der e reporta parcial; `abortar` para no primeiro
erro inesperado. **QC reprovado nunca é "continuar"**: é `rejected` e segue.

## 9. Publicação e persistência

```
$FORGE3D_HOME  (~/.local/state/forge3d)   # nada disto mora no repositório do jogo (D24)
├── cache/<chave>/            # artefatos D1/D2 já aprovados, endereçados por conteúdo
│   ├── final/                # .glb, texturas, colisão
│   └── entrada.json          # resultado + QC + provider do cache hit
├── staging/<run_id>/<id>/    # trabalho em andamento (efêmero)
├── locks/gpu.lock
├── runs/<run_id>/
│   ├── plano.json            # o que foi decidido ANTES de executar
│   └── relatorio.json        # resultado por item
├── ledger.jsonl              # append-only, 1 linha por run
├── indice.sqlite             # consultável: id, rota, tags, tris, perfil, licença
└── saida/<lote>/             # sandbox público: sempre gravável, nunca de terceiro

~/.config/forge3d/allowlist.yaml   # únicas raízes externas graváveis (D23)
```

- **Cache** é o que torna o rerun barato. Chave = conteúdo, não `mtime`.
- **Índice** é o que torna o "by demand" real: `forge3d query --tag weapon --max-tris 800`.
- **Ledger** é auditoria: nunca sobrescrito, nunca lido pelo agente em fluxo normal (herdado de D19).
- **Manifesto** viaja **com** o asset, no destino, para o jogo poder validar sem o Forge3D instalado.

## 10. Extensibilidade

| Quero | Como | Não preciso tocar |
|---|---|---|
| nova engine | escrever `profiles/<engine>.yaml` | código |
| novo modelo 3D | implementar `GeometryProvider` + entrada na allowlist de licença | pipeline, export, QC |
| nova estética procedural | implementar provider `blocky`-like | publish, QC |
| novo gate de qualidade | adicionar `G<n>` em `qc/` como função pura | providers, export |
| novo formato de saída | novo `formato` no perfil + escritor | rotas |

Provider é a **única** superfície de extensão que pode trazer dependência pesada (torch, modelo). Tudo
mais é stdlib-leve. Isso mantém `forge3d plan` rodando em CI sem instalar meio GB de wheel.

## 11. Estrutura de diretórios alvo

```
3DCreation/
├── AGENTS.md  README.md  CONSELHOS.md  MAPA.md  DECISOES.md  INVARIANTES.md  CONTINUAR.md
├── docs/            # arquitetura, contratos, rotas, perfis, QC, dependências, riscos, roadmap, gaps
├── schemas/         # spec.v1..v4.schema.json · manifest.v1..v4.schema.json  (fonte de verdade)
├── profiles/        # godot4.yaml · roblox-r15.yaml
├── examples/        # lote_01.yaml (fixture canônica)
├── skills/context-recovery/
│
├── pyproject.toml
├── src/forge3d/
│   ├── cli/            comandos.py (17 subcomandos: inclui migrate, gc, sync, mcp, export-*, upload-*) · main.py
│   ├── paths.py        três raízes: dados, config, estado (D24)
│   ├── config.py       allowlist de destino + guarda de caminho (D23)
│   ├── spec.py         normalização, schema, regras B1–B25
│   ├── profiles.py     carregar perfil + consultas de default
│   ├── plan.py         tarefas, chave de cache, resumo
│   ├── post.py         subprocesso do Blender (canal JSON)
│   ├── qc.py           parser GLB + gates G1–G10
│   ├── publish.py      manifesto, rename atômico (reexporta cache/index/verify)
│   ├── verify.py       portão de CI pós-publicação (G1–G10 + hash + órfãos)
│   ├── sync.py         sincronização ext4 → destino + Forge3DAssets.gd / Assets.lua
│   ├── pipeline.py     orquestração do lote
│   ├── doctor.py       preflight
│   ├── locks.py        lock de GPU
│   ├── canonical.py    JSON canônico, sha256, chave de cache
│   └── providers/      base.py · blocky.py · importer.py · mesh.py · modular.py
├── blender/
│   └── postprocess.py  construir, rig, normalizar, LOD, colisor, exportar, medir
├── tests/
│   ├── test_unidade.py
│   └── invariants/test_invariantes_e2e.py
└── tools/
    ├── check-contexto.sh   tetos de contexto (sem dependência)
    └── check-p0.py         portão dos documentos
```

Nada de código de pipeline em `docs/`, nada de contrato em código. Schema em `schemas/` é a única
fonte; o código importa o schema, não redefine.

## 12. Integração com o projeto de jogo

**Godot (CI de pull request, sem GPU):**
```yaml
- forge3d validate assets/lote.yaml
- forge3d plan     assets/lote.yaml --json > plano.json
- forge3d verify   assets/importados --json    # só o que já está versionado
```

**Godot (máquina do dev, sob demanda):**
```bash
forge3d run assets/lote.yaml --json && godot --headless --import
```

**Makefile do jogo:**
```make
assets: assets/lote.yaml
	forge3d run $< --json || (echo "forja falhou"; exit 1)
```

**Projeto que só quer o asset já pronto:** consome `<asset_id>.manifest.json` no destino — não precisa
do Forge3D instalado (e nunca precisa do código dele).

## 13. Não-objetivos (v0)

Editor visual · hospedagem/multi-tenant · fine-tuning de modelo · animação por IA · geração de
gameplay/level design · substituir o artista em asset de herói · ser biblioteca importável.

## 14. Riscos que moldam o desenho

Resumo; números e fontes em [`riscos-e-licencas.md`](riscos-e-licencas.md).

1. **Licença de modelo** é restrição de arquitetura (allowlist em `providers/`), não nota de rodapé.
2. **VRAM** é restrição de escalonamento (§7), não detalhe de performance.
3. **Blender 4.2** é pinado: a API do `bpy` e o exportador glTF mudam entre versões (I9).
4. **WSL** é o ambiente: nada sobre `/mnt/c` (I12).
5. **Diffusion não é determinística**: só D1 entra em CI (§6).
