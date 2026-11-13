"""QC — portao duro entre "gerou" e "entrou no jogo" (D9, I5).

Mede o **arquivo exportado**, nao a intencao. Leitura do GLB e feita aqui, de proposito: se o
pipeline mentir sobre o que escreveu, o QC descobre.
"""

from __future__ import annotations

import base64
import io
import json
import math
import struct
import zlib
from pathlib import Path

from PIL import Image, ImageDraw

from .errors import ForgeError, erro_qc
from .profiles import FRACAO_EMPUNHADURA

__all__ = [
    "ler_glb",
    "ler_glb_bin",
    "analisar",
    "topologia",
    "convexidade",
    "verificar",
    "GATES",
    "PAPEIS_TEXTURA",
]

GATES = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10")
PAPEIS_TEXTURA = (
    "textura",
    "basecolor",
    "albedo",
    "normal",
    "orm",
    "metallic",
    "roughness",
    "emissive",
)
_MAGIC = 0x46546C67  # "glTF"
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942  # "BIN\0"


def _mat4_identidade() -> list[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _mat4_mul(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * 16
    for r in range(4):
        r4 = r * 4
        for c in range(4):
            out[r4 + c] = (
                a[r4] * b[c]
                + a[r4 + 1] * b[4 + c]
                + a[r4 + 2] * b[8 + c]
                + a[r4 + 3] * b[12 + c]
            )
    return out


def _mat4_det3(m: list[float]) -> float:
    return (
        m[0] * (m[5] * m[10] - m[6] * m[9])
        - m[1] * (m[4] * m[10] - m[6] * m[8])
        + m[2] * (m[4] * m[9] - m[5] * m[8])
    )


def _mat4_de_no(no: dict) -> list[float]:
    mat = no.get("matrix")
    if isinstance(mat, list) and len(mat) == 16:
        cm = [float(v) for v in mat]
        return [
            cm[0], cm[4], cm[8], cm[12],
            cm[1], cm[5], cm[9], cm[13],
            cm[2], cm[6], cm[10], cm[14],
            cm[3], cm[7], cm[11], cm[15],
        ]
    t = no.get("translation") or [0.0, 0.0, 0.0]
    r = no.get("rotation") or [0.0, 0.0, 0.0, 1.0]
    s = no.get("scale") or [1.0, 1.0, 1.0]
    tx, ty, tz = float(t[0]), float(t[1]), float(t[2])
    qx, qy, qz, qw = float(r[0]), float(r[1]), float(r[2]), float(r[3])
    sx, sy, sz = float(s[0]), float(s[1]), float(s[2])
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if norm > 1e-12:
        qx, qy, qz, qw = qx / norm, qy / norm, qz / norm, qw / norm
    else:
        qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0
    r00 = 1.0 - 2.0 * (qy * qy + qz * qz)
    r01 = 2.0 * (qx * qy - qz * qw)
    r02 = 2.0 * (qx * qz + qy * qw)
    r10 = 2.0 * (qx * qy + qz * qw)
    r11 = 1.0 - 2.0 * (qx * qx + qz * qz)
    r12 = 2.0 * (qy * qz - qx * qw)
    r20 = 2.0 * (qx * qz - qy * qw)
    r21 = 2.0 * (qy * qz + qx * qw)
    r22 = 1.0 - 2.0 * (qx * qx + qy * qy)
    return [
        r00 * sx, r01 * sy, r02 * sz, tx,
        r10 * sx, r11 * sy, r12 * sz, ty,
        r20 * sx, r21 * sy, r22 * sz, tz,
        0.0, 0.0, 0.0, 1.0,
    ]


def _matrizes_mundo_nos(gltf: dict) -> dict[int, list[float]]:
    nodes = gltf.get("nodes", [])
    if not nodes:
        return {}
    mundos: dict[int, list[float]] = {}
    visitados: set[int] = set()

    def _descer(idx: int, pai_mat: list[float]) -> None:
        if idx in visitados or idx < 0 or idx >= len(nodes):
            return
        visitados.add(idx)
        mat = _mat4_mul(pai_mat, _mat4_de_no(nodes[idx]))
        mundos[idx] = mat
        for filho in nodes[idx].get("children", []) or []:
            if isinstance(filho, int):
                _descer(filho, mat)

    ident = _mat4_identidade()
    scenes = gltf.get("scenes", [])
    if isinstance(scenes, list) and scenes:
        scene_idx = gltf.get("scene", 0)
        if not isinstance(scene_idx, int) or scene_idx < 0 or scene_idx >= len(scenes):
            scene_idx = 0
        for raiz in scenes[scene_idx].get("nodes", []) or []:
            if isinstance(raiz, int):
                _descer(raiz, ident)

    tem_pai = {
        filho
        for no in nodes
        for filho in (no.get("children") or [])
        if isinstance(filho, int)
    }
    for idx in range(len(nodes)):
        if idx not in tem_pai and idx not in visitados:
            _descer(idx, ident)
    for idx in range(len(nodes)):
        if idx not in visitados:
            _descer(idx, ident)
    return mundos


def _aplicar_mat4(m: list[float], p: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = p
    return (
        m[0] * x + m[1] * y + m[2] * z + m[3],
        m[4] * x + m[5] * y + m[6] * z + m[7],
        m[8] * x + m[9] * y + m[10] * z + m[11],
    )


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


def analisar(gltf: dict, binario: bytes | None = None) -> dict:
    """Extrai o que o QC precisa sem confiar no produtor."""
    accessors = gltf.get("accessors", [])
    nodes = gltf.get("nodes", [])
    meshes = gltf.get("meshes", [])
    materials = gltf.get("materials", [])

    mundos = _matrizes_mundo_nos(gltf)
    mesh_instancias: list[tuple[dict, list[float]]] = [
        (meshes[int(no["mesh"])], mundos.get(idx, _mat4_identidade()))
        for idx, no in enumerate(nodes)
        if "mesh" in no and isinstance(no["mesh"], int) and 0 <= no["mesh"] < len(meshes)
    ]
    if not mesh_instancias:
        ident = _mat4_identidade()
        mesh_instancias = [(m, ident) for m in meshes]

    triangulos = 0
    vertices = 0
    primitivas = 0
    sem_uv = 0
    com_color_0 = 0
    sem_tangent_normal = 0
    materiais_com_color_0: set[int] = set()
    prim_tris: list[int] = []
    minimos = [float("inf")] * 3
    maximos = [float("-inf")] * 3

    for malha_obj, mat_mundo in mesh_instancias:
        for prim in malha_obj.get("primitives", []):
            primitivas += 1
            modo = prim.get("mode", 4)
            atributos = prim.get("attributes", {})
            if "TEXCOORD_0" not in atributos:
                sem_uv += 1
            mat_idx = prim.get("material")
            mat_obj: dict | None = None
            if mat_idx is not None and 0 <= int(mat_idx) < len(materials):
                mat_obj = materials[int(mat_idx)]
            elif len(materials) == 1:
                mat_obj = materials[0]
            if modo == 4 and mat_obj and mat_obj.get("normalTexture") and "TANGENT" not in atributos:
                sem_tangent_normal += 1
            if "COLOR_0" in atributos:
                com_color_0 += 1
                if mat_idx is not None:
                    materiais_com_color_0.add(int(mat_idx))
                elif len(materials) == 1:
                    materiais_com_color_0.add(0)
            pos = atributos.get("POSITION")
            if pos is not None and pos < len(accessors):
                acc = accessors[pos]
                vertices += int(acc.get("count", 0))
                if acc.get("min") and acc.get("max"):
                    mn = [float(v) for v in acc["min"][:3]]
                    mx = [float(v) for v in acc["max"][:3]]
                    for cx in (mn[0], mx[0]):
                        for cy in (mn[1], mx[1]):
                            for cz in (mn[2], mx[2]):
                                tx, ty, tz = _aplicar_mat4(mat_mundo, (cx, cy, cz))
                                minimos[0] = min(minimos[0], tx)
                                minimos[1] = min(minimos[1], ty)
                                minimos[2] = min(minimos[2], tz)
                                maximos[0] = max(maximos[0], tx)
                                maximos[1] = max(maximos[1], ty)
                                maximos[2] = max(maximos[2], tz)
            indices = prim.get("indices")
            if modo != 4:
                continue
            tris_prim = 0
            if indices is not None and indices < len(accessors):
                tris_prim = int(accessors[indices].get("count", 0)) // 3
            elif pos is not None and pos < len(accessors):
                tris_prim = int(accessors[pos].get("count", 0)) // 3
            triangulos += tris_prim
            prim_tris.append(tris_prim)

    if binario is not None and meshes:
        try:
            pos_mundo, _ = malha(gltf, binario)
        except (KeyError, IndexError, struct.error):
            pos_mundo = []
        if pos_mundo:
            minimos = [min(p[i] for p in pos_mundo) for i in range(3)]
            maximos = [max(p[i] for p in pos_mundo) for i in range(3)]

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

    com_textura = sum(
        1 for m in materials if (m.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
    )
    materiais_validos = sum(
        1
        for idx, m in enumerate(materials)
        if (m.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
        or "baseColorFactor" in (m.get("pbrMetallicRoughness") or {})
        or idx in materiais_com_color_0
    )

    return {
        "triangulos": triangulos,
        "vertices": vertices,
        "primitivas": primitivas,
        "prim_tris": prim_tris,
        "sem_uv": sem_uv,
        "sem_tangent_normal": sem_tangent_normal,
        "com_color_0": com_color_0,
        "bbox_m": [round(v, 6) for v in bbox],
        "min": [round(v, 6) for v in minimos] if tem_bbox else [0, 0, 0],
        "max": [round(v, 6) for v in maximos] if tem_bbox else [0, 0, 0],
        "materiais": len(materials),
        "com_textura": com_textura,
        "materiais_validos": materiais_validos,
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


def malha(gltf: dict, binario: bytes) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Posicoes e triangulos do GLB no espaco de mundo (inclui matriz dos nos)."""
    posicoes: list[tuple[float, float, float]] = []
    triangulos: list[tuple[int, int, int]] = []
    mats_mundo = _matrizes_mundo_nos(gltf)
    malhas_gltf = gltf.get("meshes", [])
    instancias: list[tuple[list[float], dict]] = [
        (mats_mundo.get(idx_no, _mat4_identidade()), malhas_gltf[int(no["mesh"])])
        for idx_no, no in enumerate(gltf.get("nodes", []))
        if "mesh" in no and 0 <= int(no["mesh"]) < len(malhas_gltf)
    ]
    if not instancias:
        instancias = [(_mat4_identidade(), m) for m in malhas_gltf]

    for mat_mundo, malha_gltf in instancias:
        inverter = _mat4_det3(mat_mundo) < 0.0
        for prim in malha_gltf.get("primitives", []):
            atributos = prim.get("attributes", {})
            pos_idx = atributos.get("POSITION")
            if pos_idx is None or int(prim.get("mode", 4)) != 4:
                continue
            posicao = _accessor(gltf, binario, int(pos_idx))
            base = len(posicoes)
            posicoes.extend(
                _aplicar_mat4(mat_mundo, (float(p[0]), float(p[1]), float(p[2]))) for p in posicao
            )
            idx = prim.get("indices")
            if idx is not None:
                ids = [int(v[0]) for v in _accessor(gltf, binario, int(idx))]
            else:
                ids = list(range(len(posicao)))
            for k in range(0, len(ids) - 2, 3):
                if inverter:
                    triangulos.append((base + ids[k], base + ids[k + 2], base + ids[k + 1]))
                else:
                    triangulos.append((base + ids[k], base + ids[k + 1], base + ids[k + 2]))
    return posicoes, triangulos


def topologia(gltf: dict, binario: bytes) -> dict:
    """Mede G1 em Python puro: solda por posicao, arestas != 2 faces e cascas invertidas."""
    posicoes, triangulos = malha(gltf, binario)

    # solda por posicao, a mesma tolerancia do bpy (1e-5 m)
    mapa: dict[tuple[float, float, float], int] = {}
    solda: list[int] = []
    pos_solda: list[tuple[float, float, float]] = []
    for p in posicoes:
        chave_pos = (round(p[0], 5), round(p[1], 5), round(p[2], 5))
        if chave_pos not in mapa:
            mapa[chave_pos] = len(mapa)
            pos_solda.append(p)
        solda.append(mapa[chave_pos])

    arestas: dict[tuple[int, int], int] = {}
    degeneradas = 0
    tris_validos: list[tuple[int, int, int, tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]] = []
    pai = list(range(len(mapa)))

    def _raiz(i: int) -> int:
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    def _unir(x: int, y: int) -> None:
        rx, ry = _raiz(x), _raiz(y)
        if rx != ry:
            pai[ry] = rx

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
            chave_aresta: tuple[int, int] = (e[0], e[1]) if e[0] < e[1] else (e[1], e[0])
            arestas[chave_aresta] = arestas.get(chave_aresta, 0) + 1
        _unir(A, B)
        _unir(B, C)
        tris_validos.append((A, B, C, pa, pb, pc))

    por_comp: dict[int, list[tuple[int, int, int, tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]]] = {}
    for tri in tris_validos:
        por_comp.setdefault(_raiz(tri[0]), []).append(tri)

    cascas: list[tuple[float, list[float], list[float]]] = []
    for ctris in por_comp.values():
        if len(ctris) < 4:
            continue
        arestas_comp: dict[tuple[int, int], int] = {}
        verts_comp: set[int] = set()
        for A, B, C, _pa, _pb, _pc in ctris:
            verts_comp.update((A, B, C))
            for e in ((A, B), (B, C), (C, A)):
                ch: tuple[int, int] = (e[0], e[1]) if e[0] < e[1] else (e[1], e[0])
                arestas_comp[ch] = arestas_comp.get(ch, 0) + 1
        if not arestas_comp or any(n != 2 for n in arestas_comp.values()):
            continue
        pts = [pos_solda[idx] for idx in verts_comp]
        npts = float(len(pts))
        cx = sum(p[0] for p in pts) / npts
        cy = sum(p[1] for p in pts) / npts
        cz = sum(p[2] for p in pts) / npts
        vol = 0.0
        for _A, _B, _C, pa, pb, pc in ctris:
            ax, ay, az = pa[0] - cx, pa[1] - cy, pa[2] - cz
            bx, by, bz = pb[0] - cx, pb[1] - cy, pb[2] - cz
            px, py, pz = pc[0] - cx, pc[1] - cy, pc[2] - cz
            vol += (
                ax * (by * pz - bz * py)
                + ay * (bz * px - bx * pz)
                + az * (bx * py - by * px)
            ) / 6.0
        cmin = [min(p[d] for p in pts) for d in range(3)]
        cmax = [max(p[d] for p in pts) for d in range(3)]
        cascas.append((vol, cmin, cmax))

    invertidas = 0
    for vol_in, mn_in, mx_in in cascas:
        if vol_in >= -1e-9:
            continue
        cavidade = any(
            vol_out > 1e-9
            and vol_out > abs(vol_in) * 1.05
            and all(mn_in[d] >= mn_out[d] - 1e-5 and mx_in[d] <= mx_out[d] + 1e-5 for d in range(3))
            for vol_out, mn_out, mx_out in cascas
        )
        if not cavidade:
            invertidas += 1

    return {
        "nao_manifold": sum(1 for n in arestas.values() if n != 2),
        "degeneradas": degeneradas,
        "invertidas": invertidas,
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
    mesmo GLB sao convexos; a uniao nao e. Rejeita tambem malhas vazias ou coplanares.
    """
    pos_brutas, tris_brutos = malha(gltf, binario)
    if not tris_brutos:
        return {"medida": True, "partes": 0, "concavas": 0, "degeneradas": 1, "convexo": False}

    mapa: dict[tuple[float, float, float], int] = {}
    posicoes: list[tuple[float, float, float]] = []
    solda: list[int] = []
    for p in pos_brutas:
        chave = (round(p[0], 5), round(p[1], 5), round(p[2], 5))
        idx = mapa.get(chave)
        if idx is None:
            idx = len(posicoes)
            mapa[chave] = idx
            posicoes.append(p)
        solda.append(idx)
    triangulos = [
        (solda[a], solda[b], solda[c])
        for a, b, c in tris_brutos
        if solda[a] != solda[b] and solda[b] != solda[c] and solda[c] != solda[a]
    ]
    if not triangulos:
        return {"medida": True, "partes": 0, "concavas": 0, "degeneradas": 1, "convexo": False}

    if len(posicoes) * len(triangulos) > max_pares:
        return {
            "medida": False,
            "partes": 0,
            "concavas": 0,
            "degeneradas": 0,
            "convexo": False,
            "motivo": "custo acima do teto; republique com colisor menor",
        }

    concavas = 0
    degeneradas = 0
    grupos = _componentes(posicoes, triangulos)
    for grupo in grupos:
        conjunto = set(grupo)
        locais = [posicoes[i] for i in grupo]
        indice = {v: k for k, v in enumerate(grupo)}
        tris = [
            (indice[a], indice[b], indice[c])
            for a, b, c in triangulos
            if a in conjunto and b in conjunto and c in conjunto
        ]
        if len(grupo) < 4 or len(tris) < 4:
            degeneradas += 1
            continue
        xs = [p[0] for p in locais]
        ys = [p[1] for p in locais]
        zs = [p[2] for p in locais]
        diag = (
            (max(xs) - min(xs)) ** 2
            + (max(ys) - min(ys)) ** 2
            + (max(zs) - min(zs)) ** 2
        ) ** 0.5
        normal_ref: tuple[float, float, float] | None = None
        origem_ref: tuple[float, float, float] | None = None
        for a, b, c in tris:
            pa, pb, pc = locais[a], locais[b], locais[c]
            ux, uy, uz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
            vx, vy, vz = pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            norma = (nx * nx + ny * ny + nz * nz) ** 0.5
            if norma >= 1e-12:
                normal_ref = (nx / norma, ny / norma, nz / norma)
                origem_ref = pa
                break
        if normal_ref is None or origem_ref is None:
            degeneradas += 1
            continue
        nx, ny, nz = normal_ref
        d_plano = nx * origem_ref[0] + ny * origem_ref[1] + nz * origem_ref[2]
        max_dist = max(abs(nx * p[0] + ny * p[1] + nz * p[2] - d_plano) for p in locais)
        if max_dist <= max(1e-6, diag * 1e-4):
            degeneradas += 1
            continue
        # D65: tolerancia de 1 mm por metro de diametro.
        eps = max(1e-9, diag * 1e-3)
        if not _convexo(locais, tris, eps):
            concavas += 1

    return {
        "medida": True,
        "partes": len(grupos),
        "concavas": concavas,
        "degeneradas": degeneradas,
        "convexo": concavas == 0 and degeneradas == 0 and len(grupos) >= 1,
    }


def _validar_bytes_imagem(dados: bytes) -> tuple[int, int] | None:
    if not dados:
        return None
    if len(dados) >= 8 and dados[:8] == b"\x89PNG\r\n\x1a\n":
        pos = 8
        primeiro_chunk = True
        viu_iend = False
        while pos + 12 <= len(dados):
            tam = struct.unpack(">I", dados[pos : pos + 4])[0]
            tipo = dados[pos + 4 : pos + 8]
            if pos + 12 + tam > len(dados):
                return None
            if primeiro_chunk and (tipo != b"IHDR" or tam < 13):
                return None
            primeiro_chunk = False
            crc_lido = struct.unpack(">I", dados[pos + 8 + tam : pos + 12 + tam])[0]
            if (zlib.crc32(dados[pos + 4 : pos + 8 + tam]) & 0xFFFFFFFF) != crc_lido:
                return None
            pos += 12 + tam
            if tipo == b"IEND":
                viu_iend = True
                break
        if not viu_iend:
            return None
    elif not (
        (len(dados) >= 2 and dados[:2] == b"\xff\xd8")
        or (len(dados) >= 12 and dados[:4] == b"RIFF" and dados[8:12] == b"WEBP")
    ):
        return None
    try:
        with Image.open(io.BytesIO(dados)) as im:
            largura, altura = im.size
            im.verify()
    except Exception:  # noqa: BLE001 - binario de imagem corrompido
        return None
    if largura <= 0 or altura <= 0:
        return None
    return int(largura), int(altura)


_dimensoes_bytes_imagem = _validar_bytes_imagem


def _png_dimensoes(caminho: Path) -> tuple[int, int]:
    dims = _validar_bytes_imagem(Path(caminho).read_bytes())
    if dims is None:
        raise erro_qc(f"textura invalida ou nao PNG/JPEG/WEBP: {caminho}", arquivo=str(caminho))
    return dims


def _imagens_embutidas(gltf: dict, binario: bytes, textura_max: int) -> list[dict[str, object]]:
    vistas = gltf.get("bufferViews", [])
    resultado: list[dict[str, object]] = []
    for idx, im in enumerate(gltf.get("images", [])):
        dados = b""
        if "bufferView" in im and int(im["bufferView"]) < len(vistas):
            bv = vistas[int(im["bufferView"])]
            off = int(bv.get("byteOffset", 0))
            tam = int(bv.get("byteLength", 0))
            dados = binario[off : off + tam]
        elif isinstance(im.get("uri"), str) and im["uri"].startswith("data:"):
            partes = im["uri"].split(",", 1)
            if len(partes) == 2 and ";base64" in partes[0]:
                try:
                    dados = base64.b64decode(partes[1])
                except ValueError:
                    dados = b""
        dims = _validar_bytes_imagem(dados)
        if dims is None:
            resultado.append({"indice": idx, "px": None, "pot": False, "valida": False})
            continue
        w, h = dims
        pot = _pot(w) and _pot(h)
        resultado.append(
            {
                "indice": idx,
                "px": [w, h],
                "pot": pot,
                "valida": pot and max(w, h) <= textura_max,
            }
        )
    return resultado


def _uv_status(gltf: dict, binario: bytes, *, permitir_tiling: bool = False) -> dict:
    fora = 0
    total = 0
    uv_colapsada = 0
    uv_min = -16.0 - 1e-4 if permitir_tiling else -1e-4
    uv_max = 16.0 + 1e-4 if permitir_tiling else 1.0 + 1e-4
    acessores = gltf.get("accessors", [])
    materiais = gltf.get("materials", [])
    for malha_gltf in gltf.get("meshes", []):
        for prim in malha_gltf.get("primitives", []):
            ti = (prim.get("attributes") or {}).get("TEXCOORD_0")
            if ti is None or int(ti) >= len(acessores):
                continue
            acc = acessores[int(ti)]
            if "bufferView" not in acc:
                continue
            comp = int(acc.get("componentType", 5126))
            norm = bool(acc.get("normalized", False))
            escala_uv = 1.0
            if norm and comp == 5121:
                escala_uv = 1.0 / 255.0
            elif norm and comp == 5123:
                escala_uv = 1.0 / 65535.0
            coords_uv: list[tuple[float, float]] = []
            for u_raw, v_raw in _accessor(gltf, binario, int(ti)):
                u = float(u_raw) * escala_uv
                v = float(v_raw) * escala_uv
                coords_uv.append((u, v))
                total += 1
                if (
                    not math.isfinite(u)
                    or not math.isfinite(v)
                    or u < uv_min
                    or u > uv_max
                    or v < uv_min
                    or v > uv_max
                ):
                    fora += 1
            mat_idx = prim.get("material")
            mat_obj: dict | None = None
            if mat_idx is not None and 0 <= int(mat_idx) < len(materiais):
                mat_obj = materiais[int(mat_idx)]
            elif len(materiais) == 1:
                mat_obj = materiais[0]
            base_tex = ((mat_obj or {}).get("pbrMetallicRoughness") or {}).get("baseColorTexture")
            if int(prim.get("mode", 4)) == 4 and isinstance(base_tex, dict) and coords_uv:
                idx_acc = prim.get("indices")
                if idx_acc is not None and int(idx_acc) < len(acessores):
                    ids = [int(v[0]) for v in _accessor(gltf, binario, int(idx_acc))]
                else:
                    ids = list(range(len(coords_uv)))
                if len(ids) >= 3:
                    area_uv = 0.0
                    for k in range(0, len(ids) - 2, 3):
                        i0, i1, i2 = ids[k], ids[k + 1], ids[k + 2]
                        if i0 < len(coords_uv) and i1 < len(coords_uv) and i2 < len(coords_uv):
                            u0, v0 = coords_uv[i0]
                            u1, v1 = coords_uv[i1]
                            u2, v2 = coords_uv[i2]
                            area_uv += 0.5 * abs((u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0))
                    if area_uv < 1e-8:
                        uv_colapsada += 1
    return {"total_uv": total, "fora_intervalo": fora, "uv_colapsada": uv_colapsada}


def _skin_status(gltf: dict, binario: bytes) -> dict:
    skins = gltf.get("skins", [])
    meshes = gltf.get("meshes", [])
    acessores = gltf.get("accessors", [])
    if not skins or not meshes:
        return {
            "ok": True,
            "primitivas_skinned": 0,
            "sem_atributos": 0,
            "joints_invalidos": 0,
            "pesos_invalidos": 0,
        }

    pares_skinned: list[tuple[dict, int]] = []
    for no in gltf.get("nodes", []):
        if "skin" in no and "mesh" in no:
            s_idx = int(no["skin"])
            m_idx = int(no["mesh"])
            if 0 <= s_idx < len(skins) and 0 <= m_idx < len(meshes):
                pares_skinned.append((meshes[m_idx], len(skins[s_idx].get("joints", []))))
    if not pares_skinned:
        num_joints_0 = len(skins[0].get("joints", []))
        pares_skinned = [(m, num_joints_0) for m in meshes]

    prims_skinned = 0
    sem_atributos = 0
    joints_invalidos = 0
    pesos_invalidos = 0
    for malha_gltf, num_joints in pares_skinned:
        for prim in malha_gltf.get("primitives", []):
            if int(prim.get("mode", 4)) != 4:
                continue
            prims_skinned += 1
            atributos = prim.get("attributes", {})
            j_idx = atributos.get("JOINTS_0")
            w_idx = atributos.get("WEIGHTS_0")
            if (
                j_idx is None
                or w_idx is None
                or int(j_idx) >= len(acessores)
                or int(w_idx) >= len(acessores)
            ):
                sem_atributos += 1
                continue
            acc_w = acessores[int(w_idx)]
            comp_w = int(acc_w.get("componentType", 5126))
            norm_w = bool(acc_w.get("normalized", False))
            escala_w = 1.0
            if norm_w and comp_w == 5121:
                escala_w = 1.0 / 255.0
            elif norm_w and comp_w == 5123:
                escala_w = 1.0 / 65535.0
            juntas = _accessor(gltf, binario, int(j_idx))
            pesos = _accessor(gltf, binario, int(w_idx))
            total_v = min(len(juntas), len(pesos))
            if total_v == 0:
                sem_atributos += 1
                continue
            validos = 0
            joint_ruim = False
            for j_vec, w_vec in zip(juntas[:total_v], pesos[:total_v]):
                wf = [float(x) * escala_w for x in w_vec]
                if any(not math.isfinite(x) or x < -1e-6 for x in wf):
                    continue
                soma = sum(wf)
                if 0.98 <= soma <= 1.02:
                    validos += 1
                for jv, wv in zip(j_vec, wf):
                    if wv > 1e-6 and (int(jv) < 0 or int(jv) >= num_joints):
                        joint_ruim = True
            if joint_ruim:
                joints_invalidos += 1
            if validos / float(total_v) < 0.99:
                pesos_invalidos += 1

    ok = sem_atributos == 0 and joints_invalidos == 0 and pesos_invalidos == 0
    return {
        "ok": ok,
        "primitivas_skinned": prims_skinned,
        "sem_atributos": sem_atributos,
        "joints_invalidos": joints_invalidos,
        "pesos_invalidos": pesos_invalidos,
    }


def _silhueta_iou_lod(
    pos0: list[tuple[float, float, float]],
    tris0: list[tuple[int, int, int]],
    pos_lod: list[tuple[float, float, float]],
    tris_lod: list[tuple[int, int, int]],
    tamanho: int = 128,
) -> float:
    todos = pos0 + pos_lod
    if not todos:
        return 0.0
    xs = [p[0] for p in todos]
    ys = [p[1] for p in todos]
    zs = [p[2] for p in todos]
    mn = (min(xs), min(ys), min(zs))
    mx = (max(xs), max(ys), max(zs))
    ext = max(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2], 1e-6)

    def _raster(
        pos: list[tuple[float, float, float]],
        tris: list[tuple[int, int, int]],
        eixo_u: int,
    ) -> list[int]:
        im = Image.new("L", (tamanho, tamanho), 0)
        draw = ImageDraw.Draw(im)
        margem = 4.0
        escala_px = (tamanho - 2.0 * margem) / ext
        for a, b, c in tris:
            pts = []
            for idx in (a, b, c):
                p = pos[idx]
                px = margem + (p[eixo_u] - mn[eixo_u]) * escala_px
                py = tamanho - 1.0 - margem - (p[1] - mn[1]) * escala_px
                pts.append((px, py))
            draw.polygon(pts, fill=255)
        return list(im.getdata())

    ious: list[float] = []
    for eixo in (0, 2):
        r0 = _raster(pos0, tris0, eixo)
        rl = _raster(pos_lod, tris_lod, eixo)
        inter = sum(1 for a, b in zip(r0, rl) if a > 0 and b > 0)
        uniao = sum(1 for a, b in zip(r0, rl) if a > 0 or b > 0)
        ious.append(inter / float(uniao) if uniao > 0 else 0.0)
    return min(ious)


def _pot(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def _desvio_pivo(regra: str, minimo_y: float, maximo_y: float) -> float | None:
    """Quanto o pivo aplicado desvia da regra declarada, em metros (D58).

    O export posiciona o objeto com a origem NO pivo, entao a regra e conferivel pela
    AABB resultante. Regra desconhecida devolve None — e o G2 nao mede.
    """
    altura = maximo_y - minimo_y
    if regra == "base":
        return abs(minimo_y)
    if regra == "centro":
        return abs((minimo_y + maximo_y) / 2.0)
    if regra == "topo":
        return abs(maximo_y)
    if regra == "empunhadura":
        return abs(minimo_y + FRACAO_EMPUNHADURA * altura)
    return None


def animacoes(gltf: dict, binario: bytes) -> list[dict]:
    """Le os clipes do glTF: nome, duracao em segundos e ossos efetivamente animados.

    Canal que nao aponta para um joint do skin e ignorado: o que interessa ao gate e motion de
    esqueleto, nao transform de objeto.
    """
    acessores = gltf.get("accessors", [])
    nos = gltf.get("nodes", [])
    skins = gltf.get("skins", [])
    ossos_do_rig: set[str] = set()
    if skins:
        ossos_do_rig = {
            nos[i].get("name", "")
            for i in skins[0].get("joints", [])
            if isinstance(i, int) and i < len(nos)
        }
    clipes: list[dict] = []
    for animacao in gltf.get("animations", []):
        duracao = 0.0
        ossos: set[str] = set()
        movendo: set[str] = set()
        canais = 0
        for canal in animacao.get("channels", []):
            alvo = canal.get("target") or {}
            indice = alvo.get("node")
            amostradores = animacao.get("samplers") or []
            amostrador = amostradores[int(canal.get("sampler", 0))] if amostradores else {}
            entrada = amostrador.get("input")
            if isinstance(entrada, int) and entrada < len(acessores):
                maximo = acessores[entrada].get("max")
                if maximo:
                    duracao = max(duracao, float(maximo[0]))
            nome = ""
            if isinstance(indice, int) and indice < len(nos):
                nome = nos[indice].get("name", "")
            if nome not in ossos_do_rig:
                continue
            ossos.add(nome)
            canais += 1
            # canal de rotacao existe sempre (o export amostra todos os ossos); o que
            # interessa ao gate e algum valor diferente da rotacao inicial.
            saida = amostrador.get("output")
            if alvo.get("path") == "rotation" and isinstance(saida, int) and saida < len(acessores):
                try:
                    valores = _accessor(gltf, binario, saida)
                except Exception:  # noqa: BLE001 - accessor de terceiro pode nao ser VEC4 float
                    valores = []
                if valores:
                    base = valores[0]
                    for valor in valores[1:]:
                        if any(abs(float(c) - float(b)) > 1e-5 for b, c in zip(base, valor)):
                            movendo.add(nome)
                            break
        clipes.append(
            {
                "nome": animacao.get("name") or f"anim{len(clipes)}",
                "duracao_s": round(duracao, 3),
                "ossos": sorted(ossos),
                "movendo": sorted(movendo),
                "canais": canais,
            }
        )
    return clipes


def escala_do_perfil(perfil: dict) -> float:
    """Fator entre metro e unidade do arquivo exportado (D62). Perfil sem o campo = 1.0."""
    valor = float((perfil.get("unidades") or {}).get("escala_saida", 1.0))
    if valor <= 0:
        raise erro_qc(f"perfil com escala_saida invalida: {valor}")
    return valor


def verificar(
    item: dict,
    perfil: dict,
    pasta: Path,
    resultado: dict,
    *,
    escala_saida: float | None = None,
    exigir_tangent_normal: bool = True,
) -> dict:
    """Roda G1-G10 sobre o artefato. Devolve relatorio; nao levanta (quem decide e o chamador).

    ``escala_saida`` sobrepoe o perfil: o ``verify`` de um manifesto reexecuta o gate com a escala
    DECLARADA no manifesto, nao com a que o perfil diz hoje.
    """
    v = perfil["validacao"]
    medidas = resultado.get("medidas", {})
    arquivos = resultado.get("arquivos", [])
    escala = float(escala_saida) if escala_saida is not None else escala_do_perfil(perfil)
    if escala <= 0:
        raise erro_qc(f"escala_saida invalida: {escala}")
    gates: list[dict] = []

    arq_malha = next((a for a in arquivos if a["papel"] == "mesh"), None)
    if arq_malha is None:
        raise erro_qc("nenhum arquivo de malha no resultado do pos-processo", id=item["id"])

    gltf, binario = ler_glb_bin(pasta / arq_malha["caminho"])
    info = analisar(gltf, binario)

    # G1 geometria sa — mede o GLB real em Python puro tambem no `run`, sem confiar so em medidas
    topo = (
        topologia(gltf, binario)
        if gltf.get("meshes")
        else {"nao_manifold": 0, "degeneradas": 0, "invertidas": 0}
    )
    nao_manifold = max(int(medidas.get("nao_manifold", 0)), int(topo["nao_manifold"]))
    degeneradas = max(int(medidas.get("degeneradas", 0)), int(topo["degeneradas"]))
    invertidas = int(topo.get("invertidas", 0))
    g1_ok = (
        nao_manifold <= int(v["nao_manifold_max"])
        and degeneradas <= int(v["faces_degeneradas_max"])
        and invertidas == 0
    )
    gates.append(
        {
            "id": "G1",
            "status": "ok" if g1_ok else "falhou",
            "medido": {
                "nao_manifold": nao_manifold,
                "degeneradas": degeneradas,
                "invertidas": invertidas,
            },
            "limite": {
                "nao_manifold_max": v["nao_manifold_max"],
                "degeneradas_max": v["faces_degeneradas_max"],
                "invertidas_max": 0,
            },
            "codigo": None if g1_ok else "FORGE-E-QC",
        }
    )

    # G2 escala e pivo — o GLB esta na unidade do arquivo (studs no roblox-r15); a comparacao
    # com `altura_metros` e em metros, entao divide pela escala declarada antes de medir (D62).
    alvo = float(item["altura_metros"])
    altura_export = info["bbox_m"][1]
    altura = (
        altura_export / escala
        if altura_export > 0
        else float(medidas.get("bbox_m", [0, 0, 0])[1])
    )
    raw_anexo = item.get("anexo")
    anexo_item: dict = raw_anexo if isinstance(raw_anexo, dict) else {}
    escala_preservada = bool(
        item.get("escala_preservada")
        or medidas.get("escala_preservada")
        or (
            bool(anexo_item.get("skinned"))
            and item.get("parte")
            and item.get("parte") != "corpo"
            and alvo >= 1.2
        )
    )
    delta_pct = abs(altura - alvo) / alvo * 100.0 if alvo else 999.0
    tolerancia_m = float(v["pivo_delta_mm"]) / 1000.0
    regra = item["pivot"]
    desvio_pivo = _desvio_pivo(regra, info["min"][1] / escala, info["max"][1] / escala)
    desvio_xz: float | None = None
    eh_equipavel = item.get("tipo") == "prop_equipavel" or item.get("parte") in ("arma", "escudo")
    checar_xz = regra == "centro" or (regra in ("base", "topo", "junta") and not eh_equipavel)
    if desvio_pivo is not None and gltf.get("meshes") and checar_xz:
        desvio_xz = max(
            abs((info["min"][0] + info["max"][0]) / 2.0),
            abs((info["min"][2] + info["max"][2]) / 2.0),
        ) / escala
        desvio_pivo = max(desvio_pivo, desvio_xz)
    if escala_preservada:
        escala_ok = (0.02 * alvo) <= altura <= (1.15 * alvo)
        pivo_ok = True
    else:
        escala_ok = delta_pct <= float(v["escala_delta_pct"])
        pivo_ok = desvio_pivo is None or desvio_pivo <= tolerancia_m
    medido_g2: dict = {
        "altura_m": round(altura, 6),
        "altura_export": round(altura_export, 6),
        "esperado_m": alvo,
        "delta_pct": round(delta_pct, 3),
        "desvio_pivo_m": None if desvio_pivo is None else round(desvio_pivo, 6),
        "pivo_regra": regra,
        "escala_saida": escala,
    }
    if escala_preservada:
        medido_g2["escala_preservada"] = True
    if desvio_xz is not None:
        medido_g2["desvio_xz_m"] = round(desvio_xz, 6)
    gates.append(
        {
            "id": "G2",
            "status": "ok" if escala_ok and pivo_ok else "falhou",
            "medido": medido_g2,
            "limite": {"escala_delta_pct": v["escala_delta_pct"], "pivo_delta_mm": v["pivo_delta_mm"]},
            "codigo": None if (escala_ok and pivo_ok) else "FORGE-E-QC",
        }
    )

    # G3 UV
    permitir_tiling = bool(
        item.get("permitir_tiling") or (perfil.get("material") or {}).get("permitir_tiling", False)
    )
    uv_info = (
        _uv_status(gltf, binario, permitir_tiling=permitir_tiling)
        if gltf.get("meshes")
        else {"total_uv": 0, "fora_intervalo": 0, "uv_colapsada": 0}
    )
    uv_ok = (
        info["sem_uv"] == 0
        and info["primitivas"] > 0
        and uv_info["fora_intervalo"] == 0
        and uv_info["uv_colapsada"] == 0
    )
    gates.append(
        {
            "id": "G3",
            "status": "ok" if uv_ok else "falhou",
            "medido": {
                "primitivas": info["primitivas"],
                "sem_uv": info["sem_uv"],
                "uv_fora_intervalo": uv_info["fora_intervalo"],
                "uv_colapsada": uv_info["uv_colapsada"],
                "permitir_tiling": permitir_tiling,
            },
            "limite": {"sem_uv_max": 0, "fora_intervalo_max": 0, "uv_colapsada_max": 0},
            "codigo": None if uv_ok else "FORGE-E-QC",
        }
    )

    # G4 textura (mede PNG/JPEG/WEBP irmaos E imagens embutidas no GLB)
    textura_max = int(perfil["material"]["textura_max"])
    if item.get("qualidade") == "hero":
        textura_max = max(textura_max, 2048)
    texturas = [a for a in arquivos if a.get("papel") in PAPEIS_TEXTURA]
    detalhes_tex = []
    tex_ok = True
    for arq in texturas:
        caminho_tex = pasta / arq["caminho"]
        dims = _validar_bytes_imagem(caminho_tex.read_bytes()) if caminho_tex.is_file() else None
        if dims is None:
            tex_ok = False
            detalhes_tex.append(
                {"arquivo": arq["caminho"], "papel": arq["papel"], "px": None, "pot": False, "valida": False}
            )
            continue
        largura, altura_px = dims
        pot = _pot(largura) and _pot(altura_px)
        dentro = max(largura, altura_px) <= textura_max
        valida_tex = pot and dentro
        tex_ok = tex_ok and valida_tex
        detalhes_tex.append(
            {"arquivo": arq["caminho"], "papel": arq["papel"], "px": [largura, altura_px], "pot": pot, "valida": valida_tex}
        )
    embutidas = _imagens_embutidas(gltf, binario, textura_max)
    for emb in embutidas:
        tex_ok = tex_ok and bool(emb["valida"])
    if gltf.get("meshes") and info["com_textura"] > 0 and not texturas and not embutidas:
        tex_ok = False
    gates.append(
        {
            "id": "G4",
            "status": "ok" if tex_ok else "falhou",
            "medido": {"texturas": detalhes_tex, "embutidas": embutidas},
            "limite": {"ppm_max": textura_max, "pot": True},
            "codigo": None if tex_ok else "FORGE-E-QC",
        }
    )

    # G5 material (aceita textura, baseColorFactor ou vertex color COLOR_0; exige TANGENT quando normalTexture presente)
    materiais_validos = int(info.get("materiais_validos", info["com_textura"]))
    sem_tangent_normal = int(info.get("sem_tangent_normal", 0))
    mat_ok = (
        info["materiais"] >= 1
        and info["materiais"] <= int(v["materiais_max"])
        and (materiais_validos == info["materiais"] or info["com_textura"] == info["materiais"])
        and not info["imagens_externas"]
        and (sem_tangent_normal == 0 or not exigir_tangent_normal)
    )
    gates.append(
        {
            "id": "G5",
            "status": "ok" if mat_ok else "falhou",
            "medido": {
                "materiais": info["materiais"],
                "com_textura": info["com_textura"],
                "imagens_externas": info["imagens_externas"],
                "sem_tangent_normal": sem_tangent_normal,
            },
            "limite": {
                "materiais_max": v["materiais_max"],
                "imagens_externas_max": 0,
                "sem_tangent_normal_max": 0 if exigir_tangent_normal else None,
            },
            "codigo": None if mat_ok else "FORGE-E-QC",
        }
    )

    # G6 rig (auto_rig ou anexo skinned; valida JOINTS_0 + WEIGHTS_0)
    eh_skinned = bool(item.get("auto_rig")) or bool(anexo_item.get("skinned"))
    if eh_skinned:
        esqueleto = item.get("esqueleto") or perfil["rig"]["esqueleto_padrao"]
        mapa = set(perfil["rig"].get("mapas", {}).get(esqueleto, []))
        presentes = set(info["nomes_ossos"])
        fora = sorted(presentes - mapa) if mapa else []
        faltando = sorted(mapa - presentes) if (mapa and item.get("auto_rig")) else []
        skin_info = _skin_status(gltf, binario)
        rig_ok = (
            info["ossos"] > 0
            and info["ossos"] <= int(perfil["rig"]["max_ossos"])
            and not fora
            and not faltando
            and bool(skin_info["ok"])
        )
        gates.append(
            {
                "id": "G6",
                "status": "ok" if rig_ok else "falhou",
                "medido": {
                    "ossos": info["ossos"],
                    "fora_do_mapa": fora,
                    "faltando_no_mapa": faltando,
                    "esqueleto": esqueleto,
                    "skin": skin_info,
                },
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
        partes_decl = int(medidas.get("partes_colisao", 0))
        nomes = []
        convexo = {"medida": False, "partes": 0, "concavas": 0, "degeneradas": 0, "convexo": False}
        dentro_da_aabb = True
        if arquivo_col is not None and (pasta / arquivo_col["caminho"]).is_file():
            try:
                gltf_col, binario_col = ler_glb_bin(pasta / arquivo_col["caminho"])
                nomes = [n.get("name", "") for n in gltf_col.get("nodes", []) if "mesh" in n]
                convexo = convexidade(gltf_col, binario_col)
                if gltf.get("meshes") and gltf_col.get("meshes"):
                    info_col = analisar(gltf_col, binario_col)
                    margem_aabb = max(0.05 * escala, 0.15 * max(info["bbox_m"] or [0.0]))
                    dentro_da_aabb = all(
                        info_col["min"][d] >= info["min"][d] - margem_aabb
                        and info_col["max"][d] <= info["max"][d] + margem_aabb
                        for d in range(3)
                    )
            except ForgeError:
                nomes = []
        partes = int(convexo["partes"]) if convexo.get("medida") and int(convexo["partes"]) > 0 else partes_decl
        col_ok = (
            arquivo_col is not None
            and partes >= 1
            and partes <= int(perfil["colisao"]["max_partes"])
            and (pasta / arquivo_col["caminho"]).is_file()
        )
        # perfil sem convencao de nome (ex.: roblox-r15) nao tem como exigir prefixo;
        # perfil que declara prefixo continua exigindo que todos os nos de malha o usem
        prefixo = perfil["colisao"].get("prefixo")
        prefixo_ok = bool(nomes) and all(n.startswith(prefixo) for n in nomes) if prefixo else True
        # C8: colisor concavo, degenerado ou fora da AABB reprova aqui
        convexo_ok = bool(convexo["convexo"]) and dentro_da_aabb
        gates.append(
            {
                "id": "G7",
                "status": "ok" if col_ok and prefixo_ok and convexo_ok else "falhou",
                "medido": {
                    "partes": partes,
                    "nos": nomes,
                    "convexidade": convexo,
                    "dentro_da_aabb": dentro_da_aabb,
                },
                "limite": {
                    "max_partes": perfil["colisao"]["max_partes"],
                    "prefixo": prefixo,
                    "convexo": True,
                },
                "codigo": None if col_ok and prefixo_ok and convexo_ok else "FORGE-E-QC",
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

    # G9 orcamento (inclui limites por parte/primitiva e validacao de LODs quando existirem)
    limite_tri = int(item["limite_triangulos"])
    bytes_max_kb = int(v["bytes_max_kb"])
    if item.get("qualidade") == "hero":
        bytes_max_kb = max(bytes_max_kb, 4096)
    bytes_max = bytes_max_kb * 1024
    maiores = []
    for arq in arquivos:
        caminho = pasta / arq["caminho"]
        tamanho = caminho.stat().st_size if caminho.is_file() else 0
        if tamanho > bytes_max:
            maiores.append({"arquivo": arq["caminho"], "bytes": tamanho})
    partes_max = v.get("partes_max")
    tri_parte_max = v.get("triangulos_por_parte_max")
    prim_tris = info.get("prim_tris") or []
    partes_ok = True if (partes_max is None or not gltf.get("meshes")) else info["primitivas"] <= int(partes_max)
    tri_parte_ok = (
        True
        if (tri_parte_max is None or not prim_tris)
        else max(prim_tris) <= int(tri_parte_max)
    )
    lods_arq = [a for a in arquivos if a.get("papel") == "lod"]
    lods_ok = True
    detalhes_lods: list[dict] = []
    if lods_arq and gltf.get("meshes"):
        pos0, tris0 = malha(gltf, binario)
        for arq_lod in lods_arq:
            caminho_lod = pasta / arq_lod["caminho"]
            if not caminho_lod.is_file():
                lods_ok = False
                detalhes_lods.append({"arquivo": arq_lod["caminho"], "ok": False})
                continue
            try:
                gltf_lod, bin_lod = ler_glb_bin(caminho_lod)
                topo_lod = (
                    topologia(gltf_lod, bin_lod)
                    if gltf_lod.get("meshes")
                    else {"nao_manifold": 0, "degeneradas": 0, "invertidas": 0}
                )
                pos_lod, tris_lod = malha(gltf_lod, bin_lod)
            except ForgeError:
                lods_ok = False
                detalhes_lods.append({"arquivo": arq_lod["caminho"], "ok": False})
                continue
            topo_lod_ok = (
                int(topo_lod["nao_manifold"]) <= int(v["nao_manifold_max"])
                and int(topo_lod.get("invertidas", 0)) == 0
            )
            iou_min: float | None = None
            silhueta_ok = True
            if len(tris0) >= 12 and len(tris_lod) >= 4:
                iou_min = _silhueta_iou_lod(pos0, tris0, pos_lod, tris_lod)
                limiar_iou = 0.78 if len(tris_lod) < 200 else 0.85
                silhueta_ok = iou_min >= limiar_iou
            lod_ok = topo_lod_ok and silhueta_ok
            lods_ok = lods_ok and lod_ok
            detalhes_lods.append(
                {
                    "arquivo": arq_lod["caminho"],
                    "nao_manifold": topo_lod["nao_manifold"],
                    "invertidas": topo_lod.get("invertidas", 0),
                    "iou_min": None if iou_min is None else round(iou_min, 4),
                    "ok": lod_ok,
                }
            )
    tri_ok = info["triangulos"] <= limite_tri and not maiores and partes_ok and tri_parte_ok and lods_ok
    gates.append(
        {
            "id": "G9",
            "status": "ok" if tri_ok else "falhou",
            "medido": {
                "triangulos": info["triangulos"],
                "limite": limite_tri,
                "primitivas": info["primitivas"],
                "max_tris_primitiva": max(prim_tris) if prim_tris else 0,
                "acima_do_tamanho": maiores,
                "qualidade": item.get("qualidade", "standard"),
                **({"lods": detalhes_lods} if detalhes_lods else {}),
            },
            "limite": {
                "limite_triangulos": limite_tri,
                "bytes_max_kb": bytes_max_kb,
                **({"partes_max": int(partes_max)} if partes_max is not None else {}),
                **(
                    {"triangulos_por_parte_max": int(tri_parte_max)}
                    if tri_parte_max is not None
                    else {}
                ),
            },
            "codigo": None if tri_ok else "FORGE-E-QC",
        }
    )

    # G10 animacao (D66)
    clipes = animacoes(gltf, binario)
    pedidos = [str(a) for a in (item.get("animacoes_base") or [])]
    por_nome = {c["nome"]: c for c in clipes}
    faltando = [n for n in pedidos if n not in por_nome]
    invalidos = [
        c["nome"] for c in clipes if c["duracao_s"] <= 0.2 or c["canais"] < 1 or not c["movendo"]
    ]
    anim_ok = not faltando and not invalidos
    gates.append(
        {
            "id": "G10",
            "status": "ok" if anim_ok else "falhou",
            "medido": {"clipes": clipes, "pedidos": pedidos, "faltando": faltando},
            "limite": {"duracao_min_s": 0.2, "canais_min": 1},
            "codigo": None if anim_ok else "FORGE-E-QC",
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
            # metros, nao unidades do arquivo: o consumidor le `unidades_export` no manifesto
            "bbox_m": [round(v / escala, 6) for v in info["bbox_m"]],
            "escala_saida": escala,
            "materiais": info["materiais"],
            "ossos": info["ossos"],
            "animacoes": clipes,
            "partes_colisao": int(medidas.get("partes_colisao", 0)),
        },
    }
