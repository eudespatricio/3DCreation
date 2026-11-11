# AGENTS — instruções para qualquer agente neste repo

Leia nesta ordem, antes de qualquer ação:

1. `CONTINUAR.md` — **se esta é uma sessão nova**: onde paramos, decisões e próximo passo.
2. `MAPA.md` — onde cada responsabilidade mora e as armadilhas.
3. `INVARIANTES.md` — o que quebra o projeto se for violado.
4. `DECISOES.md` §2 (decisões) e §4 (abertas) — o resto do arquivo é ledger, não leia inteiro.

## Regras duras

- **Documento e verificação antes de código.** P1–P5 já estão implementadas: mudar código de
  pipeline, instalar modelo ou baixar peso exige autorização explícita do operador (D1).
- **Não invente número.** Fato medido, medido por terceiro e estimativa são rótulos diferentes e
  vivem separados (`DECISOES.md` §1). Se não mediu, escreva `[estimado]`.
- **Contrato é lei.** `schemas/spec.v1.schema.json` · `schemas/spec.v2.schema.json` ·
  `schemas/spec.v3.schema.json` e `schemas/manifest.v1.schema.json` · `schemas/manifest.v2.schema.json`
  · `schemas/manifest.v3.schema.json` são a fronteira com os projetos de jogo (correntes: `spec@3` e
  `manifest@3`; `@1`/`@2` continuam válidos na leitura). Mudou o schema? Suba a versão e registre em
  `DECISOES.md`. Não existe alteração silenciosa de contrato.
- **Nada escreve direto na pasta do jogo.** Só `publish`, atômico, via staging (I3).
- **QC reprovado não publica.** Não existe flag para "publicar mesmo assim" (I5).
- **O sistema tem que funcionar sem GPU.** Se a sua mudança torna a GPU obrigatória para o caminho
  `blocky`/`import`, está errada.
- **Blender é 4.2.x, pinado, invocado por `subprocess`.** Nunca `pip install` no Python do Blender
  (3.11 embutido). Dados entram e saem por arquivo JSON, nunca por stdout (I9).
- **Dados ficam em ext4.** Nenhum pipeline, spec ou destino aponta para `/mnt/c`; a sessão no
  Windows vê o repo por UNC e isso é o normal, não defeito (ver §Ambiente, I12).
- **Não use nome de franquia em asset, tag, perfil ou arquivo.** `blocky_voxel`, nunca
  `minecraft_*`. É passivo jurídico, não preferência de estilo (I14).
- **Teto de contexto:** MAPA 60 linhas, AGENTS 80, INVARIANTES 200, CONTINUAR 200, CONSELHOS 140.
  `DECISOES.md` é ledger append-only e não é lido inteiro.

## Ambiente: o repo mora no WSL — e isto é o normal

O código vive em ext4, em `/home/eudespatricio/3DCreation`; a sessão que roda no Windows o vê
montado como `\\wsl.localhost\Ubuntu\...`. **Não é defeito, não é alerta e não se conserta:** mover
o repo para `/mnt/c` é a violação do I12. Custos medidos em 11/11/2026 (para não redescobrir por
sessão):

| Operação vista do Windows, via UNC | Resultado |
|---|---|
| criar arquivo **novo** | funciona |
| **modificar** arquivo existente (`edit`, sobrescrever com `write`) | **falha** `GetFileSecurityW EIO` |
| apagar e renomear (`mv` por bash) | funcionam |
| 200 arquivos pequenos · 50 MB | **906 ms** vs 12 ms (~75×) · **3,38 s** vs 0,03 s |

Receita única: **ler** com as ferramentas de leitura; **alterar existente** gravando `<arquivo>.new`
e trocando por `wsl.exe -e bash -lc 'cd /home/eudespatricio/3DCreation && mv X.new X'`; **rodar**
sempre por `wsl.exe ... && .venv/bin/...`, nunca com Python ou `git` do Windows contra a UNC.

## Comandos

```bash
# portão dos documentos e dos contratos (P0)
uv run --no-project --python 3.12 --with pyyaml --with jsonschema python tools/check-p0.py

forge3d doctor                          # ambiente: blender, GPU, VRAM, modelos, disco
forge3d validate examples/lote_01.yaml  # schema + regras de negócio
forge3d plan     examples/lote_01.yaml  # plano sem GPU, sem escrita
forge3d run      examples/lote_01.yaml  # executa + QC + publish
forge3d verify   <destino>              # portão de CI
bash tools/check-contexto.sh            # tetos de MAPA/AGENTS/INVARIANTES/CONTINUAR/CONSELHOS
python -m pytest                        # suíte completa (138 verdes + 1 GPU skip)
bash tools/ci.sh                        # o que o GitHub roda: testes + contexto + P0
```

## Fonte de verdade

Decisão humana > código + teste > documento por data. Documento mais velho que o código mente.
Teste verde = **consistência**, não correção (herdado de D25 do projeto `conselho`).
