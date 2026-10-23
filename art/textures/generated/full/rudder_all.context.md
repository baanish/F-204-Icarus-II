# rudder_all

Separate vertical tail control. Leading hinge meets the fin trailing cut. Fine hinge seam, sparse flush fasteners. World-normal chart family: in.

Generation required: True. Source: art/textures/generated/full/rudder_all.png.
Guide density 729.0 px/m; native density at 1254 square 595.2 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [1440, 128, 1584, 339], guide [40, 150, 739, 1175], CCW rotation False. World bounds in metres [[-0.06548140197992325, 6.695656776428223, 1.1560066938400269], [-0.0015023858286440372, 7.668936729431152, 2.5439882278442383]].
- Atlas [897, 117, 1040, 328], guide [799, 150, 1493, 1175], CCW rotation False. World bounds in metres [[0.0015018736012279987, 6.700404644012451, 1.156069278717041], [0.06527772545814514, 7.667026042938232, 2.5439488887786865]].

Closest part centroids: fin_skin, stabilator_visible, nozzle, skin_aft_R. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from fin_left, stabilator_upper. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/rudder_all.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/rudder_all.template.png
- art/textures/generated/full/rudder_all.neighbor_fin_left.png
- art/textures/generated/full/rudder_all.neighbor_stabilator_upper.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.
