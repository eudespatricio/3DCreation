"""Registro de providers + allowlist de licenca (D18, I7).

Modelo fora da allowlist nao e instanciado, mesmo que esteja instalado. Licenca e gate de arquitetura,
nao aviso de rodape.
"""

from __future__ import annotations

from .base import Provider, RawAsset

__all__ = ["obter", "registrados", "LICENCAS", "Provider", "RawAsset", "licenca_de"]

#: allowlist comercial. ``uso_comercial=False`` => provider bloqueado no publish.
LICENCAS: dict[str, dict] = {
    "procedural": {
        "modelo": "procedural (sem modelo de terceiro)",
        "uso_comercial": True,
        "notice": "Asset gerado proceduralmente por Forge3D; nenhum modelo generativo participou.",
    },
    "triposr": {
        "modelo": "TripoSR",
        "uso_comercial": True,
        "notice": "TripoSR (MIT). Ver docs/riscos-e-licencas.md.",
    },
    "sf3d": {
        "modelo": "Stable Fast 3D",
        "uso_comercial": True,
        "notice": (
            "Stable Fast 3D sob Stability AI Community License: exige registro em "
            "stability.ai/community-license, arquivo NOTICE e atribuicao 'Powered by Stability AI'; "
            "a licenca termina acima de US$ 1M de receita anual."
        ),
    },
}

#: rotas conhecidas e o provider que as atende nesta fase
_FABRICAS = {}


def registrar(rota: str, fabrica) -> None:
    _FABRICAS[rota] = fabrica


def registrados() -> dict[str, object]:
    return {rota: _estado(rota) for rota in ("blocky", "import", "mesh", "modular")}


def _estado(rota: str) -> str:
    fabrica = _FABRICAS.get(rota)
    if fabrica is None:
        return "nao implementado"
    try:
        return fabrica().preflight()[1] or "pronto"
    except Exception as exc:  # noqa: BLE001 - doctor nunca derruba
        return f"indisponivel: {exc}"


def obter(rota: str) -> Provider:
    from ..errors import erro_provider

    fabrica = _FABRICAS.get(rota)
    if fabrica is None:
        fases = {"mesh": "P3", "modular": "P4"}
        raise erro_provider(
            f"rota '{rota}' ainda nao implementada"
            + (f" (prevista para {fases[rota]})" if rota in fases else ""),
            rota=rota,
        )
    return fabrica()


def licenca_de(chave: str) -> dict:
    from ..errors import erro_licenca

    if chave not in LICENCAS:
        raise erro_licenca(
            f"modelo '{chave}' fora da allowlist comercial (D18). "
            f"Permitidos: {', '.join(sorted(LICENCAS))}",
            modelo=chave,
        )
    return dict(LICENCAS[chave])


# registro das rotas implementadas (import tardio evita ciclo)
def _carregar() -> None:
    from .blocky import BlockyProvider
    from .importer import ImportProvider

    registrar("blocky", BlockyProvider)
    registrar("import", ImportProvider)


_carregar()
