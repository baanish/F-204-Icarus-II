# lef_L_all roughness companion

Accepted base: art/textures/generated/full/lef_L_all.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means rough and black means smooth. Default maintained satin paint is about 160 grey. Existing worn edges and walkway wear are subtly smoother, about 110 grey; existing grime and soot are rougher, about 205 grey. Keep the existing seam and fastener surface-response changes at precisely their base-image positions. The physical boundary between painted surfaces and the dark surround must match. No new scuffs, soot, walkways, panel joints or markings. This is scalar linear roughness, not a glossy photograph; no lighting, highlights or shadows.

# lef_L_all

Left leading-edge flap. Smooth leading nose, hinge at its aft cut. No walkway, fuel filler or access grid. World-normal chart family: lower.

Generation required: True. Source: art/textures/generated/full/lef_L_all.png.
Guide density 843.0 px/m; native density at 1254 square 688.2 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [1772, 964, 1820, 1223], guide [40, 150, 1495, 419], CCW rotation True. World bounds in metres [[1.9560728073120117, 1.4711222648620605, -0.2865457236766815], [3.2739267349243164, 2.572148323059082, -0.04436938837170601]].
- Atlas [1780, 217, 1828, 476], guide [40, 504, 1495, 773], CCW rotation True. World bounds in metres [[1.9560600519180298, 1.474930763244629, -0.2732340097427368], [3.2739899158477783, 2.575960397720337, -0.021679729223251343]].

Closest part centroids: pylon_inner_L, pylon_inner_plug_L, wing_skin_L, aileron_L_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from wing_root, wing_upper. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/lef_L_all.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/lef_L_all.template.png
- art/textures/generated/full/lef_L_all.neighbor_wing_root.png
- art/textures/generated/full/lef_L_all.neighbor_wing_upper.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
