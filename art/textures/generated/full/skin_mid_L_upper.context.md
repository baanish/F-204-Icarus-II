# skin_mid_L_upper

Mid fuselage between intake and aft engine bay. Follow circumferential frame stations. Closed auxiliary door follows the orange guide. World-normal chart family: upper.

Generation required: True. Source: art/textures/generated/full/skin_mid_L_upper.png.
Guide density 354.0 px/m; native density at 1254 square 289.0 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [6, 844, 621, 957], guide [40, 150, 1491, 416], CCW rotation False. World bounds in metres [[0.2827664613723755, -1.149986982345581, 0.43355751037597656], [0.9035186767578125, 2.929481267929077, 0.8658215999603271]].

Closest part centroids: intake_duct_L, dorsal_cover, skin_mid_R, wing_skin_L. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from wing_root, wing_upper. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/skin_mid_L_upper.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/skin_mid_L_upper.template.png
- art/textures/generated/full/skin_mid_L_upper.neighbor_wing_root.png
- art/textures/generated/full/skin_mid_L_upper.neighbor_wing_upper.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.
