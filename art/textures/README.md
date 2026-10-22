# Icarus skin maps

The compositor makes nine 2048-square PNGs from generated unmarked surface art, current geometry bakes and scripted scheme data. The Navy atlas is both `_Basecolor` and livery 1. Exact generated prompts sit beside every source PNG in `generated/`. The Barlow Condensed font is for review captions; `fonts/OFL.txt` carries its licence. Aircraft lettering comes from generated sheets.

Run from the repository root, stopping at any failed command:

```powershell
pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python art/blender/bake_skin.py -- prepare
pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python art/blender/bake_skin.py -- audit
python art/textures/compose_skin.py compose
pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python tools/export_blockout.py
python tools/export_manifest.py --write
python art/textures/compose_skin.py measure
pwsh -NoProfile -File tools/Run-Blender.ps1 --background --factory-startup --python-exit-code 1 --python art/blender/bake_skin.py -- review
python art/textures/review_skin.py
pwsh -NoProfile -File tools/Link-WorktreeAssets.ps1
pwsh -NoProfile -File tools/Build-Icarus.ps1
```

`prepare` runs the current generator and UV checks, saves `geometry.blend`, bakes signed position, shading normal and part ID, then AO. Mirror pairs bake from the left only. AO uses 128 occlusion probes per texel. Bake copies are separated by 30 metres for self AO. Each paired forward, mid and aft fuselage shell shares assembly occluders with its fuselage section, and the left wing skin shares its box. Moving parts and stations have self AO only. Trim faces bake to a separate sink image, while still occluding their own skin. If only AO needs rebuilding, `bake_skin.py -- ao` resumes from `geometry.blend`.

Four 1152-square regions, overlapping by 256 pixels, assemble the accepted generated neutral base. The compositor rejects native inputs below 1152 pixels. An 18-pixel masked local mean removes broad source colour. Scripted reflected world-position fields provide the scheme. Generated detail fades over seven texels at island boundaries, and eight texels of colour extend into gutters. Decals touch only unique forward-fuselage and fin islands.

Nozzle skin islands added after the source-atlas pilot use the accepted unmarked `bare_metal.png` through reflected world triplanar projection. That supplies fine detail where the old source silhouettes contain gutters. Scheme colour, normal relief, cavity and smoothness still come through the same compositor. `composition.json` records those parts and source coverage for every part.

`panels.py` extracts dark seam centres and compact fastener marks from the same luminance residual used by the colour maps. It makes 2 to 3 texel grooves and 1 to 2 texel dimples, then derives tangent normals, cavity AO and reduced smoothness from that height field. The closed gun-port access panel has no opening. `damage.py` projects generated soot and torn-metal source art in reflected world coordinates, then derives dent normals from it.

`measure` rejects a livery seam median above 2.26 RGB levels, checks PNG dimensions and RGB livery encoding, records current mirror checks, and writes `gate.json` with input and output hashes. A gate remains `pipeline_accepted: false` until the owner accepts it. Regenerate the gate after integrated geometry, source or export-manifest changes.

Review outputs go under `.cache/review/wave2/p9b/02/`. The review includes four views of every livery with stations loaded and empty, nose and wing-root close-ups, matched raking-light clay and Navy views, normal-and-AO clay views, open/deployed/detached AO states and full damage. Stock store meshes are local review references loaded through `tools/local-paths.json`; no stock texture is read or supplied to image generation.

After a change to one scheme, `bake_skin.py -- review --livery 3` rerenders only that livery's ten views. Rerun `review_skin.py` afterwards to refresh sheets and hashes. A complete `review` remains required when shared maps or geometry change.

The stock shader has one shared metallic map. It follows the plan's painted-skin versus bare-aft-region policy. Livery 4 uses its own generated metal source and the supported per-livery glossiness value; it cannot switch metallic R for the entire airframe without changing the shader contract. Blender previews use the shared metallic/smoothness map. That limitation needs owner review with the Bare Metal scheme.

Unity imports SHA-checked maps and writes four Primeva `LiveryData` assets. A13 checks slot 0, damage registration, UV bounds, map dimensions and types, metallic alpha, distinct DXT1 liveries and faction ownership. Offline PNG checks do not establish Unity compression, runtime blending, detach dissolve, LOD or multiplayer behaviour. No game runs belong to this offline pipeline.
