"""Material slots of the generator. Unity remaps each slot to a material by its name on import
(IcarusAuthor.Materials.cs SlotMaterialMap), so a slot's name is its contract; the colours here only tint the Blender
views and the review renders.

The flat Icarus_* slots are the blockout's own. The stock slots carry the names of the game materials Blueprinter
patches in, each mapped to Assets/Blueprinter/_donotship/Material/<name>_PLACEHOLDER.mat; packages move geometry onto
them. Icarus_Body packs the skin atlas. Icarus_NavFairing projects the wing's existing UVs and uses the same livery.
"""
import bpy

STOCK = ("jet_mechanical", "aircraft_structure", "Matte_black", "Mirror", "Aircraft_wheels", "Fighter1_gear",
         "fighter1_canopy", "fighter1_canopy_int", "tacScreenDisplay", "CockpitWarningLight", "hotas", "Seats",
         "light_red_off", "light_green_off", "slimelight_on")


def material(name, rgba, metallic=0.0, roughness=0.5):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = rgba
    mat.metallic = metallic
    mat.roughness = roughness
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        if rgba[3] < 1:
            bsdf.inputs["Alpha"].default_value = rgba[3]
    return mat


def stock(name):
    """A stock slot: the bare material, whose name is all Unity reads."""
    if name not in STOCK:
        raise ValueError("%s is not a stock slot" % name)
    return bpy.data.materials.get(name) or bpy.data.materials.new(name)


def build():
    """Every slot, by the role the generator gives it."""
    for name in STOCK:
        stock(name)
    return {
        "body": material("Icarus_Body", (0.56, 0.57, 0.59, 1.0), 1.0, 0.32),  # bare steel for the blockout
        "nav_fairing": material("Icarus_NavFairing", (0.56, 0.57, 0.59, 1.0), 1.0, 0.32),
        "glass": material("Icarus_Glass", (0.10, 0.16, 0.22, 0.6), 0.0, 0.05),
        "duct": material("Icarus_Duct", (0.02, 0.02, 0.02, 1.0), 0.0, 0.8),
        # The speed brake wells' ribs, rivets, lines and anchor bracket: a step lighter than the dark walls they stand
        # on, so they read in the well's shadow.
        "well_detail": material("Icarus_WellDetail", (0.035, 0.036, 0.04, 1.0), 0.5, 0.65),
        "metal": material("Icarus_Nozzle", (0.25, 0.22, 0.20, 1.0), 0.9, 0.35),
        # The fuselage frames and break walls: dark, as stock shows structure at a break (the Vagrant's closed,
        # self-shadowed jet_mechanical and Matte_black), since open frames lit by the sky read white on a light trim.
        # Not Icarus_Duct: parts.open_bays finds the gear bays' faces by that slot.
        "frame": material("Icarus_Frame", (0.032, 0.034, 0.038, 1.0), 0.6, 0.5),
        "petal": material("Icarus_Petal", (0.46, 0.44, 0.42, 1.0), 0.85, 0.3),
        "seal": material("Icarus_Seal", (0.27, 0.26, 0.25, 1.0), 0.85, 0.4),
        "strut": material("Icarus_Strut", (0.70, 0.71, 0.72, 1.0), 1.0, 0.25),
        "tyre": material("Icarus_Tyre", (0.03, 0.03, 0.03, 1.0), 0.0, 0.9),
        # Hidden structure on the stock trims (Exterior rule 4): spars and ribs on aircraft_structure;
        # equipment, bays and the coves of moving surfaces on jet_mechanical.
        "structure": stock("aircraft_structure"),
        "mechanical": stock("jet_mechanical"),
        # Rubberised fuel bladders stay matte and nonmetallic beside the stock mechanical trim.
        "fuel_tank": material("Icarus_FuelCell", (0.10, 0.075, 0.035, 1.0), 0.0, 0.85),
        "engine": stock("jet_mechanical"),
        "avionics": stock("jet_mechanical"),
        "radar": stock("jet_mechanical"),
        "cockpit": stock("jet_mechanical"),
        # The gear wells' walls and roofs: the opaque dark of the duct backplates. A jet_mechanical face more than
        # about 0.38 m across its trim strip reaches the stock texture's alpha-clipped lightening holes
        # (trims.clipped), and a bay wall that wide showed the sky through the open doors.
        "gear_bay": material("Icarus_Duct", (0.02, 0.02, 0.02, 1.0), 0.0, 0.8),
    }
