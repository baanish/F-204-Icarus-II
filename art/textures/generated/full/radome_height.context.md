# radome height companion

Accepted base: art/textures/generated/pilot2/radome.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means raised, mid grey 128 means flush, black means recessed. Convert the existing dark panel seams and access-cover edges into narrow recessed grooves. Existing flush rivet heads are tiny raised domes centred exactly on their visible base marks, with their existing rings recessed. Preserve hinge joints and existing stiffeners. Paint grain and colour wear are not physical dents and must stay near mid grey. No new seams, fasteners, access covers or geometry. This is a scalar height map, not a lit normal map: no directional shading, lighting or shadows.

# radome generation context

The dielectric radar nose, ahead of the cockpit. Four tapered charts wrap its left, underside, right and top quadrants. This is smooth composite, not a sheet-metal patchwork. Only the attachment rim at the wide aft end has a fine joint. No rivet grid across the composite. Very faint longitudinal cleaning traces, no metal scratches.

The aircraft's nose points world -Y, up is +Z and left outboard is +X. FWD, UP and OUT arrows in the guide are fitted independently on each chart from the actual world-position bake. Normal-to-sheet axes are labelled rather than guessed. All size values use metres.

- Chart 4: world XYZ bounds in metres [[-0.3506285846233368, -7.9874491691589355, -0.21902680397033691], [-0.003483430715277791, -6.394190311431885, 0.40140411257743835]]; surface area about 0.597 square metres. Guide rectangle [40, 150, 756, 445]. Rotated CCW 90 degrees: True.
- Chart 2: world XYZ bounds in metres [[0.0025913661811500788, -7.992389678955078, -0.21589866280555725], [0.35090184211730957, -6.394178867340088, 0.39967435598373413]]; surface area about 0.596 square metres. Guide rectangle [40, 530, 756, 822]. Rotated CCW 90 degrees: True.
- Chart 3: world XYZ bounds in metres [[-0.2453186810016632, -7.98603630065918, -0.32336515188217163], [0.24667847156524658, -6.394217491149902, 0.02638113871216774]]; surface area about 0.535 square metres. Guide rectangle [40, 907, 753, 1144]. Rotated CCW 90 degrees: True.
- Chart 6: world XYZ bounds in metres [[-0.212215855717659, -7.990246295928955, 0.032510656863451004], [0.21306465566158295, -6.394188404083252, 0.5050099492073059]]; surface area about 0.487 square metres. Guide rectangle [40, 1229, 765, 1440]. Rotated CCW 90 degrees: True.

Guide density: 435.0 px/m. The actual native density is recorded in generation.json after generation. The atlas density stays about 150 px/m; source oversampling does not increase the final atlas resolution.

Structure comes from art/blender/internals.py via structure.json: fuselage frames start at s=1.6 m with 0.6 m pitch; wing spars follow chord fractions 0.175 and 0.70, with rib locations built from the same interval calculation as internals.py. Access covers come from panels.ACCESS_PANELS. The gun-port cover stays closed. Fin root cover and wing filler are explicit art decisions, not claims about modelled interior structure. The radome has no metal fastener grid.

The aft wide rims meet the forward fuselage at the radome break. This first part has no generated neighbours. Keep these rims uniform.

Reference inputs in tool order:
- art\textures\generated\pilot2\radome.guide.png
- art\textures\generated\pilot2\style_anchor.png
- art\textures\generated\pilot2\radome.template.png

Only our own layout, material generation and current neutral render inputs are permitted. No game texture is supplied.

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
