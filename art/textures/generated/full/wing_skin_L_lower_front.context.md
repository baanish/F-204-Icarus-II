# wing_skin_L_lower_front

Fixed lower wing skin. Follow actual spars and ribs. Moving leading edge, flap and aileron meet the control boundaries. No upper walkway on the underside. World-normal chart family: lower.

Generation required: True. Source: art/textures/generated/full/wing_skin_L_lower_front.png.
Guide density 288.0 px/m; native density at 1254 square 235.1 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [6, 700, 609, 832], guide [40, 150, 1197, 403], CCW rotation False. World bounds in metres [[1.0540016889572144, -0.6307672262191772, -0.07896699011325836], [1.9231762886047363, 3.3797378540039062, 0.1141381561756134]].
- Atlas [342, 1421, 1099, 1501], guide [40, 488, 1493, 641], CCW rotation False. World bounds in metres [[0.5800111889839172, -0.9886694550514221, 0.037392739206552505], [1.0539993047714233, 4.0458526611328125, 0.19819171726703644]].
- Atlas [341, 1511, 945, 1532], guide [40, 726, 1199, 766], CCW rotation False. World bounds in metres [[0.5799999237060547, -0.016103483736515045, 0.13156208395957947], [0.5854750871658325, 4.003371715545654, 0.2679133415222168]].
- Atlas [1862, 1557, 1881, 1787], guide [40, 851, 481, 887], CCW rotation True. World bounds in metres [[1.926080584526062, 1.8609455823898315, -0.03547348454594612], [2.04599928855896, 3.3872716426849365, 0.004616063553839922]].

Closest part centroids: pylon_inner_L, pylon_inner_plug_L, lef_L_visible, gear_door_main_L_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from wing_root, wing_upper. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/wing_skin_L_lower_front.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/wing_skin_L_lower_front.template.png
- art/textures/generated/full/wing_skin_L_lower_front.neighbor_wing_root.png
- art/textures/generated/full/wing_skin_L_lower_front.neighbor_wing_upper.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.
