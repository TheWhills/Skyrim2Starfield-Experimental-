// Plugin writer for converted assets (S2 -> WP-08 / WP-10).
//   dotnet run -- <output dir> <manifest.json> [cell.json ...]
// Creates FO4Port.esm with one STAT per converted item and, for each cell export from dotnet/Fo4Export, an interior cell
// "FO4Port_<cell>" holding every reference whose model was converted, placed at the Fallout 4 position / 70 (metres), same rotation
// (radians) and scale. Initially-disabled FO4 references stay initially disabled.
//
// FormIDs are STABLE: <output dir>/formids.json maps an identity key to its FormID and is reused on every run, so adding or
// removing assets never renumbers existing records (saves and cross-references keep working). Keys:
//   STAT:<editor id>   CELL:<cell name>   REFR:<cell name>:<source FO4 FormKey>   (lights and COC markers use their source ref)
using System.Text.Json;
using Mutagen.Bethesda.Plugins;
using Mutagen.Bethesda.Plugins.Records;
using Mutagen.Bethesda.Starfield;
using Noggog;

const float UnitsPerMetre = 70f;
const uint FirstId = 0x800;
var outDir = args[0];
Directory.CreateDirectory(outDir);

var modKey = ModKey.FromNameAndExtension("FO4Port.esm");
var sfEsm = ModKey.FromNameAndExtension("Starfield.esm");
var release = StarfieldRelease.Starfield;
var mod = new StarfieldMod(modKey, release);
mod.ModHeader.Flags |= StarfieldModHeader.HeaderFlag.Master;

// ---- stable FormID map ------------------------------------------------------------------------------------------------
var mapPath = Path.Combine(outDir, "formids.json");
var ids = File.Exists(mapPath)
    ? JsonSerializer.Deserialize<Dictionary<string, uint>>(File.ReadAllText(mapPath))!
    : new Dictionary<string, uint>();
var next = ids.Count == 0 ? FirstId : ids.Values.Max() + 1;
var usedThisRun = new HashSet<string>();
FormKey Id(string key)
{
    if (!usedThisRun.Add(key)) throw new InvalidOperationException($"duplicate identity key {key}");
    if (!ids.TryGetValue(key, out var v)) { v = next++; ids[key] = v; }
    return new FormKey(modKey, v);
}

// ---- statics ----------------------------------------------------------------------------------------------------------
var items = new List<(string editorId, string model, string source, JsonElement? door)>();
using var manifestDoc = JsonDocument.Parse(File.ReadAllText(args[1]));
foreach (var it in manifestDoc.RootElement.GetProperty("items").EnumerateArray())
    items.Add((it.GetProperty("editor_id").GetString()!, it.GetProperty("model").GetString()!, it.GetProperty("source").GetString()!,
               it.TryGetProperty("door", out var dj) ? dj : null));

// source FO4 model -> (base record, origin offset in metres). Hinged doors become DOOR records animated by a vanilla door's
// graph / skeleton / animations; their NIF origin sits at a different point, so references are shifted by origin_offset.
var bySource = new Dictionary<string, (FormKey key, P3Float offset)>(StringComparer.OrdinalIgnoreCase);
int doors = 0;
foreach (var (editorId, model, source, door) in items)
{
    if (door is JsonElement d)
    {
        var rec = new Door(Id("DOOR:" + editorId), release)
        {
            // FO4PORT_DOOR_MODEL (test hook): use this model for every door, e.g. the vanilla template door's own NIF
            EditorID = editorId, Model = new Model { File = Environment.GetEnvironmentVariable("FO4PORT_DOOR_MODEL") ?? model },
            Name = "Door",
            SoundLevel = SoundLevel.Normal,                                     // DEVT 1, as vanilla doors
            FacingAxisOverride = Door.FacingAxisOverrideEnum.BasedOnBounds,     // trailing ANAM, as vanilla doors
        };
        if (d.TryGetProperty("bounds", out var bj))                            // vanilla doors have real bounds
            rec.ObjectBounds = new ObjectBounds
            {
                First = new P3Float(bj[0][0].GetSingle(), bj[0][1].GetSingle(), bj[0][2].GetSingle()),
                Second = new P3Float(bj[1][0].GetSingle(), bj[1][1].GetSingle(), bj[1][2].GetSingle()),
            };
        rec.Components.Add(new AnimationGraphComponent
        {
            ANAM = d.GetProperty("anim_graph").GetString(), BNAM = d.GetProperty("skeleton").GetString(),
            CNAM = d.GetProperty("animations").GetString(),
        });
        mod.Doors.Add(rec);
        var o = d.GetProperty("origin_offset");
        bySource[source.Replace('/', '\\')] = (rec.FormKey, new P3Float(o[0].GetSingle(), o[1].GetSingle(), o[2].GetSingle()));
        if (Environment.GetEnvironmentVariable("FO4PORT_DOOR_BASE") is string vb)   // test hook: place a vanilla DOOR instead
            bySource[source.Replace('/', '\\')] = (new FormKey(sfEsm, Convert.ToUInt32(vb, 16)), new P3Float(0, 0, 0));
        doors++;
        continue;
    }
    var stat = new Static(Id("STAT:" + editorId), release) { EditorID = editorId, Model = new Model { File = model } };
    mod.Statics.Add(stat);
    bySource[source.Replace('/', '\\')] = (stat.FormKey, new P3Float(0, 0, 0));
}
Console.WriteLine($"{items.Count - doors} statics, {doors} doors");

// FO4 / Starfield reference rotation (radians): Bethesda angles turn CLOCKWISE seen from the positive axis, so the matrix
// uses the negated angles; applied X, then Y, then Z. Rotates a door-local offset into the cell. (0 / 180 degree doors are
// the same either way; the 135 / 225 degree double doors in Parsons looked misplaced with the counter-clockwise version.
// To verify in game.)
static P3Float RotateOffset(P3Float v, P3Float r, float scale)
{
    double cx = Math.Cos(-r.X), sx = Math.Sin(-r.X), cy = Math.Cos(-r.Y), sy = Math.Sin(-r.Y), cz = Math.Cos(-r.Z), sz = Math.Sin(-r.Z);
    double x = v.X * scale, y = v.Y * scale, z = v.Z * scale;
    double y1 = y * cx - z * sx, z1 = y * sx + z * cx;           // about X
    double x2 = x * cy + z1 * sy, z2 = -x * sy + z1 * cy;          // about Y
    double x3 = x2 * cz - y1 * sz, y3 = x2 * sz + y1 * cz;         // about Z
    return new P3Float((float)x3, (float)y3, (float)z2);
}

// Optional per-cell lighting overrides: <output dir>/lighting.json = { "<cell>": { "LIGHTING_TEMPLATE": "06BCF8", ... },
// "*": { ...defaults for every cell... } }. Keys: LIGHTING_TEMPLATE, IMAGE_SPACE, OMNI_LIGHT, LIGHT_MERGE_M.
// Lookup order: cell entry, "*" entry, environment variable, built-in default.
var lightCfgPath = Path.Combine(outDir, "lighting.json");
var lightCfg = File.Exists(lightCfgPath)
    ? JsonSerializer.Deserialize<Dictionary<string, Dictionary<string, string>>>(File.ReadAllText(lightCfgPath))!
    : new Dictionary<string, Dictionary<string, string>>();
string Setting(string cell, string key, string fallback) =>
    lightCfg.TryGetValue(cell, out var c) && c.TryGetValue(key, out var v) ? v
    : lightCfg.TryGetValue("*", out var d) && d.TryGetValue(key, out var w) ? w
    : Environment.GetEnvironmentVariable(key) ?? fallback;

// ---- cells ------------------------------------------------------------------------------------------------------------
P3Float Pos(JsonElement p) => new(p[0].GetSingle() / UnitsPerMetre, p[1].GetSingle() / UnitsPerMetre, p[2].GetSingle() / UnitsPerMetre);
P3Float Rot(JsonElement o) => new(o[0].GetSingle(), o[1].GetSingle(), o[2].GetSingle());

foreach (var cellPath in args.Skip(2))
{
    using var cdoc = JsonDocument.Parse(File.ReadAllText(cellPath));
    var root = cdoc.RootElement;
    var src4 = root.GetProperty("cell").GetString()!;
    var cellName = "FO4Port_" + src4;
    var cell = new Cell(Id("CELL:" + cellName), release) { EditorID = cellName, Flags = Cell.Flag.IsInteriorCell };
    var ltHex = Setting(src4, "LIGHTING_TEMPLATE", "06BCF8");   // KreetBase01LGTtemplate (underground); ShipInteriorLT 006658 is brighter
    cell.LightingTemplate.SetTo(new FormKey(sfEsm, Convert.ToUInt32(ltHex, 16)));
    // exposure + reflections like the vanilla underground interior DR017UndergroundInterior (25CAA7): without these the cell
    // reflects a bright default sky and auto-exposure washes everything out
    cell.ImageSpace.SetTo(new FormKey(sfEsm, Convert.ToUInt32(Setting(src4, "IMAGE_SPACE", "122393"), 16)));
    cell.EnvironmentMap = Environment.GetEnvironmentVariable("ENV_MAP") ?? "Data\\Textures\\cubemaps\\blackcube.dds";
    var cocMarker = new FormKey(sfEsm, 0x000032);                                        // COCMarkerHeading
    var omni = new FormKey(sfEsm, Convert.ToUInt32(Setting(src4, "OMNI_LIGHT", "03D38C"), 16)); // LGT_ShipInterior_Omni_NS_Neutral_2k
    var merge = float.Parse(Setting(src4, "LIGHT_MERGE_M", "3"), System.Globalization.CultureInfo.InvariantCulture);
    var lit = new List<P3Float>();
    int lights = 0, placed = 0, skipped = 0, disabled = 0;
    foreach (var r in root.GetProperty("refs").EnumerateArray())
    {
        var src = r.GetProperty("formkey").GetString()!;
        var model = r.GetProperty("model").GetString() ?? "";
        PlacedObject? obj = null;
        if (r.GetProperty("base_editor_id").GetString() == "COCMarkerHeading")            // arrival point for `coc`
        {
            obj = new PlacedObject(Id($"REFR:{cellName}:{src}"), release)
                { Base = new FormLinkNullable<IPlaceableObjectGetter>(cocMarker), Position = Pos(r.GetProperty("pos")), Rotation = Rot(r.GetProperty("rot")) };
        }
        else if (r.GetProperty("type").GetString() == "Light")
        {
            if (Environment.GetEnvironmentVariable("FO4PORT_NO_LIGHTS") == "1") continue;
            var pos = Pos(r.GetProperty("pos"));
            if (lit.Any(q => Math.Abs(q.X - pos.X) < merge && Math.Abs(q.Y - pos.Y) < merge && Math.Abs(q.Z - pos.Z) < merge)) continue;
            lit.Add(pos);
            obj = new PlacedObject(Id($"REFR:{cellName}:{src}"), release) { Base = new FormLinkNullable<IPlaceableObjectGetter>(omni), Position = pos };
            lights++;
        }
        else
        {
            if (model.Length == 0 || !bySource.TryGetValue("meshes\\" + model.TrimStart('\\'), out var bas)) { skipped++; continue; }
            var scale = r.GetProperty("scale").GetSingle();
            var rot = Rot(r.GetProperty("rot"));
            var pos = Pos(r.GetProperty("pos"));
            var off = RotateOffset(bas.offset, rot, scale);
            obj = new PlacedObject(Id($"REFR:{cellName}:{src}"), release)
            {
                Base = new FormLinkNullable<IPlaceableObjectGetter>(bas.key),
                Position = new P3Float(pos.X + off.X, pos.Y + off.Y, pos.Z + off.Z),
                Rotation = rot,
            };
            if (Math.Abs(scale - 1f) > 1e-4) obj.Scale = scale;
            placed++;
        }
        if (r.TryGetProperty("disabled", out var dis) && dis.GetInt32() != 0)
        {
            obj.MajorRecordFlagsRaw |= 0x800;                                              // Initially Disabled, as in FO4
            disabled++;
        }
        cell.Temporary.Add(obj);
    }
    var cid = cell.FormKey.ID;
    var block = new CellBlock { BlockNumber = (int)(cid % 10), GroupType = GroupTypeEnum.InteriorCellBlock };
    var sub = new CellSubBlock { BlockNumber = (int)((cid / 10) % 10), GroupType = GroupTypeEnum.InteriorCellSubBlock };
    sub.Cells.Add(cell);
    block.SubBlocks.Add(sub);
    mod.Cells.Records.Add(block);
    Console.WriteLine($"cell {cellName} {cell.FormKey}: placed {placed} references + {lights} lights ({disabled} initially disabled), skipped {skipped}");
}

// ---- door test cell (FO4PORT_DOORTEST=<door editor id>) ------------------------------------------------------------------
// One 8x8 m vanilla platform, the converted door at the origin (facing +X like an FO4 door with no rotation), the vanilla
// Akila door 0AA24A 3 m to the side for comparison, and a COC marker 1.5 m in front of the converted door, facing it.
if (Environment.GetEnvironmentVariable("FO4PORT_DOORTEST") is string testDoor)
{
    var cell = new Cell(Id("CELL:FO4Port_DoorTest"), release) { EditorID = "FO4Port_DoorTest", Flags = Cell.Flag.IsInteriorCell };
    cell.LightingTemplate.SetTo(new FormKey(sfEsm, 0x006658));
    cell.ImageSpace.SetTo(new FormKey(sfEsm, 0x122393));
    cell.EnvironmentMap = "Data\\Textures\\cubemaps\\blackcube.dds";
    var entry = items.First(i => i.editorId == testDoor);
    var (doorKey, doorOff) = bySource[entry.source.Replace('/', '\\')];
    PlacedObject P(string key, FormKey b, P3Float pos, P3Float rot) =>
        new(Id("REFR:FO4Port_DoorTest:" + key), release) { Base = new FormLinkNullable<IPlaceableObjectGetter>(b), Position = pos, Rotation = rot };
    var zero = new P3Float(0, 0, 0);
    cell.Temporary.Add(P("floor", new FormKey(sfEsm, 0x050776), new P3Float(-2, 0, 0), zero));  // NA_Transit_PlatformA_Str08x08_01: x -2..6, top z 0
    cell.Temporary.Add(P("door", doorKey, doorOff, zero));
    cell.Temporary.Add(P("vanilla", new FormKey(sfEsm, 0x0AA24A), new P3Float(0, 3, 0), zero));
    cell.Temporary.Add(P("coc", new FormKey(sfEsm, 0x000032), new P3Float(-1.5f, 0, 0.1f), new P3Float(0, 0, (float)(Math.PI / 2))));
    cell.Temporary.Add(P("light", new FormKey(sfEsm, 0x03D38C), new P3Float(-1, 1.5f, 3), zero));
    var cid = cell.FormKey.ID;
    var block = new CellBlock { BlockNumber = (int)(cid % 10), GroupType = GroupTypeEnum.InteriorCellBlock };
    var sub = new CellSubBlock { BlockNumber = (int)((cid / 10) % 10), GroupType = GroupTypeEnum.InteriorCellSubBlock };
    sub.Cells.Add(cell);
    block.SubBlocks.Add(sub);
    mod.Cells.Records.Add(block);
    Console.WriteLine($"door test cell {cell.FormKey} with {testDoor}");
}

mod.ModHeader.Stats.NextFormID = next;
var path = Path.Combine(outDir, modKey.FileName);
var sfData = Environment.GetEnvironmentVariable("STARFIELD_DATA") ?? throw new InvalidOperationException("set STARFIELD_DATA to the Starfield Data folder");
mod.BeginWrite.ToPath(path).WithLoadOrderFromHeaderMasters().WithDataFolder(sfData)
    .WithKnownMasters(new KeyedMasterStyle(sfEsm, MasterStyle.Full))
    .Write();
File.WriteAllText(mapPath, JsonSerializer.Serialize(ids.OrderBy(kv => kv.Value).ToDictionary(kv => kv.Key, kv => kv.Value),
    new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine($"wrote {path} ({new FileInfo(path).Length:N0} bytes); {ids.Count} stable FormIDs in {mapPath}");
