"""Measure the clear window of the stock canopy texture the Icarus glass samples (fighter1_canopy_int_b): per v row,
the u span whose alpha is under the threshold, the field inside the opaque tan border. art/blender/canopy.py's CLEAR_UV
is a box inside it.

    python tools/canopy_clear_window.py <path to fighter1_canopy_int_b PNG> [alpha threshold, default 0.15]
"""
import sys

import numpy as np
from PIL import Image

alpha = np.asarray(Image.open(sys.argv[1]).convert("RGBA"))[..., 3].astype(float) / 255
threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 0.15
h, w = alpha.shape
for v in np.arange(0.20, 0.96, 0.05):
    clear = np.nonzero(alpha[int(round((1 - v) * (h - 1)))] < threshold)[0]  # image rows run down, v up
    print("v %.2f: %s" % (v, "u %.3f to %.3f" % (clear.min() / (w - 1), clear.max() / (w - 1)) if len(clear) else "none"))
