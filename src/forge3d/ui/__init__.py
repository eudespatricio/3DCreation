"""Interface web local do Forge3D Studio (stdlib HTTP, zero dependencias novas)."""

from __future__ import annotations

from .server import Forge3DHTTPServer, criar_servidor, servir
from .state import (
    JobManager,
    UIHTTPError,
    eh_host_loopback,
    resolver_caminho_leitura,
    salvar_spec_ui,
    salvar_upload_input,
    validar_origem_csrf,
)

__all__ = [
    "Forge3DHTTPServer",
    "JobManager",
    "UIHTTPError",
    "criar_servidor",
    "eh_host_loopback",
    "resolver_caminho_leitura",
    "salvar_spec_ui",
    "salvar_upload_input",
    "servir",
    "validar_origem_csrf",
]
