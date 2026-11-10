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
| SF3D | **não usar** | Stability Community License | encerrado em 6 GB por **D27**; não reinstalar |
| TripoSR | pinado por commit | **MIT** | **i23d da P3**; roda na venv `venv-i23d` |
| `sd.cpp` (binário) | pinado por release | MIT | gera concept sem Python |

**Não instalar por padrão:** ComfyUI (stack completa para uma função coberta), Hunyuan3D-2.1 e
TRELLIS.2 (VRAM/licença — D18), Node/pnpm (não há etapa JS no v0).

### i23d — venv única (P3)

| Item | Valor medido |
|---|---|
| venv | `~/.cache/forge3d/venv-i23d` · Python 3.12.14 · torch **2.4.1+cu121** · **5,6 GB** |
| seleção | `FORGE3D_VENV_I23D` (default acima) |
| vendor | `~/.cache/forge3d/vendor/TripoSR` (MIT) |
| pesos | `~/.cache/huggingface/hub/models--stabilityai--TripoSR` |
| shim | `torchmcubes.py` (PyMCubes) dentro da venv; fonte em `tools/torchmcubes_shim.py` |
| opções | `FORGE3D_MC_RESOLUTION` (256) · `FORGE3D_TEX_PX` (512) · `FORGE3D_I23D_REMOVER_FUNDO=1` |
| backup | `~/.venvs/triposr` (torch 2.5.1, 5,8 GB) foi **removida**; só existe uma venv de i23d |

O núcleo **não importa `torch`**: `doctor`/`preflight` rodam um subprocesso `python -c` na venv e o
provider chama `tools/i23d_infer.py` com canal JSON (I9). Sem GPU, o item sai `bloqueado` com razão
nomeada, nunca `falhou` (D11).

### concept — SD 1.5 (P3.5)

| Item | Valor medido |
|---|---|
| venv | `~/.venvs/concept` (cópia da i23d + diffusers 0.31.0 / transformers 4.44.2 / accelerate 1.2.1; torch 2.4.1+cu121; **5,6 GB**) |
| seleção | `FORGE3D_VENV_CONCEPT` |
| setup | `bash tools/setup_concept_venv.sh` |
| modelo | `stable-diffusion-v1-5/stable-diffusion-v1-5` fp16 (**~2,0 GB**, revision `451f4fe…`) |
| licença | CreativeML **OpenRAIL-M**; uso comercial com as restrições da licença |
| opções | `FORGE3D_MODELO_CONCEPT` · `FORGE3D_CONCEPT_PASSOS` (25) · `_LARGURA`/`_ALTURA` (512) · `_GUIDANCE` (7.5) · `_SUFIXO` · `_NEGATIVO` |
| medido | 512²/25 steps: **5,5 s** de geração, **2,0 s** de carga (cache), VRAM pico **2.675 MiB**, PNG 264.929 B |
| fallback | `FORGE3D_DEVICE=cpu` (lento: 71,4 s no teste 384²/8, mc128; não é o caminho de aceitação) |

O venv é **cópia** da i23d de propósito: o TripoSR prende `transformers==4.35` e o diffusers 0.31
exige `>=4.44`. Não é uma segunda venv de i23d (GAP-031); é o segundo modelo. O núcleo chama
`tools/concept_infer.py` por subprocesso com JSON (I9). A primeira geração baixa os pesos; o teste
`FORGE3D_CONCEPT_E2E=1 pytest tests/test_concept_gpu.py -q` cobre isso.

### SF3D — encerrado por D27 (registro histórico, não reinstalar)

> **Não reinstalar.** SF3D leva ~8 min/imagem em 6 GB e o bake exige CUDA toolkit (D27).
> O registro abaixo fica só como histórico do que foi tentado.

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
forge3d run examples/lote_03_kit.yaml            # P3-D, sem GPU
FORGE3D_I23D_REMOVER_FUNDO=1 forge3d run examples/lote_04_mesh.yaml   # P3-B, GPU
bash tools/setup_concept_venv.sh                                  # uma vez, P3.5
FORGE3D_CONCEPT_E2E=1 .venv/bin/python -m pytest tests/test_concept_gpu.py -q  # baixa/testa SD1.5
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
