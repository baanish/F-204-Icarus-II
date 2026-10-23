# wing_root height companion

Accepted base: art/textures/generated/pilot2/wing_root.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means raised, mid grey 128 means flush, black means recessed. Convert the existing dark panel seams and access-cover edges into narrow recessed grooves. Existing flush rivet heads are tiny raised domes centred exactly on their visible base marks, with their existing rings recessed. Preserve hinge joints and existing stiffeners. Paint grain and colour wear are not physical dents and must stay near mid grey. No new seams, fasteners, access covers or geometry. This is a scalar height map, not a lit normal map: no directional shading, lighting or shadows.

# wing_root generation context

The upper inboard wing root and strake, joining the left fuselage fillet to the main upper wing. A narrow curved sheet, not an entire triangular wing. The yellow guide zone indicates a restrained antislip walkway near the fuselage. It is a subtle grey material change with soft shoe scuffs, no black racing stripe or text. Blue structural lines follow the actual spars and ribs. Outboard it meets the upper wing.

The aircraft's nose points world -Y, up is +Z and left outboard is +X. FWD, UP and OUT arrows in the guide are fitted independently on each chart from the actual world-position bake. Normal-to-sheet axes are labelled rather than guessed. All size values use metres.

- Chart 13: world XYZ bounds in metres [[0.5800099968910217, -0.9916287064552307, 0.11845197528600693], [1.053999662399292, 4.049741268157959, 0.2684621512889862]]; surface area about 2.229 square metres. Guide rectangle [40, 150, 1493, 305]. Rotated CCW 90 degrees: False.

Guide density: 288.0 px/m. The actual native density is recorded in generation.json after generation. The atlas density stays about 150 px/m; source oversampling does not increase the final atlas resolution.

Structure comes from art/blender/internals.py via structure.json: fuselage frames start at s=1.6 m with 0.6 m pitch; wing spars follow chord fractions 0.175 and 0.70, with rib locations built from the same interval calculation as internals.py. Access covers come from panels.ACCESS_PANELS. The gun-port cover stays closed. Fin root cover and wing filler are explicit art decisions, not claims about modelled interior structure. The radome has no metal fastener grid.

Inboard meets the skin_mid_L fillet, which stays round-1 during the pilot. Outboard meets wing_upper, generated next. Leave edge strips uniform neutral paint so seams can be joined. The forward fuselage is separated by the intake and is a style reference only.

Reference inputs in tool order:
- art\textures\generated\pilot2\wing_root.guide.png
- art\textures\generated\pilot2\style_anchor.png
- art\textures\generated\pilot2\wing_root.template.png
- art\textures\generated\pilot2\wing_root.neighbor_forward_left.png

Only our own layout, material generation and current neutral render inputs are permitted. No game texture is supplied.

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
