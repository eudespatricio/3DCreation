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
