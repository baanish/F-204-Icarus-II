# wing_root

The upper inboard wing root and strake, joining the left fuselage fillet to the main upper wing. A narrow curved sheet, not an entire triangular wing. The yellow guide zone indicates a restrained antislip walkway near the fuselage. It is a subtle grey material change with soft shoe scuffs, no black racing stripe or text. Blue structural lines follow the actual spars and ribs. Outboard it meets the upper wing.

Generation required: False. Source: art/textures/generated/pilot2/wing_root.png.
Guide density 288.0 px/m; native density at 1254 square 235.1 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [341, 1334, 1098, 1415], guide [40, 150, 1493, 305], CCW rotation False. World bounds in metres [[0.5800099968910217, -0.9916287064552307, 0.11845197528600693], [1.053999662399292, 4.049741268157959, 0.2684621512889862]].

Closest part centroids: pylon_inner_L, pylon_inner_plug_L, lef_L_visible, gear_door_main_L_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.

References in image order:
- art/textures/generated/pilot2/wing_root.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/pilot2/wing_root.template.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.
