// Fo4Land: second, independent decode of Fallout 4 LAND heights for a cell range, through Mutagen's record parser.
// Used to cross-check scripts/terrain/fo4_land_patch.py (our own plugin walker + VHGT decoder). Output is JSON in
// FO4 units; it stays outside the repository (it is derived game data).
//
//   dotnet run --project dotnet/Fo4Land -- <Fallout4.esm> <WorldEditorId> <xmin> <ymin> <xmax> <ymax> <out.json>
//   dotnet run --project dotnet/Fo4Land -- <Fallout4.esm> export-exterior <WorldEditorId> <xmin> <ymin> <xmax> <ymax> <out.json>
//       exterior references as schema v2 placement JSON (ExteriorExport.cs; terrain experiment 2c)
//
// VHGT layout as documented by fo76utils' fo4land (landdata.cpp): float offset, 33x33 signed byte gradients (row 0 =
// south, column 0 = west; a row's first byte continues from the previous row's first vertex, the others from the
// west neighbour), height = 8 * (offset + accumulated gradient). Mutagen only parses the bytes; the decode is ours.
using System.Text.Json;
using Mutagen.Bethesda;
using Mutagen.Bethesda.Fallout4;

if (args.Length >= 2 && args[1] == "export-exterior") return ExteriorExport.Run(args);
if (args.Length != 7)
{
    Console.Error.WriteLine("usage: Fo4Land <Fallout4.esm> <WorldEditorId> <xmin> <ymin> <xmax> <ymax> <out.json>");
    return 2;
}
int xmin = int.Parse(args[2]), ymin = int.Parse(args[3]), xmax = int.Parse(args[4]), ymax = int.Parse(args[5]);
using var mod = Fallout4Mod.CreateFromBinaryOverlay(args[0], Fallout4Release.Fallout4);
var world = mod.Worldspaces.FirstOrDefault(w => w.EditorID == args[1]);
if (world is null)
{
    Console.Error.WriteLine($"worldspace {args[1]} not found");
    return 1;
}

bool InRange(int x, int y) => x >= xmin && x <= xmax && y >= ymin && y <= ymax;
static string Fid(Mutagen.Bethesda.Plugins.FormKey k) => k.ID.ToString("X8");

object RefJson(IPlacedGetter p)
{
    Noggog.P3Float? pos = p switch { IPlacedObjectGetter o => o.Position, IPlacedNpcGetter n => n.Position, _ => null };
    var baseKey = p switch
    {
        IPlacedObjectGetter o => Fid(o.Base.FormKey),
        IPlacedNpcGetter n => Fid(n.Base.FormKey),
        _ => null,
    };
    return new { fid = Fid(p.FormKey), @base = baseKey, pos = pos is { } v ? new[] { v.X, v.Y, v.Z } : null };
}

var cells = new List<object>();
foreach (var block in world.SubCells)
foreach (var sub in block.Items)
foreach (var cell in sub.Items)
{
    if (cell.Grid is not { } grid || !InRange(grid.Point.X, grid.Point.Y)) continue;
    var vh = cell.Landscape?.VertexHeightMap;
    double[][]? heights = null;
    if (vh is not null)
    {
        var hm = vh.HeightMap;
        heights = new double[33][];
        int rowStart = 0;
        for (int r = 0; r < 33; r++)
        {
            heights[r] = new double[33];
            rowStart += unchecked((sbyte)hm[0, r]);
            int z = rowStart;
            heights[r][0] = 8.0 * (vh.Offset + z);
            for (int c = 1; c < 33; c++)
            {
                z += unchecked((sbyte)hm[c, r]);
                heights[r][c] = 8.0 * (vh.Offset + z);
            }
        }
    }
    cells.Add(new
    {
        x = grid.Point.X,
        y = grid.Point.Y,
        cell = Fid(cell.FormKey),
        land = cell.Landscape is { } l ? Fid(l.FormKey) : null,
        offset = vh?.Offset,
        heights,
        refs = cell.Temporary.Select(RefJson).ToList(),
    });
}

var persistent = new List<object>();
if (world.TopCell is { } top)
{
    foreach (var p in top.Persistent)
    {
        if (p is IPlacedObjectGetter o && o.Position is var pl &&
            InRange((int)Math.Floor(pl.X / 4096.0), (int)Math.Floor(pl.Y / 4096.0)))
            persistent.Add(RefJson(p));
    }
}

var doc = new { world = args[1], world_fid = Fid(world.FormKey), cells, persistent };
File.WriteAllText(args[6], JsonSerializer.Serialize(doc, new JsonSerializerOptions { WriteIndented = false }));
Console.WriteLine($"cells {cells.Count}, persistent refs in range {persistent.Count} -> {args[6]}");
return 0;

