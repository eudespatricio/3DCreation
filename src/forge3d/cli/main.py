"""CLI — o unico contrato de integracao (D3).

stdout: um objeto JSON com ``--json``, ou texto humano curto.
stderr: diagnostico humano.
Exit code: estavel (docs/contratos.md §5).
"""

from __future__ import annotations

import sys

from .. import __version__

__all__ = ["main", "__version__"]


def main(argv: list[str] | None = None) -> int:
    from .comandos import despachar

    return despachar(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
