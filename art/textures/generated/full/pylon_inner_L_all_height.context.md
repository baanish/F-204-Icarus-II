# pylon_inner_L_all height companion

Accepted base: art/textures/generated/full/pylon_inner_L_all.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means raised, mid grey 128 means flush, black means recessed. Convert the existing dark panel seams and access-cover edges into narrow recessed grooves. Existing flush rivet heads are tiny raised domes centred exactly on their visible base marks, with their existing rings recessed. Preserve hinge joints and existing stiffeners. Paint grain and colour wear are not physical dents and must stay near mid grey. No new seams, fasteners, access covers or geometry. This is a scalar height map, not a lit normal map: no directional shading, lighting or shadows.

# pylon_inner_L_all

Left inner stores pylon. Wing attachment above, store attachment below. Sparse service fasteners and clean neutral seam margins. World-normal chart family: in.

Generation required: True. Source: art/textures/generated/full/pylon_inner_L_all.png.
Guide density 819.0 px/m; native density at 1254 square 668.6 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [1753, 614, 1775, 877], guide [40, 150, 1475, 270], CCW rotation True. World bounds in metres [[1.7766642570495605, 1.3819859027862549, -0.06449323892593384], [1.9163063764572144, 3.1255924701690674, -0.017337488010525703]].
- Atlas [1738, 886, 1759, 1151], guide [40, 355, 1486, 469], CCW rotation True. World bounds in metres [[1.7760192155838013, 1.3877161741256714, -0.14813509583473206], [1.8426858186721802, 3.1295006275177, -0.018384097144007683]].
- Atlas [27, 1011, 47, 1277], guide [40, 554, 1492, 663], CCW rotation True. World bounds in metres [[1.8551709651947021, 1.3876978158950806, -0.14832192659378052], [1.921998381614685, 3.129739761352539, -0.02593691647052765]].
- Atlas [1759, 1232, 1775, 1495], guide [40, 748, 1475, 835], CCW rotation True. World bounds in metres [[1.7961243391036987, 1.3804535865783691, -0.14832444489002228], [1.8961272239685059, 3.1271204948425293, -0.14832444489002228]].

Closest part centroids: pylon_inner_plug_L, wing_skin_L, lef_L_visible, flap_L_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from wing_root, wing_upper. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/pylon_inner_L_all.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/pylon_inner_L_all.template.png
- art/textures/generated/full/pylon_inner_L_all.neighbor_wing_root.png
- art/textures/generated/full/pylon_inner_L_all.neighbor_wing_upper.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
