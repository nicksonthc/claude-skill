# Quality guide

## Good direct inputs

Transparent PNGs with a single centered object, a clean outer contour, at least 512 px on the longest side, and minimal holes work best. Logos, badges, signs, control panels, tokens, and flat product silhouettes are strong candidates.

## Settings

- `--resolution`: contour grid size on the longest image side. Start at 192; use 256 for detailed edges and 96 for quick drafts.
- `--alpha-threshold`: pixels at or above this alpha become geometry. Start at 0.1; raise it to remove soft halos.
- `--background alpha`: use source transparency.
- `--background white`: derive the mask from distance to white for an image with a nearly white background.
- `--background-threshold`: white-background distance cutoff. Start at 0.12 and raise it when pale object areas disappear.
- `--thickness`: depth as a fraction of the object's final maximum XY dimension.
- `--size`: final maximum XY dimension in Blender units.
- `--bevel`: edge bevel width in Blender units. Keep this small relative to thickness.

## Iteration order

First fix the mask and contour. Then tune thickness and bevel. Finally check scale, front direction, origin, and ground contact in the consuming scene. If the requested object needs true rounded volume or a believable unseen back, switch to multi-view or AI mesh reconstruction instead of over-tuning the silhouette.
