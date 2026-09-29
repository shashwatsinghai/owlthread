# OwlThread companion artwork

`owl-realistic.png` was generated with the built-in image generation tool for the floating browser companion. The original transparent RGBA image is kept unmodified. It is packaged locally; the extension does not fetch artwork from an external server.

Final generation prompt:

Use case: photorealistic-natural. Asset type: transparent PNG cutout mascot for a browser extension named OwlThread. Primary request: one extremely realistic small Eurasian eagle owl, full body, looking straight at viewer, perched upright with both talons visible but no perch. Actual natural owl proportions, rounded feathered body, symmetrical face and amber gold irises, fine brown and warm grey feather detail, cream facial disks, tiny dark beak, subtle ear tufts. Premium wildlife photography, soft studio key light from upper left and gentle rim light, tactile layered feathers. Wings neatly folded against body. Center owl at x=50%, head near upper third, full animal fills about 88% of canvas height and 72% width. Square composition, clean fully transparent alpha background including between talons; no ground, branch, environment, framing, text, badge, UI, pedestal, glow or accessories. Anatomically believable and alert, not cartoon, not vector, not toy. This will be displayed at about 110px high over both light and dark websites so silhouette and eyes must be especially crisp.

## Cozy developer mascot (current)

`owl-cozy-developer.png` is the current transparent mascot, generated using the built-in image generation tool. The generated RGBA file is preserved without raster edits. The exact final prompt is in `cozy-owl-prompt.txt`.

The original realistic artwork remains available as the previous version. The shipped companion, popup and help now use the cozy mascot.

The animated character groups the original artwork, live eyes and vector props in one moving body. CSS and small inline SVG props supply the opening notebook, writing wing/pencil, drawn note lines, handheld magnifying glass, lens glint and success sparkles. The gaze, blink timing and action states are driven by `companion.ts`. No external image requests are made by the extension.

Browser checks generate a standalone animated showcase at `tests/artifacts/cozy-owl-preview.html` and screenshots of the writing and inspecting states.
