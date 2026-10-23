# forward_left roughness companion

Accepted base: art/textures/generated/pilot2/forward_left.png
Native canvas: 1254 x 1254. No registration repair or per-map warping is permitted.

White means rough and black means smooth. Default maintained satin paint is about 160 grey. Existing worn edges and walkway wear are subtly smoother, about 110 grey; existing grime and soot are rougher, about 205 grey. Keep the existing seam and fastener surface-response changes at precisely their base-image positions. The physical boundary between painted surfaces and the dark surround must match. No new scuffs, soot, walkways, panel joints or markings. This is scalar linear roughness, not a glossy photograph; no lighting, highlights or shadows.

# forward_left generation context

The left forward fuselage side below the cockpit, between the radome and intake. Forward is toward the radome. The closed gun-port panel is an avionics access cover, no gun opening. Frame stations support circumferential fastener rows, not a dense rectangular greeble grid. Leave clean stencil zones under the cockpit sill; decals come later. The canopy sill is above this sheet, the intake is aft.

The aircraft's nose points world -Y, up is +Z and left outboard is +X. FWD, UP and OUT arrows in the guide are fitted independently on each chart from the actual world-position bake. Normal-to-sheet axes are labelled rather than guessed. All size values use metres.

- Chart 12: world XYZ bounds in metres [[0.1980905532836914, -6.394056797027588, -0.36091652512550354], [0.6294504404067993, -2.3685519695281982, 0.8291006088256836]]; surface area about 3.971 square metres. Guide rectangle [40, 150, 1487, 637]. Rotated CCW 90 degrees: True.

Guide density: 357.0 px/m. The actual native density is recorded in generation.json after generation. The atlas density stays about 150 px/m; source oversampling does not increase the final atlas resolution.

Structure comes from art/blender/internals.py via structure.json: fuselage frames start at s=1.6 m with 0.6 m pitch; wing spars follow chord fractions 0.175 and 0.70, with rib locations built from the same interval calculation as internals.py. Access covers come from panels.ACCESS_PANELS. The gun-port cover stays closed. Fin root cover and wing filler are explicit art decisions, not claims about modelled interior structure. The radome has no metal fastener grid.

Its forward rim meets the radome, its upper edge the cockpit sill and its aft edge the intake and mid fuselage. Radome art is available as a continuity reference. The sill and intake are not generated yet. Do not invent a joint crossing the radome break.

Reference inputs in tool order:
- art\textures\generated\pilot2\forward_left.guide.png
- art\textures\generated\pilot2\style_anchor.png
- art\textures\generated\pilot2\forward_left.template.png
- art\textures\generated\pilot2\forward_left.neighbor_radome.png

Only our own layout, material generation and current neutral render inputs are permitted. No game texture is supplied.

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.

Acceptance requires native-resolution cross-correlation displacement below one texel and reported structural feature precision and recall. A failed companion uses the base-derived fallback for that channel; failed native images remain preserved.
