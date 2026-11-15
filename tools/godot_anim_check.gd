extends SceneTree
## Confere um GLB no Godot 4 sem abrir editor: clipe existe, tem duracao e move osso de verdade.
##
## Uso: godot --headless --script tools/godot_anim_check.gd -- <arquivo.glb> [clipe]
## Saida: uma linha GODOT_ANIM_OK ... ou GODOT_ANIM_FAIL ... ; exit 0/1.

const PostImport := preload("../addons/forge3d/post_import.gd")
const CLIPES_CICLICOS: Array[String] = [
	"idle", "walk", "run", "gallop", "wing_flap", "glide", "ride_idle", "ride_fly"
]

func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		print("GODOT_ANIM_FAIL uso: godot --headless --script tools/godot_anim_check.gd -- <glb> [clipe]")
		quit(1)
		return
	var caminho: String = args[0]
	var esperado: String = args[1] if args.size() > 1 else ""
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
	PostImport.aplicar(cena, caminho)
	var players := cena.find_children("*", "AnimationPlayer", true, false)
	if players.is_empty():
		print("GODOT_ANIM_FAIL sem AnimationPlayer")
		cena.free()
		quit(1)
		return
	var player: AnimationPlayer = players[0]
	var clipes := player.get_animation_list()
	if esperado == "":
		if player.has_animation("idle"):
			esperado = "idle"
		else:
			for c_cic in CLIPES_CICLICOS:
				if player.has_animation(c_cic):
					esperado = c_cic
					break
			if esperado == "" and not clipes.is_empty():
				esperado = str(clipes[0])
	var linha := "GODOT_ANIM_OK clipes=%s" % [clipes]
	var achou := false
	for nome in clipes:
		var anim: Animation = player.get_animation(nome)
		var mov_info := _inspecionar_movimento(anim)
		var movimento: float = mov_info["maior_delta"]
		var tracks_movendo: int = mov_info["tracks_movendo"]
		linha += " | %s duracao=%.3f tracks=%d movendo=%d movimento=%.4f loop=%d" % [
			nome, anim.length, anim.get_track_count(), tracks_movendo, movimento, int(anim.loop_mode)
		]
		var nome_limpo := str(nome).to_lower()
		if nome_limpo in CLIPES_CICLICOS and anim.loop_mode != Animation.LOOP_LINEAR:
			print("GODOT_ANIM_FAIL clipe ciclico '%s' sem LOOP_LINEAR (loop_mode=%d)" % [nome, int(anim.loop_mode)])
			cena.free()
			quit(1)
			return
		if nome == esperado:
			achou = true
			var min_dur := 1.5 if esperado == "idle" else 0.25
			if anim.length < min_dur or movimento <= 0.0:
				print("GODOT_ANIM_FAIL clipe '%s' sem duracao/movimento: %.3f / %.5f" % [nome, anim.length, movimento])
				cena.free()
				quit(1)
				return
	if not achou:
		print("GODOT_ANIM_FAIL clipe '%s' ausente em %s" % [esperado, clipes])
		cena.free()
		quit(1)
		return
	print(linha)
	cena.free()
	quit(0)


func _inspecionar_movimento(anim: Animation) -> Dictionary:
	var maior := 0.0
	var tracks_movendo := 0
	for i in range(anim.get_track_count()):
		var tipo := anim.track_get_type(i)
		if tipo != Animation.TYPE_ROTATION_3D and tipo != Animation.TYPE_POSITION_3D:
			continue
		var chaves := anim.track_get_key_count(i)
		if chaves < 2:
			continue
		var primeira = anim.track_get_key_value(i, 0)
		var maior_track := 0.0
		for k in range(1, chaves):
			var valor = anim.track_get_key_value(i, k)
			var delta := 0.0
			if typeof(valor) == TYPE_QUATERNION:
				delta = abs(valor.angle_to(primeira))
			elif typeof(valor) == TYPE_VECTOR3:
				delta = (valor - primeira).length()
			maior_track = maxf(maior_track, delta)
			maior = maxf(maior, delta)
		if maior_track > 1e-4:
			tracks_movendo += 1
	return {"maior_delta": maior, "tracks_movendo": tracks_movendo}
