@tool
extends EditorPlugin

const PostImport := preload("post_import.gd")
var _importer: EditorScenePostImportPlugin


class Forge3DPostImportPlugin extends EditorScenePostImportPlugin:
	func _post_process(scene: Node) -> void:
		if scene == null:
			return
		PostImport.aplicar(scene, scene.scene_file_path)


func _enter_tree() -> void:
	_importer = Forge3DPostImportPlugin.new()
	add_scene_post_import_plugin(_importer)


func _exit_tree() -> void:
	if _importer != null:
		remove_scene_post_import_plugin(_importer)
		_importer = null
