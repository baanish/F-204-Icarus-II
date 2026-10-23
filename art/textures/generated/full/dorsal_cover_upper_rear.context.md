# dorsal_cover_upper_rear

Dorsal fuselage cover behind the canopy. Follow frame stations. Keep antenna mounting zones quiet; no antenna artwork is baked into the skin. World-normal chart family: upper.

Generation required: True. Source: art/textures/generated/full/dorsal_cover_upper_rear.png.
Guide density 408.0 px/m; native density at 1254 square 333.1 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [573, 1927, 1105, 2043], guide [40, 150, 1487, 465], CCW rotation False. World bounds in metres [[-0.31083497405052185, 0.8237488269805908, 0.8077383041381836], [0.31337133049964905, 4.352957248687744, 1.0396102666854858]].

Closest part centroids: skin_mid_R, skin_mid_L, intake_duct_L, gear_door_main_L_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from skin_mid_L_lower, skin_mid_L_out. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/dorsal_cover_upper_rear.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/dorsal_cover_upper_rear.template.png
- art/textures/generated/full/dorsal_cover_upper_rear.neighbor_skin_mid_L_lower.png
- art/textures/generated/full/dorsal_cover_upper_rear.neighbor_skin_mid_L_out.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.
