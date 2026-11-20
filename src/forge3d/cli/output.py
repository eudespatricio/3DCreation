"""Helpers de saida JSON e formatacao textual para os subcomandos CLI."""

from __future__ import annotations

import contextlib
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

_STDOUT_JSON: TextIO | None = None


@contextlib.contextmanager
def stdout_json_context(ativo: bool) -> Iterator[None]:
    """Redireciona ``stdout`` para ``stderr`` quando ``--json`` esta ativo, preservando canal JSON."""
    global _STDOUT_JSON
    anterior = _STDOUT_JSON
    _STDOUT_JSON = sys.stdout if ativo else None
    ctx = contextlib.redirect_stdout(sys.stderr) if ativo else contextlib.nullcontext()
    try:
        with ctx:
            yield
    finally:
        _STDOUT_JSON = anterior


def emit_json(obj: object) -> None:
    payload = json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False, default=str)
    alvo_arq = os.environ.get("FORGE3D_JSON_OUT")
    if alvo_arq:
        p = Path(alvo_arq)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text(payload + "\n", encoding="utf-8")
        os.replace(tmp, p)
    stream = _STDOUT_JSON if _STDOUT_JSON is not None else sys.stdout
    print(payload, file=stream, flush=True)


def marca(ok: bool) -> str:
    return "ok  " if ok else "FALHA"
