"""Triangle budget report for a built aircraft: triangles per material, per component and per part, the renderer
count, the static material list, and the sums of every module's BUDGET against the global limits.

Each module in build_icarus.MODULES carries BUDGET = {component: {"target", "cap", "objects" or "collection",
"exact", "family", "cockpit"}}: "objects" are object-name prefixes the component counts, "exact" whole object
names, "family" skin families (parts.families: the family in a build that keeps it whole, its pieces in one that
splits it, and a part a piece was joined into), "collection" counts a whole collection (LOD1, Colliders), and
"cockpit" puts it in the cockpit sum instead of the exterior one. Targets steer and caps are ceilings; a module enforces
its own caps in its check() (over_caps). This report enforces nothing.

    print(report(bpy.data.collections["Icarus"]))   # build_icarus._build prints it after every build
"""
import bpy

import build_icarus as bi

# Global limits: (target, hard limit), triangles drawn. The Unity author draws every skin triangle from both sides
# (IcarusAuthor.SkinFirst gives each a back-facing twin, as stock jets have), so these count the skin twice; module BUDGETs
# count the triangles modelled here, once.
EXTERIOR = (135000, 140000)  # exterior LOD0, internals and cockpit proxies included, cockpit_view renderers excluded
SKIN_MAX = 90000
TRIM_SHARE = (0.27, 0.58)  # jet_mechanical and aircraft_structure, of exterior LOD0
TRIMS = ("jet_mechanical", "aircraft_structure")
COCKPIT_MAX = 35000
LOD1_PER_HULL, LOD1_TOTAL = 56, 814  # hulls.LOD1_TOTAL


def tris(obj):
    return sum(len(f.vertices) - 2 for f in obj.data.polygons)


def skin_tris(obj):
    names = [m.name if m else "" for m in obj.data.materials]
    return sum(len(f.vertices) - 2 for f in obj.data.polygons if names and names[f.material_index] == "Icarus_Body")


def meshes(icarus):
    return [o for o in icarus.all_objects if o.type == "MESH"]


def is_cockpit(obj):
    return obj.get("role") == "cockpit_view"


def selected(icarus, item, key):
    """The objects one selector of a BUDGET item ("objects", "exact" or "family") picks among those measure counts:
    meshes, or for a reference_triangles item the objects carrying that property."""
    from parts import families

    names = tuple(item.get(key, ()))
    if item.get("reference_triangles"):
        pool = [o for o in icarus.all_objects if "reference_triangles" in o]
    elif "face_attribute" in item:
        pool = [o for o in meshes(icarus) if o.data.attributes.get(item["face_attribute"])]
    else:
        pool = meshes(icarus)
    match = {"objects": lambda o: o.name.startswith(names), "exact": lambda o: o.name in names,
             "family": lambda o: bool(families(o) & set(names))}[key]
    return [o for o in pool if names and match(o)]


def measure(icarus, item):
    """Triangles one BUDGET item counts on the built aircraft."""
    if "collection" in item:
        col = bpy.data.collections.get(item["collection"])
        return sum(tris(o) for o in col.objects if o.type == "MESH") if col else 0
    objs = {o for key in ("objects", "exact", "family") for o in selected(icarus, item, key)}
    if item.get("reference_triangles"):
        return sum(o.get("reference_triangles", 0) for o in objs)
    if "face_attribute" in item:
        return sum(len(f.vertices) - 2 for o in objs for f in o.data.polygons
                   if o.data.attributes[item["face_attribute"]].data[f.index].value)
    return sum(tris(o) for o in objs)


def over_caps(icarus, budget):
    """The components of one module's BUDGET above their caps, and those with a selector ("objects", "exact" or
    "family") naming something that matches nothing measure counts, as text; a module's check() raises on any. A prefix
    or name that stops matching after a rename would count 0 and pass every cap. An empty selector is a reservation
    (cockpit.py's stock_hotas) and passes."""
    out = []
    for name, item in budget.items():
        if "collection" not in item:
            out += ["%s: %s %s matches nothing" % (name, key, tuple(item[key])) for key in ("objects", "exact", "family")
                    if item.get(key) and not selected(icarus, item, key)]
        if measure(icarus, item) > item["cap"]:
            out.append("%s %d > %d" % (name, measure(icarus, item), item["cap"]))
    return out


def report(icarus):
    exterior = [o for o in meshes(icarus) if not is_cockpit(o)]
    cockpit = [o for o in meshes(icarus) if is_cockpit(o)]
    hulls = [o for o in bpy.data.collections["LOD1"].objects] if "LOD1" in bpy.data.collections else []
    colliders = [o for o in bpy.data.collections["Colliders"].objects] if "Colliders" in bpy.data.collections else []
    twins = sum(skin_tris(o) for o in exterior if o not in hulls and o not in colliders)
    lines = ["budget: exterior LOD0 %d triangles drawn (%d modelled, %d skin twins) on %d renderers; cockpit %d on %d"
             % (sum(map(tris, exterior)) + twins, sum(map(tris, exterior)), twins, len(exterior),
                sum(map(tris, cockpit)), len(cockpit))]

    per_mat = {}
    for o in exterior:
        names = [m.name if m else "" for m in o.data.materials]
        for f in o.data.polygons:
            name = names[f.material_index] if names else ""
            per_mat[name] = per_mat.get(name, 0) + len(f.vertices) - 2
    total = max(1, sum(per_mat.values()))
    lines.append("materials (%d static): %s" % (len(per_mat), ", ".join(
        "%s %d" % (n, c) for n, c in sorted(per_mat.items(), key=lambda kv: -kv[1]))))
    skin = per_mat.get("Icarus_Body", 0) + twins
    trim = sum(per_mat.get(n, 0) for n in TRIMS)
    lines.append("skin %d (limit %d)%s; trim share %.0f%% (%.0f to %.0f%%)%s" % (
        skin, SKIN_MAX, " OVER" if skin > SKIN_MAX else "", 100 * trim / total, 100 * TRIM_SHARE[0],
        100 * TRIM_SHARE[1], "" if TRIM_SHARE[0] <= trim / total <= TRIM_SHARE[1] else " OUT"))

    sums = {False: [0, 0], True: [0, 0]}
    lines.append("components (module: component today / target / cap):")
    for module in bi.modules():
        for name, item in module.BUDGET.items():
            today = measure(icarus, item)
            flag = " OVER" if today > item["cap"] else ""
            lines.append("  %s: %s %d / %d / %d%s" % (module.__name__, name, today, item["target"], item["cap"], flag))
            if "collection" not in item:
                sums[bool(item.get("cockpit"))][0] += item["target"]
                sums[bool(item.get("cockpit"))][1] += item["cap"]
    lines.append("exterior budgets sum to target %d, cap %d (global target %d, hard limit %d); cockpit to target %d, "
                 "cap %d (hard limit %d)" % (sums[False][0], sums[False][1], EXTERIOR[0], EXTERIOR[1],
                                            sums[True][0], sums[True][1], COCKPIT_MAX))

    lines.append("LOD1 %d hulls, %d triangles, largest %d (limits %d per hull, %d total); colliders %d hulls, %d triangles"
                 % (len(hulls), sum(map(tris, hulls)), max(map(tris, hulls), default=0), LOD1_PER_HULL, LOD1_TOTAL,
                    len(colliders), sum(map(tris, colliders))))
    lines.append("parts: " + ", ".join("%s %d" % (o.name, tris(o)) for o in sorted(exterior + cockpit, key=lambda o: o.name)))
    return "\n".join(lines)
