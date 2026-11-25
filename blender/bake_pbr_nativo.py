"""Deteccao e passes Cycles para malhas com PBR nativo (UVMap + TEX_IMAGE em Principled BSDF)."""

from __future__ import annotations

try:
    import bpy
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bpy = None  # type: ignore[assignment]


def _node_uid(node) -> int:
    ptr = getattr(node, "as_pointer", None)
    return int(ptr()) if callable(ptr) else id(node)


def _nodos_upstream(raiz) -> list:
    visitados: set[int] = set()
    pilha, saida = [raiz], []
    while pilha:
        atual = pilha.pop()
        if atual is None:
            continue
        uid = _node_uid(atual)
        if uid in visitados:
            continue
        visitados.add(uid)
        saida.append(atual)
        for inp in getattr(atual, "inputs", ()):
            for lk in getattr(inp, "links", ()):
                if getattr(lk, "from_node", None) is not None:
                    pilha.append(lk.from_node)
    return saida


def _tex_image_valida(node) -> bool:
    if getattr(node, "type", "") != "TEX_IMAGE":
        return False
    img = getattr(node, "image", None)
    sz = getattr(img, "size", ()) if img is not None else ()
    return len(sz) >= 2 and int(sz[0]) > 0 and int(sz[1]) > 0


def objeto_tem_pbr_nativo(obj) -> bool:
    """True iff ``obj`` tem ``uv_layers`` e >= 1 material com ``TEX_IMAGE`` ligada ao BSDF/Output."""
    if obj is None or getattr(obj, "data", None) is None or not getattr(obj.data, "uv_layers", None):
        return False
    for mat in getattr(obj.data, "materials", None) or ():
        if mat is None or not getattr(mat, "use_nodes", False) or getattr(mat, "node_tree", None) is None:
            continue
        nodes = getattr(mat.node_tree, "nodes", ())
        out_node = next(
            (n for n in nodes if getattr(n, "type", "") == "OUTPUT_MATERIAL" and getattr(n, "is_active_output", True)),
            None,
        ) or next((n for n in nodes if getattr(n, "type", "") == "OUTPUT_MATERIAL"), None)
        bsdf_node = next((n for n in nodes if getattr(n, "type", "") == "BSDF_PRINCIPLED"), None)
        for raiz in (n for n in (out_node, bsdf_node) if n is not None):
            if any(_tex_image_valida(n) for n in _nodos_upstream(raiz)):
                return True
    return False


def _material_tem_emissive_nativo(mat) -> bool:
    if mat is None or not getattr(mat, "use_nodes", False) or getattr(mat, "node_tree", None) is None:
        return False
    nodes = getattr(mat.node_tree, "nodes", ())
    bsdf = next((n for n in nodes if getattr(n, "type", "") == "BSDF_PRINCIPLED"), None) or mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        em_str = bsdf.inputs.get("Emission Strength")
        bsdf_ativo = not (
            em_str is not None and not (em_str.is_linked and em_str.links) and float(em_str.default_value) <= 1e-4
        )
        em_col = (bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")) if bsdf_ativo else None
        if em_col is not None:
            if em_col.is_linked and em_col.links:
                return True
            val = getattr(em_col, "default_value", (0.0, 0.0, 0.0, 1.0))
            if max(float(val[0]), float(val[1]), float(val[2])) > 1e-4:
                return True
    out_node = next(
        (n for n in nodes if getattr(n, "type", "") == "OUTPUT_MATERIAL" and getattr(n, "is_active_output", True)),
        None,
    ) or next((n for n in nodes if getattr(n, "type", "") == "OUTPUT_MATERIAL"), None)
    if out_node is not None:
        for n in _nodos_upstream(out_node):
            if getattr(n, "type", "") == "EMISSION":
                s_in = n.inputs.get("Strength")
                c_in = n.inputs.get("Color")
                s_ok = (s_in is not None and s_in.is_linked and bool(s_in.links)) or (
                    s_in is not None and float(s_in.default_value) > 1e-4
                )
                if s_ok and c_in is not None:
                    if c_in.is_linked and c_in.links:
                        return True
                    cv = getattr(c_in, "default_value", (0.0, 0.0, 0.0, 1.0))
                    if max(float(cv[0]), float(cv[1]), float(cv[2])) > 1e-4:
                        return True
    return False


def objeto_tem_emissive_nativo(mats) -> bool:
    """True se algum material nativo tiver emissao ativa (Principled BSDF ou Emission)."""
    if mats is None:
        return False
    itens = getattr(getattr(mats, "data", None), "materials", None)
    seq = itens if itens is not None else mats
    return any(_material_tem_emissive_nativo(m) for m in (seq or ()))


def clonar_materiais_nativos(high_obj, nome_base: str) -> list:
    """Clona slots de material da copia temporaria ``high_obj`` (isolada de ``obj`` e limpa em ``finally``)."""
    clonados: list = []
    mats = high_obj.data.materials
    for idx in range(len(mats)):
        if mats[idx] is None:
            continue
        mat_cp = mats[idx].copy()
        mat_cp.name = f"{nome_base}_high_nat_{idx}_tmp"
        mats[idx] = mat_cp
        clonados.append(mat_cp)
    return clonados


def _preparar_emit_output(mat):
    if mat is None or not getattr(mat, "use_nodes", False) or mat.node_tree is None:
        return None
    nt = mat.node_tree
    out_node = next(
        (n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and getattr(n, "is_active_output", True)),
        None,
    ) or next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out_node is None or out_node.inputs.get("Surface") is None:
        return None
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None) or nt.nodes.get("Principled BSDF")
    surf_inp = out_node.inputs["Surface"]
    antigos = [lk.from_socket for lk in list(surf_inp.links)]
    for lk in list(surf_inp.links):
        nt.links.remove(lk)
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 1.0
    nt.links.new(emit.outputs["Emission"], surf_inp)
    return nt, out_node, bsdf, antigos, emit


def _ligar_ou_valor(nt, src_inp, dst_inp, fallback) -> None:
    if src_inp is not None and src_inp.is_linked and src_inp.links:
        nt.links.new(src_inp.links[0].from_socket, dst_inp)
    elif src_inp is not None:
        dst_inp.default_value = type(fallback)(src_inp.default_value) if isinstance(fallback, float) else tuple(src_inp.default_value)
    else:
        dst_inp.default_value = fallback


def configurar_saida_basecolor_emit_nativos(mats: list) -> list[tuple]:
    """Desvia ``Base Color`` de cada material para ``Emission(1.0)`` e retorna tokens de restauro."""
    tokens: list[tuple] = []
    for mat in mats:
        prep = _preparar_emit_output(mat)
        if prep is None:
            continue
        nt, out_node, bsdf, antigos, emit = prep
        bc_inp = bsdf.inputs.get("Base Color") if bsdf is not None else None
        _ligar_ou_valor(nt, bc_inp, emit.inputs["Color"], (0.8, 0.8, 0.8, 1.0))
        tokens.append((nt, out_node, antigos, [emit]))
    return tokens


def configurar_saida_orm_emit_nativos(mats: list) -> list[tuple]:
    """Desvia ``(Metallic, Roughness, 1.0)`` para ``Emission(1.0)`` e retorna tokens de restauro."""
    tokens: list[tuple] = []
    for mat in mats:
        prep = _preparar_emit_output(mat)
        if prep is None:
            continue
        nt, out_node, bsdf, antigos, emit = prep
        comb = nt.nodes.new("ShaderNodeCombineColor")
        comb.mode = "RGB"
        _ligar_ou_valor(nt, bsdf.inputs.get("Metallic") if bsdf is not None else None, comb.inputs[0], 0.0)
        _ligar_ou_valor(nt, bsdf.inputs.get("Roughness") if bsdf is not None else None, comb.inputs[1], 0.5)
        comb.inputs[2].default_value = 1.0
        nt.links.new(comb.outputs["Color"], emit.inputs["Color"])
        tokens.append((nt, out_node, antigos, [emit, comb]))
    return tokens


def configurar_saida_emissive_emit_nativos(mats: list) -> list[tuple]:
    """Desvia canal emissivo de cada material nativo para ``Emission`` de bake e retorna tokens."""
    tokens: list[tuple] = []
    for mat in mats:
        prep = _preparar_emit_output(mat)
        if prep is None:
            continue
        nt, out_node, bsdf, antigos, emit = prep
        src_node = antigos[0].node if antigos else None
        em_up = (
            next((n for n in _nodos_upstream(src_node) if getattr(n, "type", "") == "EMISSION"), None)
            if src_node is not None
            else None
        )
        if bsdf is not None:
            em_col = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
            em_str = bsdf.inputs.get("Emission Strength")
            str_zero = (
                em_str is not None
                and not (em_str.is_linked and em_str.links)
                and float(em_str.default_value) <= 1e-4
            )
            col_zero = (
                em_col is None
                or (
                    not (em_col.is_linked and em_col.links)
                    and max(float(em_col.default_value[0]), float(em_col.default_value[1]), float(em_col.default_value[2])) <= 1e-4
                )
            )
            if not str_zero and not col_zero and em_col is not None:
                _ligar_ou_valor(nt, em_col, emit.inputs["Color"], (0.0, 0.0, 0.0, 1.0))
                _ligar_ou_valor(nt, em_str, emit.inputs["Strength"], 1.0)
            elif em_up is not None:
                _ligar_ou_valor(nt, em_up.inputs.get("Color"), emit.inputs["Color"], (0.0, 0.0, 0.0, 1.0))
                _ligar_ou_valor(nt, em_up.inputs.get("Strength"), emit.inputs["Strength"], 1.0)
            else:
                emit.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
                emit.inputs["Strength"].default_value = 0.0
        elif em_up is not None:
            _ligar_ou_valor(nt, em_up.inputs.get("Color"), emit.inputs["Color"], (0.0, 0.0, 0.0, 1.0))
            _ligar_ou_valor(nt, em_up.inputs.get("Strength"), emit.inputs["Strength"], 1.0)
        else:
            emit.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
            emit.inputs["Strength"].default_value = 0.0
        tokens.append((nt, out_node, antigos, [emit]))
    return tokens


def restaurar_saidas_nativos(tokens: list[tuple]) -> None:
    """Restaura ligacoes originais de ``Material Output.Surface`` e remove nodos temporarios."""
    for nt, out_node, antigos, nodos_tmp in tokens:
        surf_inp = out_node.inputs.get("Surface")
        if surf_inp is not None:
            for lk in list(surf_inp.links):
                nt.links.remove(lk)
            for sock in antigos:
                nt.links.new(sock, surf_inp)
        for nodo in nodos_tmp:
            if nodo is not None:
                nt.nodes.remove(nodo)
