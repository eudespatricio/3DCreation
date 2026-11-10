# CONTINUAR — handoff de sessão

**Data:** 10/11/2026 · **P0 e P1 fechadas.** A esteira funciona de ponta a ponta nas rotas `blocky` e
`import`, sem GPU, com QC como portão. 26 testes verdes.
Este arquivo é autossuficiente: a conversa pode ser fechada.

---

## O que é este projeto

**Forge3D** é um utilitário de linha de comando que transforma um **lote declarativo** (YAML/JSON) em
assets 3D de jogo verificáveis — `.glb` com escala, pivô, LOD, colisão, rig e manifesto — e publica de
forma atômica num destino autorizado.

Requisito duro do operador (10/11/2026): **o utilitário é independente de projeto**. Não lê config do
diretório onde roda, não escreve nada fora do próprio estado, não importa código de jogo. A fronteira
é CLI + arquivo de lote (D25).

## Onde paramos

- **P0** — arquitetura, contratos (`spec@1`, `manifest@1`), 2 perfis de export, docs de processo.
- **P0.5** — Q2/Q6 fechadas (D23 allowlist, D24 estado central), `tools/check-contexto.sh` no ar.
- **P1** — pipeline completo das rotas `blocky` e `import`: validar → planejar → gerar → pós-processar
  (Blender 4.2) → QC G1–G9 → cache → publicar atômico → manifesto → índice SQLite → ledger.
- **Não feito:** rotas `mesh` (P3) e `modular` (P4), perfil Roblox validado no Studio (P2), animação.

## Números medidos nesta máquina (10/11/2026)

| Medida | Valor |
|---|---|
| `run` com 3 itens, cache frio | **2.082 ms** (exit 0, 3 publicados) |
| `run` com cache quente | **476 ms** — `cache_hits: 3`, `trabalho_executado: 0` |
| `plan` (3 itens) | **141 ms** |
| `verify` (3 manifestos, 12 arquivos) | **127 ms** |
| Determinismo D1 | **sha256 idênticos** nos 12 artefatos entre dois runs com cache limpo |
| Asset `mob.skeleton.guard` | 72 tris, bbox 0,814 × 1,85 × 0,333 m, **23 ossos**, 1 colisor convexo, 5 arquivos, 38.619 B |
| Suite | **26 testes** (17 unidade + 9 ponta a ponta), ~75 s |

## O que está decidido (não reabrir sem evidência nova)

`D3` CLI-only · `D5` plan/run/verify/publish · `D7` D1/D2/D3 · `D9` QC sem bypass · `D11` GPU
serializada · `D14` animação fora da v0 · `D18` licença é gate · `D19` naming neutro ·
**`D23` allowlist de destino** · **`D24` estado central** · **`D25` isolamento por padrão** ·
**`D26` núcleo leve (3 dependências)**.

Invariantes `I1`–`I14`: 9 automatizados, ver [`INVARIANTES.md`](INVARIANTES.md) § Estado da automação.

## Aberto (não bloqueia P2)

| # | Pergunta | Fecha em |
|---|---|---|
| Q1 | nome definitivo do produto (`forge3d` é provisório) | antes de publicar o pacote |
| Q3 | escala/rig do Roblox (0,28 m por stud; PBR por `SurfaceAppearance`) | P2, com teste no Studio |
| Q5 | SF3D × TripoSR (licença × qualidade) | P3, com A/B de 10 assets |
| Q7 | assets no git do jogo: normal × LFS | antes do primeiro asset real |

## Próximo passo: P2 — perfil Roblox

1. Rodar `forge3d run` com `perfil: roblox-r15` e o mesmo lote.
2. Importar no Studio: `Humanoid`, pivô por junta, escala em studs, textura.
3. Fechar U1–U4 em [`docs/perfis-export.md`](docs/perfis-export.md) e a Q3.
4. Se o importador divergir do previsto, **corrige-se o perfil**, não o código (D4).

**Portão de saída de P2:** modelo importado no Studio com `Humanoid`, membros girando no pivô certo,
escala correta em studs, e nenhum `[verificar]` pendente nesse perfil.

## Comandos

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate

forge3d doctor                     # ambiente: blender, perfis, schemas, VRAM, disco
forge3d validate examples/lote_01.yaml
forge3d plan     examples/lote_01.yaml      # custo e cache, sem GPU
forge3d run      examples/lote_01.yaml      # gera, verifica, publica
forge3d verify   ~/.local/state/forge3d/saida/lote_01
forge3d query    --max-tris 100 --json
forge3d allowlist list             # destinos autorizados

python -m pytest -q                # 26 testes
bash tools/check-contexto.sh       # tetos de contexto
```

## Arquivos

| Arquivo | O que é |
|---|---|
| `README.md` | o produto, o contrato CLI, isolamento |
| `AGENTS.md` | ordem de leitura + regras duras |
| `MAPA.md` | onde cada responsabilidade mora + 9 armadilhas |
| `CONSELHOS.md` | quando convocar conselho + registro do Conselho #1 |
| `DECISOES.md` | §1 fatos medidos · §2 D1–D26 · §3 rejeitados · §4 Q em aberto |
| `INVARIANTES.md` | I1–I14 + estado da automação |
| `docs/avaliacao.md` | auditoria do desenho original (14 lacunas, 6 contradições) |
| `docs/arquitetura.md` | fluxo, camadas, determinismo, falha, publicação, isolamento |
| `docs/contratos.md` | `spec@1`, `manifest@1`, exit codes, `FORGE-E-*` |
| `docs/rotas-e-providers.md` | as 4 rotas + interface de provider |
| `docs/perfis-export.md` | `godot4` e `roblox-r15` |
| `docs/qc-e-verificacao.md` | gates G1–G9 |
| `docs/dependencias.md` | 3 dependências de runtime, versões pinadas |
| `docs/riscos-e-licencas.md` | modelos em 6 GB com licença e rótulo de evidência |
| `docs/roadmap.md` | P0–P6 com portão por fase |
| `docs/gaps.md` | GAP-001..018 com condição de fechamento |
| `src/forge3d/` | 13 módulos (ver `MAPA.md`) |
| `blender/postprocess.py` | script `bpy`: construir, rig, normalizar, LOD, colisor, exportar, medir |
| `tests/` | unidade + invariantes de ponta a ponta |
| `tools/check-contexto.sh` · `tools/check-p0.py` | portões (contexto e documentos) |

## Regras invioláveis (top 6)

1. **Nada roda sobre `/mnt/c` ou UNC**; estado é sempre ext4 sob `/home` (I12).
2. **Nenhuma escrita fora do destino autorizado** (I3, I13). Autorizar é `forge3d allowlist add`.
3. **QC reprovado não publica** e não existe bypass (I5).
4. **Diffusion nunca é D1.** Só `blocky`/`import`/`modular` prometem byte-idêntico (D7).
5. **Mudou a saída de um provider? Suba `VERSAO`** — a versão entra na chave de cache (D6).
6. **Blender é 4.2.x, subprocesso, canal JSON**; nunca `pip install` no Python dele (I9).

## Como retomar

Cole na nova sessão:

> Leia `3DCreation/CONTINUAR.md`, `3DCreation/MAPA.md` e `3DCreation/DECISOES.md` §2 e §4.
> P0 e P1 estão fechadas: rotas `blocky` e `import` funcionam sem GPU, 26 testes verdes, determinismo
> D1 comprovado por hash. O operador exige isolamento total do utilitário (D25). Não reabra D3–D26.
> Próximo passo: **P2 — perfil Roblox**, fechando U1–U4 e a Q3 com teste real no Studio.
