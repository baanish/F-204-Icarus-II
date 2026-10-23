# pylon_inner_plug_L_all

Left inner pylon mounting plug. Small flush attachment faces, restrained mechanical seams. World-normal chart family: in.

Generation required: True. Source: art/textures/generated/full/pylon_inner_plug_L_all.png.
Guide density 819.0 px/m; native density at 1254 square 668.6 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [1754, 342, 1770, 604], guide [40, 150, 1470, 237], CCW rotation True. World bounds in metres [[1.798208236694336, 1.3893333673477173, -0.10206655412912369], [1.8976848125457764, 3.1265318393707275, -0.056811969727277756]].
- Atlas [1759, 1507, 1775, 1770], guide [40, 322, 1475, 409], CCW rotation True. World bounds in metres [[1.8009305000305176, 1.3829004764556885, -0.06511018425226212], [1.9004496335983276, 3.1272382736206055, -0.018647585064172745]].
- Atlas [59, 1011, 67, 1277], guide [40, 494, 1492, 537], CCW rotation True. World bounds in metres [[1.8517529964447021, 1.3852194547653198, -0.10064414888620377], [1.9019999504089355, 3.1296145915985107, -0.025910547003149986]].
- Atlas [1664, 1776, 1670, 2042], guide [40, 622, 1492, 654], CCW rotation True. World bounds in metres [[1.7960000038146973, 1.3841718435287476, -0.08702565729618073], [1.8468021154403687, 3.128570795059204, -0.021060653030872345]].

Closest part centroids: pylon_inner_L, wing_skin_L, lef_L_visible, flap_L_visible. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from wing_root, wing_upper. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/pylon_inner_plug_L_all.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/pylon_inner_plug_L_all.template.png
- art/textures/generated/full/pylon_inner_plug_L_all.neighbor_wing_root.png
- art/textures/generated/full/pylon_inner_plug_L_all.neighbor_wing_upper.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.


Source stitching: {
  "method": "style anchor grain and structural guide",
  "source": "art/textures/generated/pilot2/style_anchor.png",
  "source_sha256": "22f3e60aa26457cd87340782dbe5d2ba44fa556d000867a4327a2e947c0bd44a",
  "output": "art/textures/generated/full/pylon_inner_plug_L_all.stitched.png",
  "output_sha256": "af1a2bbde0f2cfb0b069365194b615bd6de236c4b6f2bd92e74a083525d4727d",
  "native_size": [
    1254,
    1254
  ],
  "charts": [
    {
      "source": "style anchor fine grain",
      "structure": "exact blue frame/spar guide pixels",
      "chart": "pylon_inner_plug_L:lower:002",
      "target_box": [
        33,
        122,
        1200,
        193
      ]
    },
    {
      "source": "style anchor fine grain",
      "structure": "exact blue frame/spar guide pixels",
      "chart": "pylon_inner_plug_L:upper:004",
      "target_box": [
        33,
        263,
        1204,
        334
      ]
    },
    {
      "source": "style anchor fine grain",
      "structure": "exact blue frame/spar guide pixels",
      "chart": "pylon_inner_plug_L:out:003",
      "target_box": [
        33,
        403,
        1218,
        438
      ]
    },
    {
      "source": "style anchor fine grain",
      "structure": "exact blue frame/spar guide pixels",
      "chart": "pylon_inner_plug_L:in:001",
      "target_box": [
        33,
        508,
        1218,
        534
      ]
    }
  ],
  "limitation": "material reuse after generation service rejection; no independently generated part detail"
}