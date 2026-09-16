#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 INPUT_IMAGE OUTPUT_DIR [generator options...]" >&2
  exit 2
fi

input_image="$1"
output_dir="$2"
shift 2

if [[ ! -f "$input_image" ]]; then
  echo "Input image not found: $input_image" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
input_image="$(cd "$(dirname "$input_image")" && pwd)/$(basename "$input_image")"
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
success_marker="$output_dir/.image-to-3d-success-$$"
rm -f "$success_marker"
trap 'rm -f "$success_marker"' EXIT

if [[ -n "${BLENDER_BIN:-}" ]]; then
  blender_bin="$BLENDER_BIN"
elif command -v blender >/dev/null 2>&1; then
  blender_bin="$(command -v blender)"
elif [[ -x /Applications/Blender.app/Contents/MacOS/Blender ]]; then
  blender_bin=/Applications/Blender.app/Contents/MacOS/Blender
else
  echo "Blender was not found. Install it with: brew install --cask blender" >&2
  echo "Or set BLENDER_BIN to the Blender executable." >&2
  exit 127
fi

"$blender_bin" --background --factory-startup --python "$script_dir/image_to_3d.py" -- \
  --input "$input_image" \
  --output-dir "$output_dir" \
  --success-marker "$success_marker" \
  "$@"

if [[ ! -s "$success_marker" || ! -s "$output_dir/object.glb" || ! -s "$output_dir/preview.png" || ! -s "$output_dir/object.blend" || ! -s "$output_dir/manifest.json" ]]; then
  echo "Blender did not complete all expected outputs." >&2
  exit 1
fi

echo "Created:"
echo "  $output_dir/object.glb"
echo "  $output_dir/preview.png"
echo "  $output_dir/object.blend"
echo "  $output_dir/manifest.json"
