@tool
extends EditorPlugin

const PostImport := preload("post_import.gd")
var _importer: EditorScenePostImportPlugin


class Forge3DPostImportPlugin extends EditorScenePostImportPlugin:
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
		PostImport.aplicar(scene, source_path)


func _enter_tree() -> void:
	_importer = Forge3DPostImportPlugin.new()
	add_scene_post_import_plugin(_importer)


func _exit_tree() -> void:
	if _importer != null:
		remove_scene_post_import_plugin(_importer)
		_importer = null
