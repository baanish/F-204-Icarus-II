"""Compose the P3 inlet reference comparison and dimensioned model sections from its render and measurements."""
import argparse
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=REPO / ".cache/review/wave2/P3/01")
    parser.add_argument("--reference", type=Path, required=True, help="the Lockheed F-104 power plant page to compare against")
    args = parser.parse_args()
    section = json.loads((args.out / "section.json").read_text())
    fig, axes = plt.subplots(1, 2, figsize=(14, 7), layout="constrained")
    ax = axes[0]
    edge = section["lip_edge_x_z"]
    ax.plot([p[0] for p in edge], [p[1] for p in edge], color="#718a9f", lw=5, label="Outer lip / skin")
    theta = [2 * math.pi * i / 128 for i in range(129)]
    cx, cz, radius = section["duct"]
    ax.plot([cx + radius * math.cos(a) for a in theta], [cz + radius * math.sin(a) for a in theta],
            color="#333d47", lw=1.5, ls="--", label="32-sided duct envelope")
    cone = section["cone_radius_at_lip"]
    ax.plot([section["cone_x"] + cone * math.cos(a) for a in theta], [cz + cone * math.sin(a) for a in theta],
            color="#767b80", lw=2, label="Shock cone")
    ax.set(xlabel="Lateral x, m", ylabel="Height z, m", title="Mouth section at s 6.85 m", xlim=(0.1, 1.03), ylim=(-0.22, 0.70))
    ax.set_aspect("equal")
    ax.legend(loc="lower left", fontsize=8)
    ax = axes[1]
    profiles = section["cone_profile"]
    ax.plot([v[0] for v in profiles], [v[1] for v in profiles], color="#718a9f", lw=4)
    ax.axvline(6.85, color="#767b80", ls="--", label="Outer lip")
    ax.annotate("30 mm undercut\n35 mm axial bleed band", xy=(7.238, 0.22), xytext=(6.55, 0.36),
                arrowprops={"arrowstyle": "->"})
    ax.set(xlabel="Station s, m", ylabel="Radius from cone axis, m", title="Cone section through its undercut", xlim=(6.1, 7.5), ylim=(0, 0.42))
    ax.set_aspect("equal")
    ax.legend(loc="lower right", fontsize=8)
    for ax in axes:
        ax.grid(alpha=0.18)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Icarus inlet: model dimensions for owner review, not dimensioned F-104 data", fontsize=13)
    fig.savefig(args.out / "inlet_section.png", dpi=160, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 26)
    small = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 20)
    sheet = Image.new("RGB", (2200, 2060), "#f1f2f3")
    draw = ImageDraw.Draw(sheet)
    draw.text((30, 15), "Icarus P3 inlet and Lockheed reference", fill="#20272e", font=font)
    render = Image.open(args.out / "inboard_mouth.png").convert("RGBA")
    background = Image.new("RGBA", render.size, "#e0e3e6")
    background.alpha_composite(render)
    background.thumbnail((1150, 800))
    sheet.paste(background.convert("RGB"), (25, 75))
    reference = Image.open(args.reference).convert("RGB")
    reference = reference.crop((140, 595, 590, 920))
    reference.thumbnail((980, 800))
    reference = reference.resize((970, 700))
    sheet.paste(reference, (1190, 75))
    draw.text((1190, 790), "Lockheed F-104 power plant, page 6", fill="#20272e", font=small)
    draw.text((30, 895), "Model: 30 mm cone undercut; no splitter plate or stand-off (owner).", fill="#20272e", font=small)
    section_image = Image.open(args.out / "inlet_section.png").convert("RGB")
    section_image.thumbnail((2140, 1070))
    sheet.paste(section_image, ((2200 - section_image.width) // 2, 950))
    sheet.save(args.out / "inboard_mouth_reference_section.png")


if __name__ == "__main__":
    main()
