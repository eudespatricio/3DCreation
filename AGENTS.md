# AGENTS — instruções para qualquer agente neste repo

Leia nesta ordem, antes de qualquer ação:

1. `CONTINUAR.md` — **se esta é uma sessão nova**: onde paramos, decisões e próximo passo.
2. `MAPA.md` — onde cada responsabilidade mora e as armadilhas.
3. `INVARIANTES.md` — o que quebra o projeto se for violado.
4. `DECISOES.md` §2 (decisões) e §4 (abertas) — o resto do arquivo é ledger, não leia inteiro.

## Regras duras

- **A fase P0 é só documento.** Não escreva código de pipeline, não instale PyTorch, não baixe
  modelo. A implementação começa em P1, com autorização explícita do operador (D1).
- **Não invente número.** Fato medido, medido por terceiro e estimativa são rótulos diferentes e
  vivem separados (`DECISOES.md` §1). Se não mediu, escreva `[estimado]`.
- **Contrato é lei.** `schemas/spec.v1.schema.json` e `schemas/manifest.v1.schema.json` são a
  fronteira com os projetos de jogo. Mudou o schema? Suba a versão (`@1` → `@2`) e registre em
  `DECISOES.md`. Não existe alteração silenciosa de contrato.
- **Nada escreve direto na pasta do jogo.** Só `publish`, atômico, via staging (I3).
- **QC reprovado não publica.** Não existe flag para "publicar mesmo assim" (I5).
- **O sistema tem que funcionar sem GPU.** Se a sua mudança torna a GPU obrigatória para o caminho
  `blocky`/`import`, está errada.
- **Blender é 4.2.x, pinado, invocado por `subprocess`.** Nunca `pip install` no Python do Blender
  (3.11 embutido). Dados entram e saem por arquivo JSON, nunca por stdout (I9).
- **Não rode a pipeline sobre `/mnt/c` ou caminho UNC.** I/O lento e `edit` quebra — já medido no
  projeto `conselho` (I12).
- **Não use nome de franquia em asset, tag, perfil ou arquivo.** `blocky_voxel`, nunca
  `minecraft_*`. É passivo jurídico, não preferência de estilo (I14).
- **Teto de contexto:** MAPA 60 linhas, AGENTS 80, INVARIANTES 200, CONTINUAR 200. `DECISOES.md` é
  ledger append-only e não é lido inteiro.

## Comandos (a partir de P1)

```bash
# portão da fase de documentos (hoje é o único comando executável)
uv run --no-project --python 3.12 --with pyyaml --with jsonschema python tools/check-p0.py

forge3d doctor                          # ambiente: blender, GPU, VRAM, modelos, disco
forge3d validate examples/lote_01.yaml  # schema + regras de negócio
forge3d plan     examples/lote_01.yaml  # plano sem GPU, sem escrita
forge3d run      examples/lote_01.yaml  # executa + QC + publish
forge3d verify   <destino>              # portão de CI
bash tools/check-contexto.sh            # tetos de contexto (hoje: awk, sem script)
```

## Fonte de verdade

Decisão humana > código + teste > documento por data. Documento mais velho que o código mente.
Teste verde = **consistência**, não correção (herdado de D25 do projeto `conselho`).
