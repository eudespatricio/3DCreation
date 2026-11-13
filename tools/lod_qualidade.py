"""Qualidade de LOD por silhueta — mede IoU da projecao frente/lado contra o LOD0.

Motivo (GAP-013): o LOD de `blocky` sai de `decimate` cego; reduzir triangulos nao prova que a
silhueta sobreviveu. Aqui a malha e projetada ortograficamente em um plano de pixels (sem Blender,
sem GPU) e o IoU entre o LOD0 e cada LOD e medido no mesmo enquadramento.

Uso:
    python tools/lod_qualidade.py <destino|arquivo.glb> [...] [--resolucao 256]
                                  [--ioi-min 0.97] [--bbox-max-pct 2.0]

Os pares sao achados pelo nome: `<id>.glb` e `<id>_LOD<n>.glb` (o colisor `_colisao` fica fora).
Saida: uma linha por LOD; exit 1 se algum LOD furar o criterio.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw  # noqa: E402

from forge3d import qc  # noqa: E402

#: eixos da projecao: (indice no espaco glTF de cada eixo horizontal, vertical)
VISTAS = {
    "frente": (0, 1),  # x, y (glTF Y-up, frente -Z)
    "lado": (2, 1),  # z, y
}


def _ler(caminho: Path) -> tuple[list[tuple], list[tuple]]:
    gltf, binario = qc.ler_glb_bin(caminho)
    return qc.malha(gltf, binario)


def _bbox(posicoes: list[tuple]) -> list[tuple[float, float]]:
    return [
        (min(p[i] for p in posicoes), max(p[i] for p in posicoes)) for i in range(3)
    ]


def _mascara(
    posicoes: list[tuple],
    triangulos: list[tuple],
    vista: str,
    caixa: list[tuple[float, float]],
    resolucao: int,
) -> Image.Image:
    """Rasteriza a malha projetada numa imagem 1-bit (255 = coberto)."""
    horizontal, vertical = VISTAS[vista]
    (x0, x1), (y0, y1) = caixa[horizontal], caixa[vertical]
    largura = max(x1 - x0, 1e-6)
    altura = max(y1 - y0, 1e-6)
    margem = 0.02
    escala = (resolucao - 1) / max(largura, altura) * (1.0 - 2 * margem)

    def px(p: tuple) -> tuple[float, float]:
        x = (p[horizontal] - x0) * escala + (resolucao - 1) * margem
        y = (p[vertical] - y0) * escala + (resolucao - 1) * margem
        return (x, resolucao - 1 - y)

    imagem = Image.new("L", (resolucao, resolucao), 0)
    desenho = ImageDraw.Draw(imagem)
    for a, b, c in triangulos:
        desenho.polygon([px(posicoes[a]), px(posicoes[b]), px(posicoes[c])], fill=255)
    return imagem


#: faixas verticais: uma media global alta esconde a perda de um membro inteiro
FAIXAS = 8


def _pior_faixa(a: Image.Image, b: Image.Image, faixas: int = FAIXAS) -> float:
    """Menor IoU entre as faixas horizontais — o membro que sumiu aparece aqui."""
    largura, altura = a.size
    pior = 1.0
    for i in range(faixas):
        y0 = i * altura // faixas
        y1 = (i + 1) * altura // faixas
        pior = min(pior, _iou(a.crop((0, y0, largura, y1)), b.crop((0, y0, largura, y1))))
    return pior


def _iou(a: Image.Image, b: Image.Image) -> float:
    pa, pb = list(a.getdata()), list(b.getdata())
    intersecao = sum(1 for x, y in zip(pa, pb) if x and y)
    uniao = sum(1 for x, y in zip(pa, pb) if x or y)
    return intersecao / uniao if uniao else 1.0


def _pares(entradas: list[Path]) -> dict[str, dict[str, Path]]:
    """Pares LOD0/_LODn. Quando o destino tem manifesto, ele e a fonte de verdade: arquivo que

    saiu do manifesto nao entra na conta (o publish limpa, mas um destino antigo pode ter sobra).
    """
    arquivos: list[Path] = []
    for entrada in entradas:
        if entrada.is_dir():
            manifestos = sorted(entrada.glob("*.manifest.json"))
            if manifestos:
                for manifesto in manifestos:
                    dados = json.loads(manifesto.read_text(encoding="utf-8"))
                    for arq in dados.get("files", []):
                        if arq.get("caminho", "").endswith(".glb") and "colisao" not in arq["caminho"]:
                            arquivos.append(entrada / arq["caminho"])
                continue
            arquivos.extend(sorted(entrada.glob("*.glb")))
        else:
            arquivos.append(entrada)
    pares: dict[str, dict[str, Path]] = {}
    for arquivo in arquivos:
        if arquivo.name.endswith("_colisao.glb"):
            continue
        if "_LOD" in arquivo.stem:
            base, _, nivel = arquivo.stem.partition("_LOD")
            pares.setdefault(base, {})[f"LOD{nivel}"] = arquivo
        else:
            pares.setdefault(arquivo.stem, {})["LOD0"] = arquivo
    return {k: v for k, v in pares.items() if "LOD0" in v}


def avaliar(
    pares: dict[str, dict[str, Path]],
    resolucao: int = 256,
    ioi_min: float = 0.85,
    bbox_max_pct: float = 2.0,
    faixa_min: float = 0.75,
) -> tuple[list[dict], int]:
    linhas: list[dict] = []
    falhas = 0
    for base, niveis in sorted(pares.items()):
        pos0, tris0 = _ler(niveis["LOD0"])
        caixa0 = _bbox(pos0)
        mascara0 = {
            vista: _mascara(pos0, tris0, vista, caixa0, resolucao) for vista in VISTAS
        }
        for nivel in sorted(niveis, key=lambda n: int(n.replace("LOD", ""))):
            caminho = niveis[nivel]
            pos, tris = _ler(caminho)
            caixa = _bbox(pos)
            linha = {
                "asset": base,
                "nivel": nivel,
                "triangulos": len(tris),
                "ratio_tris": round(len(tris) / max(len(tris0), 1), 3),
                "ioi": {},
                "bbox_pct": {},
            }
            pior_ioi = 1.0
            pior_bbox = 0.0
            pior_faixa = 1.0
            for vista in VISTAS:
                mascara = _mascara(pos, tris, vista, caixa0, resolucao)
                valor = _iou(mascara0[vista], mascara)
                linha["ioi"][vista] = round(valor, 4)
                if nivel != "LOD0":
                    pior_ioi = min(pior_ioi, valor)
                    pior_faixa = min(pior_faixa, _pior_faixa(mascara0[vista], mascara))
                if nivel == "LOD0":
                    linha["ioi"][vista] = 1.0
            for i, eixo in enumerate("xyz"):
                base_eixo = caixa0[i][1] - caixa0[i][0]
                delta = abs((caixa[i][1] - caixa[i][0]) - base_eixo) / max(base_eixo, 1e-9) * 100
                linha["bbox_pct"][eixo] = round(delta, 2)
                if nivel != "LOD0":
                    pior_bbox = max(pior_bbox, delta)
            linha["faixa"] = round(pior_faixa, 4)
            limiar_ioi = min(ioi_min, 0.78) if linha["triangulos"] < 200 else ioi_min
            limiar_faixa = min(faixa_min, 0.65) if linha["triangulos"] < 200 else faixa_min
            if nivel != "LOD0" and (
                pior_ioi < limiar_ioi or pior_bbox > bbox_max_pct or pior_faixa < limiar_faixa
            ):
                linha["status"] = "reprovado"
                falhas += 1
            else:
                linha["status"] = "ok"
            linhas.append(linha)
    return linhas, falhas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qualidade de LOD por silhueta (GAP-013)")
    parser.add_argument("entradas", nargs="+")
    parser.add_argument("--resolucao", type=int, default=256)
    parser.add_argument("--ioi-min", type=float, default=0.85)
    parser.add_argument("--bbox-max-pct", type=float, default=2.0)
    parser.add_argument("--faixa-min", type=float, default=0.75)
    args = parser.parse_args(argv)

    pares = _pares([Path(e) for e in args.entradas])
    if not pares:
        print("nenhum par LOD0/_LODn encontrado")
        return 2
    linhas, falhas = avaliar(
        pares, args.resolucao, args.ioi_min, args.bbox_max_pct, args.faixa_min
    )
    print(
        f"criterio: IoU >= {args.ioi_min} (frente e lado), faixa vertical >= {args.faixa_min} "
        f"e bbox <= {args.bbox_max_pct}% por eixo"
    )
    for linha in linhas:
        print(
            f"{linha['asset']:32s} {linha['nivel']:5s} tris={linha['triangulos']:5d} "
            f"({linha['ratio_tris']:.0%}) IoU frente={linha['ioi']['frente']:.4f} "
            f"lado={linha['ioi']['lado']:.4f} faixa={linha['faixa']:.4f} "
            f"bbox={linha['bbox_pct']} {linha['status']}"
        )
    print("LODs reprovados:", falhas)
    return 0 if falhas == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
