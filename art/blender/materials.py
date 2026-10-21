"""Material slots of the generator. Unity remaps each slot to a material by its name on import
(IcarusAuthor.Materials.cs SlotMaterialMap), so a slot's name is its contract; the colours here only tint the Blender
views and the review renders.

The flat Icarus_* slots are the blockout's own. The stock slots carry the names of the game materials Blueprinter
patches in, each mapped to Assets/Blueprinter/_donotship/Material/<name>_PLACEHOLDER.mat; packages move geometry onto
them. Icarus_Body stays the skin, the only slot that takes a livery.
"""
import bpy

STOCK = ("jet_mechanical", "aircraft_structure", "Matte_black", "Mirror", "Aircraft_wheels", "Fighter1_gear",
         "fighter1_canopy", "fighter1_canopy_int", "tacScreenDisplay", "CockpitWarningLight", "hotas", "Seats", "LOD",
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
        "glass": material("Icarus_Glass", (0.10, 0.16, 0.22, 0.6), 0.0, 0.05),
        "duct": material("Icarus_Duct", (0.02, 0.02, 0.02, 1.0), 0.0, 0.8),
        "metal": material("Icarus_Nozzle", (0.25, 0.22, 0.20, 1.0), 0.9, 0.35),
        "frame": material("Icarus_Frame", (0.20, 0.21, 0.22, 1.0), 0.6, 0.5),
        "petal": material("Icarus_Petal", (0.46, 0.44, 0.42, 1.0), 0.85, 0.3),
        "seal": material("Icarus_Seal", (0.27, 0.26, 0.25, 1.0), 0.85, 0.4),
        "strut": material("Icarus_Strut", (0.70, 0.71, 0.72, 1.0), 1.0, 0.25),
        "tyre": material("Icarus_Tyre", (0.03, 0.03, 0.03, 1.0), 0.0, 0.9),
        # the internals keep flat review colours, so a part torn away reads as tank, engine or structure
        "fuel_tank": material("Icarus_Int_Fuel", (0.85, 0.55, 0.12, 1.0), 0.0, 0.6),
        "engine": material("Icarus_Int_Engine", (0.30, 0.28, 0.26, 1.0), 0.9, 0.4),
        "structure": material("Icarus_Int_Structure", (0.70, 0.72, 0.74, 1.0), 0.6, 0.5),
        "avionics": material("Icarus_Int_Avionics", (0.20, 0.45, 0.30, 1.0), 0.1, 0.6),
        "radar": material("Icarus_Int_Avionics", (0.20, 0.45, 0.30, 1.0), 0.1, 0.6),
        "cockpit": material("Icarus_Int_Cockpit", (0.32, 0.33, 0.35, 1.0), 0.2, 0.6),
        "gear_bay": material("Icarus_Int_Bay", (0.10, 0.10, 0.11, 1.0), 0.0, 0.8),
    }
