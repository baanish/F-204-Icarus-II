# speed_brake_L_all roughness companion

Accepted base: art/textures/generated/full/speed_brake_L_all.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means rough and black means smooth. Default maintained satin paint is about 160 grey. Existing worn edges and walkway wear are subtly smoother, about 110 grey; existing grime and soot are rougher, about 205 grey. Keep the existing seam and fastener surface-response changes at precisely their base-image positions. The physical boundary between painted surfaces and the dark surround must match. No new scuffs, soot, walkways, panel joints or markings. This is scalar linear roughness, not a glossy photograph; no lighting, highlights or shadows.

# speed_brake_L_all

Left fuselage speed brake. Perimeter and hinge are real boundaries; restrained edge grime, no decorative slots. World-normal chart family: lower.

Generation required: True. Source: art/textures/generated/full/speed_brake_L_all.png.
Guide density 1047.0 px/m; native density at 1254 square 854.8 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [1576, 1011, 1645, 1137], guide [40, 150, 521, 1029], CCW rotation False. World bounds in metres [[0.42910823225975037, 4.550003528594971, -0.12424485385417938], [0.7213895916938782, 5.34998893737793, 0.28833505511283875]].
- Atlas [110, 406, 133, 529], guide [581, 150, 1439, 310], CCW rotation True. World bounds in metres [[0.36240172386169434, 4.550379276275635, -0.17578494548797607], [0.5596551299095154, 5.349467754364014, -0.07833999395370483]].

Closest part centroids: skin_aft_L, skin_aft_R, ventral_fin, flap_L_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from flap_L_all, skin_aft_L_lower. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/speed_brake_L_all.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/speed_brake_L_all.template.png
- art/textures/generated/full/speed_brake_L_all.neighbor_flap_L_all.png
- art/textures/generated/full/speed_brake_L_all.neighbor_skin_aft_L_lower.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
