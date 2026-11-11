extends SceneTree
## Valida o pos-importador addons/forge3d/post_import.gd em um GLB publicado pelo Forge3D.
##
## Uso: godot --headless --path tools/godot_project --script tools/godot_post_import_check.gd -- <arquivo.glb>
## Saida: GODOT_POST_IMPORT_OK ... ou GODOT_POST_IMPORT_FAIL ... ; exit 0/1.

const PostImport := preload("../addons/forge3d/post_import.gd")


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		print("GODOT_POST_IMPORT_FAIL uso: godot --headless --script tools/godot_post_import_check.gd -- <glb>")
		quit(1)
		return
	var caminho: String = args[0]
	var doc := GLTFDocument.new()
	var estado := GLTFState.new()
	var erro := doc.append_from_file(caminho, estado)
	if erro != OK:
		print("GODOT_POST_IMPORT_FAIL append_from_file=%d" % erro)
		quit(1)
		return
	var cena := doc.generate_scene(estado)
	if cena == null:
		print("GODOT_POST_IMPORT_FAIL cena nula")
		quit(1)
		return

	PostImport.aplicar(cena, caminho)

	var manifest_path := caminho.get_basename() + ".manifest.json"
	if FileAccess.file_exists(manifest_path):
		if not cena.has_meta("forge3d_manifest") or not cena.has_meta("forge3d_asset_id"):
			print("GODOT_POST_IMPORT_FAIL metadados do manifesto ausentes")
			cena.free()
			quit(1)
			return

	var col_path := caminho.get_basename() + "_colisao.glb"
	var bodies := cena.find_children("*", "StaticBody3D", true, false)
	var shapes := cena.find_children("*", "CollisionShape3D", true, false)
	if FileAccess.file_exists(col_path):
		if bodies.is_empty() or shapes.is_empty():
			print("GODOT_POST_IMPORT_FAIL colisor irmao nao virou StaticBody3D+CollisionShape3D")
			cena.free()
			quit(1)
			return
		var cs := shapes[0] as CollisionShape3D
		if cs.shape == null or not (cs.shape is ConvexPolygonShape3D):
			print("GODOT_POST_IMPORT_FAIL shape nao e ConvexPolygonShape3D")
			cena.free()
			quit(1)
			return

	var loop_ok := true
	var anim_checked := 0
	for node in cena.find_children("*", "AnimationPlayer", true, false):
		var player := node as AnimationPlayer
		if player.has_animation("idle"):
			anim_checked += 1
			var anim := player.get_animation("idle")
			if anim.loop_mode != Animation.LOOP_LINEAR:
				loop_ok = false
			if player.has_animation("idle-loop"):
				print("GODOT_POST_IMPORT_FAIL clipe renomeado para idle-loop")
				cena.free()
				quit(1)
				return
	if not loop_ok:
		print("GODOT_POST_IMPORT_FAIL idle sem LOOP_LINEAR")
		cena.free()
		quit(1)
		return

	print(
		"GODOT_POST_IMPORT_OK bodies=%d shapes=%d anims=%d meta=%s"
		% [bodies.size(), shapes.size(), anim_checked, str(cena.has_meta("forge3d_manifest"))]
	)
	cena.free()
	quit(0)
