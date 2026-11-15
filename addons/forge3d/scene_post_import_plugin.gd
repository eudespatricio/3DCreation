@tool
extends EditorScenePostImportPlugin
## Plugin EditorScenePostImportPlugin zero-click para Godot 4.
## Aplica automaticamente o post-import Forge3D em qualquer .glb com .manifest.json irmao.

const PostImport := preload("post_import.gd")
var _source_queue: Array[String] = []


func _get_import_options(path: String) -> void:
	if path != "":
		_source_queue.append(path)


func _post_process(scene: Node) -> void:
	if scene == null:
		if not _source_queue.is_empty():
			_source_queue.pop_front()
		return
	var source_path := ""
	if not _source_queue.is_empty():
		source_path = String(_source_queue.pop_front())
	if source_path == "":
		source_path = scene.scene_file_path
	if scene.has_meta("forge3d_post_imported"):
		return
	PostImport.aplicar(scene, source_path)
