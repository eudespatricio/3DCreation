# CONTINUAR — handoff de sessão

**Data:** 10/11/2026 · **P0, P0.5 e P1 fechadas. P3 parcial: a mecânica funciona, a qualidade não.**
29 testes verdes · janela encerrada em transição.

**Para a próxima janela:** leia [`docs/pendencias.md`](docs/pendencias.md) (o que falta, com
critério) e [`docs/goal-proxima-janela.md`](docs/goal-proxima-janela.md) (briefing + bloco de
Goal pronto para colar). Verificação rápida: `python -m pytest tests/test_e2e_rapido.py -q`.

---

## O que é este projeto

**Forge3D** transforma um **lote declarativo** (YAML/JSON) em assets 3D verificáveis — `.glb` com
escala, pivô, LOD, colisão, rig, QC e manifesto — e publica de forma atômica num destino autorizado.

Requisito duro do operador (10/11/2026): **o utilitário é independente de projeto**. Não lê config do
diretório onde roda, não escreve fora do próprio estado, não importa código de jogo (D25).

## Onde estamos, por fase

| Fase | Estado | Entrega |
|---|---|---|
| **P0** | ✔ | arquitetura, contratos `spec@1`/`manifest@1`, 2 perfis, docs de processo |
| **P0.5** | ✔ | D23 allowlist · D24 estado central · `tools/check-contexto.sh` |
| **P1** | ✔ | rotas `blocky` e `import` de ponta a ponta: validar → planejar → gerar → Blender → QC G1–G9 → cache → publicar → índice → ledger |
| **P3** | **parcial** | stack GPU + TripoSR rodando; **SF3D encerrado em 6 GB** (geometria sai, bake exige CUDA, ~8 min/imagem); canal de delegação mapeado. Qualidade ainda inutilizável |
| **P2** | pendente | perfil `roblox-r15` (o YAML existe; falta validar no Studio) |
| **P4** | pendente | rota `modular` (WFC) |
| **P5** | pendente | animação e retarget |

## O que foi testado de image-to-3D (e falhou)

| Input | Pose | Resultado | Veredito |
|---|---|---|---|
| foto promocional com capa | A-pose | casca oca, pernas fundidas pela capa | inutilizável |
| render do nosso android | flat | laje extrudada | inutilizável |
| concept T-pose (OpenPose) | T-pose, capa | capa virou chapa de 1 m, corpo lâmina — **pior** | inutilizável |
| T-pose com `--mc-resolution 512` | T-pose | mesma topologia de 256, e 336 s em vez de 4,5 s | resolução não é o gargalo |

**Conclusões que a evidência sustenta:**

1. Fundo neutro e recorte **funcionam** (rembg + composição; o input do modelo saiu correto).
2. Pose controlada resolve simetria, **não** resolve oclusão nem superfície fina — a capa é o pior caso.
3. O gargalo é a **representação do modelo de vista única**, não a pose nem a resolução do marching cubes.
4. A saída do TripoSR **não passa no nosso QC**: sem UV, sem material, e orientação fora do frame
   canônico em 3/3 inputs.

## Números medidos nesta máquina

| Medida | Valor |
|---|---|
| `run` 3 itens, cache frio / quente | **2.082 ms** / **476 ms** (`trabalho_executado: 0`) |
| `plan` / `verify` | 141 ms / 127 ms |
| Determinismo D1 | **sha256 idênticos** nos 12 artefatos entre dois runs com cache limpo |
| Suite | **28 testes** verdes (19 unidade + 9 ponta a ponta) |
| Android humanoid | 300 tris · 25 caixas · **23 ossos** · LOD 300/130/45 · **atlas 64×64 px** (34,6 px/m) · 5 arquivos · 73.222 B |
| Import no **Godot 4.3** | `Node3D → Armature → Skeleton3D (23) → MeshInstance3D`; AABB idêntico ao manifesto; `filtro=2` (nearest+mipmaps) |
| Stack GPU | torch **2.4.1+cu121**, `cuda_available=True` na RTX 3060 (6.144 MiB) |
| TripoSR — tempo | forward **1,8–3,6 s** · extração **3,7–23 s** · total **21–55 s** frio (24 s é carregar pesos) |
| TripoSR — saída | ~**67.800 tris**, GLB 1,36 MB, só `COLOR_0` (sem UV, sem material) |
| Canal de delegação | `agentapi` funciona com `ANTIGRAVITY_LS_ADDRESS=127.0.0.1:43023` + `ANTIGRAVITY_CSRF_TOKEN` |

## Decidido (não reabrir sem evidência nova)

`D3` CLI-only · `D5` plan/run/verify/publish · `D7` D1/D2/D3 · `D9` QC sem bypass ·
`D11` GPU serializada · `D14` animação fora da v0 · `D18` licença é gate · `D19` naming neutro ·
`D23` allowlist · `D24` estado central · `D25` isolamento · `D26` núcleo leve.

## Aberto — e o que cada um trava

| # | Pergunta | Trava | Fecha em |
|---|---|---|---|
| **Q8** | qual reconstrutor: **SF3D** (UV+material, licença Stability) × TripoSR (MIT, sem UV) | a qualidade de qualquer personagem | P3, com 10 assets |
| Q5 | SF3D × TripoSR por licença comercial | publicação | junto com Q8 |
| Q3 | escala/rig Roblox (0,28 m/stud) | perfil Roblox | P2, teste no Studio |
| Q1 | nome definitivo do produto | publicar o pacote | antes do release |
| Q7 | assets no git do jogo (normal × LFS) | primeiro asset real | antes de integrar |
| Q9 | delegação: chave de API (completude) × `agentapi` (sessão agêntica) | uso seguro em execução | P4 |

## Próximos passos — com custo, em ordem de evidência

| # | Ação | Custo | Ataca |
|---|---|---|---|
| **1** | **Separar o asset**: `personagem.corpo` / `personagem.capa` / arma como `id` distintos | 1 sessão, sem GPU | a oclusão, que é a causa raiz medida |
| **2** | **Avaliar SF3D** (pesos gated no HF, precisa token): UV + material nativos | ~5 GB, 1 sessão | GAP-028 (sem UV/material) e a qualidade |
| **3** | Provider `i23d` de verdade: normalização canônica + bake + lock de GPU | 1–2 sessões | fechar a rota `mesh` |
| **4** | Concept (SD1.5 + ControlNet) | ~4,5 GB, 2 sessões | entrada — **menor prioridade**, a pose não era o gargalo |
| **5** | P2 Roblox no Studio | 1 sessão | segundo perfil de export |
| **6** | Animação (P5) | 2–3 sessões | maior salto de percepção no Godot |

**Recomendação:** 1 → 2 → 3 juntos fecham a rota `mesh` com evidência; 4 só depois. O passo 1 é barato
e pode rodar em paralelo.

## Comandos

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate

forge3d doctor                         # ambiente (mesh reporta o que falta)
forge3d plan  examples/lote_android.yaml
forge3d run   examples/lote_android.yaml
forge3d verify ~/.local/state/forge3d/saida/android
python -m pytest -q                    # 28 testes
bash tools/check-contexto.sh           # tetos
python tools/check-p0.py               # docs, schemas, I12/I14

# preview sem abrir o jogo
blender -b --factory-startup --python tools/render_preview.py -- <glb> <saida> --pose|--close
# normalização canônica de malha gerada
blender -b --factory-startup --python tools/normalize_mesh.py -- <in.glb> <out.glb>
# delegação (só com a IDE aberta; ver docs/delegacao.md)
python tools/delegar.py --tipo segunda_opiniao --texto "..." --exigir riscos --dry-run
```

## Arquivos-chave

`README.md` · `AGENTS.md` · `MAPA.md` · `CONSELHOS.md` · `DECISOES.md` · `INVARIANTES.md` ·
`docs/arquitetura.md` · `docs/contratos.md` · `docs/rotas-e-providers.md` · `docs/perfis-export.md` ·
`docs/qc-e-verificacao.md` · `docs/dependencias.md` · `docs/riscos-e-licencas.md` ·
`docs/roadmap.md` · `docs/gaps.md` · `docs/plano-p3-concept.md` · `docs/delegacao.md` ·
`src/forge3d/` (13 módulos) · `blender/postprocess.py` · `tools/` (`normalize_mesh`, `render_preview`,
`delegar`, `torchmcubes_shim`, `check-*`) · `tests/`

## Regras invioláveis (top 6)

1. Nada roda sobre `/mnt/c` ou UNC (I12); estado sempre em ext4 sob `$FORGE3D_HOME`.
2. Nenhuma escrita fora do destino autorizado (I3/I13) — autorizar é `forge3d allowlist add`.
3. QC reprovado não publica; não existe bypass (I5).
4. Diffusion nunca é D1 (D7).
5. Mudou a saída de um provider? **Suba `VERSAO`** — entra na chave de cache (D6).
6. Blender 4.2 pinado, subprocesso, canal JSON; nunca `pip install` no Python dele (I9).

## Como retomar

> Leia `3DCreation/CONTINUAR.md`, `MAPA.md` e `DECISOES.md` §2 e §4. P0, P0.5 e P1 estão fechadas;
> P3 está parcial: TripoSR roda (torch em `~/.cache/forge3d/venv-gpu`), mas a qualidade é inutilizável
> e a saída não passa no QC (sem UV/material, orientação fora do frame). Evidência: T-pose piorou,
> mc-resolution 512 não mudou topologia. Não reabra D3–D26.
> Próximo passo recomendado: **separar o asset (corpo/capa)** e **avaliar SF3D** antes de investir em
> concept. Fechar Q8 com 10 assets medidos.
