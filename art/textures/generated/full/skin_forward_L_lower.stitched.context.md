# skin_forward_L_lower

Forward fuselage around the cockpit. The gun-port access panel stays closed. Radome ahead, intake aft, canopy sill above. World-normal chart family: lower.

Generation required: True. Source: art/textures/generated/full/skin_forward_L_lower.png.
Guide density 360.0 px/m; native density at 1254 square 293.9 px/m.
FWD = world -Y; UP = +Z; left OUT = +X. Each chart fits directions from the bake.

- Atlas [76, 611, 682, 692], guide [40, 150, 1494, 344], CCW rotation False. World bounds in metres [[8.76422127475962e-05, -6.391754627227783, -0.5099917054176331], [0.45497575402259827, -2.368617534637451, -0.22320687770843506]].
- Atlas [1865, 256, 1906, 360], guide [40, 429, 289, 527], CCW rotation True. World bounds in metres [[0.00015430711209774017, -6.3940205574035645, 0.4258144497871399], [0.24167190492153168, -5.718008518218994, 0.632162868976593]].
- Atlas [120, 1768, 449, 1805], guide [349, 429, 1138, 517], CCW rotation False. World bounds in metres [[0.2530946135520935, -5.049808979034424, 0.4524346888065338], [0.4558016061782837, -2.9040350914001465, 0.8837674260139465]].
- Atlas [1380, 672, 1415, 1001], guide [40, 612, 829, 696], CCW rotation True. World bounds in metres [[0.2589578926563263, -5.0494184494018555, 0.4480099678039551], [0.44696080684661865, -2.904005527496338, 0.8725757598876953]].
- Atlas [42, 966, 372, 986], guide [40, 781, 832, 829], CCW rotation False. World bounds in metres [[0.25180789828300476, -5.049928188323975, 0.4899826943874359], [0.4094400107860565, -2.904318332672119, 0.8826162815093994]].
- Atlas [1414, 686, 1431, 1015], guide [40, 914, 829, 954], CCW rotation True. World bounds in metres [[0.25777989625930786, -5.04977560043335, 0.4893096089363098], [0.4154359698295593, -2.9041802883148193, 0.8676980137825012]].
- Atlas [1730, 1671, 1737, 1998], guide [40, 1039, 824, 1055], CCW rotation True. World bounds in metres [[0.3468100130558014, -5.045363903045654, 0.4466531276702881], [0.4563848376274109, -2.9091598987579346, 0.7570725083351135]].
- Atlas [311, 203, 316, 291], guide [884, 1039, 1095, 1051], CCW rotation True. World bounds in metres [[0.3057083785533905, -5.637394428253174, 0.46928054094314575], [0.37295374274253845, -5.060408115386963, 0.516890823841095]].

Closest part centroids: skin_forward_R, canopy_visible, gear_door_N_L_visible, radome. This proximity list is measured context, not proof of a shared boundary.
Structural references: existing structure.json, panels.ACCESS_PANELS. Wing filler and walkway are placement decisions. There is no exported fin spar layout.
Coverage rules and unmatched geometric surfaces are recorded in .cache/review/wave2/p9b-round2/full/coverage.json.
The five accepted pilot images, masks, chart layouts and guides are reused unchanged. New prompts use the same shared style block.
Additional images are native painted edge samples from radome, forward_left. Use these for paint-grain and joint treatment. Structural lines continue through the same physical frame/spar positions in the guide; the flattened strips are not UV coordinates.

References in image order:
- art/textures/generated/full/skin_forward_L_lower.guide.png
- art/textures/generated/pilot2/style_anchor.png
- art/textures/generated/full/skin_forward_L_lower.template.png
- art/textures/generated/full/skin_forward_L_lower.neighbor_radome.png
- art/textures/generated/full/skin_forward_L_lower.neighbor_forward_left.png

Shared style block:
Clean modernised F-104 interceptor in Primeva PALA service. Maintained aircraft, believable restrained service wear, crisp flush construction. Flat diffuse albedo only, neutral medium grey paint, no directional lighting, no highlights, shadows, ambient occlusion, perspective, bevel shading or painted dents. Fine satin paint grain and tiny handling scuffs. Recessed joints are narrow charcoal lines, not black trenches. Fasteners are small and sparse, flush heads in orderly structural rows. No random greebles, decorative panels, post-apocalyptic wear, rust, exposed machinery, text, markings, insignia or camouflage. The compositor adds scheme colours and decals later. Keep broad colour constant; detail belongs at its true physical scale.


Source stitching: {
  "method": "per-chart generated paint fit to exact template",
  "source": "art/textures/generated/full/skin_forward_L_lower.png",
  "source_sha256": "3d777b21607cfe0e509e221872e861c5513f3b85b1f868d1cc6980600ac1f03e",
  "output": "art/textures/generated/full/skin_forward_L_lower.stitched.png",
  "output_sha256": "1b8e4f0cd10ab33e149cb292c2b9fb65a5558a2248ae3046d99878fedb549606",
  "native_size": [
    1254,
    1254
  ],
  "charts": [
    {
      "source_box": [
        34,
        120,
        1221,
        279
      ],
      "chart": "skin_forward_L:lower:021",
      "target_box": [
        33,
        122,
        1220,
        281
      ]
    },
    {
      "source_box": [
        34,
        351,
        234,
        430
      ],
      "chart": "skin_forward_L:upper:066",
      "target_box": [
        33,
        350,
        236,
        430
      ]
    },
    {
      "source_box": [
        285,
        349,
        930,
        422
      ],
      "chart": "skin_forward_L:out:064",
      "target_box": [
        285,
        350,
        929,
        422
      ]
    },
    {
      "source_box": [
        33,
        495,
        677,
        568
      ],
      "chart": "skin_forward_L:lower:048",
      "target_box": [
        33,
        500,
        677,
        568
      ]
    },
    {
      "source_box": [
        32,
        635,
        678,
        676
      ],
      "chart": "skin_forward_L:in:017",
      "target_box": [
        33,
        638,
        679,
        677
      ]
    },
    {
      "source_box": [
        31,
        743,
        677,
        778
      ],
      "chart": "skin_forward_L:lower:041",
      "target_box": [
        33,
        746,
        677,
        779
      ]
    },
    {
      "source_box": [
        30,
        842,
        677,
        862
      ],
      "chart": "skin_forward_L:lower:058",
      "target_box": [
        33,
        848,
        673,
        861
      ]
    },
    {
      "source_box": [
        717,
        838,
        891,
        856
      ],
      "chart": "skin_forward_L:out:063",
      "target_box": [
        722,
        848,
        894,
        858
      ]
    }
  ],
  "limitation": "base-only chart fitting before companion generation; raw generated original remains unchanged"
}