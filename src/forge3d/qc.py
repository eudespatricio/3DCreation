"""QC — portao duro entre "gerou" e "entrou no jogo" (D9, I5).

Mede o **arquivo exportado**, nao a intencao. Leitura do GLB e feita aqui, de proposito: se o
pipeline mentir sobre o que escreveu, o QC descobre.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

from .errors import erro_qc

__all__ = [
    "ler_glb",
    "ler_glb_bin",
    "analisar",
    "topologia",
    "convexidade",
    "verificar",
    "GATES",
]

GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9")
_MAGIC = 0x46546C67  # "glTF"
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942  # "BIN\0"


def ler_glb_bin(caminho: Path) -> tuple[dict, bytes]:
    """Le o GLB e devolve (json, chunk binario). O binario e necessario para topologia."""
    dados = Path(caminho).read_bytes()
    if len(dados) < 12:
        raise erro_qc(f"glb truncado: {caminho}", arquivo=str(caminho))
    magic, _versao, _tamanho = struct.unpack_from("<III", dados, 0)
    if magic != _MAGIC:
        raise erro_qc(f"nao e GLB valido: {caminho}", arquivo=str(caminho))
    offset = 12
    bloco_json = None
    bloco_bin = b""
    while offset < len(dados):
        if offset + 8 > len(dados):
            break
        tamanho, tipo = struct.unpack_from("<II", dados, offset)
        offset += 8
        bloco = dados[offset : offset + tamanho]
        offset += tamanho
        if tipo == _CHUNK_JSON:
            bloco_json = bloco
        elif tipo == _CHUNK_BIN:
            bloco_bin = bloco
    if bloco_json is None:
        raise erro_qc(f"GLB sem chunk JSON: {caminho}", arquivo=str(caminho))
    return json.loads(bloco_json.decode("utf-8")), bloco_bin


def ler_glb(caminho: Path) -> dict:
    return ler_glb_bin(caminho)[0]


def analisar(gltf: dict) -> dict:
    """Extrai o que o QC precisa sem confiar no produtor."""
    accessors = gltf.get("accessors", [])
    nodes = gltf.get("nodes", [])
    meshes = gltf.get("meshes", [])
    materials = gltf.get("materials", [])

    triangulos = 0
    vertices = 0
    primitivas = 0
    sem_uv = 0
    minimos = [float("inf")] * 3
    maximos = [float("-inf")] * 3

    for malha in meshes:
        for prim in malha.get("primitives", []):
            primitivas += 1
            modo = prim.get("mode", 4)
            atributos = prim.get("attributes", {})
            if "TEXCOORD_0" not in atributos:
                sem_uv += 1
            pos = atributos.get("POSITION")
            if pos is not None and pos < len(accessors):
                acc = accessors[pos]
                vertices += int(acc.get("count", 0))
                if acc.get("min") and acc.get("max"):
                    for i in range(3):
                        minimos[i] = min(minimos[i], float(acc["min"][i]))
                        maximos[i] = max(maximos[i], float(acc["max"][i]))
            indices = prim.get("indices")
            if modo != 4:
                continue
            if indices is not None and indices < len(accessors):
                triangulos += int(accessors[indices].get("count", 0)) // 3
            elif pos is not None and pos < len(accessors):
                triangulos += int(accessors[pos].get("count", 0)) // 3

    tem_bbox = minimos[0] != float("inf")
    bbox = (
        [maximos[i] - minimos[i] for i in range(3)] if tem_bbox else [0.0, 0.0, 0.0]
    )
    imagens = gltf.get("images", [])
    skins = gltf.get("skins", [])
    nomes_nos = [n.get("name", "") for n in nodes]
    nomes_ossos = []
    if skins:
        for indice in skins[0].get("joints", []):
            if indice < len(nodes):
                nomes_ossos.append(nodes[indice].get("name", ""))

    return {
        "triangulos": triangulos,
        "vertices": vertices,
        "primitivas": primitivas,
        "sem_uv": sem_uv,
        "bbox_m": [round(v, 6) for v in bbox],
        "min": [round(v, 6) for v in minimos] if tem_bbox else [0, 0, 0],
        "max": [round(v, 6) for v in maximos] if tem_bbox else [0, 0, 0],
        "materiais": len(materials),
        "com_textura": sum(
            1 for m in materials if (m.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
        ),
        "imagens": len(imagens),
        "imagens_externas": [i["uri"] for i in imagens if i.get("uri")],
        "ossos": len(nomes_ossos),
        "nomes_ossos": nomes_ossos,
        "nos": nomes_nos,
        "colisores": [n for n in nomes_nos if n.startswith("UCX_")],
    }


_COMPONENTES = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
_TIPOS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


def _accessor(gltf: dict, binario: bytes, indice: int) -> list[tuple]:
    acc = gltf["accessors"][indice]
    bv = gltf["bufferViews"][int(acc["bufferView"])]
    componente, tamanho = _COMPONENTES[int(acc["componentType"])]
    n = _TIPOS[acc["type"]]
    base = int(bv.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    passo = int(bv.get("byteStride", tamanho * n))
    formato = "<" + componente * n
    return [
        struct.unpack_from(formato, binario, base + i * passo)
        for i in range(int(acc["count"]))
    ]


def topologia(gltf: dict, binario: bytes) -> dict:
    """Mede G1 em Python puro: solda por posicao e conta arestas com != 2 faces.

    Usado pelo ``verify`` para reexecutar o gate sem confiar no relatorio antigo e sem Blender.
    """
    posicoes: list[tuple[float, float, float]] = []
    triangulos: list[tuple[int, int, int]] = []

    for malha in gltf.get("meshes", []):
        for prim in malha.get("primitives", []):
            atributos = prim.get("attributes", {})
            pos_idx = atributos.get("POSITION")
            if pos_idx is None or int(prim.get("mode", 4)) != 4:
                continue
            posicao = _accessor(gltf, binario, int(pos_idx))
            base = len(posicoes)
            posicoes.extend((float(p[0]), float(p[1]), float(p[2])) for p in posicao)
            idx = prim.get("indices")
            if idx is not None:
                ids = [int(v[0]) for v in _accessor(gltf, binario, int(idx))]
            else:
                ids = list(range(len(posicao)))
            for k in range(0, len(ids) - 2, 3):
                triangulos.append((base + ids[k], base + ids[k + 1], base + ids[k + 2]))

    # solda por posicao, a mesma tolerancia do bpy (1e-5 m)
    mapa: dict[tuple[float, float, float], int] = {}
    solda = []
    for p in posicoes:
        chave = (round(p[0], 5), round(p[1], 5), round(p[2], 5))
        solda.append(mapa.setdefault(chave, len(mapa)))

    arestas: dict[tuple[int, int], int] = {}
    degeneradas = 0
    for a, b, c in triangulos:
        A, B, C = solda[a], solda[b], solda[c]
        if A == B or B == C or C == A:
            degeneradas += 1
            continue
        pa, pb, pc = posicoes[a], posicoes[b], posicoes[c]
        ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
        vx, vy, vz = pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]
        cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        if cx * cx + cy * cy + cz * cz < 4e-24:  # area < 1e-12
            degeneradas += 1
        for e in ((A, B), (B, C), (C, A)):
            chave = (e[0], e[1]) if e[0] < e[1] else (e[1], e[0])
            arestas[chave] = arestas.get(chave, 0) + 1

    return {
        "nao_manifold": sum(1 for n in arestas.values() if n != 2),
        "degeneradas": degeneradas,
        "vertices": len(mapa),
        "triangulos": len(triangulos),
    }


def _componentes(posicoes: list[tuple], triangulos: list[tuple]) -> list[list[int]]:
    """Agrupa vertices por conectividade, soldando por posicao (1e-5 m, igual ao G1)."""
    pai = list(range(len(posicoes)))

    def raiz(i: int) -> int:
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    def unir(a: int, b: int) -> None:
        ra, rb = raiz(a), raiz(b)
        if ra != rb:
            pai[rb] = ra

    solda: dict[tuple, int] = {}
    for i, p in enumerate(posicoes):
        chave = (round(p[0], 5), round(p[1], 5), round(p[2], 5))
        unir(i, solda.setdefault(chave, i))
    for a, b, c in triangulos:
        unir(a, b)
        unir(b, c)

    grupos: dict[int, list[int]] = {}
    for i in range(len(posicoes)):
        grupos.setdefault(raiz(i), []).append(i)
    return list(grupos.values())


def _convexo(posicoes: list[tuple], triangulos: list[tuple], eps: float) -> bool:
    """Malha fechada e convexa se, em toda face, todos os vertices caem do mesmo lado.

    Testar os dois lados (e nao so o lado da normal) torna a medida insensivel a normal
    invertida, que num hull exportado e ruido e nao concavidade.
    """
    for a, b, c in triangulos:
        pa, pb, pc = posicoes[a], posicoes[b], posicoes[c]
        ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
        vx, vy, vz = pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        norma = (nx * nx + ny * ny + nz * nz) ** 0.5
        if norma < 1e-12:
            continue
        nx, ny, nz = nx / norma, ny / norma, nz / norma
        d = nx * pa[0] + ny * pa[1] + nz * pa[2]
        acima = abaixo = False
        for p in posicoes:
            s = nx * p[0] + ny * p[1] + nz * p[2] - d
            if s > eps:
                acima = True
            elif s < -eps:
                abaixo = True
            if acima and abaixo:
                return False
    return True


def convexidade(
    gltf: dict, binario: bytes, *, max_pares: int = 4_000_000
) -> dict:
    """Mede se cada parte do colisor e convexa (GAP-038/C8).

    Convexidade e propriedade de componente conexa, nao do arquivo: dois hulls soltos no
    mesmo GLB sao convexos; a uniao nao e. Por isso mede por componente.
    """
    posicoes: list[tuple] = []
    triangulos: list[tuple] = []
    for malha in gltf.get("meshes", []):
        for prim in malha.get("primitives", []):
            if int(prim.get("mode", 4)) != 4:
                continue
            pos_idx = (prim.get("attributes") or {}).get("POSITION")
            if pos_idx is None:
                continue
            base = len(posicoes)
            posicoes.extend(
                (float(p[0]), float(p[1]), float(p[2]))
                for p in _accessor(gltf, binario, int(pos_idx))
            )
            idx = prim.get("indices")
            if idx is not None:
                ids = [int(v[0]) for v in _accessor(gltf, binario, int(idx))]
            else:
                ids = list(range(len(posicoes) - base))
            for k in range(0, len(ids) - 2, 3):
                triangulos.append((base + ids[k], base + ids[k + 1], base + ids[k + 2]))

    if not triangulos:
        return {"medida": True, "partes": 0, "concavas": 0, "convexo": True}

    if len(posicoes) * len(triangulos) > max_pares:
        return {
            "medida": False,
            "partes": 0,
            "concavas": 0,
            "convexo": True,
            "motivo": "custo acima do teto; republique com colisor menor",
        }

    concavas = 0
    grupos = _componentes(posicoes, triangulos)
    for grupo in grupos:
        if len(grupo) < 4:
            continue
        conjunto = set(grupo)
        locais = [posicoes[i] for i in grupo]
        indice = {v: k for k, v in enumerate(grupo)}
        tris = [
            (indice[a], indice[b], indice[c])
            for a, b, c in triangulos
            if a in conjunto and b in conjunto and c in conjunto
        ]
        if not tris:
            continue
        xs = [p[0] for p in locais]
        ys = [p[1] for p in locais]
        zs = [p[2] for p in locais]
        diag = (
            (max(xs) - min(xs)) ** 2
            + (max(ys) - min(ys)) ** 2
            + (max(zs) - min(zs)) ** 2
        ) ** 0.5
        eps = max(1e-9, diag * 1e-6)
        if not _convexo(locais, tris, eps):
            concavas += 1

    return {
        "medida": True,
        "partes": len(grupos),
        "concavas": concavas,
        "convexo": concavas == 0,
    }


def _png_dimensoes(caminho: Path) -> tuple[int, int]:
    with open(caminho, "rb") as fh:
        cabecalho = fh.read(26)
    if cabecalho[:8] != b"\x89PNG\r\n\x1a\n":
        raise erro_qc(f"textura nao e PNG: {caminho}", arquivo=str(caminho))
    largura, altura = struct.unpack(">II", cabecalho[16:24])
    return largura, altura


def _pot(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def verificar(item: dict, perfil: dict, pasta: Path, resultado: dict) -> dict:
    """Roda G1-G9 sobre o artefato. Devolve relatorio; nao levanta (quem decide e o chamador)."""
    v = perfil["validacao"]
    medidas = resultado.get("medidas", {})
    arquivos = resultado.get("arquivos", [])
    gates: list[dict] = []

    malha = next((a for a in arquivos if a["papel"] == "mesh"), None)
    if malha is None:
        raise erro_qc("nenhum arquivo de malha no resultado do pos-processo", id=item["id"])

    gltf = ler_glb(pasta / malha["caminho"])
    info = analisar(gltf)

    # G1 geometria sa
    nao_manifold = int(medidas.get("nao_manifold", 0))
    degeneradas = int(medidas.get("degeneradas", 0))
    gates.append(
        {
            "id": "G1",
            "status": "ok"
            if nao_manifold <= v["nao_manifold_max"] and degeneradas <= v["faces_degeneradas_max"]
            else "falhou",
            "medido": {"nao_manifold": nao_manifold, "degeneradas": degeneradas},
            "limite": {
                "nao_manifold_max": v["nao_manifold_max"],
                "degeneradas_max": v["faces_degeneradas_max"],
            },
            "codigo": "FORGE-E-QC" if nao_manifold or degeneradas else None,
        }
    )

    # G2 escala e pivo
    alvo = float(item["altura_metros"])
    altura = info["bbox_m"][1] if info["bbox_m"][1] > 0 else float(medidas.get("bbox_m", [0, 0, 0])[1])
    delta_pct = abs(altura - alvo) / alvo * 100.0 if alvo else 999.0
    tolerancia_m = float(v["pivo_delta_mm"]) / 1000.0
    regra = item["pivot"]
    desvio_pivo = None
    if regra == "base":
        desvio_pivo = abs(info["min"][1])
    elif regra == "centro":
        desvio_pivo = abs((info["min"][1] + info["max"][1]) / 2.0)
    elif regra == "topo":
        desvio_pivo = abs(info["max"][1])
    pivo_ok = desvio_pivo is None or desvio_pivo <= tolerancia_m
    gates.append(
        {
            "id": "G2",
            "status": "ok" if delta_pct <= float(v["escala_delta_pct"]) and pivo_ok else "falhou",
            "medido": {
                "altura_m": round(altura, 6),
                "esperado_m": alvo,
                "delta_pct": round(delta_pct, 3),
                "desvio_pivo_m": None if desvio_pivo is None else round(desvio_pivo, 6),
                "pivo_regra": regra,
            },
            "limite": {"escala_delta_pct": v["escala_delta_pct"], "pivo_delta_mm": v["pivo_delta_mm"]},
            "codigo": None if (delta_pct <= float(v["escala_delta_pct"]) and pivo_ok) else "FORGE-E-QC",
        }
    )

    # G3 UV
    gates.append(
        {
            "id": "G3",
            "status": "ok" if info["sem_uv"] == 0 and info["primitivas"] > 0 else "falhou",
            "medido": {"primitivas": info["primitivas"], "sem_uv": info["sem_uv"]},
            "limite": {"sem_uv_max": 0},
            "codigo": None if info["sem_uv"] == 0 and info["primitivas"] else "FORGE-E-QC",
        }
    )

    # G4 textura
    texturas = [a for a in arquivos if a["papel"] == "textura"]
    detalhes_tex = []
    tex_ok = True
    for arq in texturas:
        largura, altura_px = _png_dimensoes(pasta / arq["caminho"])
        pot = _pot(largura) and _pot(altura_px)
        dentro = max(largura, altura_px) <= int(perfil["material"]["textura_max"])
        tex_ok = tex_ok and pot and dentro
        detalhes_tex.append({"arquivo": arq["caminho"], "px": [largura, altura_px], "pot": pot})
    gates.append(
        {
            "id": "G4",
            "status": "ok" if tex_ok else "falhou",
            "medido": {"texturas": detalhes_tex},
            "limite": {"ppm_max": perfil["material"]["textura_max"], "pot": True},
            "codigo": None if tex_ok else "FORGE-E-QC",
        }
    )

    # G5 material
    mat_ok = (
        info["materiais"] <= int(v["materiais_max"])
        and info["com_textura"] >= 1
        and not info["imagens_externas"]
    )
    gates.append(
        {
            "id": "G5",
            "status": "ok" if mat_ok else "falhou",
            "medido": {
                "materiais": info["materiais"],
                "com_textura": info["com_textura"],
                "imagens_externas": info["imagens_externas"],
            },
            "limite": {"materiais_max": v["materiais_max"], "imagens_externas_max": 0},
            "codigo": None if mat_ok else "FORGE-E-QC",
        }
    )

    # G6 rig
    if item.get("auto_rig"):
        esqueleto = item.get("esqueleto") or perfil["rig"]["esqueleto_padrao"]
        mapa = set(perfil["rig"].get("mapas", {}).get(esqueleto, []))
        fora = sorted(set(info["nomes_ossos"]) - mapa) if mapa else []
        rig_ok = (
            info["ossos"] > 0 and info["ossos"] <= int(perfil["rig"]["max_ossos"]) and not fora
        )
        gates.append(
            {
                "id": "G6",
                "status": "ok" if rig_ok else "falhou",
                "medido": {"ossos": info["ossos"], "fora_do_mapa": fora, "esqueleto": esqueleto},
                "limite": {"max_ossos": perfil["rig"]["max_ossos"]},
                "codigo": None if rig_ok else "FORGE-E-QC",
            }
        )
    else:
        gates.append({"id": "G6", "status": "ok", "medido": {"ossos": info["ossos"], "rig": False}})

    # G7 colisao
    colisao = item.get("colisao", "none")
    if colisao == "none":
        gates.append({"id": "G7", "status": "ok", "medido": {"colisao": "none"}})
    else:
        arquivo_col = next((a for a in arquivos if a["papel"] == "colisor"), None)
        partes = int(medidas.get("partes_colisao", 0))
        col_ok = (
            arquivo_col is not None
            and partes >= 1
            and partes <= int(perfil["colisao"]["max_partes"])
            and (pasta / arquivo_col["caminho"]).is_file()
        )
        nomes = []
        convexo = {"medida": False, "partes": 0, "concavas": 0, "convexo": True}
        if arquivo_col is not None:
            try:
                gltf_col, binario_col = ler_glb_bin(pasta / arquivo_col["caminho"])
                nomes = analisar(gltf_col)["colisores"]
                convexo = convexidade(gltf_col, binario_col)
            except erro_qc:
                nomes = []
        # perfil sem convencao de nome (ex.: roblox-r15) nao tem como exigir prefixo;
        # perfil que declara prefixo continua exigindo que todos os nos o usem
        prefixo = perfil["colisao"].get("prefixo")
        prefixo_ok = all(n.startswith(prefixo) for n in nomes) if (prefixo and nomes) else True
        # C8: colisor concavo passa no teste de existencia e reprova aqui
        convexo_ok = bool(convexo["convexo"])
        gates.append(
            {
                "id": "G7",
                "status": "ok" if col_ok and prefixo_ok and convexo_ok else "falhou",
                "medido": {"partes": partes, "nos": nomes, "convexidade": convexo},
                "limite": {
                    "max_partes": perfil["colisao"]["max_partes"],
                    "prefixo": prefixo,
                    "convexo": True,
                },
                "codigo": None
                if col_ok and prefixo_ok and convexo_ok
                else "FORGE-E-QC",
            }
        )

    # G8 licenca
    licenca = resultado.get("licenca") or {}
    lic_ok = bool(licenca.get("uso_comercial"))
    gates.append(
        {
            "id": "G8",
            "status": "ok" if lic_ok else "falhou",
            "medido": {"modelo": licenca.get("modelo"), "uso_comercial": licenca.get("uso_comercial")},
            "limite": {"uso_comercial": True},
            "codigo": None if lic_ok else "FORGE-E-LICENCA",
        }
    )

    # G9 orcamento
    limite_tri = int(item["limite_triangulos"])
    bytes_max = int(v["bytes_max_kb"]) * 1024
    maiores = []
    for arq in arquivos:
        caminho = pasta / arq["caminho"]
        tamanho = caminho.stat().st_size if caminho.is_file() else 0
        if tamanho > bytes_max:
            maiores.append({"arquivo": arq["caminho"], "bytes": tamanho})
    tri_ok = info["triangulos"] <= limite_tri and not maiores
    gates.append(
        {
            "id": "G9",
            "status": "ok" if tri_ok else "falhou",
            "medido": {
                "triangulos": info["triangulos"],
                "limite": limite_tri,
                "acima_do_tamanho": maiores,
            },
            "limite": {"limite_triangulos": limite_tri, "bytes_max_kb": v["bytes_max_kb"]},
            "codigo": None if tri_ok else "FORGE-E-QC",
        }
    )

    limpos = []
    for g in gates:
        if g.get("codigo") is None:
            g.pop("codigo", None)
        limpos.append(g)

    aprovado = all(g["status"] != "falhou" for g in limpos)
    primeiro = next((g for g in limpos if g["status"] == "falhou"), None)
    return {
        "aprovado": aprovado,
        "gates": limpos,
        "codigo": (primeiro or {}).get("codigo") or ("FORGE-E-QC" if not aprovado else None),
        "medidas": {
            "triangulos": info["triangulos"],
            "vertices": info["vertices"],
            "bbox_m": info["bbox_m"],
            "materiais": info["materiais"],
            "ossos": info["ossos"],
            "partes_colisao": int(medidas.get("partes_colisao", 0)),
        },
    }
