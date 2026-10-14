using Mutagen.Bethesda.Plugins;
using Mutagen.Bethesda.Plugins.Binary.Parameters;
using Mutagen.Bethesda.Plugins.Records;
using Mutagen.Bethesda.Starfield;
using Noggog;

public static class PluginReader
{
    public static StarfieldMod Read(string path)
    {
        // PluginSpike currently emits standalone FO4Port with Starfield.esm as its only external master.
        // Unknown masters are intentionally not assigned a guessed light/medium/full style.
        var masters = new Cache<IModMasterStyledGetter, ModKey>(x => x.ModKey);
        masters.Set(new KeyedMasterStyle(ModKey.FromNameAndExtension("Starfield.esm"), MasterStyle.Full));
        return StarfieldMod.CreateFromBinary(path, StarfieldRelease.Starfield,
            new BinaryReadParameters { MasterFlagsLookup = masters });
    }
}
