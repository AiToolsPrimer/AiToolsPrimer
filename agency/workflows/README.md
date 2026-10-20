# ComfyUI workflows

The agency drives ComfyUI through its HTTP API. Each file here is a workflow exported
with **Workflow > Export (API)** from ComfyUI, with the values the agency controls
replaced by string tokens:

| token | meaning |
|---|---|
| `"__PROMPT__"` | positive prompt |
| `"__NEGATIVE__"` | negative prompt |
| `"__SEED__"` | integer seed |
| `"__WIDTH__"` / `"__HEIGHT__"` | output size |
| `"__FRAMES__"` / `"__FPS__"` | video length and frame rate |
| `"__IMAGE__"` | absolute path of the input image (edit / avatar) |
| `"__AUDIO__"` | absolute path of the voice track (avatar) |
| `"__MODEL__"` | model identifier |

Files the agency looks for (first match wins):

- `qwen-image-2512.json`, then `image.json` – text-to-image
- `qwen-image-edit-2511.json`, then `image-edit.json` – image editing
- `video.json` – LTX-2.5 text-to-video (if absent, the MLX command template in `agency.yaml` is used)
- `avatar.json` – LTX MLX audio-to-video presenter

`agency doctor` reports which ones are present. The `*.example.json` files show the
token placement on a minimal graph; replace the node ids with the ones from your export.
