# wing_upper

Two upper wing charts: inboard cranked panel and outboard fixed wing box. The smaller tip panel starts beyond the planform crank. The leading-edge flap, trailing flap and aileron are separate parts, absent from these islands. Their cut edges are real hinge boundaries, not extra access covers. Follow the two spars and actual rib stations. Keep a small fuel filler within the tank box, between the spars and outboard of the crank, diameter about 0.11 m. No walkway outboard.

Generation required: False. Source: art/textures/generated/pilot2/wing_upper.png.
Guide density 363.0 px/m; native density at 1254 square 296.4 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [715, 156, 907, 375], guide [40, 150, 504, 679], CCW rotation False. World bounds in metres [[2.0540313720703125, 1.9340275526046753, -0.2675512433052063], [3.305443286895752, 3.3939578533172607, -0.01942400261759758]].
- Atlas [1385, 816, 1520, 1417], guide [40, 764, 1494, 1090], CCW rotation True. World bounds in metres [[1.054042935371399, -0.6230321526527405, -0.0350179523229599], [1.9239871501922607, 3.3782119750976562, 0.19497208297252655]].

Closest part centroids: pylon_inner_L, pylon_inner_plug_L, lef_L_visible, gear_door_main_L_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.

References in image order:
- art/textures/generated/pilot2/wing_upper.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/pilot2/wing_upper.template.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.
