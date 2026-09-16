#!/usr/bin/env python3
"""Build an extruded, textured silhouette from one image inside Blender."""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--success-marker")
    parser.add_argument("--size", type=float, default=2.0)
    parser.add_argument("--thickness", type=float, default=0.12)
    parser.add_argument("--resolution", type=int, default=192)
    parser.add_argument("--alpha-threshold", type=float, default=0.1)
    parser.add_argument("--background", choices=("alpha", "white"), default="alpha")
    parser.add_argument("--background-threshold", type=float, default=0.12)
    parser.add_argument("--bevel", type=float, default=0.015)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(argv)
    if args.size <= 0 or args.thickness <= 0 or args.resolution < 8:
        parser.error("size and thickness must be positive; resolution must be at least 8")
    return args


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def sample_mask(image, longest_side, alpha_threshold, background, background_threshold):
    width, height = image.size
    if width < 1 or height < 1:
        raise ValueError("Image has invalid dimensions")
    scale = min(1.0, longest_side / max(width, height))
    cols = max(2, round(width * scale))
    rows = max(2, round(height * scale))
    pixels = list(image.pixels)
    mask = []
    for row in range(rows):
        source_y = min(height - 1, int((row + 0.5) * height / rows))
        line = []
        for col in range(cols):
            source_x = min(width - 1, int((col + 0.5) * width / cols))
            index = 4 * (source_y * width + source_x)
            red, green, blue, alpha = pixels[index : index + 4]
            if background == "white":
                distance = math.sqrt((1-red) ** 2 + (1-green) ** 2 + (1-blue) ** 2) / math.sqrt(3)
                active = alpha >= alpha_threshold and distance >= background_threshold
            else:
                active = alpha >= alpha_threshold
            line.append(active)
        mask.append(line)
    return mask, cols, rows, width, height


def build_mesh(mask, cols, rows, size, thickness):
    cell = size / max(cols, rows)
    actual_width = cols * cell
    actual_height = rows * cell
    half_depth = size * thickness / 2
    vertices = []
    faces = []
    face_uvs = []

    def add_quad(points, uvs):
        start = len(vertices)
        vertices.extend(points)
        faces.append((start, start + 1, start + 2, start + 3))
        face_uvs.append(uvs)

    def point(x, y, z):
        return (x * cell - actual_width / 2, y * cell - actual_height / 2, z)

    active_count = 0
    for row in range(rows):
        for col in range(cols):
            if not mask[row][col]:
                continue
            active_count += 1
            u0, u1 = col / cols, (col + 1) / cols
            v0, v1 = row / rows, (row + 1) / rows
            front = [point(col, row, half_depth), point(col + 1, row, half_depth),
                     point(col + 1, row + 1, half_depth), point(col, row + 1, half_depth)]
            back = [point(col + 1, row, -half_depth), point(col, row, -half_depth),
                    point(col, row + 1, -half_depth), point(col + 1, row + 1, -half_depth)]
            add_quad(front, [(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
            add_quad(back, [(u1, v0), (u0, v0), (u0, v1), (u1, v1)])
            neighbors = {
                "bottom": row == 0 or not mask[row - 1][col],
                "top": row == rows - 1 or not mask[row + 1][col],
                "left": col == 0 or not mask[row][col - 1],
                "right": col == cols - 1 or not mask[row][col + 1],
            }
            side_uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
            if neighbors["bottom"]:
                add_quad([point(col, row, -half_depth), point(col + 1, row, -half_depth),
                          point(col + 1, row, half_depth), point(col, row, half_depth)], side_uv)
            if neighbors["right"]:
                add_quad([point(col + 1, row, -half_depth), point(col + 1, row + 1, -half_depth),
                          point(col + 1, row + 1, half_depth), point(col + 1, row, half_depth)], side_uv)
            if neighbors["top"]:
                add_quad([point(col + 1, row + 1, -half_depth), point(col, row + 1, -half_depth),
                          point(col, row + 1, half_depth), point(col + 1, row + 1, half_depth)], side_uv)
            if neighbors["left"]:
                add_quad([point(col, row + 1, -half_depth), point(col, row, -half_depth),
                          point(col, row, half_depth), point(col, row + 1, half_depth)], side_uv)
    if active_count == 0:
        raise ValueError("No foreground pixels found; check transparency/background settings")

    mesh = bpy.data.meshes.new("ImageSilhouetteMesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon, uvs in zip(mesh.polygons, face_uvs):
        for loop_index, uv in zip(polygon.loop_indices, uvs):
            uv_layer.data[loop_index].uv = uv
    obj = bpy.data.objects.new("ImageSilhouette", mesh)
    bpy.context.collection.objects.link(obj)
    return obj, active_count, cell


def create_material(image):
    material = bpy.data.materials.new("ReferenceImageMaterial")
    material.use_nodes = True
    material.surface_render_method = "DITHERED"
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.get("Principled BSDF")
    shader.inputs["Roughness"].default_value = 0.55
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
    return material


def look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_preview_scene(obj, size):
    obj.rotation_euler = (math.radians(90), 0, 0)
    min_z = min((obj.matrix_world @ Vector(corner)).z for corner in obj.bound_box)
    obj.location.z -= min_z

    camera_data = bpy.data.cameras.new("PreviewCamera")
    camera = bpy.data.objects.new("PreviewCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = (size * 2.25, -size * 2.8, size * 1.8)
    camera.data.lens = 58
    look_at(camera, (0, 0, size * 0.65))
    bpy.context.scene.camera = camera

    for name, location, energy, radius in (
        ("Key", (-size * 2, -size * 2, size * 3), 900, size * 2),
        ("Fill", (size * 2, -size, size * 1.5), 500, size * 1.5),
        ("Rim", (0, size * 2, size * 2.5), 700, size),
    ):
        light_data = bpy.data.lights.new(name, "AREA")
        light_data.energy = energy
        light_data.shape = "DISK"
        light_data.size = radius
        light = bpy.data.objects.new(name, light_data)
        bpy.context.collection.objects.link(light)
        light.location = location
        look_at(light, (0, 0, size * 0.5))

    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.035, 0.04, 0.05, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.35


def main():
    args = parse_args()
    source = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        raise FileNotFoundError(source)

    clear_scene()
    image = bpy.data.images.load(str(source), check_existing=False)
    image.colorspace_settings.name = "sRGB"
    mask, cols, rows, width, height = sample_mask(
        image, args.resolution, args.alpha_threshold, args.background, args.background_threshold
    )
    obj, active_count, cell = build_mesh(mask, cols, rows, args.size, args.thickness)
    obj.data.materials.append(create_material(image))
    weld = obj.modifiers.new("MergeGrid", "WELD")
    weld.merge_threshold = cell * 0.01
    if args.bevel > 0:
        bevel = obj.modifiers.new("EdgeBevel", "BEVEL")
        bevel.width = args.bevel
        bevel.segments = 2
        bevel.limit_method = "ANGLE"

    add_preview_scene(obj, args.size)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 768
    scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = True
    scene.render.filepath = str(output_dir / "preview.png")
    scene.view_settings.look = "AgX - Medium High Contrast"

    bpy.ops.wm.save_as_mainfile(filepath=str(output_dir / "object.blend"))
    bpy.ops.render.render(write_still=True)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=str(output_dir / "object.glb"),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
    )

    manifest = {
        "source": str(source),
        "source_size": [width, height],
        "sample_grid": [cols, rows],
        "foreground_cells": active_count,
        "settings": {key: value for key, value in vars(args).items() if key != "success_marker"},
        "outputs": {
            "glb": str(output_dir / "object.glb"),
            "preview": str(output_dir / "preview.png"),
            "blend": str(output_dir / "object.blend"),
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if args.success_marker:
        Path(args.success_marker).write_text("ok\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
