@tool
extends EditorScenePostImport
## Post-importador Godot 4 para assets publicados pelo Forge3D.
## Pode ser usado como Import Script no .glb ou pelo plugin addons/forge3d.

const DEFAULT_LOD_DISTANCIA_M := 25.0


func _post_import(scene: Node) -> Object:
	return aplicar(scene, get_source_file())


static func _eh_arquivo_auxiliar(source_file: String) -> bool:
	if source_file == "":
		return false
	var stem := source_file.get_file().get_basename()
	if stem.ends_with("_colisao"):
		return true
	for i in range(1, 10):
		if stem.ends_with("_LOD" + str(i)):
			return true
	return false


static func aplicar(scene: Node, source_file: String = "") -> Node:
	if scene == null:
		return scene
	if _eh_arquivo_auxiliar(source_file):
		return scene
	var manifesto := _ler_manifesto(scene, source_file)
	if not manifesto.is_empty():
		_anexar_metadados(scene, manifesto)
	var perfil_cfg := _ler_perfil_yaml(manifesto)
	var convertidos := _converter_ucx(scene, scene)
	if convertidos == 0 and not _eh_personagem_ou_rigged(manifesto) and not _eh_equipavel_ou_anexo(manifesto):
		_carregar_colisor_irmao(scene, source_file, manifesto)
	_anexar_lods(scene, source_file, manifesto, perfil_cfg)
	_configurar_materiais(scene, source_file, manifesto, perfil_cfg)
	_configurar_animacoes(scene)
	_aplicar_bone_map(scene, manifesto)
	_aplicar_orientacao_frente(scene, manifesto, perfil_cfg)
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


static func _limpar_valor_yaml(bruto: String) -> String:
	var sem_comentario := bruto
	var in_quotes := false
	var quote_char := ""
	for i in range(bruto.length()):
		var ch := bruto.substr(i, 1)
		if (ch == "\"" or ch == "'") and (i == 0 or bruto.substr(i - 1, 1) != "\\"):
			if not in_quotes:
				in_quotes = true
				quote_char = ch
			elif ch == quote_char:
				in_quotes = false
				quote_char = ""
		elif ch == "#" and not in_quotes:
			sem_comentario = bruto.substr(0, i)
			break
	var limpo := sem_comentario.strip_edges()
	if limpo.length() >= 2:
		if (limpo.begins_with("\"") and limpo.ends_with("\"")) or (limpo.begins_with("'") and limpo.ends_with("'")):
			limpo = limpo.substr(1, limpo.length() - 2)
	return limpo


static func _ler_perfil_yaml(manifesto: Dictionary) -> Dictionary:
	var perfil := str(manifesto.get("perfil", ""))
	if perfil == "":
		return {}
	var res_dir := ProjectSettings.globalize_path("res://")
	var candidatos: Array[String] = [
		"res://profiles/%s.yaml" % perfil,
		res_dir.path_join("profiles/%s.yaml" % perfil),
		res_dir.path_join("../../profiles/%s.yaml" % perfil),
	]
	var texto := ""
	for caminho in candidatos:
		if FileAccess.file_exists(caminho):
			texto = FileAccess.get_file_as_string(caminho)
			if texto != "":
				break
	if texto == "":
		return {}

	var cfg: Dictionary = {}
	var secao := ""
	for linha_raw in texto.split("\n"):
		var linha := linha_raw.replace("\r", "")
		var stripped := linha.strip_edges()
		if stripped == "" or stripped.begins_with("#"):
			continue
		var indent := linha.length() - linha.lstrip(" \t").length()
		var idx := stripped.find(":")
		if idx <= 0:
			continue
		var chave := stripped.substr(0, idx).strip_edges()
		var valor := _limpar_valor_yaml(stripped.substr(idx + 1))
		if indent == 0:
			secao = chave
			continue
		if secao == "lod" and (chave == "distancia_m" or chave == "lod_distancia_m"):
			if valor.is_valid_float():
				cfg["lod_distancia_m"] = float(valor)
		elif secao == "material" and chave == "filtro":
			cfg["filtro"] = valor
		elif secao == "eixos" and chave == "frente":
			cfg["frente"] = valor
	return cfg


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


static func _eh_personagem_ou_rigged(manifesto: Dictionary) -> bool:
	if manifesto.is_empty():
		return false
	if str(manifesto.get("tipo", "")) == "personagem_humanoide":
		return true
	var rig: Variant = manifesto.get("rig", null)
	return rig != null


static func _eh_equipavel_ou_anexo(manifesto: Dictionary) -> bool:
	if manifesto.is_empty():
		return false
	if str(manifesto.get("tipo", "")) == "prop_equipavel":
		return true
	return manifesto.get("anexo", null) != null


static func _criar_static_body(nome: String, xform: Transform3D, mesh: Mesh, parent: Node, root: Node) -> void:
	var body := StaticBody3D.new()
	body.name = nome + "_col"
	body.transform = xform
	var shape_node := CollisionShape3D.new()
	shape_node.name = "CollisionShape3D"
	shape_node.shape = mesh.create_convex_shape(true, false)
	parent.add_child(body)
	body.add_child(shape_node)
	body.owner = root
	shape_node.owner = root


static func _transform_relativo(nodo: Node, ancestral: Node) -> Transform3D:
	var acum := Transform3D.IDENTITY
	var cur: Node = nodo
	while cur != null and cur != ancestral:
		if cur is Node3D:
			acum = (cur as Node3D).transform * acum
		cur = cur.get_parent()
	return acum


static func _converter_ucx(nodo: Node, root: Node) -> int:
	var total := 0
	for filho in nodo.get_children().duplicate():
		if filho is MeshInstance3D and String(filho.name).begins_with("UCX_"):
			var mi := filho as MeshInstance3D
			if mi.mesh != null:
				var xform_rel := _transform_relativo(mi, root)
				_criar_static_body(String(mi.name), xform_rel, mi.mesh, root, root)
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


static func _obter_lod_distancia_m(manifesto: Dictionary, perfil_cfg: Dictionary) -> float:
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
	src_mi: MeshInstance3D,
	nome_lod: String,
	destino: Node,
	scene: Node,
	vis_begin: float,
	vis_end: float,
	src_root: Node = null
) -> void:
	var lod_mi := MeshInstance3D.new()
	lod_mi.name = nome_lod
	lod_mi.mesh = src_mi.mesh
	var src_xform := _transform_relativo(src_mi, src_root) if src_root != null else src_mi.transform
	var dst_xform := _transform_relativo(destino, scene)
	lod_mi.transform = dst_xform.affine_inverse() * src_xform
	lod_mi.skin = src_mi.skin
	lod_mi.material_override = src_mi.material_override
	for idx in range(src_mi.get_surface_override_material_count()):
		lod_mi.set_surface_override_material(idx, src_mi.get_surface_override_material(idx))
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


static func _anexar_lod1(scene: Node, source_file: String, manifesto: Dictionary, perfil_cfg: Dictionary = {}) -> void:
	_anexar_lods(scene, source_file, manifesto, perfil_cfg)


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
				var meshes := _coletar_mesh_instances(lod_cena)
				if not meshes.is_empty():
					entradas_validas.append({"nivel": int(item["nivel"]), "distancia_m": item["distancia_m"], "cena": lod_cena, "meshes": meshes})
				else:
					lod_cena.free()
	if entradas_validas.is_empty():
		return

	var base_dist := _obter_lod_distancia_m(manifesto, perfil_cfg)
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
				if usados[j]:
					continue
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
				var src_extra: MeshInstance3D = lod_meshes[j]
				_instanciar_lod_mesh(src_extra, pref + _nome_base_lod(String(src_extra.name)), scene, scene, vis_begin, vis_end, lod_cena)

		lod_cena.free()


static func _caminho_textura_irma(source_file: String, manifesto: Dictionary, papel: String, sufixo: String) -> String:
	if source_file == "":
		return ""
	var base_dir := source_file.get_base_dir()
	var arquivos: Variant = manifesto.get("files", [])
	if typeof(arquivos) == TYPE_ARRAY:
		for item in arquivos:
			if typeof(item) != TYPE_DICTIONARY:
				continue
			if str(item.get("papel", "")) == papel:
				var rel := str(item.get("caminho", ""))
				if rel != "":
					var cand := base_dir.path_join(rel)
					if FileAccess.file_exists(cand):
						return cand
	var fallback := source_file.get_basename() + sufixo
	if FileAccess.file_exists(fallback):
		return fallback
	return ""


static func _carregar_textura(caminho: String) -> Texture2D:
	if caminho == "" or not FileAccess.file_exists(caminho):
		return null
	if caminho.begins_with("res://") and ResourceLoader.exists(caminho):
		var res := ResourceLoader.load(caminho)
		if res is Texture2D:
			return res as Texture2D
	var img := Image.load_from_file(caminho)
	if img == null or img.is_empty():
		return null
	if not img.has_mipmaps():
		img.generate_mipmaps()
	return ImageTexture.create_from_image(img)


static func _usar_filtro_nearest(manifesto: Dictionary, perfil_cfg: Dictionary) -> bool:
	var filtro := ""
	var mat_cfg: Variant = manifesto.get("material", null)
	if typeof(mat_cfg) == TYPE_DICTIONARY:
		filtro = str((mat_cfg as Dictionary).get("filtro", ""))
	if filtro == "":
		filtro = str(manifesto.get("filtro", manifesto.get("texture_filter", "")))
	if filtro != "":
		return filtro.to_lower() == "nearest"
	if str(manifesto.get("rota", "")) == "blocky":
		return true
	if str(manifesto.get("rota", "")) != "":
		return false
	return str(perfil_cfg.get("filtro", "")).to_lower() == "nearest"


static func _copiar_base_material(src: BaseMaterial3D, dst: BaseMaterial3D) -> void:
	dst.resource_name = src.resource_name
	dst.albedo_color = src.albedo_color
	dst.albedo_texture = src.albedo_texture
	dst.cull_mode = src.cull_mode
	dst.transparency = src.transparency
	dst.alpha_scissor_threshold = src.alpha_scissor_threshold
	dst.roughness = src.roughness
	dst.metallic = src.metallic
	dst.ao_enabled = src.ao_enabled
	dst.ao_light_affect = src.ao_light_affect
	dst.normal_enabled = src.normal_enabled
	dst.normal_texture = src.normal_texture
	dst.normal_scale = src.normal_scale
	dst.emission_enabled = src.emission_enabled
	dst.emission = src.emission
	dst.emission_energy_multiplier = src.emission_energy_multiplier
	dst.emission_texture = src.emission_texture
	dst.uv1_scale = src.uv1_scale
	dst.uv1_offset = src.uv1_offset
	dst.texture_filter = src.texture_filter


static func _processar_material(
	mat: Material,
	orm_tex: Texture2D,
	normal_tex: Texture2D,
	base_color_tex: Texture2D,
	usar_nearest: bool
) -> Material:
	var resultado: Material = mat
	if orm_tex != null:
		var orm_mat: ORMMaterial3D
		if mat is ORMMaterial3D:
			orm_mat = mat as ORMMaterial3D
		else:
			orm_mat = ORMMaterial3D.new()
			if mat is BaseMaterial3D:
				var src_bm := mat as BaseMaterial3D
				_copiar_base_material(src_bm, orm_mat)
				if src_bm.metallic_texture == null and src_bm.metallic == 0.0:
					orm_mat.metallic = 1.0
				if src_bm.roughness_texture == null:
					orm_mat.roughness = 1.0
			else:
				orm_mat.metallic = 1.0
				orm_mat.roughness = 1.0
		orm_mat.orm_texture = orm_tex
		orm_mat.ao_enabled = true
		resultado = orm_mat
	elif resultado == null and (normal_tex != null or base_color_tex != null):
		resultado = StandardMaterial3D.new()

	if resultado is BaseMaterial3D:
		var bm := resultado as BaseMaterial3D
		if bm.normal_texture != null:
			bm.normal_enabled = true
		elif normal_tex != null:
			bm.normal_enabled = true
			bm.normal_texture = normal_tex
		if base_color_tex != null and bm.albedo_texture == null:
			bm.albedo_texture = base_color_tex
		if bm.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR or String(bm.resource_name).to_lower().contains("cabelo"):
			bm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR
			if bm.alpha_scissor_threshold <= 0.0:
				bm.alpha_scissor_threshold = 0.5
			if String(bm.resource_name).to_lower().contains("cabelo") or String(bm.resource_name).to_lower().contains("hair"):
				bm.cull_mode = BaseMaterial3D.CULL_DISABLED
		bm.texture_filter = (
			BaseMaterial3D.TEXTURE_FILTER_NEAREST_WITH_MIPMAPS
			if usar_nearest
			else BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
		)
	return resultado


static func _configurar_materiais(
	scene: Node,
	source_file: String,
	manifesto: Dictionary,
	perfil_cfg: Dictionary
) -> void:
	var normal_tex := _carregar_textura(_caminho_textura_irma(source_file, manifesto, "normal", "_normal.png"))
	var orm_tex := _carregar_textura(_caminho_textura_irma(source_file, manifesto, "orm", "_orm.png"))
	var base_color_tex := _carregar_textura(_caminho_textura_irma(source_file, manifesto, "textura", "_baseColor.png"))
	var usar_nearest := _usar_filtro_nearest(manifesto, perfil_cfg)

	for mi in _coletar_mesh_instances(scene):
		if mi.material_override != null:
			mi.material_override = _processar_material(
				mi.material_override, orm_tex, normal_tex, base_color_tex, usar_nearest
			)
		if mi.mesh == null:
			continue
		var surf_count := mi.mesh.get_surface_count()
		for idx in range(surf_count):
			var override := mi.get_surface_override_material(idx)
			var alvo_mat: Material = override if override != null else mi.mesh.surface_get_material(idx)
			var tem_tex_propria := (
				idx > 0
				and surf_count > 1
				and alvo_mat is BaseMaterial3D
				and (alvo_mat as BaseMaterial3D).albedo_texture != null
			)
			var s_orm := null if tem_tex_propria else orm_tex
			var s_nm := null if tem_tex_propria else normal_tex
			var s_bc := null if tem_tex_propria else base_color_tex
			if override != null:
				mi.set_surface_override_material(
					idx, _processar_material(override, s_orm, s_nm, s_bc, usar_nearest)
				)
			else:
				var novo := _processar_material(alvo_mat, s_orm, s_nm, s_bc, usar_nearest)
				if novo != null:
					mi.mesh.surface_set_material(idx, novo)


static func _configurar_animacoes(scene: Node) -> void:
	var modos := {
		"idle": Animation.LOOP_LINEAR,
		"walk": Animation.LOOP_LINEAR,
		"run": Animation.LOOP_LINEAR,
		"jump": Animation.LOOP_NONE,
		"attack": Animation.LOOP_NONE,
		"block": Animation.LOOP_NONE,
		"hit": Animation.LOOP_NONE,
		"death": Animation.LOOP_NONE,
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


static func criar_bone_map_humanoid() -> BoneMap:
	var bone_map := BoneMap.new()
	bone_map.profile = SkeletonProfileHumanoid.new()
	var pares := {
		"Hips": "Hips",
		"Spine": "Spine",
		"Chest": "Spine1",
		"UpperChest": "Chest",
		"Neck": "Neck",
		"Head": "Head",
		"LeftShoulder": "Shoulder.L",
		"LeftUpperArm": "UpperArm.L",
		"LeftLowerArm": "LowerArm.L",
		"LeftHand": "Hand.L",
		"RightShoulder": "Shoulder.R",
		"RightUpperArm": "UpperArm.R",
		"RightLowerArm": "LowerArm.R",
		"RightHand": "Hand.R",
		"LeftUpperLeg": "UpperLeg.L",
		"LeftLowerLeg": "LowerLeg.L",
		"LeftFoot": "Foot.L",
		"LeftToes": "Toe.L",
		"RightUpperLeg": "UpperLeg.R",
		"RightLowerLeg": "LowerLeg.R",
		"RightFoot": "Foot.R",
		"RightToes": "Toe.R",
	}
	for prof_name in pares.keys():
		bone_map.set_skeleton_bone_name(prof_name, pares[prof_name])
	return bone_map


static func _aplicar_bone_map(scene: Node, manifesto: Dictionary) -> void:
	var rig: Variant = manifesto.get("rig", null)
	if typeof(rig) != TYPE_DICTIONARY:
		return
	var esq := str((rig as Dictionary).get("esqueleto", ""))
	if esq.begins_with("godot-humanoid"):
		scene.set_meta("forge3d_bone_map", criar_bone_map_humanoid())


static func _frente_mais_z(manifesto: Dictionary, perfil_cfg: Dictionary) -> bool:
	if bool(manifesto.get("girar_180_y", false)):
		return true
	var frente := str(manifesto.get("frente", manifesto.get("orientacao_frente", "")))
	if frente == "":
		var eixos: Variant = manifesto.get("eixos", null)
		if typeof(eixos) == TYPE_DICTIONARY:
			frente = str((eixos as Dictionary).get("frente", ""))
	if frente == "":
		frente = str(perfil_cfg.get("frente", ""))
	return frente.strip_edges().to_upper() == "+Z"


static func _aplicar_orientacao_frente(scene: Node, manifesto: Dictionary, perfil_cfg: Dictionary) -> void:
	if not (scene is Node3D):
		return
	if scene.has_meta("forge3d_turned_180_y"):
		return
	if _frente_mais_z(manifesto, perfil_cfg):
		(scene as Node3D).rotate_y(PI)
		scene.set_meta("forge3d_turned_180_y", true)


## Vincula uma malha modular skinned (armadura/roupa/capa) diretamente a um Skeleton3D alvo.
static func attach_skinned_mesh(mesh_inst: MeshInstance3D, target_skel: Skeleton3D) -> bool:
	if mesh_inst == null or target_skel == null:
		return false
	if mesh_inst.get_parent() != target_skel:
		if mesh_inst.get_parent() != null:
			mesh_inst.get_parent().remove_child(mesh_inst)
		target_skel.add_child(mesh_inst)
	if target_skel.owner != null:
		mesh_inst.owner = target_skel.owner
	elif mesh_inst.owner == null:
		mesh_inst.owner = target_skel
	mesh_inst.skeleton = mesh_inst.get_path_to(target_skel)
	return true


## Encapsula o node importado em um CharacterBody3D com colisao em capsula e BoneAttachment3D.
static func montar_character_body(
	body_node: Node,
	anexos: Dictionary = {},
	capsule_h: float = 1.85,
	capsule_r: float = 0.35,
	remover_static_body: bool = true
) -> CharacterBody3D:
	var cap_h := capsule_h
	var cap_r := capsule_r
	if body_node != null and body_node.has_meta("forge3d_geometry") and is_equal_approx(capsule_h, 1.85):
		var geom: Variant = body_node.get_meta("forge3d_geometry")
		if typeof(geom) == TYPE_DICTIONARY and (geom as Dictionary).has("bbox_m"):
			var bbox: Variant = (geom as Dictionary)["bbox_m"]
			if typeof(bbox) == TYPE_ARRAY and (bbox as Array).size() == 3:
				cap_h = max(0.4, float(bbox[1]))
				cap_r = max(0.15, max(float(bbox[0]), float(bbox[2])) * 0.42)
				if cap_h < cap_r * 2.0:
					cap_h = cap_r * 2.01

	var char_body := CharacterBody3D.new()
	var col_shape := CollisionShape3D.new()
	col_shape.name = "CollisionShape3D"
	var capsule := CapsuleShape3D.new()
	if cap_h > capsule.height:
		capsule.height = cap_h
		capsule.radius = cap_r
	else:
		capsule.radius = cap_r
		capsule.height = cap_h
	col_shape.shape = capsule
	col_shape.position = Vector3(0.0, cap_h / 2.0, 0.0)
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
				var bone_name := str(osso_nome)
				if skel.find_bone(bone_name) < 0:
					push_warning("Forge3D PostImport: osso '%s' nao encontrado em Skeleton3D" % bone_name)
					continue
				if anexo_node.get_parent() != null:
					anexo_node.get_parent().remove_child(anexo_node)
				var attachment := BoneAttachment3D.new()
				attachment.name = "BoneAttachment_" + bone_name
				attachment.bone_name = bone_name
				skel.add_child(attachment)
				attachment.owner = char_body
				if anexo_node is Node3D:
					_orientar_anexo_socket(anexo_node as Node3D, skel, bone_name)
				attachment.add_child(anexo_node)
				if anexo_node.owner == null:
					anexo_node.owner = char_body

	return char_body


static func _orientar_anexo_socket(n3d: Node3D, skel: Skeleton3D, bone_name: String) -> void:
	var bone_idx := skel.find_bone(bone_name)
	if bone_idx < 0:
		return
	var an_man: Variant = n3d.get_meta("forge3d_manifest", null)
	if typeof(an_man) != TYPE_DICTIONARY:
		return
	var an_info: Variant = (an_man as Dictionary).get("anexo", null)
	if typeof(an_info) != TYPE_DICTIONARY:
		return
	var an_dict := an_info as Dictionary
	var parte := str(an_dict.get("parte", "")).to_lower()
	if parte == "":
		return
	if an_dict.has("offset_rot"):
		var off: Variant = an_dict["offset_rot"]
		if typeof(off) == TYPE_ARRAY:
			var arr := off as Array
			if arr.size() == 3:
				n3d.basis = Basis.from_euler(Vector3(float(arr[0]), float(arr[1]), float(arr[2]))).scaled(n3d.scale)
				return
			if arr.size() == 4:
				n3d.basis = Basis(Quaternion(float(arr[0]), float(arr[1]), float(arr[2]), float(arr[3]))).scaled(n3d.scale)
				return

	var bone_rest_basis := skel.get_bone_global_rest(bone_idx).basis.orthonormalized()
	var target_basis_skel := Basis.IDENTITY
	var tratado := false
	if parte == "arma":
		# Arma em glTF tem ponta em +Y e fio em +X: aponta para frente (-Z) com fio vertical (+Y).
		target_basis_skel = Basis(Vector3(0.0, 1.0, 0.0), Vector3(0.0, 0.0, -1.0), Vector3(-1.0, 0.0, 0.0))
		tratado = true
	elif parte == "escudo":
		# Escudo em glTF tem topo em +Y e face convexa em -Z: mantem topo +Y e face externa para fora.
		var lado_r := bone_name.ends_with(".R") or bone_name.begins_with("Right")
		if lado_r:
			target_basis_skel = Basis(Vector3(0.0, 0.0, -1.0), Vector3(0.0, 1.0, 0.0), Vector3(1.0, 0.0, 0.0))
		else:
			target_basis_skel = Basis(Vector3(0.0, 0.0, 1.0), Vector3(0.0, 1.0, 0.0), Vector3(-1.0, 0.0, 0.0))
		tratado = true
	elif parte in ["elmo", "cabelo", "capa", "ombreiras", "peitoral", "luvas", "calcas", "calças", "botas"]:
		target_basis_skel = Basis.IDENTITY
		tratado = true
	if tratado:
		n3d.basis = (bone_rest_basis.inverse() * target_basis_skel).scaled(n3d.scale)
