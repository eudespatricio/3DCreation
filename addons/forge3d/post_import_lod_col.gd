@tool
extends RefCounted
## Submodulo de colisores UCX/irmaos, LODs proporcionais ao AABB e GI_MODE_STATIC.

const DEFAULT_LOD_DISTANCIA_M := 25.0


static func _transform_relativo(nodo: Node, ancestral: Node) -> Transform3D:
	var acum := Transform3D.IDENTITY
	var cur: Node = nodo
	while cur != null and cur != ancestral:
		if cur is Node3D:
			acum = (cur as Node3D).transform * acum
		cur = cur.get_parent()
	return acum


static func _criar_static_body_agrupado(
	itens: Array,
	parent: Node,
	root: Node,
	shape_fn: Callable = Callable()
) -> int:
	if itens.is_empty():
		return 0
	var first: Dictionary = itens[0]
	var base_xform: Transform3D = first["xform"]
	var base_inv := base_xform.affine_inverse()
	var body := StaticBody3D.new()
	body.name = String(first["nome"]) + "_col"
	body.transform = base_xform
	parent.add_child(body)
	body.owner = root

	var criados := 0
	for i in range(itens.size()):
		var item: Dictionary = itens[i]
		var mesh := item["mesh"] as Mesh
		if mesh == null:
			continue
		var shape_node := CollisionShape3D.new()
		shape_node.name = "CollisionShape3D" if criados == 0 else ("CollisionShape3D_%d" % (criados + 1))
		shape_node.shape = shape_fn.call(mesh) if shape_fn.is_valid() else mesh.create_convex_shape(true, false)
		if i > 0:
			shape_node.transform = base_inv * (item["xform"] as Transform3D)
		body.add_child(shape_node)
		shape_node.owner = root
		criados += 1
	return criados


static func _extrair_mesh_node(nodo: Node) -> Mesh:
	if nodo is MeshInstance3D:
		return (nodo as MeshInstance3D).mesh
	if nodo is ImporterMeshInstance3D:
		var imi := nodo as ImporterMeshInstance3D
		if imi.mesh != null:
			return imi.mesh.get_mesh()
	return null


static func _coletar_e_remover_ucx(nodo: Node, root: Node, saida: Array) -> void:
	for filho in nodo.get_children().duplicate():
		if (filho is MeshInstance3D or filho is ImporterMeshInstance3D) and String(filho.name).begins_with("UCX_"):
			var mesh := _extrair_mesh_node(filho)
			if mesh != null:
				saida.append({
					"nome": String(filho.name),
					"xform": _transform_relativo(filho, root),
					"mesh": mesh,
				})
			nodo.remove_child(filho)
			filho.free()
		else:
			_coletar_e_remover_ucx(filho, root, saida)


static func _converter_ucx(nodo: Node, root: Node, shape_fn: Callable = Callable()) -> int:
	var itens: Array = []
	_coletar_e_remover_ucx(nodo, root, itens)
	if itens.is_empty():
		return 0
	return _criar_static_body_agrupado(itens, root, root, shape_fn)


static func _caminho_colisor_irmao(source_file: String, manifesto: Dictionary) -> String:
	if source_file == "":
		return ""
	var col_info: Variant = manifesto.get("colisao", {})
	if typeof(col_info) == TYPE_DICTIONARY:
		var arquivo: String = str(col_info.get("arquivo", ""))
		if arquivo != "":
			return source_file.get_base_dir().path_join(arquivo)
	return source_file.get_basename() + "_colisao.glb"


static func _coletar_malhas_com_xform(nodo: Node, acum: Transform3D, saida: Array) -> void:
	for filho in nodo.get_children():
		var local_xform := acum
		if filho is Node3D:
			local_xform = acum * (filho as Node3D).transform
		var mesh := _extrair_mesh_node(filho)
		if mesh != null:
			saida.append({"nome": String(filho.name), "xform": local_xform, "mesh": mesh})
		_coletar_malhas_com_xform(filho, local_xform, saida)


static func _carregar_glb(caminho: String) -> Node:
	if caminho == "" or not FileAccess.file_exists(caminho):
		return null
	var bytes := FileAccess.get_file_as_bytes(caminho)
	if bytes.is_empty():
		return null
	var doc := GLTFDocument.new()
	var estado := GLTFState.new()
	if doc.append_from_buffer(bytes, caminho.get_base_dir(), estado) != OK:
		return null
	return doc.generate_scene(estado)


static func _carregar_colisor_irmao(
	scene: Node,
	source_file: String,
	manifesto: Dictionary,
	shape_fn: Callable = Callable()
) -> void:
	var col_path := _caminho_colisor_irmao(source_file, manifesto)
	var col_cena := _carregar_glb(col_path)
	if col_cena == null:
		return
	var itens: Array = []
	_coletar_malhas_com_xform(col_cena, Transform3D.IDENTITY, itens)
	if not itens.is_empty():
		_criar_static_body_agrupado(itens, scene, scene, shape_fn)
	col_cena.free()


static func _caminhos_lods_irmaos(source_file: String, manifesto: Dictionary) -> Array[Dictionary]:
	var saida: Array[Dictionary] = []
	if source_file == "" or manifesto.is_empty():
		return saida
	var lods: Variant = manifesto.get("lod", [])
	if typeof(lods) != TYPE_ARRAY:
		return saida
	var niveis: Array[Dictionary] = []
	for item in lods:
		if typeof(item) != TYPE_DICTIONARY:
			continue
		var raw_n: Variant = item.get("nivel", -1)
		if typeof(raw_n) != TYPE_INT and typeof(raw_n) != TYPE_FLOAT:
			continue
		var nivel := int(raw_n)
		if nivel < 1 or nivel > 4:
			continue
		var arquivo: String = str(item.get("arquivo", ""))
		var caminho := (
			source_file.get_base_dir().path_join(arquivo)
			if arquivo != ""
			else "%s_LOD%d.glb" % [source_file.get_basename(), nivel]
		)
		var dist_custom: Variant = item.get("distancia_m", item.get("lod_distancia_m", null))
		niveis.append({"nivel": nivel, "caminho": caminho, "distancia_m": dist_custom})
	niveis.sort_custom(func(a, b): return int(a["nivel"]) < int(b["nivel"]))
	return niveis


static func _caminho_lod1_irmao(source_file: String, manifesto: Dictionary) -> String:
	for item in _caminhos_lods_irmaos(source_file, manifesto):
		if int(item["nivel"]) == 1:
			return str(item["caminho"])
	return ""


static func _calcular_diag_aabb_scene(scene: Node, meshes: Array[MeshInstance3D]) -> float:
	var bmin := Vector3(INF, INF, INF)
	var bmax := Vector3(-INF, -INF, -INF)
	for mi in meshes:
		if mi == null or mi.mesh == null:
			continue
		var local_aabb := mi.mesh.get_aabb()
		var xf := _transform_relativo(mi, scene) if scene != null else mi.transform
		for ix in range(2):
			for iy in range(2):
				for iz in range(2):
					var corner := Vector3(
						local_aabb.position.x + (local_aabb.size.x if ix == 1 else 0.0),
						local_aabb.position.y + (local_aabb.size.y if iy == 1 else 0.0),
						local_aabb.position.z + (local_aabb.size.z if iz == 1 else 0.0)
					)
					var wc := xf * corner
					bmin = bmin.min(wc)
					bmax = bmax.max(wc)
	if bmin.x == INF:
		return 0.0
	return (bmax - bmin).length()


static func _obter_lod_distancia_m(
	manifesto: Dictionary,
	perfil_cfg: Dictionary,
	meshes: Array[MeshInstance3D] = [],
	scene: Node = null
) -> float:
	var raw_man: Variant = manifesto.get("lod_distancia_m", null)
	if (typeof(raw_man) == TYPE_INT or typeof(raw_man) == TYPE_FLOAT) and float(raw_man) > 0.0:
		return float(raw_man)
	var lods: Variant = manifesto.get("lod", [])
	if typeof(lods) == TYPE_ARRAY:
		for item in lods:
			if typeof(item) != TYPE_DICTIONARY:
				continue
			var nivel: Variant = item.get("nivel", -1)
			if (typeof(nivel) == TYPE_INT or typeof(nivel) == TYPE_FLOAT) and int(nivel) == 1:
				var d: Variant = item.get("distancia_m", item.get("lod_distancia_m", null))
				if (typeof(d) == TYPE_INT or typeof(d) == TYPE_FLOAT) and float(d) > 0.0:
					return float(d)
	if not meshes.is_empty():
		var diag := _calcular_diag_aabb_scene(scene, meshes)
		if diag > 0.001:
			return clampf(diag * 8.0, 4.0, 400.0)
	var raw_prof: Variant = perfil_cfg.get("lod_distancia_m", null)
	if (typeof(raw_prof) == TYPE_INT or typeof(raw_prof) == TYPE_FLOAT) and float(raw_prof) > 0.0:
		return float(raw_prof)
	return DEFAULT_LOD_DISTANCIA_M


static func _coletar_mesh_instances(root: Node) -> Array[MeshInstance3D]:
	var resultado: Array[MeshInstance3D] = []
	if root is MeshInstance3D:
		resultado.append(root as MeshInstance3D)
	for node in root.find_children("*", "MeshInstance3D", true, false):
		var mi := node as MeshInstance3D
		if mi != null:
			resultado.append(mi)
	return resultado


static func _coletar_lod_nodes_dfs(nodo: Node, saida: Array[Node3D]) -> void:
	if (nodo is MeshInstance3D or nodo is ImporterMeshInstance3D) and _extrair_mesh_node(nodo) != null:
		saida.append(nodo as Node3D)
	for filho in nodo.get_children():
		_coletar_lod_nodes_dfs(filho, saida)


static func _coletar_lod_nodes(root: Node) -> Array[Node3D]:
	var resultado: Array[Node3D] = []
	_coletar_lod_nodes_dfs(root, resultado)
	return resultado


static func _nome_base_lod(nome: String) -> String:
	var base := nome
	for pref in ["LOD0_", "LOD1_", "LOD2_"]:
		if base.begins_with(pref):
			base = base.substr(pref.length())
			break
	for suf in ["_LOD0", "_LOD1", "_LOD2"]:
		if base.ends_with(suf):
			base = base.substr(0, base.length() - suf.length())
			break
	return base


static func _instanciar_lod_mesh(
	src_node: Node3D,
	nome_lod: String,
	destino: Node,
	scene: Node,
	vis_begin: float,
	vis_end: float,
	src_root: Node = null
) -> void:
	var src_mesh := _extrair_mesh_node(src_node)
	if src_mesh == null:
		return
	var lod_mi := MeshInstance3D.new()
	lod_mi.name = nome_lod
	lod_mi.mesh = src_mesh
	var src_xform := _transform_relativo(src_node, src_root) if src_root != null else src_node.transform
	var dst_xform := _transform_relativo(destino, scene)
	lod_mi.transform = dst_xform.affine_inverse() * src_xform
	if src_node is MeshInstance3D:
		var src_mi := src_node as MeshInstance3D
		lod_mi.skin = src_mi.skin
		lod_mi.material_override = src_mi.material_override
		for idx in range(src_mi.get_surface_override_material_count()):
			lod_mi.set_surface_override_material(idx, src_mi.get_surface_override_material(idx))
	elif src_node is ImporterMeshInstance3D:
		var src_imi := src_node as ImporterMeshInstance3D
		lod_mi.skin = src_imi.skin
	lod_mi.visibility_range_begin = vis_begin
	lod_mi.visibility_range_end = vis_end
	lod_mi.visibility_range_begin_margin = 1.0 if vis_begin > 0.0 else 0.0
	lod_mi.visibility_range_end_margin = 1.0 if vis_end > 0.0 else 0.0
	lod_mi.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF

	destino.add_child(lod_mi)
	lod_mi.owner = scene
	if lod_mi.skin != null:
		var skels := scene.find_children("*", "Skeleton3D", true, false)
		var skel: Node = scene if scene is Skeleton3D else (skels[0] if not skels.is_empty() else null)
		if skel != null:
			lod_mi.skeleton = lod_mi.get_path_to(skel)
	else:
		lod_mi.skeleton = NodePath("")


static func _anexar_lods(scene: Node, source_file: String, manifesto: Dictionary, perfil_cfg: Dictionary = {}) -> void:
	var lod0_meshes := _coletar_mesh_instances(scene)
	if lod0_meshes.is_empty():
		return
	for mi in lod0_meshes:
		var nome := String(mi.name)
		if nome.begins_with("LOD1_") or nome.contains("_LOD1"):
			return

	var entradas_validas: Array[Dictionary] = []
	for item in _caminhos_lods_irmaos(source_file, manifesto):
		var cam := str(item["caminho"])
		if cam != "" and FileAccess.file_exists(cam):
			var lod_cena := _carregar_glb(cam)
			if lod_cena != null:
				var meshes := _coletar_lod_nodes(lod_cena)
				if not meshes.is_empty():
					entradas_validas.append({"nivel": int(item["nivel"]), "distancia_m": item["distancia_m"], "cena": lod_cena, "meshes": meshes})
				else:
					lod_cena.free()
	if entradas_validas.is_empty():
		return

	var base_dist := _obter_lod_distancia_m(manifesto, perfil_cfg, lod0_meshes, scene)
	var primeiro_custom: Variant = entradas_validas[0].get("distancia_m", null)
	var dist_lod0 := (
		float(primeiro_custom)
		if (typeof(primeiro_custom) == TYPE_INT or typeof(primeiro_custom) == TYPE_FLOAT) and float(primeiro_custom) > 0.0
		else base_dist
	)
	for mi in lod0_meshes:
		mi.visibility_range_begin = 0.0
		mi.visibility_range_end = dist_lod0
		mi.visibility_range_begin_margin = 0.0
		mi.visibility_range_end_margin = 1.0
		mi.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF

	for idx_ent in range(entradas_validas.size()):
		var ent := entradas_validas[idx_ent]
		var nivel := int(ent["nivel"])
		var pref := "LOD%d_" % nivel
		var dist_custom: Variant = ent.get("distancia_m", null)
		var vis_begin := (
			float(dist_custom)
			if (typeof(dist_custom) == TYPE_INT or typeof(dist_custom) == TYPE_FLOAT) and float(dist_custom) > 0.0
			else (dist_lod0 * float(idx_ent + 1))
		)
		var vis_end := 0.0
		if idx_ent + 1 < entradas_validas.size():
			var prox_custom: Variant = entradas_validas[idx_ent + 1].get("distancia_m", null)
			vis_end = (
				float(prox_custom)
				if (typeof(prox_custom) == TYPE_INT or typeof(prox_custom) == TYPE_FLOAT) and float(prox_custom) > 0.0
				else (dist_lod0 * float(idx_ent + 2))
			)

		var lod_meshes: Array = ent["meshes"]
		var lod_cena: Node = ent["cena"]
		var usados: Array[bool] = []
		usados.resize(lod_meshes.size())
		usados.fill(false)
		var pareados: Array[bool] = []
		pareados.resize(lod0_meshes.size())
		pareados.fill(false)

		for i in range(lod0_meshes.size()):
			var orig := lod0_meshes[i]
			var orig_nome := String(orig.name)
			var orig_base := _nome_base_lod(orig_nome)
			var escolhido := -1
			for j in range(lod_meshes.size()):
				if not usados[j]:
					var cand_nome := String(lod_meshes[j].name)
					if cand_nome == orig_nome or _nome_base_lod(cand_nome) == orig_base:
						escolhido = j
						break
			if escolhido >= 0:
				usados[escolhido] = true
				pareados[i] = true
				var destino: Node = orig.get_parent() if orig.get_parent() != null else scene
				_instanciar_lod_mesh(lod_meshes[escolhido], pref + orig_nome, destino, scene, vis_begin, vis_end, lod_cena)

		for i in range(lod0_meshes.size()):
			if pareados[i]:
				continue
			var escolhido := -1
			if i < lod_meshes.size() and not usados[i]:
				escolhido = i
			else:
				for j in range(lod_meshes.size()):
					if not usados[j]:
						escolhido = j
						break
			if escolhido >= 0:
				usados[escolhido] = true
				var orig := lod0_meshes[i]
				var destino: Node = orig.get_parent() if orig.get_parent() != null else scene
				_instanciar_lod_mesh(lod_meshes[escolhido], pref + String(orig.name), destino, scene, vis_begin, vis_end, lod_cena)

		for j in range(lod_meshes.size()):
			if not usados[j]:
				var src_extra: Node3D = lod_meshes[j]
				_instanciar_lod_mesh(src_extra, pref + _nome_base_lod(String(src_extra.name)), scene, scene, vis_begin, vis_end, lod_cena)

		lod_cena.free()


static func _aplicar_gi_static(scene: Node, manifesto: Dictionary) -> void:
	var tipo := str(manifesto.get("tipo", ""))
	if not (tipo in ["mapa_setor", "modulo_cenario", "prop_estatico"]):
		return
	for mi in _coletar_mesh_instances(scene):
		mi.gi_mode = GeometryInstance3D.GI_MODE_STATIC
