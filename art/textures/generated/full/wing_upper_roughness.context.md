# wing_upper roughness companion

Accepted base: art/textures/generated/pilot2/wing_upper.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means rough and black means smooth. Default maintained satin paint is about 160 grey. Existing worn edges and walkway wear are subtly smoother, about 110 grey; existing grime and soot are rougher, about 205 grey. Keep the existing seam and fastener surface-response changes at precisely their base-image positions. The physical boundary between painted surfaces and the dark surround must match. No new scuffs, soot, walkways, panel joints or markings. This is scalar linear roughness, not a glossy photograph; no lighting, highlights or shadows.

# wing_upper generation context

Two upper wing charts: inboard cranked panel and outboard fixed wing box. The smaller tip panel starts beyond the planform crank. The leading-edge flap, trailing flap and aileron are separate parts, absent from these islands. Their cut edges are real hinge boundaries, not extra access covers. Follow the two spars and actual rib stations. Keep a small fuel filler within the tank box, between the spars and outboard of the crank, diameter about 0.11 m. No walkway outboard.

The aircraft's nose points world -Y, up is +Z and left outboard is +X. FWD, UP and OUT arrows in the guide are fitted independently on each chart from the actual world-position bake. Normal-to-sheet axes are labelled rather than guessed. All size values use metres.

- Chart 2: world XYZ bounds in metres [[2.0540313720703125, 1.9340275526046753, -0.2675512433052063], [3.305443286895752, 3.3939578533172607, -0.01942400261759758]]; surface area about 1.370 square metres. Guide rectangle [40, 150, 504, 679]. Rotated CCW 90 degrees: False.
- Chart 7: world XYZ bounds in metres [[1.054042935371399, -0.6230321526527405, -0.0350179523229599], [1.9239871501922607, 3.3782119750976562, 0.19497208297252655]]; surface area about 2.436 square metres. Guide rectangle [40, 764, 1494, 1090]. Rotated CCW 90 degrees: True.

Guide density: 363.0 px/m. The actual native density is recorded in generation.json after generation. The atlas density stays about 150 px/m; source oversampling does not increase the final atlas resolution.

Structure comes from art/blender/internals.py via structure.json: fuselage frames start at s=1.6 m with 0.6 m pitch; wing spars follow chord fractions 0.175 and 0.70, with rib locations built from the same interval calculation as internals.py. Access covers come from panels.ACCESS_PANELS. The gun-port cover stays closed. Fin root cover and wing filler are explicit art decisions, not claims about modelled interior structure. The radome has no metal fastener grid.

The inboard fixed sheet meets the already generated wing_root. The small outboard fixed box meets the inboard cranked sheet at the crank. LEF, flap and aileron edges meet separate moving parts that retain round-1 art during the pilot. Continue spar rows to corresponding positions, with no dark border around each UV chart.

Reference inputs in tool order:
- art\textures\generated\pilot2\wing_upper.guide.png
- art\textures\generated\pilot2\style_anchor.png
- art\textures\generated\pilot2\wing_upper.template.png
- art\textures\generated\pilot2\wing_upper.neighbor_wing_root.png

Only our own layout, material generation and current neutral render inputs are permitted. No game texture is supplied.

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
