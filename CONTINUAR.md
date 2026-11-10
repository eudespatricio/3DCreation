# CONTINUAR — handoff de sessão

**Data:** 10/11/2026 · **P0 fechada:** escopo, arquitetura e contratos escritos.
**Zero código de pipeline. Zero dependência instalada. Zero modelo baixado.**
Este arquivo é autossuficiente: a conversa pode ser fechada.

---

## O que é este projeto

**Forge3D** é um utilitário de linha de comando que transforma um **lote declarativo** (YAML/JSON) em
assets 3D de jogo verificáveis — `.glb` com escala, pivô, LOD, colisão, rig e manifesto — e publica de
forma atômica na pasta do projeto consumidor.

Nasceu de um desenho do operador (orquestrador → rotas A/B/C → Blender headless → GLB no `/assets`) que
foi auditado nesta sessão. O veredito da auditoria: o desenho está certo no **o quê** e incompleto no
**como plugar** — ver [`docs/avaliacao.md`](docs/avaliacao.md).

## Onde paramos

- P0 entregue: 7 documentos residentes, 10 documentos de engenharia, 2 schemas JSON, 2 perfis de
  export, 2 lotes de exemplo, skill `context-recovery` adaptada.
- O diretório `/home/eudespatricio/3DCreation` estava **vazio** no início desta sessão.
- Nada de código foi escrito (D1: P0 é só documento, por decisão do operador).

## Decisões que o operador tomou nesta sessão

| Pergunta | Resposta |
|---|---|
| Contrato de consumo | **CLI + arquivo de lote** (sem HTTP, sem MCP, sem import de biblioteca) |
| Alvos de export | **Godot 4** e **Roblox R15/blocky** |
| Escopo desta sessão | **só arquitetura e documentos de processo** |
| Stack GPU | **não instalar agora** — provider plugável, `doctor` diz o que falta |

## O achado que define a próxima fase

Das 14 lacunas levantadas, **11 não são de IA** — são contrato, estado, verificação, recurso e licença.
Geração é ~20 % do problema. A esteira só é chamável por outro pipe quando tem:

1. `plan` (custo e cache sem gastar GPU);
2. cache por conteúdo (rerun = zero trabalho);
3. QC como portão (asset ruim não entra calado);
4. `publish` atômico + manifesto (rastreabilidade e licença);
5. governança de VRAM (6 GB não comportam dois modelos).

## Decidido — não reabrir sem evidência nova

`D3` CLI-only · `D5` plan/run/verify/publish · `D7` D1/D2/D3 separados · `D9` QC sem bypass ·
`D11` GPU opcional e serializada · `D14` animação fora da v0 · `D18` licença é gate ·
`D19` naming neutro (`blocky_voxel`) · `D20` spec versionada.
Invariantes `I1`–`I14` em [`INVARIANTES.md`](INVARIANTES.md) (verificáveis: I12 e I14 já hoje).

## Aberto — fecha em P0.5

| # | Pergunta | Bloqueia |
|---|---|---|
| **Q2** | allowlist de destino: arquivo de config × flag por run | I13 |
| **Q6** | `.forge/` (cache/locks) por projeto consumidor × central em `~/.cache/forge3d` | D6 |
| Q1 | nome definitivo (`forge3d` é provisório) | publicação do pacote |
| Q3 | escala/rig Roblox (0,28 m por stud) | perfil Roblox em P2 |
| Q5 | SF3D × TripoSR (licença × qualidade) | rota `mesh` em P3 |
| Q7 | assets no git do jogo: normal × LFS | primeiro asset real |

## Próximo passo

**P0.5 (~meio dia, sem GPU):** decidir Q2 e Q6; criar `tools/check-contexto.sh`; portar `scan_repo.py`
para o lens Python/Blender; fechar GAP-001 a GAP-004.

**Depois P1 — rota `blocky` + `import` de ponta a ponta.** É onde o desenho é provado sem GPU.

**Portão de saída de P1 (todos, falsificáveis):**

- `forge3d run examples/lote_01.yaml` duas vezes ⇒ **hashes idênticos**;
- segunda execução ⇒ `trabalho_executado: 0`;
- os 3 assets do exemplo entram no GameZero **sem ajuste manual** de escala, pivô ou material;
- `verify` pega um `.glb` alterado à mão ⇒ `exit 3`;
- spec com erro ⇒ `exit 2` sem instanciar provider.

## Fatos medidos (não repita a medição)

| Fato | Valor |
|---|---|
| Blender headless | 4.2.0 em `~/.local/bin/blender`; export GLB OK; Draco disponível |
| Python do Blender | 3.11 embutido (não instalar pacote nele) |
| Python do sistema | 3.14.4 — **inadequado** para `torch` |
| Python via `uv` | 3.10.22 · 3.11.16 · **3.12.14** já instalados |
| GPU | RTX 3060 Laptop, **6.144 MiB**, driver 617.42, `/dev/dxg` presente |
| RAM / disco | 15 GB / 868 GB livres |
| Ausentes | `rg`, `jq`, `ffmpeg`, `unzip`, `git-lfs` |
| Presentes | `git` 2.53, `uv`, `docker`, ImageMagick, rede (pypi/github 200) |
| Ollama | `llama3.1`, `qwen2.5-coder:7b`; **contexto efetivo 4.096** |

## Arquivos

| Arquivo | O que é |
|---|---|
| `README.md` | o projeto, o contrato CLI, as rotas |
| `AGENTS.md` | ordem de leitura + regras duras para agente |
| `MAPA.md` | onde cada responsabilidade mora + armadilhas |
| `CONSELHOS.md` | quando convocar conselho; **registro do Conselho #1** (esta sessão) |
| `DECISOES.md` | §1 fatos medidos · §2 D1–D22 · §3 rejeitados · §4 Q1–Q7 · §5 herdado |
| `INVARIANTES.md` | I1–I14 com comando de verificação |
| `docs/avaliacao.md` | **auditoria do desenho original**: 14 lacunas, 6 contradições, 5 excessos |
| `docs/arquitetura.md` | fluxo, camadas, fronteiras, determinismo, falha, publicação |
| `docs/contratos.md` | `spec@1`, `manifest@1`, exit codes, `FORGE-E-*` |
| `docs/rotas-e-providers.md` | `blocky` · `import` · `mesh` · `modular` + interface de provider |
| `docs/perfis-export.md` | `godot4` e `roblox-r15`: eixos, escala, pivô, rig, colisão |
| `docs/qc-e-verificacao.md` | gates G1–G9 e o `verify` de CI |
| `docs/dependencias.md` | versões pinadas, o que instalar, o que **não** instalar |
| `docs/riscos-e-licencas.md` | tabela de modelos 6 GB com licença e rótulo de evidência |
| `docs/roadmap.md` | P0–P6 com portão de saída por fase |
| `docs/gaps.md` | GAP-001..014 com condição de fechamento |
| `schemas/spec.v1.schema.json` | contrato de entrada (fonte de verdade) |
| `schemas/manifest.v1.schema.json` | contrato de saída (fonte de verdade) |
| `profiles/godot4.yaml` · `profiles/roblox-r15.yaml` | perfis de export |
| `examples/lote_01.yaml` | fixture canônica (3 assets, rota `blocky`) |
| `examples/lote_02_rotas.yaml` | referência de `mesh` e `modular` |
| `examples/manifest.exemplo.json` | manifesto completo ilustrativo (valida contra `manifest@1`) |
| `tools/check-p0.py` | portão do P0 — roda e sai `0` |
| `skills/context-recovery/` | protocolo + templates |

## Regras invioláveis (top 6)

1. **P0 é só documento.** Código só em P1, com autorização explícita.
2. **Nenhum número sem rótulo** `[medido]`/`[estimado]`/`[verificar]` — `DECISOES.md` §1 é a única
   fonte de fato medido.
3. **Contrato é lei.** Mudou `schemas/`? Suba a versão e registre. Não existe mudança silenciosa.
4. **Nada escreve no destino fora de `publish`** (atômico). QC reprovado não publica.
5. **Nunca prometer D1 para diffusion** — só `blocky`/`import`/`modular` são byte-idênticos.
6. **Nada roda sobre `/mnt/c` ou UNC.**

## Como verificar em 1 minuto

```bash
uv run --no-project --python 3.12 --with pyyaml --with jsonschema python tools/check-p0.py
```

Sai `0` = documentos coerentes, schemas válidos, tetos respeitados. Sai `1` = o que falhou está
listado, com arquivo e linha.

## Como retomar

Cole na nova sessão:

> Leia `3DCreation/CONTINUAR.md`, `3DCreation/MAPA.md` e `3DCreation/DECISOES.md` §2 e §4.
> A P0 está fechada (só documentos, nenhum código). O operador escolheu: contrato CLI + lote,
> alvos Godot 4 e Roblox R15, GPU só depois. Não escreva código de pipeline ainda.
> Comece fechando Q2 (allowlist de destino) e Q6 (local do `.forge/`), depois faça o P0.5:
> `tools/check-contexto.sh` + portar `scan_repo.py`. Sem só depois autorize P1.
