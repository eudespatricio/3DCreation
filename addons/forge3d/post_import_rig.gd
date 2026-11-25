@tool
extends RefCounted
## Submodulo de sockets, montaria, attachments skinned e CharacterBody3D.


static func _nome_marker_socket(chave: String) -> String:
	var k := chave.strip_edges()
	var mapa := {
		"Hand.R": "Socket_HandR",
		"RightHand": "Socket_HandR",
		"Socket_HandR": "Socket_HandR",
		"Hand.L": "Socket_HandL",
		"LeftHand": "Socket_HandL",
		"Socket_HandL": "Socket_HandL",
		"Back": "Socket_Back",
		"Chest": "Socket_Back",
		"UpperTorso": "Socket_Back",
		"Socket_Back": "Socket_Back",
		"Mount": "Socket_Mount",
		"MountSeat": "Socket_Mount",
		"Socket_Mount": "Socket_Mount",
		"Head": "Socket_Head",
		"Socket_Head": "Socket_Head",
		"Shoulder.L": "Socket_ShoulderL",
		"LeftShoulder": "Socket_ShoulderL",
		"Socket_ShoulderL": "Socket_ShoulderL",
		"Shoulder.R": "Socket_ShoulderR",
		"RightShoulder": "Socket_ShoulderR",
		"Socket_ShoulderR": "Socket_ShoulderR",
	}
	if mapa.has(k):
		return str(mapa[k])
	if k.begins_with("Socket_"):
		return k
	return "Socket_" + k.replace(".", "")


static func _basis_orthonormal_positiva(b: Basis) -> Basis:
	var out := b.orthonormalized()
	if out.determinant() < 0.0:
		out.x = -out.x
	return out


static func _espelhar_basis_yz_det_positivo(b: Basis) -> Basis:
	var mx := Basis(Vector3(-1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0), Vector3(0.0, 0.0, 1.0))
	return _basis_orthonormal_positiva(mx * b * mx)


static func _obter_ou_criar_bone_attachment(skel: Skeleton3D, bone_name: String, owner_node: Node) -> BoneAttachment3D:
	for child in skel.get_children():
		if child is BoneAttachment3D and (child as BoneAttachment3D).bone_name == bone_name:
			return child as BoneAttachment3D
	var attachment := BoneAttachment3D.new()
	attachment.name = "BoneAttachment_" + bone_name
	attachment.bone_name = bone_name
	skel.add_child(attachment)
	if owner_node != null:
		attachment.owner = owner_node
	return attachment


static func _configurar_sockets(scene: Node, manifesto: Dictionary) -> void:
	if scene == null:
		return
	var skel: Skeleton3D = scene as Skeleton3D
	if skel == null:
		var skels := scene.find_children("*", "Skeleton3D", true, false)
		if not skels.is_empty():
			skel = skels[0] as Skeleton3D
	if skel == null:
		return

	var sockets_cfg: Dictionary = {}
	var raw_sockets: Variant = manifesto.get("sockets", null)
	if typeof(raw_sockets) == TYPE_DICTIONARY:
		for k in (raw_sockets as Dictionary).keys():
			var item: Variant = (raw_sockets as Dictionary)[k]
			if typeof(item) == TYPE_DICTIONARY:
				sockets_cfg[_nome_marker_socket(str(k))] = item
	elif typeof(raw_sockets) == TYPE_ARRAY:
		for entry_var in (raw_sockets as Array):
			if typeof(entry_var) == TYPE_DICTIONARY:
				var entry := (entry_var as Dictionary).duplicate()
				var chave := str(entry.get("nome", entry.get("id", entry.get("osso", ""))))
				if chave != "":
					entry["_bone_local"] = true
					sockets_cfg[_nome_marker_socket(chave)] = entry

	var fallbacks := [
		{"marker": "Socket_HandR", "ossos": ["Hand.R", "RightHand"], "pos": [0.0, 0.0, 0.0]},
		{"marker": "Socket_HandL", "ossos": ["Hand.L", "LeftHand"], "pos": [0.0, 0.0, 0.0]},
		{"marker": "Socket_Back", "ossos": ["Chest", "UpperTorso"], "pos": [0.0, 0.08, 0.15]},
		{"marker": "Socket_Mount", "ossos": ["MountSeat"], "pos": [0.0, 0.15, 0.0]},
	]
	for fb in fallbacks:
		var m_name: String = fb["marker"]
		if sockets_cfg.has(m_name):
			continue
		for cand_osso in fb["ossos"]:
			if skel.find_bone(str(cand_osso)) >= 0:
				sockets_cfg[m_name] = {
					"osso": str(cand_osso),
					"posicao_m": fb["pos"],
					"_fallback": true,
				}
				break

	var basis_hand_r_padrao := Basis(
		Vector3(0.0, 1.0, 0.0),
		Vector3(0.0, 0.0, -1.0),
		Vector3(-1.0, 0.0, 0.0)
	)
	var basis_hand_r_final := basis_hand_r_padrao
	var local_hand_r_final := basis_hand_r_padrao
	if sockets_cfg.has("Socket_HandR"):
		var cfg_r: Dictionary = sockets_cfg["Socket_HandR"]
		var osso_r := str(cfg_r.get("osso", ""))
		var idx_r := skel.find_bone(osso_r) if osso_r != "" else -1
		var hand_r_rest_basis := (
			_basis_orthonormal_positiva(skel.get_bone_global_rest(idx_r).basis)
			if idx_r >= 0
			else Basis.IDENTITY
		)
		var q_r: Variant = cfg_r.get("rotacao_quat_wxyz", null)
		var eh_bl_r := bool(cfg_r.get("_bone_local", false))
		var tem_q_r := false
		var local_q_r := Basis.IDENTITY
		if typeof(q_r) == TYPE_ARRAY and (q_r as Array).size() == 4:
			var arr_r := q_r as Array
			var quat_r := Quaternion(float(arr_r[1]), float(arr_r[2]), float(arr_r[3]), float(arr_r[0])).normalized()
			local_q_r = _basis_orthonormal_positiva(Basis(quat_r))
			if eh_bl_r:
				tem_q_r = true
			elif not quat_r.is_equal_approx(Quaternion.IDENTITY):
				basis_hand_r_final = local_q_r
				tem_q_r = true
		if eh_bl_r and tem_q_r:
			local_hand_r_final = local_q_r
		else:
			local_hand_r_final = _basis_orthonormal_positiva(hand_r_rest_basis.inverse() * basis_hand_r_final)

	for marker_name in sockets_cfg.keys():
		var cfg: Dictionary = sockets_cfg[marker_name]
		var osso := str(cfg.get("osso", ""))
		if osso == "" or skel.find_bone(osso) < 0:
			continue
		var bone_idx := skel.find_bone(osso)
		var bone_rest_basis := _basis_orthonormal_positiva(skel.get_bone_global_rest(bone_idx).basis)
		var attachment := _obter_ou_criar_bone_attachment(skel, osso, scene)

		var marker: Marker3D = null
		for ch in attachment.get_children():
			if ch is Marker3D and String(ch.name) == marker_name:
				marker = ch as Marker3D
				break
		if marker == null:
			marker = Marker3D.new()
			marker.name = marker_name
			attachment.add_child(marker)
			marker.owner = scene

		var pos := Vector3.ZERO
		var raw_pos: Variant = cfg.get("posicao_local", cfg.get("posicao_m", null))
		if typeof(raw_pos) == TYPE_ARRAY and (raw_pos as Array).size() == 3:
			var p_arr := raw_pos as Array
			pos = Vector3(float(p_arr[0]), float(p_arr[1]), float(p_arr[2]))
		elif marker_name == "Socket_Back":
			pos = Vector3(0.0, 0.08, 0.15)
		elif marker_name == "Socket_Mount":
			pos = Vector3(0.0, 0.15, 0.0)
		marker.position = pos

		var eh_bone_local := bool(cfg.get("_bone_local", false))
		var target_skel_basis := Basis.IDENTITY
		var local_quat_basis := Basis.IDENTITY
		var tem_quat_custom := false
		var raw_q: Variant = cfg.get("rotacao_quat_wxyz", null)
		if typeof(raw_q) == TYPE_ARRAY and (raw_q as Array).size() == 4:
			var q_arr := raw_q as Array
			var quat := Quaternion(float(q_arr[1]), float(q_arr[2]), float(q_arr[3]), float(q_arr[0])).normalized()
			local_quat_basis = _basis_orthonormal_positiva(Basis(quat))
			if eh_bone_local:
				tem_quat_custom = true
			elif not quat.is_equal_approx(Quaternion.IDENTITY):
				target_skel_basis = local_quat_basis
				tem_quat_custom = true

		if marker_name == "Socket_Mount":
			marker.basis = _basis_orthonormal_positiva(bone_rest_basis.inverse() * Basis.IDENTITY)
		elif eh_bone_local and tem_quat_custom:
			if marker_name == "Socket_HandL" and sockets_cfg.has("Socket_HandR"):
				if local_quat_basis.is_equal_approx(local_hand_r_final):
					local_quat_basis = _espelhar_basis_yz_det_positivo(local_hand_r_final)
				if local_quat_basis.is_equal_approx(local_hand_r_final):
					local_quat_basis = _basis_orthonormal_positiva(
						Basis(-local_quat_basis.x, local_quat_basis.y, -local_quat_basis.z)
					)
			marker.basis = local_quat_basis
		elif marker_name == "Socket_HandR":
			if not tem_quat_custom:
				target_skel_basis = basis_hand_r_padrao
			marker.basis = _basis_orthonormal_positiva(bone_rest_basis.inverse() * target_skel_basis)
		elif marker_name == "Socket_HandL":
			if not tem_quat_custom or target_skel_basis.is_equal_approx(basis_hand_r_final):
				target_skel_basis = _espelhar_basis_yz_det_positivo(basis_hand_r_final)
			var local_l := _basis_orthonormal_positiva(bone_rest_basis.inverse() * target_skel_basis)
			if local_l.is_equal_approx(local_hand_r_final):
				local_l = _espelhar_basis_yz_det_positivo(local_hand_r_final)
			if local_l.is_equal_approx(local_hand_r_final):
				local_l = _basis_orthonormal_positiva(Basis(-local_l.x, local_l.y, -local_l.z))
			marker.basis = local_l
		else:
			marker.basis = _basis_orthonormal_positiva(bone_rest_basis.inverse() * target_skel_basis)


static func montar_cavaleiro_em_montaria(cavaleiro: Node3D, montaria: Node3D) -> Node3D:
	if cavaleiro == null or montaria == null:
		return null
	var socket_mount := montaria.find_child("Socket_Mount", true, false) as Node3D
	if socket_mount == null:
		var skels := montaria.find_children("*", "Skeleton3D", true, false)
		var skel: Skeleton3D = montaria as Skeleton3D if montaria is Skeleton3D else (skels[0] as Skeleton3D if not skels.is_empty() else null)
		if skel != null:
			var osso_mount := ""
			for cand in ["MountSeat", "Spine1", "Chest", "Spine", "Hips"]:
				if skel.find_bone(cand) >= 0:
					osso_mount = cand
					break
			if osso_mount != "":
				var bone_idx := skel.find_bone(osso_mount)
				var bone_rest_basis := _basis_orthonormal_positiva(skel.get_bone_global_rest(bone_idx).basis)
				var ba := _obter_ou_criar_bone_attachment(skel, osso_mount, montaria)
				var m := Marker3D.new()
				m.name = "Socket_Mount"
				m.position = Vector3(0.0, 0.15, 0.0)
				m.basis = _basis_orthonormal_positiva(bone_rest_basis.inverse() * Basis.IDENTITY)
				ba.add_child(m)
				m.owner = montaria
				socket_mount = m
		if socket_mount == null:
			var m_fallback := Marker3D.new()
			m_fallback.name = "Socket_Mount"
			m_fallback.position = Vector3(0.0, 1.0, 0.0)
			m_fallback.basis = Basis.IDENTITY
			montaria.add_child(m_fallback)
			m_fallback.owner = montaria
			socket_mount = m_fallback

	if cavaleiro.get_parent() != null:
		cavaleiro.get_parent().remove_child(cavaleiro)
	socket_mount.add_child(cavaleiro)
	cavaleiro.owner = montaria.owner if montaria.owner != null else montaria
	cavaleiro.transform = Transform3D.IDENTITY

	for node in cavaleiro.find_children("*", "AnimationPlayer", true, false):
		var player := node as AnimationPlayer
		if player != null and player.has_animation("ride_idle"):
			var anim := player.get_animation("ride_idle")
			if anim != null:
				anim.loop_mode = Animation.LOOP_LINEAR
			player.autoplay = "ride_idle"
			player.play("ride_idle")
	return socket_mount


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


static func montar_character_body(
	body_node: Node,
	anexos: Dictionary = {},
	capsule_h: float = 1.85,
	capsule_r: float = 0.35,
	remover_static_body: bool = true
) -> CharacterBody3D:
	var cap_h := capsule_h
	var cap_r := capsule_r
	var eh_quadrupede := false
	var bx := 0.0
	var by := 0.0
	var bz := 0.0
	var tem_bbox := false

	if body_node != null and body_node.has_meta("forge3d_manifest"):
		var man: Variant = body_node.get_meta("forge3d_manifest")
		if typeof(man) == TYPE_DICTIONARY:
			var tipo := str((man as Dictionary).get("tipo", ""))
			var rig_v: Variant = (man as Dictionary).get("rig", null)
			var esq := str((rig_v as Dictionary).get("esqueleto", "")) if typeof(rig_v) == TYPE_DICTIONARY else ""
			if tipo in ["criatura_quadrupede", "montaria"] or esq in ["quadruped@1", "winged_mount@1"]:
				eh_quadrupede = true

	if body_node != null and body_node.has_meta("forge3d_geometry"):
		var geom: Variant = body_node.get_meta("forge3d_geometry")
		if typeof(geom) == TYPE_DICTIONARY and (geom as Dictionary).has("bbox_m"):
			var bbox: Variant = (geom as Dictionary)["bbox_m"]
			if typeof(bbox) == TYPE_ARRAY and (bbox as Array).size() == 3:
				bx = float(bbox[0])
				by = float(bbox[1])
				bz = float(bbox[2])
				tem_bbox = true
				if bz > by * 1.25:
					eh_quadrupede = true

	if tem_bbox and is_equal_approx(capsule_h, 1.85):
		if eh_quadrupede:
			cap_r = maxf(0.15, minf(bx, by) * 0.45)
			cap_h = maxf(0.4, bz)
		else:
			cap_h = max(0.4, by)
			cap_r = max(0.15, max(bx, bz) * 0.42)
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
	if eh_quadrupede:
		col_shape.rotation_degrees.x = 90.0
		col_shape.position = Vector3(0.0, maxf(cap_r, by * 0.5) if tem_bbox else cap_r, 0.0)
	else:
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
				var attachment := _obter_ou_criar_bone_attachment(skel, bone_name, char_body)
				var expected_marker := _nome_marker_socket(bone_name)
				var socket_marker: Marker3D = null
				for ch in attachment.get_children():
					if ch is Marker3D:
						if String(ch.name) == expected_marker:
							socket_marker = ch as Marker3D
							break
						if socket_marker == null:
							socket_marker = ch as Marker3D
				if socket_marker != null:
					socket_marker.add_child(anexo_node)
					if anexo_node is Node3D:
						var n3d := anexo_node as Node3D
						n3d.position = Vector3.ZERO
						if _orientar_anexo_socket(n3d, skel, bone_name):
							n3d.basis = _basis_orthonormal_positiva(socket_marker.basis.inverse()) * n3d.basis
				else:
					if anexo_node is Node3D:
						_orientar_anexo_socket(anexo_node as Node3D, skel, bone_name)
					attachment.add_child(anexo_node)
				if anexo_node.owner == null:
					anexo_node.owner = char_body

	return char_body


static func _orientar_anexo_socket(n3d: Node3D, skel: Skeleton3D, bone_name: String) -> bool:
	var bone_idx := skel.find_bone(bone_name)
	if bone_idx < 0:
		return false
	if n3d == null or not n3d.has_meta("forge3d_manifest"):
		return false
	var an_man: Variant = n3d.get_meta("forge3d_manifest")
	if typeof(an_man) != TYPE_DICTIONARY:
		return false
	var an_info: Variant = (an_man as Dictionary).get("anexo", null)
	if typeof(an_info) != TYPE_DICTIONARY:
		return false
	var an_dict := an_info as Dictionary
	var parte := str(an_dict.get("parte", "")).to_lower()
	if parte == "":
		return false
	if an_dict.has("offset_rot"):
		var off: Variant = an_dict["offset_rot"]
		if typeof(off) == TYPE_ARRAY:
			var arr := off as Array
			if arr.size() == 3:
				n3d.basis = Basis.from_euler(Vector3(float(arr[0]), float(arr[1]), float(arr[2]))).scaled(n3d.scale)
				return true
			if arr.size() == 4:
				n3d.basis = Basis(Quaternion(float(arr[0]), float(arr[1]), float(arr[2]), float(arr[3]))).scaled(n3d.scale)
				return true

	var bone_rest_basis := _basis_orthonormal_positiva(skel.get_bone_global_rest(bone_idx).basis)
	var target_basis_skel := Basis.IDENTITY
	var tratado := false
	var lado_r := bone_name.ends_with(".R") or bone_name.begins_with("Right")
	if parte == "arma":
		var basis_r := Basis(Vector3(0.0, 1.0, 0.0), Vector3(0.0, 0.0, -1.0), Vector3(-1.0, 0.0, 0.0))
		target_basis_skel = basis_r if lado_r else _espelhar_basis_yz_det_positivo(basis_r)
		tratado = true
	elif parte == "escudo":
		if lado_r:
			target_basis_skel = Basis(Vector3(0.0, 0.0, 1.0), Vector3(0.0, 1.0, 0.0), Vector3(-1.0, 0.0, 0.0))
		else:
			target_basis_skel = Basis(Vector3(0.0, 0.0, -1.0), Vector3(0.0, 1.0, 0.0), Vector3(1.0, 0.0, 0.0))
		tratado = true
	elif parte in ["elmo", "cabelo", "capa", "ombreiras", "peitoral", "luvas", "calcas", "calças", "botas"]:
		target_basis_skel = Basis.IDENTITY
		tratado = true
	if tratado:
		n3d.basis = _basis_orthonormal_positiva(bone_rest_basis.inverse() * target_basis_skel).scaled(n3d.scale)
		return true
	return false
