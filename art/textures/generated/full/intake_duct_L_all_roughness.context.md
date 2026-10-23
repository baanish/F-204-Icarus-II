# intake_duct_L_all roughness companion

Accepted base: art/textures/generated/full/intake_duct_L_all.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means rough and black means smooth. Default maintained satin paint is about 160 grey. Existing worn edges and walkway wear are subtly smoother, about 110 grey; existing grime and soot are rougher, about 205 grey. Keep the existing seam and fastener surface-response changes at precisely their base-image positions. The physical boundary between painted surfaces and the dark surround must match. No new scuffs, soot, walkways, panel joints or markings. This is scalar linear roughness, not a glossy photograph; no lighting, highlights or shadows.

# intake_duct_L_all

Left intake lip and duct. Smooth clean lip, restrained downstream grime, no walkway or fuel filler. World-normal chart family: aft.

Generation required: True. Source: art/textures/generated/full/intake_duct_L_all.png.
Guide density 645.0 px/m; native density at 1254 square 526.6 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [1120, 1954, 1209, 2043], guide [40, 150, 422, 532], CCW rotation False. World bounds in metres [[0.2839243710041046, -0.6000000238418579, -0.07672814279794693], [0.877184271812439, -0.6000000238418579, 0.5160945653915405]].
- Atlas [464, 135, 519, 299], guide [482, 150, 1187, 386], CCW rotation True. World bounds in metres [[0.41165757179260254, -1.839484453201294, 0.22184281051158905], [0.7472886443138123, -0.7800423502922058, 0.45861268043518066]].
- Atlas [7, 628, 61, 789], guide [40, 617, 732, 849], CCW rotation True. World bounds in metres [[0.34085187315940857, -1.8241326808929443, 0.05609218031167984], [0.5759007334709167, -0.7800009846687317, 0.38734912872314453]].
- Atlas [398, 136, 452, 299], guide [792, 617, 1492, 849], CCW rotation True. World bounds in metres [[0.41556957364082336, -1.832262635231018, -0.018522530794143677], [0.7468199729919434, -0.7800127267837524, 0.2177426815032959]].
- Atlas [531, 134, 585, 296], guide [40, 934, 736, 1166], CCW rotation True. World bounds in metres [[0.5833688974380493, -1.829741358757019, 0.05431416258215904], [0.8187538981437683, -0.7800423502922058, 0.38554471731185913]].
- Atlas [1915, 209, 1942, 278], guide [796, 934, 1092, 1050], CCW rotation True. World bounds in metres [[0.7584742307662964, -0.7448435425758362, 0.014215187169611454], [0.8792076706886292, -0.6001113653182983, 0.42859572172164917]].
- Atlas [1921, 1543, 1947, 1613], guide [1152, 934, 1453, 1045], CCW rotation True. World bounds in metres [[0.2820145785808563, -0.7446767687797546, 0.009910877794027328], [0.4009554088115692, -0.6002042889595032, 0.42924630641937256]].
- Atlas [1172, 104, 1198, 173], guide [40, 1251, 336, 1362], CCW rotation True. World bounds in metres [[0.37219101190567017, -0.7449925541877747, -0.07807120680809021], [0.7863219976425171, -0.6000602841377258, 0.039900973439216614]].
- Atlas [631, 104, 657, 173], guide [396, 1251, 692, 1362], CCW rotation True. World bounds in metres [[0.373690664768219, -0.7449834942817688, 0.39993730187416077], [0.7877950668334961, -0.6001669764518738, 0.517937183380127]].

Closest part centroids: skin_mid_L, skin_mid_R, dorsal_cover, gear_door_N_L_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from dorsal_cover_upper_front, dorsal_cover_upper_rear. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/intake_duct_L_all.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/intake_duct_L_all.template.png
- art/textures/generated/full/intake_duct_L_all.neighbor_dorsal_cover_upper_front.png
- art/textures/generated/full/intake_duct_L_all.neighbor_dorsal_cover_upper_rear.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
