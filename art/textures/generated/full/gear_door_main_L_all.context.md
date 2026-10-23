# gear_door_main_L_all

Left main gear door. Follow perimeter and hinge, restrained wheel-well grime inside. World-normal chart family: upper.

Generation required: True. Source: art/textures/generated/full/gear_door_main_L_all.png.
Guide density 834.0 px/m; native density at 1254 square 680.9 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [1749, 1782, 1820, 2044], guide [40, 150, 1496, 544], CCW rotation True. World bounds in metres [[0.1515243649482727, 1.3490580320358276, -0.3888265788555145], [0.5785703063011169, 3.0877525806427, -0.1266700178384781]].

Closest part centroids: wing_skin_L, pylon_inner_L, pylon_inner_plug_L, ventral_fin. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from wing_root, wing_upper. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/gear_door_main_L_all.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/gear_door_main_L_all.template.png
- art/textures/generated/full/gear_door_main_L_all.neighbor_wing_root.png
- art/textures/generated/full/gear_door_main_L_all.neighbor_wing_upper.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.
