# skin_mid_L_out height companion

Accepted base: art/textures/generated/full/skin_mid_L_out.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means raised, mid grey 128 means flush, black means recessed. Convert the existing dark panel seams and access-cover edges into narrow recessed grooves. Existing flush rivet heads are tiny raised domes centred exactly on their visible base marks, with their existing rings recessed. Preserve hinge joints and existing stiffeners. Paint grain and colour wear are not physical dents and must stay near mid grey. No new seams, fasteners, access covers or geometry. This is a scalar height map, not a lit normal map: no directional shading, lighting or shadows.

# skin_mid_L_out

Mid fuselage between intake and aft engine bay. Follow circumferential frame stations. Closed auxiliary door follows the orange guide. World-normal chart family: out.

Generation required: True. Source: art/textures/generated/full/skin_mid_L_out.png.
Guide density 303.0 px/m; native density at 1254 square 247.4 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [1529, 997, 1703, 1344], guide [40, 150, 391, 850], CCW rotation False. World bounds in metres [[0.28827035427093506, -2.368497848510742, -0.21171540021896362], [0.6451694965362549, -0.08071029931306839, 0.8584640026092529]].
- Atlas [489, 938, 1107, 1053], guide [40, 935, 1288, 1167], CCW rotation False. World bounds in metres [[0.7172813415527344, -1.1499475240707397, -0.08310648053884506], [1.0771193504333496, 2.9295451641082764, 0.5541515946388245]].
- Atlas [918, 1577, 943, 1609], guide [1348, 935, 1398, 999], CCW rotation False. World bounds in metres [[0.0059999823570251465, -1.70274817943573, -0.6536381244659424], [0.0059999823570251465, -1.4960438013076782, -0.49297454953193665]].
- Atlas [970, 1577, 996, 1609], guide [40, 1252, 92, 1316], CCW rotation False. World bounds in metres [[-0.0059999823570251465, -1.7027671337127686, -0.656960129737854], [-0.0059999823570251465, -1.496064305305481, -0.4896298050880432]].
- Atlas [1118, 938, 1143, 1449], guide [152, 1252, 1184, 1302], CCW rotation True. World bounds in metres [[0.3720358908176422, -2.365379810333252, -0.38197776675224304], [0.44773563742637634, 1.0316263437271118, -0.220412015914917]].
- Atlas [1468, 664, 1487, 901], guide [40, 1401, 518, 1439], CCW rotation True. World bounds in metres [[0.2820843756198883, 1.3516803979873657, 0.7186977863311768], [0.3655114769935608, 2.924899101257324, 0.8229721188545227]].

Closest part centroids: intake_duct_L, dorsal_cover, skin_mid_R, wing_skin_L. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from wing_root, wing_upper. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/skin_mid_L_out.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/skin_mid_L_out.template.png
- art/textures/generated/full/skin_mid_L_out.neighbor_wing_root.png
- art/textures/generated/full/skin_mid_L_out.neighbor_wing_upper.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
