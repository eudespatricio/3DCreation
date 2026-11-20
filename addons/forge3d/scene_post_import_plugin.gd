@tool
extends EditorScenePostImportPlugin
## Plugin EditorScenePostImportPlugin zero-click para Godot 4.
## Aplica automaticamente o post-import Forge3D em qualquer .glb com .manifest.json irmao.

const PostImport := preload("post_import.gd")
var _ultimo_caminho: String = ""


func _get_import_options(path: String) -> void:
	if path != "":
		_ultimo_caminho = path


func _post_process(scene: Node) -> void:
	if scene == null:
		_ultimo_caminho = ""
		return
	var source_path := scene.scene_file_path
	if source_path == "":
		source_path = _ultimo_caminho
	_ultimo_caminho = ""
	if scene.has_meta("forge3d_post_imported"):
		return
	PostImport.aplicar(scene, source_path)
