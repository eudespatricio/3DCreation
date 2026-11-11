@tool
extends EditorScenePostImport
## Post-importador Godot 4 para assets publicados pelo Forge3D.
## Pode ser usado como Import Script no .glb ou pelo plugin addons/forge3d.


func _post_import(scene: Node) -> Object:
	return aplicar(scene, get_source_file())


static func aplicar(scene: Node, source_file: String = "") -> Node:
	if scene == null:
		return scene
	var manifesto := _ler_manifesto(scene, source_file)
	if not manifesto.is_empty():
		_anexar_metadados(scene, manifesto)
	var convertidos := _converter_ucx(scene, scene)
	if convertidos == 0:
		_carregar_colisor_irmao(scene, source_file, manifesto)
	_anexar_lod1(scene, source_file, manifesto)
	_configurar_animacoes(scene)
	return scene


static func _ler_manifesto(scene: Node, source_file: String) -> Dictionary:
	var candidatos: Array[String] = []
	if source_file != "":
		candidatos.append(source_file.get_basename() + ".manifest.json")
		if scene.name != "":
			candidatos.append(source_file.get_base_dir().path_join(String(scene.name) + ".manifest.json"))
	for caminho in candidatos:
		if not FileAccess.file_exists(caminho):
			continue
		var texto := FileAccess.get_file_as_string(caminho)
		if texto == "":
			continue
		var parsed: Variant = JSON.parse_string(texto)
		if typeof(parsed) == TYPE_DICTIONARY:
			return parsed
	return {}


static func _anexar_metadados(scene: Node, manifesto: Dictionary) -> void:
	scene.set_meta("forge3d_manifest", manifesto)
	scene.set_meta("forge3d_asset_id", str(manifesto.get("asset_id", "")))
	scene.set_meta("forge3d_schema", str(manifesto.get("schema", "")))
	scene.set_meta("forge3d_perfil", str(manifesto.get("perfil", "")))
	scene.set_meta("forge3d_determinism", str(manifesto.get("determinism", "")))
	var unidades: Variant = manifesto.get("unidades_export", {})
	if typeof(unidades) == TYPE_DICTIONARY and not unidades.is_empty():
		scene.set_meta("forge3d_unidades_export", unidades)
		scene.set_meta("forge3d_escala_saida", float(unidades.get("escala_saida", 1.0)))
		scene.set_meta("forge3d_metros_por_unidade", float(unidades.get("metros_por_unidade", 1.0)))
	if manifesto.has("lod"):
		scene.set_meta("forge3d_lod", manifesto["lod"])
	if manifesto.has("geometry"):
		scene.set_meta("forge3d_geometry", manifesto["geometry"])


static func _criar_static_body(nome: String, xform: Transform3D, mesh: Mesh, parent: Node, root: Node) -> void:
	var body := StaticBody3D.new()
	body.name = nome + "_col"
	body.transform = xform
	var shape_node := CollisionShape3D.new()
	shape_node.name = "CollisionShape3D"
	shape_node.shape = mesh.create_convex_shape(true, true)
	parent.add_child(body)
	body.add_child(shape_node)
	body.owner = root
	shape_node.owner = root


static func _converter_ucx(nodo: Node, root: Node) -> int:
	var total := 0
	for filho in nodo.get_children().duplicate():
		if filho is MeshInstance3D and String(filho.name).begins_with("UCX_"):
			var mi := filho as MeshInstance3D
			if mi.mesh != null:
				_criar_static_body(String(mi.name), mi.transform, mi.mesh, nodo, root)
				total += 1
			nodo.remove_child(mi)
			mi.free()
		else:
			total += _converter_ucx(filho, root)
	return total


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
		if filho is MeshInstance3D and (filho as MeshInstance3D).mesh != null:
			saida.append({"nome": String(filho.name), "xform": local_xform, "mesh": (filho as MeshInstance3D).mesh})
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


static func _carregar_colisor_irmao(scene: Node, source_file: String, manifesto: Dictionary) -> void:
	var col_path := _caminho_colisor_irmao(source_file, manifesto)
	var col_cena := _carregar_glb(col_path)
	if col_cena == null:
		return
	var itens: Array = []
	_coletar_malhas_com_xform(col_cena, Transform3D.IDENTITY, itens)
	for item in itens:
		_criar_static_body(item["nome"], item["xform"], item["mesh"], scene, scene)
	col_cena.free()


static func _caminho_lod1_irmao(source_file: String, manifesto: Dictionary) -> String:
	if source_file == "" or manifesto.is_empty():
		return ""
	var lods: Variant = manifesto.get("lod", [])
	if typeof(lods) != TYPE_ARRAY:
		return ""
	for item in lods:
		if typeof(item) != TYPE_DICTIONARY:
			continue
		var nivel: Variant = item.get("nivel", -1)
		if (typeof(nivel) == TYPE_INT or typeof(nivel) == TYPE_FLOAT) and int(nivel) == 1:
			var arquivo: String = str(item.get("arquivo", ""))
			if arquivo != "":
				return source_file.get_base_dir().path_join(arquivo)
			return source_file.get_basename() + "_LOD1.glb"
	return ""


static func _coletar_mesh_instances(root: Node) -> Array[MeshInstance3D]:
	var resultado: Array[MeshInstance3D] = []
	if root is MeshInstance3D:
		resultado.append(root as MeshInstance3D)
	for node in root.find_children("*", "MeshInstance3D", true, false):
		var mi := node as MeshInstance3D
		if mi != null:
			resultado.append(mi)
	return resultado


static func _anexar_lod1(scene: Node, source_file: String, manifesto: Dictionary) -> void:
	var lod1_path := _caminho_lod1_irmao(source_file, manifesto)
	if lod1_path == "" or not FileAccess.file_exists(lod1_path):
		return
	var lod0_meshes := _coletar_mesh_instances(scene)
	if lod0_meshes.is_empty():
		return
	for mi in lod0_meshes:
		var nome := String(mi.name)
		if nome.begins_with("LOD1_") or nome.contains("_LOD1"):
			return
	var lod1_cena := _carregar_glb(lod1_path)
	if lod1_cena == null:
		return
	var lod1_meshes := _coletar_mesh_instances(lod1_cena)
	if lod1_meshes.is_empty():
		lod1_cena.free()
		return

	for mi in lod0_meshes:
		mi.visibility_range_begin = 0.0
		mi.visibility_range_end = 15.0
		mi.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF

	var orig := lod0_meshes[0]
	var src_mi := lod1_meshes[0]
	var lod1_mi := MeshInstance3D.new()
	lod1_mi.name = "LOD1_" + String(orig.name)
	lod1_mi.mesh = src_mi.mesh
	lod1_mi.transform = src_mi.transform
	lod1_mi.skin = src_mi.skin
	lod1_mi.material_override = src_mi.material_override
	for idx in range(src_mi.get_surface_override_material_count()):
		lod1_mi.set_surface_override_material(idx, src_mi.get_surface_override_material(idx))
	lod1_mi.visibility_range_begin = 15.0
	lod1_mi.visibility_range_end = 0.0
	lod1_mi.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF

	var destino: Node = orig.get_parent() if orig.get_parent() != null else scene
	destino.add_child(lod1_mi)
	lod1_mi.owner = scene
	if lod1_mi.skin != null:
		var skels := scene.find_children("*", "Skeleton3D", true, false)
		var skel: Node = scene if scene is Skeleton3D else (skels[0] if not skels.is_empty() else null)
		if skel != null:
			lod1_mi.skeleton = lod1_mi.get_path_to(skel)
	else:
		lod1_mi.skeleton = NodePath("")
	lod1_cena.free()


static func _configurar_animacoes(scene: Node) -> void:
	var modos := {
		"idle": Animation.LOOP_LINEAR,
		"walk": Animation.LOOP_LINEAR,
		"run": Animation.LOOP_LINEAR,
		"jump": Animation.LOOP_NONE,
	}
	for node in scene.find_children("*", "AnimationPlayer", true, false):
		var player := node as AnimationPlayer
		if player == null:
			continue
		for nome in modos.keys():
			if player.has_animation(nome):
				var anim: Animation = player.get_animation(nome)
				if anim != null:
					anim.loop_mode = modos[nome]


## Encapsula o node importado em um CharacterBody3D com colisao em capsula e BoneAttachment3D.
static func montar_character_body(
	body_node: Node,
	anexos: Dictionary = {},
	capsule_h: float = 1.85,
	capsule_r: float = 0.35,
	remover_static_body: bool = true
) -> CharacterBody3D:
	var char_body := CharacterBody3D.new()
	var col_shape := CollisionShape3D.new()
	col_shape.name = "CollisionShape3D"
	var capsule := CapsuleShape3D.new()
	if capsule_h > capsule.height:
		capsule.height = capsule_h
		capsule.radius = capsule_r
	else:
		capsule.radius = capsule_r
		capsule.height = capsule_h
	col_shape.shape = capsule
	col_shape.position = Vector3(0.0, capsule_h / 2.0, 0.0)
	char_body.add_child(col_shape)
	col_shape.owner = char_body

	if body_node == null:
		return char_body

	if body_node.get_parent() != null:
		body_node.get_parent().remove_child(body_node)
	char_body.add_child(body_node)
	if body_node.owner == null:
		body_node.owner = char_body

	if remover_static_body:
		for node in body_node.find_children("*", "StaticBody3D", true, false):
			var sb := node as StaticBody3D
			if sb != null and String(sb.name).ends_with("_col"):
				if sb.get_parent() != null:
					sb.get_parent().remove_child(sb)
				sb.free()

	if not anexos.is_empty():
		var skel: Skeleton3D = body_node as Skeleton3D
		if skel == null:
			var skels := body_node.find_children("*", "Skeleton3D", true, false)
			if not skels.is_empty():
				skel = skels[0] as Skeleton3D
		if skel != null:
			for osso_nome in anexos.keys():
				var anexo_node := anexos[osso_nome] as Node
				if anexo_node == null:
					continue
				if anexo_node.get_parent() != null:
					anexo_node.get_parent().remove_child(anexo_node)
				var attachment := BoneAttachment3D.new()
				attachment.name = "BoneAttachment_" + str(osso_nome)
				attachment.bone_name = str(osso_nome)
				skel.add_child(attachment)
				attachment.owner = char_body
				attachment.add_child(anexo_node)
				if anexo_node.owner == null:
					anexo_node.owner = char_body

	return char_body
