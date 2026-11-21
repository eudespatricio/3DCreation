"""Coerencia hierarquica de pesos de skinning e mediacao de costuras (camada L1)."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

MAX_INFLUENCIAS_VERTICE = 3
_RAIZES = frozenset({"Root", "HumanoidRootPart"})
_TRONCO_ANC = frozenset(
    {"Hips", "LowerTorso", "Spine", "Spine1", "Chest", "UpperTorso", "Shoulder.L", "Shoulder.R"}
)
_OSSOS_EXTREMIDADE_BRACO = frozenset(
    {
        "LowerArm.L", "Hand.L", "LowerArm.R", "Hand.R",
        "LeftLowerArm", "LeftHand", "RightLowerArm", "RightHand",
    }
)


def _lado_osso(nome: str) -> str:
    if nome.endswith(".L") or nome.startswith("Left"):
        return "L"
    return "R" if (nome.endswith(".R") or nome.startswith("Right")) else "C"


def construir_hierarquia_ossos(
    ossos: list[dict],
) -> tuple[dict[str, str | None], dict[str, dict[str, int]], Callable[[str, str], str | None]]:
    """Constroi (pai_map, dist_hier, lca_fn) ignorando raizes como pontes entre lados."""
    pai_map: dict[str, str | None] = {}
    for osso in ossos:
        nome = osso.get("nome")
        if not nome or nome in _RAIZES:
            continue
        pai = osso.get("pai")
        pai_map[nome] = None if (not pai or pai in _RAIZES) else pai

    adj: dict[str, list[str]] = {n: [] for n in pai_map}
    for n, pai in pai_map.items():
        if pai is not None and pai in adj:
            adj[n].append(pai)
            adj[pai].append(n)

    dist_hier: dict[str, dict[str, int]] = {}
    for origem in pai_map:
        d_map: dict[str, int] = {origem: 0}
        fila = deque([origem])
        while fila:
            u = fila.popleft()
            for v in adj[u]:
                if v not in d_map:
                    d_map[v] = d_map[u] + 1
                    fila.append(v)
        dist_hier[origem] = d_map

    def lca_fn(a: str, b: str) -> str | None:
        if a not in pai_map or b not in pai_map:
            return None
        anc_a: set[str] = set()
        cur: str | None = a
        while cur is not None and cur not in anc_a:
            anc_a.add(cur)
            cur = pai_map.get(cur)
        vistos_b: set[str] = set()
        cur_b: str | None = b
        while cur_b is not None and cur_b not in vistos_b:
            if cur_b in anc_a:
                return cur_b
            vistos_b.add(cur_b)
            cur_b = pai_map.get(cur_b)
        return None

    return pai_map, dist_hier, lca_fn


def normalizar_top_k(
    brutos_wn: list[tuple[float, str]],
    max_k: int = MAX_INFLUENCIAS_VERTICE,
) -> list[tuple[str, float]]:
    """Ordena decrescente, limita a max_k, descarta < 1e-4 e renormaliza soma para 1.0."""
    if not brutos_wn:
        return []
    ordenados = sorted(brutos_wn, reverse=True)
    top = ordenados[:max_k] if max_k > 0 else ordenados
    soma = sum(w for w, _ in top)
    if soma <= 0.0:
        return [(top[0][1], 1.0)]
    norm = [(n, w / soma) for w, n in top if w / soma >= 1e-4] or [(top[0][1], 1.0)]
    total = sum(w for _, w in norm)
    return norm if abs(total - 1.0) <= 1e-9 else [(n, w / total) for n, w in norm]


def filtrar_pesos_coerentes(
    brutos_wn: list[tuple[float, str]],
    dist_hier: dict[str, dict[str, int]],
    max_k: int = MAX_INFLUENCIAS_VERTICE,
) -> list[tuple[str, float]]:
    """Mantem osso dominante e vizinhos a distancia hierarquica <= 2, normalizando em top-k."""
    if not brutos_wn:
        return []
    ordenados = sorted(brutos_wn, reverse=True)
    dom = ordenados[0][1]
    viz_dom = dist_hier.get(dom, {})
    coerentes = [(w, nome) for w, nome in ordenados if nome == dom or viz_dom.get(nome, 99) <= 2]
    return normalizar_top_k(coerentes or [ordenados[0]], max_k=max_k)


def mediar_costuras_distantes(
    ilha: list[int],
    adj: list[list[tuple[int, float]]],
    pesos_por_vertice: dict[int, list[tuple[str, float]]],
    dist_hier: dict[str, dict[str, int]],
    lca_fn: Callable[[str, str], str | None],
    max_k: int = MAX_INFLUENCIAS_VERTICE,
) -> None:
    """Media costuras entre ossos distantes (dist >= 3 ou L/R) sem colar mao na coxa."""
    if not ilha or not pesos_por_vertice:
        return
    ilha_set = set(ilha)
    dom = {vi: pesos_por_vertice[vi][0][0] for vi in ilha if pesos_por_vertice.get(vi)}
    pares: list[tuple[int, int, str]] = []
    for vi in ilha:
        di = dom.get(vi)
        if not di:
            continue
        li, d_map_i = _lado_osso(di), dist_hier.get(di, {})
        for vj, _comp in adj[vi]:
            if vj <= vi or vj not in ilha_set:
                continue
            dj = dom.get(vj)
            if not dj or dj == di:
                continue
            lj = _lado_osso(dj)
            lados_op = li in ("L", "R") and lj in ("L", "R") and li != lj
            if d_map_i.get(dj, 99) >= 3 or lados_op:
                anc = lca_fn(di, dj)
                if anc in _TRONCO_ANC and anc not in (di, dj):
                    pares.append((vi, vj, anc))
    if not pares:
        return

    n_distal = sum(1 for d in dom.values() if d in _OSSOS_EXTREMIDADE_BRACO)
    v_dist = {v for vi, vj, _ in pares for v in (vi, vj) if dom[v] in _OSSOS_EXTREMIDADE_BRACO}
    bloq = bool(v_dist and n_distal > 0 and len(v_dist) > 0.12 * n_distal)
    pares_ok = [p for p in pares if not (bloq and (dom[p[0]] in _OSSOS_EXTREMIDADE_BRACO or dom[p[1]] in _OSSOS_EXTREMIDADE_BRACO))]
    if not pares_ok:
        return

    anc_v: dict[int, str] = {}
    for vi, vj, anc in pares_ok:
        anc_v.setdefault(vi, anc)
        anc_v.setdefault(vj, anc)
    for vi, anc in anc_v.items():
        acum = {n: w * 0.45 for n, w in pesos_por_vertice.get(vi, ())}
        acum[anc] = acum.get(anc, 0.0) + 0.55
        pesos_por_vertice[vi] = normalizar_top_k([(w, n) for n, w in acum.items()], max_k=max_k)

    anel1 = set(anc_v) | {vj for vi in anc_v for vj, _ in adj[vi] if vj in ilha_set}
    anel2 = anel1 | {vj for vi in anel1 for vj, _ in adj[vi] if vj in ilha_set}
    for _ in range(3):
        novos: dict[int, list[tuple[str, float]]] = {}
        for vi in anel2:
            ws_i, viz = pesos_por_vertice.get(vi), [vj for vj, _ in adj[vi] if vj in ilha_set]
            if not ws_i or not viz:
                continue
            acum = {n: w * 0.65 for n, w in ws_i}
            fator = 0.35 / float(len(viz))
            for vj in viz:
                for n, w in pesos_por_vertice.get(vj, ()):
                    acum[n] = acum.get(n, 0.0) + w * fator
            pares_wn = [(w, n) for n, w in acum.items() if w > 1e-6]
            novos[vi] = normalizar_top_k(pares_wn, max_k=max_k) if vi in anc_v else filtrar_pesos_coerentes(pares_wn, dist_hier, max_k=max_k)
        pesos_por_vertice.update(novos)
