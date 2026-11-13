"""Erros com codigo estavel + exit code (D21, contract §5-§6).

Codigo de erro faz parte do contrato: o pipe ramifica por ele, nunca por mensagem.
"""

from __future__ import annotations

#: exit codes estaveis — ver docs/contratos.md §5
EXIT_OK = 0
EXIT_SPEC = 2
EXIT_QC = 3
EXIT_AMBIENTE = 4
EXIT_PROVIDER = 5
EXIT_RECURSO = 6
EXIT_PARCIAL = 7

#: precedencia quando varias causas existem (docs/contratos.md §5)
PRECEDENCIA = (EXIT_AMBIENTE, EXIT_SPEC, EXIT_RECURSO, EXIT_PROVIDER, EXIT_QC, EXIT_PARCIAL, EXIT_OK)


class ForgeError(Exception):
    """Falha com codigo de contrato."""

    def __init__(self, codigo: str, mensagem: str, exit_code: int, detalhes: dict | None = None):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem
        self.exit_code = exit_code
        self.detalhes = detalhes or {}

    def como_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"codigo": self.codigo, "mensagem": self.mensagem}
        if self.detalhes:
            d["detalhes"] = self.detalhes
        return d

    def __str__(self) -> str:  # pragma: no cover - cosmetico
        return f"[{self.codigo}] {self.mensagem}"


def erro_spec(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-SPEC", msg, EXIT_SPEC, det)


def erro_input_tampered(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-INPUT-TAMPERED", msg, EXIT_SPEC, det)


def erro_destino(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-DESTINO", msg, EXIT_SPEC, det)


def erro_path(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-PATH", msg, EXIT_SPEC, det)


def erro_ambiente(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-AMBIENTE", msg, EXIT_AMBIENTE, det)


def erro_provider(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-PROVIDER", msg, EXIT_PROVIDER, det)


def erro_provider_run(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-PROVIDER-RUN", msg, EXIT_PROVIDER, det)


def erro_licenca(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-LICENCA", msg, EXIT_PROVIDER, det)


def erro_recurso(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-RECURSO", msg, EXIT_RECURSO, det)


def erro_bpy(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-BPY", msg, EXIT_PROVIDER, det)


def erro_qc(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-QC", msg, EXIT_QC, det)


def erro_upload(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-UPLOAD", msg, EXIT_PROVIDER, det)


def erro_manifesto(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-MANIFEST", msg, EXIT_QC, det)


def erro_interno(msg: str, **det) -> ForgeError:
    return ForgeError("FORGE-E-INTERNO", msg, EXIT_AMBIENTE, det)


def exit_agregado(codigos: list[int], total: int) -> int:
    """Combina exit codes de varios itens pela precedencia do contrato."""
    if not codigos:
        return EXIT_OK
    presentes = set(codigos)
    for code in PRECEDENCIA[:-1]:
        if code in presentes:
            # tudo publicado ou cache-hit => OK; mistura => parcial
            return EXIT_PARCIAL if code == EXIT_OK else code
    return EXIT_OK
