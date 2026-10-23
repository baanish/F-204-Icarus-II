# radome

The dielectric radar nose, ahead of the cockpit. Four tapered charts wrap its left, underside, right and top quadrants. This is smooth composite, not a sheet-metal patchwork. Only the attachment rim at the wide aft end has a fine joint. No rivet grid across the composite. Very faint longitudinal cleaning traces, no metal scratches.

Generation required: False. Source: art/textures/generated/pilot2/radome.png.
Guide density 435.0 px/m; native density at 1254 square 355.1 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [1790, 1232, 1892, 1479], guide [40, 150, 756, 445], CCW rotation True. World bounds in metres [[-0.3506285846233368, -7.9874491691589355, -0.21902680397033691], [-0.003483430715277791, -6.394190311431885, 0.40140411257743835]].
- Atlas [1785, 609, 1886, 856], guide [40, 530, 756, 822], CCW rotation True. World bounds in metres [[0.0025913661811500788, -7.992389678955078, -0.21589866280555725], [0.35090184211730957, -6.394178867340088, 0.39967435598373413]].
- Atlas [1815, 922, 1897, 1168], guide [40, 907, 753, 1144], CCW rotation True. World bounds in metres [[-0.2453186810016632, -7.98603630065918, -0.32336515188217163], [0.24667847156524658, -6.394217491149902, 0.02638113871216774]].
- Atlas [1785, 1496, 1858, 1746], guide [40, 1229, 765, 1440], CCW rotation True. World bounds in metres [[-0.212215855717659, -7.990246295928955, 0.032510656863451004], [0.21306465566158295, -6.394188404083252, 0.5050099492073059]].

Closest part centroids: skin_forward_R, skin_forward_L, canopy_visible, gear_door_N_L_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.

References in image order:
- art/textures/generated/pilot2/radome.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/pilot2/radome.template.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.
