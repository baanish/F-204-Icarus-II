# skin_mid_L_lower height companion

Accepted base: art/textures/generated/full/skin_mid_L_lower.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means raised, mid grey 128 means flush, black means recessed. Convert the existing dark panel seams and access-cover edges into narrow recessed grooves. Existing flush rivet heads are tiny raised domes centred exactly on their visible base marks, with their existing rings recessed. Preserve hinge joints and existing stiffeners. Paint grain and colour wear are not physical dents and must stay near mid grey. No new seams, fasteners, access covers or geometry. This is a scalar height map, not a lit normal map: no directional shading, lighting or shadows.

# skin_mid_L_lower

Mid fuselage between intake and aft engine bay. Follow circumferential frame stations. Closed auxiliary door follows the orange guide. World-normal chart family: lower.

Generation required: True. Source: art/textures/generated/full/skin_mid_L_lower.png.
Guide density 270.0 px/m; native density at 1254 square 220.4 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [297, 1731, 1104, 1917], guide [40, 150, 1492, 484], CCW rotation False. World bounds in metres [[7.177712859629537e-07, -2.3684940338134766, -0.509922981262207], [1.0130797624588013, 2.929588556289673, 0.12908487021923065]].

Closest part centroids: intake_duct_L, dorsal_cover, skin_mid_R, wing_skin_L. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from wing_root, wing_upper. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/skin_mid_L_lower.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/skin_mid_L_lower.template.png
- art/textures/generated/full/skin_mid_L_lower.neighbor_wing_root.png
- art/textures/generated/full/skin_mid_L_lower.neighbor_wing_upper.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
