"""Coerencia hierarquica de pesos de skinning e mediacao de costuras (camada L1)."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

MAX_INFLUENCIAS_VERTICE = 3
_RAIZES = frozenset({"Root", "HumanoidRootPart"})
_TRONCO_ANC = frozenset(
    {"Hips", "LowerTorso", "Spine", "Spine1", "Chest", "UpperTorso", "Shoulder.L", "Shoulder.R"}
)
_OSSOS_BRACO_PROXIMAL = frozenset(
    {"Shoulder.L", "Shoulder.R", "UpperArm.L", "UpperArm.R", "LeftUpperArm", "RightUpperArm"}
)
_TRONCO_SUP = frozenset({"Spine", "Spine1", "Chest", "UpperTorso"})
_OSSOS_CABECA_COER = frozenset({"Head", "Neck"})
_OSSOS_QUADRIL_COER = frozenset({"Hips", "LowerTorso"})
_OSSOS_CANELA_PE_COER = frozenset(
    {
        "LowerLeg.L", "LowerLeg.R", "Foot.L", "Foot.R", "Toe.L", "Toe.R",
        "LeftLowerLeg", "RightLowerLeg", "LeftFoot", "RightFoot",
    }
)
_OSSOS_COXA_COER = frozenset({"UpperLeg.L", "UpperLeg.R", "LeftUpperLeg", "RightUpperLeg"})
_OSSOS_EXTREMIDADE_BRACO = frozenset(
    {
        "LowerArm.L", "Hand.L", "LowerArm.R", "Hand.R",
        "LeftLowerArm", "LeftHand", "RightLowerArm", "RightHand",
    }
)
_OSSOS_PERNA_COER = frozenset(
    {
        "UpperLeg.L", "LowerLeg.L", "Foot.L", "Toe.L",
        "UpperLeg.R", "LowerLeg.R", "Foot.R", "Toe.R",
        "LeftUpperLeg", "LeftLowerLeg", "LeftFoot",
        "RightUpperLeg", "RightLowerLeg", "RightFoot",
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
    """Mantem osso dominante e vizinhos mutualmente coerentes (dist_hier <= 2 par-a-par)."""
    if not brutos_wn:
        return []
    ordenados = sorted(brutos_wn, reverse=True)
    coerentes: list[tuple[float, str]] = []
    for w, nome in ordenados:
        if all(dist_hier.get(nome, {}).get(prev, 99) <= 2 for _, prev in coerentes):
            coerentes.append((w, nome))
            if max_k > 0 and len(coerentes) >= max_k:
                break
    return normalizar_top_k(coerentes or [ordenados[0]], max_k=max_k)


def _escolher_mediador(
    di: str,
    dj: str,
    dist_hier: dict[str, dict[str, int]],
    lca_fn: Callable[[str, str], str | None],
) -> str | None:
    """Escolhe mediador intermediario estrito (nunca em {di, dj}) no caminho hierarquico."""
    d_map_i = dist_hier.get(di, {})
    d_total = d_map_i.get(dj, 99)
    if (
        (di in _OSSOS_QUADRIL_COER and dj in _OSSOS_CANELA_PE_COER)
        or (dj in _OSSOS_QUADRIL_COER and di in _OSSOS_CANELA_PE_COER)
    ) and d_total < 99:
        cands_coxa: list[tuple[int, str]] = []
        for k, d_ik in d_map_i.items():
            if k in (di, dj) or k not in _OSSOS_COXA_COER:
                continue
            d_kj = dist_hier.get(k, {}).get(dj, 99)
            if d_ik + d_kj == d_total:
                cands_coxa.append((abs(d_ik - d_kj), k))
        if cands_coxa:
            cands_coxa.sort()
            return cands_coxa[0][1]

    tem_distal_braco = (di in _OSSOS_EXTREMIDADE_BRACO) or (dj in _OSSOS_EXTREMIDADE_BRACO)
    tem_perna = (di in _OSSOS_PERNA_COER) or (dj in _OSSOS_PERNA_COER)

    if tem_distal_braco and not tem_perna and d_total < 99:
        cands_prox: list[tuple[int, int, str]] = []
        for k, d_ik in d_map_i.items():
            if k in (di, dj) or k not in _OSSOS_BRACO_PROXIMAL:
                continue
            d_kj = dist_hier.get(k, {}).get(dj, 99)
            if d_ik + d_kj == d_total:
                pref_ombro = 0 if k.startswith("Shoulder.") else 1
                cands_prox.append((abs(d_ik - d_kj), pref_ombro, k))
        if cands_prox:
            cands_prox.sort()
            return cands_prox[0][2]

    anc = lca_fn(di, dj)
    if anc in _TRONCO_ANC and anc not in (di, dj):
        return anc

    if 2 <= d_total < 99:
        cands_mid: list[tuple[int, str]] = []
        elegiveis = _TRONCO_ANC | _OSSOS_BRACO_PROXIMAL
        for k, d_ik in d_map_i.items():
            if k in (di, dj) or k not in elegiveis:
                continue
            d_kj = dist_hier.get(k, {}).get(dj, 99)
            if d_ik + d_kj == d_total:
                cands_mid.append((abs(d_ik - d_kj), k))
        if cands_mid:
            cands_mid.sort()
            return cands_mid[0][1]
    return None


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
            par_cabeca_braco = (
                (di in _OSSOS_CABECA_COER and (dj in _OSSOS_BRACO_PROXIMAL or dj in _OSSOS_EXTREMIDADE_BRACO))
                or (dj in _OSSOS_CABECA_COER and (di in _OSSOS_BRACO_PROXIMAL or di in _OSSOS_EXTREMIDADE_BRACO))
            )
            par_quadril_canela = (
                (di in _OSSOS_QUADRIL_COER and dj in _OSSOS_CANELA_PE_COER)
                or (dj in _OSSOS_QUADRIL_COER and di in _OSSOS_CANELA_PE_COER)
            )
            par_quadril_braco = (
                (di in _OSSOS_QUADRIL_COER and dj in _OSSOS_BRACO_PROXIMAL)
                or (dj in _OSSOS_QUADRIL_COER and di in _OSSOS_BRACO_PROXIMAL)
            )
            if d_map_i.get(dj, 99) >= 3 or lados_op or par_cabeca_braco or par_quadril_canela or par_quadril_braco:
                med = _escolher_mediador(di, dj, dist_hier, lca_fn)
                if med is not None and med not in (di, dj):
                    pares.append((vi, vj, med))
    if not pares:
        _suavizar_costura_axila(ilha_set, adj, pesos_por_vertice, dist_hier, max_k=max_k)
        return

    n_distal = sum(1 for d in dom.values() if d in _OSSOS_EXTREMIDADE_BRACO)
    v_dist_perna = {
        v
        for vi, vj, _ in pares
        if (dom[vi] in _OSSOS_EXTREMIDADE_BRACO and dom[vj] in _OSSOS_PERNA_COER)
        or (dom[vj] in _OSSOS_EXTREMIDADE_BRACO and dom[vi] in _OSSOS_PERNA_COER)
        for v in (vi, vj)
        if dom[v] in _OSSOS_EXTREMIDADE_BRACO
    }
    bloq_perna = bool(v_dist_perna and n_distal > 0 and len(v_dist_perna) > 0.12 * n_distal)
    pares_ok = [
        p
        for p in pares
        if not (
            bloq_perna
            and (
                (dom[p[0]] in _OSSOS_EXTREMIDADE_BRACO and dom[p[1]] in _OSSOS_PERNA_COER)
                or (dom[p[1]] in _OSSOS_EXTREMIDADE_BRACO and dom[p[0]] in _OSSOS_PERNA_COER)
            )
        )
    ]
    if not pares_ok:
        _suavizar_costura_axila(ilha_set, adj, pesos_por_vertice, dist_hier, max_k=max_k)
        return

    anc_v: dict[int, str] = {}
    for vi, vj, anc in pares_ok:
        anc_v.setdefault(vi, anc)
        anc_v.setdefault(vj, anc)
    tem_upper_torso = any(anc == "UpperTorso" for anc in anc_v.values())
    tem_chest = any(anc == "Chest" for anc in anc_v.values())
    w_keep_anc = 0.15 if tem_upper_torso else (0.30 if tem_chest else 0.45)
    w_add_anc = 1.0 - w_keep_anc
    n_passos = 5 if tem_upper_torso else (4 if tem_chest else 3)
    w_self = 0.50 if tem_upper_torso else (0.55 if tem_chest else 0.65)
    w_viz = 1.0 - w_self
    for vi, anc in anc_v.items():
        acum = {n: w * w_keep_anc for n, w in pesos_por_vertice.get(vi, ())}
        acum[anc] = acum.get(anc, 0.0) + w_add_anc
        pesos_por_vertice[vi] = normalizar_top_k([(w, n) for n, w in acum.items()], max_k=max_k)

    anel1 = set(anc_v) | {vj for vi in anc_v for vj, _ in adj[vi] if vj in ilha_set}
    anel2 = anel1 | {vj for vi in anel1 for vj, _ in adj[vi] if vj in ilha_set}
    anel_suav = (anel2 | {vj for vi in anel2 for vj, _ in adj[vi] if vj in ilha_set}) if tem_upper_torso else anel2
    for _ in range(n_passos):
        novos: dict[int, list[tuple[str, float]]] = {}
        for vi in anel_suav:
            ws_i, viz = pesos_por_vertice.get(vi), [vj for vj, _ in adj[vi] if vj in ilha_set]
            if not ws_i or not viz:
                continue
            acum = {n: w * w_self for n, w in ws_i}
            fator = w_viz / float(len(viz))
            for vj in viz:
                for n, w in pesos_por_vertice.get(vj, ()):
                    acum[n] = acum.get(n, 0.0) + w * fator
            pares_wn = [(w, n) for n, w in acum.items() if w > 1e-6]
            novos[vi] = normalizar_top_k(pares_wn, max_k=max_k) if vi in anc_v else filtrar_pesos_coerentes(pares_wn, dist_hier, max_k=max_k)
        pesos_por_vertice.update(novos)
    _suavizar_costura_axila(ilha_set, adj, pesos_por_vertice, dist_hier, max_k=max_k)


def _suavizar_costura_axila(
    ilha_set: set[int],
    adj: list[list[tuple[int, float]]],
    pesos_por_vertice: dict[int, list[tuple[str, float]]],
    dist_hier: dict[str, dict[str, int]],
    max_k: int = MAX_INFLUENCIAS_VERTICE,
) -> None:
    """Suaviza em 4 passos (2 aneis) arestas de axila braco-movel <-> ombro/tronco com salto > 0.20."""
    ossos_braco = (_OSSOS_BRACO_PROXIMAL - {"Shoulder.L", "Shoulder.R"}) | _OSSOS_EXTREMIDADE_BRACO
    ossos_braco_todos = _OSSOS_BRACO_PROXIMAL | _OSSOS_EXTREMIDADE_BRACO
    elegiveis = _OSSOS_BRACO_PROXIMAL | _TRONCO_SUP
    dom = {vi: pesos_por_vertice[vi][0][0] for vi in ilha_set if pesos_por_vertice.get(vi)}
    w_arm = {
        vi: sum(w for n, w in pesos_por_vertice[vi] if n in ossos_braco)
        for vi in dom
    }
    w_all_arm = {
        vi: sum(w for n, w in pesos_por_vertice[vi] if n in ossos_braco_todos)
        for vi in dom
    }
    costura: set[int] = set()
    lados_axila: dict[int, str] = {}
    for vi, di in dom.items():
        if di not in elegiveis:
            continue
        wa_i, waa_i = w_arm[vi], w_all_arm[vi]
        for vj, _comp in adj[vi]:
            if vj <= vi or vj not in dom:
                continue
            dj = dom[vj]
            if dj not in elegiveis:
                continue
            li_a, lj_a = _lado_osso(di), _lado_osso(dj)
            if li_a in ("L", "R") and lj_a in ("L", "R") and li_a != lj_a:
                continue
            if abs(wa_i - w_arm[vj]) > 0.20 or abs(waa_i - w_all_arm[vj]) > 0.45:
                costura.add(vi)
                costura.add(vj)
                braco_v = di if di in ("UpperArm.L", "UpperArm.R") else (dj if dj in ("UpperArm.L", "UpperArm.R") else None)
                if braco_v is not None and (di in _TRONCO_SUP or dj in _TRONCO_SUP):
                    lado_a = _lado_osso(braco_v)
                    lados_axila.setdefault(vi, lado_a)
                    lados_axila.setdefault(vj, lado_a)
    if not costura:
        return

    lados_spine_bloq: set[int] = set()
    for vi, lado_a in lados_axila.items():
        ombro = f"Shoulder.{lado_a}"
        if ombro not in dist_hier:
            continue
        lados_spine_bloq.add(vi)
        ws_i = pesos_por_vertice.get(vi)
        if not ws_i or sum(w for n, w in ws_i if n == ombro) >= 0.15:
            continue
        acum_sh = {n: w * 0.70 for n, w in ws_i}
        acum_sh[ombro] = acum_sh.get(ombro, 0.0) + 0.30
        pesos_por_vertice[vi] = filtrar_pesos_coerentes([(w, n) for n, w in acum_sh.items()], dist_hier, max_k=max_k)

    anel1 = set(costura) | {
        vj for vi in costura for vj, _ in adj[vi] if vj in dom and dom[vj] in elegiveis
    }
    anel = anel1 | {
        vj for vi in anel1 for vj, _ in adj[vi] if vj in dom and dom[vj] in elegiveis
    }
    for _ in range(4):
        novos: dict[int, list[tuple[str, float]]] = {}
        for vi in anel:
            ws_i = pesos_por_vertice.get(vi)
            if not ws_i:
                continue
            di = ws_i[0][0]
            li, d_map_i = _lado_osso(di), dist_hier.get(di, {})
            viz_ok = [vj for vj, _ in adj[vi] if vj in dom and dom[vj] in elegiveis]
            if not viz_ok:
                continue
            bloq_sp = (vi in lados_spine_bloq) and (di != "Spine")
            acum = {n: w * 0.55 for n, w in ws_i if not (bloq_sp and n == "Spine")}
            fator = 0.45 / float(len(viz_ok))
            for vj in viz_ok:
                for n, w in pesos_por_vertice.get(vj, ()):
                    if bloq_sp and n == "Spine":
                        continue
                    ln = _lado_osso(n)
                    if li in ("L", "R") and ln in ("L", "R") and li != ln:
                        continue
                    if n in elegiveis and (n == di or d_map_i.get(n, 99) <= 2):
                        acum[n] = acum.get(n, 0.0) + w * fator
            pares_wn = sorted(((w, n) for n, w in acum.items() if w > 1e-6), reverse=True)
            escolhidos: list[tuple[float, str]] = []
            for w_c, n_c in pares_wn:
                if all(dist_hier.get(n_c, {}).get(prev, 99) <= 2 for _, prev in escolhidos):
                    escolhidos.append((w_c, n_c))
                    if len(escolhidos) >= max_k:
                        break
            if escolhidos:
                novos[vi] = normalizar_top_k(escolhidos, max_k=max_k)
        pesos_por_vertice.update(novos)
