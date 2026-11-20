@tool
extends EditorScenePostImport
## Post-importador Godot 4 para assets publicados pelo Forge3D (fachada <= 500L).
## Pode ser usado como Import Script no .glb ou pelo plugin addons/forge3d.

const DEFAULT_LOD_DISTANCIA_M := 25.0
const Materials := preload("post_import_materials.gd")
const LodCol := preload("post_import_lod_col.gd")
const Rig := preload("post_import_rig.gd")


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
	if scene.has_meta("forge3d_post_imported"):
		return scene
	if _eh_arquivo_auxiliar(source_file):
		return scene
	var manifesto := _ler_manifesto(scene, source_file)
	if not manifesto.is_empty():
		_anexar_metadados(scene, manifesto)
	var perfil_cfg := _ler_perfil_yaml(manifesto)
	var shape_fn := func(mesh: Mesh) -> Shape3D:
		return mesh.create_convex_shape(true, false)
	var convertidos := LodCol._converter_ucx(scene, scene, shape_fn)
	if convertidos == 0 and not _eh_personagem_ou_rigged(manifesto) and not _eh_equipavel_ou_anexo(manifesto):
		LodCol._carregar_colisor_irmao(scene, source_file, manifesto, shape_fn)
	LodCol._anexar_lods(scene, source_file, manifesto, perfil_cfg)
	LodCol._aplicar_gi_static(scene, manifesto)
	Materials._configurar_materiais(scene, source_file, manifesto, perfil_cfg)
	_configurar_animacoes(scene, manifesto, source_file)
	_aplicar_bone_map(scene, manifesto)
	Rig._configurar_sockets(scene, manifesto)
	_aplicar_orientacao_frente(scene, manifesto, perfil_cfg)
	scene.set_meta("forge3d_post_imported", true)
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
	return manifesto.get("rig", null) != null


static func _eh_equipavel_ou_anexo(manifesto: Dictionary) -> bool:
	if manifesto.is_empty():
		return false
	if str(manifesto.get("tipo", "")) == "prop_equipavel":
		return true
	return manifesto.get("anexo", null) != null


static func _ler_import_subresources_animacoes(source_file: String) -> Dictionary:
	var overrides := {}
	if source_file == "":
		return overrides
	var import_path := source_file if source_file.ends_with(".import") else (source_file + ".import")
	if not FileAccess.file_exists(import_path):
		return overrides
	var cf := ConfigFile.new()
	if cf.load(import_path) != OK:
		return overrides
	var sub: Variant = cf.get_value("params", "_subresources", null)
	if typeof(sub) != TYPE_DICTIONARY:
		return overrides
	var anims: Variant = (sub as Dictionary).get("animations", null)
	if typeof(anims) != TYPE_DICTIONARY:
		return overrides
	for clip_raw in (anims as Dictionary).keys():
		var clip_cfg: Variant = (anims as Dictionary)[clip_raw]
		if typeof(clip_cfg) != TYPE_DICTIONARY:
			continue
		var cfg_dict := clip_cfg as Dictionary
		if not cfg_dict.has("settings/loop_mode") or cfg_dict.get("settings/loop_mode") == null:
			continue
		var raw_mode: Variant = cfg_dict["settings/loop_mode"]
		var mode := -1
		if typeof(raw_mode) == TYPE_INT or typeof(raw_mode) == TYPE_FLOAT:
			var m_int := int(raw_mode)
			if m_int == Animation.LOOP_NONE or m_int == Animation.LOOP_LINEAR or m_int == Animation.LOOP_PINGPONG:
				mode = m_int
		elif typeof(raw_mode) == TYPE_BOOL:
			mode = Animation.LOOP_LINEAR if bool(raw_mode) else Animation.LOOP_NONE
		if mode == -1:
			continue
		var clip_key := str(clip_raw).strip_edges().to_lower()
		if clip_key != "":
			overrides[clip_key] = mode
	return overrides


static func _configurar_animacoes(scene: Node, manifesto: Dictionary = {}, source_file: String = "") -> void:
	var modos := {
		"idle": Animation.LOOP_LINEAR,
		"walk": Animation.LOOP_LINEAR,
		"run": Animation.LOOP_LINEAR,
		"gallop": Animation.LOOP_LINEAR,
		"wing_flap": Animation.LOOP_LINEAR,
		"glide": Animation.LOOP_LINEAR,
		"ride_idle": Animation.LOOP_LINEAR,
		"ride_fly": Animation.LOOP_LINEAR,
		"jump": Animation.LOOP_NONE,
		"attack": Animation.LOOP_NONE,
		"slash_combo": Animation.LOOP_NONE,
		"cast": Animation.LOOP_NONE,
		"block": Animation.LOOP_NONE,
		"hit": Animation.LOOP_NONE,
		"death": Animation.LOOP_NONE,
		"bite": Animation.LOOP_NONE,
		"roar": Animation.LOOP_NONE,
		"tail_swipe": Animation.LOOP_NONE,
		"land": Animation.LOOP_NONE,
		"rear_up": Animation.LOOP_NONE,
		"mount_up": Animation.LOOP_NONE,
		"dismount": Animation.LOOP_NONE,
	}
	var import_overrides := _ler_import_subresources_animacoes(source_file)
	var manifest_overrides := {}
	var raw_anims: Variant = manifesto.get("animacoes", [])
	if typeof(raw_anims) == TYPE_ARRAY:
		for entry_var in raw_anims:
			if typeof(entry_var) != TYPE_DICTIONARY:
				continue
			var entry: Dictionary = entry_var
			if not entry.has("loop") or entry.get("loop") == null:
				continue
			var raw_nome: Variant = entry.get("nome", null)
			var clip_nome := ("" if raw_nome == null else str(raw_nome)).strip_edges().to_lower()
			if clip_nome == "":
				var raw_name: Variant = entry.get("name", null)
				clip_nome = ("" if raw_name == null else str(raw_name)).strip_edges().to_lower()
			if clip_nome == "":
				continue
			manifest_overrides[clip_nome] = Animation.LOOP_LINEAR if bool(entry["loop"]) else Animation.LOOP_NONE

	for node in scene.find_children("*", "AnimationPlayer", true, false):
		var player := node as AnimationPlayer
		if player == null:
			continue
		for anim_name_raw in player.get_animation_list():
			var anim_name := String(anim_name_raw)
			var key := anim_name.strip_edges().to_lower()
			var base_key := key
			if key.contains("|"):
				base_key = key.substr(key.rfind("|") + 1).strip_edges()
			var target_mode := -1
			if manifest_overrides.has(key):
				target_mode = manifest_overrides[key]
			elif import_overrides.has(key):
				target_mode = import_overrides[key]
			elif base_key != key and manifest_overrides.has(base_key):
				target_mode = manifest_overrides[base_key]
			elif base_key != key and import_overrides.has(base_key):
				target_mode = import_overrides[base_key]
			elif modos.has(key):
				target_mode = modos[key]
			elif base_key != key and modos.has(base_key):
				target_mode = modos[base_key]
			if target_mode != -1:
				var anim: Animation = player.get_animation(anim_name)
				if anim != null:
					anim.loop_mode = target_mode


static func criar_bone_map_humanoid(esqueleto: String = "") -> BoneMap:
	var bone_map := BoneMap.new()
	bone_map.profile = SkeletonProfileHumanoid.new()
	var esq := esqueleto.strip_edges().to_lower()
	var pares := {}
	if esq == "godot-humanoid-aa@1":
		pares = {
			"Root": "Root",
			"Hips": "Hips",
			"Spine": "Spine",
			"Chest": "Chest",
			"UpperChest": "Chest",
			"Neck": "Neck",
			"Head": "Head",
			"LeftEye": "Eye.L",
			"RightEye": "Eye.R",
			"Jaw": "Jaw",
			"LeftShoulder": "Shoulder.L",
			"LeftUpperArm": "UpperArm.L",
			"LeftLowerArm": "LowerArm.L",
			"LeftHand": "Hand.L",
			"LeftThumbMetacarpal": "Thumb1.L",
			"LeftThumbProximal": "Thumb2.L",
			"LeftThumbDistal": "Thumb3.L",
			"LeftIndexProximal": "Index1.L",
			"LeftIndexIntermediate": "Index2.L",
			"LeftIndexDistal": "Index3.L",
			"LeftMiddleProximal": "Middle1.L",
			"LeftMiddleIntermediate": "Middle2.L",
			"LeftMiddleDistal": "Middle3.L",
			"LeftRingProximal": "Ring1.L",
			"LeftRingIntermediate": "Ring2.L",
			"LeftRingDistal": "Ring3.L",
			"LeftLittleProximal": "Little1.L",
			"LeftLittleIntermediate": "Little2.L",
			"LeftLittleDistal": "Little3.L",
			"RightShoulder": "Shoulder.R",
			"RightUpperArm": "UpperArm.R",
			"RightLowerArm": "LowerArm.R",
			"RightHand": "Hand.R",
			"RightThumbMetacarpal": "Thumb1.R",
			"RightThumbProximal": "Thumb2.R",
			"RightThumbDistal": "Thumb3.R",
			"RightIndexProximal": "Index1.R",
			"RightIndexIntermediate": "Index2.R",
			"RightIndexDistal": "Index3.R",
			"RightMiddleProximal": "Middle1.R",
			"RightMiddleIntermediate": "Middle2.R",
			"RightMiddleDistal": "Middle3.R",
			"RightRingProximal": "Ring1.R",
			"RightRingIntermediate": "Ring2.R",
			"RightRingDistal": "Ring3.R",
			"RightLittleProximal": "Little1.R",
			"RightLittleIntermediate": "Little2.R",
			"RightLittleDistal": "Little3.R",
			"LeftUpperLeg": "UpperLeg.L",
			"LeftLowerLeg": "LowerLeg.L",
			"LeftFoot": "Foot.L",
			"LeftToes": "Toe.L",
			"RightUpperLeg": "UpperLeg.R",
			"RightLowerLeg": "LowerLeg.R",
			"RightFoot": "Foot.R",
			"RightToes": "Toe.R",
		}
	else:
		pares = {
			"Root": "Root",
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


static func _eh_esqueleto_humanoide(esqueleto: String) -> bool:
	var esq := esqueleto.strip_edges().to_lower()
	if esq == "" or esq.begins_with("quadruped") or esq.begins_with("winged_mount"):
		return false
	return esq.begins_with("godot-humanoid") or esq.begins_with("humanoid")


static func _aplicar_bone_map(scene: Node, manifesto: Dictionary) -> void:
	var rig: Variant = manifesto.get("rig", null)
	if typeof(rig) != TYPE_DICTIONARY:
		return
	var esq := str((rig as Dictionary).get("esqueleto", ""))
	if not _eh_esqueleto_humanoide(esq):
		scene.set_meta("forge3d_bone_map_skipped", esq)
		return
	scene.set_meta("forge3d_bone_map", criar_bone_map_humanoid(esq))


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


static func _carregar_textura(caminho: String) -> Texture2D:
	return Materials._carregar_textura(caminho)


static func _processar_material(
	mat: Material,
	orm_tex: Texture2D,
	normal_tex: Texture2D,
	base_color_tex: Texture2D,
	usar_nearest: bool
) -> Material:
	return Materials._processar_material(mat, orm_tex, normal_tex, base_color_tex, usar_nearest)


static func _configurar_materiais(
	scene: Node,
	source_file: String,
	manifesto: Dictionary,
	perfil_cfg: Dictionary
) -> void:
	Materials._configurar_materiais(scene, source_file, manifesto, perfil_cfg)


static func _configurar_sockets(scene: Node, manifesto: Dictionary) -> void:
	Rig._configurar_sockets(scene, manifesto)


static func montar_cavaleiro_em_montaria(cavaleiro: Node3D, montaria: Node3D) -> Node3D:
	return Rig.montar_cavaleiro_em_montaria(cavaleiro, montaria)


static func attach_skinned_mesh(mesh_inst: MeshInstance3D, target_skel: Skeleton3D) -> bool:
	return Rig.attach_skinned_mesh(mesh_inst, target_skel)


static func montar_character_body(
	body_node: Node,
	anexos: Dictionary = {},
	capsule_h: float = 1.85,
	capsule_r: float = 0.35,
	remover_static_body: bool = true
) -> CharacterBody3D:
	return Rig.montar_character_body(body_node, anexos, capsule_h, capsule_r, remover_static_body)
