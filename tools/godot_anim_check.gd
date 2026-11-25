extends SceneTree
## Confere um GLB no Godot 4 sem abrir editor: clipe existe, tem duracao e move osso de verdade.
##
## Uso: godot --headless --path tools/godot_project --script "$PWD/tools/godot_anim_check.gd" -- <arquivo.glb> [clipe]
## Saida: uma linha GODOT_ANIM_OK ... ou GODOT_ANIM_FAIL ... ; exit 0/1.

const PostImport := preload("../addons/forge3d/post_import.gd")
const CLIPES_CICLICOS: Array[String] = [
	"idle", "walk", "run", "gallop", "wing_flap", "glide", "ride_idle", "ride_fly"
]
const CLIPES_NAO_CICLICOS: Array[String] = [
	"attack", "bite", "block", "cast", "death", "dismount",
	"hit", "jump", "land", "mount_up", "rear_up", "roar", "slash_combo", "tail_swipe"
]


func _fail(msg: String, cena: Node = null) -> void:
	print("GODOT_ANIM_FAIL " + msg)
	if cena != null:
		cena.free()
	quit(1)


static func _clip_base_key(nome: String) -> String:
	var key := nome.strip_edges().to_lower()
	return key.substr(key.rfind("|") + 1).strip_edges() if key.contains("|") else key


static func _extrair_manifest_loop_overrides(manifesto: Dictionary) -> Dictionary:
	var overrides := {}
	var raw_anims: Variant = manifesto.get("animacoes", [])
	if typeof(raw_anims) != TYPE_ARRAY:
		return overrides
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
		if clip_nome != "":
			overrides[clip_nome] = Animation.LOOP_LINEAR if bool(entry["loop"]) else Animation.LOOP_NONE
	return overrides


static func _loop_esperado(key: String, base_key: String, man_ov: Dictionary, imp_ov: Dictionary) -> int:
	if man_ov.has(key):
		return int(man_ov[key])
	if imp_ov.has(key):
		return int(imp_ov[key])
	if base_key != key and man_ov.has(base_key):
		return int(man_ov[base_key])
	if base_key != key and imp_ov.has(base_key):
		return int(imp_ov[base_key])
	if key in CLIPES_CICLICOS or base_key in CLIPES_CICLICOS:
		return Animation.LOOP_LINEAR
	if key in CLIPES_NAO_CICLICOS or base_key in CLIPES_NAO_CICLICOS:
		return Animation.LOOP_NONE
	return -1


static func _escolher_esperado(player: AnimationPlayer, clipes: PackedStringArray) -> String:
	if player.has_animation("idle"):
		return "idle"
	for nome_c in clipes:
		if _clip_base_key(str(nome_c)) == "idle":
			return str(nome_c)
	for c_cic in CLIPES_CICLICOS:
		if player.has_animation(c_cic):
			return c_cic
		for nome_c in clipes:
			if _clip_base_key(str(nome_c)) == c_cic:
				return str(nome_c)
	return str(clipes[0]) if not clipes.is_empty() else ""


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.is_empty():
		_fail("uso: godot --headless --path tools/godot_project --script \"$PWD/tools/godot_anim_check.gd\" -- <glb> [clipe]")
		return
	var caminho: String = args[0]
	var esperado: String = args[1] if args.size() > 1 else ""
	var doc := GLTFDocument.new()
	var estado := GLTFState.new()
	var erro := doc.append_from_file(caminho, estado)
	if erro != OK:
		_fail("append_from_file=%d" % erro)
		return
	var cena := doc.generate_scene(estado)
	if cena == null:
		_fail("cena nula")
		return

	var manifest_path := caminho.get_basename() + ".manifest.json"
	var manifesto: Dictionary = {}
	if FileAccess.file_exists(manifest_path):
		var json := JSON.new()
		if json.parse(FileAccess.get_file_as_string(manifest_path)) != OK or typeof(json.data) != TYPE_DICTIONARY:
			_fail("manifesto invalido (%s): %s" % [manifest_path, json.get_error_message()], cena)
			return
		manifesto = json.data

	PostImport.aplicar(cena, caminho)
	if manifesto.is_empty() and cena.has_meta("forge3d_manifest"):
		var meta_m: Variant = cena.get_meta("forge3d_manifest")
		if typeof(meta_m) == TYPE_DICTIONARY:
			manifesto = meta_m

	var players := cena.find_children("*", "AnimationPlayer", true, false)
	if players.is_empty():
		_fail("sem AnimationPlayer", cena)
		return
	var player: AnimationPlayer = players[0]
	var clipes := player.get_animation_list()
	if esperado == "":
		esperado = _escolher_esperado(player, clipes)

	var man_ov := _extrair_manifest_loop_overrides(manifesto)
	var imp_ov := PostImport._ler_import_subresources_animacoes(caminho)
	var esperado_base := _clip_base_key(esperado)
	var tem_esperado_exato := esperado != "" and player.has_animation(esperado)

	var linha := "GODOT_ANIM_OK clipes=%s" % [clipes]
	var achou := false
	for nome_raw in clipes:
		var nome := str(nome_raw)
		var anim: Animation = player.get_animation(nome)
		if anim == null:
			_fail("animacao nula '%s'" % nome, cena)
			return
		var mov_info := _inspecionar_movimento(anim)
		var movimento: float = mov_info["maior_delta"]
		var tracks_movendo: int = mov_info["tracks_movendo"]
		linha += " | %s duracao=%.3f tracks=%d movendo=%d movimento=%.4f loop=%d" % [
			nome, anim.length, anim.get_track_count(), tracks_movendo, movimento, int(anim.loop_mode)
		]
		var key := nome.strip_edges().to_lower()
		var base_key := _clip_base_key(nome)
		var exp_loop := _loop_esperado(key, base_key, man_ov, imp_ov)
		if exp_loop != -1 and anim.loop_mode != exp_loop:
			_fail("clipe '%s' com loop_mode=%d (esperado %d)" % [nome, int(anim.loop_mode), exp_loop], cena)
			return
		var corresponde := (nome == esperado) or (not tem_esperado_exato and esperado_base != "" and base_key == esperado_base)
		if corresponde:
			achou = true
			var min_dur := 1.5 if base_key == "idle" else 0.25
			if anim.length < min_dur or movimento <= 0.0:
				_fail("clipe '%s' sem duracao/movimento: %.3f / %.5f" % [nome, anim.length, movimento], cena)
				return
	if not achou:
		_fail("clipe '%s' ausente em %s" % [esperado, clipes], cena)
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
