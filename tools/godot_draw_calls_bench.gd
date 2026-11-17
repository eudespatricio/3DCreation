extends SceneTree
## Medidor real de draw calls, objetos, primitivas (tris) e VRAM no Godot 4.x.
##
## Importante: `--headless` ativa o driver dummy (0 draw calls). Para medir o
## RenderingServer real, invoque sem `--headless` com `--rendering-driver vulkan`
## (Forward+) ou `--rendering-driver opengl3` (Compatibility) sob X11/Wayland/xvfb.
##
## Canal de entrada/saida por arquivo JSON (I9):
##   godot --path tools/godot_project --rendering-driver vulkan --windowed --resolution 320x240 \
##     --script "$PWD/tools/godot_draw_calls_bench.gd" -- --input in.json --output out.json

var _input_path := ""
var _output_path := ""
var _cfg: Dictionary = {}
var _phase := 0
var _frame_in_phase := 0
var _frames_baseline := 4
var _frames_measure := 6

var _world_node: Node3D = null
var _assets_root: Node3D = null
var _cam: Camera3D = null
var _light: DirectionalLight3D = null
var _templates_keepalive: Array[Node] = []
var _baseline: Dictionary = {}
var _items_report: Array[Dictionary] = []
var _expected_tris := 0
var _total_instances := 0


func _fail(msg: String) -> void:
	printerr("GODOT_DRAW_CALLS_FAIL " + msg)
	if _output_path != "":
		var f := FileAccess.open(_output_path, FileAccess.WRITE)
		if f != null:
			f.store_string(JSON.stringify({"ok": false, "erro": msg}, "  "))
			f.close()
	quit(1)


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	var i := 0
	while i < args.size():
		var a := String(args[i])
		if a == "--input" and i + 1 < args.size():
			_input_path = String(args[i + 1])
			i += 2
		elif a == "--output" and i + 1 < args.size():
			_output_path = String(args[i + 1])
			i += 2
		else:
			i += 1

	if _input_path == "" or _output_path == "":
		_fail("uso: -- --input <in.json> --output <out.json>")
		return

	if not FileAccess.file_exists(_input_path):
		_fail("arquivo de entrada ausente: " + _input_path)
		return

	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(_input_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		_fail("JSON de entrada invalido: " + _input_path)
		return
	_cfg = parsed

	_frames_baseline = maxi(2, int(_cfg.get("frames_baseline", 4)))
	_frames_measure = maxi(3, int(_cfg.get("frames_measure", 6)))

	var vp := get_root()
	vp.mesh_lod_threshold = 0.0
	vp.use_occlusion_culling = false

	_world_node = Node3D.new()
	_world_node.name = "BenchWorld"
	vp.add_child(_world_node)

	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.08, 0.09, 0.11)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(1.0, 1.0, 1.0)
	env.ambient_light_energy = 0.65
	var we := WorldEnvironment.new()
	we.environment = env
	_world_node.add_child(we)

	_light = DirectionalLight3D.new()
	_light.rotation_degrees = Vector3(-50.0, 35.0, 0.0)
	_light.shadow_enabled = bool(_cfg.get("shadows", false))
	_light.directional_shadow_max_distance = 400.0
	_world_node.add_child(_light)

	_cam = Camera3D.new()
	_cam.fov = 60.0
	_cam.near = 0.05
	_cam.far = 10000.0
	_world_node.add_child(_cam)
	_cam.look_at_from_position(Vector3(0.0, 5.0, 10.0), Vector3.ZERO, Vector3.UP)
	_cam.make_current()


func _snapshot_metrics() -> Dictionary:
	var vp := get_root()
	return {
		"perf_draw_calls": int(round(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME))),
		"perf_objects": int(round(Performance.get_monitor(Performance.RENDER_TOTAL_OBJECTS_IN_FRAME))),
		"perf_primitives": int(round(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME))),
		"perf_texture_mem_bytes": int(round(Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED))),
		"perf_buffer_mem_bytes": int(round(Performance.get_monitor(Performance.RENDER_BUFFER_MEM_USED))),
		"perf_video_mem_bytes": int(round(Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED))),
		"vp_visible_draw_calls": vp.get_render_info(Viewport.RENDER_INFO_TYPE_VISIBLE, Viewport.RENDER_INFO_DRAW_CALLS_IN_FRAME),
		"vp_visible_objects": vp.get_render_info(Viewport.RENDER_INFO_TYPE_VISIBLE, Viewport.RENDER_INFO_OBJECTS_IN_FRAME),
		"vp_visible_primitives": vp.get_render_info(Viewport.RENDER_INFO_TYPE_VISIBLE, Viewport.RENDER_INFO_PRIMITIVES_IN_FRAME),
		"vp_shadow_draw_calls": vp.get_render_info(Viewport.RENDER_INFO_TYPE_SHADOW, Viewport.RENDER_INFO_DRAW_CALLS_IN_FRAME),
		"vp_shadow_objects": vp.get_render_info(Viewport.RENDER_INFO_TYPE_SHADOW, Viewport.RENDER_INFO_OBJECTS_IN_FRAME),
		"vp_shadow_primitives": vp.get_render_info(Viewport.RENDER_INFO_TYPE_SHADOW, Viewport.RENDER_INFO_PRIMITIVES_IN_FRAME),
	}


func _relative_transform(ancestor: Node3D, node: Node3D) -> Transform3D:
	var xf := Transform3D.IDENTITY
	var cur: Node = node
	while cur != null and cur != ancestor:
		if cur is Node3D:
			xf = (cur as Node3D).transform * xf
		cur = cur.get_parent()
	return xf


func _strip_ucx_nodes(root: Node) -> void:
	var to_remove: Array[Node] = []
	for child in root.find_children("UCX_*", "", true, false):
		to_remove.append(child)
	for n in to_remove:
		if n.get_parent() != null:
			n.get_parent().remove_child(n)
		n.free()


func _inspect_template(root: Node3D) -> Dictionary:
	var mesh_nodes: Array[MeshInstance3D] = []
	for n in root.find_children("*", "MeshInstance3D", true, false):
		var mi := n as MeshInstance3D
		if mi != null and mi.mesh != null:
			mesh_nodes.append(mi)
	if root is MeshInstance3D and (root as MeshInstance3D).mesh != null:
		mesh_nodes.push_front(root as MeshInstance3D)

	var skels := root.find_children("*", "Skeleton3D", true, false)
	var is_skinned := not skels.is_empty()
	var tris_unit := 0
	var surfaces_unit := 0
	var bmin := Vector3(INF, INF, INF)
	var bmax := Vector3(-INF, -INF, -INF)

	for mi in mesh_nodes:
		if mi.skin != null:
			is_skinned = true
		var rel_xf := _relative_transform(root, mi)
		var m := mi.mesh
		var sc := m.get_surface_count()
		surfaces_unit += sc
		var local_aabb := m.get_aabb()
		for ix in range(2):
			for iy in range(2):
				for iz in range(2):
					var corner := Vector3(
						local_aabb.position.x + (local_aabb.size.x if ix == 1 else 0.0),
						local_aabb.position.y + (local_aabb.size.y if iy == 1 else 0.0),
						local_aabb.position.z + (local_aabb.size.z if iz == 1 else 0.0)
					)
					var wc := rel_xf * corner
					bmin = bmin.min(wc)
					bmax = bmax.max(wc)
		for s in range(sc):
			var arr := m.surface_get_arrays(s)
			if arr.is_empty():
				continue
			var idx: PackedInt32Array = arr[Mesh.ARRAY_INDEX]
			var vts: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]
			tris_unit += int(idx.size() / 3) if not idx.is_empty() else int(vts.size() / 3)

	if bmin.x == INF:
		bmin = Vector3(-0.5, 0.0, -0.5)
		bmax = Vector3(0.5, 1.0, 0.5)

	return {
		"mesh_nodes": mesh_nodes,
		"mesh_nodes_count": mesh_nodes.size(),
		"surfaces_unit": surfaces_unit,
		"tris_unit": tris_unit,
		"skinned": is_skinned,
		"bmin": bmin,
		"bmax": bmax,
	}


func _mesh_with_overrides(mi: MeshInstance3D) -> Mesh:
	var src := mi.mesh
	var has_override := false
	for s in range(src.get_surface_count()):
		if mi.get_surface_override_material(s) != null:
			has_override = true
			break
	if not has_override:
		return src
	var dup := src.duplicate(false) as Mesh
	for s in range(dup.get_surface_count()):
		var ov := mi.get_surface_override_material(s)
		if ov != null:
			dup.surface_set_material(s, ov)
	return dup


func _populate_scene() -> bool:
	_assets_root = Node3D.new()
	_assets_root.name = "AssetsRoot"
	_world_node.add_child(_assets_root)

	var mode := String(_cfg.get("mode", "naive"))
	var raw_items: Variant = _cfg.get("items", [])
	if typeof(raw_items) != TYPE_ARRAY:
		_fail("campo items deve ser lista")
		return false

	var loaded: Array[Dictionary] = []
	var max_horiz := 1.0
	_total_instances = 0
	_expected_tris = 0

	for entry_v in raw_items:
		if typeof(entry_v) != TYPE_DICTIONARY:
			continue
		var entry: Dictionary = entry_v
		var qtd := int(entry.get("qtd", 1))
		if qtd <= 0:
			continue
		var glb_path := String(entry.get("glb", ""))
		var item_id := String(entry.get("id", glb_path.get_file().get_basename()))
		var doc := GLTFDocument.new()
		var state := GLTFState.new()
		state.set_base_path(glb_path.get_base_dir())
		var err := doc.append_from_file(glb_path, state)
		if err != OK:
			_fail("falha ao abrir GLB (%d): %s" % [err, glb_path])
			return false
		var scene_node := doc.generate_scene(state) as Node3D
		if scene_node == null:
			_fail("generate_scene nulo: " + glb_path)
			return false
		_strip_ucx_nodes(scene_node)
		var info := _inspect_template(scene_node)
		var bmin: Vector3 = info["bmin"]
		var bmax: Vector3 = info["bmax"]
		var extent_xz := maxf(bmax.x - bmin.x, bmax.z - bmin.z)
		if extent_xz > max_horiz:
			max_horiz = extent_xz
		_total_instances += qtd
		_expected_tris += int(info["tris_unit"]) * qtd
		_templates_keepalive.append(scene_node)
		loaded.append({
			"id": item_id,
			"glb": glb_path,
			"qtd": qtd,
			"template": scene_node,
			"info": info,
		})

	var cols := maxi(1, int(ceil(sqrt(float(maxi(1, _total_instances))))))
	var rows := maxi(1, int(ceil(float(maxi(1, _total_instances)) / float(cols))))
	var spacing := maxf(1.5, max_horiz * 1.35)

	var world_min := Vector3(INF, INF, INF)
	var world_max := Vector3(-INF, -INF, -INF)
	var cursor := 0

	for item in loaded:
		var qtd: int = item["qtd"]
		var tpl: Node3D = item["template"]
		var info: Dictionary = item["info"]
		var is_skinned: bool = info["skinned"]
		var bmin: Vector3 = info["bmin"]
		var bmax: Vector3 = info["bmax"]
		var y_offset := -bmin.y

		var item_transforms: Array[Transform3D] = []
		for k in range(qtd):
			var gx := cursor % cols
			var gz := int(cursor / cols)
			cursor += 1
			var pos := Vector3(
				(float(gx) - float(cols - 1) * 0.5) * spacing,
				y_offset,
				(float(gz) - float(rows - 1) * 0.5) * spacing
			)
			var xf := Transform3D(Basis.IDENTITY, pos)
			item_transforms.append(xf)
			world_min = world_min.min(pos + bmin)
			world_max = world_max.max(pos + bmax)

		var used_multimesh := (mode == "multimesh" and not is_skinned)
		if used_multimesh:
			var mesh_nodes: Array[MeshInstance3D] = info["mesh_nodes"]
			for mi in mesh_nodes:
				var rel_xf := _relative_transform(tpl, mi)
				var mm := MultiMesh.new()
				mm.transform_format = MultiMesh.TRANSFORM_3D
				mm.mesh = _mesh_with_overrides(mi)
				mm.instance_count = qtd
				for idx_i in range(qtd):
					mm.set_instance_transform(idx_i, item_transforms[idx_i] * rel_xf)
				var mmi := MultiMeshInstance3D.new()
				mmi.name = "MM_" + String(item["id"])
				mmi.multimesh = mm
				_assets_root.add_child(mmi)
		else:
			for idx_i in range(qtd):
				var inst := tpl.duplicate() as Node3D
				inst.transform = item_transforms[idx_i]
				_assets_root.add_child(inst)

		_items_report.append({
			"id": item["id"],
			"qtd": qtd,
			"tris_unit": info["tris_unit"],
			"tris_cena": int(info["tris_unit"]) * qtd,
			"surfaces_unit": info["surfaces_unit"],
			"mesh_nodes_unit": info["mesh_nodes_count"],
			"skinned": is_skinned,
			"placement_efetivo": "multimesh" if used_multimesh else "mesh_instance",
		})

	if world_min.x == INF:
		world_min = Vector3(-1.0, 0.0, -1.0)
		world_max = Vector3(1.0, 2.0, 1.0)

	var center := (world_min + world_max) * 0.5
	var half_ext := (world_max - world_min) * 0.5
	var radius := maxf(1.5, half_ext.length())
	var dist := (radius / sin(deg_to_rad(24.0))) * 1.25
	var cam_dir := Vector3(0.0, 0.72, 1.0).normalized()
	var cam_pos := center + cam_dir * dist
	_cam.far = maxf(5000.0, dist + radius * 5.0)
	_cam.look_at_from_position(cam_pos, center, Vector3.UP)
	_light.directional_shadow_max_distance = maxf(250.0, dist + radius * 3.0)
	return true


func _cleanup_and_quit(code: int) -> void:
	for tpl in _templates_keepalive:
		if tpl != null:
			tpl.free()
	_templates_keepalive.clear()
	if _world_node != null:
		_world_node.free()
		_world_node = null
	quit(code)


func _process(_delta: float) -> bool:
	_frame_in_phase += 1
	if _phase == 0 and _frame_in_phase >= _frames_baseline:
		_baseline = _snapshot_metrics()
		_phase = 1
		_frame_in_phase = 0
		if not _populate_scene():
			return true
		return false

	if _phase == 1 and _frame_in_phase >= _frames_measure:
		var measured := _snapshot_metrics()
		var delta_tex_bytes := maxi(0, int(measured["perf_texture_mem_bytes"]) - int(_baseline["perf_texture_mem_bytes"]))
		var payload := {
			"ok": true,
			"engine": {
				"godot_version": Engine.get_version_info().get("string", ""),
				"display_driver": DisplayServer.get_name(),
				"rendering_driver": RenderingServer.get_current_rendering_driver_name(),
				"rendering_method": RenderingServer.get_current_rendering_method(),
				"video_adapter": RenderingServer.get_video_adapter_name(),
			},
			"config": {
				"mode": String(_cfg.get("mode", "naive")),
				"shadows": bool(_cfg.get("shadows", false)),
				"frames_baseline": _frames_baseline,
				"frames_measure": _frames_measure,
			},
			"expected": {
				"total_instances": _total_instances,
				"total_tris": _expected_tris,
			},
			"baseline": _baseline,
			"measured": measured,
			"delta": {
				"draw_calls": maxi(0, int(measured["perf_draw_calls"]) - int(_baseline["perf_draw_calls"])),
				"visible_draw_calls": maxi(0, int(measured["vp_visible_draw_calls"]) - int(_baseline["vp_visible_draw_calls"])),
				"shadow_draw_calls": maxi(0, int(measured["vp_shadow_draw_calls"]) - int(_baseline["vp_shadow_draw_calls"])),
				"objects": maxi(0, int(measured["perf_objects"]) - int(_baseline["perf_objects"])),
				"primitives": maxi(0, int(measured["perf_primitives"]) - int(_baseline["perf_primitives"])),
				"visible_primitives": maxi(0, int(measured["vp_visible_primitives"]) - int(_baseline["vp_visible_primitives"])),
				"texture_mem_bytes": delta_tex_bytes,
				"texture_mem_mb": snappedf(float(delta_tex_bytes) / (1024.0 * 1024.0), 0.01),
				"total_texture_mem_mb": snappedf(float(measured["perf_texture_mem_bytes"]) / (1024.0 * 1024.0), 0.01),
			},
			"items": _items_report,
		}
		var out_file := FileAccess.open(_output_path, FileAccess.WRITE)
		if out_file == null:
			_fail("nao foi possivel gravar saida: " + _output_path)
			return true
		out_file.store_string(JSON.stringify(payload, "  "))
		out_file.close()
		print(
			"GODOT_DRAW_CALLS_OK driver=%s mode=%s shadows=%s dc=%d vis_dc=%d shad_dc=%d objs=%d vis_tris=%d tex_delta_mb=%.2f" % [
				payload["engine"]["rendering_driver"],
				payload["config"]["mode"],
				str(payload["config"]["shadows"]),
				payload["measured"]["perf_draw_calls"],
				payload["measured"]["vp_visible_draw_calls"],
				payload["measured"]["vp_shadow_draw_calls"],
				payload["measured"]["perf_objects"],
				payload["measured"]["vp_visible_primitives"],
				payload["delta"]["texture_mem_mb"],
			]
		)
		_cleanup_and_quit(0)
		return true

	return false
