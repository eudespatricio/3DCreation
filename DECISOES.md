# DECISOES — Forge3D

**Regra deste arquivo:** só entra o que foi **decidido** ou **medido**. Discussão em aberto fica em §4.
Se algo não está aqui nem no `CONTINUAR.md`, não foi decidido — foi só conversa.

> Este arquivo é **ledger append-only** (herdado de D19 do projeto `conselho`): agente não o lê inteiro.
> O estado canônico e enxuto vive em `MAPA.md` + `CONTINUAR.md` + `INVARIANTES.md`.

---

## 1. Fatos medidos (10/11/2026, WSL2 Ubuntu, máquina do operador)

| Fato | Valor | Como foi medido |
|---|---|---|
| Blender headless | **4.2.0** em `~/.local/bin/blender` | `blender --version` |
| Export GLB por script | **funciona**; gerou `smoke.glb` de 1.728 B | `blender -b --python` com `export_scene.gltf` |
| Draco no export | disponível | log do exportador |
| Python embutido do Blender | **3.11** (`4.2/python/lib/python3.11`) | caminho do `libextern_draco.so` |
| Python do sistema | **3.14.4** — inadequado para `torch` | `python3 --version` |
| Interpretadores via `uv` | 3.10.22 · 3.11.16 · **3.12.14** já instalados | `ls ~/.local/share/uv/python` |
| GPU | **RTX 3060 Laptop, 6.144 MiB**, driver 617.42 | `nvidia-smi` |
| Passthrough GPU no WSL | ativo (`/dev/dxg` presente) | `ls -la /dev/dxg` |
| RAM | **15 GB** total | `free -g` |
| Disco livre | **868 GB** em `/` | `df -h /home` |
| Rede | pypi e github acessíveis (HTTP 200) | `curl -o /dev/null -w %{http_code}` |
| Docker no WSL | presente, usuário em grupo `docker` | `docker` + `id` |
| Ferramentas ausentes | `rg`, `jq`, `ffmpeg`, `unzip`, `git-lfs` | `command -v` |
| ImageMagick | presente (`convert`/`magick`) | `command -v` |
| Ollama | `llama3.1`, `qwen2.5-coder:7b`; **contexto efetivo 4.096** | `ollama list`; contexto medido no projeto `conselho` (DECISOES §1) |
| Diretório do projeto | `/home/eudespatricio/3DCreation` — **vazio** antes desta sessão | `ls -la` |
| `edit` em caminho UNC | **falha** com `GetFileSecurityW EIO` (reproduzido nesta sessão) | tentativa de editar `docs/perfis-export.md` pelo harness |
| `run` 3 itens, cache frio | **2.082 ms**, exit 0, 3 publicados | `date +%s%N` em 10/11/2026 |
| `run` 3 itens, cache quente | **476 ms**, `cache_hits: 3`, `trabalho_executado: 0` | idem |
| `plan` 3 itens | **141 ms** | idem |
| `verify` 3 manifestos / 12 arquivos | **127 ms** | idem |
| Determinismo D1 | **sha256 idênticos** nos 12 artefatos entre 2 runs com cache limpo | `tests/invariants/test_i1_determinismo` |
| Asset `mob.skeleton.guard` | 72 tris · bbox 0,814×1,85×0,333 m · 23 ossos · 1 colisor convexo · 5 arquivos · 38.619 B | manifesto publicado |
| Suíte de testes | **26 verdes** (17 unidade + 9 ponta a ponta) em ~75 s | `python -m pytest -q` |
| `mob.android.sentinel.01` (humanoide, blocky) | **300 tris** · 25 caixas · 23 ossos · atlas 128 px · 1 material · 5 arquivos · 73.222 B | manifesto publicado |
| LODs da rota blocky | LOD0 **300** · LOD1 **130** · LOD2 **45** tris | campo `lod` do manifesto |
| `run` android (1 item) | **939 ms** frio · **307 ms** quente (`trabalho_executado: 0`) | `date +%s%N` em 10/11/2026 |
| Import no **Godot 4.3** | `Node3D → Armature → Skeleton3D (23 ossos) → MeshInstance3D`; AABB 0,7584×1,85×0,4255 **idêntico ao manifesto**; `albedo_tex=true`; `filtro=2` (nearest + mipmaps) | `godot --headless --import` + inspeção GDScript |
| Eixos de osso | todos com **X local = +X do mundo**, Y ao longo do osso | `data.bones[].matrix_local` no Blender |
| Rig rígido sob pose | sem fenda nas juntas depois de sobrepor peça ao pivô; manga de junta no osso pai | render `docs/preview/android_pose_final_*` |
| Slot da rota `mesh` | registrado; `doctor` reporta `P3: torch ausente — instale o extra GPU`; lote com rota mesh sai `bloqueado` com exit 5 e **nada escrito no destino** | `forge3d doctor` + `run examples/lote_02_rotas.yaml` em 10/11/2026 |
| Atlas do android | **64×64 px** → 34,6 px/m de densidade de texel (close-up pede ~380 px/m) | `Pillow` sobre o PNG publicado |
| Stack GPU instalada | torch **2.4.1+cu121**, `cuda_available=True` na RTX 3060 Laptop; venv fora do repo em `~/.cache/forge3d/venv-gpu` | `torch.cuda.is_available()` |
| `torchmcubes` sem CUDA toolkit | **inviável compilar** (sem `nvcc`, cmake, ninja) → substituído por `tools/torchmcubes_shim.py` (PyMCubes) | `command -v nvcc` |
| Bug de eixo no shim | PyMCubes devolve eixos invertidos vs `torchmcubes`; sem inverter, altura vira profundidade. Corrigido e provado com elipsoide | `tools/torchmcubes_shim.py` |
| Background removal (concept limpo) | **funciona**: rembg recortou o sujeito e compôs fundo neutro; o input do modelo ficou correto (85 % de enquadramento) | render do `input.png` do TripoSR |
| TripoSR — tempos medidos | model forward **1,8–3,1 s** · extração de malha **3,7–4,5 s** · total **21–36 s** frio (24 s é carregar pesos) | log do `run.py` |
| TripoSR — saída | ~**67.800 tris**, GLB de 1,36 MB, **sem UV e sem material** (só `COLOR_0`) | `qc.analisar` no GLB |
| TripoSR — orientação | altura sai no **eixo Y em 2 de 2 inputs** → normalização obrigatória | `tools/normalize_mesh.py` |
| TripoSR — qualidade (2 inputs) | foto real com capa → casca oca, pernas fundidas; render flat do android → laje extrudada | renders em `.scratch/` |
| TripoSR — T-pose (OpenPose) | **pior**: capa virou chapa de 1 m, corpo virou lâmina; extração de 4,5 s → 23,1 s | `.scratch/tpose_canon_frente.png` |
| TripoSR `--mc-resolution 512` | **336 s** (CPU, via shim) e **topologia igual** a 256 — só suaviza | run em 10/11/2026 |
| Venv do TripoSR já existia | `~/.venvs/triposr` (3.11.16, torch 2.5.1+cu121, CUDA ok, sem pip); instalei uma segunda (2.4.1) | `~/.venvs` + `~/.cache/forge3d/venv-gpu` |
| Canal de delegação (`agentapi`) | **funciona** com `ANTIGRAVITY_LS_ADDRESS=127.0.0.1:43023` + `ANTIGRAVITY_CSRF_TOKEN`; cria conversa e responde via `brain/<id>/.system_generated/steps/` | teste em 10/11/2026 com IDE aberta |
| `new-conversation` é **agêntico** | executa ferramentas (`commandExecutionPolicy: eager`), não é endpoint de completude; no teste rodou comandos de shell | `brain/3836b572-…/steps/13/output.txt` |
| Language server headless sozinho | **crashou** (panic do binário Go); só sobe com a IDE | `-headless=true -http_server_port=50091` |
| SF3D — acesso gated | token salvo e usuário `eudespatricio` OK, mas **HTTP 403** em `config.yaml` e `model.safetensors`; repo é `gated: auto`, `emailVerified` nulo | API `/api/whoami-v2` + `/resolve/main/*` em 10/11/2026 |
| SF3D — instalação | `~/.venvs/sf3d` (3.12, torch 2.4.1+cu121, CUDA ok); `texture_baker` compilado **CPU** (`USE_CUDA=0`, sem nvcc) → `_C` ok | smoke test de import |
| SF3D — conflitos resolvidos | `cmake` 4.x quebra build antigo (usei 3.31 via PyPI, sem sudo); `scipy 1.18` exige numpy 2 e quebrava trimesh/rembg (fixei 1.13.1) | logs do build |
| SF3D — `gpytoolbox` | falhou no build (cmake); é usado **só** no remesh → import tornado opcional no vendor, `--remesh_option none` | patch em `sf3d/models/mesh.py` |
| Estimativa do `plan` | 9,0 s estimados × 2,08 s reais para 3 itens (≈3× conservador) | comparação dos dois relatórios |

**Não medido nesta sessão** (marcar `[estimado]` ou `[verificar]` se usar): tempo por asset em
qualquer modelo 3D, VRAM real por modelo, comportamento do importador Roblox, desempenho do `uv`
resolvendo `torch`.

## 2. Decisões

| # | Decisão | Motivo |
|---|---|---|
| D1 | **P0 é só documento.** Código de pipeline, PyTorch e download de modelo só em P1/P3, com autorização explícita | escolha do operador nesta sessão; evita construir sobre contrato não fechado |
| D2 | Produto e CLI = **`forge3d`**; o diretório permanece `3DCreation` | nome curto para pipe; renomear pasta não paga o custo. Nome definitivo é Q1 |
| D3 | Contrato de integração = **CLI + arquivo de lote + exit codes estáveis**; sem HTTP, sem MCP, sem import de biblioteca na v0 | escolha do operador; é o único contrato que qualquer pipe (bash, make, CI) consome sem adaptador |
| D4 | **Perfis de export** (`godot4`, `roblox-r15`) resolvem engine; a lógica não conhece engine | o mesmo asset serve dois jogos mudando perfil, não código |
| D5 | Fluxo canônico = **`plan → run → verify → publish`**, com etapas separáveis por subcomando | `plan` roda em CI sem GPU; `verify` é portão; separação é o que torna o custo previsível |
| D6 | **Cache por conteúdo**: `sha256(spec canônico + versão da pipeline + versões dos providers + perfil)` | rerun sem mudança tem que custar zero e não tocar arquivo (I11) |
| D7 | **Providers declararam determinismo** (D1 byte-idêntico · D2 semeado · D3 estocástico) e o pipeline trata cada classe diferente | herdado de D25 do `conselho`: teste verde é consistência, não correção. Diffusion nunca é D1 |
| D8 | Rotas nomeadas por **técnica**, não por letra: `blocky`, `import`, `mesh`, `modular` | "Rota B" não diz nada a quem entra no repo; letra vira jargão morto |
| D9 | **QC é portão duro.** Reprovou, não publica; não existe `--force` | asset ruim não entra no jogo "só pra testar" e depois fica |
| D10 | Publicação **atômica** via staging + `rename`; escrita em destino só no passo `publish` | o jogo pode ter watcher com hot-reload; arquivo parcial quebra a importação |
| D11 | **GPU é opcional e serializada**: lock de exclusividade, descarregamento declarado por provider, indisponibilidade **bloqueia** a tarefa (não falha o lote) | 6 GB não comportam dois modelos residentes; `CUDA OOM` intermitente é o pior modo de falha |
| D12 | **Manifesto + índice SQLite + ledger append-only** | origem, licença e versão precisam sobreviver ao asset; `query` por demanda exige índice |
| D13 | **LLM só como front-end opcional `forge3d draft`**, nunca no caminho crítico | lote já é declarativo; LLM no caminho crítico adiciona não-determinismo e 4k de contexto útil |
| D14 | **Animação e retarget fora da v0.** Rig = transferência de template determinística (bpy) | UniRig/RigNet em 6 GB é caro e instável; `animacoes_base` do lote fica reservado, sem promessa |
| D15 | **Blender 4.2.x pinado**, invocado por `subprocess`, entrada/saída por arquivo JSON | API do `bpy` e parâmetros do exportador mudam entre versões; stdout do Blender é ruidoso |
| D16 | **Python 3.12 via `uv`** para o pacote; 3.14 do sistema não é usado | wheels de ML não existem para 3.14; 3.12 já é o padrão do ecossistema (`ia_trader`, `dark_studio`) |
| D17 | **Preflight obrigatório** (`forge3d doctor`) com modelos de falha nomeados | 80% do tempo perdido em pipeline é ambiente, não algoritmo |
| D18 | **Licença é gate**: allowlist de modelos com uso comercial permitido; `NOTICE` por asset no manifesto | Hunyuan3D-2.x exclui UE/UK/Coreia; Pixal3D é não-comercial; asset sem licença é passivo |
| D19 | **Naming neutro**: `blocky_voxel`, nunca `minecraft_*`; valores antigos aceitos como alias legado com aviso | estética é livre, marca registrada não |
| D20 | Spec é **versionada** (`forge3d/spec@1`) e validada por JSON Schema antes de qualquer provider | contrato silencioso quebra os pipes dos jogos sem aviso |
| D21 | Erros têm **código estável** `FORGE-E-*` além do exit code | pipe precisa ramificar por causa, não por parse de mensagem |
| D22 | **ComfyUI não é dependência da v0**; quando a Rota B entrar, a interface é HTTP/CLI atrás de provider | stack mais pesada do ambiente para uma função que `sd.cpp`/`sf3d` cobrem |
| D23 | **Allowlist de destino** em `~/.config/forge3d/allowlist.yaml`; sandbox do próprio Forge3D sempre liberado; **sem flag de bypass**; autorizar é `forge3d allowlist add` | deny by default — destino errado publica asset no projeto errado e não há desfazer barato (fecha Q2) |
| D24 | **Estado centralizado** em `$FORGE3D_HOME` (`~/.local/state/forge3d`): cache, runs, staging, locks, índice, ledger, saída. Nenhum `.forge/` no diretório de execução | rodar de dentro de um jogo não cria pasta nem arquivo no jogo (fecha Q6) |
| D25 | **Isolamento por padrão**: sem leitura de config a partir do cwd, sem escrita fora do estado próprio ou de destino autorizado, sem import de código de projeto de jogo | exigência explícita do operador (10/11/2026): o utilitário tem que funcionar independente de projeto |
| D26 | **Núcleo leve**: `jsonschema` + `PyYAML` + `Pillow` e `argparse`; sem pydantic/typer/rich/orjson/numpy | o schema é a fonte de verdade; instalar em segundos é o que deixa `plan` rodar no CI |

## 3. Rejeitados (e por quê)

- **ComfyUI + TripoSR + Blender acoplados num script só** — três falhas diferentes viram uma mensagem
  só; impossível degradar, impossível testar.
- **HTTP/FastAPI na v0** (escolha do operador) — daemon para servir um comando que roda em segundos;
  retorna em P6 se houver consumidor não-Python.
- **MCP/agente chamando direto** — não substitui contrato determinístico; agente não é build.
- **LLM decidindo rota, custo ou qualidade** — herdado de D8 do `conselho`: LLM não decide o próprio gasto.
- **"Publicar mesmo assim" (`--force`/`--skip-qc`)** — o gate que tem bypass não é gate.
- **Escrever direto na pasta do jogo durante a geração** — quebra hot-reload e deixa lixo parcial.
- **Gerar `LOD` a partir de decimate cego na Rota B** — decimate destrói silhouette de mesh gerada;
  LOD de mesh generativa é P5, com critério visual.
- **Animar via modelo generativo** — fora de escopo, custo desproporcional em 6 GB (D14).
- **Rodar a pipeline sobre `/mnt/c`** — I/O lento comprovado e `edit` já quebrou em UNC no `conselho`.
- **YAML como formato de manifesto de saída** — consumidor precisa de parse estrito e hash estável; JSON.

## 4. Em aberto (não decidido)

| # | Pergunta | Quando fecha | Bloqueia |
|---|---|---|---|
| Q1 | Nome definitivo do produto (`forge3d` é provisório) | antes de publicar o pacote | nada — é reversível |
| ~~Q2~~ | **Resolvida em 10/11/2026 por D23** — allowlist em arquivo global, sandbox próprio liberado, sem bypass | — | — |
| Q3 | Escala/rig do Roblox R15: 1 stud ≈ 0,28 m, nomes de membro e formato de animação | teste com o importador no P2 | I8 no perfil Roblox |
| Q4 | Biblioteca de WFC para `modular` | P4 | Rota C |
| Q5 | Modelo de mesh: SF3D (licença Stability, exige registro e teto US$ 1 M) × TripoSR (MIT) | P3, com A/B de 10 assets | Rota `mesh`, D18 |
| ~~Q6~~ | **Resolvida em 10/11/2026 por D24** — estado central em `$FORGE3D_HOME`, nada no repo do jogo | — | — |
| Q7 | Assets versionados no git do jogo: direto × Git LFS | antes do primeiro asset real no GameZero | nada técnico |

## 5. Herdado do projeto `conselho` (aplicado aqui)

| Origem | Regra que vale aqui |
|---|---|
| D3 · D8 | local é executor; roteamento e custo são determinísticos, nunca decisão de LLM |
| D19 | ledger histórico (append-only, não lido) ≠ estado canônico (sobrescrito, curto, regenerado) |
| D23 | conselho só onde **não há oráculo** — ver [`CONSELHOS.md`](CONSELHOS.md) §1 |
| D24 | autoridade: decisão humana > código + teste > documento por data |
| D25 | teste verde = consistência, não correção → por isso D7 separa D1/D2/D3 |
| D26 | mudança de rumo exige critério escrito **antes** e custo na conta |
