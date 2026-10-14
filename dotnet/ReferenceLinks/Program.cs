using System.Text.Json;
using Mutagen.Bethesda.Plugins;
using Mutagen.Bethesda.Plugins.Records;
using Mutagen.Bethesda.Starfield;

if (args.Length < 4)
{
    Console.Error.WriteLine("usage: <input.esm> <formids.json> <output dir> <cell.json...> [--report-only] [--allow-unresolved]");
    Environment.ExitCode = 1;
    return;
}
var mod = PluginReader.Read(args[0]);
var output = Path.Combine(args[2], mod.ModKey.FileName);
if (Path.GetFullPath(output).Equals(Path.GetFullPath(args[0]), StringComparison.OrdinalIgnoreCase))
    throw new InvalidOperationException("output must be separate from the input plugin");
if (File.Exists(output)) throw new InvalidOperationException("output plugin already exists; use a fresh output directory");
var ids = JsonSerializer.Deserialize<Dictionary<string, uint>>(File.ReadAllText(args[1]))!;
var exports = args.Skip(3).Where(p => !p.StartsWith("--")).Select(p => JsonDocument.Parse(File.ReadAllText(p))).ToArray();
try
{
    var data = Environment.GetEnvironmentVariable("STARFIELD_DATA");
    Dictionary<string, FormKey>? markerBases = null;
    if (data != null && !args.Contains("--no-markers"))
    {
        using var vanilla = StarfieldMod.CreateFromBinaryOverlay(Path.Combine(data, "Starfield.esm"), StarfieldRelease.Starfield);
        var names = new HashSet<string>(new[] { "EnableMarker", "XMarker", "XMarkerHeading", "LightBox" }, StringComparer.OrdinalIgnoreCase);
        markerBases = vanilla.Statics.Where(s => s.EditorID != null && names.Contains(s.EditorID))
            .ToDictionary(s => s.EditorID!, s => s.FormKey, StringComparer.OrdinalIgnoreCase);
    }
    var report = Relationships.Apply(mod, ids, exports.Select(x => x.RootElement), markerBases);
    Directory.CreateDirectory(args[2]);
    var statePath = Path.Combine(args[2], "build-state.json");
    File.WriteAllText(statePath, JsonSerializer.Serialize(new { complete = false, status = "relationship_translation", unresolved = report.Issues.Count }));
    File.WriteAllText(Path.Combine(args[2], "relationships-report.json"), JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
    Console.WriteLine($"markers={report.CreatedMarkers}, keywords={report.CreatedKeywords}, persistent={report.Persistent}, enable parents={report.EnableParents}, linked refs={report.LinkedReferences}, teleports={report.Teleports}, issues={report.Issues.Count}");
    if (report.Issues.Count > 0 && !args.Contains("--allow-unresolved")) { Environment.ExitCode = 2; return; }
    if (args.Contains("--report-only")) return;
    if (data == null) throw new InvalidOperationException("set STARFIELD_DATA");
    mod.BeginWrite.ToPath(output).WithLoadOrderFromHeaderMasters().WithDataFolder(data)
        .WithKnownMasters(new KeyedMasterStyle(ModKey.FromNameAndExtension("Starfield.esm"), MasterStyle.Full)).Write();
    File.WriteAllText(Path.Combine(args[2], "formids.json"), JsonSerializer.Serialize(ids, new JsonSerializerOptions { WriteIndented = true }));
    File.WriteAllText(statePath, JsonSerializer.Serialize(new { complete = true, status = "relationships_written", unresolved = report.Issues.Count,
        fidelity = report.Issues.Count == 0 ? "resolved_exported_relationships" : "partial_explicitly_allowed" }));
    Console.WriteLine($"wrote {output}; input was unchanged");
}
finally { foreach (var export in exports) export.Dispose(); }
