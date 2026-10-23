# fin_left height companion

Accepted base: art/textures/generated/pilot2/fin_left.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means raised, mid grey 128 means flush, black means recessed. Convert the existing dark panel seams and access-cover edges into narrow recessed grooves. Existing flush rivet heads are tiny raised domes centred exactly on their visible base marks, with their existing rings recessed. Preserve hinge joints and existing stiffeners. Paint grain and colour wear are not physical dents and must stay near mid grey. No new seams, fasteners, access covers or geometry. This is a scalar height map, not a lit normal map: no directional shading, lighting or shadows.

# fin_left generation context

Left face of the vertical fin, its lower root fillet and small top cap, above the rear fuselage. The rudder is a separate trailing control surface and is absent. Use a fine perimeter joint near that cut boundary, a few flush fasteners near the base and one restrained root service cover. No invented fin spar grid: the current model has no separate fin spar layout exported here. Keep broad skin clean. Generated detail is reflected in aircraft world coordinates to the other face; the compositor adds readable separate fin markings.

The aircraft's nose points world -Y, up is +Z and left outboard is +X. FWD, UP and OUT arrows in the guide are fitted independently on each chart from the actual world-position bake. Normal-to-sheet axes are labelled rather than guessed. All size values use metres.

- Chart 11: world XYZ bounds in metres [[0.001500000013038516, 4.550123691558838, 1.1240134239196777], [0.07760649919509888, 7.2397141456604, 2.5722436904907227]]; surface area about 2.079 square metres. Guide rectangle [40, 150, 519, 1041]. Rotated CCW 90 degrees: False.
- Chart 12: world XYZ bounds in metres [[0.001500479644164443, 4.379094123840332, 0.760940670967102], [0.08445534110069275, 7.646763801574707, 1.1230766773223877]]; surface area about 0.659 square metres. Guide rectangle [40, 1126, 1122, 1247]. Rotated CCW 90 degrees: True.
- Chart 1: world XYZ bounds in metres [[0.001500000013038516, 6.358088493347168, 2.5791807174682617], [0.032719649374485016, 7.676762104034424, 2.8799948692321777]]; surface area about 0.354 square metres. Guide rectangle [40, 1332, 477, 1433]. Rotated CCW 90 degrees: True.

Guide density: 330.0 px/m. The actual native density is recorded in generation.json after generation. The atlas density stays about 150 px/m; source oversampling does not increase the final atlas resolution.

Structure comes from art/blender/internals.py via structure.json: fuselage frames start at s=1.6 m with 0.6 m pitch; wing spars follow chord fractions 0.175 and 0.70, with rib locations built from the same interval calculation as internals.py. Access covers come from panels.ACCESS_PANELS. The gun-port cover stays closed. Fin root cover and wing filler are explicit art decisions, not claims about modelled interior structure. The radome has no metal fastener grid.

The lower fillet meets the aft fuselage. The trailing cut meets the rudder, and the top meets the stabilator. These neighbours remain round-1 for the pilot. No generated adjacent part exists. Earlier parts are material-scale references only.

Reference inputs in tool order:
- art\textures\generated\pilot2\fin_left.guide.png
- art\textures\generated\pilot2\style_anchor.png
- art\textures\generated\pilot2\fin_left.template.png
- art\textures\generated\pilot2\fin_left.neighbor_wing_upper.png

Only our own layout, material generation and current neutral render inputs are permitted. No game texture is supplied.

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
