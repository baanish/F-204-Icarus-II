# Reuse the registered generation atlas

The 33 accepted source group names and native chart layouts stay in `native/parts.json`.
Its masks, ordered transfers, provenance records and input hashes are persisted here.
Original generated PNGs, guides, templates, contexts and prompts remain in their source folders.
Native registration still requires silhouette IoU >= 0.70 and density >= 180 px/m.
Companion acceptance runs before remapping with the existing native alignment gates.

`current/parts.json` assigns the current atlas through maps in `current/`.
Each rule reads immutable generation-atlas indices and writes current-atlas indices.
Apply rules in listed order to base RGB, height, roughness, both validity masks and used.
Current group masks describe mapped ownership. Native chart registration uses the source manifest.
Distances and normal agreement measure physical reuse independently of source registration.
New and replaced gear doors and brake panels carry nearest parent paint, not new authored detail.
Brake wells use the separate mechanical material and are outside this skin atlas.

After prepare and audit finish, inventory automatically remaps a changed geometry bake
from the frozen native generation inputs. No source snapshot argument or manual hash is needed:

```powershell
python art/textures/full_skin_guides.py inventory
python art/textures/full_skin_guides.py check
python art/textures/full_skin_guides.py guides
python art/textures/full_skin_registration.py
```

After copying this source pack and the original generated folders into another checkout,
prepare and audit the geometry, then run `python art/textures/full_skin_guides.py inventory`.
`restore` also rebuilds changed maps. Readers resolve repo-relative metadata in the
active checkout. Convert legacy records with `python tools/Make-TextureRecordsPortable.py`
before inventory; the conversion refreshes metadata hashes and preserves source images.
The exact old generation bake and pilot metadata are retained in `native/generation-inputs`
for independent source-atlas coverage checks. No ignored old cache is required.
Unknown canonical parts choose one source physical part by minimum whole-part RMS nearest
world position and normal distance. Normal weight is 0.02 m. Equal scores choose the
lexically first source name. Every such decision records candidate scores, marks the whole
part as parent paint and reports an art limitation. Named new-door donor rules stay fixed.
The bake and atlas hashes must stay unchanged throughout each rebuild.
Current ownership guides go to the review cache. They never replace generation references.
`remap_fields(source_fields, manifest_path)` preserves native registration report counts and
returns the six mapped arrays plus current coverage evidence in `report.source_atlas_mapping`.
