extends SceneTree
## Validador visual e estrutural headless (Godot 4.x) para assets GLB do Forge3D.
##
## Uso:
##   godot --headless --path tools/godot_project --script "$PWD/tools/godot_visual_qa.gd" -- <glb> [more_glbs...]
## Saida:
##   GODOT_VISUAL_QA_OK ... (exit 0) ou GODOT_VISUAL_QA_FAIL ... (exit 1)

const PostImport := preload("../addons/forge3d/post_import.gd")

const TIPOS_ORGANICOS: Array[String] = [
	"personagem_humanoide",
	"criatura",
	"criatura_quadrupede",
	"criatura_alada",
	"montaria",
]

const CLIPES_CICLICOS: Array[String] = [
	"idle",
	"walk",
	"run",
	"gallop",
	"wing_flap",
	"glide",
	"ride_idle",
	"ride_fly",
]


func _fail(msg: String, cena: Node = null) -> void:
	print("GODOT_VISUAL_QA_FAIL " + msg)
	printerr("GODOT_VISUAL_QA_FAIL " + msg)
	if cena != null:
		cena.free()
	quit(1)


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		_fail("uso: godot --headless --path tools/godot_project --script tools/godot_visual_qa.gd -- <glb> [more_glbs...]")
		return

	var resumos: Array[String] = []
	for caminho in args:
		if caminho == "" or caminho == "-":
			continue
		var ok_msg := _validar_glb(caminho)
		if ok_msg == "":
			return
		resumos.append(ok_msg)

	if resumos.is_empty():
		_fail("nenhum arquivo GLB fornecido")
		return

	print("GODOT_VISUAL_QA_OK count=%d | %s" % [resumos.size(), " ; ".join(resumos)])
	quit(0)


func _validar_glb(caminho: String) -> String:
	var doc := GLTFDocument.new()
	var estado := GLTFState.new()
	var erro := doc.append_from_file(caminho, estado)
	if erro != OK:
		_fail("append_from_file(%s)=%d" % [caminho, erro])
		return ""
	var cena := doc.generate_scene(estado)
	if cena == null:
		_fail("cena nula em %s" % caminho)
		return ""

	var manifest_path := caminho.get_basename() + ".manifest.json"
	var manifesto: Dictionary = {}
	if FileAccess.file_exists(manifest_path):
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
		if typeof(parsed) == TYPE_DICTIONARY:
			manifesto = parsed

	if not cena.has_meta("forge3d_manifest") and cena.find_children("Socket_*", "Marker3D", true, false).is_empty():
		PostImport.aplicar(cena, caminho)

	if manifesto.is_empty() and cena.has_meta("forge3d_manifest"):
		var meta_m: Variant = cena.get_meta("forge3d_manifest")
		if typeof(meta_m) == TYPE_DICTIONARY:
			manifesto = meta_m

	var tipo := str(manifesto.get("tipo", ""))
	var rota := str(manifesto.get("rota", ""))
	var tem_rig_man := typeof(manifesto.get("rig", null)) == TYPE_DICTIONARY
	var tem_anexo_man := typeof(manifesto.get("anexo", null)) == TYPE_DICTIONARY
	var eh_organico := ((tipo in TIPOS_ORGANICOS) or (tem_rig_man and not tem_anexo_man)) and rota != "blocky"

	# 1. Inspeciona malhas, normais, facetamento organico e materiais PBR
	var mesh_nodes := cena.find_children("*", "MeshInstance3D", true, false)
	if mesh_nodes.is_empty():
		_fail("nenhum MeshInstance3D em %s" % caminho, cena)
		return ""

	var total_tris := 0
	var arestas_suaves := 0
	var arestas_facetadas := 0
	var aabb_min := Vector3(INF, INF, INF)
	var aabb_max := Vector3(-INF, -INF, -INF)

	for mnode in mesh_nodes:
		var mi := mnode as MeshInstance3D
		if mi == null or mi.mesh == null:
			continue
		var mesh := mi.mesh
		for s in range(mesh.get_surface_count()):
			var mat: Material = mi.get_surface_override_material(s)
			if mat == null:
				mat = mesh.surface_get_material(s)
			if mat != null and mat is StandardMaterial3D:
				var smat := mat as StandardMaterial3D
				if smat.roughness < 0.0 or smat.roughness > 1.0 or smat.metallic < 0.0 or smat.metallic > 1.0:
					_fail("PBR fora de [0,1] em %s: metallic=%.3f roughness=%.3f" % [caminho, smat.metallic, smat.roughness], cena)
					return ""
				if smat.metallic_texture == null and smat.roughness_texture == null:
					if is_equal_approx(smat.metallic, 1.0) and is_equal_approx(smat.roughness, 1.0):
						_fail("PBR clampado em metallic=1.0/roughness=1.0 sem textura ORM em %s" % caminho, cena)
						return ""
				if smat.normal_texture != null and not smat.normal_enabled:
					_fail("normal_texture presente mas normal_enabled=false em %s" % caminho, cena)
					return ""

			var arrays := mesh.surface_get_arrays(s)
			if arrays.is_empty():
				continue
			var verts: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
			var normals: PackedVector3Array = arrays[Mesh.ARRAY_NORMAL]
			var indices: PackedInt32Array = arrays[Mesh.ARRAY_INDEX]
			if verts.is_empty() or normals.size() != verts.size():
				_fail("surface sem normais por vertice em %s" % caminho, cena)
				return ""
			for v in verts:
				aabb_min = aabb_min.min(v)
				aabb_max = aabb_max.max(v)
			var tri_count := int(indices.size() / 3) if not indices.is_empty() else int(verts.size() / 3)
			total_tris += tri_count
			if eh_organico:
				var fac := _medir_arestas_facetadas(verts, normals, indices)
				arestas_suaves += int(fac["suaves"])
				arestas_facetadas += int(fac["facetadas"])

	if eh_organico and total_tris >= 200 and arestas_suaves >= 12:
		var fracao := float(arestas_facetadas) / float(arestas_suaves)
		if fracao > 0.85:
			_fail("malha_organica_facetada em %s (fracao=%.3f, suaves=%d)" % [caminho, fracao, arestas_suaves], cena)
			return ""

	if (aabb_max.y - aabb_min.y) <= 0.005:
		_fail("AABB com altura degenerada em %s" % caminho, cena)
		return ""

	# 2. Inspeciona Skeleton3D, orientacao (-Z / +Y) e Sockets ortonormais (det = +1)
	var skels := cena.find_children("*", "Skeleton3D", true, false)
	var sockets_count := 0
	if not skels.is_empty():
		var skel := skels[0] as Skeleton3D
		var idx_hips := skel.find_bone("Hips")
		var idx_head := skel.find_bone("Head")
		var idx_nose := skel.find_bone("Nose")
		var idx_tail := skel.find_bone("Tail1")
		var rig_dict: Variant = manifesto.get("rig", {})
		var esqueleto := ""
		if typeof(rig_dict) == TYPE_DICTIONARY:
			esqueleto = str(rig_dict.get("esqueleto", ""))
		var eh_quad_ou_mount := (
			esqueleto in ["quadruped@1", "winged_mount@1"]
			or tipo in ["criatura_quadrupede", "criatura_alada", "montaria"]
			or idx_tail >= 0
			or idx_nose >= 0
		)
		if eh_quad_ou_mount and idx_head >= 0 and idx_hips >= 0:
			var z_frente := skel.get_bone_global_rest(idx_nose if idx_nose >= 0 else idx_head).origin.z
			var z_tras := skel.get_bone_global_rest(idx_tail if idx_tail >= 0 else idx_hips).origin.z
			if z_frente >= z_tras:
				_fail("criatura/montaria invertida (frente Z=%.3f >= tras Z=%.3f) em %s" % [z_frente, z_tras, caminho], cena)
				return ""
		elif idx_head >= 0 and idx_hips >= 0:
			var y_head := skel.get_bone_global_rest(idx_head).origin.y
			var y_hips := skel.get_bone_global_rest(idx_hips).origin.y
			if y_head <= y_hips:
				_fail("rig invertido (Head.y=%.3f <= Hips.y=%.3f) em %s" % [y_head, y_hips, caminho], cena)
				return ""

		var markers := cena.find_children("Socket_*", "Marker3D", true, false)
		sockets_count = markers.size()
		var por_nome := {}
		for m in markers:
			var mk := m as Marker3D
			por_nome[mk.name] = mk
			var det := mk.transform.basis.determinant()
			if absf(det - 1.0) > 0.02 or not mk.transform.basis.is_conformal():
				_fail("socket %s nao ortonormal (det=%.4f) em %s" % [mk.name, det, caminho], cena)
				return ""

		if por_nome.has("Socket_HandR") and por_nome.has("Socket_HandL"):
			var b_r: Basis = (por_nome["Socket_HandR"] as Marker3D).transform.basis
			var b_l: Basis = (por_nome["Socket_HandL"] as Marker3D).transform.basis
			if b_l.is_equal_approx(b_r):
				_fail("Socket_HandL reutiliza a mesma basis de Socket_HandR em %s" % caminho, cena)
				return ""

		if skel.find_bone("Hand.R") >= 0 and not por_nome.has("Socket_HandR"):
			_fail("Socket_HandR ausente em rig com Hand.R (%s)" % caminho, cena)
			return ""
		if skel.find_bone("Hand.L") >= 0 and not por_nome.has("Socket_HandL"):
			_fail("Socket_HandL ausente em rig com Hand.L (%s)" % caminho, cena)
			return ""
		if skel.find_bone("Chest") >= 0 and not por_nome.has("Socket_Back"):
			_fail("Socket_Back ausente em rig com Chest (%s)" % caminho, cena)
			return ""
		if skel.find_bone("MountSeat") >= 0 and not por_nome.has("Socket_Mount"):
			_fail("Socket_Mount ausente em rig com MountSeat (%s)" % caminho, cena)
			return ""

	# 3. Inspeciona AnimationPlayer e playback de tracks
	var players := cena.find_children("*", "AnimationPlayer", true, false)
	var anims_count := 0
	if not players.is_empty():
		var player := players[0] as AnimationPlayer
		var lista := player.get_animation_list()
		anims_count = lista.size()
		for nome in lista:
			var anim := player.get_animation(nome)
			if anim == null or anim.length <= 0.2 or anim.get_track_count() < 1:
				_fail("animacao '%s' invalida em %s" % [nome, caminho], cena)
				return ""
			var nome_limpo := str(nome).to_lower()
			if nome_limpo in CLIPES_CICLICOS and anim.loop_mode != Animation.LOOP_LINEAR:
				_fail("clipe ciclico '%s' sem LOOP_LINEAR em %s" % [nome, caminho], cena)
				return ""
			var max_delta := _maior_delta_anim(anim)
			if max_delta <= 1e-5:
				_fail("clipe '%s' congelado (delta=%.6f) em %s" % [nome, max_delta, caminho], cena)
				return ""
			player.play(nome)
			player.seek(anim.length * 0.5, true)

	var resumo := "%s(tris=%d,sockets=%d,anims=%d)" % [caminho.get_file(), total_tris, sockets_count, anims_count]
	cena.free()
	return resumo


func _medir_arestas_facetadas(
	verts: PackedVector3Array, normals: PackedVector3Array, indices: PackedInt32Array
) -> Dictionary:
	var tri_count := int(indices.size() / 3) if not indices.is_empty() else int(verts.size() / 3)
	if tri_count < 200:
		return {"suaves": 0, "facetadas": 0}
	var edge_map := {}
	for t in range(tri_count):
		var i0 := int(indices[t * 3]) if not indices.is_empty() else t * 3
		var i1 := int(indices[t * 3 + 1]) if not indices.is_empty() else t * 3 + 1
		var i2 := int(indices[t * 3 + 2]) if not indices.is_empty() else t * 3 + 2
		var v0 := verts[i0]
		var v1 := verts[i1]
		var v2 := verts[i2]
		var fn := (v1 - v0).cross(v2 - v0)
		var flen := fn.length()
		if flen <= 1e-9:
			continue
		fn /= flen
		var n0 := normals[i0]
		var n1 := normals[i1]
		var n2 := normals[i2]
		var flat_tri := n0.distance_to(n1) < 1e-4 and n1.distance_to(n2) < 1e-4
		var k0 := _quant_v(v0)
		var k1 := _quant_v(v1)
		var k2 := _quant_v(v2)
		_registrar_aresta(edge_map, k0, k1, fn, flat_tri)
		_registrar_aresta(edge_map, k1, k2, fn, flat_tri)
		_registrar_aresta(edge_map, k2, k0, fn, flat_tri)

	var suaves := 0
	var facetadas := 0
	for key in edge_map.keys():
		var lista: Array = edge_map[key]
		if lista.size() != 2:
			continue
		var a: Dictionary = lista[0]
		var b: Dictionary = lista[1]
		var fn_a: Vector3 = a["fn"]
		var fn_b: Vector3 = b["fn"]
		var dot_f := fn_a.dot(fn_b)
		if dot_f > 0.866025 and dot_f < 0.9999:
			suaves += 1
			if bool(a["flat"]) and bool(b["flat"]):
				facetadas += 1
	return {"suaves": suaves, "facetadas": facetadas}


func _quant_v(v: Vector3) -> Vector3i:
	return Vector3i(int(round(v.x * 10000.0)), int(round(v.y * 10000.0)), int(round(v.z * 10000.0)))


func _registrar_aresta(edge_map: Dictionary, ka: Vector3i, kb: Vector3i, fn: Vector3, flat_tri: bool) -> void:
	if ka == kb:
		return
	var k := [ka, kb] if (ka.x < kb.x or (ka.x == kb.x and (ka.y < kb.y or (ka.y == kb.y and ka.z < kb.z)))) else [kb, ka]
	if not edge_map.has(k):
		edge_map[k] = []
	edge_map[k].append({"fn": fn, "flat": flat_tri})


func _maior_delta_anim(anim: Animation) -> float:
	var maior := 0.0
	for i in range(anim.get_track_count()):
		var tipo := anim.track_get_type(i)
		if tipo != Animation.TYPE_ROTATION_3D and tipo != Animation.TYPE_POSITION_3D:
			continue
		var chaves := anim.track_get_key_count(i)
		if chaves < 2:
			continue
		var primeira = anim.track_get_key_value(i, 0)
		for k in range(1, chaves):
			var valor = anim.track_get_key_value(i, k)
			var delta := 0.0
			if typeof(valor) == TYPE_QUATERNION:
				delta = absf(valor.angle_to(primeira))
			elif typeof(valor) == TYPE_VECTOR3:
				delta = (valor - primeira).length()
			maior = maxf(maior, delta)
	return maior
