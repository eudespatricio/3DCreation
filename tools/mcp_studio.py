"""Cliente MCP (stdio) do StudioMCP do Roblox — executa Luau no Studio e devolve o resultado.

Por que existe: validar coisa dentro do Roblox exige o Studio GUI logado (D51), e o servidor
headless do run-in-roblox nao carrega asset privado. Com o MCP ligado no Studio, este cliente
fala JSON-RPC com o `StudioMCP.exe` e roda o codigo no place aberto.

Uso:
    python tools/mcp_studio.py --estado
    python tools/mcp_studio.py --exec 'return workspace:FindFirstChild("X") ~= nil'

O binario do proxy muda a cada versao do Studio; `--binario` ou `FORGE3D_STUDIOMCP` apontam
para o caminho certo (default: a versao vista nesta maquina).
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time

_PADRAO = (
    "/mnt/c/Users/Eudes/AppData/Local/Roblox/Versions/version-63eb6055af4e4688/StudioMCP.exe"
)


def binario() -> str:
    return os.environ.get("FORGE3D_STUDIOMCP", _PADRAO)


class Cliente:
    """MCP sobre stdio: uma linha JSON por mensagem, resposta casada por id."""

    def __init__(self, exe: str | None = None):
        self.proc = subprocess.Popen(
            [exe or binario(), "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.fila: queue.Queue = queue.Queue()
        self.erros: list[str] = []
        threading.Thread(target=self._ler, daemon=True).start()
        threading.Thread(target=self._ler_err, daemon=True).start()
        self.id = 0

    def _ler(self):
        for linha in self.proc.stdout:
            texto = linha.decode("utf-8", "replace").strip()
            if texto:
                self.fila.put(texto)
        self.fila.put(None)

    def _ler_err(self):
        for linha in self.proc.stderr:
            self.erros.append(linha.decode("utf-8", "replace").strip())

    def pedir(self, metodo: str, params=None, timeout: float = 30) -> dict | None:
        self.id += 1
        msg = {"jsonrpc": "2.0", "id": self.id, "method": metodo}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        self.proc.stdin.flush()
        limite = time.time() + timeout
        while time.time() < limite:
            try:
                texto = self.fila.get(timeout=max(0.1, limite - time.time()))
            except queue.Empty:
                break
            if texto is None:
                return None
            try:
                obj = json.loads(texto)
            except ValueError:
                continue
            if obj.get("id") == self.id:
                return obj
        return None

    def notificar(self, metodo: str, params=None) -> None:
        msg = {"jsonrpc": "2.0", "method": metodo}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        self.proc.stdin.flush()

    def abrir(self) -> None:
        self.pedir(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "forge3d", "version": "0.1"},
            },
        )
        self.notificar("notifications/initialized")

    def chamar(self, nome: str, argumentos: dict, timeout: float = 60) -> str:
        resposta = self.pedir(
            "tools/call", {"name": nome, "arguments": argumentos}, timeout=timeout
        )
        if not resposta:
            return ""
        partes = (resposta.get("result") or {}).get("content") or []
        return "\n".join(p.get("text", "") for p in partes if isinstance(p, dict))

    def studio_id(self, tentativas: int = 15, espera: float = 4.0) -> str | None:
        """O proxy precisa ficar vivo alguns segundos para o Studio se conectar."""
        for _ in range(tentativas):
            bruto = self.chamar("list_roblox_studios", {}, timeout=30)
            try:
                estudios = json.loads(bruto).get("studios") or []
            except ValueError:
                estudios = []
            if estudios:
                return estudios[0].get("id") or estudios[0].get("studioId")
            time.sleep(espera)
        return None

    def luau(self, codigo: str, sid: str, datamodel: str = "Edit") -> str:
        return self.chamar(
            "execute_luau",
            {"code": codigo, "datamodel_type": datamodel, "studio_id": sid},
            timeout=90,
        )

    def fechar(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="mcp_studio", description="Roda Luau no Studio via MCP.")
    p.add_argument("--estado", action="store_true", help="lista os Studios conectados")
    p.add_argument("--exec", dest="codigo", help="codigo Luau a executar no place")
    p.add_argument("--datamodel", default="Edit", choices=["Edit", "Client", "Server"])
    p.add_argument("--binario", default=None)
    args = p.parse_args(argv)

    cliente = Cliente(args.binario)
    try:
        cliente.abrir()
        sid = cliente.studio_id(tentativas=3 if args.estado else 15)
        if not sid:
            print("nenhum Studio conectado (MCP ligado? proxy vivo alguns segundos?)")
            return 1
        print("studio:", sid)
        if args.codigo:
            print(cliente.luau(args.codigo, sid, args.datamodel))
        return 0
    finally:
        cliente.fechar()


if __name__ == "__main__":
    raise SystemExit(main())
