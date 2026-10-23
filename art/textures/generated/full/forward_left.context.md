# forward_left

The left forward fuselage side below the cockpit, between the radome and intake. Forward is toward the radome. The closed gun-port panel is an avionics access cover, no gun opening. Frame stations support circumferential fastener rows, not a dense rectangular greeble grid. Leave clean stencil zones under the cockpit sill; decals come later. The canopy sill is above this sheet, the intake is aft.

Generation required: False. Source: art/textures/generated/pilot2/forward_left.png.
Guide density 357.0 px/m; native density at 1254 square 291.5 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [1182, 952, 1387, 1560], guide [40, 150, 1487, 637], CCW rotation True. World bounds in metres [[0.1980905532836914, -6.394056797027588, -0.36091652512550354], [0.6294504404067993, -2.3685519695281982, 0.8291006088256836]].

Closest part centroids: skin_forward_R, canopy_visible, gear_door_N_L_visible, radome. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.

References in image order:
- art/textures/generated/pilot2/forward_left.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/pilot2/forward_left.template.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.
