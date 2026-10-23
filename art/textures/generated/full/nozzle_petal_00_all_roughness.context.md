# nozzle_petal_00_all roughness companion

Accepted base: art/textures/generated/full/nozzle_petal_00_all.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means rough and black means smooth. Default maintained satin paint is about 160 grey. Existing worn edges and walkway wear are subtly smoother, about 110 grey; existing grime and soot are rougher, about 205 grey. Keep the existing seam and fastener surface-response changes at precisely their base-image positions. The physical boundary between painted surfaces and the dark surround must match. No new scuffs, soot, walkways, panel joints or markings. This is scalar linear roughness, not a glossy photograph; no lighting, highlights or shadows.

# nozzle_petal_00_all

Representative variable exhaust petal. Fine longitudinal heat streaks and restrained soot toward the aft lip; preserve overlap edges. Shared around the engine axis.

Generation required: True. Source: art/textures/generated/full/nozzle_petal_00_all.png.
Guide density 1047.0 px/m; native density at 1254 square 854.8 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [1661, 356, 1681, 427], guide [40, 150, 535, 289], CCW rotation True. World bounds in metres [[0.2868504524230957, 7.300923824310303, 0.3062610626220703], [0.35985371470451355, 7.761848449707031, 0.43292778730392456]].

Closest part centroids: nozzle, rudder_visible, fin_skin, stabilator_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from fin_left, rudder_all. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/nozzle_petal_00_all.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/nozzle_petal_00_all.template.png
- art/textures/generated/full/nozzle_petal_00_all.neighbor_fin_left.png
- art/textures/generated/full/nozzle_petal_00_all.neighbor_rudder_all.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
