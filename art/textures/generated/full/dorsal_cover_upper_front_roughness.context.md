# dorsal_cover_upper_front roughness companion

Accepted base: art/textures/generated/full/dorsal_cover_upper_front.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means rough and black means smooth. Default maintained satin paint is about 160 grey. Existing worn edges and walkway wear are subtly smoother, about 110 grey; existing grime and soot are rougher, about 205 grey. Keep the existing seam and fastener surface-response changes at precisely their base-image positions. The physical boundary between painted surfaces and the dark surround must match. No new scuffs, soot, walkways, panel joints or markings. This is scalar linear roughness, not a glossy photograph; no lighting, highlights or shadows.

# dorsal_cover_upper_front

Dorsal fuselage cover behind the canopy. Follow frame stations. Keep antenna mounting zones quiet; no antenna artwork is baked into the skin. World-normal chart family: upper.

Generation required: True. Source: art/textures/generated/full/dorsal_cover_upper_front.png.
Guide density 381.0 px/m; native density at 1254 square 311.1 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [4, 1928, 575, 2044], guide [40, 150, 1490, 444], CCW rotation False. World bounds in metres [[-0.31800055503845215, -2.975693464279175, 0.8305724263191223], [0.3165644407272339, 0.8237385153770447, 1.0403684377670288]].

Closest part centroids: skin_mid_R, skin_mid_L, intake_duct_L, gear_door_main_L_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from skin_mid_L_lower, skin_mid_L_out. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/dorsal_cover_upper_front.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/dorsal_cover_upper_front.template.png
- art/textures/generated/full/dorsal_cover_upper_front.neighbor_skin_mid_L_lower.png
- art/textures/generated/full/dorsal_cover_upper_front.neighbor_skin_mid_L_out.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
