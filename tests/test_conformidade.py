"""Testes do linter de conformidade (GAP-004, docs/gaps.md, tools/conformidade.py).

Cobre:
1. Caso limpo em tmp_path (exit 0, sem violacoes);
2. Caso com violacoes plantadas em tmp_path (exit 1, uma linha por violacao);
3. Execucao via subprocesso da CLI tools/conformidade.py.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Adiciona tools ao path para importar verificar_conformidade
RAIZ_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ_REPO / "tools"))

from conformidade import verificar_conformidade  # noqa: E402


def test_conformidade_caso_limpo(tmp_path: Path):
    """Estrutura valida e limpa nao produz violacoes e retorna 0."""
    repo = tmp_path / "repo_limpo"
    repo.mkdir()

    # (a) Arquivos de contexto dentro do limite
    (repo / "CONTINUAR.md").write_text("\n".join(f"linha {i}" for i in range(150)))  # <= 200
    (repo / "MAPA.md").write_text("\n".join(f"linha {i}" for i in range(40)))  # <= 60
    (repo / "AGENTS.md").write_text("\n".join(f"linha {i}" for i in range(50)))  # <= 80
    (repo / "INVARIANTES.md").write_text("\n".join(f"linha {i}" for i in range(180)))  # <= 200

    # (b) e (c) Diretorios com conteudo limpo
    for d in ("examples", "profiles", "schemas", "docs"):
        (repo / d).mkdir()

    (repo / "examples" / "lote.yaml").write_text("projeto: demo\nlote: []\n", encoding="utf-8")
    (repo / "profiles" / "perfil.yaml").write_text("schema: forge3d/profile@1\n", encoding="utf-8")
    (repo / "schemas" / "spec.json").write_text('{"title": "spec"}\n', encoding="utf-8")
    (repo / "docs" / "guia.md").write_text("# Guia\nCaminhos sob /home/user.\n", encoding="utf-8")

    violacoes = verificar_conformidade(repo)
    assert violacoes == []

    # Executa tambem via subprocesso CLI
    script = RAIZ_REPO / "tools" / "conformidade.py"
    proc = subprocess.run([sys.executable, str(script), str(repo)], capture_output=True, text=True)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_conformidade_caso_com_violacoes_plantadas(tmp_path: Path):
    """Detecta violacoes de tetos, franquias e caminhos proibidos, saindo 1."""
    repo = tmp_path / "repo_com_violacoes"
    repo.mkdir()

    # (a) Violacao de teto em CONTINUAR.md (> 200) e MAPA.md (> 60)
    (repo / "CONTINUAR.md").write_text("\n".join(f"linha {i}" for i in range(210)))
    (repo / "MAPA.md").write_text("\n".join(f"linha {i}" for i in range(65)))
    (repo / "AGENTS.md").write_text("ok\n")
    (repo / "INVARIANTES.md").write_text("ok\n")

    for d in ("examples", "profiles", "schemas", "docs"):
        (repo / d).mkdir()

    # (b) Violacoes de franquia
    (repo / "examples" / "ruim.yaml").write_text(
        "modelo: mario_kart\npersonagem: pikachu pokemon\n", encoding="utf-8"
    )
    (repo / "profiles" / "zelda_profile.yaml").write_text(
        "nome: zelda_style\n", encoding="utf-8"
    )

    # (c) Violacoes de caminhos proibidos (/mnt e UNC)
    (repo / "docs" / "instalacao.md").write_text(
        "Copie para /mnt/c/Users/teste/forge\n", encoding="utf-8"
    )
    (repo / "schemas" / "schema_unc.json").write_text(
        '{"path": "\\\\\\\\wsl$\\\\Ubuntu\\\\home"}\n', encoding="utf-8"
    )

    # (e) Nome de projeto de jogo e caminho pessoal fixo (I15)
    (repo / "src").mkdir()
    (repo / "src" / "engine.py").write_text(
        '# preset do GameZero\nDESTINO = "/home/eudespatricio/jogo"\n', encoding="utf-8"
    )
    (repo / "examples" / "projeto.yaml").write_text("projeto: jogo-roblox\n", encoding="utf-8")

    violacoes = verificar_conformidade(repo)
    assert len(violacoes) >= 6

    # Verifica se cada tipo esperado de violacao foi capturado
    assert any("TETO: CONTINUAR.md" in v for v in violacoes)
    assert any("TETO: MAPA.md" in v for v in violacoes)
    assert any("I14:" in v and "mario" in v.lower() for v in violacoes)
    assert any("I14:" in v and "pokemon" in v.lower() for v in violacoes)
    assert any("I14:" in v and "zelda" in v.lower() for v in violacoes)
    assert any("I12:" in v and "/mnt/c/" in v for v in violacoes)
    assert any("I12:" in v and "\\\\wsl" in v for v in violacoes)
    assert any("I15:" in v and "gamezero" in v.lower() for v in violacoes)
    assert any("I15:" in v and "jogo-roblox" in v.lower() for v in violacoes)
    assert any("I15:" in v and "/home/eudespatricio/" in v for v in violacoes)

    # Executa via subprocesso CLI para verificar saida e exit code
    script = RAIZ_REPO / "tools" / "conformidade.py"
    proc = subprocess.run([sys.executable, str(script), str(repo)], capture_output=True, text=True)
    assert proc.returncode == 1

    linhas_saida = [linha for linha in proc.stdout.splitlines() if linha.strip()]
    assert len(linhas_saida) == len(violacoes)
