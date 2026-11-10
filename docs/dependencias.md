# Dependências

> Medido nesta máquina em 10/11/2026 (`DECISOES.md` §1). Versão sem pin é dívida: tudo que entra na
> chave de cache (D6) precisa de versão declarada.

## 1. Ambiente assumido

| Item | Valor medido | Observação |
|---|---|---|
| SO | WSL2, Ubuntu (kernel 6.18) | projeto roda em ext4 sob `/home` (I12) |
| GPU | RTX 3060 Laptop **6.144 MiB**, driver 617.42 | `/dev/dxg` presente, CUDA via WSL |
| RAM | 15 GB | dois modelos grandes não coexistem |
| Disco livre | 868 GB | orçamento de cache: 20 GB |
| Blender | **4.2.0** em `/home/eudespatricio/.local/bin/blender` | Python **3.11** embutido |
| Python do sistema | 3.14.4 | **não usar** para o pacote |
| Python via `uv` | 3.12.14 instalado | usar este |
| Docker | disponível | opcional, não é caminho do v0 |

## 2. Runtime — Python

| Dependência | Versão | Por quê | Se faltar |
|---|---|---|---|
| Python | **3.12.14** (venv do repo) | roda o pacote; 3.14 não tem wheel de ML | nada funciona |
| `jsonschema` | `>=4.21,<5` | valida a spec e o **manifesto de terceiros** | contrato deixa de ser verificável |
| `PyYAML` | `>=6.0,<7` | lote, perfis e allowlist em YAML | só JSON |
| `Pillow` | `>=10,<12` | atlas de pixel art da rota `blocky` | rota blocky não existe |
| `pytest` | `>=8` (dev) | oráculo dos invariantes | sem CI |

**Sem `pydantic`, `typer`, `rich`, `numpy`, `orjson`** (D26): o schema é a fonte de verdade, então a
validação é `jsonschema`; `argparse` e `json` são stdlib. Instalar em segundos é o que permite
`forge3d plan` rodar em CI sem GPU.

## 3. Runtime — Blender (subprocesso)

| Item | Requisito | Verificação |
|---|---|---|
| Blender | `4.2.x` exato (major.minor) | `blender --version` no `doctor` |
| Exportador glTF | habilitado (padrão) | `hasattr(bpy.ops.export_scene, 'gltf')` |
| Draco | opcional | log do exportador |
| Python do Blender | 3.11 — **não instalar pacote nele** | I9 |

Scripts em `blender/` usam **somente** `bpy`, `bmesh`, `mathutils` e stdlib. Nenhum `pip install`
dentro do Blender: isso contamina o DCC e quebra na próxima atualização.

## 4. GPU (opcional — só P3)

| Dependência | Versão | Licença | Nota |
|---|---|---|---|
| `torch` CUDA | `2.x` cu12x | BSD-3 | wheel grande (~2,5 GB) |
| SF3D | pinado por commit | Stability Community License | exige **registro** + `NOTICE` |
| TripoSR | pinado por commit | **MIT** | sem PBR, topologia pior |
| `sd.cpp` (binário) | pinado por release | MIT | gera concept sem Python |

**Não instalar por padrão:** ComfyUI (stack completa para uma função coberta), Hunyuan3D-2.1 e
TRELLIS.2 (VRAM/licença — D18), Node/pnpm (não há etapa JS no v0).

### SF3D (gated) — o que é preciso para rodar

| Passo | Onde | Observação |
|---|---|---|
| conta com **e-mail verificado** | `huggingface.co/settings/account` | sem verificação o repo gated dá 403 |
| **aceitar os termos** do modelo | `huggingface.co/stabilityai/stable-fast-3d` → *Agree and access repository* | `gated: auto`: libera na hora após o aceite |
| token **Read** | `huggingface.co/settings/tokens` | `huggingface-cli login --token hf_...`; fica em `~/.cache/huggingface/token` (fora do repo) |
| conferir acesso | `curl -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $(cat ~/.cache/huggingface/token)" https://huggingface.co/stabilityai/stable-fast-3d/resolve/main/config.yaml` | **403** = sem aceite · **200** = liberado |

Instalação (verificada em 10/11/2026): venv isolada `~/.venvs/sf3d` (o SF3D pina `transformers==4.42.3`
e `huggingface-hub==0.23.4`, que **conflitam** com o TripoSR), `cmake<4` via PyPI (sem sudo),
`scipy==1.13.1` (o 1.18 exige numpy 2 e quebra `trimesh`/`rembg` com numpy 1.26), pacotes locais com
`--no-build-isolation` e `USE_CUDA=0` (sem `nvcc` o `texture_baker` compila em CPU).
`gpytoolbox` só serve ao remesh: import tornado opcional no vendor, usar `--remesh_option none`.

## 5. Sistema

| Ferramenta | Estado | Necessidade |
|---|---|---|
| `git` | 2.53.0 | versionamento, `pipeline_version` |
| `uv` | presente | interpretador e venv |
| `imagemagick` (`magick`) | presente | inspeção de textura, debug |
| `rg`, `jq`, `ffmpeg`, `unzip`, `git-lfs` | **ausentes** | opcionais: `rg` para busca, `jq` para debug, `git-lfs` se Q7 for LFS |

Instalação opcional: `sudo apt-get install -y ripgrep jq unzip` (o usuário está no grupo `sudo`).

## 6. Montagem do ambiente (P1)

```bash
cd /home/eudespatricio/3DCreation
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
forge3d doctor
```

`doctor` é a fonte de verdade do ambiente: ele falha com mensagem explícita, não com traceback. Ele
verifica, no mínimo: Blender presente e `4.2.x`; exportador glTF disponível; VRAM livre agora;
`perfil` carregável; schema presente e válido; espaço em disco para cache; destino sob allowlist;
modelos declarados na allowlist de licença.

## 7. Orçamento de disco

| Uso | Tamanho |
|---|---|
| código + venv | ~300 MB |
| cache de assets | ~5 MB por asset `blocky`, ~50 MB por asset `mesh` |
| stack GPU (opcional) | ~12 GB (torch + pesos) |
| **reserva recomendada** | 20 GB para cache com folga |

Política: cache cresce por conteúdo; `forge3d gc --manter-dias 30` (P6) remove o que não é referenciado
por manifesto publicado.
