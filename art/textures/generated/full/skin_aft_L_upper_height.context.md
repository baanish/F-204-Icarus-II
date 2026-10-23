# skin_aft_L_upper height companion

Accepted base: art/textures/generated/full/skin_aft_L_upper.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means raised, mid grey 128 means flush, black means recessed. Convert the existing dark panel seams and access-cover edges into narrow recessed grooves. Existing flush rivet heads are tiny raised domes centred exactly on their visible base marks, with their existing rings recessed. Preserve hinge joints and existing stiffeners. Paint grain and colour wear are not physical dents and must stay near mid grey. No new seams, fasteners, access covers or geometry. This is a scalar height map, not a lit normal map: no directional shading, lighting or shadows.

# skin_aft_L_upper

Aft engine-bay fuselage ahead of the exhaust. Closed underside vent cover follows the orange guide. Restrained soot only near the nozzle. World-normal chart family: upper.

Generation required: True. Source: art/textures/generated/full/skin_aft_L_upper.png.
Guide density 504.0 px/m; native density at 1254 square 411.5 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [1481, 1610, 1559, 2042], guide [40, 150, 1491, 412], CCW rotation True. World bounds in metres [[6.969086825847626e-06, 4.353140830993652, 0.6320043802261353], [0.4593621492385864, 7.199963569641113, 1.042203664779663]].
- Atlas [32, 361, 100, 528], guide [40, 497, 601, 725], CCW rotation True. World bounds in metres [[0.36828988790512085, 2.9296231269836426, 0.4330299198627472], [0.7148416042327881, 4.036726474761963, 0.7176685929298401]].

Closest part centroids: speed_brake_L_visible, skin_aft_R, ventral_fin, flap_L_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
No generated physical-neighbour edge image exists yet; retain uniform neutral margins.

References in image order:
- art/textures/generated/full/skin_aft_L_upper.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/skin_aft_L_upper.template.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
