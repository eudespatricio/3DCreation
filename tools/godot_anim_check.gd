extends SceneTree
## Confere um GLB no Godot 4 sem abrir editor: clipe existe, tem duracao e move osso de verdade.
##
## Uso: godot --headless --script tools/godot_anim_check.gd -- <arquivo.glb> [clipe]
## Saida: uma linha GODOT_ANIM_OK ... ou GODOT_ANIM_FAIL ... ; exit 0/1.

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		print("GODOT_ANIM_FAIL uso: godot --headless --script tools/godot_anim_check.gd -- <glb> [clipe]")
		quit(1)
		return
	var caminho: String = args[0]
	var esperado: String = args[1] if args.size() > 1 else "idle"
	var doc := GLTFDocument.new()
	var estado := GLTFState.new()
	var erro := doc.append_from_file(caminho, estado)
	if erro != OK:
		print("GODOT_ANIM_FAIL append_from_file=%d" % erro)
		quit(1)
		return
	var cena := doc.generate_scene(estado)
	if cena == null:
		print("GODOT_ANIM_FAIL cena nula")
		quit(1)
		return
	var players := cena.find_children("*", "AnimationPlayer", true, false)
	if players.is_empty():
		print("GODOT_ANIM_FAIL sem AnimationPlayer")
		quit(1)
		return
	var player: AnimationPlayer = players[0]
	var clipes := player.get_animation_list()
	var linha := "GODOT_ANIM_OK clipes=%s" % [clipes]
	var achou := false
	for nome in clipes:
		var anim: Animation = player.get_animation(nome)
		var movimento := _movimento(anim)
		linha += " | %s duracao=%.3f tracks=%d movimento=%.4f" % [nome, anim.length, anim.get_track_count(), movimento]
		if nome == esperado:
			achou = true
			if anim.length < 1.5 or movimento <= 0.0:
				print("GODOT_ANIM_FAIL clipe '%s' sem duracao/movimento: %.3f / %.5f" % [nome, anim.length, movimento])
				quit(1)
				return
	if not achou:
		print("GODOT_ANIM_FAIL clipe '%s' ausente em %s" % [esperado, clipes])
		quit(1)
		return
	print(linha)
	quit(0)


func _movimento(anim: Animation) -> float:
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
				delta = abs(valor.angle_to(primeira))
			elif typeof(valor) == TYPE_VECTOR3:
				delta = (valor - primeira).length()
			maior = maxf(maior, delta)
	return maior
