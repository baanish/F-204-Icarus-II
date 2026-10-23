# nozzle_all roughness companion

Accepted base: art/textures/generated/full/nozzle_all.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means rough and black means smooth. Default maintained satin paint is about 160 grey. Existing worn edges and walkway wear are subtly smoother, about 110 grey; existing grime and soot are rougher, about 205 grey. Keep the existing seam and fastener surface-response changes at precisely their base-image positions. The physical boundary between painted surfaces and the dark surround must match. No new scuffs, soot, walkways, panel joints or markings. This is scalar linear roughness, not a glossy photograph; no lighting, highlights or shadows.

# nozzle_all

Fixed exhaust shroud between the rear fuselage and movable petal ring. Circumferential attachment seams, restrained aft soot and heat staining. World-normal chart family: aft.

Generation required: True. Source: art/textures/generated/full/nozzle_all.png.
Guide density 615.0 px/m; native density at 1254 square 502.1 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [562, 181, 677, 296], guide [40, 150, 511, 621], CCW rotation False. World bounds in metres [[-0.3809989094734192, 7.300000190734863, -0.01078772358596325], [0.38331925868988037, 7.300000190734863, 0.7535312175750732]].
- Atlas [1834, 1379, 1947, 1493], guide [571, 150, 1034, 617], CCW rotation False. World bounds in metres [[-0.3779924213886261, 7.311258316040039, -0.007217062171548605], [0.37842535972595215, 7.311258316040039, 0.746648371219635]].
- Atlas [1842, 1116, 1956, 1229], guide [40, 706, 507, 1169], CCW rotation False. World bounds in metres [[-0.37744203209877014, 7.288741588592529, -0.0072787003591656685], [0.3764250874519348, 7.288741588592529, 0.7465863823890686]].
- Atlas [1889, 1013, 1934, 1104], guide [567, 706, 940, 890], CCW rotation True. World bounds in metres [[-0.384958952665329, 7.006659030914307, 0.09881675243377686], [-0.27319034934043884, 7.29999303817749, 0.6399438381195068]].
- Atlas [1647, 1357, 1692, 1448], guide [1000, 706, 1373, 890], CCW rotation True. World bounds in metres [[-0.27003955841064453, 7.002264976501465, -0.01496531069278717], [0.2710871994495392, 7.295600891113281, 0.09672258049249649]].
- Atlas [1872, 661, 1917, 752], guide [40, 1254, 413, 1438], CCW rotation True. World bounds in metres [[0.27296075224876404, 7.004286766052246, 0.09856341034173965], [0.3849421739578247, 7.2976202964782715, 0.6396898031234741]].
- Atlas [1875, 561, 1920, 652], guide [473, 1254, 846, 1438], CCW rotation True. World bounds in metres [[-0.27035605907440186, 7.00579309463501, 0.6435639262199402], [0.2707710862159729, 7.299128532409668, 0.7549862861633301]].

Closest part centroids: rudder_visible, fin_skin, skin_aft_L, skin_aft_R. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from fin_left, rudder_all. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/nozzle_all.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/nozzle_all.template.png
- art/textures/generated/full/nozzle_all.neighbor_fin_left.png
- art/textures/generated/full/nozzle_all.neighbor_rudder_all.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
