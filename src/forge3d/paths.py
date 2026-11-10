"""Resolucao de caminhos — o Forge3D e um utilitario independente do projeto.

Tres raizes, tres donos, nenhuma mistura:

* ``raiz_dados()``   — schemas e perfis (fonte de verdade, vem com o pacote)
* ``raiz_config()``  — allowlist de destino (config global do usuario)
* ``raiz_estado()``  — cache, runs, staging, locks, indice, ledger (propriedade do Forge3D)

Nada aqui desce a partir do diretorio corrente: rodar de dentro de um repositorio de jogo nao
muda uma virgula do comportamento (D2-isolamento).
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "raiz_dados",
    "raiz_config",
    "raiz_estado",
    "arquivo_allowlist",
    "dir_cache",
    "dir_runs",
    "dir_staging",
    "dir_locks",
    "arquivo_indice",
    "arquivo_ledger",
    "dir_saida",
]


def raiz_dados() -> Path:
    """Raiz com ``schemas/`` e ``profiles/``."""
    env = os.environ.get("FORGE3D_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if (p / "schemas").is_dir():
            return p
    # repo (instalacao editavel): sobe ate achar schemas/
    for cand in Path(__file__).resolve().parents:
        if (cand / "schemas" / "spec.v1.schema.json").is_file():
            return cand
    # instalado como wheel: dados dentro do pacote
    return Path(__file__).resolve().parent / "data"


def _xdg(var: str, padrao: str) -> Path:
    valor = os.environ.get(var)
    base = Path(valor).expanduser() if valor else Path.home() / padrao
    return (base / "forge3d").resolve()


def raiz_config() -> Path:
    """Configuracao global do usuario (allowlist). Independente do cwd."""
    env = os.environ.get("FORGE3D_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    return _xdg("XDG_CONFIG_HOME", ".config")


def raiz_estado() -> Path:
    """Estado proprio: cache, runs, staging, locks, indice, ledger, saida demo."""
    env = os.environ.get("FORGE3D_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return _xdg("XDG_STATE_HOME", ".local/state")


def arquivo_allowlist() -> Path:
    return raiz_config() / "allowlist.yaml"


def dir_cache() -> Path:
    return raiz_estado() / "cache"


def dir_runs() -> Path:
    return raiz_estado() / "runs"


def dir_staging() -> Path:
    return raiz_estado() / "staging"


def dir_locks() -> Path:
    return raiz_estado() / "locks"


def arquivo_indice() -> Path:
    return raiz_estado() / "indice.sqlite"


def arquivo_ledger() -> Path:
    return raiz_estado() / "ledger.jsonl"


def dir_saida() -> Path:
    """Sandbox publico do proprio utilitario — sempre gravavel, nunca de terceiro."""
    return raiz_estado() / "saida"


def garantir_dirs() -> None:
    for d in (raiz_config(), dir_cache(), dir_runs(), dir_staging(), dir_locks(), dir_saida()):
        d.mkdir(parents=True, exist_ok=True)
