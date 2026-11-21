"""F1 — segmentacao por posicao de osso (partes articuladas).

Roda o script ``blender/split_por_ossos.py`` em subprocesso (I9: JSON em disco, nunca stdout),
valida a saida e devolve os metadados que o manifesto publica (``partes`` e ``rig.ancoras``).

Nao decide nada sobre o jogo: os nomes das partes e das juntas vem do ``spec`` (regra B25).
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
from pathlib import Path

from . import paths, post
from .errors import erro_qc


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _vec3_finito(val: object) -> bool:
    return (
        isinstance(val, (list, tuple))
        and len(val) == 3
        and all(isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(float(c)) for c in val)
    )


def dividir(glb: Path, item: dict, destino: Path, timeout: int = 900) -> dict:
    """Divide ``glb`` nas partes declaradas no item e grava os .glb em ``destino``.

    Devolve ``{"partes": [...], "ancoras": {...}, "arquivos": [...]}``; levanta ``FORGE-E-QC``
    quando a segmentacao nao devolve exatamente as partes pedidas ou produz artefato invalido.
    """
    partes_pedidas = item.get("partes") or []
    if not partes_pedidas:
        raise erro_qc("segmentacao: item sem 'partes'", id=item.get("id"))

    script = paths.raiz_dados() / "blender" / "split_por_ossos.py"
    if not script.is_file():
        raise erro_qc(f"segmentacao: script ausente: {script}", id=item.get("id"))

    glb = Path(glb)
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="forge3d-split-") as td:
        job = Path(td) / "job.json"
        resumo = Path(td) / "resumo.json"
        job.write_text(
            json.dumps(
                {
                    "glb": str(glb),
                    "saida": str(destino),
                    "partes": [
                        {"nome": str(p["nome"]), "junta": str(p.get("junta") or "")}
                        for p in partes_pedidas
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cmd = [
            post.binario(),
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(script),
            "--",
            str(job),
            str(resumo),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0 or not resumo.is_file():
            cauda = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
            raise erro_qc(
                "segmentacao falhou: " + " | ".join(cauda),
                id=item.get("id"),
            )
        info = json.loads(resumo.read_text(encoding="utf-8"))

    partes = info.get("partes") or []
    nomes = [str(p["nome"]) for p in partes]
    esperados = [str(p["nome"]) for p in partes_pedidas]
    if nomes != esperados:
        raise erro_qc(
            f"segmentacao devolveu partes diferentes do pedido: {nomes} != {esperados}",
            id=item.get("id"),
        )

    ancoras = info.get("ancoras")
    if not isinstance(ancoras, dict) or not ancoras:
        raise erro_qc("segmentacao: 'ancoras' ausente ou vazio", id=item.get("id"))
    for k_anc, v_anc in ancoras.items():
        if not _vec3_finito(v_anc):
            raise erro_qc(f"segmentacao: ancora invalida em '{k_anc}'", id=item.get("id"))

    arquivos = []
    for parte in partes:
        nome = str(parte["nome"])
        caminho = destino / str(parte["arquivo"])
        if not caminho.is_file() or caminho.stat().st_size <= 0:
            raise erro_qc(f"segmentacao: arquivo ausente ou vazio: {caminho}", id=item.get("id"))
        if int(parte.get("triangulos") or 0) <= 0:
            raise erro_qc(f"segmentacao: parte sem triangulos: {nome}", id=item.get("id"))
        if not _vec3_finito(parte.get("ancora")) or not _vec3_finito(parte.get("bbox")):
            raise erro_qc(f"segmentacao: ancora/bbox invalida em {nome}", id=item.get("id"))
        if "centro_bbox" in parte and not _vec3_finito(parte.get("centro_bbox")):
            raise erro_qc(f"segmentacao: centro_bbox invalido em {nome}", id=item.get("id"))
        parte["arquivo"] = caminho.name
        arquivos.append(
            {
                "caminho": caminho.name,
                "papel": "parte",
                "sha256": _sha256(caminho),
                "bytes": caminho.stat().st_size,
            }
        )

    retorno: dict = {"partes": partes, "ancoras": ancoras, "arquivos": arquivos}
    nome_comb = info.get("partes_combinadas")
    if nome_comb or (destino / "partes_combinadas.glb").is_file():
        caminho_comb = destino / str(nome_comb or "partes_combinadas.glb")
        if not caminho_comb.is_file() or caminho_comb.stat().st_size <= 0:
            raise erro_qc(
                f"segmentacao: partes_combinadas ausente ou vazio: {caminho_comb}",
                id=item.get("id"),
            )
        arquivos.append(
            {
                "caminho": caminho_comb.name,
                "papel": "partes_combinadas",
                "sha256": _sha256(caminho_comb),
                "bytes": caminho_comb.stat().st_size,
            }
        )
        retorno["partes_combinadas"] = caminho_comb.name

    return retorno
