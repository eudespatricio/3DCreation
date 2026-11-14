extends SceneTree

const PostImport := preload("../addons/forge3d/post_import.gd")


func _fail(msg: String, node: Node = null) -> void:
	printerr("RIG_AXES_FAIL: " + msg)
	if node != null:
		node.free()
	quit(1)


func _carregar_glb(caminho: String) -> Node:
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	var err := doc.append_from_file(caminho, st)
	if err != OK:
		return null
	return doc.generate_scene(st)


func _achar_tipo(raiz: Node, tipo: String) -> Node:
	if raiz.is_class(tipo):
		return raiz
	for c in raiz.get_children():
		var r := _achar_tipo(c, tipo)
		if r != null:
			return r
	return null


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() < 1:
		_fail("uso: -- <body.glb> [arma.glb] [escudo.glb]")
		return

	var body := _carregar_glb(args[0])
	if body == null:
		_fail("falha ao carregar body.glb: " + args[0])
		return

	var anexos := {}
	var arma_node: Node3D = null
	var escudo_node: Node3D = null

	if args.size() >= 2 and args[1] != "" and args[1] != "-":
		var a := _carregar_glb(args[1]) as Node3D
		if a == null:
			_fail("falha ao carregar arma.glb: " + args[1], body)
			return
		if not a.has_meta("forge3d_manifest"):
			a.set_meta("forge3d_manifest", {"anexo": {"parte": "arma", "osso": "Hand.R"}})
		anexos["Hand.R"] = a
		arma_node = a

	if args.size() >= 3 and args[2] != "" and args[2] != "-":
		var e := _carregar_glb(args[2]) as Node3D
		if e == null:
			_fail("falha ao carregar escudo.glb: " + args[2], body)
			return
		if not e.has_meta("forge3d_manifest"):
			e.set_meta("forge3d_manifest", {"anexo": {"parte": "escudo", "osso": "LowerArm.L"}})
		anexos["LowerArm.L"] = e
		escudo_node = e

	var cb := PostImport.montar_character_body(body, anexos)
	root.add_child(cb)
	await process_frame

	if arma_node != null:
		var arma_ponta := (arma_node.global_transform.basis * Vector3(0.0, 1.0, 0.0)).normalized()
		if arma_ponta.dot(Vector3(0.0, 0.0, -1.0)) <= 0.9:
			_fail("arma nao aponta para frente (-Z): " + str(arma_ponta), cb)
			return
		var arma_fio := (arma_node.global_transform.basis * Vector3(1.0, 0.0, 0.0)).normalized()
		if absf(arma_fio.y) <= 0.9:
			_fail("fio da arma nao esta vertical: " + str(arma_fio), cb)
			return

	if escudo_node != null:
		var esc_topo := (escudo_node.global_transform.basis * Vector3(0.0, 1.0, 0.0)).normalized()
		if esc_topo.dot(Vector3(0.0, 1.0, 0.0)) <= 0.9:
			_fail("escudo nao esta com topo para cima (+Y): " + str(esc_topo), cb)
			return
		var esc_frente := (escudo_node.global_transform.basis * Vector3(0.0, 0.0, -1.0)).normalized()
		if esc_frente.dot(Vector3(1.0, 0.0, 0.0)) <= 0.9:
			_fail("escudo nao aponta face externa para fora (+X): " + str(esc_frente), cb)
			return

	var skel := _achar_tipo(cb, "Skeleton3D") as Skeleton3D
	var ap := _achar_tipo(cb, "AnimationPlayer") as AnimationPlayer
	if skel == null or ap == null:
		_fail("Skeleton3D ou AnimationPlayer ausente", cb)
		return

	var jump_name := ""
	for nome in ap.get_animation_list():
		if nome == "jump" or nome.ends_with("/jump"):
			jump_name = nome
			break
	if jump_name == "":
		_fail("clipe jump ausente em AnimationPlayer", cb)
		return

	var sh_l := skel.find_bone("Shoulder.L")
	var ua_l := skel.find_bone("UpperArm.L")
	var sh_r := skel.find_bone("Shoulder.R")
	var ua_r := skel.find_bone("UpperArm.R")
	if sh_l < 0 or ua_l < 0 or sh_r < 0 or ua_r < 0:
		_fail("ossos Shoulder/UpperArm ausentes", cb)
		return

	var rest_dy_l := skel.get_bone_global_rest(ua_l).origin.y - skel.get_bone_global_rest(sh_l).origin.y
	var rest_dy_r := skel.get_bone_global_rest(ua_r).origin.y - skel.get_bone_global_rest(sh_r).origin.y

	var anim := ap.get_animation(jump_name)
	ap.play(jump_name)
	ap.seek(anim.length * 0.5, true)
	await process_frame

	var pose_dy_l := skel.get_bone_global_pose(ua_l).origin.y - skel.get_bone_global_pose(sh_l).origin.y
	var pose_dy_r := skel.get_bone_global_pose(ua_r).origin.y - skel.get_bone_global_pose(sh_r).origin.y
	if (pose_dy_l - rest_dy_l) <= 0.005 or (pose_dy_r - rest_dy_r) <= 0.005:
		_fail(
			"ombros nao sobem no pico do jump: dL=%s dR=%s" % [pose_dy_l - rest_dy_l, pose_dy_r - rest_dy_r],
			cb
		)
		return

	cb.queue_free()
	print("RIG_AXES_OK")
	quit(0)
