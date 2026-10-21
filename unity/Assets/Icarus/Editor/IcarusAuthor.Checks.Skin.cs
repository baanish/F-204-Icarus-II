using System.Collections.Generic;

namespace Icarus.Editor
{
    public static partial class IcarusAuthor
    {
        // A13: every renderer wearing the skin has it at slot 0 and is listed in its part's damageMaterial.renderers.
        // Nothing is measured yet.
        private static string CheckSkin(Build b, List<string> p) => "not built";
    }
}
