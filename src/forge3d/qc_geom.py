"""Metricas geometricas puras de QC: topologia (G1) e convexidade de colisores (G7)."""

from __future__ import annotations

from .qc_glb import malha


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
    tris_validos: list[
        tuple[
            int,
            int,
            int,
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ]
    ] = []
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

    por_comp: dict[
        int,
        list[
            tuple[
                int,
                int,
                int,
                tuple[float, float, float],
                tuple[float, float, float],
                tuple[float, float, float],
            ]
        ],
    ] = {}
    for tri in tris_validos:
        por_comp.setdefault(_raiz(tri[0]), []).append(tri)

    cascas: list[tuple[float, list[float], list[float], bool]] = []
    invertidas_abertas = 0
    for ctris in por_comp.values():
        arestas_comp: dict[tuple[int, int], int] = {}
        dir_arestas: dict[tuple[int, int], int] = {}
        verts_comp: set[int] = set()
        for A, B, C, _pa, _pb, _pc in ctris:
            verts_comp.update((A, B, C))
            for e in ((A, B), (B, C), (C, A)):
                dir_arestas[e] = dir_arestas.get(e, 0) + 1
                ch: tuple[int, int] = (e[0], e[1]) if e[0] < e[1] else (e[1], e[0])
                arestas_comp[ch] = arestas_comp.get(ch, 0) + 1
        conflito_winding = any(cnt > 1 for cnt in dir_arestas.values())
        if len(ctris) < 4 or not arestas_comp or any(n != 2 for n in arestas_comp.values()):
            if conflito_winding:
                invertidas_abertas += 1
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
        cascas.append((vol, cmin, cmax, conflito_winding))

    invertidas = invertidas_abertas
    for vol_in, mn_in, mx_in, conflito_w in cascas:
        if vol_in >= -1e-9:
            if conflito_w:
                invertidas += 1
            continue
        cavidade = any(
            vol_out > 1e-9
            and vol_out > abs(vol_in) * 1.05
            and all(mn_in[d] >= mn_out[d] - 1e-5 and mx_in[d] <= mx_out[d] + 1e-5 for d in range(3))
            for vol_out, mn_out, mx_out, _cw in cascas
        )
        if not cavidade:
            invertidas += 1

    bordas_abertas = sum(1 for n in arestas.values() if n == 1)
    arestas_t = sum(1 for n in arestas.values() if n > 2)
    return {
        "nao_manifold": bordas_abertas + arestas_t,
        "bordas_abertas": bordas_abertas,
        "arestas_t": arestas_t,
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
    """Malha fechada e convexa se, em toda face, todos os vertices caem do mesmo lado."""
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
    """Mede se cada parte do colisor e convexa (GAP-038/C8)."""
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
