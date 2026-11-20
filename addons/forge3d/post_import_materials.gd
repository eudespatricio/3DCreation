@tool
extends RefCounted
## Submodulo de materiais PBR/ORM e texturas para PostImport Godot 4.


static func _coletar_mesh_instances(root: Node) -> Array[MeshInstance3D]:
	var resultado: Array[MeshInstance3D] = []
	if root is MeshInstance3D:
		resultado.append(root as MeshInstance3D)
	for node in root.find_children("*", "MeshInstance3D", true, false):
		var mi := node as MeshInstance3D
		if mi != null:
			resultado.append(mi)
	return resultado


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
	if caminho == "":
		return null
	var res_path := caminho
	if not res_path.begins_with("res://"):
		var local := ProjectSettings.localize_path(caminho)
		if local.begins_with("res://"):
			res_path = local
	if res_path.begins_with("res://") and ResourceLoader.exists(res_path):
		var res := ResourceLoader.load(res_path)
		if res is Texture2D:
			return res as Texture2D
	if not FileAccess.file_exists(caminho):
		return null
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
	dst.refraction_enabled = src.refraction_enabled
	dst.refraction_scale = src.refraction_scale
	dst.uv1_scale = src.uv1_scale
	dst.uv1_offset = src.uv1_offset
	dst.texture_filter = src.texture_filter
	dst.shading_mode = src.shading_mode
	dst.vertex_color_use_as_albedo = src.vertex_color_use_as_albedo
	dst.vertex_color_is_srgb = src.vertex_color_is_srgb


static func _aplicar_fallback_dieletrico(alvo: BaseMaterial3D, ref: BaseMaterial3D) -> void:
	if ref.metallic_texture != null or ref.roughness_texture != null:
		return
	if ref.metallic >= 0.99 and ref.roughness >= 0.99:
		alvo.metallic = 0.0
		alvo.roughness = 0.65
		return
	if ref.transparency != BaseMaterial3D.TRANSPARENCY_DISABLED or ref.emission_enabled:
		return
	if ref.metallic <= 0.05 and ref.roughness >= 0.999:
		alvo.roughness = 0.65


static func _processar_material(
	mat: Material,
	orm_tex: Texture2D,
	normal_tex: Texture2D,
	base_color_tex: Texture2D,
	usar_nearest: bool
) -> Material:
	var resultado: Material = mat
	var criado_novo := false
	if orm_tex != null:
		var orm_mat: ORMMaterial3D
		if mat is ORMMaterial3D:
			orm_mat = mat as ORMMaterial3D
		else:
			orm_mat = ORMMaterial3D.new()
			if mat is BaseMaterial3D:
				_copiar_base_material(mat as BaseMaterial3D, orm_mat)
		orm_mat.orm_texture = orm_tex
		orm_mat.ao_enabled = true
		orm_mat.metallic = 1.0
		orm_mat.roughness = 1.0
		resultado = orm_mat
	elif resultado == null and (normal_tex != null or base_color_tex != null):
		var std_mat := StandardMaterial3D.new()
		std_mat.metallic = 0.0
		std_mat.roughness = 0.65
		resultado = std_mat
		criado_novo = true

	if resultado is BaseMaterial3D:
		var bm := resultado as BaseMaterial3D
		if orm_tex == null and not (bm is ORMMaterial3D) and not criado_novo:
			_aplicar_fallback_dieletrico(bm, bm)
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
			var override: Material = (
				mi.get_surface_override_material(idx)
				if idx < mi.get_surface_override_material_count()
				else null
			)
			var alvo_mat: Material = override if override != null else mi.mesh.surface_get_material(idx)
			var preservar_albedo := false
			if surf_count > 1 and idx > 0 and alvo_mat is BaseMaterial3D:
				var abm := alvo_mat as BaseMaterial3D
				preservar_albedo = (
					abm.albedo_texture != null
					or abm.transparency != BaseMaterial3D.TRANSPARENCY_DISABLED
					or abm.emission_enabled
					or abm.metallic > 0.05
				)
			var s_bc: Texture2D = null if preservar_albedo else base_color_tex
			if override != null:
				mi.set_surface_override_material(
					idx, _processar_material(override, orm_tex, normal_tex, s_bc, usar_nearest)
				)
			else:
				var novo := _processar_material(alvo_mat, orm_tex, normal_tex, s_bc, usar_nearest)
				if novo != null:
					mi.mesh.surface_set_material(idx, novo)
