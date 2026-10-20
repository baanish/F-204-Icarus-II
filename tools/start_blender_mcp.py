"""Enable the Blender Lab MCP extension in a GUI session and start its socket server."""
import addon_utils
import bpy

MODULE = "bl_ext.lab_blender_org.mcp"


def start():
    try:
        bpy.ops.blmcp.server_start()
        print("icarus: MCP server started")
    except Exception as ex:  # report and keep Blender open
        print("icarus: MCP server start failed:", ex)
    return None


addon_utils.enable(MODULE, default_set=True, persistent=True)
bpy.app.timers.register(start, first_interval=2.0)
